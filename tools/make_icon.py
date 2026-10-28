"""Generate the Kosmic PDF app icon (SVG plus PNGs) into kosmicpdf/icons/app/.

A document page (Lucide's file shape with a translucent dog-ear) in a deepened
version of the kosmos.law frost-to-amber gradient, carrying the Kosmos sparkle above
"PDF" in night. A faint dark edge and drop shadow hold it on light and dark panels.

Run: .venv/bin/python tools/make_icon.py
"""
import os
import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kosmicpdf", "icons", "app")
# Kosmos palette (kosmos.law): night for ink, snow for the dog-ear; frost and amber
# deepened so the page holds its own on light panels.
NIGHT, SNOW, FROST, AMBER = "#2e3440", "#eceff4", "#6aaabd", "#e2b461"

# Lucide file page in its 24-unit grid. It is stroked 2 units wide, so its outer edge
# lies 1 unit outside this path.
PAGE = ("M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588"
        "A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z")
# Dog-ear: its outer side follows the stroked page's real outline (both rounded
# corners and the cut, i.e. Lucide's arcs grown from 2.4 to 3.4), and its legs sit on
# Lucide's own crease lines (x = 14, y = 8), so it fills the corner exactly.
DOG_EAR = "M14 1A3.4 3.4 0 0 1 16.411 2.003L19.996 5.587A3.4 3.4 0 0 1 21 8H15a1 1 0 0 1-1-1z"

# "PDF" in Schibsted Grotesk ExtraBold (the kosmos.law typeface, SIL OFL), as outlines in
# the 24-unit grid: centred on x = 12, baseline y = 18.2, cap height 3.6. Stored as shapes
# so the icon never depends on the font being installed.
PDF_LETTERS = (
    "M6.994 18.200 L6.994 14.600 L8.806 14.600 C9.241 14.600 9.566 14.692 9.782 14.875 C9.999 "
    "15.059 10.107 15.334 10.107 15.701 C10.107 16.065 9.989 16.339 9.752 16.523 C9.516 16.707 "
    "9.159 16.799 8.681 16.799 L7.896 16.799 L7.896 18.200 L6.994 18.200 Z M7.896 16.107 L8.740 "
    "16.107 C8.893 16.107 9.009 16.072 9.091 16.002 C9.172 15.931 9.213 15.831 9.213 15.702 "
    "C9.213 15.578 9.172 15.478 9.091 15.404 C9.010 15.329 8.887 15.292 8.722 15.292 L7.896 "
    "15.292 L7.896 16.107 Z M10.559 18.200 L10.559 14.600 L12.047 14.600 C12.482 14.600 12.838 "
    "14.670 13.113 14.810 C13.389 14.950 13.592 15.154 13.722 15.421 C13.853 15.688 13.918 16.013 "
    "13.918 16.394 C13.918 16.787 13.851 17.117 13.715 17.385 C13.579 17.653 13.373 17.856 13.095 "
    "17.994 C12.818 18.131 12.466 18.200 12.040 18.200 L10.559 18.200 Z M11.461 17.433 L11.944 "
    "17.433 C12.633 17.433 12.977 17.089 12.977 16.400 C12.977 16.178 12.939 15.990 12.864 15.837 "
    "C12.789 15.684 12.676 15.567 12.524 15.487 C12.373 15.407 12.182 15.367 11.951 15.367 "
    "L11.461 15.367 L11.461 17.433 Z M14.411 18.200 L14.411 14.600 L17.006 14.600 L17.006 15.367 "
    "L15.313 15.367 L15.313 16.007 L16.777 16.007 L16.777 16.774 L15.313 16.774 L15.313 18.200 "
    "L14.411 18.200 Z"
)


def sparkle(cx, cy, r):
    """The Kosmos sparkle: four points joined by inward curves, as in the kosmos.law favicon."""
    k = 0.16 * r
    return (f"M{cx} {cy - r}Q{cx + k} {cy - k} {cx + r} {cy}Q{cx + k} {cy + k} {cx} {cy + r}"
            f"Q{cx - k} {cy + k} {cx - r} {cy}Q{cx - k} {cy - k} {cx} {cy - r}Z")


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
    <path d="{DOG_EAR}" fill="{SNOW}" fill-opacity="0.6"/>
    <path d="{sparkle(12, 10.9, 3.0)}" fill="{NIGHT}"/>
    <path d="{"".join(PDF_LETTERS)}" fill="{NIGHT}"/>
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
