"""Printing: the system's print dialog, then each page drawn by MuPDF at the printer's
resolution (up to PRINT_DPI), so annotations, highlights, typewriter notes and exhibit
labels print just as they look on screen."""
import pymupdf as fitz
from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QImage, QPageLayout, QPainter
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QHBoxLayout, QProgressDialog

PRINT_DPI = 300     # enough for crisp text and scans, without each page taking a great deal of memory

_printer = None     # kept between prints, so the printer and settings chosen last time are offered again


def printer():
    global _printer
    if _printer is None:
        _printer = QPrinter(QPrinter.HighResolution)
    return _printer


def chosen_pages(p, count, current, selected):
    """The page indexes (from 0) that the print dialog's choices on printer p call for."""
    rng = p.printRange()
    if rng == QPrinter.CurrentPage:
        return [current]
    if rng == QPrinter.Selection and selected:
        return list(selected)
    if rng == QPrinter.PageRange:
        ranges = p.pageRanges()
        if not ranges.isEmpty():
            return [i for i in range(count) if ranges.contains(i + 1)]
        lo, hi = max(1, p.fromPage()), min(count, p.toPage() or count)
        return list(range(lo - 1, hi))
    return list(range(count))


def print_pages(p, doc, pages, progress=None):
    """Print the given pages of the fitz document doc on printer p. Each page is printed at
    its actual size if it fits within the printable area, and otherwise shrunk to fit,
    centred, and turned a quarter-turn when that suits the paper better (a landscape page
    on portrait paper). progress(n), if given, is called before each page and returns False
    to cancel. True if every page was sent to the printer."""
    p.setFullPage(False)
    # As small as the printer allows (Qt keeps them to its minimum), so nothing is shrunk more than it must be.
    p.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
    painter = QPainter()
    if not painter.begin(p):
        return False
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    gray = p.colorMode() == QPrinter.GrayScale
    res = p.resolution()
    area = QRectF(p.pageRect(QPrinter.DevicePixel))
    area.moveTo(0, 0)                  # the painter's origin is the printable area's corner
    try:
        for n, i in enumerate(pages):
            if progress and not progress(n):
                p.abort()
                return False
            if n:
                p.newPage()
            page = doc[i]
            w_pt, h_pt = page.rect.width, page.rect.height
            turn = (w_pt > h_pt) != (area.width() > area.height()) and abs(w_pt - h_pt) > 1
            if turn:
                w_pt, h_pt = h_pt, w_pt
            # device pixels per point, at actual size, then shrunk if the page doesn't fit
            scale = min(res / 72, area.width() / w_pt, area.height() / h_pt)
            target = QRectF(0, 0, w_pt * scale, h_pt * scale)
            target.moveCenter(area.center())
            zoom = min(scale, PRINT_DPI / 72)
            m = fitz.Matrix(zoom, zoom)
            if turn:
                m.prerotate(-90)        # its top to the left, as printers turn landscape pages
            pix = page.get_pixmap(matrix=m, alpha=False, colorspace=fitz.csGRAY if gray else fitz.csRGB)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_Grayscale8 if gray else QImage.Format_RGB888)
            painter.drawImage(target, img)
            del img, pix
    finally:
        painter.end()
    return True


def arrange_dialog(dlg):
    """Qt's own print dialog (Linux), rearranged: its options (copies, page range and so on)
    always shown, without the Options button that hides them, and Cancel at the left, away
    from Print. On Windows the system's own dialog is shown instead, and this changes nothing."""
    box = dlg.findChild(QDialogButtonBox)
    if box is None:
        return
    keep = (box.button(QDialogButtonBox.Ok), box.button(QDialogButtonBox.Cancel))
    for b in box.buttons():
        if b not in keep:              # "Options >>": open the options, then take the button away
            b.click()
            box.removeButton(b)
            b.deleteLater()
    cancel = keep[1]
    layout = dlg.layout()
    if cancel is None or layout is None or layout.indexOf(box) < 0:
        return
    box.removeButton(cancel)
    cancel.clicked.connect(dlg.reject)
    row = QHBoxLayout()
    i = layout.indexOf(box)
    layout.removeWidget(box)
    row.addWidget(cancel)
    row.addStretch()
    row.addWidget(box)
    layout.insertLayout(i, row)


def print_dialog(parent, doc, title, current=0, selected=()):
    """Show the print dialog for the fitz document doc, then print what was chosen, with a
    progress window that can cancel it. selected: the pages chosen in the page panel, offered
    as "Selection" when there are any. True if it printed, False if cancelled, None if the
    printer could not be started."""
    p = printer()
    p.setDocName(title)
    count = doc.page_count
    dlg = QPrintDialog(p, parent)
    dlg.setWindowTitle("Print")
    dlg.setOption(QAbstractPrintDialog.PrintPageRange, True)
    dlg.setOption(QAbstractPrintDialog.PrintCurrentPage, True)
    dlg.setOption(QAbstractPrintDialog.PrintSelection, bool(selected))
    dlg.setOption(QAbstractPrintDialog.PrintCollateCopies, True)
    dlg.setMinMax(1, count)
    p.setFromTo(1, count)
    p.setPrintRange(QPrinter.Selection if len(selected) > 1 else QPrinter.AllPages)
    arrange_dialog(dlg)
    if dlg.exec() != QPrintDialog.Accepted:
        return False
    pages = [i for i in chosen_pages(p, count, current, selected) if 0 <= i < count]
    if not pages:
        return False
    bar = QProgressDialog("Sending pages to the printer…", "Cancel", 0, len(pages), parent)
    bar.setWindowTitle("Print")
    bar.setWindowModality(Qt.WindowModal)
    bar.setMinimumDuration(500)

    def progress(n):
        bar.setValue(n)
        bar.setLabelText(f"Sending page {n + 1} of {len(pages)} to the printer…")
        QApplication.processEvents()
        return not bar.wasCanceled()

    QApplication.setOverrideCursor(Qt.BusyCursor)
    try:
        if not print_pages(p, doc, pages, progress):
            return False if bar.wasCanceled() else None
    finally:
        QApplication.restoreOverrideCursor()
        bar.close()
    return True
