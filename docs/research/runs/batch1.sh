#!/bin/bash
cd /home/claude/PokerScribe
T=mixed,stations,maniacs,fish247
run() { echo "=== $1 | $2 | stacks $3" ; python3 tools/compare.py "$1" "$2" --tables $T --stacks "$3" $4; }
run '{"push_chart": true}' 2000 tourney
run '{"reshove": {"EP": 0.08, "HJ": 0.10, "CO": 0.13, "BTN": 0.17, "SB": 0.20}}' 2000 tourney
run '{"eff_push": true, "push_chart": true}' 2000 tourney --base='{"push_chart": true}'
run '{"bully": true}' 2000 uneven
