#!/usr/bin/env bash
# Phase 1 gate, run 5: confirming the gate rule Kevin chose after run 4.
#
# Decision (Kevin, 26 Nov 2026, after seeing run 4): judge only comparisons in which at least
# 1% of hands play differently; below that a comparison has too little to measure.
#
# Rule, fixed before any hand on seeds 808 or 909 was played:
#   The same 8 comparisons as runs 1 to 4, 3000 hands each.
#   New way: as in run 4 (--method duplicate --redeal --exact-luck --no-hidden: 6 replays from
#   where the variants part, dealing the bots still in fresh hands from what they could hold;
#   luck taken out only for board cards after which nobody can bet again), on seeds 808 and 909.
#   Old way: --method classic, raw difference, pooled over seeds 303, 404, 606, 707, 808, 909.
#   r = sd per hand of the new way (decks as units, pooled over its seeds) over sd per hand of
#   the old way (pooled over its seeds), as in run 4.
#   Judged: the comparisons in which at least 1% of the new way's hands (seeds 808 and 909
#   together) differ. Run 4 had five (ev_sizing on mixed and fish247, bet_size 0.5,
#   texture_sizing, push_chart).
#   Pass: geometric mean of r over the judged comparisons at most 0.5, no judged comparison
#   with r above 0.75, and the new way's CPU seconds per hand at most 1.25 times the old way's
#   (all 8 comparisons, seeds 808 and 909, one process each).
#   If run 5 passes, the Phase 1 gate is passed. Run 4 also passes this rule, but it was used
#   to choose the rule, so it doesn't count.
#
# Run from the repo root: bash docs/research/runs/phase1_gate5.sh   (4 runs at a time)
set -u
OUT=${OUT:-docs/research/runs/phase1_gate5}
mkdir -p "$OUT"
PY=${PY:-.venv/bin/python}
export OUT PY
{
  for seed in 808 909; do
    for m in classic duplicate; do
      echo "ev_mixed $m $seed '{\"ev_sizing\": true}' --tables mixed"
      echo "ev_fish $m $seed '{\"ev_sizing\": true}' --tables fish247"
      echo "bet_half $m $seed '{\"bet_size\": 0.5}' --tables mixed"
      echo "semibluff_never $m $seed '{\"semibluff_turn\": \"never\"}' --tables mixed"
      echo "texture $m $seed '{\"texture_sizing\": true}' --tables mixed"
      echo "push_chart $m $seed '{\"push_chart\": true}' --tables mixed --stacks tourney"
      echo "commit $m $seed '{\"commit\": 1.0}' --tables mixed"
      echo "no_stab $m $seed '{\"stab\": 0.0}' --tables mixed"
    done
  done
} | xargs -P "${JOBS:-4}" -L 1 bash -c 'name=$0; m=$1; seed=$2; json=$3; shift 3
  new=""; [ "$m" = duplicate ] && new="--redeal --exact-luck --no-hidden"
  "$PY" tools/compare.py "$json" 3000 "$@" --method "$m" --seed "$seed" $new --save "$OUT/${name}_${m}_${seed}.json" \
    > "$OUT/${name}_${m}_${seed}.txt" 2>&1
  echo "done $name $m $seed"'
"$PY" docs/research/runs/phase1_gate4_summary.py "$OUT" --new-seeds 808,909 --old-seeds 303,404,606,707,808,909 \
  --min-share 0.01 | tee "$OUT/summary.md"
