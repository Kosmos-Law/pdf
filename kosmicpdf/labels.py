"""Exhibit labels: the coloured sticker a lawyer puts on the first page of an exhibit, with
a caption across the top ("PLAINTIFF'S EXHIBIT") and the exhibit's number or letter large
beneath it.

A label is a Stamp annotation whose appearance Kosmic PDF draws itself, as vector content
(a filled box, a hairline border, and Helvetica Bold text sized to fit), so it is crisp at
any zoom, prints, flattens, and looks the same in every PDF viewer. Its caption, number,
colour and size are kept in the annotation (``/KosmicPDFLabel``), so the label can be
edited later and redrawn.

MuPDF redraws a Stamp annotation in its own style (a red "Approved") whenever one of its
properties is changed through the annotation API, which would throw the label away. So
labels are never passed through ``Annot.update()`` or ``set_rect()``: the appearance is
written straight into the PDF objects, and a move edits the ``/Rect`` entry directly
(see set_label_rect).
"""
import json
from collections import OrderedDict

import pymupdf as fitz
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QColorDialog, QFormLayout, QLabel,
                               QLineEdit, QVBoxLayout)

LABEL_NAME = "KosmicPDFExhibitLabel"   # the stamp's /Name, which marks it as one of ours
LABEL_KEY = "KosmicPDFLabel"            # the annotation key holding the label's settings, as JSON

# Sticker colours, as sold for exhibit labels, in the order they are offered.
COLORS = OrderedDict([
    ("Yellow", "#ffe94d"), ("Orange", "#ffa94d"), ("Red", "#f0625f"), ("Pink", "#ff8fc8"),
    ("Green", "#7ad67a"), ("Blue", "#6fa8ff"), ("Light Blue", "#aed9ff"), ("Purple", "#b48bff"),
    ("Grey", "#d9d9d9"), ("White", "#ffffff"),
])
SIZES = OrderedDict([("Small", (1.5, 0.875)), ("Standard", (1.75, 1.0)), ("Large", (2.25, 1.25))])   # inches
CAPTIONS = ["EXHIBIT", "PLAINTIFF'S EXHIBIT", "DEFENDANT'S EXHIBIT", "DEPOSITION EXHIBIT", "JOINT EXHIBIT",
            "PETITIONER'S EXHIBIT", "RESPONDENT'S EXHIBIT", "STATE'S EXHIBIT", "TRIAL EXHIBIT"]
DEFAULTS = {"caption": "EXHIBIT", "designation": "1", "color": COLORS["Yellow"], "width": 1.75, "height": 1.0}
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


def appearance(params):
    """The label's appearance as a PDF content stream (bytes), drawn in a box of
    label_size(params) with its origin at the bottom left, as PDF content is."""
    w, h = label_size(params)
    fill = _rgb(params["color"])
    border = tuple(v * 0.55 for v in fill)        # a darker shade of the fill
    tc = text_color(params["color"])
    pad = 0.07 * h
    out = [f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg {border[0]:.3f} {border[1]:.3f} {border[2]:.3f} RG 1 w",
           f"0.5 0.5 {w - 1:.2f} {h - 1:.2f} re B",
           f"{tc[0]} {tc[1]} {tc[2]} rg"]
    top = h - pad                                  # where the next line of text may start
    caption = params["caption"].strip()
    if caption:
        cs = _fit(caption, w - 2 * pad, 0.19 * h)
        baseline = top - CAP_HEIGHT * cs
        x = (w - fitz.get_text_length(caption, FONT, cs)) / 2
        out.append(f"BT /HeBo {cs:.2f} Tf 1 0 0 1 {x:.2f} {baseline:.2f} Tm {_pdf_string(caption)} Tj ET")
        top = baseline - 0.35 * cs
    designation = params["designation"].strip()
    if designation:
        avail = top - pad
        glyph = CAP_HEIGHT + (DESCENDER if DESCENDING & set(designation) else 0)
        ds = _fit(designation, w - 2 * pad, avail * 0.9 / glyph)
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


class LabelDialog(QDialog):
    """Caption, number or letter, colour and size of an exhibit label, with a preview.
    For a new label, OK means "go and place it"; for an existing one, the changes apply."""

    def __init__(self, parent, params, editing=False):
        super().__init__(parent)
        self.setWindowTitle("Edit Exhibit Label" if editing else "Exhibit Label")
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
            self.size.addItem(f'{name}  ({w:g}" × {h:g}")', (w, h))
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(int(SIZES["Large"][1] * 72) + 8)
        form = QFormLayout()
        form.addRow("Caption", self.caption)
        form.addRow("Number or letter", self.designation)
        form.addRow("Colour", self.color)
        form.addRow("Size", self.size)
        form.addRow("Preview", self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply" if editing else "Place")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        if not editing:
            lay.addWidget(QLabel("Click where the label should go; it follows the mouse until then.\n"
                                 "Afterwards, drag it to move it, or use the button on its corner to delete it."))
        lay.addWidget(buttons)
        self._set_color(params["color"])
        self._set_size(params["width"], params["height"])
        self.caption.currentTextChanged.connect(self._update)
        self.designation.textChanged.connect(self._update)
        self.color.activated.connect(self._color_chosen)
        self.size.currentIndexChanged.connect(self._update)
        self.designation.setFocus()
        self.designation.selectAll()
        self._update()

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
        i = self.size.findData((w, h))
        if i < 0:
            self.size.addItem(f'Custom  ({w:g}" × {h:g}")', (w, h))
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
