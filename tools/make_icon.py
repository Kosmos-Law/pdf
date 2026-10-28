"""Generate the Kosmic PDF app icon (SVG plus PNGs) into kosmicpdf/icons/app/.

A document page in the Kosmos brand: filled with the frost-to-amber gradient of
the kosmos.law favicon, with a translucent paper dog-ear, the Kosmos sparkle and
text lines in night. The page shape signals "PDF"; the colours and sparkle tie
it to Kosmos. A faint drop shadow sits it on light and dark panels alike.
Small sizes get heavier lines so they don't fade away.

Run: .venv/bin/python tools/make_icon.py
"""
import os
import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kosmicpdf", "icons", "app")
# Kosmos palette (kosmos.law CSS variables).
NIGHT, SNOW, FROST, AMBER = "#2e3440", "#eceff4", "#88c0d0", "#ebcb8b"

# Lucide file-text page, in its 24-unit grid. It is stroked 2 units wide, so its
# outer edge lies 1 unit outside this path; the corner cut's outer edge is x - y = 14.41.
PAGE = ("M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588"
        "A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z")
# Dog-ear: its outer side follows the stroked page's real outline (both rounded
# corners and the cut, i.e. Lucide's arcs grown from 2.4 to 3.4), and its legs sit on
# Lucide's own crease lines (x = 14, y = 8), so it fills the corner exactly.
DOG_EAR = "M14 1A3.4 3.4 0 0 1 16.411 2.003L19.996 5.587A3.4 3.4 0 0 1 21 8H15a1 1 0 0 1-1-1z"
LINES = ("M8 17h8", "M14.2 13h1.8")


def sparkle(cx, cy, r):
    """The Kosmos sparkle: four points joined by inward curves, as in the kosmos.law favicon."""
    k = 0.16 * r
    return (f"M{cx} {cy - r}Q{cx + k} {cy - k} {cx + r} {cy}Q{cx + k} {cy + k} {cx} {cy + r}"
            f"Q{cx - k} {cy + k} {cx - r} {cy}Q{cx - k} {cy - k} {cx} {cy - r}Z")


def svg(line_width):
    scale = 10.6
    tx, ty = 128 - 12 * scale, 128 - 12 * scale
    lines = "".join(f'<path d="{d}"/>' for d in LINES)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="kosmos" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0.15" stop-color="{FROST}"/><stop offset="0.85" stop-color="{AMBER}"/>
    </linearGradient>
  </defs>
  <g transform="translate({tx:.1f} {ty:.1f}) scale({scale})" stroke-linecap="round" stroke-linejoin="round">
    <path d="{PAGE}" transform="translate(0 0.45)" fill="#000" fill-opacity="0.18" stroke="#000" stroke-opacity="0.18" stroke-width="2"/>
    <path d="{PAGE}" fill="url(#kosmos)" stroke="url(#kosmos)" stroke-width="2"/>
    <path d="{DOG_EAR}" fill="{SNOW}" fill-opacity="0.6"/>
    <path d="{sparkle(9.4, 11.6, 3.3)}" fill="{NIGHT}"/>
    <g fill="none" stroke="{NIGHT}" stroke-width="{line_width}">{lines}</g>
  </g>
</svg>
"""


def main():
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "kosmicpdf.svg"), "w") as f:
        f.write(svg(1.6))
    for size, line_width in ((16, 2.3), (24, 2.1), (32, 1.9), (48, 1.75), (64, 1.6), (128, 1.6), (256, 1.6)):
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg(line_width).encode())).render(p, QRectF(0, 0, size, size))
        p.end()
        img.save(os.path.join(OUT, f"kosmicpdf-{size}.png"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
