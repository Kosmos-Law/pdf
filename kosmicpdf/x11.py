"""A few requests to the X11 window manager that Qt doesn't make for us, sent through
libX11 directly (standard library only, so a launch that just hands its files to the
running copy stays quick). Each quietly does nothing where there is no X display, such
as under Wayland, or if libX11 can't be loaded.
"""
import ctypes
import os

SUBSTRUCTURE = (1 << 19) | (1 << 20)     # SubstructureNotifyMask | SubstructureRedirectMask
PROPERTY_CHANGE = 1 << 22                # PropertyChangeMask
FROM_PAGER = 2                           # EWMH source indication: a pager, workspace switcher or the like
ALL_DESKTOPS = 0xFFFFFFFF                # _NET_WM_DESKTOP of a window shown on every workspace


class _Data(ctypes.Union):
    _fields_ = [("b", ctypes.c_char * 20), ("l", ctypes.c_long * 5)]


class _ClientMessage(ctypes.Structure):   # XClientMessageEvent, padded to the size of an XEvent
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", _Data), ("pad", ctypes.c_long * 24)]


def _libx11():
    if not os.environ.get("DISPLAY"):
        return None
    try:
        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XCreateSimpleWindow.restype = ctypes.c_ulong
    x11.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_int] * 2 + [ctypes.c_uint] * 3 \
        + [ctypes.c_ulong] * 2
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
    x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
                                       ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                       ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x11


def _cardinal(x11, dpy, window, name):
    """A window's CARDINAL property (e.g. which workspace it's on), or None."""
    atom = x11.XInternAtom(dpy, name, 0)
    kind, fmt, n, rest, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
    ok = x11.XGetWindowProperty(dpy, window, atom, 0, 1, 0, 6, ctypes.byref(kind), ctypes.byref(fmt),   # 6 = XA_CARDINAL
                                ctypes.byref(n), ctypes.byref(rest), ctypes.byref(data))
    value = None
    if ok == 0 and data.value:
        if fmt.value == 32 and n.value:
            value = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0] & 0xFFFFFFFF   # format 32 is stored as longs
        x11.XFree(data)
    return value


def _message(x11, dpy, target, window, name, fmt, mask, data):
    ev = _ClientMessage(type=33, send_event=1, display=dpy, window=window, format=fmt,   # 33 = ClientMessage
                        message_type=x11.XInternAtom(dpy, name, 0))
    if fmt == 8:
        ev.data.b = data
    else:
        ev.data.l = (ctypes.c_long * 5)(*data)
    x11.XSendEvent(dpy, target, 0, mask, ctypes.byref(ev))


def finish_startup_notification(startup_id):
    """Tell the desktop that a launch is done, for one that handed its files on and so
    never shows a window of its own. Without this the busy cursor the Menu or file
    manager started would spin until it timed out. (Qt does this itself when a window
    is shown.) X11's startup-notification protocol: a "remove" message sent to the
    root window in 20-byte pieces."""
    x11 = _libx11() if startup_id else None
    dpy = x11.XOpenDisplay(None) if x11 else None
    if not dpy:
        return
    root = x11.XDefaultRootWindow(dpy)
    sender = x11.XCreateSimpleWindow(dpy, root, -100, -100, 1, 1, 0, 0, 0)
    if any(c in startup_id for c in ' "\\'):
        startup_id = '"' + startup_id.replace("\\", "\\\\").replace('"', '\\"') + '"'
    message = f"remove: ID={startup_id}".encode() + b"\0"
    for n in range(0, len(message), 20):
        _message(x11, dpy, root, sender, b"_NET_STARTUP_INFO_BEGIN" if n == 0 else b"_NET_STARTUP_INFO", 8,
                 PROPERTY_CHANGE, message[n:n + 20].ljust(20, b"\0"))
    x11.XDestroyWindow(dpy, sender)
    x11.XCloseDisplay(dpy)                                       # flushes the messages


def on_current_workspace(window):
    """Whether a top-level window is on the workspace the user is on (or on every
    workspace); None where that can't be told."""
    x11 = _libx11()
    dpy = x11.XOpenDisplay(None) if x11 else None
    if not dpy:
        return None
    here = _cardinal(x11, dpy, x11.XDefaultRootWindow(dpy), b"_NET_CURRENT_DESKTOP")
    there = _cardinal(x11, dpy, window, b"_NET_WM_DESKTOP")
    x11.XCloseDisplay(dpy)
    if here is None or there is None:
        return None
    return there in (here, ALL_DESKTOPS)


def bring_to_current_workspace(window):
    """Move a top-level window to the workspace the user is on, and give it the focus,
    as `wmctrl -R` does. Used when a file opened elsewhere (say, double-clicked in the
    file manager) goes to a window that may be on another workspace. The requests are
    sent as a workspace switcher would send them: the window manager refuses an
    application's own request for the focus while another program has it. A window
    shown on every workspace stays so."""
    x11 = _libx11()
    dpy = x11.XOpenDisplay(None) if x11 else None
    if not dpy:
        return
    root = x11.XDefaultRootWindow(dpy)
    here = _cardinal(x11, dpy, root, b"_NET_CURRENT_DESKTOP")
    there = _cardinal(x11, dpy, window, b"_NET_WM_DESKTOP")
    if here is not None and there not in (here, ALL_DESKTOPS):
        _message(x11, dpy, root, window, b"_NET_WM_DESKTOP", 32, SUBSTRUCTURE, [here, FROM_PAGER, 0, 0, 0])
    _message(x11, dpy, root, window, b"_NET_ACTIVE_WINDOW", 32, SUBSTRUCTURE, [FROM_PAGER, 0, 0, 0, 0])
    x11.XCloseDisplay(dpy)                                       # flushes the requests
