#!/bin/sh
# Launcher for Kosmos PDF; runs from the project's own virtualenv.
here="$(dirname "$(readlink -f "$0")")"
# Run as kosmospdf-dev (see ./install.sh --dev), it's the development copy.
case "$(basename "$0")" in kosmospdf-dev) set -- --dev "$@" ;; esac
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec "$here/.venv/bin/python" -m kosmospdf "$@"
