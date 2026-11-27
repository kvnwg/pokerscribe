#!/usr/bin/env bash
# Phase 1, heads-up: gate run 5's rule applied to the heads-up mode (--players 2).
#
# Kevin's Phase 1 brief: "Gate: the standard error per comparison is at least halved versus
# the current compare.py at equal hands", now also heads-up. The method is not changed for
# heads-up and nothing was tried on these seeds first, so this is the first and only run.
#
# Rule, fixed before any heads-up hand on seeds 1111, 1212, 1313 or 1414 was played:
#   The same 8 comparisons as gate runs 1 to 5, heads-up (--players 2), 3000 hands each.
#   New way: compare.py's defaults (--method duplicate: each deal played twice with the
#   seats swapped; 6 replays from where the variants part, dealing the bot fresh hands from
#   what it could hold; luck taken out only for board cards after which nobody can bet
#   again), on seeds 1111 and 1212.
#   Old way: --method classic, raw difference, pooled over seeds 1111, 1212, 1313 and 1414.
#   r = sd per hand of the new way (decks as units, pooled over its seeds) over sd per hand of
#   the old way (pooled over its seeds), as in runs 4 and 5.
#   Judged: the comparisons in which at least 1% of the new way's hands (seeds 1111 and 1212
#   together) differ.
#   Pass: geometric mean of r over the judged comparisons at most 0.5, no judged comparison
#   with r above 0.75, and the new way's CPU seconds per hand at most 1.25 times the old way's
#   (all 8 comparisons, seeds 1111 and 1212, one process each).
#   Also reported, not part of the rule: whether every judged r is at most 0.5 (the brief's
#   wording read strictly).
#
# Run from the repo root: bash docs/research/runs/phase1_heads_up_gate.sh   (4 runs at a time)
set -u
OUT=${OUT:-docs/research/runs/phase1_heads_up_gate}
mkdir -p "$OUT"
PY=${PY:-.venv/bin/python}
export OUT PY
{
  for seed in 1111 1212 1313 1414; do
    for m in classic duplicate; do
      if [ "$m" = duplicate ] && [ "$seed" != 1111 ] && [ "$seed" != 1212 ]; then continue; fi
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
  "$PY" tools/compare.py "$json" 3000 "$@" --players 2 --method "$m" --seed "$seed" --save "$OUT/${name}_${m}_${seed}.json" \
    > "$OUT/${name}_${m}_${seed}.txt" 2>&1
  echo "done $name $m $seed"'
"$PY" docs/research/runs/phase1_gate4_summary.py "$OUT" --new-seeds 1111,1212 --old-seeds 1111,1212,1313,1414 \
  --min-share 0.01 --strict | tee "$OUT/summary.md"
