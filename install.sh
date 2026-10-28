#!/bin/sh
# Add Kosmic PDF to the Menu with its icon (for the current user only).
# It does not change which app opens PDFs by default. Exec is filled in with
# this folder's path, so the committed .desktop file stays machine-neutral.
here="$(dirname "$(readlink -f "$0")")"
icons="$HOME/.local/share/icons/hicolor"
for s in 16 24 32 48 64 128 256; do
    install -Dm644 "$here/kosmicpdf/icons/app/kosmicpdf-$s.png" "$icons/${s}x${s}/apps/kosmicpdf.png"
done
install -Dm644 "$here/kosmicpdf/icons/app/kosmicpdf.svg" "$icons/scalable/apps/kosmicpdf.svg"
sed "s|^Exec=.*|Exec=$here/kosmicpdf.sh %F|" "$here/kosmicpdf.desktop" > "$HOME/.local/share/applications/kosmicpdf.desktop"
gtk-update-icon-cache -q -t "$icons" 2>/dev/null || true
update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true
echo "Kosmic PDF added to the Menu."
