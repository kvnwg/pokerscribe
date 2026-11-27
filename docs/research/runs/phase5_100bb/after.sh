#!/bin/sh
# After the plan (not pre-registered, written while standard-k200 trained, after the k10 and k50
# results): every run's final strategy on a second deal set (b56_14, seed 779, 100,000 hands),
# because M's fall from 10 to 50 buckets was close to the 2 SE bar; and the references at
# 100bb (always call, random action, random kind of action) on the final deals, for scale.
set -x
B=/root/bp/blueprint-100bb
G=/root/bp/100bb
A=/root/bp/100bb-after
mkdir -p $A
until grep -q '^exit' $G/err.log 2>/dev/null; do sleep 20; done
date
for r in standard-k10 standard-k50 standard-k200; do
  stage=$(python3 -c "import json;print(json.load(open('$G/$r/done.json'))['stage'])")
  [ -f $A/seed779/$r.b56_14.s779.h100000.deals ] && continue
  $B lbr --strategy $G/$r/strategy-$stage.bps --settings b56_14 --hands 100000 --seed 779 \
     --deals $A/seed779 --label $r --out $A/seed779.jsonl
done
date
$B reference --stack 100 --hands 100000 --seed 778 --settings b56_14 \
   --deals $A/references --out $A/references.jsonl
date
echo AFTER DONE
