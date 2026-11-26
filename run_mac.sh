#!/usr/bin/env bash
# Start PokerScribe (runs setup first if needed).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  ./setup_mac.sh
fi
exec .venv/bin/python -m app.main "$@"
