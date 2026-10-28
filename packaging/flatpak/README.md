# Kosmic PDF as a Flatpak

Kosmic PDF is published as a Flatpak from our own signed repository, so people
can install it from kosmos.law and receive updates automatically through their
software updater, without a Flathub listing.

## For users

Open **https://kosmos.law/flatpak/kosmicpdf.flatpakref** (Mint's Software Manager
handles it), or run:

    flatpak install --user https://kosmos.law/flatpak/kosmicpdf.flatpakref

This installs the app and subscribes to the Kosmos repository, so updates arrive
with other system updates. If it's your first per-user Flatpak app and it doesn't
appear in the Menu, restart Cinnamon (Ctrl+Alt+Esc) or log out and back in once. The Flatpak includes OCR (Tesseract, English) and PDF/A
conversion (OCRmyPDF, Ghostscript); nothing else needs installing.

If the app looks plain rather than matching the desktop theme, install the
Flatpak copy of the theme, e.g. for Mint-Y-Aqua:

    flatpak install flathub org.gtk.Gtk3theme.Mint-Y-Aqua

(Sandboxed apps can't see themes installed in `/usr/share/themes`. In dark mode
without the theme, Kosmic PDF falls back to a dark Kosmos palette.)

## Publishing a release

1. Bump `__version__` in `kosmicpdf/__init__.py` and add a `<release>` entry to
   `law.kosmos.KosmicPDF.metainfo.xml`. If `requirements.txt` changed, run
   `.venv/bin/python tools/flatpak_pip_sources.py` to refresh `python-deps.json`.
2. Run `tools/flatpak_publish.sh`. It builds at low priority, adds the build to the
   signed repository and refreshes the `.flatpakref`/`.flatpakrepo` files in
   `~/.cache/kosmicpdf-flatpak/site/`. The first build compiles the OCR engine and
   Ghostscript (about 15 minutes); later builds reuse them (about 2 minutes).
3. Upload the **whole** `site/` folder to `https://kosmos.law/flatpak/`, keeping
   the existing `repo/` contents (it holds the release history users update from).
   Use `--url` if hosting somewhere else.

Before finishing, the script installs the new build into a throwaway installation
and runs the full test suite on the user runtime; if anything fails it stops and
says not to upload. (Testing with `flatpak-builder --run` isn't enough: it uses the
much larger SDK, which once hid a missing library that stopped the app starting.)

To test-launch the app by hand without touching your own recent files, pass
`--env=KOSMICPDF_SETTINGS_DIR=/some/scratch/dir` to `flatpak run`. (Flatpak always
sets `XDG_CONFIG_HOME` itself, so overriding that has no effect.)

Requirements: `flatpak-builder` (`sudo apt install flatpak-builder`). The build
SDK is downloaded into a private Flatpak installation under
`~/.cache/kosmicpdf-flatpak`, leaving the user's own installation alone.

## The signing key

Every release and the repository index are signed by the "Kosmos Flatpak
Repository" key (`E493 0174 D589 BFE5 8737  68C6 C90A F7C0 5AF5 4E87`). Users'
machines reject anything not signed by it.

- The **private** key is in `~/.local/share/kosmicpdf-signing` (not in git). Back
  it up somewhere safe and private. Losing it means users must re-add the
  repository; anyone holding it can sign updates for every user.
- The **public** key is `kosmos-repo.gpg` here, and is embedded in the
  `.flatpakref` and `.flatpakrepo` files.

## Files

- `law.kosmos.KosmicPDF.yml`: the build recipe
- `python-deps.json`: Python wheels (generated; don't edit by hand)
- `law.kosmos.KosmicPDF.metainfo.xml`: description and release notes for software centres
- `kosmicpdf-launcher.sh`: the `kosmicpdf` command inside the sandbox
