#!/bin/bash
cd /home/claude/PokerScribe
T=mixed,stations,maniacs,fish247
run() { echo "=== $1 | $2 | stacks $3" ; python3 tools/compare.py "$1" "$2" --tables $T --stacks "$3" $4; }
run '{"commit": 1.0}' 1500 even
run '{"commit": 1.0}' 1500 tourney
run '{"river_ip_call_share": 0.6}' 1500 even
run '{"geometric": true}' 1500 even
run '{"balanced_river": true}' 1500 even
