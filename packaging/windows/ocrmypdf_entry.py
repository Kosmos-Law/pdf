"""Entry point of the ocrmypdf.exe that ships beside KosmicPDF.exe on Windows: the
OCRmyPDF command line, frozen with the app so users need not install Python.

OCRmyPDF runs Tesseract and Ghostscript as console programs. Started from a program
without a console (this one, launched by the app), each would open a console window of
its own, so they are started without one.
"""
import multiprocessing
import subprocess
import sys

multiprocessing.freeze_support()

if sys.platform == "win32":
    _popen_init = subprocess.Popen.__init__

    def _quiet_init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        _popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _quiet_init

from ocrmypdf.__main__ import run  # noqa: E402

sys.exit(run())
