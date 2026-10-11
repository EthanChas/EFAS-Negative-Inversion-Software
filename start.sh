#!/bin/sh
# Starts EFAS from source on Linux or macOS.
# Run "./start.sh" to start it; errors and prints show in this terminal.
cd "$(dirname "$0")" || exit 1
PYTHONPATH="$(pwd)/src" exec python3 -m photoeditor "$@"
