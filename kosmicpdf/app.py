"""Entry point. One process per user: launching again (e.g. double-clicking a PDF
in the file manager) hands the files to the running instance, so every document
lives in one process and tabs and pages can be dragged between all windows."""
import json
import os
import socket
import sys
import tempfile

from PySide6.QtCore import QObject, QSettings, QSocketNotifier
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .theme import follow_color_scheme
from .window import WINDOWS, MainWindow

# The single-instance handoff uses a plain Unix socket (Python's socket module rather
# than QtNetwork, which needs Kerberos libraries the Flatpak runtime doesn't ship).
# Inside a Flatpak each launch gets its own /tmp, so the socket goes in the app's
# runtime folder, which all of its sandboxed copies share.
FLATPAK_ID = os.environ.get("FLATPAK_ID")
_runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
if FLATPAK_ID:
    SOCKET_PATH = os.path.join(_runtime, "app", FLATPAK_ID, "kosmicpdf.sock")
else:
    SOCKET_PATH = os.path.join(_runtime, f"kosmicpdf-{os.getuid()}.sock")


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


class InstanceServer(QObject):
    """Listens for later launches and opens the files they pass on."""

    def __init__(self, on_files):
        super().__init__()
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
        self.notifier = QSocketNotifier(self.sock.fileno(), QSocketNotifier.Read, self)
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
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "app")
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(os.path.join(folder, f"kosmicpdf-{size}.png"))
    return icon


def open_from_another_launch(paths):
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
    # For test launches: keep settings (recent files, last folder) out of the user's own.
    # Flatpak always sets XDG_CONFIG_HOME itself, so that can't be used to redirect them.
    if os.environ.get("KOSMICPDF_SETTINGS_DIR"):
        QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, os.environ["KOSMICPDF_SETTINGS_DIR"])
    app = QApplication(sys.argv)
    app.setApplicationName("Kosmic PDF")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(FLATPAK_ID or "kosmicpdf")   # matches the installed .desktop file
    app.setWindowIcon(app_icon())
    follow_color_scheme(app)
    # --new-instance runs on its own, without taking over the running copy's socket.
    if "--new-instance" not in sys.argv:
        if send_to_running(files):
            return 0
        app.instance_server = InstanceServer(open_from_another_launch)   # lives as long as the app
    win = MainWindow()
    win.show()
    win.open_files(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
