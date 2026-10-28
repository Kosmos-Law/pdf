#!/bin/sh
# Add PDF Desk to the Menu with its icon (for the current user only).
# It does not change which app opens PDFs by default.
here="$(dirname "$(readlink -f "$0")")"
icons="$HOME/.local/share/icons/hicolor"
for s in 16 24 32 48 64 128 256; do
    install -Dm644 "$here/pdfdesk/icons/app/pdfdesk-$s.png" "$icons/${s}x${s}/apps/pdfdesk.png"
done
install -Dm644 "$here/pdfdesk/icons/app/pdfdesk.svg" "$icons/scalable/apps/pdfdesk.svg"
sed "s|^Exec=.*|Exec=$here/pdfdesk.sh %F|" "$here/pdfdesk.desktop" > "$HOME/.local/share/applications/pdfdesk.desktop"
gtk-update-icon-cache -q -t "$icons" 2>/dev/null || true
update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true
echo "PDF Desk added to the Menu."
