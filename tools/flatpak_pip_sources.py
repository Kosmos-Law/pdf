"""Generate packaging/flatpak/python-deps.json: the Python wheels the Flatpak installs.

Flatpak builds have no network access, so every wheel is listed with its URL and
sha256. pip resolves the set for the runtime's Python (see PYTHON below): our
pinned requirements.txt, plus OCRmyPDF and its dependencies (in the Flatpak,
OCR can't use the system's copy). Re-run after changing requirements.txt or
OCRMYPDF, and commit the result.

Run: .venv/bin/python tools/flatpak_pip_sources.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "packaging", "flatpak", "python-deps.json")
PYTHON = "3.13"                    # Python in org.freedesktop.Platform 25.08
OCRMYPDF = "ocrmypdf==17.13.0"
PLATFORMS = ["manylinux_2_39_x86_64", "manylinux_2_34_x86_64", "manylinux_2_28_x86_64",
             "manylinux_2_17_x86_64", "manylinux2014_x86_64"]


def resolve(args):
    """Ask pip (dry run) which wheels it would install, for the runtime's platform."""
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        cmd = [sys.executable, "-m", "pip", "install", "-q", "--dry-run", "--ignore-installed",
               "--only-binary=:all:", "--python-version", PYTHON, "--implementation", "cp",
               "--target", os.path.join(tmp, "t"), "--report", report]
        for p in PLATFORMS:
            cmd += ["--platform", p]
        subprocess.run(cmd + args, check=True)
        return json.load(open(report))["install"]


def main():
    # requirements.txt is the complete app set (installed --no-deps, as in install.sh);
    # OCRmyPDF brings its own dependency tree.
    wheels = resolve(["--no-deps", "-r", os.path.join(ROOT, "requirements.txt")]) + resolve([OCRMYPDF])
    sources, seen = [], set()
    for w in wheels:
        info = w["download_info"]
        url = info["url"]
        if url in seen:
            continue
        seen.add(url)
        sha = info["archive_info"]["hashes"]["sha256"]
        sources.append({"type": "file", "url": url, "sha256": sha})
    module = {
        "name": "python-deps",
        "buildsystem": "simple",
        "build-commands": [
            "pip3 install --no-index --no-deps --no-build-isolation --prefix=${FLATPAK_DEST} *.whl"
        ],
        "sources": sources,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(module, f, indent=2)
        f.write("\n")
    print(f"wrote {OUT}: {len(sources)} wheels")


if __name__ == "__main__":
    main()
