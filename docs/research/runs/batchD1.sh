#!/bin/bash
cd /home/claude/PokerScribe
while pgrep -f '"bully": true' > /dev/null; do sleep 5; done
run() { echo "=== $1 | $2 | stacks $3 | $5" ; python3 tools/compare.py "$1" "$2" --tables "$4" --stacks "$3" $6; }
run '{"ev_sizing": true}' 1000 even mixed,fish247 x
run '{"bucket_sizing": true, "small_bet_from": 0.55}' 1000 even mixed,fish247 x
run '{"geometric": true}' 1000 even mixed,fish247 x
run '{"bully": true}' 1000 tourney mixed,fish247 x
run '{"eff_push": true, "push_chart": true}' 1000 tourney mixed,fish247 "base push_chart" --base='{"push_chart":true}'
