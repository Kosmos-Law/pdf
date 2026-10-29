"""Document model and helpers shared by the rest of the app.

PyMuPDF reports text and annotation coordinates in the page's *unrotated*
space; what the user sees is the rotated page. Convert with
``page.derotation_matrix`` (screen -> PDF) and ``page.rotation_matrix``
(PDF -> screen).
"""
import itertools
import os
import time

import pymupdf as fitz
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QObject, Signal
from PySide6.QtGui import QImageIOHandler, QImageReader

MIME_PAGES = "application/x-kosmicpdf-pages"    # PDF bytes of the dragged/copied pages
MIME_SOURCE = "application/x-kosmicpdf-source"  # "pid:doc_uid:i,j,k" so a drop knows where pages came from
MIME_TAB = "application/x-kosmicpdf-tab"        # "pid:id(DocTab)" for dragging tabs between windows

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".jxr", ".pnm", ".pbm", ".pgm", ".ppm"}
PAGE_SIZES = {
    "Letter": (612, 792),
    "Legal": (612, 1008),
    "A4": (595, 842),
}
UNDO_LIMIT = 20
SCAN_IMAGE_SHARE = 0.25   # images covering this much of a page, with no text, look like a scan


REDACT_MARK = (0.18, 0.2, 0.25)   # slate


def mark_redaction(page, rect):
    """Mark rect on page for redaction. Once redactions are applied, the content under
    it is removed and a black box left in its place. Until then the mark is drawn
    lightly: a faint slate outline, without the red box and cross MuPDF draws by default
    (Kosmic PDF lays a see-through wash over it as well; see PageView.paint_overlays)."""
    a = page.add_redact_annot(fitz.Rect(rect), fill=(0, 0, 0))
    a.set_colors(stroke=REDACT_MARK)
    a.set_opacity(0.45)
    a.update(cross_out=False)
    return a


def page_needs_ocr(page):
    """True for a page that looks like a scan with no text layer: no text that can be
    selected or searched, and an image covering a good part of the page. (A blank page,
    or one with only a small logo, doesn't need OCR.)"""
    if not page.get_images() or page.get_text("text").strip():
        return False
    # Added up, since some scanners store a page as several strips.
    covered = sum(abs(fitz.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return covered >= SCAN_IMAGE_SHARE * abs(page.rect)


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def image_to_pdf(path, page_size="Letter"):
    """Return a PDF (fitz.Document) holding the image's page(s).

    page_size is a key of PAGE_SIZES (image fitted, orientation chosen to
    match) or "Image" to keep the image's own size at its stated resolution.
    Camera images are turned upright according to their EXIF orientation.
    """
    data = open(path, "rb").read()
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    if reader.imageCount() <= 1:
        img = reader.read()
        if not img.isNull() and reader.transformation() != QImageIOHandler.TransformationNone:
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "JPEG", 92)
            data, ext = bytes(buf.data()), "jpg"
    with fitz.open(stream=data, filetype=ext) as img_doc:
        src = fitz.open("pdf", img_doc.convert_to_pdf())
    if page_size not in PAGE_SIZES:
        return src
    out = fitz.open()
    w, h = PAGE_SIZES[page_size]
    for i, page in enumerate(src):
        landscape = page.rect.width > page.rect.height
        new = out.new_page(width=h if landscape else w, height=w if landscape else h)
        new.show_pdf_page(new.rect, src, i)
    return out


def load_any(path, page_size="Letter"):
    """Open a PDF or image file and return a fitz PDF document."""
    if is_image(path):
        return image_to_pdf(path, page_size)
    doc = fitz.open(stream=open(path, "rb").read(), filetype="pdf")
    return doc


def pages_mime(pdoc, pages):
    """Mime data carrying the given pages as a standalone PDF."""
    data = pdoc.extract_bytes(pages)
    mime = QMimeData()
    mime.setData(MIME_PAGES, QByteArray(data))
    mime.setData("application/pdf", QByteArray(data))
    mime.setData(MIME_SOURCE, QByteArray(f"{os.getpid()}:{pdoc.uid}:{','.join(map(str, pages))}".encode()))
    return mime


def parse_source(mime):
    """Return (doc_uid, pages) if the mime came from this process, else (None, None)."""
    if not mime.hasFormat(MIME_SOURCE):
        return None, None
    pid, uid, pages = bytes(mime.data(MIME_SOURCE)).decode().split(":")
    if int(pid) != os.getpid():
        return None, None
    return int(uid), [int(p) for p in pages.split(",") if p]


def mime_pdf_bytes(mime):
    for fmt in (MIME_PAGES, "application/pdf"):
        if mime.hasFormat(fmt):
            return bytes(mime.data(fmt))
    return None


def parse_da_fontsize(doc, annot, default=12.0):
    """Font size from a FreeText annotation's /DA string (e.g. '/Helv 12 Tf 0 g')."""
    kind, da = doc.xref_get_key(annot.xref, "DA")
    parts = da.strip("()").split()
    if "Tf" in parts:
        try:
            return float(parts[parts.index("Tf") - 1])
        except (ValueError, IndexError):
            pass
    return default


class PdfDocument(QObject):
    """A PDF open in a tab, with snapshot-based undo.

    Every mutating operation calls checkpoint() first, which keeps a copy of
    the document bytes. That makes undo exact for every kind of edit at the
    cost of memory, which is fine for the documents a law office handles.
    """
    structure_changed = Signal()      # pages added/removed/reordered, or the whole doc replaced
    pages_changed = Signal(list)      # contents of these page indices changed
    modified_changed = Signal(bool)
    _uids = itertools.count(1)

    def __init__(self, doc=None, path=None, title=None):
        super().__init__()
        self.uid = next(self._uids)
        self.doc = doc if doc is not None else fitz.open()
        self.path = path
        self.title = title or (os.path.basename(path) if path else "Untitled")
        self.folder = os.path.dirname(path) if path else None   # where Save As starts
        self.was_encrypted = bool(self.doc.is_encrypted)
        self.modified = False
        self.generation = 0           # bumped whenever cached renders may be stale wholesale
        self._versions = {}           # page xref -> edit counter, for render cache keys
        self._needs_ocr = {}          # page key -> page_needs_ocr(), so edits only recheck their pages
        self._undo, self._redo = [], []

    # --- identity / caching -------------------------------------------------
    @property
    def page_count(self):
        return self.doc.page_count

    def key(self, i):
        xref = self.doc.page_xref(i)
        return (self.uid, self.generation, xref, self._versions.get(xref, 0))

    def touch(self, pages):
        for i in pages:
            xref = self.doc.page_xref(i)
            self._versions[xref] = self._versions.get(xref, 0) + 1

    def set_modified(self, value=True):
        if value != self.modified:
            self.modified = value
            self.modified_changed.emit(value)

    def display_name(self):
        return self.title + (" *" if self.modified else "")

    def needs_ocr(self, budget=None):
        """Whether any page looks like a scan without text. With a time budget in seconds,
        returns None if there wasn't time to look at every page; the pages already looked
        at are remembered, so the next call carries on from there."""
        start = time.monotonic()
        for i in range(self.page_count):
            k = self.key(i)
            if k not in self._needs_ocr:
                if budget is not None and time.monotonic() - start > budget:
                    return None
                self._needs_ocr[k] = page_needs_ocr(self.doc[i])
            if self._needs_ocr[k]:
                return True
        return False

    # --- undo ---------------------------------------------------------------
    def checkpoint(self):
        self._undo.append(self.doc.tobytes())
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if self._undo:
            self._redo.append(self.doc.tobytes())
            self.replace(self._undo.pop(), checkpoint=False)

    def redo(self):
        if self._redo:
            self._undo.append(self.doc.tobytes())
            self.replace(self._redo.pop(), checkpoint=False)

    def replace(self, data, checkpoint=True):
        """Swap in new document bytes (undo, OCR output, PDF/A output)."""
        if checkpoint:
            self.checkpoint()
        self.doc.close()
        self.doc = fitz.open("pdf", data)
        self.generation += 1
        self._versions.clear()
        self._needs_ocr.clear()
        self.set_modified(True)
        self.structure_changed.emit()

    # --- page operations ----------------------------------------------------
    def edited(self, pages):
        """Call after changing page contents in place (annotations, stamps)."""
        self.touch(pages)
        self.set_modified(True)
        self.pages_changed.emit(list(pages))

    def rotate(self, pages, delta):
        self.checkpoint()
        for i in pages:
            page = self.doc[i]
            page.set_rotation((page.rotation + delta) % 360)
        self.edited(pages)

    def delete_pages(self, pages):
        self.checkpoint()
        self.doc.delete_pages(sorted(set(pages)))
        self.set_modified(True)
        self.structure_changed.emit()

    def move_pages(self, pages, dest):
        """Move pages so they sit before original index `dest`. Returns their new indices."""
        pages = sorted(set(pages))
        moving = set(pages)
        before = [i for i in range(dest) if i not in moving]
        after = [i for i in range(dest, self.page_count) if i not in moving]
        order = before + pages + after
        if order == list(range(self.page_count)):
            return pages
        self.checkpoint()
        self.doc.select(order)
        self.set_modified(True)
        self.structure_changed.emit()
        return list(range(len(before), len(before) + len(pages)))

    def extract_bytes(self, pages):
        out = fitz.open()
        for i in pages:
            out.insert_pdf(self.doc, from_page=i, to_page=i)
        return out.tobytes(garbage=3, deflate=True)

    def insert_doc(self, src, at):
        """Insert all pages of fitz document `src` before index `at`. Returns new indices."""
        at = max(0, min(at, self.page_count))
        n = src.page_count
        if not n:
            return []
        self.checkpoint()
        self.doc.insert_pdf(src, start_at=at if at < self.page_count else -1)
        self.set_modified(True)
        self.structure_changed.emit()
        return list(range(at, at + n))

    def insert_bytes(self, data, at):
        with fitz.open("pdf", data) as src:
            return self.insert_doc(src, at)

    def insert_blank(self, at):
        ref = self.doc[min(at, self.page_count - 1)].rect if self.page_count else fitz.paper_rect("letter")
        self.checkpoint()
        self.doc.new_page(pno=at if at < self.page_count else -1, width=ref.width, height=ref.height)
        self.set_modified(True)
        self.structure_changed.emit()

    # --- redaction / flatten ------------------------------------------------
    def redaction_count(self):
        return sum(1 for page in self.doc for a in page.annots(types=[fitz.PDF_ANNOT_REDACT]))

    def redacted_copy(self):
        """A new, unsaved document with everything marked for redaction removed, named
        "<title> - Redacted.pdf" for the same folder. This document is left as it is, so
        redacting never changes the original; and the copy has no undo history, so the
        removed content can't be brought back into it."""
        doc = fitz.open("pdf", self.doc.tobytes())
        for page in doc:
            if any(True for _ in page.annots(types=[fitz.PDF_ANNOT_REDACT])):
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        copy = PdfDocument(doc, title=f"{os.path.splitext(self.title)[0]} - Redacted.pdf")
        copy.folder = self.folder
        copy.set_modified(True)
        return copy

    def flatten(self):
        self.checkpoint()
        self.doc.bake(annots=True, widgets=True)
        self.generation += 1
        self.set_modified(True)
        self.structure_changed.emit()

    # --- saving -------------------------------------------------------------
    def save(self, path):
        """Full rewrite with garbage collection, so redacted content does not
        survive in orphaned objects, written atomically next to the target."""
        tmp = path + ".kosmicpdf-tmp"
        enc = fitz.PDF_ENCRYPT_KEEP if self.was_encrypted else fitz.PDF_ENCRYPT_NONE
        self.doc.save(tmp, garbage=3, deflate=True, encryption=enc)
        os.replace(tmp, path)
        self.path = path
        self.title = os.path.basename(path)
        self.folder = os.path.dirname(path)
        self.generation += 1          # garbage collection may renumber page xrefs
        self._versions.clear()
        self.modified = None          # force the signal so the tab title refreshes
        self.set_modified(False)

    def to_bytes(self):
        return self.doc.tobytes(garbage=3, deflate=True)
