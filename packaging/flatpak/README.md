# Kosmos PDF as a Flatpak

Kosmos PDF is published as a Flatpak from our own signed repository, so people
can install it from kosmos.law and receive updates automatically through their
software updater, without a Flathub listing.

## For users

Open **https://kosmos.law/flatpak/kosmospdf.flatpakref** (Mint's Software Manager
handles it), or run:

    flatpak install --user https://kosmos.law/flatpak/kosmospdf.flatpakref

This installs the app and subscribes to the Kosmos repository, so updates arrive
with other system updates. If it's your first per-user Flatpak app and it doesn't
appear in the Menu, restart Cinnamon (Ctrl+Alt+Esc) or log out and back in once. The Flatpak includes OCR (Tesseract, English) and PDF/A
conversion (OCRmyPDF, Ghostscript); nothing else needs installing.

If the app looks plain rather than matching the desktop theme, install the
Flatpak copy of the theme, e.g. for Mint-Y-Aqua:

    flatpak install flathub org.gtk.Gtk3theme.Mint-Y-Aqua

(Sandboxed apps can't see themes installed in `/usr/share/themes`. In dark mode
without the theme, Kosmos PDF falls back to a dark Kosmos palette.)

## Publishing a release

1. Bump `__version__` in `kosmospdf/__init__.py` and add a `<release>` entry to
   `law.kosmos.KosmosPDF.metainfo.xml`. If `requirements.txt` changed, run
   `.venv/bin/python tools/flatpak_pip_sources.py` to refresh `python-deps.json`.
2. Run `tools/flatpak_publish.sh`. It builds at low priority, adds the build to the
   signed repository and refreshes the `.flatpakref`/`.flatpakrepo` files in
   `~/.cache/kosmospdf-flatpak/site/`. The first build compiles the OCR engine and
   Ghostscript (about 15 minutes); later builds reuse them (about 2 minutes).
3. `tools/flatpak_deploy.sh dev` copies that build to the dev server
   (https://darmok.link/flatpak/). To try it there before it reaches users:
   `flatpak install --user https://darmok.link/flatpak/kosmospdf.flatpakref` on a
   machine that doesn't have the production copy (the two can't be installed side
   by side). James's own copy follows production, like everyone else's, so he sees
   each release exactly as users do, one step later.
4. `tools/flatpak_deploy.sh production` copies the **same** build, unchanged, to
   https://kosmos.law/flatpak/, and users' copies update from it on their own.

The landing page needs no change for a release: it links to
`kosmos.law/flatpak/kosmospdf.flatpakref`, which stays put. (`latest.json` beside
it gives the current version and date, if a page wants to show them.) The deploy
script copies the build's files before the repository index, so anyone updating
meanwhile never sees an index naming files that haven't arrived, and it keeps the
older builds the index still lists (the publish script prunes beyond five).

### The rename from Kosmic PDF

Up to 0.3.7 the app was Kosmic PDF, published as `law.kosmos.KosmicPDF`. The first
publish after the rename marks that old app (and its Debug extension) end-of-life,
replaced by `law.kosmos.KosmosPDF`; later publishes see the mark and leave it. Once
that build is deployed, `flatpak update` tells each user that the old app is replaced
and offers to switch; on accepting, Flatpak installs Kosmos PDF, moves the app's data
(`~/.var/app/law.kosmos.KosmicPDF`) to the new ID, and removes the old one. The app
itself then copies its settings from the old name. The desktop file's
`X-Flatpak-RenamedFrom` keeps a default-app choice or panel pin pointing at it.

The repository and signing key stay where they were, in `~/.cache/kosmicpdf-flatpak`
and `~/.local/share/kosmicpdf-signing`: the scripts use the old folder names until
folders with the new names exist. Don't start a fresh repository for the new name, as
deploying it would drop the old app from the server instead of handing users over. The
deploy also still writes `kosmicpdf.flatpakref`, installing Kosmos PDF, for old links.

Where the files live (set up 2026-10-29):

- dev: `/home/james/kosmos-flatpak` on `dev`, served by the `darmok.link` site
  (`/etc/nginx/sites-available/dev-server`, `location /flatpak/`, outside the
  devauth gate since Flatpak can't sign in).
- production: `/www/kosmos-flatpak` on `kosmos.law`, served beside the landing
  page like `/docs` (`/etc/nginx/sites-available/kosmos-landing.conf`).

Before finishing, the script installs the new build into a throwaway installation
and runs the full test suite on the user runtime; if anything fails it stops and
says not to upload. (Testing with `flatpak-builder --run` isn't enough: it uses the
much larger SDK, which once hid a missing library that stopped the app starting.)

To test-launch the app by hand without touching your own recent files, pass
`--env=KOSMOSPDF_SETTINGS_DIR=/some/scratch/dir` to `flatpak run`. (Flatpak always
sets `XDG_CONFIG_HOME` itself, so overriding that has no effect.)

Requirements: `flatpak-builder` (`sudo apt install flatpak-builder`). The build
SDK is downloaded into a private Flatpak installation under
`~/.cache/kosmospdf-flatpak`, leaving the user's own installation alone.

To have an installed copy follow dev instead of production (or back again), point
its remote at the other repository; both are signed by the same key:
`flatpak remote-modify --user --url=https://darmok.link/flatpak/repo/ <remote>`,
where `<remote>` is the name `flatpak info --user law.kosmos.KosmosPDF` shows as
Origin (usually `kosmos` or `kosmospdf-origin`).

## The signing key

Every release and the repository index are signed by the "Kosmos Flatpak
Repository" key (`E493 0174 D589 BFE5 8737  68C6 C90A F7C0 5AF5 4E87`). Users'
machines reject anything not signed by it.

- The **private** key is in `~/.local/share/kosmospdf-signing` (not in git). Back
  it up somewhere safe and private. Losing it means users must re-add the
  repository; anyone holding it can sign updates for every user.
- The **public** key is `kosmos-repo.gpg` here, and is embedded in the
  `.flatpakref` and `.flatpakrepo` files.

## Files

- `law.kosmos.KosmosPDF.yml`: the build recipe
- `python-deps.json`: Python wheels (generated; don't edit by hand)
- `law.kosmos.KosmosPDF.metainfo.xml`: description and release notes for software centres
- `kosmospdf-launcher.sh`: the `kosmospdf` command inside the sandbox
