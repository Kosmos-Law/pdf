"""Generate tests/samples/scanned-letter.pdf: a three-page "scan" with no text layer,
for trying out OCR and the OCR button's highlight.

Each page is typeset, rendered to a greyscale picture, and given the marks of a cheap
office scanner (a slight tilt, off-white paper, a shadow along the edge, specks of
dust), then saved as a JPEG inside a PDF page. The result has no text at all until
it is OCRed. The letter and everyone in it are made up.

Run: .venv/bin/python tools/make_scan_sample.py [OUTPUT.pdf]
"""
import os
import random
import sys

import pymupdf as fitz
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "samples",
                   "scanned-letter.pdf")
DPI = 200
CSS = """
* { font-family: serif; font-size: 11.5pt; line-height: 1.35; }
p { margin: 0 0 9pt 0; }
.head { text-align: center; margin-bottom: 20pt; }
.firm { font-size: 17pt; font-weight: bold; letter-spacing: 1pt; }
.small { font-size: 9.5pt; }
h2 { font-size: 12.5pt; text-align: center; margin: 0 0 12pt 0; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 0.8pt solid black; padding: 3pt 6pt; font-size: 10.5pt; }
th { text-align: left; }
.num { text-align: right; }
"""
LETTERHEAD = """<div class="head"><div class="firm">BRIGHTWATER PROPERTY MANAGEMENT</div>
<div class="small">410 Harbor Lane, Suite 200 &middot; Savannah, Georgia 31401 &middot; (912) 555-0148</div></div>"""

PAGES = [
    (0.45, LETTERHEAD + """
<p>March 3, 2026</p>
<p>Ms. Dana Whitfield<br>1187 Laurel Street, Apt. 4B<br>Savannah, Georgia 31405</p>
<p><b>Re: Renewal of your lease at 1187 Laurel Street, Apt. 4B</b></p>
<p>Dear Ms. Whitfield,</p>
<p>Thank you for being such a considerate resident over the past two years. Your current lease
ends on April 30, 2026, and we would be glad to have you stay. This letter sets out the terms we
can offer for a renewal, so that you have time to consider them before the end of the month.</p>
<p>We propose a twelve-month term beginning May 1, 2026, at a monthly rent of $1,385.00, an
increase of $45.00 over your present rent. The increase reflects the rise in property insurance
and water charges for the building this year. All other terms of your lease would remain the same,
including your parking space (No. 14) and the pet addendum for your cat.</p>
<p>If you would prefer a shorter term, we can also offer a six-month renewal at $1,425.00 per month.
Please let us know which option suits you, or whether you would like to discuss either of them.</p>
"""),
    (-1.1, """
<p>Ms. Dana Whitfield<br>March 3, 2026<br>Page 2</p>
<p>To accept, please sign and return the enclosed renewal form by <b>March 31, 2026</b>. You may
drop it in the office mailbox, mail it to the address above, or send a signed copy by email to
leasing@brightwater.example. If we have not heard from you by then, we will be in touch to confirm
your plans, since we would not want the date to pass unnoticed.</p>
<p>A summary of your account for the current lease year is attached for your records. It shows
every payment received on time, for which we are grateful. Your security deposit of $1,200.00
remains on file and will carry over to the renewed lease.</p>
<p>Maintenance requests can still be made through the resident portal or by calling the office.
The repainting of the stairwells is scheduled for the week of April 13, and we will post a notice
on each floor beforehand.</p>
<p>With thanks and kind regards,</p>
<p style="margin-top:34pt">______________________________<br>Marcus Ellery<br>Leasing Manager</p>
<p class="small">Enclosures: Renewal form; Account summary</p>
"""),
    (0.7, """
<h2>ACCOUNT SUMMARY &mdash; LEASE YEAR MAY 2025 TO APRIL 2026</h2>
<p>Resident: Dana Whitfield &nbsp;&nbsp; Unit: 1187 Laurel Street, Apt. 4B &nbsp;&nbsp; Account No. BW-30417</p>
<table>
<tr><th>Date</th><th>Description</th><th class="num">Charge</th><th class="num">Payment</th></tr>
<tr><td>05/01/2025</td><td>Rent, May 2025</td><td class="num">1,340.00</td><td class="num">&nbsp;</td></tr>
<tr><td>05/01/2025</td><td>Payment received, thank you</td><td class="num">&nbsp;</td><td class="num">1,340.00</td></tr>
<tr><td>06/01/2025</td><td>Rent, June 2025</td><td class="num">1,340.00</td><td class="num">&nbsp;</td></tr>
<tr><td>06/02/2025</td><td>Payment received, thank you</td><td class="num">&nbsp;</td><td class="num">1,340.00</td></tr>
<tr><td>07/01/2025</td><td>Rent, July 2025</td><td class="num">1,340.00</td><td class="num">&nbsp;</td></tr>
<tr><td>07/01/2025</td><td>Payment received, thank you</td><td class="num">&nbsp;</td><td class="num">1,340.00</td></tr>
<tr><td>08/01/2025</td><td>Rent, August 2025</td><td class="num">1,340.00</td><td class="num">&nbsp;</td></tr>
<tr><td>08/01/2025</td><td>Pet rent, August 2025</td><td class="num">25.00</td><td class="num">&nbsp;</td></tr>
<tr><td>08/04/2025</td><td>Payment received, thank you</td><td class="num">&nbsp;</td><td class="num">1,365.00</td></tr>
<tr><td>09/01/2025</td><td>Rent and pet rent, September 2025</td><td class="num">1,365.00</td><td class="num">&nbsp;</td></tr>
<tr><td>09/01/2025</td><td>Payment received, thank you</td><td class="num">&nbsp;</td><td class="num">1,365.00</td></tr>
<tr><td>10/01/2025</td><td>Rent and pet rent, October 2025</td><td class="num">1,365.00</td><td class="num">&nbsp;</td></tr>
<tr><td>10/02/2025</td><td>Payment received, thank you</td><td class="num">&nbsp;</td><td class="num">1,365.00</td></tr>
</table>
<p style="margin-top:14pt">Balance due as of March 3, 2026: <b>$0.00</b></p>
<p class="small">Questions about this summary? Please call the office at (912) 555-0148, Monday to Friday,
9 a.m. to 5 p.m.</p>
"""),
]


def typeset(html):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_htmlbox(fitz.Rect(72, 66, 540, 740), html, css=CSS)
    return page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY), doc


def scanned(pix, tilt, rng):
    """The rendered page as a scanner would see it."""
    page = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_Grayscale8).copy()
    w, h = page.width(), page.height()
    out = QImage(w, h, QImage.Format_RGB32)
    out.fill(QColor(236, 234, 228))                      # off-white paper
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.translate(w / 2, h / 2)
    p.rotate(tilt)
    p.translate(-w / 2, -h / 2)
    p.setCompositionMode(QPainter.CompositionMode_Multiply)   # ink darkens the paper; white leaves it
    p.drawImage(0, 0, page)
    p.resetTransform()
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    edge = QLinearGradient(QPointF(0, 0), QPointF(w * 0.035, 0))   # shadow where the lid didn't quite close
    edge.setColorAt(0, QColor(0, 0, 0, 90))
    edge.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(0, 0, w * 0.035, h), edge)
    p.setPen(Qt.NoPen)
    for _ in range(450):                                  # dust and toner specks
        p.setBrush(QColor(0, 0, 0, rng.randint(60, 200)))
        r = rng.choice((1.0, 1.0, 1.5, 2.0, 3.0))
        p.drawEllipse(QPointF(rng.uniform(0, w), rng.uniform(0, h)), r, r)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    out.convertToFormat(QImage.Format_Grayscale8).save(buf, "JPEG", 60)
    return bytes(buf.data())


def main():
    QGuiApplication(sys.argv[:1])
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    rng = random.Random(7)                              # the same "scan" every time
    pdf = fitz.open()
    for tilt, html in PAGES:
        pix, _ = typeset(html)
        page = pdf.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=scanned(pix, tilt, rng))
    pdf.set_metadata({"title": "Scanned letter (sample)", "producer": "Kosmic PDF sample generator"})
    pdf.save(out, garbage=3, deflate=True)
    print("wrote", out, f"({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
