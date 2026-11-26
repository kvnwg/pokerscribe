#!/bin/bash
cd /home/claude/PokerScribe
run() { echo "=== $1 | $2 | stacks $3 | $5" ; python3 tools/compare.py "$1" "$2" --tables "$4" --stacks "$3" $6; }
run '{"reshove": {"EP": 0.08, "HJ": 0.10, "CO": 0.13, "BTN": 0.17, "SB": 0.20}}' 1000 tourney mixed,fish247 x
run '{"eff_push": true, "push_chart": true}' 1000 tourney mixed,fish247 "base push_chart" --base='{"push_chart":true}'
run '{"commit": 1.0}' 1000 tourney mixed,fish247 x
run '{"bully": true}' 1000 tourney mixed,fish247 x
