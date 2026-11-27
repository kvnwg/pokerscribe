# After the gate: references, B0, benches, the Phase 6 game, checks

Run on 27 Nov 2026 straight after the gate, on the same machine, one step at a time, by
`run.sh` (started by `wait_then_run.sh` when the gate ended) and then `extra.sh`. The write-up is
in `docs/research/experiments.md`, "Phase 5: the gate". Steps 1 to 4 were planned with the gate
(references and the B0 run check are in `../README.md`); the checks in steps 5 and 6 and in
`extra.sh` were added after the gate's results and are not pre-registered.

| File | What |
| --- | --- |
| `run.sh`, `run.log` | The steps and their trace |
| `extra.sh`, `extra.log` | Every run's final strategy on a third deal set (the log without its wait loop) |
| `references.jsonl`, `references.out` | Step 1: always call, random action, random kind of action on the final deals (seed 778) |
| `b0.json`, `b0.out` | Step 1: standard-k200's final strategy against B0 at 20bb (`tools/b0_arena.py`) |
| `bench.jsonl` | Step 2: threads 1 to 4, standard-k200 at 20bb |
| `bench-prune.jsonl` | Step 3: no pruning, then thresholds of -10,000 and -100,000 big blinds |
| `rich-trainer.json`, `rich-4.out`, `rich-1.out`, `rich/` | Step 4: the Phase 6 game (200bb, `rich`, 200 buckets) through the `tools/cloud` trainer contract, 25 minutes on 4 threads then 5 on 1; `rich/log.jsonl` has one line per session |
| `check-seed779.jsonl` | Step 5: standard-k10 and small-k10 on seed 779 |
| `longer.jsonl`, `longer/` | Step 6: small-k10 trained on to 64M and small-k200 to 256M, measured on the final deals |
| `seed779.jsonl` | `extra.sh`: all eight runs, `b56_14`, seed 779, 100,000 hands |
| `recheck778.jsonl` | Last, by hand: standard-k10 on seed 778 again (its gate figure was about 3 SE below its other two deal sets) |
| `specs/` | The specs of steps 2 to 4 |
| `deals.tar.xz` | The per-deal results of steps 5, 6, `extra.sh` and the recheck |
| `pack.sh` | How these files were copied here and the two `deals.tar.xz` packed |

The per-deal results are kept, packed, because training on 4 lock-free threads does not repeat
exactly, so they could not be rebuilt from the scripts. `../checks.py` reads them:

```bash
cd docs/research/runs/phase5_gate
(cd gate && tar -xJf deals.tar.xz) && (cd after && tar -xJf deals.tar.xz)
python checks.py gate after
```
