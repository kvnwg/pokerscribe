#!/bin/bash
cd /home/claude/PokerScribe
run() { echo "=== $1 | $2 | stacks $3 | $5" ; python3 tools/compare.py "$1" "$2" --tables "$4" --stacks "$3" --profiles $6; }
run '{"ev_sizing": true}' 3000 even fish247 "profiles"
run '{"semibluff_turn": "combo"}' 2000 even fish247 "profiles, base always" --base='{"semibluff_turn":"always"}'
run '{"river_ip_call_share": 0.6}' 1000 even mixed,fish247 profiles
run '{"bucket_sizing": true, "small_bet_from": 0.55}' 1000 even mixed,fish247 profiles
run '{"bully": true}' 1000 tourney mixed,fish247 profiles
