#!/bin/sh
# Kosmic PDF launcher inside the Flatpak.
export PYTHONPATH="/app/share/kosmicpdf${PYTHONPATH:+:$PYTHONPATH}"
# -P: never import from the folder the app happens to be started in.
exec python3 -P -m kosmicpdf "$@"
