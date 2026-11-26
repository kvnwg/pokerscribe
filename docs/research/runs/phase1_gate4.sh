#!/usr/bin/env bash
# Phase 1 gate, run 4: replays that also deal the opponents new hands.
#
# Rule, fixed before any result on seeds 606 or 707 was seen (26 Nov 2026):
#   The same 8 comparisons as runs 1 to 3 (phase1_gate.sh), 3000 hands each.
#   New way: --method duplicate --redeal --exact-luck --no-hidden (6 replays from where the
#   variants part; each replay also deals the bots still in a fresh draw from the hands they
#   could hold given what they did before the split, tools/hidden.live_classes; the luck of
#   board cards is taken out only where nobody can bet again, tools/luck.no_more_betting), on
#   seeds 606 and 707. The estimate is the "replayed 6 times" column ("resampled" in the JSON).
#   Chosen on seeds 303 and 404 (phase1_redeal_explore.py, phase1_redeal/summary.md): on the
#   same hands its SE was 0.39 of the raw SE (geometric mean of 14 cells), against 0.61 for
#   run 3's replays. The hidden-cards estimate (tools/hidden.py) is not used: on top of the
#   redeal it did not help consistently.
#   Old way: --method classic, raw difference, on seeds 606 and 707 plus the classic runs
#   of seeds 303 and 404 already made (phase1_gate/ and phase1_gate_404/).
#   r = sd per hand of the new way (decks as units, pooled over its seeds) over sd per hand
#   of the old way (pooled over its seeds): the ratio of standard errors at any equal number
#   of hands. A single 3000-hand run's SE was shown to be off by up to half (experiments.md,
#   Phase 1), so the sd is pooled over seeds instead.
#   Pass: geometric mean of r at most 0.5, no r above 0.75, and the new way's CPU seconds per
#   hand at most 1.25 times the old way's (seeds 606 and 707, one process each).
#   Comparisons in which no hand differs are left out, as before.
#
# Run from the repo root: bash docs/research/runs/phase1_gate4.sh   (4 runs at a time)
set -u
OUT=${OUT:-docs/research/runs/phase1_gate4}
mkdir -p "$OUT"
PY=${PY:-.venv/bin/python}
export OUT PY
{
  for seed in 606 707; do
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
"$PY" docs/research/runs/phase1_gate4_summary.py "$OUT"
