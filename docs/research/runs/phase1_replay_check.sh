#!/usr/bin/env bash
# Phase 1 check: do the redealt replays keep the hand's expected value? (26 Nov 2026)
#
# Why: on the gate runs' hands (seeds 606 to 909) the default "replayed 6 times" figure for
# bet_size 0.5 came out 11 bb/100 below the plain paired difference on the same hands (-3.9
# SE). Looks at those and at 8 fresh seeds (41 to 48) found replays with the bots' real cards
# matching the original deals, and replays with redealt cards a little lower; see
# experiments.md, Phase 1, the replays against the raw difference.
#
# Rule, fixed before any hand on seeds 51 to 66 was played:
#   Comparison: {"bet_size": 0.5} against B0 on mixed, 3000 hands per seed, duplicate decks,
#   seeds 51 to 66 (48000 hands).
#   For every hand where the variants differ: three arms replayed from the split with salts 1
#   to 5, both variants each time: the bots' real hands, and two fresh draws from their classes
#   (phase1_replay_check.py arms).
#   Statistic: the sum over those hands of the real arm's mean difference minus the mean of the
#   two redealt arms. p: the share of 10000 random relabellings (which arm is the real one, per
#   hand) at or above it; one-sided, since every earlier look had the real arm higher.
#   p < 0.01: the redeal is taken to be biased. p > 0.10: no sign of a bias on new hands.
#   In between: not settled. Either way the result is written down before anything changes.
#
# Run from the repo root: bash docs/research/runs/phase1_replay_check.sh   (4 at a time)
set -u
OUT=${OUT:-docs/research/runs/phase1_replay_check}
PY=${PY:-.venv/bin/python}
mkdir -p "$OUT"
export OUT PY OMP_NUM_THREADS=1
seq 51 66 | xargs -P "${JOBS:-4}" -I SEED sh -c \
  '"$PY" docs/research/runs/phase1_replay_check.py arms "{}" "{\"bet_size\": 0.5}" mixed SEED 3000 "$OUT/arms_SEED.json" && echo "done SEED"'
"$PY" docs/research/runs/phase1_replay_check.py test "$OUT/arms_*.json" | tee "$OUT/summary.md"
