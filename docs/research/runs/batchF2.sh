#!/bin/bash
cd /home/claude/PokerScribe
run() { echo "=== $1 | $2 | stacks $3 | $5" ; python3 tools/compare.py "$1" "$2" --tables "$4" --stacks "$3" --profiles $6; }
run '{"ev_sizing": true}' 3000 even mixed "profiles, base = baseline"
run '{"semibluff_turn": "combo"}' 2000 even mixed "profiles, base = baseline (always)"
