#!/bin/bash
cd /home/claude/PokerScribe
while pgrep -f 'batchC.sh' > /dev/null; do sleep 5; done
run() { echo "=== $1 | $2 | stacks $3 | $5" ; python3 tools/compare.py "$1" "$2" --tables "$4" --stacks "$3" $6; }
run '{"river_ip_call_share": 0.6}' 1000 even mixed,fish247 x
run '{"oop_lead": 0.80}' 1000 even mixed,fish247 x
run '{"balanced_river": true}' 1000 even mixed,fish247 x
run '{"commit": 1.0, "commit_draws": true}' 1000 tourney mixed,fish247 x
