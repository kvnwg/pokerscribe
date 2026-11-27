#!/bin/sh
# Copy the after-gate outputs into the repository, and pack the per-deal results.
set -e
R=/home/user/pokerscribe/docs/research/runs/phase5_gate
A=/root/bp/after
D=$R/after
mkdir -p $D/specs $D/rich $D/longer/small-k10 $D/longer/small-k200
cp $A/run.sh $A/extra.sh $A/wait_then_run.sh $A/run.log $D/
# extra.log without the 700 lines of its wait loop
grep -v '^+ grep -q\|^+ sleep 20' $A/extra.log > $D/extra.log
cp $A/references.jsonl $A/references.out $A/b0.json $A/b0.out $D/
cp $A/bench.jsonl $A/bench-prune.jsonl $D/
cp $A/rich-trainer.json $A/rich-4.out $A/rich-1.out $D/
cp $A/rich/log.jsonl $A/rich/spec.json $D/rich/
cp $A/check-seed779.jsonl $A/longer.jsonl $A/seed779.jsonl $A/recheck778.jsonl $D/
for r in small-k10 small-k200; do
  cp $A/longer/$r/log.jsonl $A/longer/$r/spec.json $D/longer/$r/
done
cp /root/bp/specs/rich200-k200.json /root/bp/specs/bench-standard-k200.json \
   /root/bp/specs/bench-standard-k200-prune1e4.json /root/bp/specs/bench-standard-k200-prune1e5.json $D/specs/
# Per-deal results: the gate's final deals and the references, and the checks' deals.
(cd /root/bp/gate && tar -cf - */deals/*-final-*.deals references/*.deals | xz -9 -T4 > $R/gate/deals.tar.xz)
(cd $A && tar -cf - check-deals/*.deals longer/deals/*.deals seed779/*.deals recheck778/*.deals | xz -9 -T4 > $D/deals.tar.xz)
ls -la $R/gate/deals.tar.xz $D/deals.tar.xz
