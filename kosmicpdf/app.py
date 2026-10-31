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
import secrets
import socket
import sys
import tempfile
import types

from . import __version__

WINDOWS = sys.platform == "win32"
# The single-instance handoff uses a plain socket (Python's socket module rather than
# QtNetwork, which needs Kerberos libraries the Flatpak runtime doesn't ship): a Unix
# socket, or on Windows, which has none, a loopback TCP port. Inside a Flatpak each
# launch gets its own /tmp, so the socket goes in the app's runtime folder, which all
# of its sandboxed copies share.
FLATPAK_ID = os.environ.get("FLATPAK_ID")
# --dev marks the development copy (./install.sh --dev): its own name, grey icon and
# socket, so it runs alongside the installed app instead of handing files to it.
DEV = "--dev" in sys.argv
_runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
if FLATPAK_ID:
    SOCKET_PATH = os.path.join(_runtime, "app", FLATPAK_ID, "kosmicpdf.sock")
elif WINDOWS:
    # Not a socket but a note of where the running copy listens: its port, a secret that
    # proves a caller read this file, and its process id (see _connect).
    SOCKET_PATH = os.path.join(os.environ.get("LOCALAPPDATA") or _runtime, "kosmicpdf",
                               f"instance{'-dev' if DEV else ''}.json")
else:
    SOCKET_PATH = os.path.join(_runtime, f"kosmicpdf{'-dev' if DEV else ''}-{os.getuid()}.sock")


def _connect():
    """A socket connected to the running copy, and the secret to send it (None on Unix).
    Raises OSError (or ValueError, for a damaged note) when nothing is listening."""
    if WINDOWS:
        with open(SOCKET_PATH) as f:
            note = json.load(f)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", int(note["port"])))
        except OSError:
            s.close()
            raise
        # Windows gives the focus only to the foreground process (this launch) or one it
        # names here; without this the running copy's window could only flash its button.
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(int(note["pid"]))
        except (OSError, AttributeError, ValueError, KeyError):
            pass
        return s, str(note["secret"])
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(SOCKET_PATH)
    except OSError:
        s.close()
        raise
    return s, None


def send_to_running(files, token=None):
    """Hand files to an already-running Kosmic PDF. False if none is running. On Wayland,
    `token` is this launch's activation token (XDG_ACTIVATION_TOKEN), which lets the
    running copy bring its window forward: Wayland gives focus only to a window that
    shows one."""
    try:
        s, secret = _connect()
    except (OSError, ValueError, KeyError):
        return False
    with s:
        try:
            s.sendall(json.dumps({"files": files, "token": token, "secret": secret}).encode())
            if WINDOWS:
                # The port in the note may have been reused by another program since the copy
                # that wrote it died: only Kosmic PDF answers "ok" (once its event loop gets
                # round to it, so this waits longer than the connection did).
                s.shutdown(socket.SHUT_WR)
                s.settimeout(5)
                return s.recv(2) == b"ok"
            return True
        except OSError:
            return False


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
        self.secret = None
        os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
        if WINDOWS:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.bind(("127.0.0.1", 0))
            self.secret = secrets.token_hex(16)
            note = {"port": self.sock.getsockname()[1], "secret": self.secret, "pid": os.getpid()}
            with open(SOCKET_PATH + ".tmp", "w") as f:
                json.dump(note, f)
            os.replace(SOCKET_PATH + ".tmp", SOCKET_PATH)   # never half-written when a launch reads it
        else:
            try:
                os.unlink(SOCKET_PATH)          # left behind by an instance that didn't exit cleanly
            except FileNotFoundError:
                pass
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
            if self.secret and message.get("secret") != self.secret:
                return                         # not a launch of Kosmic PDF (it didn't read the note)
            try:
                conn.sendall(b"ok")
            except OSError:
                pass
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


def add_bundled_tools():
    """The Windows build (packaging/windows) carries OCRmyPDF, Tesseract and Ghostscript
    beside the app; put them where the OCR and PDF/A commands look, ahead of any copies
    installed on the machine."""
    if not getattr(sys, "frozen", False):
        return
    here = os.path.dirname(os.path.abspath(sys.executable))
    tools = os.path.join(here, "tools")
    ahead = [p for p in (here, os.path.join(tools, "tesseract"), os.path.join(tools, "gs", "bin")) if os.path.isdir(p)]
    os.environ["PATH"] = os.pathsep.join(ahead + [os.environ.get("PATH", "")])
    tessdata = os.path.join(tools, "tesseract", "tessdata")
    if os.path.isdir(tessdata):
        os.environ["TESSDATA_PREFIX"] = tessdata


def main():
    files = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("-")]
    # --new-instance runs on its own, without taking over the running copy's socket.
    if "--new-instance" not in sys.argv and send_to_running(files, os.environ.get("XDG_ACTIVATION_TOKEN")):
        finish_startup_notification()
        return 0

    # Qt and the app's modules are loaded only now, so a handoff above is quick.
    add_bundled_tools()
    defer_import("pymupdf")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from .theme import LucideStyle, follow_color_scheme
    from .window import MainWindow

    # For test launches: keep settings (recent files, last folder) out of the user's own.
    # Flatpak always sets XDG_CONFIG_HOME itself, so that can't be used to redirect them.
    if os.environ.get("KOSMICPDF_SETTINGS_DIR"):
        QSettings.setDefaultFormat(QSettings.IniFormat)    # a folder of files, on Windows too (not the registry)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, os.environ["KOSMICPDF_SETTINGS_DIR"])
    app = QApplication(sys.argv)
    app.setApplicationName("Kosmic PDF (Dev)" if DEV else "Kosmic PDF")   # also ends each window's title
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(FLATPAK_ID or ("kosmicpdf-dev" if DEV else "kosmicpdf"))   # the installed .desktop file
    app.setWindowIcon(app_icon())
    app.setStyle(LucideStyle(app.style().name()))
    follow_color_scheme(app)
    # Nothing can be done with the program until its terms (no warranty) are accepted.
    from .dialogs import TermsDialog, terms_accepted
    if not terms_accepted() and not TermsDialog().exec():
        return 0
    if "--new-instance" not in sys.argv:
        app.instance_server = InstanceServer(open_from_another_launch)   # lives as long as the app
    win = MainWindow()
    win.show()
    win.open_when_shown(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
