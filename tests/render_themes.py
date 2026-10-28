"""Render Kosmic PDF with a light and a dark palette, switching live. Run:
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/render_themes.py OUTDIR
"""
import os
import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kosmicpdf import window  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
app = QApplication(sys.argv)
# Keep test runs out of the real settings (recent files, last folder, Bates numbers).
from PySide6.QtCore import QSettings  # noqa: E402
import tempfile  # noqa: E402
QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, tempfile.mkdtemp(prefix="kosmicpdf-test-settings-"))
app.setStyle("Fusion")


def palette(window_c, base, text, accent):
    p = QPalette()
    for role, c in ((QPalette.Window, window_c), (QPalette.Base, base), (QPalette.AlternateBase, base),
                    (QPalette.Button, window_c), (QPalette.WindowText, text), (QPalette.Text, text),
                    (QPalette.ButtonText, text), (QPalette.Highlight, accent), (QPalette.HighlightedText, "#ffffff"),
                    (QPalette.ToolTipBase, base), (QPalette.ToolTipText, text)):
        p.setColor(role, QColor(c))
    return p


LIGHT = palette("#ececed", "#ececed", "#303030", "#895bd4")     # Mint-Y-Purple-Custom, as Qt reads it
DARK = palette("#2e2e33", "#2e2e33", "#dededf", "#895bd4")      # Mint-Y-Dark-Purple


def pump(n=300):
    for _ in range(n):
        app.processEvents()


app.setPalette(LIGHT)
w = window.MainWindow()
w.resize(1200, 820)
w.show()
w.open_files([os.path.join(SAMPLES, "sample.pdf"), os.path.join(SAMPLES, "second.pdf")])
w.tabs.setCurrentIndex(0)
w.tab.thumbs.select_pages([1])
pump()
w.grab().save(os.path.join(OUT, "light.png"))
light = w.colors.key()
app.setPalette(DARK)       # what Qt does when the desktop theme changes
pump()
w.grab().save(os.path.join(OUT, "dark.png"))
print("light", light, "\ndark ", w.colors.key())
print("switched live:", light != w.colors.key())
for t in w.doc_tabs():
    t.pdoc.modified = False
w.close()
