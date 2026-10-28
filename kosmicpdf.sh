#!/bin/sh
# Launcher for Kosmic PDF; runs from the project's own virtualenv.
here="$(dirname "$(readlink -f "$0")")"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec "$here/.venv/bin/python" -m kosmicpdf "$@"
