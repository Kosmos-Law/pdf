"""Dialogs: Bates numbering (one document, or several files), combine files, OCR, PDF/A."""
import os
import shutil
import subprocess

import pymupdf as fitz
from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from .core import PAGE_SIZES, is_image, load_any

POSITIONS = ["Bottom right", "Bottom center", "Bottom left", "Top right", "Top center", "Top left"]


def settings():
    return QSettings("kosmicpdf", "kosmicpdf")


def stamp_bates(doc, start, prefix, digits, suffix, position, font_size, margin, background):
    """Stamp sequential Bates numbers into page content. Returns the next number."""
    n = start
    for page in doc:
        text = f"{prefix}{n:0{digits}d}{suffix}"
        width = fitz.get_text_length(text, "helv", font_size)
        W, H = page.rect.width, page.rect.height
        vert, horiz = position.split()
        x = {"left": margin, "center": (W - width) / 2, "right": W - margin - width}[horiz]
        y = H - margin if vert == "Bottom" else margin + font_size * 0.8
        if background:
            box = fitz.Rect(x - 3, y - font_size * 0.85, x + width + 3, y + font_size * 0.3)
            page.draw_rect(box * page.derotation_matrix, color=None, fill=(1, 1, 1), overlay=True)
        page.insert_text(fitz.Point(x, y) * page.derotation_matrix, text, fontsize=font_size,
                         fontname="helv", color=(0, 0, 0), rotate=page.rotation)
        n += 1
    return n


class BatesFields(QWidget):
    """The Bates settings (prefix, start, digits, …), shared by the two Bates dialogs and
    remembered between uses."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        s = settings()
        self.prefix = QLineEdit(s.value("bates/prefix", ""))
        self.start = QSpinBox(maximum=999_999_999, value=int(s.value("bates/next", 1)))
        self.digits = QSpinBox(minimum=1, maximum=12, value=int(s.value("bates/digits", 6)))
        self.suffix = QLineEdit(s.value("bates/suffix", ""))
        self.position = QComboBox()
        self.position.addItems(POSITIONS)
        self.position.setCurrentText(s.value("bates/position", "Bottom right"))
        self.font_size = QDoubleSpinBox(minimum=4, maximum=48, value=float(s.value("bates/size", 10)))
        self.margin = QDoubleSpinBox(minimum=0, maximum=144, value=float(s.value("bates/margin", 24)), suffix=" pt")
        self.background = QCheckBox("White box behind the number")
        self.background.setChecked(s.value("bates/background", "false") == "true")
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        for label, w in (("Prefix", self.prefix), ("Start at", self.start), ("Digits", self.digits),
                         ("Suffix", self.suffix), ("Position", self.position), ("Font size", self.font_size),
                         ("Margin", self.margin), ("", self.background)):
            self.form.addRow(label, w)
        for w in (self.prefix, self.suffix):
            w.textChanged.connect(self.changed)
        for w in (self.start, self.digits):
            w.valueChanged.connect(self.changed)

    def fmt(self, n):
        return f"{self.prefix.text()}{n:0{self.digits.value()}d}{self.suffix.text()}"

    def values(self):
        return dict(prefix=self.prefix.text(), digits=self.digits.value(), suffix=self.suffix.text(),
                    position=self.position.currentText(), font_size=self.font_size.value(),
                    margin=self.margin.value(), background=self.background.isChecked())

    def remember(self, next_number):
        s = settings()
        v = self.values()
        s.setValue("bates/prefix", v["prefix"])
        s.setValue("bates/digits", v["digits"])
        s.setValue("bates/suffix", v["suffix"])
        s.setValue("bates/position", v["position"])
        s.setValue("bates/size", v["font_size"])
        s.setValue("bates/margin", v["margin"])
        s.setValue("bates/background", "true" if v["background"] else "false")
        s.setValue("bates/next", next_number)


class BatesDialog(QDialog):
    """Bates numbers for the open document (or every open document in the window)."""

    def __init__(self, parent, page_count, open_doc_count):
        super().__init__(parent)
        self.setWindowTitle("Bates Numbering")
        self.page_count = page_count
        self.fields = BatesFields()
        self.start, self.fmt, self.values, self.remember = (self.fields.start, self.fields.fmt, self.fields.values,
                                                             self.fields.remember)
        self.all_docs = QCheckBox(f"Number all {open_doc_count} open files in this window, in tab order")
        self.all_docs.setVisible(open_doc_count > 1)
        self.preview = QLabel()
        self.fields.form.addRow("", self.all_docs)
        self.fields.form.addRow("Preview", self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.fields)
        lay.addWidget(QLabel("Numbers are stamped into the page content, so they print and cannot be moved.\n"
                             "Undo is available until you close the file."))
        lay.addWidget(buttons)
        self.fields.changed.connect(self._update)
        self._update()

    def _update(self):
        a = self.start.value()
        self.preview.setText(f"{self.fmt(a)}  …  {self.fmt(a + self.page_count - 1)} (this file)")


class FileList(QWidget):
    """Files to put in order: drag them, or Move Up / Move Down; Add Files, Sort by Name,
    and the Delete key to take the selected ones out. Each row shows label(path), the
    file's name unless a dialog says otherwise."""
    changed = Signal()

    def __init__(self, file_filter, label=os.path.basename):
        super().__init__()
        self.file_filter, self.label = file_filter, label
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setProperty("field", True)        # drawn like a text box (see theme.stylesheet)
        self.list.installEventFilter(self)
        self.list.model().rowsMoved.connect(self.changed)
        side = QVBoxLayout()
        for text, slot in (("Add Files…", self.add_files),
                           ("Move Up", lambda: self._move(-1)), ("Move Down", lambda: self._move(1)),
                           ("Sort by Name", self._sort)):
            side.addWidget(QPushButton(text, clicked=slot))
        side.addStretch()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.list, 1)
        row.addLayout(side)
        self.changed.connect(self.relabel)

    def eventFilter(self, obj, e):
        if obj is self.list and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._remove()
            return True
        return super().eventFilter(obj, e)

    def add(self, paths):
        for f in paths:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, f)
            it.setToolTip(f)
            self.list.addItem(it)
        if paths:
            self.changed.emit()

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add files", settings().value("last_dir", os.path.expanduser("~")),
                                                self.file_filter)
        if files:
            settings().setValue("last_dir", os.path.dirname(files[0]))
        self.add(files)

    def files(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def relabel(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setText(self.label(it.data(Qt.UserRole)))

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self.changed.emit()

    def _sort(self):
        items = sorted((self.list.takeItem(0) for _ in range(self.list.count())),
                       key=lambda it: os.path.basename(it.data(Qt.UserRole)).lower())
        for it in items:
            self.list.addItem(it)
        self.changed.emit()

    def _move(self, step):
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=step > 0)
        for r in rows:
            nr = r + step
            if 0 <= nr < self.list.count():
                it = self.list.takeItem(r)
                self.list.insertItem(nr, it)
                it.setSelected(True)
        self.changed.emit()


PDFS_AND_IMAGES = "PDFs and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp);;All files (*)"


class CombineDialog(QDialog):
    """Pick and order PDFs and images to combine into one new PDF."""

    def __init__(self, parent, files=(), images_only=False):
        super().__init__(parent)
        self.setWindowTitle("Images to PDF" if images_only else "Combine Files")
        self.images_only = images_only
        self.resize(560, 420)
        self.list = FileList("Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)" if images_only
                             else PDFS_AND_IMAGES, label=lambda f: f)
        self.list.add(list(files))
        self.page_size = QComboBox()
        self.page_size.addItems(list(PAGE_SIZES) + ["Image"])
        self.page_size.setItemText(len(PAGE_SIZES), "Image's own size")
        self.page_size.setCurrentText(settings().value("images/page_size", "Letter"))
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Page size for images:"))
        size_row.addWidget(self.page_size)
        size_row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create PDF")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Drag to reorder; Delete takes the selected files out. The files are combined "
                             "top to bottom into a new, unsaved PDF."))
        lay.addWidget(self.list, 1)
        lay.addLayout(size_row)
        lay.addWidget(buttons)
        if not files:
            self.list.add_files()

    def files(self):
        return self.list.files()

    def size_choice(self):
        settings().setValue("images/page_size", self.page_size.currentText())
        idx = self.page_size.currentIndex()
        return list(PAGE_SIZES)[idx] if idx < len(PAGE_SIZES) else "Image"


# --- Bates numbering several files -------------------------------------------------------------------
NAMINGS = {      # how numbered copies are named: (menu text, name for a file and its first Bates number)
    "keep": ("Keep each file's name", lambda stem, first: stem),
    "number": ("Name each file by its first Bates number", lambda stem, first: first),
    "both": ("First Bates number, then the file's name", lambda stem, first: f"{first} - {stem}"),
}


def page_count(path):
    """Pages in a PDF (1 for an image), or None if the file can't be read."""
    try:
        if is_image(path):
            return 1
        with fitz.open(path) as doc:
            return None if doc.needs_pass else doc.page_count
    except Exception:
        return None


def bates_name(path, first_label, naming):
    stem = os.path.splitext(os.path.basename(path))[0]
    return NAMINGS[naming][1](stem, first_label) + ".pdf"


def number_files(files, folder, naming, start, fields):
    """Bates number copies of files, in order, into folder: each continues the numbering
    from the one before. The originals aren't changed. `fields` gives the Bates
    settings (BatesFields.values() and .fmt). Returns [(new path, first, last)] and the
    next number."""
    os.makedirs(folder, exist_ok=True)
    done, n = [], start
    for f in files:
        doc = load_any(f, "Letter")
        first = n
        n = stamp_bates(doc, n, **fields.values())
        dst = os.path.join(folder, bates_name(f, fields.fmt(first), naming))
        tmp = dst + ".kosmicpdf-tmp"
        doc.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, dst)
        doc.close()
        done.append((dst, first, n - 1))
    return done, n


class BatesFilesDialog(QDialog):
    """Bates number a set of files, in an order the user sets, into numbered copies,
    optionally named by their first Bates number."""

    def __init__(self, parent, files=()):
        super().__init__(parent)
        self.setWindowTitle("Bates Number Files")
        self.resize(760, 640)
        self._pages = {}
        self.list = FileList(PDFS_AND_IMAGES, label=self._label)
        self.fields = BatesFields()
        self.naming = QComboBox()
        for key, (text, _) in NAMINGS.items():
            self.naming.addItem(text, key)
        self.naming.setCurrentIndex(max(0, self.naming.findData(settings().value("bates/naming", "keep"))))
        self.folder = QLineEdit()
        browse = QPushButton("Choose…", clicked=self._choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        self.example = QLabel()
        self.example.setForegroundRole(QPalette.PlaceholderText)
        self.fields.form.addRow("File names", self.naming)
        self.fields.form.addRow("", self.example)
        self.fields.form.addRow("Save copies in", folder_row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Number Files")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Drag to set the order: the numbering runs top to bottom, each file carrying on "
                             "from the one before.\nDelete takes the selected files out. Numbered copies are saved "
                             "in the folder below; the original files aren't changed."))
        lay.addWidget(self.list, 1)
        lay.addWidget(self.fields)
        lay.addWidget(buttons)
        self.list.changed.connect(self._update)
        self.fields.changed.connect(self.list.relabel)
        self.fields.changed.connect(self._update)
        self.naming.currentIndexChanged.connect(self._update)
        self.list.add(list(files))
        self._update()

    def _pages_of(self, f):
        if f not in self._pages:
            self._pages[f] = page_count(f)
        return self._pages[f]

    def ranges(self):
        """[(file, first, last)] in the list's order; first/last are None for a file that can't be read."""
        out, n = [], self.fields.start.value()
        for f in self.list.files():
            pages = self._pages_of(f)
            out.append((f, n, n + pages - 1) if pages else (f, None, None))
            n += pages or 0
        return out

    def _label(self, f):
        for path, a, b in self.ranges():
            if path == f:
                if a is None:
                    return f"{os.path.basename(f)}    (can't be read, or needs a password)"
                rng = self.fields.fmt(a) if a == b else f"{self.fields.fmt(a)} – {self.fields.fmt(b)}"
                return f"{os.path.basename(f)}    {rng}"
        return os.path.basename(f)

    def _update(self):
        files = self.list.files()
        if files and not self.folder.text():
            self.folder.setText(os.path.join(os.path.dirname(files[0]), "Bates Numbered"))
        example = files[0] if files else "Contract.pdf"
        self.example.setText("e.g. " + bates_name(example, self.fields.fmt(self.fields.start.value()), self.naming_key()))

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Save the numbered copies in", self.folder.text()
                                             or settings().value("last_dir", os.path.expanduser("~")))
        if d:
            self.folder.setText(d)

    def naming_key(self):
        return self.naming.currentData()

    def targets(self):
        folder = self.folder.text()
        return [os.path.join(folder, bates_name(f, self.fields.fmt(a), self.naming_key()))
                for f, a, _ in self.ranges()]

    def problem(self):
        """Why the files can't be numbered as set up, or None."""
        files = self.list.files()
        if not files:
            return "Add the files to number first."
        unreadable = [os.path.basename(f) for f, a, _ in self.ranges() if a is None]
        if unreadable:
            return ("These files can't be read, or need a password; remove them, or open and save them first:\n"
                    + "\n".join(unreadable))
        if not self.folder.text().strip():
            return "Choose a folder for the numbered copies."
        sources = {os.path.realpath(f) for f in files}
        targets = [os.path.realpath(t) for t in self.targets()]
        if sources & set(targets):
            return ("That would save over an original file. Choose another folder, or name the copies by "
                    "their Bates numbers.")
        if len(set(targets)) < len(targets):
            return "Two files would get the same name. Name the copies by their Bates numbers, or rename one."
        return None

    def accept(self):
        problem = self.problem()
        if problem:
            QMessageBox.information(self, "Bates Number Files", problem)
            return
        existing = [t for t in self.targets() if os.path.exists(t)]
        if existing:
            names = "\n".join(os.path.basename(t) for t in existing[:8]) + ("\n…" if len(existing) > 8 else "")
            r = QMessageBox.question(self, "Bates Number Files",
                                     f"{len(existing)} of the numbered copies are already in that folder:\n\n{names}"
                                     "\n\nReplace them?", QMessageBox.Yes | QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return
        settings().setValue("bates/naming", self.naming_key())
        super().accept()


def tesseract_languages():
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10).stdout
        return [l.strip() for l in out.splitlines()[1:] if l.strip() and l.strip() != "osd"]
    except (OSError, subprocess.SubprocessError):
        return []


class OcrDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("OCR (Make Searchable)")
        s = settings()
        self.langs = QListWidget()
        self.langs.setProperty("field", True)
        self.langs.setMaximumHeight(110)
        chosen = (s.value("ocr/langs", "eng") or "eng").split("+")
        for l in tesseract_languages():
            self.langs.addItem(l)
            it = self.langs.item(self.langs.count() - 1)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if l in chosen else Qt.Unchecked)
        self.skip = QRadioButton("Only pages without text (safe default)")
        self.redo = QRadioButton("Redo OCR on pages that already have an OCR layer")
        self.force = QRadioButton("Force: rasterize and OCR every page (loses vector text)")
        {"redo": self.redo, "force": self.force}.get(s.value("ocr/mode"), self.skip).setChecked(True)
        self.deskew = QCheckBox("Straighten crooked scans (deskew)")
        self.rotate = QCheckBox("Turn pages that were scanned sideways or upside down")
        self.rotate.setChecked(True)
        self.pdfa = QCheckBox("Output as PDF/A-2b")
        self.redo.toggled.connect(lambda on: self.deskew.setEnabled(not on))
        modes = QGroupBox("Pages")
        ml = QVBoxLayout(modes)
        for w in (self.skip, self.redo, self.force):
            ml.addWidget(w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Run OCR")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Languages"))
        lay.addWidget(self.langs)
        lay.addWidget(modes)
        for w in (self.deskew, self.rotate, self.pdfa):
            lay.addWidget(w)
        lay.addWidget(buttons)

    def args(self):
        langs = [self.langs.item(i).text() for i in range(self.langs.count())
                 if self.langs.item(i).checkState() == Qt.Checked] or ["eng"]
        mode = "redo" if self.redo.isChecked() else "force" if self.force.isChecked() else "skip"
        s = settings()
        s.setValue("ocr/langs", "+".join(langs))
        s.setValue("ocr/mode", mode)
        args = ["-l", "+".join(langs), {"skip": "--skip-text", "redo": "--redo-ocr", "force": "--force-ocr"}[mode]]
        if self.deskew.isChecked() and mode != "redo":
            args.append("--deskew")
        if self.rotate.isChecked():
            args.append("--rotate-pages")
        args += ["--output-type", "pdfa-2" if self.pdfa.isChecked() else "pdf"]
        return args


class PdfaDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Convert to PDF/A")
        self.level = QComboBox()
        self.level.addItem("PDF/A-2b (recommended; accepted by most courts and archives)", "pdfa-2")
        self.level.addItem("PDF/A-1b (oldest, strictest)", "pdfa-1")
        self.level.addItem("PDF/A-3b (allows embedded files)", "pdfa-3")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Convert")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.level)
        lay.addWidget(QLabel("The converted document replaces this tab's contents (Undo restores it).\n"
                             "Save afterwards to keep it. Conversion uses Ghostscript via OCRmyPDF;\n"
                             "no OCR is performed."))
        lay.addWidget(buttons)

    def args(self):
        return ["--skip-text", "--tesseract-timeout", "0", "--output-type", self.level.currentData()]


def ocrmypdf_available():
    return shutil.which("ocrmypdf") is not None
