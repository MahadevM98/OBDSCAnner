#!/usr/bin/env bash
# Launch the OBD-II scanner GUI.
cd "$(dirname "$0")" || exit 1
exec python3 obdscan.py "$@"
