#!/bin/bash
cd /home/claude/PokerScribe
run() { echo "=== $1 | $2 | stacks $3 | $5" ; python3 tools/compare.py "$1" "$2" --tables "$4" --stacks "$3" $6; }
run '{"semibluff_turn": "combo"}' 1500 even mixed,fish247 "base always"
run '{"semibluff_turn": "never"}' 1500 even mixed,fish247 "base always"
