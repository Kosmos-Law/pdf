"""Exhibit labels: the coloured sticker a lawyer puts on the first page of an exhibit, with
a caption across the top ("PLAINTIFF'S EXHIBIT") and the exhibit's number or letter large
beneath it.

A label is a Stamp annotation whose appearance Kosmic PDF draws itself, as vector content
(a filled box with rounded corners and a black border, and Helvetica Bold text sized to
fit), so it is crisp at any zoom, prints, flattens, and looks the same in every PDF
viewer. Its caption, number, colour and size are kept in the annotation
(``/KosmicPDFLabel``), so the label can be edited later and redrawn.

Presets (a caption, colour and size under a name) are the user's own, kept in the
settings, so they carry across files.

Label Exhibit Files (LabelFilesDialog, label_files) labels a set of files in order, as
Bates Number Files does: into copies, or the files themselves, renamed "Exhibit 3 -
Contract.pdf". A file that already carries a label has it renumbered rather than
doubled, so reordering the list and running it again renumbers the whole set, names
and stickers together.

MuPDF redraws a Stamp annotation in its own style (a red "Approved") whenever one of its
properties is changed through the annotation API, which would throw the label away. So
labels are never passed through ``Annot.update()`` or ``set_rect()``: the appearance is
written straight into the PDF objects, and a move edits the ``/Rect`` entry directly
(see set_label_rect).
"""
import json
import os
import re
from collections import OrderedDict

import pymupdf as fitz
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QColorDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from .core import load_any
from .dialogs import FileList, PDFS_AND_IMAGES, POSITIONS, settings as app_settings

LABEL_NAME = "KosmicPDFExhibitLabel"   # the stamp's /Name, which marks it as one of ours
LABEL_KEY = "KosmicPDFLabel"            # the annotation key holding the label's settings, as JSON

# Label colours: pale, like the firm's highlight colours (pageview.HIGHLIGHT_COLORS), so the
# black text and border stand out and the page beneath isn't shouted down.
COLORS = OrderedDict([
    ("Yellow", "#ffffa6"), ("Orange", "#ffdcaa"), ("Red", "#ffc2bd"), ("Pink", "#ffd3e8"),
    ("Green", "#dde8cb"), ("Blue", "#cfe0ff"), ("Purple", "#dedce6"), ("Beige", "#ddd8c3"),
    ("Grey", "#e2e2e2"), ("White", "#ffffff"),
])
SIZES = OrderedDict([("Small", (1.0, 0.625)), ("Standard", (1.25, 0.75)), ("Wide", (1.75, 0.75)),
                     ("Large", (1.5, 0.875))])   # inches; Wide is Standard's height, for a long caption
CAPTIONS = ["Exhibit", "Plaintiff Exhibit", "Defendant Exhibit", "Deposition Exhibit", "Joint Exhibit",
            "Petitioner Exhibit", "Respondent Exhibit", "State Exhibit", "Trial Exhibit"]
DEFAULTS = {"caption": "Exhibit", "designation": "1", "color": COLORS["Yellow"], "width": 1.25, "height": 0.75}
PRESETS_KEY = "label/presets"      # the user's saved presets, as JSON: [{name, caption, color, width, height}]
BORDER = 2.0                        # pt
CORNER = 0.09                       # corner radius, as a share of the label's height
KAPPA = 0.5523                      # Bézier handle length for a quarter circle, as a share of the radius
GHOST_OPACITY = 0.65     # of the label shown under the cursor while choosing where it goes

FONT = "hebo"            # Helvetica Bold, one of the PDF base fonts: no embedding needed
CAP_HEIGHT = 0.718       # of the font size, for Helvetica
DESCENDER = 0.21
DESCENDING = set("gjpqyQ,;()")


def is_label(annot):
    return annot.type[0] == fitz.PDF_ANNOT_STAMP and annot.info.get("name") == LABEL_NAME


def label_params(doc, xref):
    """The settings stored in a label annotation, or None if it isn't one of ours."""
    kind, value = doc.xref_get_key(xref, LABEL_KEY)
    if kind != "string":
        return None
    try:
        params = dict(DEFAULTS)
        params.update(json.loads(value))
        return params
    except ValueError:
        return None


def label_size(params):
    """Width and height in points."""
    return params["width"] * 72, params["height"] * 72


def text_color(hex_color):
    """Black text on light stickers, white on dark ones."""
    c = QColor(hex_color)
    luminance = 0.299 * c.redF() + 0.587 * c.greenF() + 0.114 * c.blueF()
    return (0, 0, 0) if luminance > 0.5 else (1, 1, 1)


def _rgb(hex_color):
    c = QColor(hex_color)
    return c.redF(), c.greenF(), c.blueF()


def _pdf_string(text):
    """A PDF literal string in WinAnsi, which is how the base fonts are encoded here.
    Characters outside it (rare in a caption) become question marks."""
    s = text.encode("cp1252", "replace").decode("latin-1")
    return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def _fit(text, max_width, max_size):
    """The largest font size, up to max_size, at which text fits in max_width points."""
    per_pt = fitz.get_text_length(text, FONT, 1.0)
    return min(max_size, max_width / per_pt) if per_pt > 0 else max_size


def rounded_rect_path(x0, y0, x1, y1, r):
    """PDF path operators for a rectangle with corners rounded to radius r."""
    k = KAPPA * r
    return (f"{x0 + r:.2f} {y0:.2f} m {x1 - r:.2f} {y0:.2f} l "
            f"{x1 - r + k:.2f} {y0:.2f} {x1:.2f} {y0 + r - k:.2f} {x1:.2f} {y0 + r:.2f} c "
            f"{x1:.2f} {y1 - r:.2f} l {x1:.2f} {y1 - r + k:.2f} {x1 - r + k:.2f} {y1:.2f} {x1 - r:.2f} {y1:.2f} c "
            f"{x0 + r:.2f} {y1:.2f} l {x0 + r - k:.2f} {y1:.2f} {x0:.2f} {y1 - r + k:.2f} {x0:.2f} {y1 - r:.2f} c "
            f"{x0:.2f} {y0 + r:.2f} l {x0:.2f} {y0 + r - k:.2f} {x0 + r - k:.2f} {y0:.2f} {x0 + r:.2f} {y0:.2f} c h")


def appearance(params):
    """The label's appearance as a PDF content stream (bytes), drawn in a box of
    label_size(params) with its origin at the bottom left, as PDF content is."""
    w, h = label_size(params)
    fill = _rgb(params["color"])
    tc = text_color(params["color"])
    pad = 0.08 * h                                 # below the number
    caption_pad = 0.12 * h                         # above the caption, and either side of it
    out = [f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg 0 G {BORDER} w 1 j",
           rounded_rect_path(BORDER / 2, BORDER / 2, w - BORDER / 2, h - BORDER / 2, CORNER * h) + " B",
           f"{tc[0]} {tc[1]} {tc[2]} rg"]
    top = h - caption_pad                          # where the next line of text may start
    caption = params["caption"].strip()
    if caption:
        cs = _fit(caption, w - 2 * caption_pad, 0.2 * h)
        baseline = top - CAP_HEIGHT * cs
        x = (w - fitz.get_text_length(caption, FONT, cs)) / 2
        out.append(f"BT /HeBo {cs:.2f} Tf 1 0 0 1 {x:.2f} {baseline:.2f} Tm {_pdf_string(caption)} Tj ET")
        top = baseline - 0.35 * cs
    designation = params["designation"].strip()
    if designation:
        avail = top - pad
        glyph = CAP_HEIGHT + (DESCENDER if DESCENDING & set(designation) else 0)
        ds = _fit(designation, w - 2 * pad, avail * 0.52 / glyph)      # large, but not filling the box
        baseline = pad + (avail - glyph * ds) / 2 + (DESCENDER * ds if glyph > CAP_HEIGHT else 0)
        x = (w - fitz.get_text_length(designation, FONT, ds)) / 2
        out.append(f"BT /HeBo {ds:.2f} Tf 1 0 0 1 {x:.2f} {baseline:.2f} Tm {_pdf_string(designation)} Tj ET")
    return "\n".join(out).encode("latin-1")


def _write_appearance(doc, page, xref, params):
    """Give the label annotation its appearance stream, replacing any it has. The form's
    Matrix turns it with the page's rotation, so it reads upright however the page is shown."""
    w, h = label_size(params)
    kind, value = doc.xref_get_key(xref, "AP/N")
    if kind == "xref":
        apx = int(value.split()[0])
    else:
        apx = doc.get_new_xref()
        doc.xref_set_key(xref, "AP", f"<</N {apx} 0 R>>")
    kind, value = doc.xref_get_key(apx, "Resources/Font/HeBo")
    if kind == "xref":
        fx = int(value.split()[0])          # the font object from an earlier drawing of this label
    else:
        fx = doc.get_new_xref()
        doc.update_object(fx, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>")
    m = fitz.Matrix(page.rotation)
    doc.update_object(apx, f"<</Type/XObject/Subtype/Form/BBox[0 0 {w:g} {h:g}]"
                           f"/Matrix[{m.a:g} {m.b:g} {m.c:g} {m.d:g} 0 0]/Resources<</Font<</HeBo {fx} 0 R>>>>>>")
    doc.update_stream(apx, appearance(params))
    doc.xref_set_key(xref, "Name", "/" + LABEL_NAME)
    doc.xref_set_key(xref, "Contents", _pdf_string(" ".join(s for s in (params["caption"].strip(),
                                                                         params["designation"].strip()) if s)))
    doc.xref_set_key(xref, "Subj", "(Exhibit Label)")
    doc.xref_set_key(xref, LABEL_KEY, "<" + json.dumps(params).encode().hex() + ">")


def set_label_rect(page, xref, vis_rect):
    """Put the label at vis_rect (page coordinates as displayed, i.e. after rotation) by
    editing its /Rect directly, which MuPDF doesn't take as a reason to redraw it."""
    doc = page.parent
    r = fitz.Rect(vis_rect) * page.derotation_matrix * page.transformation_matrix
    doc.xref_set_key(xref, "Rect", f"[{r.x0:g} {r.y0:g} {r.x1:g} {r.y1:g}]")


def clamp(rect, bounds):
    """rect moved, as little as possible, to lie within bounds (both fitz.Rect)."""
    r = fitz.Rect(rect)
    dx = min(0, bounds.x1 - r.x1) if r.x0 >= bounds.x0 else bounds.x0 - r.x0
    dy = min(0, bounds.y1 - r.y1) if r.y0 >= bounds.y0 else bounds.y0 - r.y0
    return r + (dx, dy, dx, dy)


def label_rect_at(page, vis_center, params):
    """The visible rect of a label of this size centred on vis_center, kept on the page."""
    w, h = label_size(params)
    r = fitz.Rect(vis_center.x - w / 2, vis_center.y - h / 2, vis_center.x + w / 2, vis_center.y + h / 2)
    return clamp(r, fitz.Rect(0, 0, page.rect.width, page.rect.height))


def add_label(page, vis_rect, params):
    """Place a label on the page, its top left at vis_rect's (as displayed). Returns its xref."""
    doc = page.parent
    annot = page.add_stamp_annot(fitz.Rect(vis_rect) * page.derotation_matrix, stamp=0)
    xref = annot.xref
    _write_appearance(doc, page, xref, params)
    set_label_rect(page, xref, vis_rect)
    return xref


def update_label(page, xref, params):
    """Change a label's caption, number, colour or size, keeping its centre where it is."""
    doc = page.parent
    annot = page.load_annot(xref)
    vis = annot.rect * page.rotation_matrix
    _write_appearance(doc, page, xref, params)
    set_label_rect(page, xref, label_rect_at(page, (vis.tl + vis.br) / 2, params))


def fix_rotation(page):
    """After the page's rotation changed: turn its labels so they read upright again, each
    centred where it was. (Their rectangles swap width and height with a quarter turn.)"""
    doc = page.parent
    for annot in page.annots(types=[fitz.PDF_ANNOT_STAMP]):
        params = label_params(doc, annot.xref) if is_label(annot) else None
        if params:
            vis = annot.rect * page.rotation_matrix
            _write_appearance(doc, page, annot.xref, params)
            set_label_rect(page, annot.xref, label_rect_at(page, (vis.tl + vis.br) / 2, params))


def next_designation(s):
    """The designation after this one: 3 -> 4, A -> B, Z -> AA, 12-A -> 12-B; anything
    else stays as it is."""
    s = s.strip()
    if not s:
        return s
    if s[-1].isdigit():
        head = s.rstrip("0123456789")
        digits = s[len(head):]
        return head + str(int(digits) + 1).zfill(len(digits))
    if s[-1].isalpha() and s[-1].isascii():
        head = s.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
        letters = s[len(head):]
        upper = letters.isupper()
        letters = letters.upper()
        # Letters count like spreadsheet columns: Z -> AA, AZ -> BA.
        chars = list(letters)
        i = len(chars) - 1
        while i >= 0:
            if chars[i] != "Z":
                chars[i] = chr(ord(chars[i]) + 1)
                break
            chars[i] = "A"
            i -= 1
        else:
            chars.insert(0, "A")
        out = "".join(chars)
        return head + (out if upper else out.lower())
    return s


def label_pixmap(params, zoom, dpr=1.0):
    """The label drawn exactly as it will appear on the page, at the view's zoom, as a
    QPixmap with a transparent background: the ghost that follows the cursor, and the
    dialog's preview."""
    w, h = label_size(params)
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    add_label(page, fitz.Rect(0, 0, w, h), params)
    page = doc[0]       # reload, so the annotation just written is rendered
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom * dpr, zoom * dpr), alpha=True)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGBA8888).copy()
    doc.close()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


# --- settings ----------------------------------------------------------------------
def remembered(settings):
    """The label settings to offer: what was used last, with the next number or letter."""
    params = dict(DEFAULTS)
    for key in ("caption", "designation", "color"):
        params[key] = settings.value(f"label/{key}", params[key])
    params["width"] = float(settings.value("label/width", params["width"]))
    params["height"] = float(settings.value("label/height", params["height"]))
    return params


def remember(settings, params, placed=True):
    """Keep the settings for next time; after a label is placed, move on to the next
    number or letter."""
    for key in ("caption", "color", "width", "height"):
        settings.setValue(f"label/{key}", params[key])
    settings.setValue("label/designation", next_designation(params["designation"]) if placed else params["designation"])


def presets(settings):
    """The user's saved presets, in the order saved: [{name, caption, color, width, height}]."""
    try:
        saved = json.loads(settings.value(PRESETS_KEY, "[]"))
        return [p for p in saved if isinstance(p, dict) and "name" in p]
    except ValueError:
        return []


def save_presets(settings, items):
    settings.setValue(PRESETS_KEY, json.dumps(items))


def size_text(w, h):
    name = next((n for n, wh in SIZES.items() if wh == (w, h)), "Custom")
    return f'{name}  ({w:g}" × {h:g}")'


class LabelFields(QWidget):
    """The settings of an exhibit label: preset, caption, number or letter, colour and size,
    with a preview. Shared by the label dialog and Label Exhibit Files. A preset (a
    caption, colour and size under a name) fills the fields in one go; the user can save
    the fields as one, or remove one, and they carry across files."""
    changed = Signal()

    def __init__(self, params, settings=None, designation_label="Number or letter"):
        super().__init__()
        self.settings = settings if settings is not None else app_settings()
        self.preset = QComboBox()
        self.preset.setToolTip("A saved caption, colour and size")
        self.save_button = QPushButton("Save…")
        self.save_button.setToolTip("Save the caption, colour and size below as a preset")
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Remove the chosen preset")
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.preset, 1)
        preset_row.addWidget(self.save_button)
        preset_row.addWidget(self.remove_button)
        self.caption = QComboBox(editable=True)
        self.caption.addItems(CAPTIONS)
        self.caption.setCurrentText(params["caption"])
        self.designation = QLineEdit(params["designation"])
        self.designation.setMaxLength(12)
        self.color = QComboBox()
        for name, hex_color in COLORS.items():
            self.color.addItem(self._swatch(hex_color), name, hex_color)
        self.color.addItem("Other colour…", "other")
        self.size = QComboBox()
        for name, (w, h) in SIZES.items():
            self.size.addItem(size_text(w, h), (w, h))
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(int(SIZES["Large"][1] * 72) + 8)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.addRow("Preset", preset_row)
        self.form.addRow("Caption", self.caption)
        self.form.addRow(designation_label, self.designation)
        self.form.addRow("Colour", self.color)
        self.form.addRow("Size", self.size)
        self.form.addRow("Preview", self.preview)
        self._set_color(params["color"])
        self._set_size(params["width"], params["height"])
        self._fill_presets()
        self.caption.currentTextChanged.connect(self._update)
        self.designation.textChanged.connect(self._update)
        self.color.activated.connect(self._color_chosen)
        self.size.currentIndexChanged.connect(self._update)
        self.preset.activated.connect(self._preset_chosen)
        self.save_button.clicked.connect(self._save_preset)
        self.remove_button.clicked.connect(self._remove_preset)
        self._update()

    # --- presets ---
    def _fill_presets(self):
        self.preset.clear()
        items = presets(self.settings)
        self.preset.addItem("Choose a preset…" if items else "No presets saved yet", None)
        for item in items:
            self.preset.addItem(self._swatch(item["color"]), item["name"], item)
        self._match_preset()

    def _match_preset(self):
        """Show the preset the fields agree with, if any; otherwise the placeholder."""
        p = self.params()
        for i in range(1, self.preset.count()):
            item = self.preset.itemData(i)
            if (item["caption"], item["color"], item["width"], item["height"]) == (p["caption"], p["color"], p["width"], p["height"]):
                self.preset.setCurrentIndex(i)
                break
        else:
            self.preset.setCurrentIndex(0)
        self.remove_button.setEnabled(self.preset.currentIndex() > 0)

    def _preset_chosen(self, index):
        item = self.preset.itemData(index)
        if not item:
            return
        self.caption.setCurrentText(item["caption"])
        self._set_color(item["color"])
        self._set_size(item["width"], item["height"])
        self._update()

    def _save_preset(self):
        p = self.params()
        current = self.preset.currentData()
        name, ok = QInputDialog.getText(self, "Save Preset", "Name for this caption, colour and size:",
                                        text=current["name"] if current else p["caption"])
        name = name.strip()
        if not ok or not name:
            return
        items = [item for item in presets(self.settings) if item["name"] != name]
        items.append({"name": name, "caption": p["caption"], "color": p["color"], "width": p["width"], "height": p["height"]})
        save_presets(self.settings, items)
        self._fill_presets()

    def _remove_preset(self):
        current = self.preset.currentData()
        if not current:
            return
        if QMessageBox.question(self, "Remove Preset", f'Remove the preset "{current["name"]}"?') != QMessageBox.Yes:
            return
        save_presets(self.settings, [item for item in presets(self.settings) if item["name"] != current["name"]])
        self._fill_presets()

    @staticmethod
    def _swatch(hex_color):
        from .theme import swatch
        return swatch(_rgb(hex_color))

    def _set_color(self, hex_color):
        i = self.color.findData(hex_color)
        if i < 0:        # a colour of the user's own: offered as a swatch above "Other colour…"
            i = self.color.count() - 1
            self.color.insertItem(i, self._swatch(hex_color), "Custom", hex_color)
        self.color.setCurrentIndex(i)

    def _set_size(self, w, h):
        # (findData can't match a tuple, so look by hand.)
        i = next((n for n in range(self.size.count()) if self.size.itemData(n) == (w, h)), -1)
        if i < 0:
            self.size.addItem(size_text(w, h), (w, h))
            i = self.size.count() - 1
        self.size.setCurrentIndex(i)

    def _color_chosen(self, index):
        if self.color.itemData(index) == "other":
            current = QColor(self._last_color)
            chosen = QColorDialog.getColor(current, self, "Label colour")
            self._set_color(chosen.name() if chosen.isValid() else self._last_color)
        self._update()

    def params(self):
        w, h = self.size.currentData()
        return {"caption": self.caption.currentText().strip(), "designation": self.designation.text().strip(),
                "color": self.color.currentData(), "width": w, "height": h}

    def _update(self, *_):
        if self.color.currentData() == "other":
            return
        self._last_color = self.color.currentData()
        p = self.params()
        dpr = self.devicePixelRatioF()
        self.preview.setPixmap(label_pixmap(p, 1.0, dpr))
        self.preview.setMinimumSize(QSize(int(p["width"] * 72) + 8, int(SIZES["Large"][1] * 72) + 8))
        if self.preset.count():
            self._match_preset()
        self.changed.emit()


class LabelDialog(QDialog):
    """Caption, number or letter, colour and size of one exhibit label (see LabelFields).
    For a new label, OK means "go and place it"; for an existing one, the changes apply."""

    def __init__(self, parent, params, editing=False, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Exhibit Label" if editing else "Exhibit Label")
        self.fields = LabelFields(params, settings)
        for name in ("preset", "save_button", "remove_button", "caption", "designation", "color", "size", "preview",
                     "params", "_update", "_preset_chosen"):
            setattr(self, name, getattr(self.fields, name))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply" if editing else "Place")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.fields)
        if not editing:
            lay.addWidget(QLabel("Click where the label should go; it follows the mouse until then.\n"
                                 "Afterwards, drag it to move it, or use the button on its corner to delete it."))
        lay.addWidget(buttons)
        self.designation.setFocus()
        self.designation.selectAll()


# --- Label Exhibit Files: a set of files, labelled and named in order ----------------------
# A file name's existing designation prefix, "Exhibit 3 - " or "3 - ", which is replaced
# when the file is labelled (so renumbering doesn't pile prefixes up).
NAME_PREFIX = re.compile(r"^(?:Exhibit\s+)?(\d{1,4}|[A-Za-z]{1,3}|\d{1,4}-[A-Za-z]{1,3})\s+-\s+", re.IGNORECASE)
NAMINGS = OrderedDict([("exhibit", "Exhibit 3 - name.pdf"), ("keep", "Keep the file names")])
DEFAULT_MARGIN = 18.0    # pt from the page's edge to the label


def exhibit_name(path, designation, naming="exhibit"):
    """The labelled file's name: 'Exhibit 3 - Contract.pdf', with any designation the
    name already carried replaced; or the name kept, as a PDF."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if naming == "keep":
        return stem + ".pdf"
    return f"Exhibit {designation} - {NAME_PREFIX.sub('', stem, count=1)}.pdf"


def file_labels(path):
    """The designations of the labels a file already carries, in page order; [] if none,
    or if the file can't be read."""
    try:
        with load_any(path) as doc:
            if doc.needs_pass:
                return []
            out = []
            for page in doc:
                for a in page.annots(types=[fitz.PDF_ANNOT_STAMP]):
                    params = label_params(doc, a.xref) if is_label(a) else None
                    if params:
                        out.append(params["designation"])
            return out
    except Exception:
        return []


def corner_rect(page, params, position, margin):
    """The visible rect of a new label in a corner (one of dialogs.POSITIONS) of the page."""
    w, h = label_size(params)
    W, H = page.rect.width, page.rect.height
    vert, horiz = position.split()
    x = {"left": margin, "center": (W - w) / 2, "right": W - margin - w}[horiz]
    y = margin if vert == "Top" else H - margin - h
    return clamp(fitz.Rect(x, y, x + w, y + h), fitz.Rect(0, 0, W, H))


def label_file(src, dst, params, position, margin):
    """Label one file into dst (a path to write): a label it already has is changed to
    params in place; otherwise one goes in the given corner of the first page. Returns
    True if the file was already labelled."""
    doc = load_any(src)
    had = False
    for page in doc:
        for a in list(page.annots(types=[fitz.PDF_ANNOT_STAMP])):
            if is_label(a):
                update_label(page, a.xref, params)
                had = True
    if not had and doc.page_count:
        page = doc[0]
        add_label(page, corner_rect(page, params, position, margin), params)
    doc.save(dst, garbage=3, deflate=True)
    doc.close()
    return had


def label_files(files, targets, params, position, margin, in_place=False, progress=None):
    """Label files in order into targets (one path per file), each numbered on from the
    one before, starting at params["designation"]. With in_place, the files themselves
    are replaced (and renamed) rather than copied. Every file is written to a temporary
    name first and nothing is replaced until all have succeeded, so a failure midway
    leaves the files as they were. Returns [(target, designation, was already labelled)]."""
    temps, done, designation = [], [], params["designation"]
    try:
        for k, (src, dst) in enumerate(zip(files, targets)):
            if progress:
                progress(k, src)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            tmp = dst + ".kosmicpdf-tmp"
            had = label_file(src, tmp, dict(params, designation=designation), position, margin)
            temps.append(tmp)
            done.append((dst, designation, had))
            designation = next_designation(designation)
    except Exception:
        for tmp in temps:
            if os.path.exists(tmp):
                os.remove(tmp)
        raise
    if in_place:
        kept = {os.path.realpath(t) for t in targets}
        for src in files:
            if os.path.realpath(src) not in kept and os.path.exists(src):
                os.remove(src)
    for tmp, dst in zip(temps, targets):
        os.replace(tmp, dst)
    return done


class LabelFilesDialog(QDialog):
    """Label a set of files, in an order the user sets, into copies named
    "Exhibit 3 - Contract.pdf", or the files themselves, renamed. Files already labelled
    are renumbered, so the whole set can be reordered and run again."""

    def __init__(self, parent, files=(), settings=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else app_settings()
        self.setWindowTitle("Label Exhibit Files")
        self.resize(760, 720)
        self._existing = {}
        self.list = FileList(PDFS_AND_IMAGES, label=self._label)
        self.fields = LabelFields(remembered(self.settings), self.settings, designation_label="Start at")
        self.position = QComboBox()
        self.position.addItems(POSITIONS)
        self.position.setCurrentText(self.settings.value("label_files/position", "Bottom right"))
        self.margin = QDoubleSpinBox(minimum=0, maximum=144, value=float(self.settings.value("label_files/margin", DEFAULT_MARGIN)),
                                     suffix=" pt")
        self.margin.setToolTip("From the page's edge, for a label that is being added")
        position_row = QHBoxLayout()
        position_row.addWidget(self.position, 1)
        position_row.addWidget(QLabel("Margin"))
        position_row.addWidget(self.margin)
        self.naming = QComboBox()
        for key, text in NAMINGS.items():
            self.naming.addItem(text, key)
        self.naming.setCurrentIndex(max(0, self.naming.findData(self.settings.value("label_files/naming", "exhibit"))))
        self.copies = QRadioButton("Labelled copies, saved in")
        self.in_place = QRadioButton("The files themselves, labelled and renamed where they are")
        (self.in_place if self.settings.value("label_files/in_place", "false") == "true" else self.copies).setChecked(True)
        self.folder = QLineEdit()
        browse = QPushButton("Choose…", clicked=self._choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.copies)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        self.example = QLabel()
        self.example.setForegroundRole(QPalette.PlaceholderText)
        form = self.fields.form
        form.addRow("Position", position_row)
        form.addRow("File names", self.naming)
        form.addRow("", self.example)
        form.addRow("Write", folder_row)
        form.addRow("", self.in_place)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Label Files")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Drag to set the order: the numbering runs top to bottom. Delete takes the selected files "
                             "out.\nA file that already carries a label is renumbered rather than given a second one, "
                             "so to renumber a set, put the files in their new order and label them again."))
        lay.addWidget(self.list, 1)
        lay.addWidget(self.fields)
        lay.addWidget(buttons)
        self.list.changed.connect(self._update)
        self.fields.changed.connect(self.list.relabel)
        self.fields.changed.connect(self._update)
        self.naming.currentIndexChanged.connect(self._update)
        self.copies.toggled.connect(self._update)
        self.list.add(list(files))
        self._update()

    def _existing_of(self, f):
        if f not in self._existing:
            self._existing[f] = file_labels(f)
        return self._existing[f]

    def designations(self):
        """[(file, designation)] in the list's order."""
        out, d = [], self.fields.params()["designation"]
        for f in self.list.files():
            out.append((f, d))
            d = next_designation(d)
        return out

    def targets(self):
        naming, folder = self.naming_key(), self.folder.text()
        return [os.path.join(os.path.dirname(f) if self.in_place.isChecked() else folder, exhibit_name(f, d, naming))
                for f, d in self.designations()]

    def _label(self, f):
        for (path, d), target in zip(self.designations(), self.targets()):
            if path == f:
                name = os.path.basename(target)
                old = self._existing_of(f)
                if old and old != [d] * len(old):
                    note = f"    (now labelled {', '.join(old)})"
                elif not old:
                    note = "    (no label yet)"
                else:
                    note = ""
                return name + ("" if name == os.path.basename(f) else f"    was {os.path.basename(f)}") + note
        return os.path.basename(f)

    def _update(self, *_):
        files = self.list.files()
        if files and not self.folder.text():
            self.folder.setText(os.path.join(os.path.dirname(files[0]), "Exhibits"))
        self.folder.setEnabled(self.copies.isChecked())
        d = self.fields.params()["designation"]
        self.example.setText("e.g. " + exhibit_name(files[0] if files else "Contract.pdf", d, self.naming_key()))
        self.list.relabel()

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Save the labelled copies in", self.folder.text()
                                             or self.settings.value("last_dir", os.path.expanduser("~")))
        if d:
            self.folder.setText(d)

    def naming_key(self):
        return self.naming.currentData()

    def problem(self):
        """Why the files can't be labelled as set up, or None."""
        files = self.list.files()
        if not files:
            return "Add the files to label first."
        if not self.fields.params()["designation"]:
            return "Give the first file its number or letter (Start at)."
        sources = {os.path.realpath(f) for f in files}
        targets = [os.path.realpath(t) for t in self.targets()]
        if len(set(targets)) < len(targets):
            return "Two files would get the same name. Rename one of them first."
        if self.in_place.isChecked():
            clash = [t for t in targets if os.path.exists(t) and t not in sources]
            if clash:
                return ("That would replace a file that isn't in the list:\n" + "\n".join(os.path.basename(t) for t in clash[:8]))
            return None
        if not self.folder.text().strip():
            return "Choose a folder for the labelled copies."
        if sources & set(targets):
            return "That would save over an original file. Choose another folder, or label the files where they are."
        return None

    def accept(self):
        problem = self.problem()
        if problem:
            QMessageBox.information(self, "Label Exhibit Files", problem)
            return
        if self.copies.isChecked():
            existing = [t for t in self.targets() if os.path.exists(t)]
            if existing:
                names = "\n".join(os.path.basename(t) for t in existing[:8]) + ("\n…" if len(existing) > 8 else "")
                r = QMessageBox.question(self, "Label Exhibit Files",
                                         f"{len(existing)} of the labelled copies are already in that folder:\n\n{names}"
                                         "\n\nReplace them?", QMessageBox.Yes | QMessageBox.Cancel)
                if r != QMessageBox.Yes:
                    return
        s = self.settings
        s.setValue("label_files/position", self.position.currentText())
        s.setValue("label_files/margin", self.margin.value())
        s.setValue("label_files/naming", self.naming_key())
        s.setValue("label_files/in_place", "true" if self.in_place.isChecked() else "false")
        super().accept()
