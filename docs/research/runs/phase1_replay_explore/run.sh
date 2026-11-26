#!/usr/bin/env bash
# The looks at the replays against the raw difference (experiments.md, Phase 1, the replays
# against the raw difference). bet_size 0.5 against B0 on mixed, 3000 hands per seed. Seeds
# 606 to 909 are gate runs 4 and 5's hands; 41 to 48 were new. Run from the repo root; the
# record step takes about 4 minutes per seed, 4 at a time.
set -u
D=docs/research/runs/phase1_replay_explore
PY=${PY:-.venv/bin/python}
export D PY OMP_NUM_THREADS=1
SEEDS="606 707 808 909 41 42 43 44 45 46 47 48"
# every play of each hand that differs: the original pair, 5 replays with the real cards, 5 redealt
echo $SEEDS | tr ' ' '\n' | xargs -P 4 -I SEED sh -c \
  '"$PY" $D/record.py "{}" "{\"bet_size\": 0.5}" mixed SEED 3000 $D/bet_half_SEED.json'
# one extra redealt hand per hand, replayed with the same 5 salts as the real cards
echo $SEEDS | tr ' ' '\n' | xargs -P 4 -I SEED sh -c '"$PY" $D/extra_draw.py $D/bet_half_SEED.json $D/ystar_SEED.json'
G="$D/bet_half_[0-9][0-9][0-9].json"; F="$D/bet_half_4[1-8].json"
{ "$PY" $D/gaps.py "$G"; "$PY" $D/gaps.py "$F"; } > $D/gaps.txt
{ echo "gate seeds:"; "$PY" $D/permutation.py "$G"; echo "seeds 41-48:"; "$PY" $D/permutation.py "$F"; } > $D/permutation.txt
{ echo "gate seeds:"; "$PY" $D/plain_vs_redeal.py "$G"; echo "seeds 41-48:"; "$PY" $D/plain_vs_redeal.py "$F"; } > $D/plain_vs_redeal.txt
{ echo "gate seeds:"; "$PY" $D/salt_signs.py "$G"; echo "seeds 41-48:"; "$PY" $D/salt_signs.py "$F"; } > $D/salt_signs.txt
"$PY" $D/extra_draw_test.py "$D/ystar_[0-9][0-9][0-9].json" "$D/ystar_4[1-4].json" "$D/ystar_4[5-8].json" \
  "$D/ystar_4[1-8].json" > $D/extra_draw_test.txt
# where the real hands sit within their classes (slow: replays each hand that differs once more)
"$PY" $D/class_rank.py "$G" > $D/class_rank_gate.txt
"$PY" $D/class_rank.py "$D/bet_half_4[1-4].json" > $D/class_rank_fresh1.txt
"$PY" $D/class_rank.py "$D/bet_half_4[5-8].json" > $D/class_rank_fresh2.txt
"$PY" $D/first_answer.py "$G" > $D/first_answer_gate.txt
"$PY" $D/first_answer.py "$D/bet_half_4[1-4].json" > $D/first_answer_fresh1.txt
"$PY" $D/first_answer.py "$D/bet_half_4[5-8].json" > $D/first_answer_fresh2.txt
"$PY" $D/showdown.py "$G" > $D/showdown_gate.txt
"$PY" $D/showdown.py "$D/bet_half_4[1-4].json" > $D/showdown_fresh1.txt
"$PY" $D/showdown.py "$D/bet_half_4[5-8].json" > $D/showdown_fresh2.txt
