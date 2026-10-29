#!/bin/sh
# Copy the Flatpak repository that tools/flatpak_publish.sh built and tested to a
# server, so Flatpak can install and update Kosmic PDF from it:
#
#   tools/flatpak_deploy.sh dev          https://darmok.link/flatpak/  (try a build first)
#   tools/flatpak_deploy.sh production   https://kosmos.law/flatpak/
#
# The same signed build goes to each, unchanged, so what was tried on dev is
# exactly what users get. A release: flatpak_publish.sh, then deploy to dev and
# check it (flatpak update), then deploy to production. The landing page needs no
# change; it links to <url>/kosmicpdf.flatpakref, which stays put.
#
# The build files go first and the repository's index (summary, refs) last, so
# anyone updating while it copies never sees an index that names files that
# haven't arrived. Each server gets install files carrying its own address.
set -eu

root="$(dirname "$(dirname "$(readlink -f "$0")")")"
cache="${KOSMICPDF_FLATPAK_CACHE:-$HOME/.cache/kosmicpdf-flatpak}"
keydir="${KOSMICPDF_SIGNING_DIR:-$HOME/.local/share/kosmicpdf-signing}"
app=law.kosmos.KosmicPDF
branch=stable

case "${1:-}" in
    dev)        host=dev;              dir=/home/james/kosmos-flatpak; url=https://darmok.link/flatpak ;;
    production) host=james@kosmos.law; dir=/www/kosmos-flatpak;        url=https://kosmos.law/flatpak ;;
    *) echo "Usage: $0 dev|production"; exit 2 ;;
esac

site="$cache/site"
[ -f "$site/repo/summary" ] || { echo "Nothing to deploy: run tools/flatpak_publish.sh first."; exit 1; }
version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/kosmicpdf/__init__.py")"

# The install files, written for this server's address.
extra="$(mktemp -d)"
trap 'rm -rf "$extra"' EXIT
gpgkey="$(base64 -w0 "$keydir/public.gpg")"
cp "$root/kosmicpdf/icons/app/kosmicpdf.svg" "$extra/kosmicpdf.svg"
cat > "$extra/kosmicpdf.flatpakref" <<EOF
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
cat > "$extra/kosmos.flatpakrepo" <<EOF
[Flatpak Repo]
Title=Kosmos
Comment=Apps from Kosmos
Url=$url/repo/
Homepage=https://kosmos.law/
Icon=$url/kosmicpdf.svg
GPGKey=$gpgkey
EOF
# For the landing page, if it wants to show the current version.
printf '{"app": "%s", "version": "%s", "date": "%s"}\n' "$app" "$version" "$(date -u +%Y-%m-%d)" > "$extra/latest.json"

echo "==> Deploying Kosmic PDF $version to $1 ($host:$dir, $url)"
ssh "$host" "mkdir -p '$dir/repo'"
index="--exclude=/summary* --exclude=/summaries/ --exclude=/refs/ --exclude=/delta-indexes/ --exclude=/config"
work="--exclude=/tmp/ --exclude=/state/"
# Readable by the web server, whatever the permissions are here (the temporary folder is private).
perms="--chmod=D755,F644"
# shellcheck disable=SC2086
rsync -a $perms $work $index "$site/repo/" "$host:$dir/repo/"          # the new build's files
# shellcheck disable=SC2086
rsync -a $perms --delete $work "$site/repo/" "$host:$dir/repo/"        # then the index; prune what's gone
rsync -a $perms "$extra/" "$host:$dir/"

echo "==> Checking $url"
curl -fsS -o /dev/null "$url/repo/summary" && curl -fsS -o /dev/null "$url/kosmicpdf.flatpakref" \
    || { echo "The files are on the server, but $url doesn't serve them yet (see packaging/flatpak/README.md)."; exit 1; }
echo "==> Kosmic PDF $version is on $1. Install:  flatpak install --user $url/kosmicpdf.flatpakref"
