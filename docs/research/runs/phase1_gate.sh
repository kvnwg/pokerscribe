#!/usr/bin/env bash
# Phase 1 gate: does the new way of comparing variants at least halve the standard error?
#
# Run 1, seed 303. Rule fixed before the run (26 Nov 2026):
#   For each of the 8 comparisons below, r = SE of the luck-adjusted difference with
#   --method duplicate divided by SE of the raw difference with --method classic (the way
#   every earlier result was made), at the same number of hands, same tables, seed 303
#   (never used before). The gate passes if the geometric mean of r is at most 0.5, no r is
#   above 0.75, and the duplicate runs take at most 1.25 times as long as the classic ones.
#   "Luck-adjusted" then meant the checked-down value only (now saved as "checked_down").
#   Its classic runs showed the checked-down adjustment can add variance: a card that both
#   wins the pot and gets the stacks in is only half corrected (experiments.md).
#
# Run 2, seed 404. Rule fixed before the run (26 Nov 2026), after run 1's classic results:
#   the same r, thresholds and comparisons, with "luck-adjusted" meaning tools/luck.py's mix
#   of the checked-down and all-in values with the frozen WEIGHTS ("adjusted"), fitted once
#   on seed 505 training hands of the baseline (`python tools/luck.py fit 2400`). A per-run
#   cross-fitted fit was tried first and dropped before run 2: with 16 hands that differ it
#   was unstable (its standard error was six times the checked-down one in a 300-hand test).
#
# Run 3, seed 404. Rule fixed before any seed-404 result was seen (26 Nov 2026), after a
#   diagnostic on seed 303 (phase1_variance_split.py) showed that on the mixed table most of
#   the variance left is the bots' random choices after the variants part ways: the duplicate
#   runs also replay each hand where the variants differ 6 times from the first decision where
#   they part (--resample 6; fresh bot random numbers and board cards, the same for both), and
#   r is the SE of that averaged luck-adjusted difference ("resampled") over the classic raw
#   SE of run 2. Same thresholds, comparisons and classic runs.
#
# The keyed runs (a seed per bot decision, no seat rotation) only show which part helps.
# Run from the repo root (4 runs at a time):
#   SEED=404 RESAMPLE=6 OUT=docs/research/runs/phase1_gate_404 bash docs/research/runs/phase1_gate.sh
set -u
OUT=${OUT:-docs/research/runs/phase1_gate}
mkdir -p "$OUT"
HANDS=${HANDS:-3000}
SEED=${SEED:-303}
PY=${PY:-.venv/bin/python}
METHODS=${METHODS:-classic duplicate keyed}
export OUT HANDS SEED PY RESAMPLE
{
  for m in $METHODS; do
    echo "ev_mixed $m '{\"ev_sizing\": true}' --tables mixed"
    echo "ev_fish $m '{\"ev_sizing\": true}' --tables fish247"
    echo "bet_half $m '{\"bet_size\": 0.5}' --tables mixed"
    echo "semibluff_never $m '{\"semibluff_turn\": \"never\"}' --tables mixed"
    echo "texture $m '{\"texture_sizing\": true}' --tables mixed"
    echo "push_chart $m '{\"push_chart\": true}' --tables mixed --stacks tourney"
    echo "commit $m '{\"commit\": 1.0}' --tables mixed"
    echo "no_stab $m '{\"stab\": 0.0}' --tables mixed"
  done
} | xargs -P "${JOBS:-4}" -L 1 bash -c 'name=$0; m=$1; json=$2; shift 2
  res=1; [ "$m" != classic ] && res=${RESAMPLE:-1}
  "$PY" tools/compare.py "$json" "$HANDS" "$@" --method "$m" --seed "$SEED" --resample "$res" --save "$OUT/${name}_$m.json" \
    > "$OUT/${name}_$m.txt" 2>&1
  echo "done $name $m"'
"$PY" docs/research/runs/phase1_gate_summary.py "$OUT"
