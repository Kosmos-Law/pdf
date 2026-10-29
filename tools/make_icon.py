"""Generate the Kosmic PDF app icon (SVG plus PNGs) into kosmicpdf/icons/app/.

A document page (Lucide's file shape, with its cut corner but no fold) in a deepened
version of the kosmos.law frost-to-amber gradient, carrying the three text lines of
Lucide's file-text icon in white. Plain strokes, rather than a logo or lettering, stay
recognisable down to panel size. A faint dark edge and a soft drop shadow hold the
page on light and dark panels.

The development copy (./install.sh --dev) gets the same icon in greys, so the two
are easy to tell apart in the Menu and the panel.

Run: .venv/bin/python tools/make_icon.py
"""
import os
import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kosmicpdf", "icons", "app")
# Kosmos palette (kosmos.law): night for ink; frost and amber, deepened so the page
# holds its own on light panels.
NIGHT, FROST, AMBER = "#2e3440", "#6aaabd", "#e2b461"
DEV_LIGHT, DEV_DARK = "#8c96a8", "#c3c9d4"      # slate greys for the development copy

# Lucide file page in its 24-unit grid (stroked 2 units wide, so it reaches 1 unit beyond).
PAGE = ("M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588"
        "A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z")

# The three text lines of Lucide's file-text icon (the top one shorter), in the same
# 24-unit grid as the page, drawn in white: a little lighter than Lucide's and spread
# a little further apart (Lucide has them at 9, 13 and 17), about the same centre.
LINES = ((8, 10, 8.4), (8, 16, 13), (8, 16, 17.6))     # (left, right, height)
LINE_WIDTH = 1.6
LINE = "#ffffff"
SCALE = 10.6                     # px per grid unit in the 256 px icon
OFFSET = 128 - 12 * SCALE        # where the grid starts in it, px


def lines(size=None):
    """The text lines. For a small PNG (`size` px across), each line's thickness and
    height are rounded to whole pixels, so it stays crisp instead of blurring across
    two rows of pixels."""
    width, rows = LINE_WIDTH, [y for _, _, y in LINES]
    if size:
        unit, offset = size / 256 * SCALE, size / 256 * OFFSET
        px = max(1, round(LINE_WIDTH * unit))
        width = px / unit
        rows = [(round(offset + y * unit - px / 2) + px / 2 - offset) / unit for y in rows]
    return (f'<g fill="none" stroke="{LINE}" stroke-width="{width:.4f}">'
            + "".join(f'<path d="M{x1} {y:.4f}H{x0}"/>' for (x0, x1, _), y in zip(LINES, rows)) + "</g>")


def shadow():
    """A soft drop shadow, a little below the page: rings of widening stroke, each
    fainter than the last, standing in for a blur (which QtSvg can't draw)."""
    rings = ((4.6, 0.035), (3.8, 0.05), (3.0, 0.07), (2.2, 0.1))
    return "".join(f'<path d="{PAGE}" transform="translate(0 0.55)" fill="#000" fill-opacity="0.1" '
                   f'stroke="#000" stroke-opacity="{alpha}" stroke-width="{width}"/>' for width, alpha in rings)


def svg(start=FROST, end=AMBER, size=None):
    """The icon; with `size`, tuned for a PNG of that many pixels (see lines())."""
    scale = SCALE
    tx, ty = OFFSET, OFFSET
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="kosmos" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0.15" stop-color="{start}"/><stop offset="0.85" stop-color="{end}"/>
    </linearGradient>
  </defs>
  <g transform="translate({tx:.1f} {ty:.1f}) scale({scale})" stroke-linecap="round" stroke-linejoin="round">
    {shadow()}
    <path d="{PAGE}" fill="none" stroke="{NIGHT}" stroke-opacity="0.32" stroke-width="2.4"/>
    <path d="{PAGE}" fill="url(#kosmos)" stroke="url(#kosmos)" stroke-width="2"/>
    {lines(size)}
  </g>
</svg>
"""


def main():
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    for name, colours in (("kosmicpdf", (FROST, AMBER)), ("kosmicpdf-dev", (DEV_LIGHT, DEV_DARK))):
        with open(os.path.join(OUT, f"{name}.svg"), "w") as f:
            f.write(svg(*colours))
        for size in (16, 24, 32, 48, 64, 128, 256):
            img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            QSvgRenderer(QByteArray(svg(*colours, size=size).encode())).render(p, QRectF(0, 0, size, size))
            p.end()
            img.save(os.path.join(OUT, f"{name}-{size}.png"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
