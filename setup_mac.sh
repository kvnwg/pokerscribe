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

# Optional: the Rust engine (engine/). PokerScribe runs without it, so nothing here can
# make the setup fail. With Rust installed (https://rustup.rs) this builds the Python
# module pokerscribe_engine and, once that crate is there, the solver program
# subgame-solve. Set POKERSCRIBE_SKIP_RUST=1 to leave it out.
if [ "${POKERSCRIBE_SKIP_RUST:-}" != "1" ] && command -v cargo >/dev/null 2>&1; then
  echo
  echo "Rust is installed: building the optional Rust engine (a minute or two the first time)."
  if .venv/bin/python -m pip install ./engine/crates/py; then
    echo "Built the Python module pokerscribe_engine."
  else
    echo "Could not build pokerscribe_engine. PokerScribe works without it; see engine/crates/py/README.md."
  fi
  if [ -d engine/crates/subgame ]; then
    if (cd engine && cargo build --release --bin subgame-solve); then
      echo "Built the solver program engine/target/release/subgame-solve."
    else
      echo "Could not build subgame-solve. PokerScribe works without it (the Python solver is used)."
    fi
  fi
fi

echo
echo "Setup complete. Start PokerScribe with ./run_mac.sh or by double-clicking PokerScribe.command"
