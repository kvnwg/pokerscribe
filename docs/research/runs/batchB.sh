#!/bin/bash
cd /home/claude/PokerScribe
run() { echo "=== $1 | $2 | stacks $3 | $5" ; python3 tools/compare.py "$1" "$2" --tables "$4" --stacks "$3" $6; }
run '{"push_chart": true}' 1000 tourney maniacs,fish247 x
run '{"bully": true}' 1000 uneven mixed,fish247 x
run '{"river_ip_call_share": 0.6}' 1000 even mixed,fish247 x
run '{"geometric": true}' 1000 even mixed,fish247 x
run '{"balanced_river": true}' 1000 even mixed,fish247 x
