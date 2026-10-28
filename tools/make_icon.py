"""Generate the Kosmic PDF app icon (SVG plus PNGs) into kosmicpdf/icons/app/.

A document page (Lucide's file shape, with its cut corner but no fold) in a deepened
version of the kosmos.law frost-to-amber gradient, carrying the Kosmos K-and-sparkle
mark in night. The mark alone, without lettering, stays legible down to panel size.
A faint dark edge and drop shadow hold the page on light and dark panels.

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

# Lucide file page in its 24-unit grid (stroked 2 units wide, so it reaches 1 unit beyond).
PAGE = ("M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588"
        "A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z")

# The Kosmos mark exactly as in the kosmos.law favicon, in its 100-unit grid.
KAPPA = ("M28.06 20.46Q26.93 24.89 26.93 48.77Q32.69 42.73 37.78 37.64Q46.19 29.24 47.79 27.35"
         "Q51.09 23.48 51.28 20.46H69.69Q66.95 22.63 60.72 29.14Q54.77 35.18 51.75 38.34Q48.73 41.51 48.45 41.79"
         "Q47.22 43.02 45.48 44.71Q43.73 46.41 41.56 48.58Q47.60 53.59 51.47 57.08Q65.25 70.01 71.29 79.54"
         "H54.40Q53.08 75.67 50.05 71.80Q48.73 70.20 46.28 67.70Q43.83 65.20 40.24 61.61Q32.03 53.49 26.93 50.09"
         "V67.27Q27.03 71.71 27.26 74.73Q27.50 77.75 27.97 79.54H14.00Q15.04 75.96 15.13 67.46Q15.13 49.91 15.13 40.18"
         "Q15.13 30.46 15.04 28.29Q14.94 26.12 14.71 24.19Q14.47 22.25 14.00 20.46Z")
SPARKLE = ("M76.87 31.10Q79.61 45.49 94.00 48.23Q79.61 50.97 76.87 65.36Q74.13 50.97 59.74 48.23"
           "Q74.13 45.49 76.87 31.10Z")
MARK_LEFT, MARK_RIGHT, MARK_TOP, MARK_BOTTOM = 14.0, 94.0, 20.46, 79.54
MARK_WIDTH = 13.5      # in the 24-unit grid; the page interior is about 16 wide


def mark():
    """The Kosmos mark, MARK_WIDTH units wide, centred on the page."""
    s = MARK_WIDTH / (MARK_RIGHT - MARK_LEFT)
    height = (MARK_BOTTOM - MARK_TOP) * s
    x, y = 12 - MARK_WIDTH / 2 - MARK_LEFT * s, 12 - height / 2 - MARK_TOP * s
    return (f'<g transform="translate({x:.3f} {y:.3f}) scale({s:.5f})" fill="{NIGHT}">'
            f'<path d="{KAPPA}"/><path d="{SPARKLE}"/></g>')


def svg():
    scale = 10.6
    tx, ty = 128 - 12 * scale, 128 - 12 * scale
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="kosmos" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0.15" stop-color="{FROST}"/><stop offset="0.85" stop-color="{AMBER}"/>
    </linearGradient>
  </defs>
  <g transform="translate({tx:.1f} {ty:.1f}) scale({scale})" stroke-linecap="round" stroke-linejoin="round">
    <path d="{PAGE}" transform="translate(0 0.45)" fill="#000" fill-opacity="0.18" stroke="#000" stroke-opacity="0.18" stroke-width="2"/>
    <path d="{PAGE}" fill="none" stroke="{NIGHT}" stroke-opacity="0.22" stroke-width="2.35"/>
    <path d="{PAGE}" fill="url(#kosmos)" stroke="url(#kosmos)" stroke-width="2"/>
    {mark()}
  </g>
</svg>
"""


def main():
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "kosmicpdf.svg"), "w") as f:
        f.write(svg())
    for size in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg().encode())).render(p, QRectF(0, 0, size, size))
        p.end()
        img.save(os.path.join(OUT, f"kosmicpdf-{size}.png"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
