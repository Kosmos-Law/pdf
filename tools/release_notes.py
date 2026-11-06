#!/usr/bin/env python3
"""Print one version's release notes from the Flatpak metainfo as Markdown, for the
GitHub release the Windows workflow creates:

    python tools/release_notes.py 0.3.1
"""
import os
import sys
import xml.etree.ElementTree as ET

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tree = ET.parse(os.path.join(root, "packaging", "flatpak", "law.kosmos.KosmosPDF.metainfo.xml"))
version = sys.argv[1]
for rel in tree.iter("release"):
    if rel.get("version") == version:
        for el in rel.find("description"):
            if el.tag == "p":
                print(" ".join(el.text.split()), end="\n\n")
            elif el.tag == "ul":
                for li in el:
                    print("- " + " ".join(li.text.split()))
                print()
        break
else:
    sys.exit(f"no release {version} in the metainfo")
