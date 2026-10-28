"""Generate the PDF Desk app icon (SVG plus PNGs) into pdfdesk/icons/app/.

Lucide's "file-text" page, filled in the reds of the Papirus PDF icon (dark red
page, lighter folded corner) with white text lines and Papirus's faint drop
shadow, so it sits naturally beside other desktop icons in light and dark themes.
Small sizes get heavier lines so they don't fade away.

Run: .venv/bin/python tools/make_icon.py
"""
import os
import sys

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pdfdesk", "icons", "app")
PAGE_RED, FOLD_RED, INK = "#c03630", "#f36961", "#ffffff"   # Papirus application-pdf colours

# Lucide file-text, in its 24-unit grid.
PAGE = ("M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588"
        "A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z")
FOLD = "M14 2v5a1 1 0 0 0 1 1h5z"
LINES = ("M10 9H8", "M16 13H8", "M16 17H8")


def svg(line_width):
    scale = 10.6
    tx, ty = 128 - 12 * scale, 128 - 12 * scale
    lines = "".join(f'<path d="{d}"/>' for d in LINES)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <g transform="translate({tx:.1f} {ty:.1f}) scale({scale})" stroke-linecap="round" stroke-linejoin="round">
    <path d="{PAGE}" transform="translate(0 0.45)" fill="#000" fill-opacity="0.2" stroke="#000" stroke-opacity="0.2" stroke-width="2"/>
    <path d="{PAGE}" fill="{PAGE_RED}" stroke="{PAGE_RED}" stroke-width="2"/>
    <path d="{FOLD}" fill="{FOLD_RED}" stroke="{FOLD_RED}" stroke-width="1"/>
    <g fill="none" stroke="{INK}" stroke-width="{line_width}">{lines}</g>
  </g>
</svg>
"""


def main():
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "pdfdesk.svg"), "w") as f:
        f.write(svg(1.6))
    for size, line_width in ((16, 2.2), (24, 2.0), (32, 1.9), (48, 1.75), (64, 1.6), (128, 1.6), (256, 1.6)):
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg(line_width).encode())).render(p, QRectF(0, 0, size, size))
        p.end()
        img.save(os.path.join(OUT, f"pdfdesk-{size}.png"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
