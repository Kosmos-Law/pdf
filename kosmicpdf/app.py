"""Entry point. One process per user: launching again (e.g. double-clicking a PDF
in the file manager) hands the files to the running instance, so every document
lives in one process and tabs and pages can be dragged between all windows.

Startup is arranged so something appears quickly. A launch that only hands files
to the running copy does so before loading Qt. A first launch shows its window
before PyMuPDF is loaded and the document is opened (see MainWindow.open_when_shown).
"""
import ctypes
import importlib.util
import json
import os
import socket
import sys
import tempfile
import types

from . import __version__

# The single-instance handoff uses a plain Unix socket (Python's socket module rather
# than QtNetwork, which needs Kerberos libraries the Flatpak runtime doesn't ship).
# Inside a Flatpak each launch gets its own /tmp, so the socket goes in the app's
# runtime folder, which all of its sandboxed copies share.
FLATPAK_ID = os.environ.get("FLATPAK_ID")
# --dev marks the development copy (./install.sh --dev): its own name, grey icon and
# socket, so it runs alongside the installed app instead of handing files to it.
DEV = "--dev" in sys.argv
_runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
if FLATPAK_ID:
    SOCKET_PATH = os.path.join(_runtime, "app", FLATPAK_ID, "kosmicpdf.sock")
else:
    SOCKET_PATH = os.path.join(_runtime, f"kosmicpdf{'-dev' if DEV else ''}-{os.getuid()}.sock")


def send_to_running(files):
    """Hand files to an already-running Kosmic PDF. False if none is running."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(SOCKET_PATH)
        s.sendall(json.dumps(files).encode())
        return True
    except OSError:
        return False
    finally:
        s.close()


def finish_startup_notification():
    """Tell the desktop this launch is done, for a launch that handed its files on and
    so never shows a window of its own. Without this the busy cursor the Menu or file
    manager started would spin until it timed out. (Qt does this itself when a window
    is shown.) X11's startup-notification protocol: a "remove" message sent to the
    root window in 20-byte pieces."""
    startup_id = os.environ.pop("DESKTOP_STARTUP_ID", "")
    if not startup_id or not os.environ.get("DISPLAY"):
        return
    try:
        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return
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
    x11.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    class Data(ctypes.Union):
        _fields_ = [("b", ctypes.c_char * 20), ("l", ctypes.c_long * 5)]

    class ClientMessage(ctypes.Structure):   # XClientMessageEvent, padded to the size of an XEvent
        _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                    ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                    ("format", ctypes.c_int), ("data", Data), ("pad", ctypes.c_long * 24)]

    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return
    root = x11.XDefaultRootWindow(dpy)
    sender = x11.XCreateSimpleWindow(dpy, root, -100, -100, 1, 1, 0, 0, 0)
    if any(c in startup_id for c in ' "\\'):
        startup_id = '"' + startup_id.replace("\\", "\\\\").replace('"', '\\"') + '"'
    message = f"remove: ID={startup_id}".encode() + b"\0"
    for n in range(0, len(message), 20):
        ev = ClientMessage(type=33, send_event=1, display=dpy, window=sender, format=8,    # 33 = ClientMessage
                           message_type=x11.XInternAtom(dpy, b"_NET_STARTUP_INFO_BEGIN" if n == 0
                                                        else b"_NET_STARTUP_INFO", 0))
        ev.data.b = message[n:n + 20].ljust(20, b"\0")
        x11.XSendEvent(dpy, root, 0, 1 << 22, ctypes.byref(ev))   # PropertyChangeMask, as the protocol asks
    x11.XDestroyWindow(dpy, sender)
    x11.XCloseDisplay(dpy)                                       # flushes the messages


class DeferredModule(types.ModuleType):
    """Stands in for a module until something uses it, then loads it and becomes it.
    (importlib's LazyLoader can't be used: an `import` statement itself loads the module.)"""

    def __getattr__(self, attr):
        # Introspection, such as the source lookup Shiboken's import hook does on every
        # newly imported module, doesn't count as use.
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(attr)
        if sys.modules.get(self.__name__) is self:
            del sys.modules[self.__name__]
        self.__dict__.update(importlib.import_module(self.__name__).__dict__)
        try:
            return self.__dict__[attr]
        except KeyError:
            raise AttributeError(f"module {self.__name__!r} has no attribute {attr!r}") from None


def defer_import(name):
    """Load a module only when first used. PyMuPDF takes a noticeable fraction of a
    second to load, and nothing needs it until a document is opened, which now happens
    after the window is on screen."""
    if name not in sys.modules and importlib.util.find_spec(name):
        sys.modules[name] = DeferredModule(name)


class InstanceServer:
    """Listens for later launches and opens the files they pass on."""

    def __init__(self, on_files):
        from PySide6.QtCore import QSocketNotifier
        self.on_files = on_files
        try:
            os.unlink(SOCKET_PATH)          # left behind by an instance that didn't exit cleanly
        except FileNotFoundError:
            pass
        os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(SOCKET_PATH)
        self.sock.listen(8)
        self.sock.setblocking(False)
        self.notifier = QSocketNotifier(self.sock.fileno(), QSocketNotifier.Read)
        self.notifier.activated.connect(self._accept)

    def _accept(self):
        try:
            conn, _ = self.sock.accept()
        except BlockingIOError:
            return
        with conn:
            conn.settimeout(2)
            data = b""
            try:
                while chunk := conn.recv(65536):
                    data += chunk
            except OSError:
                pass
        try:
            paths = json.loads(data.decode() or "[]")
        except ValueError:
            return
        self.on_files(paths)


def app_icon():
    from PySide6.QtGui import QIcon
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "app")
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(os.path.join(folder, f"kosmicpdf{'-dev' if DEV else ''}-{size}.png"))
    return icon


def open_from_another_launch(paths):
    from .window import WINDOWS, MainWindow
    win = next((w for w in reversed(WINDOWS) if w.isActiveWindow()), WINDOWS[-1] if WINDOWS else None)
    if win is None or not paths:   # launched from the menu: a fresh window
        win = MainWindow()
        win.show()
    if paths:
        win.open_files(paths)
    win.raise_()
    win.activateWindow()


def main():
    files = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("-")]
    # --new-instance runs on its own, without taking over the running copy's socket.
    if "--new-instance" not in sys.argv and send_to_running(files):
        finish_startup_notification()
        return 0

    # Qt and the app's modules are loaded only now, so a handoff above is quick.
    defer_import("pymupdf")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from .theme import LucideStyle, follow_color_scheme
    from .window import MainWindow

    # For test launches: keep settings (recent files, last folder) out of the user's own.
    # Flatpak always sets XDG_CONFIG_HOME itself, so that can't be used to redirect them.
    if os.environ.get("KOSMICPDF_SETTINGS_DIR"):
        QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, os.environ["KOSMICPDF_SETTINGS_DIR"])
    app = QApplication(sys.argv)
    app.setApplicationName("Kosmic PDF (Dev)" if DEV else "Kosmic PDF")   # also ends each window's title
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(FLATPAK_ID or ("kosmicpdf-dev" if DEV else "kosmicpdf"))   # the installed .desktop file
    app.setWindowIcon(app_icon())
    app.setStyle(LucideStyle(app.style().name()))
    follow_color_scheme(app)
    if "--new-instance" not in sys.argv:
        app.instance_server = InstanceServer(open_from_another_launch)   # lives as long as the app
    win = MainWindow()
    win.show()
    win.open_when_shown(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
