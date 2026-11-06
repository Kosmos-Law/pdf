#!/bin/sh
# Kosmos PDF launcher inside the Flatpak.
export PYTHONPATH="/app/share/kosmospdf${PYTHONPATH:+:$PYTHONPATH}"
# -P: never import from the folder the app happens to be started in.
exec python3 -P -m kosmospdf "$@"
