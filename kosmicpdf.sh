#!/bin/sh
# Launcher for Kosmic PDF; runs from the project's own virtualenv.
here="$(dirname "$(readlink -f "$0")")"
# Run as kosmicpdf-dev (see ./install.sh --dev), it's the development copy.
case "$(basename "$0")" in kosmicpdf-dev) set -- --dev "$@" ;; esac
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec "$here/.venv/bin/python" -m kosmicpdf "$@"
