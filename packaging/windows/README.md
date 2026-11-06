# Kosmos PDF on Windows

The Windows build is a folder made by PyInstaller, wrapped in an Inno Setup installer,
and it includes OCR and PDF/A conversion: OCRmyPDF (frozen as `ocrmypdf.exe` beside the
app), Tesseract and Ghostscript. Nothing else needs installing.

## For users

Download **KosmosPDF-Setup.exe** from https://kosmos.law/pdf/ (or from the
[releases](https://github.com/Kosmos-Law/pdf/releases) on GitHub) and run it. It
installs for the current user, without an administrator password, and adds Kosmos PDF
to the Start menu and to the "Open with" choices for PDFs and images. To make it the
default for PDFs, pick it under Settings > Apps > Default apps.

The installer shows the terms of use (`kosmospdf/terms.txt`: no warranty, use at your
own risk) and installs only once they are accepted; the program shows them again at its
first start (on every system, not only Windows) and runs only once "I agree" is chosen.
The answer is kept in the settings under `terms/accepted` with the
date in `dialogs.TERMS_VERSION`; change that date when the terms change materially, and
everyone is asked again.

The installer isn't code-signed, so Windows shows its "unrecognised app" warning the
first time: choose *More info*, then *Run anyway*. Updates are a matter of running a
newer installer over the old one; the app doesn't update itself.

## How it is built

GitHub Actions builds it (`.github/workflows/windows.yml`) on a Windows runner, since
PyInstaller only builds for the system it runs on:

1. `packaging/windows/fetch_tools.ps1` downloads the Tesseract (UB Mannheim build) and
   Ghostscript installers, checks their checksums, runs them silently and keeps the
   pieces OCRmyPDF needs under `packaging/windows/tools/`.
2. The test suite runs headless in the Python environment, as on Linux.
3. `pyinstaller packaging/windows/kosmospdf.spec` freezes `KosmosPDF.exe` and
   `ocrmypdf.exe` into one folder, `dist/KosmosPDF`, with the tools under `tools/`.
   `kosmospdf_entry.py` and `ocrmypdf_entry.py` are the two programs' entry points.
4. The test suite runs again *inside* `KosmosPDF.exe` (`KOSMOSPDF_SELFTEST`, see
   `kosmospdf_entry.py`), so what is tested is what ships.
5. Inno Setup (`kosmospdf.iss`) makes `dist/KosmosPDF-Setup-<version>.exe`.

Every push to `main` builds and tests, leaving the installer as a workflow artifact. A
version tag publishes a GitHub release with the installer attached, under its versioned
name and as `KosmosPDF-Setup.exe`, so the link
https://github.com/Kosmos-Law/pdf/releases/latest/download/KosmosPDF-Setup.exe always
gives the newest; kosmos.law links there. It is attached as `KosmicPDF-Setup.exe` too,
the name from before the rename, so older links still work.

The app was Kosmic PDF until 0.3.7. The installer keeps the same AppId, so it upgrades
a Kosmic PDF installation in place: it installs into a "Kosmos PDF" folder, removes the
old folder, shortcuts and Default apps entry, and leaves the old document type
(`KosmicPDF.Document`) opening the new program, so a choice of it as the PDF app still
holds. Settings are copied from the old registry key by the app at its first start.

## Publishing a release

1. Bump `__version__` and add the `<release>` to the Flatpak metainfo as usual
   (`packaging/flatpak/README.md`); the GitHub release's notes are taken from there
   (`tools/release_notes.py`).
2. Commit, then tag and push:

       git tag v0.3.1
       git push origin main v0.3.1

   The workflow refuses a tag that doesn't match `__version__`.
3. Watch https://github.com/Kosmos-Law/pdf/actions. About ten minutes later the release
   is at https://github.com/Kosmos-Law/pdf/releases.

## What differs from Linux

Everything in `kosmospdf/` runs unchanged except these, each gated on `sys.platform`:

- The single-instance handoff (`app.py`): Windows has no Unix sockets, so the running
  copy listens on a loopback TCP port and leaves a note of it (port, a secret, its
  process id) in `%LOCALAPPDATA%\kosmospdf\instance.json`. A later launch reads the
  note, allows the running copy to take the foreground, sends the files with the
  secret, and waits for "ok", so a stale note can't send files to some other program.
- Console programs (Tesseract, Ghostscript, OCRmyPDF) are started without a console
  window, and OCRmyPDF with `--use-threads` so it doesn't start worker processes that
  would each open one.
- The icon cache lives under `%LOCALAPPDATA%` rather than `~/.cache`, and test runs
  keep their settings in files, not the registry.
- `add_bundled_tools()` in `app.py` puts the bundled tools on `PATH` when the app is
  frozen.

The X11 helpers do nothing without a `DISPLAY`, and Qt handles light and dark mode on
Windows itself.
