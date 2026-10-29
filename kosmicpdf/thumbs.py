"""Thumbnail pane: page navigation, multi-select, drag to reorder or to another file."""
import pymupdf as fitz
from PySide6.QtCore import QItemSelectionModel, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem

from .core import MIME_PAGES, mime_pdf_bytes, pages_mime, parse_source
from .theme import Colors

THUMB_W, THUMB_H = 120, 156
CELL_W, CELL_H = THUMB_W + 22, THUMB_H + 30      # the least room each thumbnail takes


def framed(pm):
    """Thumbnail with a hairline border so white pages stand out on a light panel."""
    p = QPainter(pm)
    p.setPen(QPen(QColor(0, 0, 0, 55), 0))
    w, h = pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()
    p.drawRect(QRectF(0, 0, w - 1 / pm.devicePixelRatio(), h - 1 / pm.devicePixelRatio()))
    p.end()
    return pm


def thumb_icon(pm):
    # Same pixmap when selected: Qt would otherwise tint the page with the highlight colour.
    icon = QIcon(pm)
    icon.addPixmap(pm, QIcon.Selected)
    return icon


class ThumbPane(QListWidget):
    page_clicked = Signal(int)
    pages_dropped = Signal(bytes, int)        # pdf bytes from elsewhere, insert-before index
    files_dropped = Signal(list, int)         # local files, insert-before index
    context_requested = Signal(QPoint)
    command = Signal(str)                     # "copy", "cut", "paste", "delete" from the keyboard

    def __init__(self, pdoc, parent=None):
        super().__init__(parent)
        self.pdoc = pdoc
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(THUMB_W, THUMB_H))
        self.setGridSize(QSize(CELL_W, CELL_H))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        # Static movement (set above) quietly turns off drops on the viewport,
        # which is where the mouse actually is; switch them back on.
        self.viewport().setAcceptDrops(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_requested)
        self.setMinimumWidth(THUMB_W + 40)
        self.setFrameShape(QListWidget.NoFrame)

        self._cache = {}
        self._queue = set()
        self._timer = QTimer(self, interval=0, timeout=self._render_some)
        self._drop_at = None
        self._drag_pos = QPoint()
        self._scroll_timer = QTimer(self, interval=30, timeout=self._auto_scroll)
        self._syncing = False
        self._centre_soon = QTimer(self, singleShot=True, interval=0, timeout=self._centre_columns)
        self.placeholder = QPixmap(THUMB_W, THUMB_H)
        self.placeholder.fill(QColor("#ffffff"))
        self.placeholder = framed(self.placeholder)
        self.apply_colors(Colors())

        self.itemClicked.connect(lambda it: self.page_clicked.emit(self.row(it)))
        self.currentRowChanged.connect(self._row_changed)
        pdoc.structure_changed.connect(self.rebuild)
        pdoc.pages_changed.connect(self.refresh)
        self.rebuild()

    def apply_colors(self, colors):
        self.colors = colors
        c = colors
        self.setStyleSheet(
            f"QListWidget{{background:{c.panel.name()};color:{c.text.name()};outline:none;padding-top:8px;}}"
            f"QListWidget::item{{border-radius:6px;padding-top:4px;}}"
            f"QListWidget::item:hover{{background:{c.rgba(c.accent, 30)};}}"
            f"QListWidget::item:selected{{background:{c.rgba(c.accent, 70)};color:{c.text.name()};}}")
        self.viewport().update()

    # --- thumbnails ---------------------------------------------------------
    def rebuild(self):
        selected = self.selected_pages()
        current = max(0, self.currentRow())
        self._syncing = True
        self.clear()
        keys = {self.pdoc.key(i) for i in range(self.pdoc.page_count)}
        self._cache = {k: v for k, v in self._cache.items() if k in keys}
        for i in range(self.pdoc.page_count):
            it = QListWidgetItem(thumb_icon(self._cache.get(self.pdoc.key(i), self.placeholder)), str(i + 1))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
            self.addItem(it)
            if self.pdoc.key(i) not in self._cache:
                self._queue.add(i)
        if self.count():
            self.setCurrentRow(min(current, self.count() - 1), QItemSelectionModel.NoUpdate)
            self.select_pages([p for p in selected if p < self.count()])
        self._syncing = False
        self._timer.start()
        self._centre_soon.start()

    def refresh(self, pages):
        for i in pages:
            if i < self.count():
                self._queue.add(i)
        self._timer.start()

    def _render_some(self):
        if not self._queue:
            self._timer.stop()
            return
        first = self.indexAt(QPoint(5, 5)).row()
        last = self.indexAt(QPoint(self.viewport().width() - 5, self.viewport().height() - 5)).row()
        if last < 0:
            last = self.count() - 1
        visible = [i for i in self._queue if max(first, 0) <= i <= last + 4]
        batch = sorted(visible)[:4] or sorted(self._queue)[:4]
        dpr = self.devicePixelRatioF()
        for i in batch:
            self._queue.discard(i)
            if i >= self.pdoc.page_count:
                continue
            page = self.pdoc.doc[i]
            z = min(THUMB_W / page.rect.width, THUMB_H / page.rect.height) * dpr
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            pm = QPixmap.fromImage(QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy())
            pm.setDevicePixelRatio(dpr)
            pm = framed(pm)
            self._cache[self.pdoc.key(i)] = pm
            self.item(i).setIcon(thumb_icon(pm))

    # --- selection / sync with page view --------------------------------------
    def selected_pages(self):
        return sorted(self.row(it) for it in self.selectedItems())

    def select_pages(self, pages):
        self.clearSelection()
        for i in pages:
            if 0 <= i < self.count():
                self.item(i).setSelected(True)
        if pages:
            self.setCurrentRow(pages[0], QItemSelectionModel.NoUpdate)
            self.scrollToItem(self.item(pages[0]))

    def follow_page(self, i):
        """Page view scrolled to page i. Keep a deliberate multi-selection alone."""
        if i >= self.count():
            return
        self._syncing = True
        if len(self.selectedItems()) <= 1:
            self.setCurrentRow(i)
        else:
            self.setCurrentRow(i, QItemSelectionModel.NoUpdate)
        self.scrollToItem(self.item(i))
        self._syncing = False

    def _row_changed(self, row):
        if not self._syncing and row >= 0 and self.hasFocus():
            self.page_clicked.emit(row)

    def keyPressEvent(self, e):
        # Handle these here: QListWidget would otherwise copy the item label on Ctrl+C.
        for seq, cmd in ((QKeySequence.Copy, "copy"), (QKeySequence.Cut, "cut"),
                         (QKeySequence.Paste, "paste"), (QKeySequence.Delete, "delete")):
            if e.matches(seq):
                self.command.emit(cmd)
                return
        if e.key() == Qt.Key_Backspace:
            self.command.emit("delete")
            return
        super().keyPressEvent(e)

    # --- drag out -----------------------------------------------------------
    def startDrag(self, actions):
        pages = self.selected_pages()
        if not pages:
            return
        drag = QDrag(self)
        drag.setMimeData(pages_mime(self.pdoc, pages))
        icon = self.item(pages[0]).icon().pixmap(QSize(60, 78))
        if len(pages) > 1:
            icon = self._badge(icon, len(pages))
        drag.setPixmap(icon)
        drag.exec(Qt.MoveAction | Qt.CopyAction, Qt.MoveAction)
        self._drop_at = None
        self.viewport().update()

    def _badge(self, pm, n):
        out = QPixmap(pm.width() + 14, pm.height() + 14)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawPixmap(0, 8, pm)
        p.setBrush(self.colors.accent)
        p.setPen(Qt.NoPen)
        p.drawEllipse(out.width() - 26, 0, 26, 26)
        p.setPen(Qt.white)
        p.drawText(QRect(out.width() - 26, 0, 26, 26), Qt.AlignCenter, str(n))
        p.end()
        return out

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._centre_soon.start()

    def _centre_columns(self):
        """Centre the columns of thumbnails in the panel, with an equal margin on the left
        for the room Qt keeps on the right (for a scroll bar, which it reserves even before
        one is needed). The margin is measured from the first row as laid out, so the
        thumbnails stay centred whatever Qt has reserved."""
        if not self.count():
            return
        left = self.viewportMargins().left()
        full = self.viewport().width() + left
        y0 = self.visualItemRect(self.item(0)).y()
        cols = sum(1 for k in range(self.count()) if self.visualItemRect(self.item(k)).y() == y0)
        margin = max(0, (full - cols * self.gridSize().width()) // 2)
        if margin != left:
            self.setViewportMargins(margin, 0, 0, 0)
            self._centre_soon.start()        # check again once Qt has laid the thumbnails out anew

    # --- drop in ------------------------------------------------------------
    def _single_column(self):
        return self.viewport().width() < 2 * self.gridSize().width()

    def drop_index(self, pos):
        n = self.count()
        if n == 0:
            return 0
        idx = self.indexAt(pos)
        if not idx.isValid():
            best = min(range(n), key=lambda r: (self.visualRect(self.model().index(r, 0)).center() - pos).manhattanLength())
            idx = self.model().index(best, 0)
        r = self.visualRect(idx)
        after = pos.y() > r.center().y() if self._single_column() else pos.x() > r.center().x()
        return idx.row() + (1 if after else 0)

    def _accepts(self, mime):
        return mime.hasFormat(MIME_PAGES) or mime.hasFormat("application/pdf") or mime.hasUrls()

    def _is_internal(self, e):
        uid, _ = parse_source(e.mimeData())
        return uid == self.pdoc.uid and not (e.modifiers() & Qt.ControlModifier)

    def dragEnterEvent(self, e):
        if self._accepts(e.mimeData()):
            e.setDropAction(Qt.MoveAction if self._is_internal(e) else Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not self._accepts(e.mimeData()):
            e.ignore()
            return
        pos = e.position().toPoint()
        self._drop_at = self.drop_index(pos)
        e.setDropAction(Qt.MoveAction if self._is_internal(e) else Qt.CopyAction)
        e.accept()
        self._drag_pos = pos
        if self._edge_speed(pos):
            self._scroll_timer.start()
        self.viewport().update()

    # Our drag handling replaces Qt's, so scroll the pane ourselves while a page
    # is held near its top or bottom edge (e.g. moving a page to the front).
    EDGE = 36

    def _edge_speed(self, pos):
        h = self.viewport().height()
        if pos.y() < self.EDGE:
            return -max(4, (self.EDGE - pos.y()) // 2)
        if pos.y() > h - self.EDGE:
            return max(4, (pos.y() - (h - self.EDGE)) // 2)
        return 0

    def _auto_scroll(self):
        speed = self._edge_speed(self._drag_pos) if self._drop_at is not None else 0
        if not speed:
            self._scroll_timer.stop()
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + speed)
        self._drop_at = self.drop_index(self._drag_pos)
        self.viewport().update()

    def dragLeaveEvent(self, e):
        self._drop_at = None
        self._scroll_timer.stop()
        self.viewport().update()

    def dropEvent(self, e):
        at = self.drop_index(e.position().toPoint())
        self._drop_at = None
        self._scroll_timer.stop()
        self.viewport().update()
        mime = e.mimeData()
        uid, pages = parse_source(mime)
        if uid == self.pdoc.uid and not (e.modifiers() & Qt.ControlModifier):
            # Reorder within this document. Report CopyAction so the source
            # (this same pane) does not also delete anything.
            new = self.pdoc.move_pages(pages, at)
            self.select_pages(new)
            e.setDropAction(Qt.CopyAction)
            e.accept()
            return
        data = mime_pdf_bytes(mime)
        if data:
            self.pages_dropped.emit(data, at)
        elif mime.hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in mime.urls() if u.isLocalFile()], at)
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._drop_at is None or not self.count():
            return
        p = QPainter(self.viewport())
        p.setPen(QPen(self.colors.accent, 3))
        n = self.count()
        last = self._drop_at >= n
        r = self.visualRect(self.model().index(n - 1 if last else self._drop_at, 0))
        # Keep the mark inside the viewport, so it still shows before the first page or after the last.
        if self._single_column():
            y = r.bottom() + 2 if last else r.top() - 2
            y = max(2, min(y, self.viewport().height() - 2))
            p.drawLine(r.left() + 4, y, r.right() - 4, y)
        else:
            x = r.right() + 2 if last else r.left() - 2
            x = max(2, min(x, self.viewport().width() - 2))
            p.drawLine(x, r.top() + 4, x, r.bottom() - 4)
        p.end()
