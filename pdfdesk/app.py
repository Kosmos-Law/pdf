"""Entry point. One process per user: launching again (e.g. double-clicking a PDF
in the file manager) hands the files to the running instance, so every document
lives in one process and tabs and pages can be dragged between all windows."""
import json
import os
import sys

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .window import WINDOWS, MainWindow

SERVER_NAME = f"pdfdesk-{os.getuid()}"


def send_to_running(files):
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(QByteArray(json.dumps(files).encode()))
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def app_icon():
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "app")
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(os.path.join(folder, f"pdfdesk-{size}.png"))
    return icon


def main():
    files = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("-")]
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Desk")
    app.setDesktopFileName("pdfdesk")
    app.setWindowIcon(app_icon())
    if "--new-instance" not in sys.argv and send_to_running(files):
        return 0

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def incoming():
        sock = server.nextPendingConnection()

        def read():
            if sock.bytesAvailable():
                paths = json.loads(bytes(sock.readAll()).decode() or "[]")
                win = next((w for w in reversed(WINDOWS) if w.isActiveWindow()), WINDOWS[-1] if WINDOWS else None)
                if win is None or not paths:   # launched from the menu: a fresh window
                    win = MainWindow()
                    win.show()
                if paths:
                    win.open_files(paths)
                win.raise_()
                win.activateWindow()
        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(incoming)
    win = MainWindow()
    win.show()
    win.open_files(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
