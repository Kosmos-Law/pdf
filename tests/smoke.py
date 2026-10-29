"""Headless end-to-end check of Kosmic PDF. Run:
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/smoke.py OUTDIR
"""
import os
import shutil
import sys

import pymupdf as fitz
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QToolButton

if not os.environ.get("KOSMICPDF_TEST_INSTALLED"):   # set when testing an installed build (e.g. the Flatpak)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kosmicpdf import dialogs, window  # noqa: E402
from kosmicpdf.core import PdfDocument, pages_mime  # noqa: E402

OUT = sys.argv[1]
SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)
# Keep test runs out of the real settings (recent files, last folder, Bates numbers).
from PySide6.QtCore import QSettings  # noqa: E402
import tempfile  # noqa: E402
QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, tempfile.mkdtemp(prefix="kosmicpdf-test-settings-"))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)   # auto-confirm
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def mouse(w, kind, pos, buttons=Qt.LeftButton):
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease,
         "double": QEvent.MouseButtonDblClick}[kind]
    btn = Qt.NoButton if kind == "move" else Qt.LeftButton
    held = Qt.NoButton if kind == "release" else buttons
    ev = QMouseEvent(t, QPointF(pos), QPointF(w.mapToGlobal(pos)), btn, held, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def pump(n=20):
    for _ in range(n):
        app.processEvents()


def click_menu_item(button, label):
    """Click the button for real, wait for its menu, then choose `label` (None = dismiss)."""
    QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
    QTest.qWait(60)
    popup = QApplication.activePopupWidget()
    assert popup is not None and popup is button.menu(), "menu did not open"
    if label is not None:
        [a for a in popup.actions() if a.text() == label][0].trigger()
    popup.close()
    pump()


def text_pos(view, i, word):
    """Canvas position of the first occurrence of `word` on page i."""
    r = view.pdoc.doc[i].search_for(word)[0]
    return view.to_canvas(i, r)


work = os.path.join(OUT, "work")
shutil.rmtree(work, ignore_errors=True)
shutil.copytree(SAMPLES, work)
w = window.MainWindow()
w.resize(1200, 900)
w.show()
w.open_files([os.path.join(work, "sample.pdf"), os.path.join(work, "second.pdf")])
pump()
check("two tabs open", w.tabs.count() == 2)
w.tabs.setCurrentIndex(0)
t = w.tab
pump(200)
w.grab().save(os.path.join(OUT, "01-open.png"))

# --- rotation of multiple pages ---------------------------------------------------
t.thumbs.select_pages([0, 1])
w.actions_by_name["rotate_right"].trigger()
check("rotate two pages", [t.pdoc.doc[i].rotation for i in (0, 1)] == [90, 90])
w.actions_by_name["undo"].trigger()
check("undo rotation", [t.pdoc.doc[i].rotation for i in (0, 1)] == [0, 0])

# --- reorder: move pages 1 and 2 (indices 0,1) to the end ---------------------------
first_texts = [t.pdoc.doc[i].get_text()[:20] for i in range(6)]
new = t.pdoc.move_pages([0, 1], 6)
check("move pages to end", [t.pdoc.doc[i].get_text()[:20] for i in range(6)] == first_texts[2:] + first_texts[:2], str(new))
t.pdoc.undo()

# --- reorder via a real drop on the thumbnail pane ------------------------------------
from PySide6.QtGui import QDropEvent  # noqa: E402
mime = pages_mime(t.pdoc, [4])
pos = t.thumbs.visualRect(t.thumbs.model().index(0, 0)).center() - QPoint(0, 40)
ev = QDropEvent(QPointF(pos), Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
t.thumbs.dropEvent(ev)
check("drop reorders page 5 to front", t.pdoc.doc[0].get_text().startswith("Page 5"), t.pdoc.doc[0].get_text()[:12])
check("reorder keeps page count", t.pdoc.page_count == 6)
t.pdoc.undo()

# --- cut / copy / paste pages -----------------------------------------------------------
t.thumbs.select_pages([1])
t.cut_pages()
check("cut page", t.pdoc.page_count == 5)
t.thumbs.select_pages([3])
t.paste_pages()
check("paste after selection", t.pdoc.page_count == 6 and t.pdoc.doc[4].get_text().startswith("Page 2"),
      t.pdoc.doc[4].get_text()[:12])
t.pdoc.undo(); t.pdoc.undo()

# --- keyboard copy/paste/delete in the thumbnail pane --------------------------------------
from PySide6.QtGui import QKeyEvent as _KE  # noqa: E402
t.thumbs.setFocus()
t.thumbs.select_pages([0])
QApplication.sendEvent(t.thumbs, _KE(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier))
QApplication.sendEvent(t.thumbs, _KE(QEvent.KeyPress, Qt.Key_V, Qt.ControlModifier))
check("Ctrl+C / Ctrl+V pages in thumbnails", t.pdoc.page_count == 7 and t.pdoc.doc[1].get_text().startswith("Page 1"))
t.thumbs.select_pages([1])
QApplication.sendEvent(t.thumbs, _KE(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
check("Delete key removes page", t.pdoc.page_count == 6)

badge = t.thumbs._badge(t.thumbs.item(0).icon().pixmap(60, 78), 3)
check("multi-page drag badge", not badge.isNull())

# --- drag pages from one file to another (copy) -------------------------------------------
t2 = w.tabs.widget(1)
mime = pages_mime(t.pdoc, [0, 5])
ev = QDropEvent(QPointF(t2.thumbs.visualRect(t2.thumbs.model().index(0, 0)).center() + QPoint(0, 60)),
                Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
t2.thumbs.dropEvent(ev)
check("drag pages into other file", t2.pdoc.page_count == 5 and t.pdoc.page_count == 6,
      f"{t2.pdoc.page_count} {[t2.pdoc.doc[i].get_text()[:8] for i in range(5)]}")
check("dropped pages in place", t2.pdoc.doc[1].get_text().startswith("Page 1") and t2.pdoc.doc[2].get_text().startswith("Page 6"))

# --- extract to new PDF ---------------------------------------------------------------------
t.thumbs.select_pages([2, 3])
w.actions_by_name["extract"].trigger()
check("copy pages to new PDF", w.tabs.count() == 3 and w.tab.pdoc.page_count == 2)
w.tabs.setCurrentWidget(t)

# --- text selection and copy -------------------------------------------------------------------
v = t.view
v.set_zoom(1.0)
pump()
v.go_to_page(0)
pump()
r = text_pos(v, 0, "quick")
a, b = r.topLeft().toPoint() + QPoint(1, 4), text_pos(v, 0, "lazy").bottomRight().toPoint() - QPoint(1, 4)
mouse(v.canvas, "press", a); mouse(v.canvas, "move", b); mouse(v.canvas, "release", b)
sel = v.selected_text()
check("text selection", sel.startswith("quick") and sel.rstrip().endswith("lazy"), repr(sel))
w.copy()
check("copy text to clipboard", QGuiApplication.clipboard().text() == sel)

# --- highlight ------------------------------------------------------------------------------------
w.set_mode("highlight")
r = text_pos(v, 0, "Confidential")
mouse(v.canvas, "press", r.topLeft().toPoint() + QPoint(1, 4))
mouse(v.canvas, "move", r.bottomRight().toPoint() - QPoint(1, 4))
mouse(v.canvas, "release", r.bottomRight().toPoint() - QPoint(1, 4))
p0 = t.pdoc.doc[0]
hl = [a for a in p0.annots() if a.type[0] == fitz.PDF_ANNOT_HIGHLIGHT]
check("highlight annotation", len(hl) == 1 and "Confidential" in p0.get_textbox(hl[0].rect))

# --- typewriter on a normal and a rotated page ---------------------------------------------------
w.set_mode("typewriter")
for pg in (0, 2):
    v.go_to_page(pg); pump()
    rr = v.page_rects[pg]
    p = rr.topLeft() + QPoint(100, 60)
    mouse(v.canvas, "press", p); pump()
    ed = v.canvas.findChildren(window.QWidget)
    from kosmicpdf.pageview import TypewriterEditor  # noqa: E402
    ed = [e for e in v.canvas.findChildren(TypewriterEditor) if e.isVisible()][0]
    ed.setPlainText("Typed note\nsecond line")
    ed.commit(); pump()
    pp = t.pdoc.doc[pg]
    ft = [a for a in pp.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]
    vis = ft[0].rect * pp.rotation_matrix if ft else None
    check(f"typewriter page {pg + 1} (rotation {t.pdoc.doc[pg].rotation})",
          ft and abs(vis.x0 - 100 / v.zoom) < 2 and abs(vis.y0 - 60 / v.zoom) < 2, str(vis))
w.set_mode("select")
pump()
w.grab().save(os.path.join(OUT, "02-annotated.png"))

# --- move and delete an annotation ------------------------------------------------------------------
v.go_to_page(0); pump()
p0 = t.pdoc.doc[0]
ft = [a for a in p0.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT][0]
old_rect = fitz.Rect(ft.rect)
c = v.to_canvas(0, old_rect).center().toPoint()
mouse(v.canvas, "press", c); mouse(v.canvas, "move", c + QPoint(50, 30)); mouse(v.canvas, "release", c + QPoint(50, 30))
p0 = t.pdoc.doc[0]
ft2 = [a for a in p0.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT][0]
check("move annotation", abs(ft2.rect.x0 - old_rect.x0 - 50) < 2, f"{old_rect} -> {ft2.rect}")
from PySide6.QtGui import QKeyEvent  # noqa: E402
QApplication.sendEvent(v.canvas, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
check("delete annotation", not [a for a in t.pdoc.doc[0].annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT])

# --- redaction --------------------------------------------------------------------------------------
on_toolbar = {b.defaultAction() for b in w.toolbar.findChildren(QToolButton)}
check("redaction tools are off the main toolbar",
      not on_toolbar & {w.actions_by_name[n] for n in ("mode_redact", "apply_redactions", "redact_search")})
check("redaction bar hidden until redacting", w.redact_bar.isHidden())
tb_actions = w.toolbar.actions()
check("OCR sits just right of Save", tb_actions[tb_actions.index(w.actions_by_name["save"]) + 1] is w.actions_by_name["ocr"])
v.canvas.setFocus(); pump()
QTest.keyClick(w, Qt.Key_R)
pump()
check("R starts redacting and shows the redaction bar", w.mode == "redact" and w.redact_bar.isVisible()
      and w.redact_count.text().startswith("Nothing marked"), w.mode)
check("redacting starts by selecting text", w.redact_by == "text" and v.redact_by == "text"
      and w.actions_by_name["redact_text"].isChecked())
r = text_pos(v, 0, "12345")
mouse(v.canvas, "press", r.topLeft().toPoint() + QPoint(1, 4))
mouse(v.canvas, "move", r.bottomRight().toPoint() - QPoint(1, 4))
mouse(v.canvas, "release", r.bottomRight().toPoint() - QPoint(1, 4))
check("redaction marked", t.pdoc.redaction_count() == 1)
check("redaction bar counts the marks", w.redact_count.text().startswith("1 area marked"), w.redact_count.text())
mark = next(t.pdoc.doc[0].annots(types=[fitz.PDF_ANNOT_REDACT]))
from kosmicpdf.core import REDACT_MARK  # noqa: E402
check("a mark is drawn lightly: a faint mauve outline, no cross", mark.colors["stroke"]
      and all(abs(a - b) < 0.01 for a, b in zip(mark.colors["stroke"], REDACT_MARK)) and mark.opacity < 0.5,
      f"{mark.colors} {mark.opacity}")
tools_menu = next(m for m in w.menuBar().findChildren(QMenu) if m.title() == "&Tools")
check("the Tools menu keeps only Redact for redaction",
      w.actions_by_name["mode_redact"] in tools_menu.actions()
      and not {w.actions_by_name[n] for n in ("redact_search", "apply_redactions")} & set(tools_menu.actions())
      and w.actions_by_name["redact_search"] in w.redact_bar.actions()
      and w.actions_by_name["redact_search"].text() == "Search…")
# Part of one line and on into the next, in one drag.
words = t.pdoc.doc[0].get_text("words")
end_of_line = next(k for k in range(len(words) - 1) if words[k][4] == "fox" and words[k + 1][4] == "jumps"
                   and words[k][5:7] != words[k + 1][5:7])
fox, jumps = fitz.Rect(words[end_of_line][:4]), fitz.Rect(words[end_of_line + 1][:4])
a, b = v.to_canvas(0, fox), v.to_canvas(0, jumps)
mouse(v.canvas, "press", a.topLeft().toPoint() + QPoint(1, 4))
mouse(v.canvas, "move", b.bottomRight().toPoint() - QPoint(1, 4))
mouse(v.canvas, "release", b.bottomRight().toPoint() - QPoint(1, 4))
marks = [m.rect for m in t.pdoc.doc[0].annots(types=[fitz.PDF_ANNOT_REDACT])]
check("selecting text across a line break marks just those words, one mark per line",
      len(marks) == 3 and t.pdoc.doc[0].get_textbox(marks[-1]).strip() == "jumps"
      and t.pdoc.doc[0].get_textbox(marks[-2]).strip() == "fox", str([t.pdoc.doc[0].get_textbox(m) for m in marks]))
w.actions_by_name["redact_area"].trigger(); pump()
check("Area switches to drawing a box", w.redact_by == "area" and v.redact_by == "area")
head = text_pos(v, 0, "sample")
mouse(v.canvas, "press", head.topLeft().toPoint() - QPoint(4, 4))
mouse(v.canvas, "move", head.bottomRight().toPoint() + QPoint(4, 4))
mouse(v.canvas, "release", head.bottomRight().toPoint() + QPoint(4, 4))
check("a box drawn in Area mode is marked", t.pdoc.redaction_count() == 4)
pg0 = t.pdoc.doc[0]          # annotations stay valid only while their page does
box = v.to_canvas(0, list(pg0.annots(types=[fitz.PDF_ANNOT_REDACT]))[-1].rect)
from kosmicpdf.pageview import ShoulderButton  # noqa: E402
mouse(v.canvas, "move", box.center().toPoint(), Qt.NoButton); pump()
mb = v.mark_button
check("hovering over a mark shows its shoulder button, the same as a note's",
      isinstance(mb, ShoulderButton) and mb.isVisible() and mb.popupMode() == QToolButton.InstantPopup
      and mb.geometry().topLeft() == QPoint(round(box.right()) + 3, round(box.top())), str(mb and mb.geometry()))
mouse(v.canvas, "move", (box.topRight() + QPointF(2, 5)).toPoint(), Qt.NoButton); pump()
check("it stays while the mouse crosses to it", mb.isVisible())
click_menu_item(mb, None)
check("clicking the button only opens its menu", t.pdoc.redaction_count() == 4)
click_menu_item(mb, "Remove mark")
check("Remove mark in its menu removes just that mark", t.pdoc.redaction_count() == 3 and mb.isHidden())
t.pdoc.undo(); pump()
check("undo brings the mark back", t.pdoc.redaction_count() == 4)
w.redact_bar.grab().save(os.path.join(OUT, "02b-redact-bar.png"))
w.set_redact_style("white")
check("the redaction style is remembered", dialogs.settings().value("redact/style") == "white"
      and w.redact_style_button.text() == "White Boxes")
asked = []
QFileDialog.getSaveFileName = staticmethod(lambda parent, title, start, *a: (asked.append(start) or start, ""))
original_text, n_tabs = t.pdoc.doc[0].get_text(), w.tabs.count()
w.apply_redactions(); pump()
ct = w.tab
want_path = os.path.join(work, "sample - Redacted.pdf")
check("Save Redacted Copy saves a new copy beside the original, named for it",
      ct is not t and w.tabs.count() == n_tabs + 1 and asked == [want_path] and ct.pdoc.path == want_path
      and os.path.exists(want_path), f"{asked} {ct.pdoc.path}")
saved = fitz.open(want_path)
check("the copy has the marked content removed, and no marks left",
      saved[0].get_text().count("12345") == original_text.count("12345") - 1
      and not any(True for p in saved for _ in p.annots(types=[fitz.PDF_ANNOT_REDACT])))
boxes = [d for d in saved[0].get_drawings() if d.get("fill") == (1.0, 1.0, 1.0) and d.get("color") == (0.0, 0.0, 0.0)]
check("white style: each redacted area is a white box with a black border", len(boxes) == 4, str(len(boxes)))
grey = t.pdoc.redacted_copy("grey")
grey_boxes = [d for d in grey.doc[0].get_drawings() if d.get("fill") and abs(d["fill"][0] - 0.82) < 0.01
              and d.get("color") is None]
check("grey style: each redacted area is a light grey box", len(grey_boxes) == 4, str(len(grey_boxes)))
saved.close()
w.set_redact_style("black")
check("the original is untouched: the same text, its marks still there",
      t.pdoc.doc[0].get_text() == original_text and t.pdoc.redaction_count() == 4)
check("the copy has no undo history to bring the text back", not ct.pdoc.can_undo())
check("making the copy ends redacting", w.mode == "select" and w.redact_bar.isHidden())
w.close_tab(ct); w.tabs.setCurrentWidget(t); pump()
for _ in range(3):
    t.pdoc.undo()
check("undo takes the marks off the original again", t.pdoc.redaction_count() == 0)
w.set_mode("redact"); w.set_redact_by("text")
w.actions_by_name["redact_done"].trigger()
check("Done hides the redaction bar", w.mode == "select" and w.redact_bar.isHidden())

# --- Bates numbering, including the rotated page ------------------------------------------------------
t.pdoc.checkpoint()
nxt = dialogs.stamp_bates(t.pdoc.doc, 1, "CRAIG", 6, "", "Bottom right", 10, 24, True)
t.pdoc.edited(range(t.pdoc.page_count))
ok = True
for i, page in enumerate(t.pdoc.doc):
    hits = page.search_for(f"CRAIG{i + 1:06d}")
    if not hits:
        ok = False; continue
    vr = hits[0] * page.rotation_matrix
    ok &= vr.x1 > page.rect.width - 60 and vr.y1 > page.rect.height - 40
check("Bates on every page, bottom right (incl. rotated)", ok and nxt == 7)
pump(200)
w.grab().save(os.path.join(OUT, "03-bates.png"))

# --- flatten -------------------------------------------------------------------------------------------
t.pdoc.flatten()
check("flatten removes annotations", sum(len(list(p.annots())) for p in t.pdoc.doc) == 0)

# --- save and reopen ---------------------------------------------------------------------------------------
out_path = os.path.join(work, "saved.pdf")
w.tabs.setCurrentWidget(t); pump()
had_dot = w._badges["save"]
w._write(t, out_path)
check("saving clears the dot on Save", had_dot and not w._badges["save"])
d = fitz.open(out_path)
check("saved file reopens", d.page_count == 6 and "CRAIG000006" in d[5].get_text())
d.close()

# --- combine PDF + image ----------------------------------------------------------------------------------
out = fitz.open()
from kosmicpdf.core import load_any  # noqa: E402
out.insert_pdf(load_any(os.path.join(work, "second.pdf")))
out.insert_pdf(load_any(os.path.join(work, "scan.png"), "Letter"))
check("combine pdf + image", out.page_count == 4 and out[3].rect == fitz.Rect(0, 0, 612, 792))

# --- OCR the image page (synchronously wait for the QProcess) -------------------------------------------------
img_doc = PdfDocument(load_any(os.path.join(work, "scan.png"), "Letter"), title="scan.pdf")
it = w.add_doc(img_doc)
check("image has no text before OCR", not img_doc.doc[0].get_text().strip())
pump(10)
check("OCR button gets a dot for a scan", img_doc.needs_ocr() and w._badges["ocr"]
      and w.ocr_button.toolButtonStyle() == Qt.ToolButtonTextBesideIcon)
job = window.ExternalJob(w, it, ["-l", "eng", "--skip-text", "--output-type", "pdf"], "OCR")
while job.proc.state() != job.proc.ProcessState.NotRunning:
    job.proc.waitForFinished(100); pump(5)
pump(20)
check("OCR adds searchable text", "quick brown fox" in img_doc.doc[0].get_text(), img_doc.doc[0].get_text()[:60])
check("OCR dot goes once the text is there", not img_doc.needs_ocr() and not w._badges["ocr"])
check("Save has a dot while there are unsaved changes", img_doc.modified and w._badges["save"])

# --- PDF/A ----------------------------------------------------------------------------------------------------
job = window.ExternalJob(w, it, ["--skip-text", "--tesseract-timeout", "0", "--output-type", "pdfa-2"], "PDF/A")
while job.proc.state() != job.proc.ProcessState.NotRunning:
    job.proc.waitForFinished(100); pump(5)
pump(20)
meta = img_doc.doc.xref_get_key(-1, "Root")
xmp = img_doc.doc.get_xml_metadata()
check("PDF/A-2 output", "pdfaid:part" in xmp and ("<pdfaid:part>2" in xmp or 'pdfaid:part="2"' in xmp), xmp[xmp.find("pdfaid"):][:60])

# --- tabs: move to new window and back --------------------------------------------------------------------------
n_before = len(window.WINDOWS)
w.move_tab_to_new_window(it)
pump()
w2 = window.WINDOWS[-1]
check("tab to new window", len(window.WINDOWS) == n_before + 1 and it.main_window() is w2)
w2.move_tab_to(it, w)
pump(50)
check("tab back; empty window closes", it.main_window() is w and w2 not in window.WINDOWS)

# --- pages dropped onto another tab in the tab bar ------------------------------------------------------------------
w.tabs.setCurrentWidget(t)
from PySide6.QtGui import QDragMoveEvent  # noqa: E402
tb = w.tabs.tabBar()
target = 1
mime = pages_mime(t.pdoc, [0])
before = w.tabs.widget(target).pdoc.page_count
tb.dropEvent(QDropEvent(QPointF(tb.tabRect(target).center()), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
check("drop pages on a tab appends", w.tabs.widget(target).pdoc.page_count == before + 1)

# --- dragging thumbnails with the real mouse path ------------------------------------------------------------
w.tabs.setCurrentWidget(t)
pump(50)
th = t.thumbs
check("thumbnail viewport accepts drops", th.viewport().acceptDrops() and th.dragEnabled())
from kosmicpdf import thumbs as thumbs_mod  # noqa: E402
started = []


class FakeDrag:
    def __init__(self, src): pass
    def setMimeData(self, m): started.append(m)
    def setPixmap(self, pm): pass
    def exec(self, *a): return Qt.IgnoreAction


real_drag, thumbs_mod.QDrag = thumbs_mod.QDrag, FakeDrag
c = th.visualRect(th.model().index(1, 0)).center()
mouse(th.viewport(), "press", c)
for dy in (5, 15, 30, 60):
    mouse(th.viewport(), "move", c + QPoint(0, dy))
mouse(th.viewport(), "release", c + QPoint(0, 60))
thumbs_mod.QDrag = real_drag
check("mouse drag on a thumbnail starts a page drag", started and started[0].hasFormat("application/x-kosmicpdf-pages"))

# --- drop mark before the first page, and auto-scroll near the edge ----------------------------------------------
from PySide6.QtGui import QDragMoveEvent  # noqa: E402
from PySide6.QtCore import QMimeData  # noqa: E402


def drag_move(pane, pos, mime):
    ev = QDragMoveEvent(QPoint(pos), Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    pane.dragMoveEvent(ev)
    pump(5)


mime = pages_mime(t.pdoc, [2])
th.scrollToTop(); pump()
drag_move(th, th.visualRect(th.model().index(0, 0)).center() - QPoint(0, 30), mime)
img = th.viewport().grab().toImage()
accent = th.colors.accent.name()
top_rows = [y for y in range(0, 6) if any(img.pixelColor(x, y).name() == accent for x in range(10, img.width() - 10))]
check("drop mark shows above the first page", th._drop_at == 0 and top_rows, f"drop_at={th._drop_at} rows={top_rows}")
th.dragLeaveEvent(None)
th.verticalScrollBar().setValue(th.verticalScrollBar().maximum()); pump()
start_val = th.verticalScrollBar().value()
drag_move(th, QPoint(th.viewport().width() // 2, 5), mime)
for _ in range(20):
    th._scroll_timer.isActive() and th._auto_scroll()
check("holding a page near the top scrolls the pane", start_val > 0 and th.verticalScrollBar().value() < start_val,
      f"{start_val} -> {th.verticalScrollBar().value()}")
th.dragLeaveEvent(None)
check("panel border is 1px", t.splitter.handleWidth() == 1)
check("the panel border takes the accent colour while it's held",
      f"QSplitter::handle:pressed {{ background:{w.colors.accent.name()}; }}" in QApplication.instance().styleSheet())

# --- typewriter stays open while the font size changes ---------------------------------------------------------
w.set_mode("typewriter")
v = t.view
v.go_to_page(1); pump()
p0 = v.page_rects[1].topLeft() + QPoint(80, 80)
mouse(v.canvas, "press", p0); pump()
ed = v.editor
ed.setPlainText("Size change")
w.font_size.setFocus(); pump(20)
check("note stays open when font box gets focus", v.editor is ed and ed.isVisible())
w.font_size.setValue(18); pump(20)
check("new size applies to the open note", ed.font_size == 18 and v.editor is ed)
mouse(v.canvas, "press", v.page_rects[1].topLeft() + QPoint(300, 500)); pump(20)
pg1 = t.pdoc.doc[1]
notes = [a for a in pg1.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]
from kosmicpdf.core import parse_da_fontsize  # noqa: E402
check("clicking the page saves the note at the new size",
      len(notes) == 1 and parse_da_fontsize(t.pdoc.doc, notes[0]) == 18, str([a.info.get("content") for a in notes]))
if v.editor:
    v.editor.setPlainText(""); v.editor.commit()
w.font_size.setValue(12)
w.set_mode("select")

# --- editing an existing note: hidden while editing (no ghost), undo restores it --------------------------------
HIDDEN = fitz.PDF_ANNOT_IS_HIDDEN


def note_on(i):
    page = t.pdoc.doc[i]
    notes = [(a.info.get("content"), a.flags, fitz.Rect(a.rect)) for a in page.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]
    return notes[0] if notes else None


w.set_mode("typewriter")
text0, flags0, rect0 = note_on(1)
c = v.to_canvas(1, rect0).center().toPoint()
depth = len(t.pdoc._undo)
mouse(v.canvas, "press", c); pump()
check("clicking a note opens it for editing", v.editor is not None and v.editor.toPlainText() == text0)
check("note is hidden while being edited", note_on(1)[1] & HIDDEN)
v.editor.commit(); pump()
check("closing an unchanged note records no edit", len(t.pdoc._undo) == depth and not note_on(1)[1] & HIDDEN)
mouse(v.canvas, "press", c); pump()
v.editor.setPlainText("Edited note"); v.editor.commit(); pump()
check("edited note is saved and visible", note_on(1)[0] == "Edited note" and not note_on(1)[1] & HIDDEN)
t.pdoc.undo(); pump()
check("undo brings back the original note, visible", note_on(1)[0] == text0 and not note_on(1)[1] & HIDDEN)
w.set_mode("select")

# --- firm highlight colours, eraser, recolour, and selecting highlighted text ---------------------------------
from kosmicpdf.pageview import HIGHLIGHT_COLORS  # noqa: E402


def highlights(i):
    page = t.pdoc.doc[i]
    return [(a.xref, tuple(round(c, 3) for c in a.colors["stroke"])) for a in page.annots(types=[fitz.PDF_ANNOT_HIGHLIGHT])]


def drag(a, b):
    mouse(v.canvas, "press", a); mouse(v.canvas, "move", b); mouse(v.canvas, "release", b); pump()


rnd = lambda rgb: tuple(round(c, 3) for c in rgb)  # noqa: E731
menu_items = [a.text() for a in w.color_button.menu().actions() if a.text()] if w.color_button.menu() else []
check("colour button offers the firm colours and Clear",
      menu_items == ["Yellow", "Green", "Purple", "Beige", "Clear (remove highlights)"], str(menu_items))
check("default highlight colour is the firm yellow", rnd(w.hl_color) == rnd((1.0, 1.0, 166 / 255)))
v.go_to_page(3); pump()
w.set_mode("highlight")
w.set_hl_color(HIGHLIGHT_COLORS["Green"])
r = text_pos(v, 3, "Confidential")
drag(r.topLeft().toPoint() + QPoint(1, 4), r.bottomRight().toPoint() - QPoint(1, 4))
check("highlight in firm green", [c for _, c in highlights(3)] == [rnd(HIGHLIGHT_COLORS["Green"])])

w.set_mode("select")
green, purple = rnd(HIGHLIGHT_COLORS["Green"]), rnd(HIGHLIGHT_COLORS["Purple"])
lazy, jumps = text_pos(v, 3, "lazy"), text_pos(v, 3, "jumps")
drag(lazy.topLeft().toPoint() + QPoint(1, 4), lazy.bottomRight().toPoint() - QPoint(1, 4))
w.actions_by_name["mode_highlight"].trigger(); pump()
check("Highlight button highlights the selected text and stays in Select",
      [c for _, c in highlights(3)] == [green, green] and w.mode == "select"
      and w.actions_by_name["mode_select"].isChecked(), str(highlights(3)))
drag(jumps.topLeft().toPoint() + QPoint(1, 4), jumps.bottomRight().toPoint() - QPoint(1, 4))
w.set_hl_color(HIGHLIGHT_COLORS["Purple"]); pump()
check("choosing a colour highlights the selected text in it", sorted(c for _, c in highlights(3)) == sorted([green, green, purple])
      and w.mode == "select")
drag(jumps.topLeft().toPoint() + QPoint(1, 4), lazy.bottomRight().toPoint() - QPoint(1, 4))
w.set_hl_color(None); pump()
check("Clear removes the highlights under the selected text", [c for _, c in highlights(3)] == [green])
w.set_hl_color(HIGHLIGHT_COLORS["Green"])
check("the button shows the colour under the highlighter, with an arrow for the colours",
      w.color_button.defaultAction() is w.actions_by_name["mode_highlight"]
      and w.color_button.popupMode() == QToolButton.MenuButtonPopup)

w.set_mode("select")
drag(r.topLeft().toPoint() + QPoint(2, 4), text_pos(v, 3, "12345").bottomRight().toPoint() - QPoint(1, 4))
check("dragging over a highlight still selects text", "onfidential account 12345" in v.selected_text() and v.sel_annot is None,
      repr(v.selected_text()))
v.clear_selection()
mouse(v.canvas, "move", r.center().toPoint(), Qt.NoButton); pump()
check("hovering over a highlight keeps the text cursor", v.canvas.cursor().shape() == Qt.IBeamCursor,
      str(v.canvas.cursor().shape()))
mouse(v.canvas, "press", r.center().toPoint()); mouse(v.canvas, "release", r.center().toPoint()); pump()
check("clicking a highlight doesn't select it as an object", v.sel_annot is None)
drag(r.topLeft().toPoint() + QPoint(1, 4), r.bottomRight().toPoint() - QPoint(1, 4))
w.set_hl_color(HIGHLIGHT_COLORS["Purple"]); pump()
check("selecting highlighted text and picking a colour recolours it (no stacking)",
      [c for _, c in highlights(3)] == [rnd(HIGHLIGHT_COLORS["Purple"])], str(highlights(3)))
t.pdoc.undo(); pump()
check("undo brings back the old colour", [c for _, c in highlights(3)] == [green])

w.set_mode("highlight")
w.set_hl_color(None)
drag(r.center().toPoint() - QPoint(10, 0), r.center().toPoint() + QPoint(10, 0))
check("eraser: dragging across removes the highlight", highlights(3) == [])
w.set_hl_color(HIGHLIGHT_COLORS["Beige"])
drag(r.topLeft().toPoint() + QPoint(1, 4), r.bottomRight().toPoint() - QPoint(1, 4))
w.set_hl_color(None)
mouse(v.canvas, "press", r.center().toPoint()); mouse(v.canvas, "release", r.center().toPoint()); pump()
check("eraser: clicking removes the highlight", highlights(3) == [])
w.set_hl_color(HIGHLIGHT_COLORS["Yellow"])
w.set_mode("select")

# --- double-click a word, then drag: extends a whole word at a time --------------------------------------------
w.set_mode("select")
v.go_to_page(4); pump()
brown = text_pos(v, 4, "brown").center().toPoint()
for kind in ("press", "release", "double"):
    mouse(v.canvas, kind, brown)
check("double-click selects a word", v.selected_text() == "brown", repr(v.selected_text()))
jr = text_pos(v, 4, "jumps")
mouse(v.canvas, "move", QPoint(int(jr.left() + jr.width() * 0.5), int(jr.center().y())))
sel = v.selected_text()
check("dragging after a double-click extends by characters", sel.startswith("brown fox ju") and sel != "brown fox jumps", repr(sel))
qr = text_pos(v, 4, "quick")
mouse(v.canvas, "move", QPoint(int(qr.left() + qr.width() * 0.6), int(qr.center().y())))
sel = v.selected_text()
check("dragging back keeps the whole first word, by characters", sel.endswith(" brown") and 6 < len(sel) < len("quick brown"),
      repr(sel))
mouse(v.canvas, "release", QPoint(int(qr.left() + qr.width() * 0.6), int(qr.center().y())))
check("selection stays after release", v.selected_text() == sel)
v.clear_selection()

# --- drag handle on the typewriter box --------------------------------------------------------------------------
w.set_mode("typewriter")
v.go_to_page(5); pump()
start = v.page_rects[5].topLeft() + QPoint(100, 120)
mouse(v.canvas, "press", start); pump()
ed = v.editor
ed.setPlainText("Movable note"); pump()
hd = ed.handle
check("typewriter box has a drag handle on its left", hd.isVisible() and hd.geometry().right() <= ed.geometry().left() + 1)
from PySide6.QtTest import QTest  # noqa: E402
w.activateWindow(); pump()
hc = hd.geometry().center()
# Window-level events (as a real mouse sends), so Qt's click-focus rules apply too.
QTest.mousePress(hd, Qt.LeftButton, Qt.NoModifier, hd.rect().center())
for k in range(1, 5):   # targets are fixed page positions, converted into the (moving) handle's coordinates
    QTest.mouseMove(hd, hd.mapFrom(v.canvas, hc + QPoint(15 * k, 10 * k))); pump(3)
QTest.mouseRelease(hd, Qt.LeftButton, Qt.NoModifier, hd.mapFrom(v.canvas, hc + QPoint(60, 40))); pump()
check("dragging the handle moves the box and keeps it open", v.editor is ed and hd.geometry().center() - hc == QPoint(60, 40),
      str(hd.geometry().center() - hc))
mouse(v.canvas, "press", v.page_rects[5].topLeft() + QPoint(400, 600)); pump()
if v.editor:
    v.editor.commit()
pg5 = t.pdoc.doc[5]
nt = [fitz.Rect(a.rect) for a in pg5.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]
want = fitz.Point(100 + 60, 120 + 40) / v.zoom
check("note is saved where the handle left it", nt and abs(nt[0].x0 - want.x) < 1 and abs(nt[0].y0 - want.y) < 1, f"{nt} want {want}")
del t.pdoc._undo[:-5]       # leave room under the undo cap (20 steps) so one more step can be counted
depth = len(t.pdoc._undo)
mouse(v.canvas, "press", v.to_canvas(5, nt[0]).center().toPoint()); pump()
hd = v.editor.handle
mouse(hd, "press", hd.rect().center()); mouse(hd, "move", hd.rect().center() + QPoint(-30, 50))
mouse(hd, "release", hd.rect().center() + QPoint(-30, 50)); pump()
v.editor.commit(); pump()
pg5 = t.pdoc.doc[5]
nt2 = [fitz.Rect(a.rect) for a in pg5.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]
check("moving an existing note with the handle is one edit", len(t.pdoc._undo) == depth + 1 and len(nt2) == 1
      and abs(nt2[0].x0 - (nt[0].x0 - 30 / v.zoom)) < 1, f"{nt2}")
t.pdoc.undo(); pump()
pg5 = t.pdoc.doc[5]
check("undo puts the note back", [round(a.rect.x0) for a in pg5.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT] == [round(nt[0].x0)])
mouse(v.canvas, "press", v.page_rects[5].topLeft() + QPoint(200, 300)); pump()
ed = v.editor
ed.setPlainText("Nudge me"); pump()
g0 = ed.geometry().topLeft()
QTest.mouseClick(ed.handle, Qt.LeftButton, Qt.NoModifier, ed.handle.rect().center()); pump()
check("clicking the handle keeps the note open and focuses the handle",
      v.editor is ed and QApplication.focusWidget() is ed.handle, type(QApplication.focusWidget()).__name__)
for _ in range(3):
    QTest.keyClick(ed.handle, Qt.Key_Right)
QTest.keyClick(ed.handle, Qt.Key_Down, Qt.ShiftModifier); pump()
check("arrow keys nudge 1px, Shift+arrow 10px", ed.geometry().topLeft() - g0 == QPoint(3, 10), str(ed.geometry().topLeft() - g0))
QTest.keyClick(ed.handle, Qt.Key_Return); pump()
check("Enter returns to typing", QApplication.focusWidget() is ed and v.editor is ed)
QTest.mouseClick(v.canvas, Qt.LeftButton, Qt.NoModifier, v.page_rects[5].topLeft() + QPoint(450, 650)); pump()
if v.editor:
    v.editor.commit(); pump()
pg5 = t.pdoc.doc[5]
nudged = [fitz.Rect(a.rect) for a in pg5.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT and a.info.get("content") == "Nudge me"]
want = fitz.Point(200 + 3, 300 + 10) / v.zoom
check("nudged note is saved at its new spot", nudged and abs(nudged[0].x0 - want.x) < 0.5 and abs(nudged[0].y0 - want.y) < 0.5,
      f"{nudged} want {want}")
# --- corner button: Cut / Delete menu (two clicks, so no accidental deletes) -------------------------------------

def notes_on(i):
    page = t.pdoc.doc[i]
    return [(a.info.get("content"), a.flags) for a in page.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]


mouse(v.canvas, "press", v.page_rects[5].topLeft() + QPoint(150, 420)); pump()
ed = v.editor
ed.setPlainText("Keep me"); pump()
bt = ed.remove_button
check("note box has a corner remove button", bt.isVisible() and bt.geometry().left() >= ed.geometry().right())
check("its menu offers only Delete note", [a.text() for a in bt.menu().actions()] == ["Delete note"])
click_menu_item(bt, None)
check("opening and dismissing the menu keeps the note open", v.editor is ed and ed.isVisible())
before = len(notes_on(5))
click_menu_item(bt, "Delete note")
check("Delete on a new note discards it", v.editor is None and len(notes_on(5)) == before)

existing = [a for a in t.pdoc.doc[5].annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT and a.info.get("content") == "Nudge me"]
pg5 = t.pdoc.doc[5]
er = fitz.Rect([a.rect for a in pg5.annots() if a.info.get("content") == "Nudge me"][0])
mouse(v.canvas, "press", v.to_canvas(5, er).center().toPoint()); pump()
del t.pdoc._undo[:-5]
depth = len(t.pdoc._undo)
click_menu_item(v.editor.remove_button, "Delete note")
check("Delete removes an existing note", "Nudge me" not in [c for c, _ in notes_on(5)] and len(t.pdoc._undo) == depth + 1)
t.pdoc.undo(); pump()
check("undo restores the deleted note, visible",
      [f & fitz.PDF_ANNOT_IS_HIDDEN for c, f in notes_on(5) if c == "Nudge me"] == [0], str(notes_on(5)))
w.set_mode("select")

# --- recent documents ------------------------------------------------------------------------------------------
recent = window.recent_files()
check("opened and saved files are in Recent, newest first",
      recent[:4] == [out_path, os.path.join(work, "sample - Redacted.pdf"), os.path.join(work, "second.pdf"),
                     os.path.join(work, "sample.pdf")], str(recent[:4]))
extra = os.path.join(work, "extra.pdf")
shutil.copy(os.path.join(work, "second.pdf"), extra)
window.remember_recent(extra)
window.remember_recent(os.path.join(work, "gone.pdf"))
w.fill_recent_menu()
acts = [a for a in w.recent_menu.actions() if a.text()]
check("missing files are greyed out as not found", acts[0].text().endswith("not found") and not acts[0].isEnabled())
check("entries show the file name and folder", acts[1].text().startswith("&2  extra.pdf\t") and acts[1].isEnabled(), acts[1].text())
n_tabs = w.tabs.count()
acts[1].trigger(); pump()
check("choosing a recent file opens it", w.tabs.count() == n_tabs + 1 and w.tab.pdoc.path == extra)
w.close_tab(w.tab)
[a for a in w.recent_menu.actions() if a.text().startswith("Clear")][0].trigger()
w.fill_recent_menu()
check("Clear empties the list", window.recent_files() == [] and not w.recent_menu.actions()[0].isEnabled())

# --- dark-mode fallback (for Flatpak, when the desktop theme isn't visible) --------------------------------------
from PySide6.QtGui import QColor, QPalette as _QP  # noqa: E402
from kosmicpdf.theme import choose_palette  # noqa: E402
light = _QP(); light.setColor(_QP.Window, QColor("#faf9f8"))
dark_ok = _QP(); dark_ok.setColor(_QP.Window, QColor("#333339"))
check("dark desktop + light palette -> Kosmos dark palette",
      choose_palette(True, light).color(_QP.Window).name() == "#2e3440")
check("palette kept when it already matches", choose_palette(True, dark_ok) is dark_ok and choose_palette(False, light) is light)

# --- single-instance handoff (on a private socket, never the real app's) ------------------------------------------
from kosmicpdf import app as appmod  # noqa: E402
appmod.SOCKET_PATH = os.path.join(tempfile.mkdtemp(prefix="kosmicpdf-test-sock-"), "s.sock")
check("no running instance -> handoff declines", appmod.send_to_running(["/x.pdf"]) is False)
received = []
server = appmod.InstanceServer(received.append)
check("handoff reaches the running instance", appmod.send_to_running(["/a.pdf", "/b.pdf"]) and (pump(30) or True)
      and received == [["/a.pdf", "/b.pdf"]], str(received))
check("app modules don't load QtNetwork", "PySide6.QtNetwork" not in sys.modules)
os.environ.pop("DESKTOP_STARTUP_ID", None)
appmod.finish_startup_notification()   # nothing to finish: returns quietly
check("handoff without a startup id is quiet", True)

# --- startup: the window first, then the document --------------------------------------------------------------
appmod.defer_import("colorsys")         # a module nothing here has loaded yet
import colorsys  # noqa: E402
check("deferred module isn't loaded by an import", type(colorsys) is appmod.DeferredModule)
check("deferred module loads on first use", colorsys.rgb_to_hsv(1, 0, 0) == (0, 1, 1)
      and type(sys.modules["colorsys"]) is not appmod.DeferredModule)
from kosmicpdf import theme  # noqa: E402
check("icons drawn only at the sizes shown", theme.icon_sizes() == [12, 16], str(theme.icon_sizes()))
shutil.copy(os.path.join(work, "second.pdf"), os.path.join(work, "startup.pdf"))   # not open anywhere yet
w2 = window.MainWindow()
w2.show()
w2.open_when_shown([os.path.join(work, "startup.pdf")])
check("window says what it's opening", w2.empty.text().startswith("Opening startup.pdf") and not w2.doc_tabs())
pump(30)
check("document opens once the window is drawn", len(w2.doc_tabs()) == 1 and w2.empty.text() == window.EMPTY_TEXT
      and QApplication.overrideCursor() is None, f"{len(w2.doc_tabs())} tabs, {w2.empty.text()!r}")
for tab in w2.doc_tabs():
    tab.pdoc.modified = False
w2.close()
pump()

# --- scans without text ---------------------------------------------------------------------------------------
from kosmicpdf.core import page_needs_ocr  # noqa: E402
scan = fitz.open(os.path.join(work, "scanned-letter.pdf"))
check("sample scan has no text, and every page needs OCR",
      not any(p.get_text().strip() for p in scan) and all(page_needs_ocr(p) for p in scan))
check("a text PDF doesn't need OCR", PdfDocument(fitz.open(os.path.join(work, "sample.pdf"))).needs_ocr() is False)
mixed = PdfDocument(fitz.open(os.path.join(work, "sample.pdf")))
mixed.insert_doc(scan, 3)
check("one scanned page among text pages is found", mixed.needs_ocr() is True)
check("a time budget lets a long check carry on later", mixed.needs_ocr(budget=-1) in (None, True)
      and mixed.needs_ocr() is True)

# --- find bar --------------------------------------------------------------------------------------------------
import re  # noqa: E402
import time  # noqa: E402
from kosmicpdf.pageview import find_in_chars, search_pattern  # noqa: E402


def settle(ms=400):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        pump(5); time.sleep(0.01)


ft = w.add_doc(PdfDocument(fitz.open(os.path.join(SAMPLES, "sample.pdf")), title="find.pdf"))
fb = w.findbar
settle(100)
ft.view.go_to_page(2); settle(100)
w.activateWindow(); settle(100)
QTest.keyClick(w, Qt.Key_F, Qt.ControlModifier)
pump()
check("Ctrl+F opens the find bar under the toolbar", fb.isVisible() and w.toolBarArea(fb) == Qt.TopToolBarArea
      and fb.y() > w.toolbar.y()
      and fb.edit.hasFocus())
texts = [p.get_text() for p in ft.pdoc.doc]
want = sum(len(re.findall(r"fox\s+jumps", tx)) for tx in texts)
QTest.keyClicks(fb.edit, "fox jumps")
settle()
check("typing finds every match, including ones wrapped onto the next line",
      len(ft.view.find_hits) == want and want > ft.pdoc.page_count, f"{len(ft.view.find_hits)} of {want}")
check("the first match shown is on the page in view", ft.view.find_hits[ft.view.find_index][0] == 2
      and fb.label.text() == f"{ft.view.find_index + 1} of {want}", fb.label.text())
wrapped = [h for h in ft.view.find_hits if len(h[1]) == 2]
check("a wrapped match is marked on both lines", bool(wrapped))
first = ft.view.find_index
QTest.keyClick(fb.edit, Qt.Key_Return)
check("Enter goes to the next match", ft.view.find_index == first + 1)
QTest.keyClick(fb.edit, Qt.Key_Return, Qt.ShiftModifier)
check("Shift+Enter goes back", ft.view.find_index == first)
w.actions_by_name["find_next"].trigger()
check("F3 / Ctrl+G step on as well", ft.view.find_index == first + 1)
fb.edit.setText("QUICK"); settle()
n_any = len(ft.view.find_hits)
fb.case.setChecked(True); settle()
check("Match Case leaves out other capitals", n_any > 0 and not ft.view.find_hits
      and fb.label.text() == "No matches" and fb.edit.property("notFound") is True, fb.label.text())
fb.case.setChecked(False)
fb.edit.setText("fox jump"); settle()
part = len(ft.view.find_hits)
fb.whole.setChecked(True); settle()
check("Whole Words skips parts of words", part == want and not ft.view.find_hits)
fb.whole.setChecked(False)
chars = [(fitz.Rect(i * 5, 0, i * 5 + 5, 10), c, 1) for i, c in enumerate("Plaintiff’s ﬁling")]
check("curly apostrophes and ligatures match plain typing",
      len(find_in_chars(chars, search_pattern("plaintiff's filing"))) == 1)
fb.edit.setText("lazy dog"); settle()
ft.pdoc.delete_pages([0]); settle()
check("matches are found again after pages change",
      len(ft.view.find_hits) == sum(len(re.findall(r"lazy\s+dog", tx)) for tx in texts[1:]) > 0, str(len(ft.view.find_hits)))
w.set_mode("redact"); pump()
check("find and redaction bars can both be open, one under the other",
      w.redact_bar.isVisible() and fb.isVisible() and fb.y() != w.redact_bar.y())
w.set_mode("select")
QTest.keyClick(fb.edit, Qt.Key_Escape)
check("Esc closes the bar and clears the marks", fb.isHidden() and not ft.view.find_hits)
w.actions_by_name["find"].trigger(); settle()
check("reopening brings the last search back", fb.isVisible() and fb.edit.text() == "lazy dog" and ft.view.find_hits)
fbtn = w.toolbar.widgetForAction(w.actions_by_name["find_bar"])
zoom_at = w.toolbar.actions().index(w.actions_by_name["zoom_in"])
check("Find button sits just after the zoom controls, pressed while the bar is open",
      w.toolbar.actions()[zoom_at + 1] is w.actions_by_name["find_bar"] and fbtn.isChecked())
QTest.mouseClick(fbtn, Qt.LeftButton); pump()
check("clicking it again closes the bar", fb.isHidden() and not fbtn.isChecked() and not ft.view.find_hits)
QTest.mouseClick(fbtn, Qt.LeftButton); pump()
check("and once more opens it", fb.isVisible() and fbtn.isChecked())
check("the find field has a clear button", fb.edit.isClearButtonEnabled())
fb.edit.clear(); pump()
check("clearing the field removes the marks at once", not ft.view.find_hits and fb.label.text() == "")
fb.close_bar()
ft.pdoc.modified = False
w.close_tab(ft)
pump()

# --- the page panel folds away ------------------------------------------------------------------------------------
w.tabs.setCurrentWidget(t); pump()
pbtn = w.toolbar.widgetForAction(w.actions_by_name["thumbs"])
check("page panel button comes first on the toolbar, pressed while the panel shows",
      w.toolbar.actions()[0] is w.actions_by_name["thumbs"] and pbtn.isChecked() and t.thumbs.isVisible())
total = sum(t.splitter.sizes())
t.splitter.setSizes([240, total - 240]); t.splitter.splitterMoved.emit(240, 1); pump()
QTest.mouseClick(pbtn, Qt.LeftButton); pump()
check("clicking it hides the panel in every tab", not pbtn.isChecked()
      and not any(tab.thumbs.isVisible() for tab in w.doc_tabs()))
QTest.mouseClick(pbtn, Qt.LeftButton); pump()
check("clicking again brings it back at the same width", t.thumbs.isVisible() and abs(t.splitter.sizes()[0] - 240) <= 2,
      str(t.splitter.sizes()))
t.splitter.setSizes([0, total]); t.splitter.splitterMoved.emit(0, 1); pump()
check("dragging the edge all the way left folds the panel away", not pbtn.isChecked() and not t.thumbs.isVisible())
w.actions_by_name["thumbs"].trigger(); pump()
check("F4 opens it again at its last width", t.thumbs.isVisible() and abs(t.splitter.sizes()[0] - 240) <= 2
      and not t.splitter.isCollapsible(1), str(t.splitter.sizes()))
check("the panel's state and width are remembered", dialogs.settings().value("view/thumbs", type=bool) is True
      and dialogs.settings().value("view/thumbs_width", type=int) == 240)

# --- dialogs use Lucide icons -----------------------------------------------------------------------------------
from PySide6.QtWidgets import QStyle  # noqa: E402
from kosmicpdf.theme import LucideStyle  # noqa: E402
lstyle = LucideStyle(app.style().name())
discard = lstyle.standardIcon(QStyle.SP_DialogDiscardButton)
question = lstyle.standardIcon(QStyle.SP_MessageBoxQuestion)
check("dialog buttons and message boxes get Lucide icons, drawn once",
      not discard.isNull() and discard.cacheKey() == lstyle.standardIcon(QStyle.SP_DialogDiscardButton).cacheKey()
      and QSize(24, 24) in question.availableSizes()
      and lstyle.pixelMetric(QStyle.PM_MessageBoxIconSize) == 24, str(question.availableSizes()))

# --- page number field ----------------------------------------------------------------------------------------
w.tabs.setCurrentWidget(t); pump()
w.page_box.setText("4")
w.page_box.returnPressed.emit()
pump()
check("typing a page number jumps there", t.view.current_page == 3)

w.tabs.setCurrentWidget(t)
pump(200)
w.grab().save(os.path.join(OUT, "04-final.png"))
for win in list(window.WINDOWS):
    for tab in win.doc_tabs():
        tab.pdoc.modified = False
    win.close()
fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} passed" + (f"; failed: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
