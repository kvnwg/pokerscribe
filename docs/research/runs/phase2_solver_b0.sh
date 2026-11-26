#!/usr/bin/env bash
# Phase 2 gate: river_solver against B0.
#
# Rule, fixed before any hand on seeds 1111 to 8888 was played (26 Nov 2026, after Kevin
# closed Phase 1 on run 5):
#   Each run: tools/compare.py '{"river_solver": true}' 3000 --tables <table> --seed <seed>,
#   with the defaults: duplicate decks; 6 replays from where the variants part, dealing the
#   bots still in fresh hands they could hold; the luck of board cards taken out only where
#   nobody can bet again; even stacks (100 big blinds); no profiles. Simulations give the
#   solver a fixed 300 iterations (tools/simulate.py, SOLVER_ITERATIONS).
#   Estimate: the "replayed 6 times" figure, pooled over a stage's seeds, SE with decks as
#   units (phase2_solver_b0_summary.py).
#   Stage 1: mixed, seeds 1111, 2222, 3333 and 4444 (12000 hands). Passes if river_solver
#     minus B0 is at least 2.5 SE.
#   Stage 2, only if stage 1 passes: fish247, heldout, regulars, switchers and wildcards,
#     seeds 1111 and 2222 (6000 hands each). Passes if none loses significantly, which here
#     means a difference of -2 SE or less.
#   Stages 3 and 4, only if stages 1 and 2 pass: the same again on fresh seeds (mixed: 5555,
#     6666, 7777 and 8888; the others: 5555 and 6666), with the same conditions.
#   river_solver meets the B0 bar only if all four stages pass. Even then it stays off until
#   Kevin decides to make it the default, since it changes what the app tells him at the
#   table. If a stage fails, the later stages aren't run and the switch stays off.
#
# Run from the repo root: bash docs/research/runs/phase2_solver_b0.sh <stage>   (4 runs at a time)
set -u
STAGE=${1:?stage 1, 2, 3 or 4}
OUT=${OUT:-docs/research/runs/phase2_solver_b0}
mkdir -p "$OUT"
PY=${PY:-.venv/bin/python}
# one thread per run: four runs share the machine (fixed iterations, so this changes speed only)
export OUT PY OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
case "$STAGE" in
  1) TABLES="mixed"; SEEDS="1111 2222 3333 4444" ;;
  2) TABLES="fish247 heldout regulars switchers wildcards"; SEEDS="1111 2222" ;;
  3) TABLES="mixed"; SEEDS="5555 6666 7777 8888" ;;
  4) TABLES="fish247 heldout regulars switchers wildcards"; SEEDS="5555 6666" ;;
  *) echo "stage 1, 2, 3 or 4"; exit 1 ;;
esac
for table in $TABLES; do
  for seed in $SEEDS; do
    echo "$table $seed"
  done
done | xargs -P "${JOBS:-4}" -L 1 bash -c 'table=$0; seed=$1
  "$PY" tools/compare.py "{\"river_solver\": true}" 3000 --tables "$table" --seed "$seed" \
    --save "$OUT/${table}_${seed}.json" > "$OUT/${table}_${seed}.txt" 2>&1
  echo "done $table $seed"'
"$PY" docs/research/runs/phase2_solver_b0_summary.py "$STAGE" | tee "$OUT/stage$STAGE.md"
