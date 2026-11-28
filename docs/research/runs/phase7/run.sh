#!/bin/bash
# The Phase 7 runs on Kevin's Mac, in the order of README.md ("The run, step by step"), with
# the seeds and sizes pre-registered in docs/research/experiments.md ("Phase 7: the plan at
# 200 big blinds"). From the repository's root:
#
#   caffeinate -i docs/research/runs/phase7/run.sh STEP
#
# STEP is one of: check, bench, pilot, size, match, read, lbr, repeat. Every step skips what is
# already in OUT, so a step that was stopped (Ctrl-C, a crash, the Mac asleep) goes on from the
# last chunk it finished when it is run again. A chunk that was cut off is played again from
# its start, with the same seed, and gives the same result.
#
# Settings (environment): S, the strategy file (its leaf tables must be next to it as
# $S.leaf); T, the bucket tables; OUT, where the results go.
set -euo pipefail
S=${S:-$HOME/phase6/run1/strategy-512000000.bps}
T=${T:-$HOME/abstraction/k200}
OUT=${OUT:-$HOME/phase7/runs}
B=engine/target/release/search
HERE=docs/research/runs/phase7
THREADS=4
mkdir -p "$OUT"

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/log.txt"; }
need() { [ -f "$1" ] || { echo "$1 is not there: $2" >&2; exit 1; }; }
need "$B" "build it first: (cd engine && cargo build --release --locked -p search)"
need "$S" "set S to the it512M strategy file"
need "$S.leaf" "the leaf tables go next to the strategy file (README.md, step 3)"

# One match, written whole: to a temporary name, then renamed.
match() { # file deals seed
  local f="$OUT/$1"
  if [ -f "$f" ]; then log "have $1"; return; fi
  log "match $1: $2 deals, seed $3"
  "$B" match --strategy "$S" --tables "$T" --deals "$2" --seed "$3" --threads $THREADS \
      --out "$f.tmp" >> "$OUT/log.txt" 2>&1
  mv "$f.tmp" "$f"
}

# One LBR run of 1,000 hands, written whole.
lbr() { # agent setting chunk seed
  local f="$OUT/lbr-$1-$2-$3"
  if [ -f "$f.json" ]; then log "have lbr-$1-$2-$3"; return; fi
  log "lbr $1 $2 chunk $3: 1000 hands, seed $4"
  "$B" lbr --strategy "$S" --tables "$T" --agent "$1" --setting "$2" --hands 1000 --seed "$4" \
      --out "$f.deals" > "$f.json.tmp" 2>> "$OUT/log.txt"
  mv "$f.json.tmp" "$f.json"
}

chunks() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['chunks'])" "$OUT/size.json"; }

case "${1:-}" in
  check)
    # Not a result: the agent loads (bucket tables, leaf tables), plays 10 hands, and the
    # memory it takes is printed (macOS: the peak, in bytes, as "maximum resident set size").
    /usr/bin/time -l "$B" bench --strategy "$S" --tables "$T" --hands 10 --seed 9601 \
        --threads $THREADS 2>&1 | tail -25
    ;;
  bench)
    # Decision time per street on 4 threads, one decision at a time.
    if [ -f "$OUT/bench.json" ]; then log "have bench.json"; exit 0; fi
    log "bench: 200 hands, seed 7581, $THREADS threads"
    "$B" bench --strategy "$S" --tables "$T" --hands 200 --seed 7581 --threads $THREADS \
        --out "$OUT/bench.json.tmp" > /dev/null 2>> "$OUT/log.txt"
    mv "$OUT/bench.json.tmp" "$OUT/bench.json"
    python3 "$HERE/gate.py" bounds "$OUT"
    ;;
  pilot)
    match pilot.json 2000 7501
    ;;
  size)
    need "$OUT/pilot.json" "run the pilot first"
    python3 "$HERE/gate.py" size "$OUT"
    ;;
  match)
    need "$OUT/size.json" "run size first"
    for k in $(seq 1 "$(chunks)"); do match "$(printf 'match-%02d.json' "$k")" 1000 $((7600 + k)); done
    log "the gate match is complete: run.sh read"
    ;;
  read)
    python3 "$HERE/gate.py" read "$OUT"
    echo "summary: $OUT/summary.md"
    ;;
  lbr)
    # Reported, not judged: both settings, both agents, the same deals for both (paired).
    for setting in fcpa14 b56_14; do
      base=7560; [ "$setting" = b56_14 ] && base=7570
      for k in 1 2; do
        lbr blueprint $setting $k $((base + k))
        lbr search $setting $k $((base + k))
        "$B" compare "$OUT/lbr-search-$setting-$k.deals" "$OUT/lbr-blueprint-$setting-$k.deals" \
            > "$OUT/compare-$setting-$k.json"
      done
    done
    log "LBR is complete: run.sh read"
    ;;
  repeat)
    # Only after the gate match passes (README.md, "The plan"): the same on fresh seeds.
    need "$OUT/size.json" "run size first"
    for k in $(seq 1 "$(chunks)"); do match "$(printf 'repeat-%02d.json' "$k")" 1000 $((7700 + k)); done
    log "the repeat is complete: run.sh read"
    ;;
  *)
    echo "usage: run.sh check|bench|pilot|size|match|read|lbr|repeat (README.md)" >&2
    exit 2
    ;;
esac
