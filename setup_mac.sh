#!/usr/bin/env bash
# One-time setup: creates a private Python environment in .venv and installs the app.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3.12 python3.13 python3.11 python3.14 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version=$("$candidate" -c 'import sys; print("%d%02d" % sys.version_info[:2])')
    # 3.15 and newer: the text reader (onnxruntime) has no installer for them yet
    if [ "$version" -ge 310 ] && [ "$version" -lt 315 ]; then
      PY="$candidate"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "PokerScribe needs Python 3.10 to 3.14."
  echo "Install Python 3.14 from https://www.python.org/downloads/ or with Homebrew: brew install python@3.14"
  exit 1
fi

echo "Using $($PY --version)"
"$PY" -m venv --clear .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt
echo
echo "Setup complete. Start PokerScribe with ./run_mac.sh or by double-clicking PokerScribe.command"
