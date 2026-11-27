#!/bin/sh
# After the gate: references, B0 match, benches. One step at a time unless noted.
set -x
B=/root/bp/blueprint-gate
A=/root/bp/after
V=/tmp/claude-0/-home-user-pokerscribe/8a0324c3-774b-5b90-a070-b8c2eb12d3d0/scratchpad/venv/bin/python
cd /root/bp/after
date
# 1. References on the final deals (seed 778), and the B0 run check at the same time (one process).
$B reference --stack 20 --hands 100000 --seed 778 --settings b56_14,b56_34,fcpa14,fcpa34,fc34 \
   --deals /root/bp/gate/references --out $A/references.jsonl > $A/references.out 2>&1 &
R=$!
STAGE=$(python3 -c 'import json;print(json.load(open("/root/bp/gate/standard-k200/done.json"))["stage"])')
(cd /home/user/pokerscribe && $V tools/b0_arena.py blueprint:/root/bp/gate/standard-k200/strategy-$STAGE.bps --stack-bb 20 --deals 1000 --seed 2027 --out $A/b0.json > $A/b0.out 2>&1)
wait $R
date
# 2. Thread scaling at 20bb, standard menu, 200 buckets.
$B bench --spec /root/bp/specs/bench-standard-k200.json --seconds 60 --warmup 60 --threads 1,2,3,4 --out $A/bench.jsonl
date
# 3. Pruning: the same game with and without, after the same warm-up (300 s, about 20M iterations).
$B bench --spec /root/bp/specs/bench-standard-k200.json --seconds 120 --warmup 300 --threads 4 --out $A/bench-prune.jsonl
$B bench --spec /root/bp/specs/bench-standard-k200-prune1e4.json --seconds 120 --warmup 300 --threads 4 --out $A/bench-prune.jsonl
$B bench --spec /root/bp/specs/bench-standard-k200-prune1e5.json --seconds 120 --warmup 300 --threads 4 --out $A/bench-prune.jsonl
date
# 4. The Phase 6 game (200bb, rich menu, 200 buckets): 25 minutes on 4 threads, then 4 on 1.
rm -rf $A/rich; mkdir -p $A/rich
$B --config $A/rich-trainer.json --checkpoint-dir $A/rich > $A/rich-4.out 2>&1 &
T=$!; sleep 1500; kill -TERM $T; wait $T; echo "exit $?"
$B --config $A/rich-trainer.json --checkpoint-dir $A/rich --resume --threads 1 > $A/rich-1.out 2>&1 &
T=$!; sleep 300; kill -TERM $T; wait $T; echo "exit $?"
ls -la $A/rich
date
# 5. Check: standard-k10 final strategy on a third deal set (the stage and final LBR differed by 10.9).
$B lbr --strategy /root/bp/gate/standard-k10/strategy-32000000.bps --settings b56_14 --hands 100000 --seed 779 --deals $A/check-deals --out $A/check-seed779.jsonl
$B lbr --strategy /root/bp/gate/small-k10/strategy-8000000.bps --settings b56_14 --hands 100000 --seed 779 --deals $A/check-deals --out $A/check-seed779.jsonl
date
echo CHECK DONE
# 6. Check (not pre-registered): is the bucket result an artefact of where the runs stopped?
#    small-k10 trained on to 64M (8 times its stop) and small-k200 to 256M (4 times its stop),
#    then measured on the final deals (b56_14, seed 778, 100,000 hands).
for r in small-k10:64000000 small-k200:256000000; do
  name=${r%%:*}; until=${r##*:}
  rm -rf $A/longer/$name; mkdir -p $A/longer; cp -r /root/bp/gate/$name $A/longer/$name
  rm -f $A/longer/$name/done.json
  $B train --spec $A/longer/$name/spec.json --dir $A/longer/$name --until $until >> $A/longer.jsonl
  $B lbr --strategy $A/longer/$name/strategy-$until.bps --settings b56_14,fcpa34 --hands 100000 --seed 778 \
     --deals $A/longer/deals --label longer-$name-$until --out $A/longer.jsonl
done
date
echo LONGER DONE
echo ALL DONE
