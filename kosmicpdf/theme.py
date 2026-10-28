"""Colours and icons that follow the desktop's light or dark theme.

Colours are derived from the Qt palette, which Qt reads from the GTK theme, so
the app matches Mint-Y, Mint-Y-Dark, or whatever theme is active. Icons are
Lucide (ISC licence, see icons/LICENSE-lucide), tinted to the theme's text colour.
"""
import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "kosmicpdf", "icons")
ICON_SIZES = (16, 18, 20, 24, 32, 36, 40, 48)
TOOLBAR_ICON = 16      # px
ICON_STROKE = 1.5      # Lucide line width in its 24-unit grid; its default of 2 looks heavy at this size
ICON_OPACITY = 1.0


class Colors:
    def __init__(self, palette=None):
        pal = palette or QApplication.palette()
        win = pal.color(QPalette.Window)
        self.dark = win.lightness() < 128
        # Like Xreader: pages sit on the window colour, panels are a shade lighter.
        self.pages = QColor(win) if self.dark else win.darker(106)
        self.panel = win.lighter(112) if self.dark else win.lighter(102)
        self.window = QColor(win)
        self.text = pal.color(QPalette.WindowText)
        self.accent = pal.color(QPalette.Highlight)
        self.line = win.lighter(150) if self.dark else win.darker(115)       # hairline borders
        self.field = win.darker(125) if self.dark else win.lighter(104)      # text boxes, menus
        self.shadow = 46 if self.dark else 24      # alpha of the innermost shadow ring

    def key(self):
        return (self.pages.name(), self.panel.name(), self.text.name(), self.accent.name())

    def accent_alpha(self, alpha):
        c = QColor(self.accent)
        c.setAlpha(alpha)
        return c

    def rgba(self, c, alpha):
        return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def lucide(name, color):
    """A crisp, multi-size QIcon from a bundled Lucide SVG in the given colour."""
    path = os.path.join(ICON_DIR, f"{name}.svg")
    if not os.path.exists(path):
        return QIcon()
    svg = open(path, encoding="utf-8").read()
    icon = QIcon()
    svg = svg.replace('stroke-width="2"', f'stroke-width="{ICON_STROKE}"')
    for mode, opacity in ((QIcon.Normal, ICON_OPACITY), (QIcon.Disabled, 0.38 * ICON_OPACITY)):
        data = QByteArray(svg.replace('stroke="currentColor"',
                                      f'stroke="{color.name()}" stroke-opacity="{opacity}"').encode())
        renderer = QSvgRenderer(data)
        for size in ICON_SIZES:
            img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            renderer.render(p, QRectF(0, 0, size, size))
            p.end()
            icon.addPixmap(QPixmap.fromImage(img), mode)
    return icon


def draw_page_shadow(p, rect, colors):
    """A soft three-ring shadow, slightly heavier below the page."""
    p.save()
    p.setPen(Qt.NoPen)
    r = QRectF(rect)
    for d in (3, 2, 1):
        p.setBrush(QColor(0, 0, 0, colors.shadow // d))
        p.drawRoundedRect(r.adjusted(-d, -d + 1, d, d + 1), d + 1, d + 1)
    p.restore()


def swatch(rgb):
    """A rounded-square colour swatch with a hairline outline, for highlight colours."""
    icon = QIcon()
    for size in (16, 32):
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        fill = QColor.fromRgbF(*rgb)
        p.setPen(QPen(fill.darker(160), size / 16))
        p.setBrush(fill)
        side = size * 0.84
        p.drawRoundedRect(QRectF((size - side) / 2, (size - side) / 2, side, side), size * 0.2, size * 0.2)
        p.end()
        icon.addPixmap(QPixmap.fromImage(img))
    return icon


def icon_file(name, color, stroke=2.0):
    """Path to a tinted copy of a Lucide SVG, for use in stylesheets (which need a file)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{name}-{color.name()[1:]}-{stroke}.svg")
    if not os.path.exists(path):
        svg = open(os.path.join(ICON_DIR, f"{name}.svg"), encoding="utf-8").read()
        svg = svg.replace('stroke="currentColor"', f'stroke="{color.name()}"')
        svg = svg.replace('stroke-width="2"', f'stroke-width="{stroke}"')
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    return path


def stylesheet(c):
    """A flat look for the whole app: no gradients, hairline borders, slender
    scroll bars (like Xreader's), and colours taken from the desktop theme."""
    t = c.text
    soft = c.rgba(t, 165)            # secondary text, e.g. inactive tabs
    hover = c.rgba(t, 22)
    press = c.rgba(t, 38)
    down = icon_file("chevron-down", t, 2.5)
    up = icon_file("chevron-up", t, 2.5)
    close = icon_file("x", t, 2.0)
    return f"""
QToolBar {{ background:{c.window.name()}; border:none; border-bottom:1px solid {c.line.name()};
           padding:5px 6px; spacing:3px; }}
QToolBar::separator {{ width:1px; background:{c.line.name()}; margin:5px 6px; }}
QToolButton {{ border:1px solid transparent; border-radius:5px; padding:5px; }}
QToolButton:hover {{ background:{hover}; }}
QToolButton:pressed {{ background:{press}; }}
QToolButton:checked {{ background:{c.rgba(c.accent, 55)}; border-color:{c.rgba(c.accent, 130)}; }}
QToolButton::menu-indicator {{ image:url({down}); width:8px; height:8px;
                              subcontrol-origin:padding; subcontrol-position:bottom right; }}

QTabWidget::pane {{ border:none; }}
QTabBar {{ background:{c.window.name()}; }}
QTabBar::tab {{ background:transparent; color:{soft}; border:none; border-bottom:2px solid transparent;
               padding:7px 8px 6px 12px; margin:0; }}
QTabBar::tab:selected {{ background:{c.panel.name()}; color:{t.name()}; border-bottom-color:{c.accent.name()}; }}
QTabBar::tab:hover:!selected {{ background:{hover}; }}
QTabBar::close-button {{ image:url({close}); subcontrol-position:right; border-radius:3px;
                        margin:2px; padding:1px; }}
QTabBar::close-button:hover {{ background:{press}; }}

QScrollBar:vertical {{ background:transparent; width:14px; margin:0; }}
QScrollBar:horizontal {{ background:transparent; height:14px; margin:0; }}
QScrollBar::handle {{ background:{c.rgba(t, 70)}; border-radius:4px; margin:3px; }}
QScrollBar::handle:vertical {{ min-height:36px; }}
QScrollBar::handle:horizontal {{ min-width:36px; }}
QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background:{c.rgba(t, 125)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; border:none; background:none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:none; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background:{c.field.name()}; color:{t.name()};
    border:1px solid {c.line.name()}; border-radius:4px; padding:3px 6px; min-height:20px;
    selection-background-color:{c.accent.name()}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color:{c.accent.name()}; }}
QComboBox::drop-down {{ border:none; width:18px; }}
QComboBox::down-arrow {{ image:url({down}); width:10px; height:10px; }}
QComboBox QAbstractItemView {{ background:{c.field.name()}; border:1px solid {c.line.name()};
    selection-background-color:{c.rgba(c.accent, 70)}; selection-color:{t.name()}; outline:none; }}
QSpinBox, QDoubleSpinBox {{ padding-right:16px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin:border; subcontrol-position:top right;
    width:16px; border:none; background:transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right;
    width:16px; border:none; background:transparent; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background:{hover}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image:url({up}); width:8px; height:8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image:url({down}); width:8px; height:8px; }}

QPushButton {{ background:{c.field.name()}; color:{t.name()}; border:1px solid {c.line.name()};
              border-radius:5px; padding:5px 14px; }}
QPushButton:hover {{ background:{c.rgba(c.accent, 30)}; }}
QPushButton:pressed {{ background:{c.rgba(c.accent, 55)}; }}
QPushButton:default {{ border-color:{c.accent.name()}; }}

QMenuBar {{ background:{c.window.name()}; }}
QMenuBar::item {{ padding:4px 9px; border-radius:4px; background:transparent; }}
QMenuBar::item:selected {{ background:{hover}; }}
QMenu {{ background:{c.field.name()}; border:1px solid {c.line.name()}; padding:4px; }}
QMenu::item {{ padding:5px 26px 5px 10px; border-radius:4px; }}
QMenu::item:selected {{ background:{c.rgba(c.accent, 60)}; color:{t.name()}; }}
QMenu::item:disabled {{ color:{c.rgba(t, 100)}; }}
QMenu::icon {{ padding-left:8px; }}
QMenu::separator {{ height:1px; background:{c.line.name()}; margin:4px 8px; }}

QSplitter::handle {{ background:{c.line.name()}; }}
QSplitter::handle:horizontal {{ width:1px; }}
QStatusBar {{ background:{c.window.name()}; border-top:1px solid {c.line.name()}; }}
QStatusBar::item {{ border:none; }}
"""
