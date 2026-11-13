"""Exhibit labels from the command line, with no window: `kosmospdf label ...`.

For scripts, and for an AI assistant working through a shell: every command prints one
JSON object on standard output, and a failure prints a plain message on standard error
and exits with 1 (2 for a command line that can't be understood). It does what Label
Exhibit Files does in the app, through the same functions (labels.label_files), and
reads the same saved presets, so a label put on here is the same label, and can be
edited or renumbered in the app afterwards.

Nothing here needs a display: Qt is used only for the settings and for colours.
"""
import argparse
import json
import os
import re
import sys

DESIGNATION_MAX = 12      # as the label dialog's field allows

DESCRIPTION = """\
Put exhibit labels on PDFs (or images, which become PDFs) without opening a window.
An exhibit label is the coloured sticker on an exhibit's first page: a caption across
the top ("Plaintiff Exhibit") and the exhibit's number or letter beneath it.

Every command prints one JSON object. Start with `options` to see the saved presets
and the colours, sizes and positions to choose from; try `apply` with --dry-run to see
what it would do before it does it.
"""

APPLY_NOTES = """\
The files are labelled in the order given, numbered on from --start: 3, 4, 5; A, B, C;
12-A, 12-B. Each gets one label, on its first page. A file that already carries a label
has that label changed where it is (number, caption, colour and size) rather than
getting a second one, so to renumber a set, give the files in their new order and run
this again.

One of --in-place or --folder is needed. --in-place replaces each file and, unless
--naming keep is given, renames it "Exhibit 3 - Contract.pdf"; --folder leaves the
files as they are and writes labelled copies there. Either way, nothing is replaced
unless every file was labelled without a problem.

The label is --preset's caption, colour and size, or the built-in default (a yellow
Standard label captioned "Exhibit"), with --caption, --color and --size changing any
of the three.

examples:
  kosmospdf label apply Contract.pdf Letter.pdf --start 1 --preset "Plaintiff" --folder Exhibits
  kosmospdf label apply *.pdf --start A --caption "Defendant Exhibit" --color Blue --in-place --dry-run
"""


class Problem(Exception):
    """Something the caller can put right; its text is the whole message."""


def _settings():
    """The app's settings, with a test run's own folder obeyed (see app.use_test_settings)."""
    from .app import use_test_settings
    from .dialogs import carry_over_settings, settings, terms_accepted
    use_test_settings()
    carry_over_settings()
    if not terms_accepted():
        raise Problem("Kosmos PDF's terms of use haven't been accepted yet. Open Kosmos PDF once and accept them; "
                      "then this will run.")
    return settings()


def _color(text):
    from . import labels
    by_name = {name.lower(): value for name, value in labels.COLORS.items()}
    if text.lower() in by_name:
        return by_name[text.lower()]
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.lower()
    raise Problem(f'"{text}" is not a colour. Give one of {", ".join(labels.COLORS)}, or a hex colour such as #cfe0ff.')


def _size(text):
    from . import labels
    by_name = {name.lower(): wh for name, wh in labels.SIZES.items()}
    if text.lower() in by_name:
        return by_name[text.lower()]
    m = re.fullmatch(r"(\d*\.?\d+)\s*[x×]\s*(\d*\.?\d+)", text.strip(), re.IGNORECASE)
    if m and 0.25 <= float(m[1]) <= 8 and 0.25 <= float(m[2]) <= 8:
        return float(m[1]), float(m[2])
    raise Problem(f'"{text}" is not a size. Give one of {", ".join(labels.SIZES)}, or width by height in inches '
                  'such as 1.5x0.875 (each from 0.25 to 8).')


def _position(text):
    from .dialogs import POSITIONS
    wanted = re.sub(r"[\s_-]+", " ", text.strip()).lower().replace("centre", "center")
    for p in POSITIONS:
        if p.lower() == wanted:
            return p
    raise Problem(f'"{text}" is not a position. Give one of: {", ".join(POSITIONS)}.')


def _params(args, settings):
    """The label's settings: the preset's (or the defaults), with any given outright on top."""
    from . import labels
    params = dict(labels.DEFAULTS)
    if args.preset:
        saved = labels.presets(settings)
        match = [p for p in saved if p["name"].strip().lower() == args.preset.strip().lower()]
        if not match:
            names = ", ".join(f'"{p["name"]}"' for p in saved) or "none are saved yet (save one in the app's label dialog)"
            raise Problem(f'There is no preset called "{args.preset}". Saved presets: {names}.')
        for key in ("caption", "color", "width", "height"):
            if key in match[0]:
                params[key] = match[0][key]
    if args.caption is not None:
        params["caption"] = args.caption.strip()
    if args.color:
        params["color"] = _color(args.color)
    if args.size:
        params["width"], params["height"] = _size(args.size)
    params["width"], params["height"] = float(params["width"]), float(params["height"])
    start = args.start.strip()
    if not start:
        raise Problem("--start needs the first file's number or letter.")
    if len(start) > DESIGNATION_MAX:
        raise Problem(f"--start is longer than a label holds ({DESIGNATION_MAX} characters).")
    params["designation"] = start
    return params


def _labels_in(path):
    """The labels a file carries, in page order: [{page, designation, caption, color, width, height}].
    Raises Problem for a file that is missing, locked or not a PDF or image."""
    import pymupdf as fitz
    from . import labels
    from .core import load_any
    if not os.path.isfile(path):
        raise Problem(f"No such file: {path}")
    try:
        doc = load_any(path)
    except Exception as exc:
        raise Problem(f"{path} can't be read as a PDF or an image ({exc}).") from None
    with doc:
        if doc.needs_pass:
            raise Problem(f"{path} is protected by a password; save an unprotected copy first.")
        out = []
        for page in doc:
            for a in page.annots(types=[fitz.PDF_ANNOT_STAMP]):
                params = labels.label_params(doc, a.xref) if labels.is_label(a) else None
                if params:
                    out.append({"page": page.number + 1, "designation": params["designation"],
                                "caption": params["caption"], "color": params["color"],
                                "width": params["width"], "height": params["height"]})
        return out


def _files(paths):
    files = [os.path.abspath(p) for p in paths]
    seen = set()
    for f in files:
        real = os.path.realpath(f)
        if real in seen:
            raise Problem(f"{f} is given twice.")
        seen.add(real)
    return files


# --- the commands -------------------------------------------------------------------------
def cmd_options(args):
    from . import labels
    from .dialogs import POSITIONS
    return {
        "presets": [{"name": p["name"], "caption": p.get("caption", ""), "color": p.get("color"),
                     "width": p.get("width"), "height": p.get("height")} for p in labels.presets(_settings())],
        "default": {k: labels.DEFAULTS[k] for k in ("caption", "color", "width", "height")},
        "captions": labels.CAPTIONS,
        "colors": dict(labels.COLORS),
        "sizes": {name: {"width": w, "height": h} for name, (w, h) in labels.SIZES.items()},
        "positions": POSITIONS,
        "default_position": "Bottom right",
        "default_margin": labels.DEFAULT_MARGIN,
        "namings": dict(labels.NAMINGS),
        "units": "width and height in inches; margin in points (72 to the inch)",
    }


def cmd_show(args):
    _settings()
    return {"files": [{"file": f, "labels": _labels_in(f)} for f in _files(args.files)]}


def cmd_apply(args):
    from . import labels
    settings = _settings()
    files = _files(args.files)
    params = _params(args, settings)
    position = _position(args.position)
    if not 0 <= args.margin <= 144:
        raise Problem("--margin is in points, from 0 to 144.")
    in_place = args.in_place
    folder = "" if in_place else os.path.abspath(args.folder)
    existing = {f: _labels_in(f) for f in files}          # also checks that each can be read
    targets = labels.targets_for(files, params["designation"], args.naming, in_place, folder)
    problem = labels.files_problem(files, targets, params["designation"], in_place, folder)
    if problem:
        raise Problem(problem)
    if not in_place and not args.overwrite:
        there = [t for t in targets if os.path.exists(t)]
        if there:
            raise Problem("These labelled copies are already in that folder; pass --overwrite to replace them:\n"
                          + "\n".join(there))
    plan = [{"source": f, "file": t, "designation": d, "relabelled": bool(existing[f]),
             "previous_designations": [x["designation"] for x in existing[f]]}
            for (f, d), t in zip(labels.designations(files, params["designation"]), targets)]
    result = {"dry_run": bool(args.dry_run), "in_place": in_place,
              "label": {k: params[k] for k in ("caption", "color", "width", "height")},
              "position": position, "margin": args.margin, "files": plan,
              "next_designation": labels.next_designation(plan[-1]["designation"])}
    if args.dry_run:
        return result
    try:
        labels.label_files(files, targets, params, position, args.margin, in_place)
    except Exception as exc:
        raise Problem(f"Stopped: {exc}\nNo file was changed.") from None
    return result


def build_parser():
    raw = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(prog="kosmospdf label", description=DESCRIPTION, formatter_class=raw)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p = sub.add_parser("options", formatter_class=raw, help="the saved presets, and the colours, sizes and positions to choose from",
                       description="Print the saved presets (each a caption, colour and size under a name, as saved in the "
                                   "app's label dialog) and the built-in colours, sizes, captions and positions.")
    p.set_defaults(run=cmd_options)

    p = sub.add_parser("show", formatter_class=raw, help="the exhibit labels the files already carry",
                       description="Print the exhibit labels each file carries: page, number or letter, caption, colour and size.")
    p.add_argument("files", nargs="+", metavar="FILE")
    p.set_defaults(run=cmd_show)

    p = sub.add_parser("apply", formatter_class=raw, help="label the files in order, or renumber the labels they carry",
                       description="Label a set of files in order.", epilog=APPLY_NOTES)
    p.add_argument("files", nargs="+", metavar="FILE", help="PDFs or images, in exhibit order")
    p.add_argument("--start", required=True, metavar="N", help="the first file's number or letter: 1, A, 12-A")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--in-place", action="store_true", help="label (and rename) the files themselves")
    where.add_argument("--folder", metavar="DIR", help="write labelled copies here instead (made if need be)")
    p.add_argument("--preset", metavar="NAME", help="a saved preset's caption, colour and size (see `options`)")
    p.add_argument("--caption", metavar="TEXT", help='the words across the top, e.g. "Plaintiff Exhibit"; "" for none')
    p.add_argument("--color", "--colour", metavar="COLOR", help="a colour's name (see `options`) or hex, e.g. Blue or #cfe0ff")
    p.add_argument("--size", metavar="SIZE", help="Small, Standard, Wide or Large, or inches as WIDTHxHEIGHT")
    p.add_argument("--position", default="Bottom right", metavar="WHERE",
                   help='where a new label goes on the first page: "Bottom right" (the default), "Top right", ... (see `options`)')
    p.add_argument("--margin", type=float, default=None, metavar="PT", help="from the page's edge, in points (default 18)")
    p.add_argument("--naming", choices=["exhibit", "keep"], default="exhibit",
                   help='exhibit: name each file "Exhibit 3 - Contract.pdf" (the default); keep: keep its name')
    p.add_argument("--overwrite", action="store_true", help="with --folder, replace labelled copies already there")
    p.add_argument("--dry-run", action="store_true", help="print what would be done, and change nothing")
    p.set_defaults(run=cmd_apply)
    return parser


def main(argv=None):
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if getattr(args, "margin", 0) is None:
        from .labels import DEFAULT_MARGIN
        args.margin = DEFAULT_MARGIN
    try:
        result = args.run(args)
    except Problem as exc:
        if sys.stderr:
            print(f"kosmospdf label: {exc}", file=sys.stderr)
        return 1
    if sys.stdout:            # a windowed Windows program started without a pipe has none
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0
