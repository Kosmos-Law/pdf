"""Check for Updates, at the foot of the menu.

Inside the Flatpak the app has no network access of its own, so it asks Flatpak, through
its portal, to look for a newer version and install it. Anywhere else it reads the number
of the latest release from GitHub and offers the download. Either way nothing happens
until the user asks, and nothing is sent but the request itself."""
import json
import os
import sys
import threading
import urllib.request

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot, SLOT
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from . import __version__

try:
    from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage, QDBusObjectPath
except ImportError:         # the Windows build leaves QtDBus out; only the Flatpak uses it
    QDBusMessage = None

TITLE = "Check for Updates"
RELEASE_API = "https://api.github.com/repos/Kosmos-Law/pdf/releases/latest"
INSTALLER = "https://github.com/Kosmos-Law/pdf/releases/latest/download/KosmosPDF-Setup.exe"
DOWNLOAD_PAGE = "https://kosmos.law/pdf/"
FLATPAK_ID = os.environ.get("FLATPAK_ID")
PORTAL = "org.freedesktop.portal.Flatpak"
PORTAL_PATH = "/org/freedesktop/portal/Flatpak"
MONITOR = PORTAL + ".UpdateMonitor"
RUNNING, EMPTY, DONE, ERROR = range(4)      # the portal's "status" in a Progress signal


def version_key(text):
    """'v0.5.1' as (0, 5, 1), so that versions compare by number; () if it isn't one."""
    try:
        return tuple(int(part) for part in str(text).strip().lstrip("vV").split("."))
    except ValueError:
        return ()


def latest_release(timeout=15):
    """The version number of the latest release on GitHub."""
    request = urllib.request.Request(RELEASE_API, headers={"User-Agent": "KosmosPDF",
                                                           "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.load(reply)["tag_name"].lstrip("vV")


class ReleaseCheck(QObject):
    """Looks up the latest release without holding up the window."""
    done = Signal(str, str)         # the latest version; or "" and why it couldn't be found

    def start(self, window_id=""):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            found = latest_release(), ""
        except Exception as exc:        # no network, GitHub down, an answer that makes no sense
            found = "", str(getattr(exc, "reason", None) or exc)
        try:
            self.done.emit(*found)
        except RuntimeError:            # the app closed while the answer was on its way
            pass

    def stop(self):
        pass


class FlatpakUpdate(QObject):
    """Has Flatpak look for a newer version and install it. Flatpak asks the user's leave
    the first time, and reports back in Progress signals."""
    progress = Signal(int)          # percent of the download and installation
    done = Signal(str, str)         # "updated", "current", "denied" or "failed"; and what went wrong

    def start(self, window_id=""):
        self.bus = QDBusConnection.sessionBus()
        self.handle = None
        call = QDBusMessage.createMethodCall(PORTAL, PORTAL_PATH, PORTAL, "CreateUpdateMonitor")
        call.setArguments([{}])
        reply = self.bus.call(call)
        if reply.type() != QDBusMessage.ReplyMessage or not reply.arguments():
            return self.done.emit("failed", reply.errorMessage() or "Flatpak's update service did not answer.")
        handle = reply.arguments()[0]
        self.handle = handle.path() if isinstance(handle, QDBusObjectPath) else str(handle)
        self.bus.connect(PORTAL, self.handle, MONITOR, "Progress", self, SLOT("_progress(QVariantMap)"))
        call = QDBusMessage.createMethodCall(PORTAL, self.handle, MONITOR, "Update")
        call.setArguments([window_id, {}])
        reply = self.bus.call(call)         # answers at once; the work is reported in Progress
        if reply.type() != QDBusMessage.ReplyMessage:
            self._finish("failed", reply.errorMessage())

    @Slot("QVariantMap")
    def _progress(self, info):
        status = int(info.get("status", ERROR))
        if status == RUNNING:
            ops = int(info.get("n_ops", 0))
            if ops:
                self.progress.emit(min(100, (int(info.get("op", 0)) * 100 + int(info.get("progress", 0))) // ops))
        elif status == EMPTY:
            self._finish("current", "")
        elif status == DONE:
            self._finish("updated", "")
        else:
            denied = str(info.get("error", "")).endswith("AccessDenied")
            self._finish("denied" if denied else "failed", str(info.get("error_message", "")))

    def _finish(self, outcome, detail):
        self.stop()
        self.done.emit(outcome, detail)

    def stop(self):
        """Let go of Flatpak's monitor, which also calls off an update still under way."""
        if getattr(self, "handle", None):
            self.bus.disconnect(PORTAL, self.handle, MONITOR, "Progress", self, SLOT("_progress(QVariantMap)"))
            self.bus.call(QDBusMessage.createMethodCall(PORTAL, self.handle, MONITOR, "Close"), QDBus.NoBlock)
            self.handle = None


def superseded():
    """True when a newer version was installed while this one was running (Flatpak marks
    the running copy), so that all it takes is starting the app again."""
    return os.path.exists("/app/.updated")


class Check(QObject):
    """One run of Check for Updates in a window: a note that it is looking, then the answer."""

    def __init__(self, win, flatpak=None):
        super().__init__(win)
        self.win = win
        self.flatpak = bool(FLATPAK_ID) if flatpak is None else flatpak
        self.version = __version__
        self.finished = False
        self.worker = (FlatpakUpdate if self.flatpak else ReleaseCheck)(self)
        self.dlg = QProgressDialog("Checking for updates…", "Cancel", 0, 0, win)
        self.dlg.setWindowTitle(TITLE)
        self.dlg.setMinimumWidth(380)
        self.dlg.setWindowModality(Qt.WindowModal)
        self.dlg.setMinimumDuration(0)
        self.dlg.setAutoClose(False)
        self.dlg.setAutoReset(False)
        self.dlg.canceled.connect(self.cancel)
        self.dlg.show()
        if self.flatpak:
            self.worker.progress.connect(self.installing)
            self.worker.done.connect(self.flatpak_done)
        else:
            self.worker.done.connect(self.release_found)
        x11 = QGuiApplication.platformName() == "xcb"       # lets Flatpak put its question over this window
        self.worker.start(f"x11:{int(win.winId()):x}" if x11 else "")

    def cancel(self):
        if not self.finished:
            self.finished = True
            self.worker.stop()
            self.dlg.close()

    def installing(self, percent):
        if not self.finished:
            self.dlg.setLabelText("Installing the update…")
            self.dlg.setRange(0, 100)
            self.dlg.setValue(percent)

    def _answer(self):
        """Closes the note; False if the user had already called the check off."""
        if self.finished:
            return False
        self.finished = True
        self.dlg.close()
        return True

    def flatpak_done(self, outcome, detail):
        if not self._answer():
            return
        by_hand = f"You can also update from a terminal:\n\nflatpak update {FLATPAK_ID or 'law.kosmos.KosmosPDF'}"
        if outcome == "updated":
            self.say("Kosmos PDF has been updated.\n\nClose it and open it again to use the new version.")
        elif outcome == "current" and superseded():
            self.say("The latest version is already installed.\n\nClose Kosmos PDF and open it again to use it.")
        elif outcome == "current":
            self.say(f"Kosmos PDF {self.version} is the latest version.")
        elif outcome == "denied":
            self.say("Kosmos PDF isn't allowed to update itself; that was turned down when Flatpak asked.\n\n"
                     + by_hand, QMessageBox.Warning)
        else:
            self.say("Kosmos PDF couldn't be updated." + (f"\n\n{detail}" if detail else "") + f"\n\n{by_hand}",
                     QMessageBox.Warning)

    def release_found(self, latest, error):
        if not self._answer():
            return
        if not version_key(latest):
            return self.say("Couldn't check for updates." + (f"\n\n{error}" if error else ""), QMessageBox.Warning)
        if version_key(latest) <= version_key(self.version):
            return self.say(f"Kosmos PDF {self.version} is the latest version.")
        windows = sys.platform == "win32"
        box = QMessageBox(QMessageBox.Information, TITLE,
                          f"Kosmos PDF {latest} is available. You have {self.version}.", QMessageBox.NoButton, self.win)
        get = box.addButton("Download Installer" if windows else "Open Download Page", QMessageBox.AcceptRole)
        box.addButton("Not Now", QMessageBox.RejectRole)
        box.setDefaultButton(get)
        box.exec()
        if box.clickedButton() is get:
            QDesktopServices.openUrl(QUrl(INSTALLER if windows else DOWNLOAD_PAGE))

    def say(self, text, icon=QMessageBox.Information):
        QMessageBox(icon, TITLE, text, QMessageBox.Ok, self.win).exec()
