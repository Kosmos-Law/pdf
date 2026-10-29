"""Entry point. One process per user: launching again (e.g. double-clicking a PDF
in the file manager) hands the files to the running instance, so every document
lives in one process and tabs and pages can be dragged between all windows.

Startup is arranged so something appears quickly. A launch that only hands files
to the running copy does so before loading Qt. A first launch shows its window
before PyMuPDF is loaded and the document is opened (see MainWindow.open_when_shown).
"""
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


def send_to_running(files, token=None):
    """Hand files to an already-running Kosmic PDF. False if none is running. On Wayland,
    `token` is this launch's activation token (XDG_ACTIVATION_TOKEN), which lets the
    running copy bring its window forward: Wayland gives focus only to a window that
    shows one."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(SOCKET_PATH)
        s.sendall(json.dumps({"files": files, "token": token}).encode())
        return True
    except OSError:
        return False
    finally:
        s.close()


def finish_startup_notification():
    """End the desktop's busy cursor for a launch that handed its files on (see x11)."""
    from .x11 import finish_startup_notification as finish
    finish(os.environ.pop("DESKTOP_STARTUP_ID", ""))


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
            message = json.loads(data.decode() or "[]")
        except ValueError:
            return
        if isinstance(message, list):      # from a launch of an earlier version: just the files
            message = {"files": message}
        self.on_files(message.get("files") or [], message.get("token"))


def app_icon():
    from PySide6.QtGui import QIcon
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "app")
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(os.path.join(folder, f"kosmicpdf{'-dev' if DEV else ''}-{size}.png"))
    return icon


def window_for_files(windows, here=None):
    """The window a file from another launch goes to: the one used most recently, out of
    those on the workspace in view if any are. `here(window)` says whether a window is on
    that workspace (True, False, or None where that can't be told, as on Wayland)."""
    by_use = sorted(windows, key=lambda w: w.last_used, reverse=True)
    if here:
        nearby = [w for w in by_use if here(w)]
        if nearby:
            return nearby[0]
    return by_use[0] if by_use else None


def open_from_another_launch(paths, token=None):
    from PySide6.QtGui import QGuiApplication
    from .window import WINDOWS, MainWindow
    here = None
    if QGuiApplication.platformName() == "xcb":
        from .x11 import on_current_workspace
        here = lambda w: on_current_workspace(int(w.winId()))  # noqa: E731
    win = window_for_files(WINDOWS, here)
    fresh = win is None or not paths
    if fresh:                      # launched from the menu: a fresh window, on the workspace in view
        win = MainWindow()
        win.show()
    if paths:
        win.open_files(paths)
    if win.isMinimized():
        win.showNormal()
    platform = QGuiApplication.platformName()
    if token and platform.startswith("wayland"):
        # Wayland gives the focus only to a window that shows the launch's activation token,
        # and lets the compositor decide where (typically, by switching to the window's
        # workspace). Qt reads the token from here when the window asks for the focus.
        os.environ["XDG_ACTIVATION_TOKEN"] = token
    win.raise_()
    win.activateWindow()
    if not fresh and platform == "xcb":
        # On X11 the window may be on another workspace, and the window manager won't give
        # it the focus at its own request: bring it to the user instead (see x11).
        from .x11 import bring_to_current_workspace
        bring_to_current_workspace(int(win.winId()))


def main():
    files = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("-")]
    # --new-instance runs on its own, without taking over the running copy's socket.
    if "--new-instance" not in sys.argv and send_to_running(files, os.environ.get("XDG_ACTIVATION_TOKEN")):
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
