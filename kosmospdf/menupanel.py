"""The menu: a panel that opens over the window under the menu button at the top left,
with a subpanel beside it for the section the pointer or the keys are on (File, Insert,
Table, ...). Both are children of the window, laid over it; neither is a window itself.

At the top a search box: a few letters find any command, in the panel itself. The keyboard
works as in a menu: Up and Down move, Enter runs, Right opens a section's subpanel and Left
leaves it, Escape clears the search, then closes the subpanel, then the menu. A command
run, a click anywhere else, or the window losing the keyboard closes it.

(The same panel as Kosmos Writer's.)
"""
import math

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from .theme import Colors, lucide

WIDTH, ROW = 300, 28
EDGE = 6                # the least space kept between a panel and the window's edge
GAP = 3                 # between the panel and its subpanel
RADIUS = 8              # of a panel's corners
LINGER = 180            # ms the pointer rests on a row before the subpanel follows it


class Row(QAbstractButton):
    """A command, or (with `section`) the row that opens a section's subpanel. `plain`
    rows show no icon: those of the panel itself, whose sections have none."""

    def __init__(self, rows, action=None, section=None, hint="", plain=False):
        super().__init__()
        self.rows, self.panel = rows, rows.menu
        self.action, self.section, self.hint, self.plain = action, section, hint, plain
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setFixedHeight(ROW)
        if action is not None:
            self.setEnabled(action.isEnabled())
            self.setToolTip(action.toolTip() if action.toolTip() != action.text() else "")
            action.changed.connect(self.follow)      # the pane stays open: its rows follow their commands
        self.clicked.connect(lambda: self.panel.run(self))

    def follow(self):
        try:
            self.setEnabled(self.action.isEnabled())
            self.update()
        except RuntimeError:
            pass                                    # a row of a layout that has been replaced

    def leaveEvent(self, event):
        if self.rows.current is self:
            self.rows.set_current(None)

    def label(self):
        return self.section if self.section else self.action.text().replace("&&", "\0").replace("&", "").replace("\0", "&")

    def sizeHint(self):
        return QSize(WIDTH - 20, self.height())

    def enterEvent(self, event):
        self.rows.set_current(self, scroll=False)
        self.panel.pointer_on(self)

    def paintEvent(self, _event):
        p = QPainter(self)
        pal = self.palette()
        current = self.rows.current is self or (self.section is not None and self.panel.sub_section == self.section)
        if current and self.isEnabled():
            tint = QColor(pal.color(QPalette.Highlight))
            tint.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(tint)
            p.setRenderHint(QPainter.Antialiasing)
            p.drawRoundedRect(self.rect().adjusted(4, 1, -4, -1), 5, 5)
        text = pal.color(QPalette.Active if self.isEnabled() else QPalette.Disabled, QPalette.WindowText)
        faded = pal.color(QPalette.PlaceholderText)
        box = self.rect().adjusted(12, 0, -12, 0)
        if self.section:
            if self.isEnabled():
                lucide("chevron-right", faded).paint(p, QRect(box.right() - 13, (self.height() - 14) // 2, 14, 14))
            p.setPen(text)
            p.drawText(box, Qt.AlignVCenter | Qt.AlignLeft, self.section)
            return
        act = self.action
        spot = QRect(box.left(), (self.height() - 16) // 2, 16, 16)
        if self.plain:
            pass
        elif act.isCheckable() and act.isChecked():
            mark = QColor(pal.color(QPalette.Highlight))
            mark.setAlpha(90)
            p.setPen(Qt.NoPen)
            p.setBrush(mark)
            p.setRenderHint(QPainter.Antialiasing)
            p.drawRoundedRect(spot.adjusted(-3, -3, 3, 3), 4, 4)
            if act.icon().isNull():
                lucide("check", text).paint(p, spot)
        if not self.plain and not act.icon().isNull():
            act.icon().paint(p, spot, Qt.AlignCenter, act.icon().Mode.Normal if self.isEnabled() else act.icon().Mode.Disabled)
        keys = act.shortcut().toString(QKeySequence.NativeText)
        metrics = p.fontMetrics()
        right = box.right()
        if keys:
            p.setPen(faded)
            p.drawText(box, Qt.AlignVCenter | Qt.AlignRight, keys)
            right -= metrics.horizontalAdvance(keys) + 12
        left = box.left() + (0 if self.plain else 26)
        label = metrics.elidedText(self.label(), Qt.ElideRight, max(40, right - left))
        p.setPen(text)
        p.drawText(QRect(left, 0, right - left, self.height()), Qt.AlignVCenter | Qt.AlignLeft, label)
        if self.hint:
            at = left + metrics.horizontalAdvance(label) + 10
            p.setPen(faded)
            p.drawText(QRect(at, 0, max(0, right - at), self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       metrics.elidedText(self.hint, Qt.ElideLeft, max(0, right - at)))


class Line(QWidget):
    """The line between two groups of rows: one device pixel thick and on a whole pixel
    wherever it falls, so that every line in a panel looks the same at any display scale."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(9)
        self.setEnabled(False)

    def paintEvent(self, event):
        p = QPainter(self)
        d = self.devicePixelRatioF()
        at = self.mapTo(self.window(), QPoint(0, 0))
        y = round((at.y() + self.height() / 2) * d)             # in the window's device pixels
        p.scale(1 / d, 1 / d)
        p.translate(-at.x() * d, -at.y() * d)
        p.fillRect(QRectF(at.x() * d, y, self.width() * d, 1), Colors().line)


class Rows(QScrollArea):
    """A column of rows, one of which may be the current one. It scrolls when the window
    is too short for it."""

    def __init__(self, menu):
        super().__init__()
        self.menu, self.rows, self.current = menu, [], None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)

    def fill(self, items):
        """items: Row, or None for a line. Lines at the ends, and doubled, are left out."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.rows, self.current, self.tall, line = [], None, 0, False
        for item in items:
            if item is None:
                line = bool(self.rows)
                continue
            if line:
                column.addWidget(Line())
                self.tall += 9
                line = False
            column.addWidget(item)
            self.tall += item.height()
            if item.action is not None or item.isEnabled():
                self.rows.append(item)
        column.addStretch(1)
        self.setWidget(holder)

    def usable(self):
        return [r for r in self.rows if r.isEnabled()]

    def set_current(self, row, scroll=True):
        was, self.current = self.current, row
        for r in (was, row):
            if r is not None:
                try:
                    r.update()
                except RuntimeError:
                    pass                        # a row of the layout before this one
        if row is not None and scroll:
            QTimer.singleShot(0, lambda: self.current is row and self.ensureWidgetVisible(row, 0, 30))

    def step(self, by):
        usable = self.usable()
        if not usable:
            return
        if self.current in usable:
            at = (usable.index(self.current) + by) % len(usable)
        else:
            at = 0 if by > 0 else len(usable) - 1
        self.set_current(usable[at])


class Panel(QFrame):
    """A rounded panel with a hairline around it. The line is drawn here, one device pixel
    wide and on whole device pixels wherever the panel sits; a style sheet's border is a
    point wide, which at a display scale of 125% or 150% smears over two pixels on some
    sides and not others."""

    def paintEvent(self, event):
        colors = Colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = self.devicePixelRatioF()
        at = self.mapTo(self.window(), QPoint(0, 0))
        left, top = math.ceil(at.x() * d - 1e-6), math.ceil(at.y() * d - 1e-6)
        right, bottom = math.floor((at.x() + self.width()) * d + 1e-6), math.floor((at.y() + self.height()) * d + 1e-6)
        p.scale(1 / d, 1 / d)
        p.translate(-at.x() * d, -at.y() * d)           # now in the window's device pixels
        p.setPen(QPen(colors.line, 1))
        p.setBrush(colors.panel)
        p.drawRoundedRect(QRectF(left + 0.5, top + 0.5, right - left - 1, bottom - top - 1), RADIUS * d, RADIUS * d)


class SubPanel(Panel):
    """A section's commands, beside the row that opened it."""

    def __init__(self, menu, parent):
        super().__init__(parent)
        self.setObjectName("menuPanel")
        self.list = Rows(menu)
        box = QVBoxLayout(self)
        box.setContentsMargins(1, 5, 1, 5)
        box.addWidget(self.list)
        self.hide()


class MenuPanel(Panel):
    """contents() gives what the menu holds, each time it is laid out:
    (top, sections, bottom), where top and bottom are lists of QAction (None for a line)
    and sections is [(title, [QAction or None or (QAction, hint)])]. closed: the menu has
    gone, by a command, Escape, F10 or a click elsewhere."""

    closed = Signal()

    def __init__(self, contents, parent):
        super().__init__(parent)
        self.setObjectName("menuPanel")
        self.contents = contents
        self.stale_timer = QTimer(self, singleShot=True, interval=0, timeout=self.refresh)
        self.linger = QTimer(self, singleShot=True, interval=LINGER, timeout=self.follow_pointer)
        self.pointed = None
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the commands")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.build())
        self.search.installEventFilter(self)
        self.list = Rows(self)
        box = QVBoxLayout(self)
        box.setContentsMargins(1, 9, 1, 5)
        box.setSpacing(7)
        edge = QVBoxLayout()
        edge.setContentsMargins(9, 0, 9, 0)
        edge.addWidget(self.search)
        box.addLayout(edge)
        box.addWidget(self.list, 1)
        self.sub = SubPanel(self, parent)
        self.sub_section = None
        self.search_only = set()        # sections that have no row: their commands are found by searching
        self.keep = set()               # widgets a click on which does not close the menu (its button)
        self.at = QPoint(EDGE, EDGE)
        self.hide()
        QApplication.instance().focusChanged.connect(self.focus_moved)

    # ---- compatibility with what reads the panel -------------------------------------------

    @property
    def rows(self):
        return self.list.rows

    @property
    def current(self):
        return self.list.current

    # ---- showing and closing ----------------------------------------------------------------

    def popup(self, at):
        """Open with the top left corner at `at` (in the window), the caret in the search box."""
        self.at = at
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.build()
        self.show()
        self.raise_()
        self.search.setFocus()
        QApplication.instance().installEventFilter(self)

    def close_menu(self):
        if not self.isVisible():
            return
        QApplication.instance().removeEventFilter(self)
        self.linger.stop()
        self.close_sub()
        self.hide()
        self.closed.emit()

    def focus_moved(self, _old, new):
        if self.isVisible() and new is not None and new is not self.search:
            self.close_menu()

    def place(self):
        """The panel's size follows what it holds, as far as the window lets it."""
        win = self.parentWidget()
        tall = self.list.tall + self.search.sizeHint().height() + 9 + 7 + 5 + 2
        x = max(EDGE, min(self.at.x(), win.width() - WIDTH - EDGE))
        self.setGeometry(x, self.at.y(), WIDTH, max(ROW * 2, min(tall, win.height() - self.at.y() - EDGE)))

    # ---- what is shown ----------------------------------------------------------------------

    def commands(self):
        """Every command in the menu once, with the section it is in: [(QAction, section)]."""
        top, sections, bottom = self.contents()
        out, seen = [], set()
        for title, items in [("", top)] + list(sections) + [("", bottom)]:
            for item in items:
                act = item[0] if isinstance(item, tuple) else item
                if act is not None and id(act) not in seen:
                    seen.add(id(act))
                    out.append((act, title))
        return out

    def row(self, rows, item, hint="", plain=False):
        if item is None:
            return None
        act, hint = item if isinstance(item, tuple) else (item, hint)
        return Row(rows, action=act, hint=hint, plain=plain)

    def build(self):
        """Lay the panel out: the search's results if there is a search, else the sections."""
        self.close_sub()
        words = self.search.text().lower().split()
        items = []
        if words:
            for act, title in self.commands():
                text = act.text().replace("&", "").lower()
                if all(w in text or w in title.lower() for w in words):
                    items.append(self.row(self.list, act, title))
            if not items:
                nothing = Row(self.list, section="No command found")
                nothing.setEnabled(False)
                items.append(nothing)
        else:
            top, sections, bottom = self.contents()
            items += [self.row(self.list, item, plain=True) for item in top] + [None]
            items += [Row(self.list, section=title) for title, _ in sections if title not in self.search_only]
            items += [None] + [self.row(self.list, item, plain=True) for item in bottom]
        self.list.fill(items)
        self.place()
        if words and self.list.usable():
            self.list.set_current(self.list.usable()[0])

    def refresh(self):
        """Lay the menu out again: the commands or their keys have changed."""
        if self.isVisible():
            self.build()

    def stale(self):
        """What the menu holds has changed (styles, recent documents, keys): refresh() soon."""
        self.stale_timer.start()

    # ---- the subpanel -----------------------------------------------------------------------

    def open_sub(self, section, keys=False):
        """The section's commands beside its row. keys: the keyboard moves into them."""
        head = next((r for r in self.list.rows if r.section == section), None)
        items = dict(self.contents()[1]).get(section)
        if head is None or items is None:
            return
        if self.sub_section != section or not self.sub.isVisible():
            self.sub_section = section
            self.sub.list.fill([self.row(self.sub.list, item) for item in items])
            win = self.parentWidget()
            tall = min(self.sub.list.tall + 12, win.height() - 2 * EDGE)
            x = self.geometry().right() + 1 + GAP
            if x + WIDTH > win.width() - EDGE:          # a narrow window: over the panel, as far right as fits
                x = max(EDGE, win.width() - WIDTH - EDGE)
            y = head.mapTo(win, QPoint(0, 0)).y() - 6
            y = max(EDGE, min(y, win.height() - EDGE - tall))
            self.sub.setGeometry(x, y, WIDTH, tall)
            self.sub.show()
            self.sub.raise_()
        self.list.set_current(head)
        if keys and self.sub.list.usable():
            self.sub.list.set_current(self.sub.list.usable()[0])
        for r in self.list.rows:
            r.update()

    def close_sub(self):
        if self.sub_section is not None:
            self.sub_section = None
            self.sub.hide()
            self.sub.list.fill([])
            for r in self.list.rows:
                try:
                    r.update()
                except RuntimeError:
                    pass

    def pointer_on(self, row):
        """The pointer is on a row. On the panel's own rows the subpanel follows it after a
        moment, so that it can cross other rows on its way into the subpanel."""
        if row.rows is self.list:
            self.pointed = row
            self.linger.start()
        else:
            self.linger.stop()
            head = next((r for r in self.list.rows if r.section == self.sub_section), None)
            if head is not None and self.list.current is not head:
                self.list.set_current(head, scroll=False)

    def follow_pointer(self):
        row = self.pointed
        try:
            if row is None or not row.underMouse():
                return
        except RuntimeError:
            return
        if row.section and row.isEnabled():
            self.open_sub(row.section)
        else:
            self.close_sub()

    # ---- moving about and running -----------------------------------------------------------

    def run(self, row, keys=False):
        if row is None or not row.isEnabled():
            return
        if row.section:
            self.linger.stop()
            return self.open_sub(row.section, keys)
        action = row.action
        self.close_menu()
        QTimer.singleShot(0, action.trigger)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.search:
            return kind == QEvent.KeyPress and self.key(event)
        if kind == QEvent.MouseButtonPress and isinstance(watched, QWidget):
            inside = watched in self.keep or any(watched is p or p.isAncestorOf(watched) for p in (self, self.sub))
            if not inside:
                self.close_menu()               # the click still goes where it was made
        elif kind in (QEvent.WindowDeactivate, QEvent.Resize) and watched is self.window():
            self.close_menu()
        return False

    def keyPressEvent(self, event):
        if not self.key(event):
            super().keyPressEvent(event)

    def key(self, event):
        key = event.key()
        in_sub = self.sub.isVisible() and self.sub.list.current is not None
        rows = self.sub.list if in_sub else self.list
        if key in (Qt.Key_Down, Qt.Key_Up):
            if not in_sub:
                self.close_sub()
            rows.step(1 if key == Qt.Key_Down else -1)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.run(rows.current, keys=True)
        elif key == Qt.Key_Right and not in_sub and rows.current is not None and rows.current.section:
            self.run(rows.current, keys=True)
        elif key == Qt.Key_Left and in_sub:
            self.sub.list.set_current(None)
            self.close_sub()
        elif key == Qt.Key_Escape:
            if self.search.text():
                self.search.clear()
            elif self.sub.isVisible():
                self.close_sub()
            else:
                self.close_menu()
        elif key == Qt.Key_F10:
            self.close_menu()
        else:
            return False
        return True
