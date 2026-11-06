#!/bin/sh
# Build Kosmos PDF as a Flatpak and publish it to a signed repository, ready to
# upload to a web server.
#
#   tools/flatpak_publish.sh [--url https://kosmos.law/flatpak]
#
# Produces, in ~/.cache/kosmospdf-flatpak/site/ (tools/flatpak_deploy.sh copies it to the servers):
#   repo/                    the signed Flatpak repository (static files)
#   kosmospdf.flatpakref     "Install Kosmos PDF": opening it installs the app and
#                            subscribes to updates from this repository
#   kosmos.flatpakrepo       adds the Kosmos repository on its own
#   kosmospdf.svg            icon referenced by the two files above
#   kosmicpdf.flatpakref     the same as kosmospdf.flatpakref, under the app's former
#                            name, so links to it from before the rename still work
#
# Each run adds a new build to the existing repository, so users who installed
# from the .flatpakref get it as an update. Bump __version__ and add a <release>
# to the metainfo first.
#
# Needs flatpak-builder (sudo apt install flatpak-builder) and the signing key in
# ~/.local/share/kosmospdf-signing (keep that folder backed up and private).
set -eu

root="$(dirname "$(dirname "$(readlink -f "$0")")")"
# Kosmos PDF was called Kosmic PDF, and these folders may still have the old name. Use
# them as they are: the repository must stay the same one, since it holds the old app
# (law.kosmos.KosmicPDF) too, which users are moved on from (see below).
pick() { if [ -e "$1" ] || [ ! -e "$2" ]; then echo "$1"; else echo "$2"; fi; }
cache="${KOSMOSPDF_FLATPAK_CACHE:-$(pick "$HOME/.cache/kosmospdf-flatpak" "$HOME/.cache/kosmicpdf-flatpak")}"
keydir="${KOSMOSPDF_SIGNING_DIR:-$(pick "$HOME/.local/share/kosmospdf-signing" "$HOME/.local/share/kosmicpdf-signing")}"
url="${KOSMOSPDF_FLATPAK_URL:-https://kosmos.law/flatpak}"
app=law.kosmos.KosmosPDF
old_app=law.kosmos.KosmicPDF     # its ID until 0.3.7, as Kosmic PDF
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
# --disable-rofiles-fuse: copy cached files rather than mount them, which needs FUSE and
# isn't allowed everywhere (a sandboxed shell, some containers); the result is the same.
nice -n 19 ionice -c 3 flatpak-builder --user --install-deps-from=flathub --force-clean --state-dir="$cache/state" \
    --disable-rofiles-fuse \
    --default-branch="$branch" --repo="$site/repo" --gpg-sign="$key" --gpg-homedir="$GNUPGHOME" \
    "$cache/build-dir" "$manifest"

# The app was published as law.kosmos.KosmicPDF until 0.3.7. Mark the old app and its
# Debug extension end-of-life, replaced by the new ID: "flatpak update" then offers each
# user the switch to Kosmos PDF, and Flatpak moves their data (~/.var/app) across.
# Done once; a ref already marked is left alone.
for ref in "app/$old_app/x86_64/$branch" "runtime/$old_app.Debug/x86_64/$branch"; do
    ostree --repo="$site/repo" rev-parse "$ref" >/dev/null 2>&1 || continue
    if ostree --repo="$site/repo" show --print-metadata-key=ostree.endoflife-rebase "$ref" >/dev/null 2>&1; then
        continue
    fi
    echo "==> Marking $ref as replaced by $app"
    flatpak build-commit-from --src-ref="$ref" --end-of-life-rebase="$old_app=$app" \
        --gpg-sign="$key" --gpg-homedir="$GNUPGHOME" "$site/repo" "$ref"
done

echo "==> Signing the repository index"
flatpak build-update-repo --generate-static-deltas --prune --prune-depth=5 \
    --title="Kosmos" --default-branch="$branch" \
    --gpg-sign="$key" --gpg-homedir="$GNUPGHOME" "$site/repo"

gpgkey="$(base64 -w0 "$keydir/public.gpg")"
cp "$root/kosmospdf/icons/app/kosmospdf.svg" "$site/kosmospdf.svg"
cat > "$site/kosmospdf.flatpakref" <<EOF
[Flatpak Ref]
Name=$app
Branch=$branch
Title=Kosmos PDF
Comment=View, organise, annotate and redact PDFs
Url=$url/repo/
SuggestRemoteName=kosmos
Homepage=https://kosmos.law/
Icon=$url/kosmospdf.svg
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
IsRuntime=false
GPGKey=$gpgkey
EOF
# Under the former name too, so old links install Kosmos PDF.
cp "$site/kosmospdf.flatpakref" "$site/kosmicpdf.flatpakref"
cat > "$site/kosmos.flatpakrepo" <<EOF
[Flatpak Repo]
Title=Kosmos
Comment=Apps from Kosmos
Url=$url/repo/
Homepage=https://kosmos.law/
Icon=$url/kosmospdf.svg
GPGKey=$gpgkey
EOF

# Test what users will actually get: install from the signed repository into a
# throwaway installation and run the test suite on the user runtime. (Testing
# with flatpak-builder --run uses the much larger SDK, which can hide missing
# libraries.)
echo "==> Testing the published build as users will run it"
test_inst="$cache/test-install"
rm -rf "$test_inst" "$cache/test-results"
FLATPAK_USER_DIR="$test_inst" flatpak remote-add --user --gpg-import="$keydir/public.gpg" kosmos-test "file://$site/repo/"
FLATPAK_USER_DIR="$test_inst" flatpak install --user -y --noninteractive kosmos-test "$app" >/dev/null
if ! FLATPAK_USER_DIR="$test_inst" nice -n 19 flatpak run --env=QT_QPA_PLATFORM=offscreen \
        --env=KOSMOSPDF_TEST_INSTALLED=1 --env=PYTHONPATH=/app/share/kosmospdf --command=python3 \
        "$app" -P "$root/tests/smoke.py" "$cache/test-results" > "$cache/test-results.log" 2>&1; then
    grep -E "^FAIL|Traceback|Error" "$cache/test-results.log" | head -20
    echo "Tests FAILED in the published build (log: $cache/test-results.log). Do not upload."
    exit 1
fi
tail -1 "$cache/test-results.log"
rm -rf "$test_inst"

echo "==> Built and tested. Next: tools/flatpak_deploy.sh dev, try it, then tools/flatpak_deploy.sh production"
