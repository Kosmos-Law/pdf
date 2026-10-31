# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the Windows build: one folder (dist/KosmicPDF) holding
# KosmicPDF.exe, ocrmypdf.exe (OCRmyPDF frozen with its Python dependencies), their
# shared libraries under _internal, and Tesseract and Ghostscript under tools/, staged
# there by the workflow. Run from the repository root:
#
#     pyinstaller --noconfirm packaging/windows/kosmicpdf.spec
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
icon = os.path.join(root, "kosmicpdf", "icons", "app", "kosmicpdf.ico")
tools = os.path.join(SPECPATH, "tools")

# Qt modules the app never imports; PySide6_Essentials ships them and the hooks would
# otherwise pick up some of their libraries.
unused_qt = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
             "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtXml",
             "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtPrintSupport", "PySide6.QtDesigner",
             "PySide6.QtHelp", "PySide6.QtUiTools"]

app = Analysis(
    [os.path.join(SPECPATH, "kosmicpdf_entry.py")],
    pathex=[root],
    datas=[(os.path.join(root, "kosmicpdf", "icons"), os.path.join("kosmicpdf", "icons"))],
    # QtTest is only for the self-test (see kosmicpdf_entry.py); it is small.
    hiddenimports=["PySide6.QtTest"],
    excludes=["tkinter", "_tkinter"] + unused_qt,
    noarchive=False,
)
app_pyz = PYZ(app.pure)
app_exe = EXE(
    app_pyz, app.scripts, [],
    exclude_binaries=True,
    name="KosmicPDF",
    icon=icon,
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)

# OCRmyPDF finds its plugins by name and its version through the package metadata, which
# PyInstaller's analysis can't see; pdfminer.six and pikepdf read their versions the
# same way.
ocr = Analysis(
    [os.path.join(SPECPATH, "ocrmypdf_entry.py")],
    pathex=[root],
    datas=(collect_data_files("ocrmypdf") + copy_metadata("ocrmypdf") + copy_metadata("pikepdf")
           + copy_metadata("img2pdf") + copy_metadata("pdfminer.six") + copy_metadata("pluggy")
           + copy_metadata("Pillow")),
    hiddenimports=collect_submodules("ocrmypdf") + collect_submodules("pikepdf"),
    excludes=["tkinter", "_tkinter", "PySide6", "shiboken6", "pymupdf"],
    noarchive=False,
)
ocr_pyz = PYZ(ocr.pure)
ocr_exe = EXE(
    ocr_pyz, ocr.scripts, [],
    exclude_binaries=True,
    name="ocrmypdf",
    console=True,
    upx=False,
)

extras = [Tree(tools, prefix="tools")] if os.path.isdir(tools) else []
COLLECT(
    app_exe, app.binaries, app.datas,
    ocr_exe, ocr.binaries, ocr.datas,
    *extras,
    name="KosmicPDF",
    upx=False,
)
