"""Colours and icons that follow the desktop's light or dark theme.

Colours are derived from the Qt palette, which Qt reads from the GTK theme, so
the app matches Mint-Y, Mint-Y-Dark, or whatever theme is active. Icons are
Lucide (ISC licence, see icons/LICENSE-lucide), tinted to the theme's text colour.
"""
import os

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QProxyStyle, QPushButton, QStyle

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "kosmicpdf", "icons")
TOOLBAR_ICON = 16      # px, also the menus' icon size
NOTE_MENU_ICON = 12    # px, the menu button on a typewriter note
ICON_STROKE = 1.5      # Lucide line width in its 24-unit grid; its default of 2 looks heavy at this size
ICON_OPACITY = 1.0
BADGE = "#c62828"      # the red dot on a button that has something waiting: Save, or OCR for a scan
WARNING = "#d19a1e"    # amber, for the warning symbol in message boxes
REDACT = "#c0392b"     # a muted red, tinting the bar shown while redacting


def mix(a, b, share):
    """Colour a with `share` of colour b blended in."""
    return QColor.fromRgbF(*(x + (y - x) * share for x, y in zip(a.getRgbF()[:3], b.getRgbF()[:3])))


def kosmos_dark_palette():
    """A dark palette in the Kosmos colours (kosmos.law: night, snow, frost)."""
    night, deep, rule, dim, text, frost = "#2e3440", "#3b4252", "#434c5e", "#aab3c5", "#d8dee9", "#88c0d0"
    pal = QPalette()
    for role, c in ((QPalette.Window, night), (QPalette.WindowText, text), (QPalette.Base, deep),
                    (QPalette.AlternateBase, rule), (QPalette.Text, text), (QPalette.Button, deep),
                    (QPalette.ButtonText, text), (QPalette.ToolTipBase, deep), (QPalette.ToolTipText, text),
                    (QPalette.PlaceholderText, dim), (QPalette.Highlight, frost),
                    (QPalette.HighlightedText, night), (QPalette.Link, frost), (QPalette.BrightText, "#ffffff"),
                    (QPalette.Light, rule), (QPalette.Midlight, rule), (QPalette.Mid, rule),
                    (QPalette.Dark, "#242933"), (QPalette.Shadow, "#1c2027")):
        pal.setColor(role, QColor(c))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(dim))
    return pal


def choose_palette(dark_wanted, platform_palette):
    """The platform's palette, unless the desktop wants dark but the palette is light.

    That happens inside a Flatpak when the desktop's GTK theme isn't available
    to the sandbox: Qt falls back to a light default even in dark mode.
    """
    if dark_wanted and platform_palette.color(QPalette.Window).lightness() >= 128:
        return kosmos_dark_palette()
    return platform_palette


def follow_color_scheme(app):
    """Apply choose_palette() now and whenever the desktop switches light/dark."""
    hints = app.styleHints()

    def update(*_):
        app.setPalette(QPalette())                 # back to the platform's own palette
        dark = hints.colorScheme() == Qt.ColorScheme.Dark
        chosen = choose_palette(dark, app.palette())
        if chosen is not app.palette():
            app.setPalette(chosen)

    hints.colorSchemeChanged.connect(update)
    update()


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
        self.redact_band = mix(win, QColor(REDACT), 0.16 if self.dark else 0.09)   # the bar shown while redacting
        self.redact_line = mix(win, QColor(REDACT), 0.45 if self.dark else 0.35)

    def key(self):
        return (self.pages.name(), self.panel.name(), self.text.name(), self.accent.name())

    def accent_alpha(self, alpha):
        c = QColor(self.accent)
        c.setAlpha(alpha)
        return c

    def rgba(self, c, alpha):
        return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def icon_sizes():
    """The pixel sizes the screens will ask icons for. Drawing only these (rather than a
    spread of sizes) keeps startup quick, and each icon is drawn at exactly the size
    shown, so it isn't rescaled and stays crisp at fractional scales like 1.4."""
    ratios = {s.devicePixelRatio() for s in QApplication.screens()} or {1.0}
    return sorted({round(n * r) for n in (NOTE_MENU_ICON, TOOLBAR_ICON) for r in ratios})


def lucide(name, color, dot=False, stripe=None, sizes=None, gap=0.0):
    """A crisp QIcon from a bundled Lucide SVG in the given colour, optionally with a
    red dot in its bottom right corner (see BADGE), or drawn a little smaller above a
    stripe of colour (an RGB tuple), like the highlighter in a word processor. Drawn at
    the toolbar's sizes unless `sizes` (in device pixels) says otherwise. `gap` leaves
    clear space to the right, as a fraction of the size (see DIALOG_ICON_GAP)."""
    path = os.path.join(ICON_DIR, f"{name}.svg")
    if not os.path.exists(path):
        return QIcon()
    svg = open(path, encoding="utf-8").read()
    icon = QIcon()
    svg = svg.replace('stroke-width="2"', f'stroke-width="{ICON_STROKE}"')
    sizes = sizes or icon_sizes()
    for mode, opacity in ((QIcon.Normal, ICON_OPACITY), (QIcon.Disabled, 0.38 * ICON_OPACITY)):
        data = QByteArray(svg.replace('stroke="currentColor"',
                                      f'stroke="{color.name()}" stroke-opacity="{opacity}"').encode())
        renderer = QSvgRenderer(data)
        for size in sizes:
            img = QImage(size + round(size * gap), size, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            if stripe:
                # Only the drawing's own extent (Lucide leaves a margin), so it stays a good size above the stripe.
                renderer.setViewBox(QRectF(2, 3, 21, 18))
                h = size * 0.74
                renderer.render(p, QRectF((size - h * 21 / 18) / 2, 0, h * 21 / 18, h))
                draw_stripe(p, size, stripe, opacity)
            else:
                renderer.render(p, QRectF(0, 0, size, size))
            if dot:
                draw_dot(p, size)
            p.end()
            icon.addPixmap(QPixmap.fromImage(img), mode)
    return icon


# The icons Qt asks the style for in dialogs, drawn from Lucide rather than taken from
# the desktop's icon theme, whose filled icons look heavy beside the rest of the app.
DIALOG_ICONS = {
    QStyle.SP_DialogSaveButton: "save", QStyle.SP_DialogDiscardButton: "trash-2", QStyle.SP_DialogCancelButton: "x",
    QStyle.SP_DialogCloseButton: "x", QStyle.SP_DialogNoButton: "x", QStyle.SP_DialogOkButton: "check",
    QStyle.SP_DialogYesButton: "check", QStyle.SP_DialogApplyButton: "check",
    QStyle.SP_DialogOpenButton: "folder-open", QStyle.SP_DialogResetButton: "rotate-ccw",
}
MESSAGE_ICONS = {      # the symbol beside a message box's text, and its colour (None: the theme's accent)
    QStyle.SP_MessageBoxQuestion: ("circle-question-mark", None), QStyle.SP_MessageBoxInformation: ("info", None),
    QStyle.SP_MessageBoxWarning: ("triangle-alert", WARNING), QStyle.SP_MessageBoxCritical: ("circle-x", BADGE),
}
MESSAGE_ICON = 32      # px, as Qt lays out message boxes
# Qt sets a button's icon right against its text; dialog buttons' icons carry this much
# clear space on their right (px), and the buttons show icons this much wider to fit it.
DIALOG_ICON_GAP = 5


class LucideStyle(QProxyStyle):
    """The desktop's own style, but with Lucide icons in dialogs. Install it with
    app.setStyle(LucideStyle(app.style().name()))."""

    def __init__(self, base):
        super().__init__(base)
        self._icons = {}

    def standardIcon(self, which, option=None, widget=None):
        pal = QApplication.palette()
        gap = 0.0
        if which == QStyle.SP_LineEditClearButton:      # the × inside a text box, e.g. the find field
            name, color, sizes = "x", pal.color(QPalette.PlaceholderText), None
        elif which in DIALOG_ICONS:
            name, color, sizes = DIALOG_ICONS[which], pal.color(QPalette.ButtonText), None
            gap = DIALOG_ICON_GAP / TOOLBAR_ICON
        elif which in MESSAGE_ICONS:
            name, color = MESSAGE_ICONS[which]
            color = QColor(color) if color else pal.color(QPalette.Highlight)
            ratios = {s.devicePixelRatio() for s in QApplication.screens()} or {1.0}
            sizes = sorted({round(MESSAGE_ICON * r) for r in ratios})
        else:
            return super().standardIcon(which, option, widget)
        key = (name, color.name(), gap)
        if key not in self._icons:
            self._icons[key] = lucide(name, color, sizes=sizes, gap=gap)
        return self._icons[key]

    def polish(self, widget):
        super().polish(widget)
        if isinstance(widget, QPushButton):     # room for the gap drawn into dialog icons
            widget.setIconSize(QSize(TOOLBAR_ICON + DIALOG_ICON_GAP, TOOLBAR_ICON))


def draw_stripe(p, size, rgb, opacity):
    fill = QColor.fromRgbF(*rgb)
    p.setOpacity(opacity)
    p.setPen(QPen(fill.darker(165), max(1.0, size / 22)))
    p.setBrush(fill)
    p.drawRoundedRect(QRectF(size * 0.06, size * 0.8, size * 0.88, size * 0.17), size * 0.05, size * 0.05)
    p.setOpacity(1)


def draw_dot(p, size):
    """The badge dot, with a thin clear ring cut out of the icon around it so it stands
    apart from the strokes beneath on any background."""
    d = size * 0.42
    centre = QPointF(size - d / 2, size - d / 2)
    p.setPen(Qt.NoPen)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.drawEllipse(centre, d / 2 + size * 0.09, d / 2 + size * 0.09)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    p.setBrush(QColor(BADGE))
    p.drawEllipse(centre, d / 2, d / 2)


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
QToolBar#findBar {{ padding:3px 6px; }}
QLineEdit[notFound="true"] {{ background:{c.redact_band.name()}; border-color:{c.redact_line.name()}; }}
QToolBar#redactBar {{ background:{c.redact_band.name()}; border-bottom:1px solid {c.redact_line.name()}; padding:3px 6px; }}
QToolButton[popupMode="1"] {{ padding-right:17px; }}
QToolButton::menu-button {{ border:none; border-left:1px solid transparent; width:15px;
                           border-top-right-radius:5px; border-bottom-right-radius:5px; }}
QToolButton::menu-button:hover {{ background:{hover}; border-left-color:{c.line.name()}; }}
QToolButton::menu-arrow {{ image:url({down}); width:9px; height:9px; }}
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
