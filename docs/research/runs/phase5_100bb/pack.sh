#!/bin/sh
# Copy the 100bb check's logs into the repository, and pack its final per-deal results.
set -e
R=/home/user/pokerscribe/docs/research/runs/phase5_100bb
B=/root/bp/100bb
D=$R/run
mkdir -p $D
cp $B/out.log $B/err.log $D/
for r in standard-k10 standard-k50 standard-k200; do
  mkdir -p $D/$r
  for f in spec.json stages.jsonl lbr.jsonl final.jsonl log.jsonl done.json; do
    [ -f $B/$r/$f ] && cp $B/$r/$f $D/$r/
  done
done
# Per-deal results of the final LBR (seed 778): training on 4 lock-free threads does not
# repeat exactly, so they could not be rebuilt from the plan.
(cd $B && tar -cf - */deals/*-final-*.deals | xz -9 -T4 > $D/deals.tar.xz)
ls -la $D/deals.tar.xz
