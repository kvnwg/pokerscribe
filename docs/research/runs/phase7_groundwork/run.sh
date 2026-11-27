#!/bin/bash
# The Phase 7 groundwork runs, in the order of README.md. Run from the repository's root:
#   docs/research/runs/phase7_groundwork/run.sh /root/bp/standard-k200/strategy-64000000.bps OUT_DIR
set -u
S=$1
OUT=$2
B=engine/target/release/search
mkdir -p "$OUT"
step() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/log.txt"; }
step "4 bench";  $B bench --strategy "$S" --hands 150 --seed 7104 --threads 4 --out "$OUT/bench.json" > /dev/null 2>> "$OUT/log.txt"
step "4 scale";  $B scale --strategy "$S" --hands 40 --seed 7105 --spots 6 --out "$OUT/scale.json" > /dev/null 2>> "$OUT/log.txt"
step "4 trees";  $B trees --stack-bb 20 > "$OUT/trees-20.json"; $B trees --stack-bb 200 > "$OUT/trees-200.json"
step "5 ranges"; $B ranges --strategy "$S" --hands 300 --seed 7106 --out "$OUT/ranges.json" > /dev/null 2>> "$OUT/log.txt"
step "6 b0 search";    python3 tools/b0_arena.py "search:$S" --stack-bb 20 --deals 100 --seed 7107 --out "$OUT/b0-search.json" >> "$OUT/log.txt" 2>&1
step "6 b0 blueprint"; python3 tools/b0_arena.py "blueprint:$S" --stack-bb 20 --deals 100 --seed 7107 --out "$OUT/b0-blueprint.json" >> "$OUT/log.txt" 2>&1
step "1 h2h";    $B match --strategy "$S" --deals 3000 --seed 7101 --threads 4 --out "$OUT/h2h.json" >> "$OUT/log.txt" 2>&1
for setting in fcpa14 b56_14; do
  seed=7102; [ "$setting" = b56_14 ] && seed=7103
  for agent in blueprint search; do
    step "lbr $setting $agent"
    $B lbr --strategy "$S" --agent $agent --setting $setting --hands 1500 --seed $seed --out "$OUT/$agent-$setting.deals" >> "$OUT/log.txt" 2>&1
  done
  $B compare "$OUT/search-$setting.deals" "$OUT/blueprint-$setting.deals" >> "$OUT/log.txt" 2>&1
done
step "done"
