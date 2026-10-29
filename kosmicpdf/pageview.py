"""Continuous-scroll page view with the annotation tools."""
import bisect
import re
import time
from collections import OrderedDict

import pymupdf as fitz
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPen, QPixmap,
                           QTextBlockFormat, QTextCursor)
from PySide6.QtWidgets import QApplication, QFrame, QMenu, QScrollArea, QTextEdit, QToolButton, QWidget

from .core import MIME_PAGES, mark_redaction, mime_pdf_bytes, parse_da_fontsize
from .theme import NOTE_MENU_ICON, Colors, draw_page_shadow, lucide

MARGIN = 12      # space around and between pages, in screen pixels
FIND_OTHER = QColor(255, 222, 0, 95)       # find matches: yellow, stronger than the firm's pale highlight
FIND_CURRENT = QColor(255, 204, 0, 175)
FIND_OUTLINE = QColor(176, 132, 0)
REDACT_WASH = QColor(168, 74, 92, 52)      # over marked areas: mauve, as the redaction bar, and see-through
REDACT_EDGE = QColor(168, 74, 92, 170)     # the box being drawn around an area
CACHE_PAGES = 24
def _hex(h):
    return tuple(int(h[k:k + 2], 16) / 255 for k in (1, 3, 5))


# The firm's highlight colours, from the Highlights macros in the Craig Legal
# Writer Kit (Config Libre); Beige is from the older Macros.bas.
HIGHLIGHT_COLORS = {
    "Yellow": _hex("#ffffa6"),
    "Green": _hex("#dde8cb"),
    "Purple": _hex("#dedce6"),
    "Beige": _hex("#ddd8c3"),
}


def text_markup(annot_type):
    """Highlights and their kin. They belong to the text, so the mouse passes through
    them to the text beneath: select the text to change or clear them."""
    return annot_type in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE, fitz.PDF_ANNOT_STRIKE_OUT,
                          fitz.PDF_ANNOT_SQUIGGLY)


def highlight_rects(annot):
    """The marked areas of a highlight, one rectangle per line."""
    v = annot.vertices or []
    return [fitz.Quad(v[k:k + 4]).rect for k in range(0, len(v) - 3, 4)] or [annot.rect]


def movable(annot_type):
    """Annotations the select tool can drag about. (A function rather than a set, so
    importing this module doesn't load PyMuPDF; see app.defer_import.)"""
    return annot_type in (fitz.PDF_ANNOT_FREE_TEXT, fitz.PDF_ANNOT_REDACT, fitz.PDF_ANNOT_SQUARE,
                          fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_STAMP)


def page_chars(page):
    """Characters in reading order as (rect, char, line_id), unrotated coords."""
    chars, line_id = [], 0
    flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_MEDIABOX_CLIP
    for block in page.get_text("rawdict", flags=flags)["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            line_id += 1
            for span in line["spans"]:
                for ch in span["chars"]:
                    chars.append((fitz.Rect(ch["bbox"]), ch["c"], line_id))
    return chars


def nearest_char(chars, pt, max_dist=None):
    best, best_d = None, None
    for idx, (r, _, _) in enumerate(chars):
        dx = max(r.x0 - pt.x, 0, pt.x - r.x1)
        dy = max(r.y0 - pt.y, 0, pt.y - r.y1)
        d = dy * 4 + dx   # prefer characters on the same line
        if best_d is None or d < best_d:
            best, best_d = idx, d
            if d == 0:
                break
    if max_dist is not None and (best_d is None or best_d > max_dist):
        return None
    return best


def word_bounds(chars, idx):
    """(first, last) character indices of the word containing chars[idx]."""
    line = chars[idx][2]
    lo = hi = idx
    while lo > 0 and chars[lo - 1][2] == line and not chars[lo - 1][1].isspace():
        lo -= 1
    while hi + 1 < len(chars) and chars[hi + 1][2] == line and not chars[hi + 1][1].isspace():
        hi += 1
    return lo, hi


def line_rects(chars, lo, hi):
    """One rectangle per text line covering chars[lo..hi]."""
    rects = {}
    for r, c, line in chars[lo:hi + 1]:
        if r.is_empty:
            continue
        rects[line] = rects[line] | r if line in rects else fitz.Rect(r)
    return list(rects.values())


# Characters searched as if they were the plain ones, so "find" matches the "ﬁ" ligature
# and "Plaintiff's" matches "Plaintiff’s".
SEARCH_AS = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
             "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "}


def search_pattern(term, match_case=False, whole_words=False):
    """A regular expression for a find term, or None for an empty one. Spaces in the
    term match any run of spaces or a line break, so a phrase wrapped onto the next
    line is still found."""
    words = "".join(SEARCH_AS.get(c, c) for c in term).split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    if whole_words:
        pattern = rf"(?<!\w){pattern}(?!\w)"
    return re.compile(pattern, 0 if match_case else re.IGNORECASE)


def find_in_chars(chars, pattern):
    """Each match of pattern in a page's characters, as a list of rectangles (one per line)."""
    text, owner = [], []          # the searchable text, and the character each of its letters came from
    last_line = None
    for n, (_, c, line) in enumerate(chars):
        if last_line is not None and line != last_line:
            text.append(" ")              # a line break reads as a space
            owner.append(None)
        last_line = line
        for letter in SEARCH_AS.get(c, c):
            text.append(letter)
            owner.append(n)
    hits = []
    for m in pattern.finditer("".join(text)):
        used = [n for n in owner[m.start():m.end()] if n is not None]
        if used:
            hits.append(line_rects(chars, used[0], used[-1]))
    return hits


def chars_text(chars, lo, hi):
    out, last = [], None
    for _, c, line in chars[lo:hi + 1]:
        if last is not None and line != last:
            out.append("\n")
        out.append(c)
        last = line
    return "".join(out)


class TypewriterEditor(QTextEdit):
    """Inline editor for typewriter text; commits on focus-out, Esc or Ctrl+Enter.

    Focus moving to a widget marked with the "keepsTypewriterOpen" property (the
    font-size box) does not commit, so the size can be changed mid-note.

    Text is laid out the way MuPDF lays out a FreeText annotation (Helvetica
    metrics, first baseline 0.8 em below the top, lines 1.2 em apart), so it
    does not jump when the note is saved.
    """
    BASELINE, LEADING = 0.8, 1.2   # ems; measured from MuPDF's FreeText rendering

    def __init__(self, canvas, page, vis_pt, anchor, font_px, text="", on_commit=None):
        super().__init__(canvas)
        self.page_index, self.vis_pt, self.anchor, self.on_commit = page, vis_pt, anchor, on_commit
        self._done = False
        self._formatting = False
        self.setAcceptRichText(False)
        self.setStyleSheet("QTextEdit{background:rgba(255,255,225,215);border:1px dashed #3a7bd5;}")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.document().setDocumentMargin(2)
        self.setPlainText(text)
        self.textChanged.connect(self._text_changed)
        self.set_font_px(font_px)

    def set_font_px(self, font_px):
        self.font_px = font_px
        f = QFont("Helvetica")
        f.setStyleHint(QFont.SansSerif)
        f.setPointSizeF(max(3.0, font_px * 72 / self.logicalDpiY()))   # fractional, unlike pixel sizes
        self.setFont(f)
        self.document().setDefaultFont(f)
        self._apply_leading()
        self._fit()

    def _apply_leading(self):
        self._formatting = True
        fmt = QTextBlockFormat()
        fmt.setLineHeight(self.LEADING * self.font_px, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        cur = QTextCursor(self.document())
        cur.select(QTextCursor.Document)
        cur.mergeBlockFormat(fmt)
        self._formatting = False

    def _text_changed(self):
        if not self._formatting:
            self._apply_leading()      # pasted lines get the same spacing
            self._fit()

    def _fit(self):
        fm = QFontMetricsF(self.font())
        lines = self.toPlainText().split("\n") or [""]
        m = self.document().documentMargin()
        frame = self.frameWidth()
        w = max(fm.horizontalAdvance(l) for l in lines) + fm.horizontalAdvance("M") + 2 * (m + frame)
        h = self.LEADING * self.font_px * len(lines) + 2 * (m + frame) + 2
        self.resize(max(round(w), 40), round(h))
        self.place()

    def place(self):
        """Move so the first baseline sits where MuPDF will draw it."""
        self.ensurePolished()
        block = self.document().firstBlock()
        line = block.layout().lineAt(0)
        if not line.isValid():
            return
        top = self.document().documentLayout().blockBoundingRect(block).topLeft()
        vp = self.viewport().geometry().topLeft()
        x = self.anchor.x() - (vp.x() + top.x() + line.x())
        y = self.anchor.y() + self.BASELINE * self.font_px - (vp.y() + top.y() + line.y() + line.ascent())
        self.move(round(x), round(y))
        for w in getattr(self, "attachments", ()):
            w.follow()

    def move_by(self, delta):
        """Shift the note by a screen offset, keeping its top-left corner on the page."""
        r = self.page_rect
        x = min(max(self.anchor.x() + delta.x(), r.left()), r.right() - 8)
        y = min(max(self.anchor.y() + delta.y(), r.top()), r.bottom() - 8)
        self.anchor = QPointF(x, y)
        self.vis_pt = fitz.Point((x - r.left()) / self.zoom, (y - r.top()) / self.zoom)
        self.place()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape or (e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier):
            self.commit()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
            return   # switched to another window or opened a menu: keep typing later
        QTimer.singleShot(0, self._commit_unless_kept_open)

    def _commit_unless_kept_open(self):
        if self._done:
            return
        w = QApplication.focusWidget()
        while w is not None:
            if w is self or w.property("keepsTypewriterOpen"):
                return
            w = w.parentWidget()
        self.commit()

    def commit(self):
        if self._done:
            return
        self._done = True
        text = self.toPlainText().rstrip("\n")
        cb = self.on_commit
        self.close_controls()
        if cb:
            cb(self, text)

    def close_controls(self):
        """Hide and dispose of the editor and the controls attached to it."""
        self._done = True
        self.hide()
        for w in getattr(self, "attachments", ()):
            w.hide()
            w.deleteLater()
        self.deleteLater()


class DragHandle(QWidget):
    """Grip on the left edge of a typewriter box. Drag it to move the note, or
    click it and nudge with the arrow keys (Shift for bigger steps).

    It takes focus when clicked; otherwise Qt would give focus to the page
    behind it, which closes the note. It carries "keepsTypewriterOpen", so the
    note stays open while the handle has focus.
    """
    WIDTH = 12
    NUDGE, BIG_NUDGE = 1, 10      # screen pixels

    def __init__(self, editor, color):
        super().__init__(editor.parentWidget())
        self.editor, self.color = editor, QColor(color)
        self._last = None
        self.setFocusPolicy(Qt.ClickFocus)
        self.setProperty("keepsTypewriterOpen", True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag to move, or click and use the arrow keys")

    def follow(self):
        g = self.editor.geometry()
        self.setGeometry(g.left() - self.WIDTH + 1, g.top(), self.WIDTH, g.height())
        self.raise_()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color.darker(135) if self.hasFocus() else self.color)
        p.drawRoundedRect(QRectF(self.rect()), 3, 3)
        p.setBrush(QColor(255, 255, 255, 235))
        cx, cy = self.width() / 2, self.height() / 2
        for dy in (-4.5, 0, 4.5):
            for dx in (-2, 2):
                p.drawEllipse(QPointF(cx + dx, cy + dy), 1.1, 1.1)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._last = e.globalPosition()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._last is not None:
            self.editor.move_by(e.globalPosition() - self._last)
            self._last = e.globalPosition()

    def mouseReleaseEvent(self, e):
        self._last = None
        self.setCursor(Qt.OpenHandCursor)

    def keyPressEvent(self, e):
        step = self.BIG_NUDGE if e.modifiers() & Qt.ShiftModifier else self.NUDGE
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if e.key() in moves:
            self.editor.move_by(QPointF(*moves[e.key()]))
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
            self.editor.setFocus()          # back to typing
        elif e.key() == Qt.Key_Escape:
            self.editor.commit()
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.update()

    def focusOutEvent(self, e):
        self.update()
        if e.reason() not in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
            QTimer.singleShot(0, self.editor._commit_unless_kept_open)


class ShoulderButton(QToolButton):
    """A small trash button on the shoulder (top right corner) of a box: a typewriter
    note, or a redaction mark. It opens a one-item menu rather than acting at once,
    so a stray click can't remove anything."""
    SIZE = 18

    def __init__(self, parent, color, label, tip, on_remove):
        super().__init__(parent)
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip(tip)
        self.setIcon(lucide("trash-2", QColor("white")))
        self.setIconSize(QSize(NOTE_MENU_ICON, NOTE_MENU_ICON))
        self.setPopupMode(QToolButton.InstantPopup)
        self.set_color(color)
        menu = QMenu(self)
        menu.addAction(lucide("trash-2", QColor(self.palette().color(self.foregroundRole()))), label, on_remove)
        self.setMenu(menu)

    def set_color(self, color):
        c = QColor(color)
        self.setStyleSheet(f"QToolButton{{background:{c.name()};border:none;border-radius:4px;padding:0;}}"
                           f"QToolButton:hover,QToolButton:pressed,QToolButton:focus{{background:{c.darker(135).name()};}}"
                           "QToolButton::menu-indicator{image:none;width:0;}")

    def place_beside(self, rect):
        """Just outside the top right corner of rect (a box on the canvas)."""
        self.setGeometry(round(rect.right()) + 3, round(rect.top()), self.SIZE, self.SIZE)
        self.raise_()


class NoteMenuButton(ShoulderButton):
    """The shoulder button of a typewriter box: Delete note. Like the handle, it
    takes click focus and keeps the note open."""

    def __init__(self, editor, color, on_remove):
        super().__init__(editor.parentWidget(), color, "Delete note", "Delete this note", lambda: on_remove(editor))
        self.editor = editor
        self.setFocusPolicy(Qt.ClickFocus)
        self.setProperty("keepsTypewriterOpen", True)

    def follow(self):
        g = self.editor.geometry()
        self.setGeometry(g.right() + 3, g.top(), self.SIZE, self.SIZE)
        self.raise_()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() not in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
            QTimer.singleShot(0, self.editor._commit_unless_kept_open)


class PageCanvas(QWidget):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, e):
        self.view.paint(QPainter(self), e.rect())

    def mousePressEvent(self, e):
        self.view.mouse_press(e)

    def mouseMoveEvent(self, e):
        self.view.mouse_move(e)

    def mouseReleaseEvent(self, e):
        self.view.mouse_release(e)

    def mouseDoubleClickEvent(self, e):
        self.view.mouse_double(e)

    def leaveEvent(self, e):
        self.view.hover_marks(None)

    def contextMenuEvent(self, e):
        self.view.context_menu(e)

    def keyPressEvent(self, e):
        if not self.view.key_press(e):
            super().keyPressEvent(e)


class PageView(QScrollArea):
    current_page_changed = Signal(int)
    zoom_changed = Signal(float)
    status = Signal(str)
    pages_dropped = Signal(bytes, int)   # pdf bytes, insert-before index
    files_dropped = Signal(list)

    def __init__(self, pdoc, parent=None):
        super().__init__(parent)
        self._hover_mark = None       # (page, xref, canvas rect) of the redaction mark under the mouse
        self.mark_button = None       # its shoulder button (Remove mark), made when first needed
        self.pdoc = pdoc
        self.canvas = PageCanvas(self)
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)
        self.setBackgroundRole(self.backgroundRole())
        self.setFrameShape(QFrame.NoFrame)
        self.colors = Colors()
        self.apply_colors(self.colors)
        self.setAcceptDrops(True)

        self.zoom = 1.0
        self.fit = "width"            # "width", "page" or None
        self.mode = "select"
        self.font_size = 12.0
        self.hl_color = HIGHLIGHT_COLORS["Yellow"]
        self.redact_by = "text"       # redact mode: "text" (select it) or "area" (draw a box)
        self.page_rects = []          # QRect per page in canvas coords
        self._sizes = []              # (w, h) per page in points, as last laid out
        self._cache = OrderedDict()   # (key, zoom, dpr) -> QPixmap
        self._chars = {}              # pdoc.key(i) -> chars
        self._current = 0

        self.sel = None               # (page, lo, hi) text selection
        self.sel_annot = None         # (page, xref) selected annotation
        self.find_hits = []           # [(page, [fitz.Rect, one per line])], in page order
        self.find_index = -1
        self._find_pattern = None     # the search still in progress, if any (see find_more)
        self._find_pages = []         # pages it has yet to look at
        self._press = None            # state for drags
        self._rubber = None           # (page, QRectF in canvas coords)
        self._move_offset = None
        self.editor = None            # open TypewriterEditor, if any

        pdoc.structure_changed.connect(self._structure_changed)
        pdoc.pages_changed.connect(self._pages_changed)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.relayout()

    def apply_colors(self, colors):
        self.colors = colors
        if self.mark_button:
            self.mark_button.set_color(colors.accent)
        pal = self.viewport().palette()
        pal.setColor(self.viewport().backgroundRole(), colors.pages)
        self.viewport().setPalette(pal)
        self.viewport().setAutoFillBackground(True)
        self.canvas.update()

    # --- layout -------------------------------------------------------------
    def _structure_changed(self):
        self.sel = self.sel_annot = None
        self.hover_marks(None)
        self.find_hits = []
        self.find_index = -1
        self._find_pattern = None
        self._chars.clear()
        self.relayout()
        self.canvas.update()

    def _pages_changed(self, pages):
        if self.sel and self.sel[0] in pages:
            self.sel = None
        # Only a rotation changes page size; skip re-measuring every page otherwise.
        if any(i >= len(self._sizes) or self.page_size(i) != self._sizes[i] for i in pages):
            self.relayout()
        self.canvas.update()

    def page_size(self, i):
        r = self.pdoc.doc[i].rect
        return r.width, r.height

    def compute_fit_zoom(self):
        if not self.pdoc.page_count or not self.fit:
            return self.zoom
        sizes = [self.page_size(i) for i in range(min(self.pdoc.page_count, 50))]
        avail_w = self.viewport().width() - 2 * MARGIN
        z = avail_w / max(w for w, _ in sizes)
        if self.fit == "page":
            w, h = self.page_size(min(self._current, self.pdoc.page_count - 1))
            z = min(avail_w / w, (self.viewport().height() - 2 * MARGIN) / h)
        return max(0.05, z)

    def relayout(self, keep_page=None):
        self.hover_marks(None)            # its mark moves; it comes back with the mouse
        keep = self._current if keep_page is None else keep_page
        frac = self._scroll_fraction()
        if self.fit:
            self.zoom = self.compute_fit_zoom()
        sizes = self._sizes = [self.page_size(i) for i in range(self.pdoc.page_count)]
        maxw = max((w for w, _ in sizes), default=0) * self.zoom
        width = max(self.viewport().width(), int(maxw) + 2 * MARGIN)
        y, rects = MARGIN, []
        for w, h in sizes:
            pw, ph = round(w * self.zoom), round(h * self.zoom)
            rects.append(QRect((width - pw) // 2, y, pw, ph))
            y += ph + MARGIN
        self.page_rects = rects
        self.canvas.resize(width, max(y, self.viewport().height()))
        if rects:
            keep = min(keep, len(rects) - 1)
            self.verticalScrollBar().setValue(rects[keep].top() - MARGIN + int(frac * rects[keep].height()))
        self.zoom_changed.emit(self.zoom)

    def _scroll_fraction(self):
        if not self.page_rects or self._current >= len(self.page_rects):
            return 0.0
        r = self.page_rects[self._current]
        return max(0.0, (self.verticalScrollBar().value() + MARGIN - r.top()) / max(1, r.height()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit or self.canvas.width() < self.viewport().width():
            self.relayout()

    def set_zoom(self, zoom=None, fit=None):
        self.fit = fit
        if zoom is not None:
            self.zoom = max(0.1, min(zoom, 8.0))
        self.relayout()
        self.canvas.update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1))
            e.accept()
            return
        super().wheelEvent(e)

    # --- navigation ---------------------------------------------------------
    def _scrolled(self, value):
        mid = value + self.viewport().height() // 3
        for i, r in enumerate(self.page_rects):
            if r.bottom() + MARGIN >= mid:
                if i != self._current:
                    self._current = i
                    self.current_page_changed.emit(i)
                break

    @property
    def current_page(self):
        return self._current

    def go_to_page(self, i, y_pts=None):
        if not self.page_rects:
            return
        i = max(0, min(i, len(self.page_rects) - 1))
        top = self.page_rects[i].top() - MARGIN
        if y_pts is not None:
            top = self.page_rects[i].top() + int(y_pts * self.zoom) - self.viewport().height() // 3
        self.verticalScrollBar().setValue(top)
        self._current = i
        self.current_page_changed.emit(i)

    # --- coordinates --------------------------------------------------------
    def page_at(self, pos, slack=0):
        for i, r in enumerate(self.page_rects):
            if r.adjusted(-slack, -slack, slack, slack).contains(pos):
                return i
        return None

    def to_pdf(self, i, pos):
        """Canvas position -> unrotated PDF point on page i."""
        r = self.page_rects[i]
        vis = fitz.Point((pos.x() - r.left()) / self.zoom, (pos.y() - r.top()) / self.zoom)
        return vis * self.pdoc.doc[i].derotation_matrix

    def to_vis(self, i, pos):
        r = self.page_rects[i]
        return fitz.Point((pos.x() - r.left()) / self.zoom, (pos.y() - r.top()) / self.zoom)

    def to_canvas(self, i, rect):
        """Unrotated PDF rect on page i -> QRectF in canvas coords."""
        vr = fitz.Rect(rect) * self.pdoc.doc[i].rotation_matrix
        r = self.page_rects[i]
        return QRectF(r.left() + vr.x0 * self.zoom, r.top() + vr.y0 * self.zoom,
                      vr.width * self.zoom, vr.height * self.zoom)

    def chars(self, i):
        k = self.pdoc.key(i)
        if k not in self._chars:
            self._chars[k] = page_chars(self.pdoc.doc[i])
        return self._chars[k]

    # --- painting -----------------------------------------------------------
    def render(self, i):
        dpr = self.devicePixelRatioF()
        k = (self.pdoc.key(i), round(self.zoom, 4), dpr)
        pm = self._cache.get(k)
        if pm is None:
            pix = self.pdoc.doc[i].get_pixmap(matrix=fitz.Matrix(self.zoom * dpr, self.zoom * dpr), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            self._cache[k] = pm
            while len(self._cache) > CACHE_PAGES:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(k)
        return pm

    def paint(self, p, clip):
        p.fillRect(clip, self.colors.pages)
        p.setRenderHint(QPainter.Antialiasing)
        for i, r in enumerate(self.page_rects):
            if r.bottom() < clip.top() or r.top() > clip.bottom():
                continue
            draw_page_shadow(p, r, self.colors)
            p.drawPixmap(r.topLeft(), self.render(i))
            self.paint_overlays(p, i)
        if self._rubber:
            p.setPen(QPen(REDACT_EDGE, 1, Qt.DashLine))
            p.setBrush(REDACT_WASH)
            p.drawRect(self._rubber[1])
        p.end()

    def paint_overlays(self, p, i):
        page = self.pdoc.doc[i]
        # Redaction marks: a light wash over MuPDF's faint outline (see core.mark_redaction).
        p.setPen(Qt.NoPen)
        p.setBrush(REDACT_WASH)
        for a in page.annots(types=[fitz.PDF_ANNOT_REDACT]):
            p.drawRect(self.to_canvas(i, a.rect))
        if self.sel and self.sel[0] == i:
            p.setPen(Qt.NoPen)
            p.setBrush(self.colors.accent_alpha(80))
            for r in line_rects(self.chars(i), self.sel[1], self.sel[2]):
                p.drawRect(self.to_canvas(i, r))
        for n, (pi, rects) in enumerate(self.find_hits):
            if pi == i:
                current = n == self.find_index        # the match you're on: deeper, with an outline
                p.setPen(QPen(FIND_OUTLINE, 1) if current else Qt.NoPen)
                p.setBrush(FIND_CURRENT if current else FIND_OTHER)
                for r in rects:
                    p.drawRect(self.to_canvas(i, r))
        if self.sel_annot and self.sel_annot[0] == i:
            annot = page.load_annot(self.sel_annot[1])
            if annot:
                rect = self.to_canvas(i, annot.rect)
                if self._move_offset is not None:
                    rect.translate(self._move_offset)
                p.setPen(QPen(QColor("#3a7bd5"), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect.adjusted(-2, -2, 2, 2))

    # --- removing a redaction mark: a shoulder button, shown on hover --------------------
    def mark_at(self, pos):
        """The redaction mark under pos, or whose shoulder button is: (page, xref, canvas rect)."""
        i = self.page_at(pos, slack=ShoulderButton.SIZE + 3)     # the button stands just off the mark
        if i is None:
            return None
        hit = None
        page = self.pdoc.doc[i]           # its annotations are valid only while it lives
        for a in page.annots(types=[fitz.PDF_ANNOT_REDACT]):
            r = self.to_canvas(i, a.rect)
            reach = r.united(QRectF(r.right(), r.top(), ShoulderButton.SIZE + 4, ShoulderButton.SIZE))
            if reach.contains(QPointF(pos)):
                hit = (i, a.xref, r)              # last one wins: topmost
        return hit

    def hover_marks(self, pos):
        """Show the shoulder button of the mark under the mouse (while redacting), or hide it."""
        if self.mark_button and self.mark_button.menu().isVisible():
            return                                # its menu is open: keep the mark it belongs to
        hit = self.mark_at(pos) if self.mode == "redact" and pos is not None else None
        self._hover_mark = hit
        if hit is None:
            if self.mark_button:
                self.mark_button.hide()
            return
        if self.mark_button is None:
            self.mark_button = ShoulderButton(self.canvas, self.colors.accent, "Remove mark",
                                              "Remove this redaction mark", self._remove_hovered_mark)
            self.mark_button.setFocusPolicy(Qt.NoFocus)
        self.mark_button.place_beside(hit[2])
        self.mark_button.mark = hit[:2]           # the button keeps its mark, whatever the mouse does next
        self.mark_button.show()

    def _remove_hovered_mark(self):
        self.remove_mark(*self.mark_button.mark)

    def remove_mark(self, i, xref):
        self.pdoc.checkpoint()
        page = self.pdoc.doc[i]
        a = page.load_annot(xref)
        if a:
            page.delete_annot(a)
        self._hover_mark = None
        if self.mark_button:
            self.mark_button.hide()           # its mark is gone (its menu may still be closing)
        self.pdoc.edited([i])
        self.status.emit("Removed the redaction mark.")

    # --- mouse --------------------------------------------------------------
    def annot_at(self, i, pt):
        # An Annot is only valid while its Page object lives, so hold on to
        # the page until the next hit test.
        page = self._hit_page = self.pdoc.doc[i]
        hit = None
        for a in page.annots():
            if not text_markup(a.type[0]) and (a.rect + (-2, -2, 2, 2)).contains(pt):
                hit = a  # last one wins: topmost
        return hit

    def mouse_press(self, e):
        pos = e.position().toPoint()
        if self.editor is not None:
            self.editor.commit()     # clicking the page finishes the note being typed
        self.canvas.setFocus()
        if e.button() != Qt.LeftButton:
            return
        i = self.page_at(pos)
        self._press = None
        if i is None:
            self.clear_selection()
            return
        pt = self.to_pdf(i, pos)
        if self.mode == "typewriter":
            a = self.annot_at(i, pt)
            if a and a.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                self.edit_freetext(i, a)
            else:
                self.start_typewriter(i, self.to_vis(i, pos))
            return
        if self.mode == "redact" and self.redact_by == "area":
            self._press = ("rect", i, pos)
            self._rubber = (i, QRectF(pos, pos))
            return
        self.sel_annot = None
        if self.mode == "select":
            a = self.annot_at(i, pt)
            if a and movable(a.type[0]):
                self.sel = None
                self.sel_annot = (i, a.xref)
                self._press = ("move", i, pos)
                self.canvas.update()
                return
            if a:
                # A click selects the annotation (so Delete removes it); a drag still selects the text.
                self.sel_annot = (i, a.xref)
        chars = self.chars(i)
        idx = nearest_char(chars, pt, max_dist=None if self.mode == "select" else 30)
        if self.mode in ("highlight", "redact") and idx is None:
            # No text near the click (e.g. a scan): highlight, or redact, a rectangle instead.
            self._press = ("hlrect" if self.mode == "highlight" else "rect", i, pos)
            self._rubber = (i, QRectF(pos, pos))
            return
        self._press = ("text", i, pos, idx)
        self.sel = None
        self.canvas.update()

    def mouse_move(self, e):
        pos = e.position().toPoint()
        if not self._press or not (e.buttons() & Qt.LeftButton):
            self._update_cursor(pos)
            return
        kind, i = self._press[0], self._press[1]
        start = self._press[2]
        if kind in ("rect", "hlrect"):
            self._rubber = (i, QRectF(start, pos).normalized() & QRectF(self.page_rects[i]))
        elif kind == "move":
            self._move_offset = QPointF(pos - start)
        elif kind == "word":
            chars = self.chars(i)
            end = nearest_char(chars, self.to_pdf(i, pos))
            if end is not None:
                lo, hi = self._press[3], self._press[4]     # the double-clicked word stays selected
                self.sel = (i, min(lo, end), max(hi, end))
        elif kind == "text":
            if (pos - start).manhattanLength() < 3 or self._press[3] is None:
                return
            chars = self.chars(i)
            end = nearest_char(chars, self.to_pdf(i, pos))
            if end is not None:
                a = self._press[3]
                self.sel = (i, min(a, end), max(a, end))
                self.sel_annot = None
        self.canvas.update()

    def mouse_release(self, e):
        if e.button() != Qt.LeftButton or not self._press:
            return
        kind, i = self._press[0], self._press[1]
        self._press = None
        if kind in ("rect", "hlrect"):
            rect = self._rubber[1] if self._rubber else QRectF()
            self._rubber = None
            if rect.width() > 3 and rect.height() > 3:
                pr = self.page_rects[i]
                vis = fitz.Rect((rect.left() - pr.left()) / self.zoom, (rect.top() - pr.top()) / self.zoom,
                                (rect.right() - pr.left()) / self.zoom, (rect.bottom() - pr.top()) / self.zoom)
                pdf_rect = vis * self.pdoc.doc[i].derotation_matrix
                if kind == "rect":
                    self.add_redaction(i, [pdf_rect])
                elif self.hl_color is None:
                    self.erase_highlights(i, [pdf_rect])
                else:
                    self.add_highlight(i, [pdf_rect])
            elif kind == "hlrect" and self.hl_color is None:
                self.erase_highlights(i, [self._point_rect(i, rect.center())])
            self.canvas.update()
        elif kind == "move":
            off = self._move_offset
            self._move_offset = None
            if off is not None and (abs(off.x()) > 1 or abs(off.y()) > 1):
                self.move_annot(i, off)
            self.canvas.update()
        elif kind == "word":
            if self.mode == "highlight" and self.sel:
                self.highlight_selection()
            elif self.mode == "redact" and self.sel:
                self.redact_selection()
            self.canvas.update()
        elif kind == "text":
            if self.mode == "highlight" and self.hl_color is None:
                # Eraser: remove highlights under the dragged text, or under a click.
                if self.sel:
                    _, lo, hi = self.sel
                    rects = line_rects(self.chars(i), lo, hi)
                else:
                    rects = [self._point_rect(i, e.position())]
                self.sel = None
                self.erase_highlights(i, rects)
            elif self.mode == "highlight" and self.sel:
                self.highlight_selection()
            elif self.mode == "redact" and self.sel:
                self.redact_selection()          # text redaction: just the selected characters, line by line
            elif not self.sel:
                self.canvas.update()

    def mouse_double(self, e):
        pos = e.position().toPoint()
        i = self.page_at(pos)
        if i is None:
            return
        pt = self.to_pdf(i, pos)
        a = self.annot_at(i, pt)
        if a and a.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
            self.edit_freetext(i, a)
            return
        if (self.mode == "select" or (self.mode == "highlight" and self.hl_color is not None)
                or (self.mode == "redact" and self.redact_by == "text")):
            # Double-click selects a word; dragging on from there extends it a character at a time.
            chars = self.chars(i)
            idx = nearest_char(chars, pt, max_dist=2)
            if idx is None:
                return
            lo, hi = word_bounds(chars, idx)
            self.sel = (i, lo, hi)
            self.sel_annot = None
            self._press = ("word", i, pos, lo, hi)
            self.canvas.update()

    def _update_cursor(self, pos):
        cursors = {"select": Qt.IBeamCursor, "highlight": Qt.IBeamCursor,
                   "typewriter": Qt.IBeamCursor, "redact": Qt.CrossCursor}
        i = self.page_at(pos)
        cur = cursors[self.mode] if i is not None else Qt.ArrowCursor
        if i is not None and self.mode == "redact" and self.redact_by == "text":
            cur = Qt.IBeamCursor
        self.hover_marks(pos)
        if i is not None and self.mode == "select" and self.annot_at(i, self.to_pdf(i, pos)):
            cur = Qt.SizeAllCursor
        self.canvas.setCursor(cur)

    def key_press(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel_annot:
            self.delete_selected_annot()
            return True
        if e.key() == Qt.Key_Escape:
            self.clear_selection()
            return True
        return False

    def clear_selection(self):
        self.sel = self.sel_annot = None
        self.canvas.update()

    def context_menu(self, e):
        i = self.page_at(e.pos())
        if i is not None and not self.sel:
            a = self.annot_at(i, self.to_pdf(i, e.pos()))
            if a:
                self.sel_annot = (i, a.xref)
                self.canvas.update()
        menu = QMenu(self)
        if self.sel:
            si, lo, hi = self.sel
            menu.addAction("Copy text", self.copy_text)
            menu.addAction("Highlight", self.highlight_selection)
            if self.highlights_touching(si, line_rects(self.chars(si), lo, hi)):
                menu.addAction("Remove highlights", lambda: self.erase_highlights(
                    si, line_rects(self.chars(si), lo, hi)))
            menu.addAction("Mark for redaction", self.redact_selection)
        if self.sel_annot:
            annot = self.pdoc.doc[self.sel_annot[0]].load_annot(self.sel_annot[1])
            if annot:
                menu.addAction("Delete annotation", self.delete_selected_annot)
        if not menu.isEmpty():
            menu.exec(e.globalPos())

    # --- drops: pages dragged in from a thumbnail pane --------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_PAGES) or e.mimeData().hasUrls():
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def dropEvent(self, e):
        mime = e.mimeData()
        if mime.hasFormat(MIME_PAGES):
            pos = self.canvas.mapFrom(self, e.position().toPoint())
            i = self.page_at(pos, slack=MARGIN)
            at = self.pdoc.page_count if i is None else i + 1
            self.pages_dropped.emit(mime_pdf_bytes(mime), at)
        elif mime.hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in mime.urls() if u.isLocalFile()])
        e.setDropAction(Qt.CopyAction)
        e.accept()

    # --- text ---------------------------------------------------------------
    def selected_text(self):
        if not self.sel:
            return ""
        i, lo, hi = self.sel
        return chars_text(self.chars(i), lo, hi)

    def copy_text(self):
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status.emit(f"Copied {len(text)} characters.")
        return bool(text)

    def select_all_on_page(self):
        i = self._current
        chars = self.chars(i)
        if chars:
            self.sel = (i, 0, len(chars) - 1)
            self.canvas.update()

    # --- annotations --------------------------------------------------------
    def add_highlight(self, i, rects, replace=()):
        """Highlight rects on page i in the current colour, in place of the highlights
        whose xrefs are in `replace`."""
        self.pdoc.checkpoint()
        page = self.pdoc.doc[i]
        for x in replace:
            old = page.load_annot(x)
            if old:
                page.delete_annot(old)
        a = page.add_highlight_annot(quads=[fitz.Rect(r).quad for r in rects])
        a.set_colors(stroke=self.hl_color or HIGHLIGHT_COLORS["Yellow"])
        a.update()
        self.pdoc.edited([i])

    def _point_rect(self, i, canvas_pos):
        """A tiny PDF rect around a clicked point, for hit-testing highlights."""
        pt = self.to_pdf(i, QPointF(canvas_pos).toPoint())
        return fitz.Rect(pt.x - 1, pt.y - 1, pt.x + 1, pt.y + 1)

    def highlights_touching(self, i, rects):
        """xrefs of highlight annotations on page i whose marked areas touch any of rects."""
        page = self._hit_page = self.pdoc.doc[i]
        hits = []
        for a in page.annots(types=[fitz.PDF_ANNOT_HIGHLIGHT]):
            if any(q.intersects(r) or q.contains(r.tl) for q in highlight_rects(a) for r in rects):
                hits.append(a.xref)
        return hits

    def highlights_within(self, i, rects):
        """xrefs of highlights on page i lying wholly inside rects. Highlighting the same
        text again replaces them, so choosing a new colour recolours rather than stacks."""
        page = self._hit_page = self.pdoc.doc[i]
        grown = [fitz.Rect(r) + (-2, -2, 2, 2) for r in rects]
        return [a.xref for a in page.annots(types=[fitz.PDF_ANNOT_HIGHLIGHT])
                if all(any(g.contains(q) for g in grown) for q in highlight_rects(a))]

    def erase_highlights(self, i, rects):
        xrefs = self.highlights_touching(i, rects)
        if not xrefs:
            self.canvas.update()
            return
        self.pdoc.checkpoint()
        page = self.pdoc.doc[i]
        for x in xrefs:
            a = page.load_annot(x)
            if a:
                page.delete_annot(a)
        self.pdoc.edited([i])
        self.status.emit(f"Removed {len(xrefs)} highlight(s).")

    def highlight_selection(self):
        if not self.sel:
            return
        i, lo, hi = self.sel
        rects = line_rects(self.chars(i), lo, hi)
        self.sel = None
        if rects:
            self.add_highlight(i, rects, replace=self.highlights_within(i, rects))

    def highlighter_on_selection(self):
        """What the Highlight button does to text that is already selected: highlight it in
        the current colour, or, with Clear chosen, remove the highlights under it. False if
        nothing is selected."""
        if not self.sel:
            return False
        if self.hl_color is None:
            i, lo, hi = self.sel
            self.sel = None
            self.erase_highlights(i, line_rects(self.chars(i), lo, hi))
        else:
            self.highlight_selection()
        self.canvas.update()
        return True

    def add_redaction(self, i, rects):
        self.pdoc.checkpoint()
        page = self.pdoc.doc[i]
        for r in rects:
            mark_redaction(page, r)
        self.pdoc.edited([i])
        self.status.emit("Marked for redaction. Save Redacted Copy removes it, in a copy; the original stays as it is.")

    def redact_selection(self):
        if not self.sel:
            return
        i, lo, hi = self.sel
        rects = line_rects(self.chars(i), lo, hi)
        self.sel = None
        if rects:
            self.add_redaction(i, rects)

    def delete_selected_annot(self):
        if not self.sel_annot:
            return
        i, xref = self.sel_annot
        self.sel_annot = None
        self.pdoc.checkpoint()
        page = self.pdoc.doc[i]
        annot = page.load_annot(xref)
        if annot:
            page.delete_annot(annot)
        self.pdoc.edited([i])

    def move_annot(self, i, offset):
        _, xref = self.sel_annot
        self.pdoc.checkpoint()
        page = self.pdoc.doc[i]
        annot = page.load_annot(xref)
        if not annot:
            return
        vis = annot.rect * page.rotation_matrix
        vis = vis + (offset.x() / self.zoom, offset.y() / self.zoom, offset.x() / self.zoom, offset.y() / self.zoom)
        annot.set_rect(vis * page.derotation_matrix)
        annot.update()
        self.sel_annot = (i, annot.xref)
        self.pdoc.edited([i])

    # --- typewriter ---------------------------------------------------------
    def start_typewriter(self, i, vis_pt, text="", font_size=None, replace_xref=None, restore_flags=None):
        fs = font_size or self.font_size
        r = self.page_rects[i]
        anchor = QPointF(r.left() + vis_pt.x * self.zoom, r.top() + vis_pt.y * self.zoom)
        ed = self.editor = TypewriterEditor(self.canvas, i, vis_pt, anchor, fs * self.zoom, text,
                                            self._commit_typewriter)
        ed.font_size = fs
        ed.replace_xref, ed.restore_flags = replace_xref, restore_flags
        ed.original = (text, fs, (vis_pt.x, vis_pt.y))
        ed.page_rect, ed.zoom = QRectF(r), self.zoom
        accent = self.colors.accent.name()
        ed.setStyleSheet(f"QTextEdit{{background:rgba(255,255,225,215);border:1px dashed {accent};}}")
        ed.handle = DragHandle(ed, self.colors.accent)
        ed.remove_button = NoteMenuButton(ed, self.colors.accent, self.remove_note)
        ed.attachments = [ed.handle, ed.remove_button]
        for w in ed.attachments:
            w.show()
        ed.place()
        ed.show()
        ed.setFocus()
        cur = ed.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        ed.setTextCursor(cur)

    def edit_freetext(self, i, annot):
        page = self.pdoc.doc[i]
        vis = annot.rect * page.rotation_matrix
        fs = parse_da_fontsize(self.pdoc.doc, annot, self.font_size)
        # Hide the note while it is being edited, so it doesn't show through the editor.
        flags = annot.flags
        annot.set_flags(flags | fitz.PDF_ANNOT_IS_HIDDEN)
        self.pdoc.touch([i])
        self.canvas.update()
        self.start_typewriter(i, vis.tl, annot.info.get("content", ""), fs, annot.xref, flags)

    def set_font_size(self, fs):
        """Typewriter font size changed in the toolbar; apply it to an open note too."""
        self.font_size = fs
        ed = self.editor
        if ed is not None:
            ed.font_size = fs
            ed.set_font_px(fs * self.zoom)
            ed.setFocus()

    def remove_note(self, ed):
        """Delete the note being edited."""
        if self.editor is ed:
            self.editor = None
        ed.close_controls()
        i = ed.page_index
        if ed.replace_xref is not None and i < self.pdoc.page_count:
            page = self.pdoc.doc[i]
            old = page.load_annot(ed.replace_xref)
            if old:
                old.set_flags(ed.restore_flags)      # visible again in the undo snapshot
                self.pdoc.checkpoint()
                page = self.pdoc.doc[i]
                page.delete_annot(page.load_annot(ed.replace_xref))
                self.pdoc.edited([i])
        self.canvas.setFocus()
        self.status.emit("Note deleted." + (" Undo (Ctrl+Z) brings it back." if ed.replace_xref is not None else ""))

    def _commit_typewriter(self, ed, text):
        if self.editor is ed:
            self.editor = None
        i, fs = ed.page_index, ed.font_size
        if i >= self.pdoc.page_count:
            return
        page = self.pdoc.doc[i]
        if ed.replace_xref is not None:
            old = page.load_annot(ed.replace_xref)
            if old:
                old.set_flags(ed.restore_flags)    # unhide before the undo snapshot
            if (text, fs, (ed.vis_pt.x, ed.vis_pt.y)) == ed.original:   # opened but not changed: nothing to record
                self.pdoc.touch([i])
                self.canvas.update()
                if self.editor is None:
                    self.canvas.setFocus()
                return
        elif not text.strip():
            return
        self.pdoc.checkpoint()
        if ed.replace_xref is not None:
            old = page.load_annot(ed.replace_xref)
            if old:
                page.delete_annot(old)
        if text.strip():
            lines = text.split("\n")
            w = max(fitz.get_text_length(l, "helv", fs) for l in lines) + fs
            h = len(lines) * fs * 1.25 + fs * 0.5
            vis = fitz.Rect(ed.vis_pt.x, ed.vis_pt.y, ed.vis_pt.x + w, ed.vis_pt.y + h)
            page.add_freetext_annot(vis * page.derotation_matrix, text, fontsize=fs, fontname="helv",
                                    text_color=(0, 0, 0), rotate=page.rotation)
        self.pdoc.edited([i])
        if self.editor is None:
            self.canvas.setFocus()

    # --- find ---------------------------------------------------------------
    def find(self, term, match_case=False, whole_words=False):
        """Start a search; find_more() does the work, a few pages at a time, beginning at
        the page in view so its matches turn up first. An empty term clears the search."""
        self.find_hits = []
        self.find_index = -1
        self._find_pattern = search_pattern(term, match_case, whole_words)
        n = self.pdoc.page_count
        self._find_pages = [(self._current + k) % n for k in range(n)] if self._find_pattern else []
        self.canvas.update()

    def find_more(self, budget=0.03):
        """Search on for up to `budget` seconds. True once every page has been searched."""
        start = time.monotonic()
        found = False
        while self._find_pages and time.monotonic() - start < budget:
            i = self._find_pages.pop(0)
            hits = find_in_chars(page_chars(self.pdoc.doc[i]), self._find_pattern)
            if hits:
                at = bisect.bisect_left([pi for pi, _ in self.find_hits], i)
                self.find_hits[at:at] = [(i, rects) for rects in hits]
                if 0 <= at <= self.find_index:
                    self.find_index += len(hits)      # keep pointing at the same match
                found = True
        if found:
            self.canvas.update()
        return not self._find_pages

    def find_step(self, step):
        if not self.find_hits:
            return
        if self.find_index < 0:
            # the first match from the page in view onwards (or, going back, the last one up to it)
            if step > 0:
                after = [n for n, (pi, _) in enumerate(self.find_hits) if pi >= self._current]
                self.find_index = after[0] if after else 0
            else:
                before = [n for n, (pi, _) in enumerate(self.find_hits) if pi <= self._current]
                self.find_index = before[-1] if before else len(self.find_hits) - 1
        else:
            self.find_index = (self.find_index + step) % len(self.find_hits)
        i, rects = self.find_hits[self.find_index]
        vr = rects[0] * self.pdoc.doc[i].rotation_matrix
        self.go_to_page(i, vr.y0)
        self.canvas.update()
