#!/bin/sh
# Kosmic PDF launcher inside the Flatpak.
export PYTHONPATH="/app/share/kosmicpdf${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m kosmicpdf "$@"
