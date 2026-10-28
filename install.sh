#!/bin/sh
# Kosmic PDF installer, for the current user only.
#
#   ./install.sh               set up everything: Python environment, Menu entry,
#                              icon, and a `kosmicpdf` command
#   ./install.sh --default     the same, and make Kosmic PDF the default app for PDFs
#   ./install.sh --uninstall   remove the Menu entry, icon and command again
#                              (your settings and this folder are left alone)
#
# Safe to run again at any time, e.g. after `git pull`. Nothing needs root except
# the optional OCR tools, and the script asks before installing those.
set -eu

here="$(dirname "$(readlink -f "$0")")"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor"
bin="$HOME/.local/bin"
sizes="16 24 32 48 64 128 256"

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

refresh_menus() {
    gtk-update-icon-cache -q -t "$icons" 2>/dev/null || true
    update-desktop-database -q "$apps" 2>/dev/null || true
}

uninstall() {
    step "Removing Kosmic PDF from the Menu"
    # Ask before removing the entry: once it's gone, the system no longer reports it.
    was_default="$(xdg-mime query default application/pdf 2>/dev/null || true)"
    rm -f "$apps/kosmicpdf.desktop" "$icons/scalable/apps/kosmicpdf.svg"
    for s in $sizes; do rm -f "$icons/${s}x${s}/apps/kosmicpdf.png"; done
    if [ -L "$bin/kosmicpdf" ]; then rm -f "$bin/kosmicpdf"; fi
    refresh_menus
    if [ "$was_default" = "kosmicpdf.desktop" ]; then
        say "Kosmic PDF was your default PDF app; your system will now pick another."
    fi
    say "Done. Your settings (~/.config/kosmicpdf) and this folder were kept."
}

make_default=no
case "${1:-}" in
    --uninstall) uninstall; exit 0 ;;
    --default) make_default=yes ;;
    "") ;;
    *) say "Usage: $0 [--default | --uninstall]"; exit 2 ;;
esac

step "Checking Python"
if ! command -v python3 >/dev/null 2>&1; then
    say "Python 3 is needed:  sudo apt install python3 python3-venv"; exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    say "Python 3.10 or newer is needed (found $(python3 --version 2>&1))."; exit 1
fi
if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
    say "Python's venv module is needed:  sudo apt install python3-venv"; exit 1
fi
say "$(python3 --version) is fine."

step "Checking the OCR tools (used by OCR and Convert to PDF/A)"
missing=""
for tool in ocrmypdf tesseract gs; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done
if [ -z "$missing" ]; then
    say "OCRmyPDF, Tesseract and Ghostscript are installed."
else
    say "Not found:$missing"
    packages="ocrmypdf tesseract-ocr tesseract-ocr-eng ghostscript"
    answer=n
    if command -v apt-get >/dev/null 2>&1 && [ -t 0 ]; then
        printf 'Install them now with "sudo apt install %s"? [y/N] ' "$packages"
        read -r answer || answer=n
    fi
    case "$answer" in
        [Yy]*) sudo apt-get install -y $packages ;;
        *) say "Skipped. Everything else works; for OCR and PDF/A later, run:"
           say "    sudo apt install $packages" ;;
    esac
fi

step "Setting up the Python environment in .venv"
if ! "$here/.venv/bin/python" -c 'import sys' >/dev/null 2>&1; then
    rm -rf "$here/.venv"
    python3 -m venv "$here/.venv"
fi
"$here/.venv/bin/python" -m pip install -q --upgrade pip
# --no-deps: requirements.txt is the complete, tested list (see the note there).
"$here/.venv/bin/python" -m pip install -q --no-deps -r "$here/requirements.txt"
"$here/.venv/bin/python" -c 'import PySide6.QtWidgets, PySide6.QtSvg, pymupdf' \
    || { say "The Python libraries did not install correctly."; exit 1; }
say "Python libraries ready."

step "Adding Kosmic PDF to the Menu"
for s in $sizes; do
    install -Dm644 "$here/kosmicpdf/icons/app/kosmicpdf-$s.png" "$icons/${s}x${s}/apps/kosmicpdf.png"
done
install -Dm644 "$here/kosmicpdf/icons/app/kosmicpdf.svg" "$icons/scalable/apps/kosmicpdf.svg"
mkdir -p "$apps"
# The committed .desktop file is machine-neutral; point Exec at this folder.
sed "s|^Exec=.*|Exec=$here/kosmicpdf.sh %F|" "$here/kosmicpdf.desktop" > "$apps/kosmicpdf.desktop"
refresh_menus
mkdir -p "$bin"
ln -sfn "$here/kosmicpdf.sh" "$bin/kosmicpdf"
say "Menu entry, icon and the \`kosmicpdf\` command are installed."
case ":$PATH:" in
    *":$bin:"*) ;;
    *) say "(~/.local/bin is not on your PATH yet; it usually is after you next log in.)" ;;
esac

if [ "$make_default" = yes ]; then
    step "Making Kosmic PDF the default app for PDFs"
    xdg-mime default kosmicpdf.desktop application/pdf
    say "Done."
fi

step "Kosmic PDF is installed"
say "Open it from the Menu (Office), or run:  kosmicpdf [files...]"
if [ "$make_default" = no ]; then
    say "To make it your default PDF app:  ./install.sh --default"
fi
