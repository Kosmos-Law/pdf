#!/bin/sh
# Kosmic PDF installer, for the current user only.
#
#   ./install.sh               set up everything: Python environment, Menu entry,
#                              icon, and a `kosmicpdf` command
#   ./install.sh --default     the same, and make Kosmic PDF the default app for PDFs
#   ./install.sh --uninstall   remove the Menu entry, icon and command again
#                              (your settings and this folder are left alone)
#   ./install.sh --dev         a development copy instead: a "Kosmic PDF (Dev)" Menu
#                              entry with a grey icon and a `kosmicpdf-dev` command,
#                              running this folder's code as it stands. It runs
#                              alongside the installed app (e.g. the Flatpak) and is
#                              never made the default. Add --uninstall to remove it.
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
    step "Removing $label from the Menu"
    # Ask before removing the entry: once it's gone, the system no longer reports it.
    was_default="$(xdg-mime query default application/pdf 2>/dev/null || true)"
    rm -f "$apps/$id.desktop" "$icons/scalable/apps/$id.svg"
    for s in $sizes; do rm -f "$icons/${s}x${s}/apps/$id.png"; done
    if [ -L "$bin/$id" ]; then rm -f "$bin/$id"; fi
    refresh_menus
    if [ "$was_default" = "$id.desktop" ]; then
        say "$label was your default PDF app; your system will now pick another."
    fi
    say "Done. Your settings (~/.config/kosmicpdf) and this folder were kept."
}

action=install
make_default=no
dev=no
for arg in "$@"; do
    case "$arg" in
        --uninstall) action=uninstall ;;
        --default) make_default=yes ;;
        --dev) dev=yes ;;
        *) say "Usage: $0 [--default | --dev] [--uninstall]"; exit 2 ;;
    esac
done
if [ "$dev" = yes ]; then
    id=kosmicpdf-dev; label="Kosmic PDF (Dev)"; flag=" --dev"
    if [ "$make_default" = yes ]; then
        say "The development copy is never made the default PDF app; leave out --default."; exit 2
    fi
else
    id=kosmicpdf; label="Kosmic PDF"; flag=""
fi
if [ "$action" = uninstall ]; then uninstall; exit 0; fi

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

step "Adding $label to the Menu"
for s in $sizes; do
    install -Dm644 "$here/kosmicpdf/icons/app/$id-$s.png" "$icons/${s}x${s}/apps/$id.png"
done
install -Dm644 "$here/kosmicpdf/icons/app/$id.svg" "$icons/scalable/apps/$id.svg"
mkdir -p "$apps"
# The committed .desktop file is machine-neutral; point Exec at this folder.
sed -e "s|^Exec=.*|Exec=$here/kosmicpdf.sh$flag %F|" -e "s|^Name=.*|Name=$label|" -e "s|^Icon=.*|Icon=$id|" \
    "$here/kosmicpdf.desktop" > "$apps/$id.desktop"
refresh_menus
mkdir -p "$bin"
ln -sfn "$here/kosmicpdf.sh" "$bin/$id"
say "Menu entry, icon and the \`$id\` command are installed."
case ":$PATH:" in
    *":$bin:"*) ;;
    *) say "(~/.local/bin is not on your PATH yet; it usually is after you next log in.)" ;;
esac

if [ "$make_default" = yes ]; then
    step "Making Kosmic PDF the default app for PDFs"
    xdg-mime default kosmicpdf.desktop application/pdf
    say "Done."
fi

step "$label is installed"
say "Open it from the Menu (Office), or run:  $id [files...]"
if [ "$dev" = yes ]; then
    say "It runs this folder's code as it stands: edit, then reopen it to try the change."
elif [ "$make_default" = no ]; then
    say "To make it your default PDF app:  ./install.sh --default"
fi
