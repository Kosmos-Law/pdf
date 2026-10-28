#!/bin/sh
# Build Kosmic PDF as a Flatpak and publish it to a signed repository, ready to
# upload to a web server.
#
#   tools/flatpak_publish.sh [--url https://kosmos.law/flatpak]
#
# Produces, in ~/.cache/kosmicpdf-flatpak/site/ (upload all of it to the URL):
#   repo/                    the signed Flatpak repository (static files)
#   kosmicpdf.flatpakref     "Install Kosmic PDF": opening it installs the app and
#                            subscribes to updates from this repository
#   kosmos.flatpakrepo       adds the Kosmos repository on its own
#   kosmicpdf.svg            icon referenced by the two files above
#
# Each run adds a new build to the existing repository, so users who installed
# from the .flatpakref get it as an update. Bump __version__ and add a <release>
# to the metainfo first.
#
# Needs flatpak-builder (sudo apt install flatpak-builder) and the signing key in
# ~/.local/share/kosmicpdf-signing (keep that folder backed up and private).
set -eu

root="$(dirname "$(dirname "$(readlink -f "$0")")")"
cache="${KOSMICPDF_FLATPAK_CACHE:-$HOME/.cache/kosmicpdf-flatpak}"
keydir="${KOSMICPDF_SIGNING_DIR:-$HOME/.local/share/kosmicpdf-signing}"
url="${KOSMICPDF_FLATPAK_URL:-https://kosmos.law/flatpak}"
app=law.kosmos.KosmicPDF
branch=stable
manifest="$root/packaging/flatpak/$app.yml"

while [ $# -gt 0 ]; do
    case "$1" in
        --url) url="${2%/}"; shift 2 ;;
        *) echo "Usage: $0 [--url BASE_URL]"; exit 2 ;;
    esac
done

[ -s "$keydir/key-id" ] || { echo "No signing key in $keydir"; exit 1; }
key="$(cat "$keydir/key-id")"
export GNUPGHOME="$keydir/gnupg"
site="$cache/site"
mkdir -p "$site"

# Build tools (the SDK) live in a private Flatpak installation, so building
# doesn't add runtimes to the user's own installation.
export FLATPAK_USER_DIR="$cache/installation"
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo

echo "==> Building $app and adding it to $site/repo"
# Lowest CPU and disk priority, so compiling the OCR engine (first build only;
# later builds reuse the cached modules) doesn't make the desktop sluggish.
nice -n 19 ionice -c 3 flatpak-builder --user --install-deps-from=flathub --force-clean --state-dir="$cache/state" \
    --default-branch="$branch" --repo="$site/repo" --gpg-sign="$key" --gpg-homedir="$GNUPGHOME" \
    "$cache/build-dir" "$manifest"

echo "==> Signing the repository index"
flatpak build-update-repo --generate-static-deltas --prune --prune-depth=5 \
    --title="Kosmos" --default-branch="$branch" \
    --gpg-sign="$key" --gpg-homedir="$GNUPGHOME" "$site/repo"

gpgkey="$(base64 -w0 "$keydir/public.gpg")"
cp "$root/kosmicpdf/icons/app/kosmicpdf.svg" "$site/kosmicpdf.svg"
cat > "$site/kosmicpdf.flatpakref" <<EOF
[Flatpak Ref]
Name=$app
Branch=$branch
Title=Kosmic PDF
Comment=View, organise, annotate and redact PDFs
Url=$url/repo/
SuggestRemoteName=kosmos
Homepage=https://kosmos.law/
Icon=$url/kosmicpdf.svg
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
IsRuntime=false
GPGKey=$gpgkey
EOF
cat > "$site/kosmos.flatpakrepo" <<EOF
[Flatpak Repo]
Title=Kosmos
Comment=Apps from Kosmos
Url=$url/repo/
Homepage=https://kosmos.law/
Icon=$url/kosmicpdf.svg
GPGKey=$gpgkey
EOF

echo "==> Published. Upload the contents of $site to $url/"
echo "    Users install with:  flatpak install --user $url/kosmicpdf.flatpakref"
echo "    (or by opening kosmicpdf.flatpakref from the web page)"
