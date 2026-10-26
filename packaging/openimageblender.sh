#!/bin/sh
# Runs and outputs live in the user's data dir, code in /usr/lib.
DATA="$HOME/.local/share/openimageblender"
mkdir -p "$DATA/runs" "$DATA/outputs" "$DATA/inputs"
cd "$DATA" || exit 1
PYTHONPATH=/usr/lib/openimageblender exec python3 -m src.app "$@"
