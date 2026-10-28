"""Dialogs: Bates numbering, combine files, OCR, PDF/A."""
import os
import shutil
import subprocess

import pymupdf as fitz
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout)

from .core import PAGE_SIZES

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


class BatesDialog(QDialog):
    def __init__(self, parent, page_count, open_doc_count):
        super().__init__(parent)
        self.setWindowTitle("Bates Numbering")
        self.page_count = page_count
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
        self.all_docs = QCheckBox(f"Number all {open_doc_count} open files in this window, in tab order")
        self.all_docs.setVisible(open_doc_count > 1)
        self.preview = QLabel()

        form = QFormLayout()
        form.addRow("Prefix", self.prefix)
        form.addRow("Start at", self.start)
        form.addRow("Digits", self.digits)
        form.addRow("Suffix", self.suffix)
        form.addRow("Position", self.position)
        form.addRow("Font size", self.font_size)
        form.addRow("Margin", self.margin)
        form.addRow("", self.background)
        form.addRow("", self.all_docs)
        form.addRow("Preview", self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("Numbers are stamped into the page content, so they print and cannot be moved.\n"
                             "Undo is available until you close the file."))
        lay.addWidget(buttons)
        for w in (self.prefix, self.suffix):
            w.textChanged.connect(self._update)
        for w in (self.start, self.digits):
            w.valueChanged.connect(self._update)
        self._update()

    def fmt(self, n):
        return f"{self.prefix.text()}{n:0{self.digits.value()}d}{self.suffix.text()}"

    def _update(self):
        a = self.start.value()
        self.preview.setText(f"{self.fmt(a)}  …  {self.fmt(a + self.page_count - 1)} (this file)")

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


class CombineDialog(QDialog):
    """Pick and order PDFs and images to combine into one new PDF."""

    def __init__(self, parent, files=(), images_only=False):
        super().__init__(parent)
        self.setWindowTitle("Images to PDF" if images_only else "Combine Files")
        self.images_only = images_only
        self.resize(560, 420)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for f in files:
            self.list.addItem(f)
        add = QPushButton("Add files…", clicked=self.add_files)
        remove = QPushButton("Remove", clicked=lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        up = QPushButton("Move up", clicked=lambda: self._move(-1))
        down = QPushButton("Move down", clicked=lambda: self._move(1))
        sort = QPushButton("Sort by name", clicked=lambda: self.list.sortItems())
        side = QVBoxLayout()
        for b in (add, remove, up, down, sort):
            side.addWidget(b)
        side.addStretch()
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(side)
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
        lay.addWidget(QLabel("Drag to reorder. The files are combined top to bottom into a new, unsaved PDF."))
        lay.addLayout(row)
        lay.addLayout(size_row)
        lay.addWidget(buttons)
        if not files:
            self.add_files()

    def add_files(self):
        filt = ("Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)" if self.images_only else
                "PDFs and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp);;All files (*)")
        files, _ = QFileDialog.getOpenFileNames(self, "Add files", settings().value("last_dir", os.path.expanduser("~")), filt)
        for f in files:
            self.list.addItem(f)
        if files:
            settings().setValue("last_dir", os.path.dirname(files[0]))

    def _move(self, step):
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=step > 0)
        for r in rows:
            nr = r + step
            if 0 <= nr < self.list.count():
                it = self.list.takeItem(r)
                self.list.insertItem(nr, it)
                it.setSelected(True)

    def files(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def size_choice(self):
        settings().setValue("images/page_size", self.page_size.currentText())
        idx = self.page_size.currentIndex()
        return list(PAGE_SIZES)[idx] if idx < len(PAGE_SIZES) else "Image"


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
