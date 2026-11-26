#!/usr/bin/env bash
# B0 heads-up: every table and stack setting, looking for instructions that are wrong whatever
# the strategy (phase1_heads_up_b0.py), and three six-max runs with the same checks for
# comparison. Seeds 21 to 43, none of them the heads-up gate's.
#
# Run from the repo root: bash docs/research/runs/phase1_heads_up_b0.sh   (4 runs at a time)
set -u
OUT=${OUT:-docs/research/runs/phase1_heads_up_b0}
PY=${PY:-.venv/bin/python}
mkdir -p "$OUT"
export OUT PY
cat <<'LIST' | xargs -P "${JOBS:-4}" -L 1 bash -c 'name=$(echo "$@" | tr " " "_")
  "$PY" docs/research/runs/phase1_heads_up_b0.py "$@" > "$OUT/$name.json" 2> "$OUT/$name.err"; echo "done $name"' _
2 mixed even 2000 21
2 stations even 2000 22
2 nits even 2000 23
2 tags even 2000 24
2 lags even 2000 25
2 maniacs even 2000 26
2 fish247 even 2000 27
2 heldout even 2000 28
2 regulars even 2000 29
2 switchers even 2000 30
2 wildcards even 2000 31
2 mixed uneven 2000 32
2 mixed tourney 2000 33
2 fish247 tourney 2000 34
2 mixed even 2000 35 deep
2 fish247 even 2000 36 deep
2 mixed even 1000 37 profiles
6 mixed even 1200 41
6 mixed tourney 1200 42
6 fish247 even 1200 43 deep
LIST
"$PY" docs/research/runs/phase1_heads_up_b0_table.py "$OUT" | tee "$OUT/summary.md"
