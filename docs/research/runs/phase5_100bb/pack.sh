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
  for f in spec.json stages.jsonl progress.jsonl lbr.jsonl final.jsonl log.jsonl done.json; do
    [ -f $B/$r/$f ] && cp $B/$r/$f $D/$r/
  done
done
# Per-deal results of the final LBR (seed 778): training on 4 lock-free threads does not
# repeat exactly, so they could not be rebuilt from the plan.
(cd $B && tar -cf - */deals/*-final-*.deals | xz -9 -T4 > $D/deals.tar.xz)
ls -la $D/deals.tar.xz
# The checks after the plan (after.sh): logs, results and their per-deal files.
A=/root/bp/100bb-after
mkdir -p $R/after
cp $A/seed779.jsonl $A/references.jsonl $R/after/
# after.log without the lines of its wait loop
grep -v '^+ grep -q\|^+ sleep 20' $A/after.log > $R/after/after.log
(cd $A && tar -cf - seed779/*.deals references/*.deals | xz -9 -T4 > $R/after/deals.tar.xz)
ls -la $R/after/deals.tar.xz
