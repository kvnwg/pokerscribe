#!/bin/bash
# Runs 7 and 8 of README.md (LBR on fresh seeds). From the repository's root:
#   docs/research/runs/phase7_groundwork/run-repeat.sh /root/bp/standard-k200/strategy-64000000.bps OUT_DIR
set -u
S=$1
OUT=$2
B=engine/target/release/search
mkdir -p "$OUT"
step() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/log.txt"; }
for setting in fcpa14 b56_14; do
  seed=7201; [ "$setting" = b56_14 ] && seed=7202
  for agent in blueprint search; do
    step "lbr $setting $agent"
    $B lbr --strategy "$S" --agent $agent --setting $setting --hands 6000 --seed $seed --out "$OUT/$agent-$setting.deals" >> "$OUT/log.txt" 2>&1
  done
  $B compare "$OUT/search-$setting.deals" "$OUT/blueprint-$setting.deals" >> "$OUT/log.txt" 2>&1
done
step "done"
