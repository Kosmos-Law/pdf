"""Generate the Kosmic PDF app icon (SVG plus PNGs) into kosmicpdf/icons/app/.

A document page (Lucide's file shape, with its cut corner but no fold) in a deep
version of the kosmos.law frost-to-amber gradient, carrying the Kosmos K-and-sparkle
mark above "PDF" in night. A faint dark edge and drop shadow hold it on light and dark
panels. At 16 and 24 px, where lettering can't be read, the mark appears alone.

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
NIGHT, FROST, AMBER = "#2e3440", "#4f93a8", "#d69d3a"

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

# "PDF" in Schibsted Grotesk ExtraBold (the kosmos.law typeface, SIL OFL), as outlines in
# the 24-unit grid: centred on x = 12, baseline y = 19, cap height 3.7. Stored as shapes
# so the icon never depends on the font being installed.
PDF_LETTERS = (
    "M6.855 19.000 L6.855 15.300 L8.718 15.300 C9.164 15.300 9.498 15.394 9.721 15.583 C9.943 "
    "15.771 10.055 16.054 10.055 16.431 C10.055 16.806 9.933 17.088 9.690 17.277 C9.447 17.466 "
    "9.080 17.560 8.589 17.560 L7.782 17.560 L7.782 19.000 L6.855 19.000 Z M7.782 16.849 L8.649 "
    "16.849 C8.806 16.849 8.926 16.813 9.010 16.741 C9.094 16.668 9.135 16.566 9.135 16.433 "
    "C9.135 16.305 9.094 16.202 9.010 16.126 C8.927 16.049 8.801 16.011 8.631 16.011 L7.782 "
    "16.011 L7.782 16.849 Z M10.519 19.000 L10.519 15.300 L12.049 15.300 C12.496 15.300 12.861 "
    "15.372 13.144 15.516 C13.427 15.660 13.636 15.869 13.770 16.144 C13.905 16.418 13.972 16.752 "
    "13.972 17.144 C13.972 17.548 13.902 17.887 13.762 18.163 C13.623 18.438 13.411 18.646 13.126 "
    "18.788 C12.841 18.929 12.479 19.000 12.041 19.000 L10.519 19.000 Z M11.446 18.211 L11.942 "
    "18.211 C12.650 18.211 13.004 17.858 13.004 17.150 C13.004 16.921 12.965 16.728 12.888 16.571 "
    "C12.811 16.414 12.694 16.294 12.539 16.212 C12.384 16.130 12.187 16.089 11.950 16.089 "
    "L11.446 16.089 L11.446 18.211 Z M14.478 19.000 L14.478 15.300 L17.145 15.300 L17.145 16.089 "
    "L15.405 16.089 L15.405 16.746 L16.909 16.746 L16.909 17.535 L15.405 17.535 L15.405 19.000 "
    "L14.478 19.000 Z"
)


def mark(width, top=None):
    """The Kosmos mark, `width` units wide, centred horizontally; vertically centred if no top."""
    s = width / (MARK_RIGHT - MARK_LEFT)
    height = (MARK_BOTTOM - MARK_TOP) * s
    y = top if top is not None else 12 - height / 2
    return (f'<g transform="translate({12 - width / 2 - MARK_LEFT * s:.3f} {y - MARK_TOP * s:.3f}) '
            f'scale({s:.5f})" fill="{NIGHT}"><path d="{KAPPA}"/><path d="{SPARKLE}"/></g>')


def svg(small=False):
    scale = 10.6
    tx, ty = 128 - 12 * scale, 128 - 12 * scale
    content = mark(13.5) if small else mark(11.0, top=4.6) + f'<path d="{"".join(PDF_LETTERS)}" fill="{NIGHT}"/>'
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
    {content}
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
        QSvgRenderer(QByteArray(svg(small=size <= 24).encode())).render(p, QRectF(0, 0, size, size))
        p.end()
        img.save(os.path.join(OUT, f"kosmicpdf-{size}.png"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
