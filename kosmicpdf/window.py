"""Main window, document tabs, and detachable tab bar."""
import os
import tempfile

import pymupdf as fitz
from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QProcess, QSize, Qt, QTimer, qVersion
from PySide6.QtGui import (QAction, QActionGroup, QCursor, QDrag, QGuiApplication, QIcon, QIntValidator, QPalette,
                           QKeySequence, QMouseEvent)
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressDialog, QSizePolicy, QSplitter, QTabBar, QTabWidget,
                               QToolBar, QToolButton, QVBoxLayout, QWidget)

from . import dialogs
from .core import MIME_PAGES, MIME_TAB, PdfDocument, is_image, load_any, mime_pdf_bytes, pages_mime
from .pageview import HIGHLIGHT_COLORS, PageView
from . import theme
from .theme import Colors, lucide, stylesheet, swatch
from .thumbs import ThumbPane

WINDOWS = []   # every open MainWindow, so tabs can find their way between them
RECENT_MAX = 12
EMPTY_TEXT = "Open a PDF (Ctrl+O), or drop files here."


def recent_files():
    return [p for p in dialogs.settings().value("recent_files", [], type=list) if p]


def remember_recent(path):
    files = [path] + [p for p in recent_files() if p != path]
    dialogs.settings().setValue("recent_files", files[:RECENT_MAX])


def short_folder(path):
    """The last two folders of a file's location, e.g. 'Smith v Jones/Drafts'."""
    parts = os.path.dirname(path).replace(os.path.expanduser("~"), "~", 1).split(os.sep)
    return os.sep.join(parts[-2:]) if len(parts) > 2 else os.sep.join(parts)


# Lucide icon for each action (bundled in kosmicpdf/icons).
LUCIDE = {
    "open": "folder-open", "save": "save", "save_as": "save", "close_tab": "x", "new_window": "app-window",
    "combine": "combine", "images": "image", "quit": "log-out", "undo": "undo-2", "redo": "redo-2",
    "copy": "copy", "cut": "scissors", "paste": "clipboard-paste", "find": "search", "find_bar": "search",
    "cut_pages": "scissors", "copy_pages": "copy", "paste_pages": "clipboard-paste", "delete_pages": "trash-2",
    "rotate_left": "rotate-ccw", "rotate_right": "rotate-cw", "rotate_180": "refresh-ccw",
    "extract": "file-output", "insert_blank": "file-plus", "insert_file": "file-input",
    "zoom_in": "zoom-in", "zoom_out": "zoom-out", "fit_width": "move-horizontal", "fit_page": "maximize",
    "thumbs": "panel-left", "bates": "hash", "ocr": "scan-text", "pdfa": "file-check", "flatten": "layers",
    "redact_search": "text-search", "apply_redactions": "check-check", "redact_done": "x", "about": "info",
    "mode_select": "text-cursor", "mode_highlight": "highlighter", "mode_typewriter": "type", "mode_redact": "eye-off",
}


class FindBar(QToolBar):
    """Find in the document, in a bar that opens under the toolbar, near the button that
    opens it. The search starts as you type and runs a few pages at a time, beginning with the
    page in view, so a long document doesn't hold up the window."""

    def __init__(self, win):
        super().__init__("Find")
        self.win = win
        self.tab = None
        self.setObjectName("findBar")
        self.setMovable(False)
        self.setIconSize(QSize(theme.TOOLBAR_ICON, theme.TOOLBAR_ICON))
        self.toggleViewAction().setVisible(False)       # not offered in the toolbar menu
        self.edit = QLineEdit(placeholderText="Find in document")
        self.edit.setFixedWidth(300)
        self.edit.installEventFilter(self)
        self.search_icon = self.edit.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.addWidget(self.edit)
        self.prev = self.addAction("Previous", lambda: self.step(-1))
        self.prev.setToolTip("Previous match (Shift+Enter)")
        self.next = self.addAction("Next", lambda: self.step(1))
        self.next.setToolTip("Next match (Enter)")
        self.addSeparator()
        self.case = self.addAction("Match Case")
        self.whole = self.addAction("Whole Words")
        for a, tip in ((self.case, "Only matches with the same capitals"),
                       (self.whole, "Only whole words, so “art” doesn't find “party”")):
            a.setCheckable(True)
            a.setToolTip(tip)
            a.toggled.connect(lambda _: self.restart())
            self.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addSeparator()
        self.label = QLabel()
        self.addWidget(self.label)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.addWidget(spacer)
        self.close_action = self.addAction("Close", self.close_bar)
        self.close_action.setToolTip("Close (Esc)")
        self.typing = QTimer(self, singleShot=True, interval=250)    # search once typing pauses
        self.typing.timeout.connect(self.restart)
        self.edit.textChanged.connect(lambda: self.typing.start())
        self.edit.returnPressed.connect(
            lambda: self.step(-1 if QApplication.keyboardModifiers() & Qt.ShiftModifier else 1))
        self.searching = QTimer(self, interval=0)
        self.searching.timeout.connect(self._search_more)
        self._jump = False
        self.hide()

    def apply_colors(self, colors):
        self.search_icon.setIcon(lucide("search", colors.text))
        self.prev.setIcon(lucide("chevron-up", colors.text))
        self.next.setIcon(lucide("chevron-down", colors.text))
        self.close_action.setIcon(lucide("x", colors.text))

    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self.close_bar()
            return True
        return super().eventFilter(obj, e)

    def open_bar(self):
        was_open = self.isVisible()
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()
        if not was_open and self.edit.text().strip():
            self.restart(jump=False)        # bring back the last search's matches

    def close_bar(self):
        self.hide()
        self.searching.stop()
        self.typing.stop()
        if self.tab:
            self.tab.view.find("")
            self.tab.view.canvas.setFocus()
        self.label.clear()

    def set_tab(self, tab):
        """The window now shows this tab (or none)."""
        if tab is self.tab:
            return
        if self.tab:
            self.tab.pdoc.structure_changed.disconnect(self._restructured)
            self.tab.view.find("")
        self.tab = tab
        self.searching.stop()
        if tab:
            tab.pdoc.structure_changed.connect(self._restructured)
        if self.isVisible() and self.edit.text().strip():
            self.restart(jump=False)
        else:
            self.label.clear()

    def _restructured(self):
        # Pages were added, removed or moved, which clears the view's matches; find them again.
        if self.isVisible() and self.edit.text().strip():
            self.restart(jump=False)

    def restart(self, jump=True):
        self.typing.stop()
        if not self.tab:
            return
        self.tab.view.find(self.edit.text(), self.case.isChecked(), self.whole.isChecked())
        self._jump = jump
        self.searching.start()
        self._search_more()

    def _search_more(self):
        view = self.tab.view if self.tab else None
        if view is None:
            self.searching.stop()
            return
        done = view.find_more()
        if self._jump and view.find_hits:
            self._jump = False
            view.find_step(1)
        if done:
            self.searching.stop()
        self.show_count()

    def step(self, d):
        if not self.tab:
            return
        if self.typing.isActive() or (self.edit.text().strip() and not self.tab.view.find_hits
                                      and not self.searching.isActive()):
            self.restart(jump=d > 0)        # Enter pressed before the search began
            if d < 0:
                self.tab.view.find_step(-1)
        else:
            self.tab.view.find_step(d)
        self.show_count()

    def show_count(self):
        view = self.tab.view if self.tab else None
        n = len(view.find_hits) if view else 0
        searching = self.searching.isActive()
        if not view or not self.edit.text().strip():
            text = ""
        elif view.find_index >= 0:
            text = f"{view.find_index + 1} of {n}" + ("…" if searching else "")
        elif searching:
            text = f"Searching… {n} found" if n else "Searching…"
        else:
            text = "No matches" if not n else f"{n} match{'es' if n != 1 else ''}"
        self.label.setText(text)
        not_found = bool(view and self.edit.text().strip() and not n and not searching)
        if self.edit.property("notFound") != not_found:
            self.edit.setProperty("notFound", not_found)
            self.edit.style().unpolish(self.edit)
            self.edit.style().polish(self.edit)


class DocTab(QWidget):
    """One open document: thumbnails on the left, pages on the right."""

    def __init__(self, pdoc):
        super().__init__()
        self.pdoc = pdoc
        self.thumbs = ThumbPane(pdoc)
        self.view = PageView(pdoc)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.thumbs)
        self.splitter.addWidget(self.view)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setHandleWidth(1)
        self.splitter.setSizes([170, 900])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.splitter)

        self.thumbs.page_clicked.connect(self.view.go_to_page)
        self.view.current_page_changed.connect(self.thumbs.follow_page)
        self.thumbs.pages_dropped.connect(self.insert_pdf_bytes)
        self.view.pages_dropped.connect(self.insert_pdf_bytes)
        self.thumbs.files_dropped.connect(self.insert_files)
        self.view.files_dropped.connect(lambda files: self.main_window().open_files(files))
        self.thumbs.context_requested.connect(self.thumb_menu)
        self.thumbs.command.connect(lambda c: {"copy": self.copy_pages, "cut": self.cut_pages,
                                               "paste": self.paste_pages, "delete": self.delete_pages}[c]())
        pdoc.modified_changed.connect(lambda _: self.update_title())

    def main_window(self):
        w = self.window()
        return w if isinstance(w, MainWindow) else None

    def update_title(self):
        w = self.main_window()
        if w:
            i = w.tabs.indexOf(self)
            if i >= 0:
                w.tabs.setTabText(i, self.pdoc.display_name())
                w.tabs.setTabToolTip(i, self.pdoc.path or "Not saved yet")
            w.update_window_title()
            w.update_badges()

    # --- page selection helpers ---------------------------------------------------
    def target_pages(self):
        """Pages selected in the thumbnail pane, or the current page."""
        return self.thumbs.selected_pages() or ([self.view.current_page] if self.pdoc.page_count else [])

    def insert_point(self):
        sel = self.thumbs.selected_pages()
        return (sel[-1] + 1) if sel else min(self.view.current_page + 1, self.pdoc.page_count)

    # --- page operations ------------------------------------------------------------
    def rotate(self, delta):
        pages = self.target_pages()
        if pages:
            self.pdoc.rotate(pages, delta)
            self.thumbs.select_pages(pages)

    def copy_pages(self):
        pages = self.target_pages()
        if pages:
            QGuiApplication.clipboard().setMimeData(pages_mime(self.pdoc, pages))
            self.status(f"Copied {len(pages)} page(s).")

    def cut_pages(self):
        pages = self.target_pages()
        if not pages:
            return
        if len(pages) >= self.pdoc.page_count:
            self.status("A PDF must keep at least one page; copy instead, or close the file.")
            return
        self.copy_pages()
        self.pdoc.delete_pages(pages)
        self.status(f"Cut {len(pages)} page(s).")

    def delete_pages(self):
        pages = self.target_pages()
        if not pages:
            return
        if len(pages) >= self.pdoc.page_count:
            QMessageBox.information(self, "Delete pages", "A PDF must keep at least one page.")
            return
        self.pdoc.delete_pages(pages)
        self.status(f"Deleted {len(pages)} page(s).")

    def paste_pages(self):
        mime = QGuiApplication.clipboard().mimeData()
        at = self.insert_point()
        data = mime_pdf_bytes(mime)
        if data:
            self.insert_pdf_bytes(data, at)
        elif mime.hasImage():
            img = QGuiApplication.clipboard().image()
            path = os.path.join(tempfile.mkdtemp(prefix="kosmicpdf-"), "clipboard.png")
            img.save(path)
            self.insert_files([path], at)
        elif mime.hasUrls():
            self.insert_files([u.toLocalFile() for u in mime.urls() if u.isLocalFile()], at)
        else:
            self.status("The clipboard has no pages to paste.")

    def insert_pdf_bytes(self, data, at):
        new = self.pdoc.insert_bytes(data, at)
        self.thumbs.select_pages(new)
        self.status(f"Inserted {len(new)} page(s).")

    def insert_files(self, files, at):
        size = dialogs.settings().value("images/page_size", "Letter")
        size = "Image" if size.startswith("Image") else size
        for f in files:
            try:
                src = load_any(f, size)
            except Exception as exc:
                QMessageBox.warning(self, "Insert", f"Could not read {os.path.basename(f)}:\n{exc}")
                continue
            new = self.pdoc.insert_doc(src, at)
            at += len(new)
        self.status(f"Inserted {len(files)} file(s).")

    def insert_from_file(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Insert pages from", dialogs.settings().value("last_dir", ""),
                                                "PDFs and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)")
        if files:
            self.insert_files(files, self.insert_point())

    def extract_to_new(self):
        pages = self.target_pages()
        if pages:
            pdoc = PdfDocument(fitz.open("pdf", self.pdoc.extract_bytes(pages)),
                               title=f"Pages from {os.path.splitext(self.pdoc.title)[0]}")
            pdoc.set_modified(True)
            self.main_window().add_doc(pdoc)

    def thumb_menu(self, pos):
        w = self.main_window()
        m = QMenu(self)
        for name in ("cut_pages", "copy_pages", "paste_pages", "delete_pages", None,
                     "rotate_left", "rotate_right", "rotate_180", None,
                     "extract", "insert_blank", "insert_file", None, "select_all_pages"):
            if name is None:
                m.addSeparator()
            else:
                m.addAction(w.actions_by_name[name])
        m.exec(self.thumbs.viewport().mapToGlobal(pos))

    def status(self, msg):
        w = self.main_window()
        if w:
            w.statusBar().showMessage(msg, 5000)


class DetachableTabBar(QTabBar):
    """Tabs can be reordered, dropped on another window, or dragged out to a new one.
    Dragging pages over a tab switches to it, so pages can be dropped into its thumbnails."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setAcceptDrops(True)
        self.setElideMode(Qt.ElideMiddle)
        self.setExpanding(False)
        self._press_pos = None

    def mousePressEvent(self, e):
        self._press_pos = e.position().toPoint() if e.button() == Qt.LeftButton else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._press_pos is not None and e.buttons() & Qt.LeftButton and self.count():
            if not self.rect().adjusted(-20, -25, 20, 25).contains(pos):
                # Leave QTabBar's own drag-to-reorder cleanly before starting ours.
                release = QMouseEvent(QEvent.MouseButtonRelease, e.position(), e.globalPosition(),
                                      Qt.LeftButton, Qt.NoButton, e.modifiers())
                super().mouseReleaseEvent(release)
                self._press_pos = None
                self.win.drag_tab_out(self.win.tabs.currentWidget())
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press_pos = None
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        m = e.mimeData()
        if m.hasFormat(MIME_TAB) or m.hasFormat(MIME_PAGES) or m.hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        m = e.mimeData()
        i = self.tabAt(e.position().toPoint())
        if (m.hasFormat(MIME_PAGES)) and i >= 0 and i != self.currentIndex():
            self.setCurrentIndex(i)
        e.setDropAction(Qt.MoveAction if m.hasFormat(MIME_TAB) else Qt.CopyAction)
        e.accept()

    def dropEvent(self, e):
        m = e.mimeData()
        i = self.tabAt(e.position().toPoint())
        if m.hasFormat(MIME_TAB):
            self.win.accept_tab_drop(m, i)
            e.setDropAction(Qt.MoveAction)
        elif m.hasFormat(MIME_PAGES) and i >= 0:
            tab = self.win.tabs.widget(i)
            tab.insert_pdf_bytes(mime_pdf_bytes(m), tab.pdoc.page_count)
            e.setDropAction(Qt.CopyAction)
        elif m.hasUrls():
            self.win.open_files([u.toLocalFile() for u in m.urls() if u.isLocalFile()])
            e.setDropAction(Qt.CopyAction)
        e.accept()


class ExternalJob:
    """Run ocrmypdf on a document's current bytes and swap in the result."""

    def __init__(self, win, tab, args, label):
        self.win, self.tab, self.label = win, tab, label
        self.tmp = tempfile.TemporaryDirectory(prefix="kosmicpdf-")
        self.src = os.path.join(self.tmp.name, "in.pdf")
        self.dst = os.path.join(self.tmp.name, "out.pdf")
        with open(self.src, "wb") as f:
            f.write(tab.pdoc.to_bytes())
        self.proc = QProcess(win)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._output)
        self.proc.finished.connect(self._finished)
        self.log = []
        self.dlg = QProgressDialog(f"{label}…", "Cancel", 0, 0, win)
        self.dlg.setWindowTitle(label)
        self.dlg.setMinimumWidth(460)
        self.dlg.setWindowModality(Qt.WindowModal)
        self.dlg.canceled.connect(self.proc.kill)
        self.dlg.show()
        self.proc.start("ocrmypdf", args + [self.src, self.dst])

    def _output(self):
        text = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        for line in text.replace("\r", "\n").splitlines():
            line = line.strip()
            if line:
                self.log.append(line)
                self.dlg.setLabelText(f"{self.label}…\n{line[:90]}")

    def _finished(self, code, status):
        self.dlg.reset()
        self.win.jobs.discard(self)
        if status == QProcess.NormalExit and code == 0 and os.path.exists(self.dst):
            self.tab.pdoc.replace(open(self.dst, "rb").read())
            self.tab.status(f"{self.label} finished. Save to keep the result.")
        elif code == 6:   # ocrmypdf: page already has text
            QMessageBox.information(self.win, self.label, "Every page already has text, so there was nothing to OCR.\n"
                                    "Choose Redo or Force in the OCR options if the existing text is poor.")
        elif status == QProcess.NormalExit:
            QMessageBox.warning(self.win, self.label, f"{self.label} did not finish (exit code {code}).\n\n"
                                + "\n".join(self.log[-12:]))
        self.tmp.cleanup()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        WINDOWS.append(self)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(1200, 860)
        self.setAcceptDrops(True)
        self.jobs = set()
        self.mode = "select"
        self.tabs = QTabWidget()
        self.tabs.setTabBar(DetachableTabBar(self))
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(lambda i: self.close_tab(self.tabs.widget(i)))
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.empty = QLabel(EMPTY_TEXT)
        self._pending_files = None
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("font-size:16px;")
        self.empty.setForegroundRole(QPalette.PlaceholderText)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.tabs)
        hl.addWidget(self.empty)
        self.setCentralWidget(holder)
        self.page_box = QLineEdit()       # a plain page-number field, as in Xreader
        self.page_box.setAlignment(Qt.AlignCenter)
        self.page_box.setFixedWidth(52)
        self.page_box.setValidator(QIntValidator(1, 1, self.page_box))
        self.page_box.returnPressed.connect(lambda: self.tab and self.tab.view.go_to_page(int(self.page_box.text()) - 1))
        self.page_total = QLabel(" / 0 ")
        self.zoom_box = QComboBox(editable=True)
        self.zoom_box.addItems(["Fit width", "Fit page", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"])
        self.zoom_box.setMinimumContentsLength(8)
        self.zoom_box.textActivated.connect(self._zoom_chosen)
        self.font_size = QDoubleSpinBox(minimum=4, maximum=72, value=12, suffix=" pt", decimals=1)
        self.font_size.setToolTip("Typewriter font size")
        self.font_size.setMaximumWidth(84)
        self.font_size.setKeyboardTracking(False)          # apply on Enter or arrow click, not every keystroke
        self.font_size.setProperty("keepsTypewriterOpen", True)
        self.font_size.valueChanged.connect(lambda v: self.tab and self.tab.view.set_font_size(v))
        self.hl_color = HIGHLIGHT_COLORS["Yellow"]
        self.colors = None
        self.ocr_needed = False
        self._badges = {}                 # action name -> whether its icon has the red dot
        self._ocr_check = QTimer(self, singleShot=True, interval=10)
        self._ocr_check.timeout.connect(self._check_ocr)
        self.build_actions()
        self.build_menus()
        self.build_toolbar()
        self.apply_theme()
        self.update_state()

    # --- helpers -------------------------------------------------------------
    @property
    def tab(self):
        return self.tabs.currentWidget()

    def doc_tabs(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def act(self, name, text, slot, shortcut=None, tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcuts(shortcut if isinstance(shortcut, list) else [QKeySequence(shortcut)])
        a.setToolTip(tip or text.replace("&", "").replace("…", ""))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        self.actions_by_name[name] = a
        return a

    def on_tab(self, method, *args):
        """Slot that calls a DocTab method on the current tab, if any."""
        return lambda: self.tab and getattr(self.tab, method)(*args)

    def build_actions(self):
        self.actions_by_name = {}
        A = self.act
        A("open", "&Open…", self.open_dialog, QKeySequence.Open)
        A("save", "&Save", self.save, QKeySequence.Save)
        A("save_as", "Save &As…", self.save_as, QKeySequence.SaveAs)
        A("close_tab", "&Close Tab", lambda: self.tab and self.close_tab(self.tab), QKeySequence.Close)
        A("new_window", "New &Window", lambda: MainWindow().show(), QKeySequence.New)
        A("combine", "Co&mbine Files into PDF…", self.combine)
        A("images", "&Images to PDF…", lambda: self.combine(images_only=True))
        A("quit", "&Quit", QApplication.closeAllWindows, QKeySequence.Quit)
        A("undo", "&Undo", lambda: self.tab and self.tab.pdoc.undo(), QKeySequence.Undo)
        A("redo", "&Redo", lambda: self.tab and self.tab.pdoc.redo(), QKeySequence.Redo)
        A("copy", "&Copy", self.copy, QKeySequence.Copy)
        A("cut", "Cu&t", self.cut, QKeySequence.Cut)
        A("paste", "&Paste Pages", self.on_tab("paste_pages"), QKeySequence.Paste)
        A("select_all", "Select &All", self.select_all, QKeySequence.SelectAll)
        A("find", "&Find…", lambda: self.findbar.open_bar(), QKeySequence.Find, tip="Find in document (Ctrl+F)")
        # The toolbar's Find button: pressed while the find bar is open, and a second click closes it.
        A("find_bar", "Find", lambda on: self.findbar.open_bar() if on else self.findbar.close_bar(),
          tip="Find in document (Ctrl+F)", checkable=True)
        A("find_next", "Find &Next", lambda: self.find_step(1), [QKeySequence(QKeySequence.FindNext), QKeySequence("Ctrl+G")])
        A("find_prev", "Find Pre&vious", lambda: self.find_step(-1),
          [QKeySequence(QKeySequence.FindPrevious), QKeySequence("Ctrl+Shift+G")])
        A("cut_pages", "Cut Pages", self.on_tab("cut_pages"))
        A("copy_pages", "Copy Pages", self.on_tab("copy_pages"))
        A("paste_pages", "Paste Pages", self.on_tab("paste_pages"))
        A("delete_pages", "Delete Pages", self.on_tab("delete_pages"))
        A("rotate_left", "Rotate Left", self.on_tab("rotate", -90), "Ctrl+Shift+L",
          tip="Rotate selected pages left")
        A("rotate_right", "Rotate Right", self.on_tab("rotate", 90), "Ctrl+Shift+R",
          tip="Rotate selected pages right")
        A("rotate_180", "Rotate 180°", self.on_tab("rotate", 180))
        A("extract", "Copy Pages to New PDF", self.on_tab("extract_to_new"), "Ctrl+Shift+E")
        A("insert_blank", "Insert Blank Page", lambda: self.tab and self.tab.pdoc.insert_blank(self.tab.insert_point()))
        A("insert_file", "Insert Pages from File…", self.on_tab("insert_from_file"))
        A("select_all_pages", "Select All Pages", lambda: self.tab and self.tab.thumbs.selectAll())
        A("zoom_in", "Zoom &In", lambda: self.tab and self.tab.view.set_zoom(self.tab.view.zoom * 1.2), QKeySequence.ZoomIn)
        A("zoom_out", "Zoom &Out", lambda: self.tab and self.tab.view.set_zoom(self.tab.view.zoom / 1.2), QKeySequence.ZoomOut)
        A("fit_width", "Fit &Width", lambda: self.tab and self.tab.view.set_zoom(fit="width"), "Ctrl+2")
        A("fit_page", "Fit &Page", lambda: self.tab and self.tab.view.set_zoom(fit="page"), "Ctrl+1")
        A("actual", "&Actual Size", lambda: self.tab and self.tab.view.set_zoom(1.0), "Ctrl+0")
        A("thumbs", "&Thumbnails", self.toggle_thumbs, "F4", checkable=True).setChecked(True)
        A("bates", "&Bates Numbering…", self.bates)
        A("ocr", "&OCR (Make Searchable)…", self.ocr).setIconText("OCR")
        A("pdfa", "Convert to &PDF/A…", self.pdfa)
        A("flatten", "&Flatten Annotations and Forms", self.flatten)
        A("redact_search", "Mark Text for Redaction…", self.redact_search).setIconText("Mark Text…")
        A("apply_redactions", "Apply Redactions", self.apply_redactions, tip="Permanently remove everything marked for redaction")
        A("redact_done", "Done", lambda: self.set_mode("select"), tip="Finish redacting and go back to selecting text")
        A("about", "&About Kosmic PDF", self.about)

        self.mode_group = QActionGroup(self)
        for name, text, key, tip in (
                ("select", "Select", "V", "Select and copy text; click an annotation to move or delete it"),
                ("highlight", "Highlight", "H", "Drag across text to highlight it, or highlight the selected text"),
                ("typewriter", "Typewriter", "T", "Click to type text onto the page"),
                ("redact", "Redact", "R", "Drag a box around content to mark it for redaction")):
            slot = self.highlight_clicked if name == "highlight" else (lambda checked=False, n=name: self.set_mode(n))
            a = A(f"mode_{name}", text, slot, key, tip=f"{tip} ({key})", checkable=True)
            self.mode_group.addAction(a)
        self.actions_by_name["mode_select"].setChecked(True)

    def build_menus(self):
        a = self.actions_by_name
        mb = self.menuBar()

        def menu(title, names):
            m = mb.addMenu(title)
            for n in names:
                m.addSeparator() if n is None else m.addAction(a[n])
            return m

        file_menu = menu("&File", ["open"])
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self.fill_recent_menu)
        for n in ("save", "save_as", None, "combine", "images", None, "new_window", "close_tab", "quit"):
            file_menu.addSeparator() if n is None else file_menu.addAction(a[n])
        menu("&Edit", ["undo", "redo", None, "cut", "copy", "paste", "select_all", None, "find", "find_next", "find_prev"])
        menu("&View", ["zoom_in", "zoom_out", "fit_width", "fit_page", "actual", None, "thumbs"])
        menu("&Pages", ["rotate_left", "rotate_right", "rotate_180", None, "cut_pages", "copy_pages", "paste_pages",
                        "delete_pages", None, "extract", "insert_blank", "insert_file", "select_all_pages"])
        menu("&Tools", ["mode_select", "mode_highlight", "mode_typewriter", "mode_redact", None,
                        "redact_search", "apply_redactions", None, "bates", "ocr", "pdfa", "flatten"])
        menu("&Help", ["about"])

    def build_toolbar(self):
        a = self.actions_by_name
        tb = self.toolbar = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(theme.TOOLBAR_ICON, theme.TOOLBAR_ICON))
        self.addToolBar(tb)
        for n in ("open", "save", "ocr"):
            tb.addAction(a[n])
        self.ocr_button = tb.widgetForAction(a["ocr"])
        tb.addSeparator()
        for n in ("undo", "redo"):
            tb.addAction(a[n])
        tb.addSeparator()
        tb.addWidget(self.page_box)
        tb.addWidget(self.page_total)
        tb.addAction(a["zoom_out"])
        tb.addWidget(self.zoom_box)
        tb.addAction(a["zoom_in"])
        tb.addAction(a["find_bar"])
        tb.addSeparator()
        tb.addAction(a["rotate_left"])
        tb.addAction(a["rotate_right"])
        tb.addSeparator()
        tb.addAction(a["mode_select"])
        # Highlight is a split button, as in a word processor: the button highlights, and
        # its arrow chooses the colour, which shows as a stripe under the highlighter.
        colors = QToolButton()
        colors.setDefaultAction(a["mode_highlight"])
        colors.setPopupMode(QToolButton.MenuButtonPopup)
        cm = QMenu(colors)
        for name, rgb in HIGHLIGHT_COLORS.items():
            cm.addAction(swatch(rgb), name, lambda rgb=rgb: self.set_hl_color(rgb))
        cm.addSeparator()
        self.clear_action = cm.addAction("Clear (remove highlights)", lambda: self.set_hl_color(None))
        colors.setMenu(cm)
        self.color_button = colors
        tb.addWidget(colors)
        tb.addAction(a["mode_typewriter"])
        tb.addWidget(self.font_size)
        # Common commands are icons with tooltips; the tools keep a label so they are easy to find.
        labelled = {a[n] for n in ("mode_select", "mode_highlight", "mode_typewriter", "ocr")}
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        for b in tb.findChildren(QToolButton):
            if b.defaultAction() in labelled:
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.build_redact_bar()
        self.findbar = FindBar(self)
        self.findbar.visibilityChanged.connect(a["find_bar"].setChecked)
        self.addToolBarBreak()
        self.addToolBar(self.findbar)

    def build_redact_bar(self):
        """A second row that appears only while redacting (Tools › Redact, or R), with the
        commands that go with it. Redaction is occasional work, so its tools stay off the
        main toolbar the rest of the time."""
        a = self.actions_by_name
        bar = self.redact_bar = QToolBar("Redaction")
        bar.setObjectName("redactBar")
        bar.setMovable(False)
        bar.setIconSize(QSize(theme.TOOLBAR_ICON, theme.TOOLBAR_ICON))
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.toggleViewAction().setVisible(False)       # not offered in the toolbar menu
        self.addToolBarBreak()
        self.addToolBar(bar)
        self.redact_icon = QLabel()
        bar.addWidget(self.redact_icon)
        bar.addWidget(QLabel("<b>Redacting.</b> Drag a box around anything that should be removed."))
        bar.addSeparator()
        bar.addAction(a["redact_search"])
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self.redact_count = QLabel()
        bar.addWidget(self.redact_count)
        bar.addAction(a["apply_redactions"])
        bar.addAction(a["redact_done"])
        bar.hide()

    def update_redact_bar(self):
        if not self.redact_bar.isVisible():
            return
        n = self.tab.pdoc.redaction_count() if self.tab else 0
        self.redact_count.setText(f"{n} area{'' if n == 1 else 's'} marked  " if n else "Nothing marked yet  ")

    def find_step(self, d):
        """Find Next / Previous: step through the matches, or open the find bar if it's closed."""
        if self.findbar.isVisible() and self.findbar.edit.text().strip():
            self.findbar.step(d)
        else:
            self.findbar.open_bar()

    # --- badges: a red dot on Save and OCR when they have something waiting ------------
    def update_badges(self):
        t = self.tab
        wanted = {"save": bool(t and t.pdoc.modified), "ocr": bool(t and self.ocr_needed)}
        for name, on in wanted.items():
            if self._badges.get(name) != on:
                self._badges[name] = on
                self.actions_by_name[name].setIcon(lucide(LUCIDE[name], self.colors.text, dot=on))
        self.actions_by_name["save"].setToolTip("Save (there are unsaved changes)" if wanted["save"] else "Save")
        self.actions_by_name["ocr"].setToolTip(
            "Some pages are scans without text. OCR them to make the document searchable" if wanted["ocr"]
            else "OCR (Make Searchable)")

    def check_ocr_soon(self):
        """Look, a little at a time, for pages that are scans without text, and put a dot
        on the OCR button if there are any."""
        self._ocr_check.start()

    def _check_ocr(self):
        t = self.tab
        found = t.pdoc.needs_ocr(budget=0.03) if t else False
        if found is None:                  # a long document: carry on after the window has had a turn
            self._ocr_check.start()
            return
        self.ocr_needed = found
        self.update_badges()
        if found and not getattr(t.pdoc, "ocr_hint_shown", False):
            t.pdoc.ocr_hint_shown = True
            self.statusBar().showMessage("This document has scanned pages without text. "
                                         "OCR will make them searchable.", 10000)

    # --- state --------------------------------------------------------------
    def update_window_title(self):
        t = self.tab
        name = QApplication.applicationName()
        self.setWindowTitle(f"{t.pdoc.display_name()} — {name}" if t else name)

    def update_state(self):
        has = self.tab is not None
        self.tabs.setVisible(has)
        self.empty.setVisible(not has)
        for n, a in self.actions_by_name.items():
            if n not in ("open", "new_window", "combine", "images", "quit", "about", "thumbs", "redact_done"):
                a.setEnabled(has)
        if has:
            pdoc = self.tab.pdoc
            self.actions_by_name["undo"].setEnabled(pdoc.can_undo())
            self.actions_by_name["redo"].setEnabled(pdoc.can_redo())
            self.page_box.validator().setTop(max(1, pdoc.page_count))
            if not self.page_box.hasFocus():
                self.page_box.setText(str(self.tab.view.current_page + 1))
            self.page_total.setText(f" / {pdoc.page_count} ")
            z = self.tab.view
            self.zoom_box.setEditText({"width": "Fit width", "page": "Fit page"}.get(z.fit, f"{round(z.zoom * 100)}%"))
        self.update_window_title()
        self.update_badges()

    def update_document_state(self):
        """After the document in view changes, or a different one comes into view."""
        self.update_state()
        self.update_redact_bar()
        self.check_ocr_soon()

    def _tab_changed(self, _):
        t = self.tab
        if t:
            self.apply_settings(t)
        self.findbar.set_tab(t)
        self.update_document_state()

    def apply_theme(self):
        """Recolour icons, pages and panels from the current palette (light or dark)."""
        colors = Colors(self.palette())
        if self.colors and colors.key() == self.colors.key():
            return
        self.colors = colors
        for name, a in self.actions_by_name.items():
            if name in LUCIDE:
                a.setIcon(lucide(LUCIDE[name], colors.text))
        self._badges.clear()
        self.update_badges()
        for t in self.doc_tabs():
            t.view.apply_colors(colors)
            t.thumbs.apply_colors(colors)
        if hasattr(self, "color_button"):
            self.actions_by_name["mode_highlight"].setIcon(self.hl_icon())
            self.redact_icon.setPixmap(lucide(LUCIDE["mode_redact"], colors.text).pixmap(theme.TOOLBAR_ICON))
            self.findbar.apply_colors(colors)
            self.clear_action.setIcon(lucide("eraser", colors.text))
        app = QApplication.instance()
        sheet = stylesheet(colors)
        if app.styleSheet() != sheet:      # shared by all windows; only set when the theme changes
            app.setStyleSheet(sheet)

    def changeEvent(self, e):
        if e.type() in (QEvent.PaletteChange, QEvent.ThemeChange):
            self.apply_theme()
        super().changeEvent(e)

    def apply_settings(self, t):
        t.view.mode = self.mode
        t.view.font_size = self.font_size.value()
        t.view.hl_color = self.hl_color
        t.thumbs.setVisible(self.actions_by_name["thumbs"].isChecked())
        t.view.apply_colors(self.colors)
        t.thumbs.apply_colors(self.colors)

    def set_mode(self, mode):
        self.mode = mode
        self.actions_by_name[f"mode_{mode}"].setChecked(True)
        for t in self.doc_tabs():
            t.view.mode = mode
            t.view.clear_selection()
        self.redact_bar.setVisible(mode == "redact")
        self.update_redact_bar()

    def hl_icon(self):
        if self.hl_color is None:
            return lucide("eraser", self.colors.text)
        return lucide(LUCIDE["mode_highlight"], self.colors.text, stripe=self.hl_color)

    def highlight_clicked(self):
        """The Highlight button (or H): highlight the selected text if there is some, and
        stay in the current tool; otherwise switch to the highlighter."""
        if self.tab and self.tab.view.highlighter_on_selection():
            self.actions_by_name[f"mode_{self.mode}"].setChecked(True)   # the click checked Highlight
        else:
            self.set_mode("highlight")

    def set_hl_color(self, rgb):
        """Pick the highlighter colour; None turns the highlighter into an eraser. Text
        already selected gets the new colour (or, for None, loses its highlights)."""
        self.hl_color = rgb
        a = self.actions_by_name["mode_highlight"]
        a.setIcon(self.hl_icon())
        a.setToolTip("Remove highlights: drag across highlighted text, or click a highlight (H)" if rgb is None
                     else "Drag across text to highlight it, or highlight the selected text (H)")
        for t in self.doc_tabs():
            t.view.hl_color = rgb
        if self.tab and self.tab.view.highlighter_on_selection():
            return
        if rgb is None:
            self.statusBar().showMessage("Drag across highlighted text, or click a highlight, to remove it.", 8000)
        self.set_mode("highlight")

    def toggle_thumbs(self):
        for t in self.doc_tabs():
            t.thumbs.setVisible(self.actions_by_name["thumbs"].isChecked())

    def _zoom_chosen(self, text):
        if not self.tab:
            return
        if text.startswith("Fit w"):
            self.tab.view.set_zoom(fit="width")
        elif text.startswith("Fit p"):
            self.tab.view.set_zoom(fit="page")
        else:
            try:
                self.tab.view.set_zoom(float(text.strip().rstrip("%")) / 100)
            except ValueError:
                pass
        self.tab.view.canvas.setFocus()

    # --- tabs ---------------------------------------------------------------
    def add_doc(self, pdoc, index=-1):
        return self.add_tab(DocTab(pdoc), index)

    def add_tab(self, tab, index=-1):
        i = self.tabs.insertTab(index if index >= 0 else self.tabs.count(), tab, tab.pdoc.display_name())
        tab.view.current_page_changed.connect(self._page_changed)
        tab.view.zoom_changed.connect(self._view_changed)
        tab.view.status.connect(self._view_status)
        tab.pdoc.structure_changed.connect(self._doc_changed)
        tab.pdoc.pages_changed.connect(self._doc_changed)
        self.tabs.setCurrentIndex(i)
        self.apply_settings(tab)
        tab.update_title()
        self.update_state()
        return tab

    def detach_tab(self, tab):
        """Remove a tab from this window without closing its document."""
        for sig, slot in ((tab.view.current_page_changed, self._page_changed), (tab.view.zoom_changed, self._view_changed),
                          (tab.view.status, self._view_status), (tab.pdoc.structure_changed, self._doc_changed),
                          (tab.pdoc.pages_changed, self._doc_changed)):
            sig.disconnect(slot)
        self.tabs.removeTab(self.tabs.indexOf(tab))
        self.update_state()
        if not self.tabs.count() and len(WINDOWS) > 1:
            QTimer.singleShot(0, self.close)

    def _page_changed(self, i):
        if self.sender() is (self.tab.view if self.tab else None):
            self.update_state()

    def _view_changed(self, _):
        if self.tab and self.sender() is self.tab.view:
            self.update_state()

    def _view_status(self, msg):
        self.statusBar().showMessage(msg, 6000)

    def _doc_changed(self, *_):
        self.update_document_state()

    def _tab_menu(self, pos):
        i = self.tabs.tabBar().tabAt(pos)
        if i < 0:
            return
        tab = self.tabs.widget(i)
        m = QMenu(self)
        m.addAction("Move to New Window", lambda: self.move_tab_to_new_window(tab))
        others = [w for w in WINDOWS if w is not self]
        if others:
            sub = m.addMenu("Move to Window")
            for n, w in enumerate(others, 1):
                sub.addAction(f"{n}: {w.windowTitle()}", lambda w=w: self.move_tab_to(tab, w))
        m.addSeparator()
        m.addAction("Close", lambda: self.close_tab(tab))
        m.exec(self.tabs.tabBar().mapToGlobal(pos))

    def move_tab_to(self, tab, win, index=-1):
        if tab.main_window() is win:
            return
        self.detach_tab(tab)
        win.add_tab(tab, index)
        win.raise_()
        win.activateWindow()

    def move_tab_to_new_window(self, tab, pos=None):
        if self.tabs.count() == 1:
            if pos is not None:
                self.move(pos)
            return
        win = MainWindow()
        win.resize(self.size())
        self.move_tab_to(tab, win)
        if pos is not None:
            win.move(pos)
        win.show()

    def drag_tab_out(self, tab):
        if tab is None:
            return
        mime = QMimeData()
        mime.setData(MIME_TAB, QByteArray(f"{os.getpid()}:{id(tab)}".encode()))
        drag = QDrag(self.tabs.tabBar())
        drag.setMimeData(mime)
        pm = tab.grab().scaled(360, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(30, 10))
        if drag.exec(Qt.MoveAction) == Qt.IgnoreAction and tab.main_window() is self:
            # Dropped outside every Kosmic PDF window: give it a window of its own.
            self.move_tab_to_new_window(tab, QCursor.pos() - QPoint(60, 20))

    def accept_tab_drop(self, mime, index=-1):
        pid, ident = bytes(mime.data(MIME_TAB)).decode().split(":")
        if int(pid) != os.getpid():
            return
        for w in WINDOWS:
            for t in w.doc_tabs():
                if id(t) == int(ident):
                    w.move_tab_to(t, self, index)
                    return

    # window-level drops: tabs from other windows, files from the file manager
    def dragEnterEvent(self, e):
        m = e.mimeData()
        if m.hasFormat(MIME_TAB) or m.hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        m = e.mimeData()
        if m.hasFormat(MIME_TAB):
            self.accept_tab_drop(m)
            e.setDropAction(Qt.MoveAction)
            e.accept()
        elif m.hasUrls():
            self.open_files([u.toLocalFile() for u in m.urls() if u.isLocalFile()])
            e.acceptProposedAction()

    # --- files --------------------------------------------------------------
    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open", dialogs.settings().value("last_dir", os.path.expanduser("~")),
                                                "PDF files (*.pdf);;Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp);;All files (*)")
        self.open_files(files)

    def open_when_shown(self, files):
        """Open files once the window is on screen, so a launch shows the window straight
        away, saying what it's opening, instead of nothing until the document is loaded."""
        if not files:
            return
        self._pending_files = files
        names = ", ".join(os.path.basename(f) for f in files[:2]) + (", …" if len(files) > 2 else "")
        self.empty.setText(f"Opening {names}…")
        self.empty.installEventFilter(self)
        QApplication.setOverrideCursor(Qt.BusyCursor)
        QTimer.singleShot(1000, self._open_pending)   # in case the window is never drawn (e.g. starts minimised)

    def eventFilter(self, obj, e):
        if obj is self.empty and e.type() == QEvent.Paint and self._pending_files:
            QTimer.singleShot(0, self._open_pending)   # after this paint reaches the screen
        return super().eventFilter(obj, e)

    def _open_pending(self):
        files, self._pending_files = self._pending_files, None
        if files is None:
            return
        self.empty.removeEventFilter(self)
        try:
            self.open_files(files)
        finally:
            QApplication.restoreOverrideCursor()
            self.empty.setText(EMPTY_TEXT)

    def open_files(self, files):
        for path in files:
            path = os.path.abspath(path)
            dialogs.settings().setValue("last_dir", os.path.dirname(path))
            existing = next(((w, t) for w in WINDOWS for t in w.doc_tabs() if t.pdoc.path == path), None)
            if existing:
                w, t = existing
                w.tabs.setCurrentWidget(t)
                w.raise_()
                remember_recent(path)
                continue
            try:
                if is_image(path):
                    pdoc = PdfDocument(load_any(path, dialogs.settings().value("images/page_size", "Letter")),
                                       title=os.path.splitext(os.path.basename(path))[0] + ".pdf")
                    pdoc.set_modified(True)
                else:
                    doc = load_any(path)
                    if doc.needs_pass and not self.unlock(doc, path):
                        continue
                    pdoc = PdfDocument(doc, path=path)
            except Exception as exc:
                QMessageBox.warning(self, "Open", f"Could not open {os.path.basename(path)}:\n{exc}")
                continue
            self.add_doc(pdoc)
            if pdoc.path:
                remember_recent(pdoc.path)

    def fill_recent_menu(self):
        """Rebuilt each time it opens, so every window shows the same, current list."""
        m = self.recent_menu
        m.clear()
        files = recent_files()
        if not files:
            m.addAction("No recent documents").setEnabled(False)
            return
        for n, path in enumerate(files):
            name = os.path.basename(path).replace("&", "&&")
            label = f"&{n + 1}  {name}" if n < 9 else f"    {name}"
            act = m.addAction(f"{label}\t{short_folder(path).replace('&', '&&')}",
                              lambda path=path: self.open_files([path]))
            act.setStatusTip(path)
            act.setToolTip(path)
            if not os.path.exists(path):
                act.setEnabled(False)
                act.setText(f"{label}\tnot found")
        m.setToolTipsVisible(True)
        m.addSeparator()
        m.addAction("Clear Recent Documents", lambda: dialogs.settings().remove("recent_files"))

    def unlock(self, doc, path):
        while True:
            pw, ok = QInputDialog.getText(self, "Password", f"{os.path.basename(path)} is password protected:",
                                          QLineEdit.Password)
            if not ok:
                return False
            if doc.authenticate(pw):
                return True

    def save(self, tab=None):
        tab = tab or self.tab
        if not tab:
            return False
        if not tab.pdoc.path:
            return self.save_as(tab)
        return self._write(tab, tab.pdoc.path)

    def save_as(self, tab=None):
        tab = tab if isinstance(tab, DocTab) else self.tab
        if not tab:
            return False
        start = tab.pdoc.path or os.path.join(dialogs.settings().value("last_dir", os.path.expanduser("~")),
                                              tab.pdoc.title if tab.pdoc.title.endswith(".pdf") else tab.pdoc.title + ".pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save As", start, "PDF files (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return self._write(tab, path)

    def _write(self, tab, path):
        n = tab.pdoc.redaction_count()
        if n:
            box = QMessageBox(QMessageBox.Warning, "Unapplied redactions",
                              f"{n} area(s) are marked for redaction but not yet applied, so the content "
                              "underneath is still in the file.", parent=self)
            apply = box.addButton("Apply and Save", QMessageBox.AcceptRole)
            box.addButton("Save with Marks Only", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is apply:
                tab.pdoc.apply_redactions()
            elif box.clickedButton() is box.button(QMessageBox.Cancel):
                return False
        try:
            tab.pdoc.save(path)
        except Exception as exc:
            QMessageBox.warning(self, "Save", f"Could not save:\n{exc}")
            return False
        dialogs.settings().setValue("last_dir", os.path.dirname(path))
        remember_recent(path)
        tab.update_title()
        self.statusBar().showMessage(f"Saved {path}", 5000)
        return True

    def maybe_save(self, tab):
        if not tab.pdoc.modified:
            return True
        r = QMessageBox.question(self, "Unsaved changes", f"Save changes to {tab.pdoc.title}?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save(tab)
        return r == QMessageBox.Discard

    def close_tab(self, tab):
        self.tabs.setCurrentWidget(tab)
        if not self.maybe_save(tab):
            return False
        self.detach_tab(tab)
        tab.pdoc.doc.close()
        tab.deleteLater()
        return True

    def closeEvent(self, e):
        for t in self.doc_tabs():
            if not self.close_tab(t):
                e.ignore()
                return
        if self in WINDOWS:
            WINDOWS.remove(self)
        e.accept()

    # --- edit ---------------------------------------------------------------
    def copy(self):
        t = self.tab
        if not t:
            return
        if t.thumbs.hasFocus():
            t.copy_pages()
        elif not t.view.copy_text():
            self.statusBar().showMessage("Select some text first, or click in the thumbnails to copy pages.", 4000)

    def cut(self):
        if self.tab and self.tab.thumbs.hasFocus():
            self.tab.cut_pages()

    def select_all(self):
        t = self.tab
        if t:
            t.thumbs.selectAll() if t.thumbs.hasFocus() else t.view.select_all_on_page()

    # --- tools --------------------------------------------------------------
    def combine(self, images_only=False):
        dlg = dialogs.CombineDialog(self, images_only=images_only)
        if not dlg.exec() or not dlg.files():
            return
        size = dlg.size_choice()
        out = fitz.open()
        for f in dlg.files():
            try:
                out.insert_pdf(load_any(f, size))
            except Exception as exc:
                QMessageBox.warning(self, "Combine", f"Skipped {os.path.basename(f)}:\n{exc}")
        if out.page_count:
            pdoc = PdfDocument(out, title="Images.pdf" if images_only else "Combined.pdf")
            pdoc.set_modified(True)
            self.add_doc(pdoc)

    def bates(self):
        t = self.tab
        tabs = self.doc_tabs()
        dlg = dialogs.BatesDialog(self, t.pdoc.page_count, len(tabs))
        if not dlg.exec():
            return
        targets = tabs if dlg.all_docs.isChecked() else [t]
        n = dlg.start.value()
        first = n
        for tab in targets:
            tab.pdoc.checkpoint()
            n = dialogs.stamp_bates(tab.pdoc.doc, n, **dlg.values())
            tab.pdoc.edited(range(tab.pdoc.page_count))
        dlg.remember(n)
        self.statusBar().showMessage(f"Bates numbered {dlg.fmt(first)} to {dlg.fmt(n - 1)}.", 8000)

    def _need_ocrmypdf(self):
        if dialogs.ocrmypdf_available():
            return True
        QMessageBox.information(self, "OCRmyPDF needed", "This needs OCRmyPDF and Tesseract:\n\nsudo apt install ocrmypdf tesseract-ocr")
        return False

    def ocr(self):
        if not self._need_ocrmypdf():
            return
        dlg = dialogs.OcrDialog(self)
        if dlg.exec():
            self.jobs.add(ExternalJob(self, self.tab, dlg.args(), "OCR"))

    def pdfa(self):
        if not self._need_ocrmypdf():
            return
        if self.tab.pdoc.redaction_count() and not self._ask_apply_redactions("converting"):
            return
        dlg = dialogs.PdfaDialog(self)
        if dlg.exec():
            self.jobs.add(ExternalJob(self, self.tab, dlg.args(), "PDF/A conversion"))

    def _ask_apply_redactions(self, doing):
        r = QMessageBox.question(self, "Unapplied redactions",
                                 f"Some content is marked for redaction but not yet removed. Apply the redactions before {doing}?",
                                 QMessageBox.Yes | QMessageBox.Cancel)
        if r == QMessageBox.Yes:
            self.tab.pdoc.apply_redactions()
            return True
        return False

    def flatten(self):
        t = self.tab
        if t.pdoc.redaction_count() and not self._ask_apply_redactions("flattening"):
            return
        r = QMessageBox.question(self, "Flatten", "Merge all annotations and form fields into the page content? "
                                 "They will no longer be editable (Undo is available until you close the file).")
        if r == QMessageBox.Yes:
            t.pdoc.flatten()
            self.statusBar().showMessage("Flattened.", 5000)

    def redact_search(self):
        t = self.tab
        term, ok = QInputDialog.getText(self, "Mark Text for Redaction",
                                        "Mark every occurrence of (not case-sensitive):")
        if not ok or not term.strip():
            return
        hits = [(i, r) for i in range(t.pdoc.page_count) for r in t.pdoc.doc[i].search_for(term)]
        if not hits:
            QMessageBox.information(self, "Mark Text for Redaction", f"“{term}” was not found.")
            return
        t.pdoc.checkpoint()
        pages = set()
        for i, r in hits:
            t.pdoc.doc[i].add_redact_annot(r, fill=(0, 0, 0))
            pages.add(i)
        t.pdoc.edited(sorted(pages))
        self.statusBar().showMessage(f"Marked {len(hits)} occurrence(s) on {len(pages)} page(s). "
                                     "Review them, then Apply Redactions.", 10000)

    def apply_redactions(self):
        t = self.tab
        n = t.pdoc.redaction_count()
        if not n:
            QMessageBox.information(self, "Apply Redactions", "Nothing is marked for redaction yet. "
                                    "Use the Redact tool to draw boxes, or Tools › Mark Text for Redaction.")
            return
        r = QMessageBox.question(self, "Apply Redactions", f"Permanently remove the content under {n} marked area(s)? "
                                 "Text, images and drawings beneath the marks are deleted, not just covered.")
        if r == QMessageBox.Yes:
            pages = t.pdoc.apply_redactions()
            self.statusBar().showMessage(f"Redactions applied on {pages} page(s). Save to make them permanent.", 8000)

    def about(self):
        QMessageBox.about(self, "Kosmic PDF", f"Kosmic PDF {QApplication.instance().applicationVersion()}\n"
                          "A lightweight PDF viewer and editor.\n\n"
                          f"PyMuPDF {fitz.VersionBind}, Qt {qVersion()}\n"
                          "OCR and PDF/A by OCRmyPDF and Tesseract.")
