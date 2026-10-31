"""Entry point of the Windows build (KosmicPDF.exe); see kosmicpdf.spec.

With KOSMICPDF_SELFTEST set to a script's path, runs that script inside the built app
instead, so the test suite can check the very files users get (as the Flatpak build
does with its installed copy). The script's output goes to KOSMICPDF_SELFTEST_LOG, since
a windowed program has no console; so does any error on the way, since a windowed
program would otherwise report it in a dialog that nobody is there to close.
"""
import multiprocessing
import os
import sys
import traceback

multiprocessing.freeze_support()

test = os.environ.get("KOSMICPDF_SELFTEST")
if test:
    log = open(os.environ.get("KOSMICPDF_SELFTEST_LOG") or (test + ".log"), "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    sys.argv = [test] + sys.argv[1:]
    try:
        from kosmicpdf.app import add_bundled_tools
        add_bundled_tools()
        print("self-test in", sys.executable, "PATH", os.environ["PATH"][:300])
        with open(test, encoding="utf-8") as f:
            code = compile(f.read(), test, "exec")
        exec(code, {"__name__": "__main__", "__file__": test})
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        sys.exit(2)
    sys.exit(0)

from kosmicpdf.app import main  # noqa: E402

sys.exit(main())
