#!/bin/sh
# After run.sh: every run's final strategy on a third deal set (b56_14, seed 779, 100,000 hands),
# so the gate's paired differences can be checked on fresh deals. Not pre-registered.
set -x
B=/root/bp/blueprint-gate
A=/root/bp/after
until grep -q 'ALL DONE' $A/run.log 2>/dev/null; do sleep 20; done
date
for r in small-k10 small-k50 small-k50eq small-k200 standard-k10 standard-k50 standard-k50eq standard-k200; do
  stage=$(python3 -c "import json;print(json.load(open('/root/bp/gate/$r/done.json'))['stage'])")
  [ -f $A/seed779/$r.b56_14.s779.deals ] && continue
  $B lbr --strategy /root/bp/gate/$r/strategy-$stage.bps --settings b56_14 --hands 100000 --seed 779 \
     --deals $A/seed779 --label $r --out $A/seed779.jsonl
done
date
echo EXTRA DONE
