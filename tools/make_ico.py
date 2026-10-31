#!/usr/bin/env python3
"""Build the Windows icon (kosmicpdf/icons/app/kosmicpdf.ico) from the PNG sizes already
in that folder. An .ico can hold PNG-compressed images (Windows Vista and later), so no
image library is needed: this writes the icon directory by hand.

    .venv/bin/python tools/make_ico.py
"""
import os
import struct

SIZES = (16, 24, 32, 48, 64, 128, 256)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
folder = os.path.join(here, "kosmicpdf", "icons", "app")

images = [open(os.path.join(folder, f"kosmicpdf-{s}.png"), "rb").read() for s in SIZES]
header = struct.pack("<HHH", 0, 1, len(SIZES))        # reserved, type 1 = icon, count
offset = len(header) + 16 * len(SIZES)
entries, blobs = b"", b""
for size, png in zip(SIZES, images):
    dim = 0 if size == 256 else size                  # 0 means 256 in the one-byte field
    entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
    blobs += png
out = os.path.join(folder, "kosmicpdf.ico")
with open(out, "wb") as f:
    f.write(header + entries + blobs)
print(f"wrote {out} ({len(header) + len(entries) + len(blobs)} bytes, {len(SIZES)} sizes)")
