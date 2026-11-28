# Phase 7: search against the blueprint at 200 big blinds, ready to run

Phase 7 of the roadmap (`docs/research/README.md`): depth-limited search on every postflop
decision (Modicum), on the Phase 6 blueprint (it512M: `strategy-512000000.bps`, 200 big blinds,
the `rich` menu, 200 buckets). The search crate is `engine/crates/search`; its groundwork at 20
big blinds is in `experiments.md`, "Phase 7 groundwork".

The gate (Kevin, 27 Nov 2026) has three conditions: the search beats the blueprint head to head
by 2.5 SE, a luck-adjusted Slumbot match, and the GTO Wizard Benchmark. This folder covers the
first: the head-to-head match, with LBR and decision time reported beside it. **Slumbot and the
GTO Wizard Benchmark are left for later**, with their own plan, once this condition is read.

Nothing here has been run on it512M and nothing has been launched or rented. The plan is
pre-registered in `docs/research/experiments.md`, "Phase 7: the plan at 200 big blinds (28 Nov
2026)", and is binding as written there; this README is the runbook. Everything is offline and
against our own agents (rule 4).

| File | What it is |
| --- | --- |
| `run.sh` | Every run on Kevin's Mac, one step at a time, resumable, with the pre-registered seeds and sizes |
| `gate.py` | The decision-time check, the match size from the pilot, and the reading (`summary.md`) |
| `leaf.json` | The leaf table build as a `tools/cloud` job: strategy file, bucket tables, 16M deals, seed 7, 256 turn starts a part |
| `cloud.env.example` | The `tools/cloud` settings for that build, without a project or bucket |
| `leaf_rehearsal.py` | The dress rehearsal of the build under the real `tools/cloud` supervisor, run here |

## The run, step by step

On Kevin's Mac, from the repo root. Steps 1 to 3 once; then `run.sh` step by step. Every
`run.sh` step can be stopped (Ctrl-C, a crash, the lid closed) and run again: it skips what is
done and plays a cut-off chunk again from its start, with the same seed and the same result.

1. **The code and the files:**

   ```
   git pull
   (cd engine && cargo build --release --locked -p search)
   sysctl -n hw.memsize                                    # 17179869184 or more (16 GB)
   ls -l ~/phase6/run1/strategy-512000000.bps ~/abstraction/k200
   ```

   The search agent holds the 9.7 GB leaf tables in memory: about 11 GB in all (measured here).
   With 16 GB, close the other big programs while it plays; under 16 GB it can't run as planned
   (stop and tell the manager session). If the files are elsewhere, set `S` (the strategy file)
   and `T` (the bucket tables) in the environment for every command below.

2. **The cloud settings** (only for the cloud build, 3a):
   `cp docs/research/runs/phase7/cloud.env.example ~/.config/pokerscribe/cloud-leaf.env`, then
   fill in `PROJECT`, `BUCKET` and `SERVICE_ACCOUNT` (Phase 6's), and read the current Spot
   price of c4a-highcpu-64 in us-central1 into `SPOT_PRICE_PER_HOUR` ($1.445888 on 27 Nov 2026).
   It is a separate file so Phase 6's `cloud.env` stays as it was; every command below names it.

3. **The leaf tables**, `~/phase6/run1/strategy-512000000.bps.leaf` (9.7 GB), once. Either way
   gives the same tables ("The leaf tables" has the hours and dollars).

   **3a. On a rented machine (recommended): about 1.3 to 3.3 hours, $1.9 to $4.9, capped at $8.**

   ```
   python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env check       # "all checks passed"
   python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env launch --dry-run
   python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env launch
   caffeinate -i python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env recover   # second terminal, leave it running
   python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env watch --every 60
   ```

   `watch` counts the progress in deals (`iterations`): 34 parts of 16,000,000, so 544,000,000
   at the end. When the run is done (`recover` exits, `watch` says done):

   ```
   python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env artifacts --download ~/phase7/leaf --only 'strategy-512000000.bps.leaf'
   mv ~/phase7/leaf/strategy-512000000.bps.leaf ~/phase6/run1/
   python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env cleanup
   python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env leftovers   # only the bucket
   ```

   The parts and the table file stay in the bucket (19.4 GB, about $0.39 a month) until the run's
   folder is deleted: `gcloud storage rm -r gs://<BUCKET>/runs/hu-leaf-512m`, once step 4 has
   loaded the file. If the $8 cap stops the run first, raise `BUDGET_USD` and
   `python -m tools.cloud --settings ~/.config/pokerscribe/cloud-leaf.env resume`: the parts done
   are kept. A Spot preemption costs at most the part being built (about 2 to 4 minutes).

   **3b. On the Mac: about 8 to 16 hours, $0.**

   ```
   caffeinate -i engine/target/release/search leaf --strategy ~/phase6/run1/strategy-512000000.bps \
       --tables ~/abstraction/k200 --deals 16000000 --seed 7
   ```

   It writes its parts in `~/phase6/run1/strategy-512000000.bps.leaf-parts` (about 1.5 GB of
   memory, up to 19.4 GB of disk while it puts the file together), then the table file next to
   the strategy file, and deletes the parts. Stopped, the same command goes on from the parts
   done.

4. **Check** (a minute or two; not a result):

   ```
   caffeinate -i docs/research/runs/phase7/run.sh check
   ```

   It loads the strategy file with `T`'s tables and the leaf tables (refused if they were built
   for another strategy file), plays 10 hands and prints the peak memory ("maximum resident set
   size", in bytes; about 11 GB expected).

5. **Decision time** (a few minutes): `caffeinate -i docs/research/runs/phase7/run.sh bench`.
   It ends with `"bounded": true`, or names the streets over their bound ("Decision time"). If a
   street is over, stop and tell the manager session before the match.

6. **The pilot** (about 40 to 70 minutes): `caffeinate -i docs/research/runs/phase7/run.sh pilot`.
   2,000 deals, seed 7501: only for the match's size, never pooled into the gate.

7. **The match's size**: `docs/research/runs/phase7/run.sh size`. Prints N (4,000 to 40,000
   deals), the chunks and the hours it projects.

8. **The gate match** (N / 1,000 chunks, about 1.2 to 2 seconds a deal: from 1.4 to 23 hours):
   `caffeinate -i docs/research/runs/phase7/run.sh match`. It can run over several sessions.

9. **The reading**: `docs/research/runs/phase7/run.sh read`, then `~/phase7/runs/summary.md`.
   The gate's head-to-head condition is read there, by the rule in "The plan".

10. **LBR** (reported, not judged; about 6 to 10 hours):
    `caffeinate -i docs/research/runs/phase7/run.sh lbr`, then `run.sh read` again.

11. **Only if the gate match passed: the repeat on fresh seeds** (as long as the match):
    `caffeinate -i docs/research/runs/phase7/run.sh repeat`, then `run.sh read`.

12. **The results** go to the manager session: `~/phase7/runs` without the `*.deals` files
    (`summary.md`, `summary.json`, `size.json`, `bench.json`, `pilot.json`, the match, repeat,
    LBR and compare JSON files, `log.txt`), copied into `docs/research/runs/phase7/results/` for
    the write-up in `experiments.md`.

## The plan

Pre-registered in `experiments.md`, "Phase 7: the plan at 200 big blinds (28 Nov 2026)", written
before any run on it512M. In short:

| Run | Size | Seeds | What it gives |
| --- | --- | --- | --- |
| `check` | 10 hands | 9601 | the files load, the memory; not a result |
| `bench` | 200 hands against the blueprint, 4 threads | 7581 | decision time per street; the bound check |
| Pilot | 2,000 deals | 7501 | the sd a deal, for N; not pooled |
| Gate match | N deals in chunks of 1,000 | 7601, 7602, ... | **the gate's head-to-head condition** |
| LBR `fcpa14` | 2,000 hands against each agent, 2 chunks | 7561, 7562 | reported |
| LBR `b56_14` | 2,000 hands against each agent, 2 chunks | 7571, 7572 | reported |
| Repeat (only after a pass) | N deals in chunks of 1,000 | 7701, 7702, ... | for promotion (CLAUDE.md ground rules) |

- **The match**: `search match`, the search agent (`Settings::default()`, the leaf tables of
  step 3) against the blueprint it searches on, it512M itself. Duplicate deals: each deal is
  played twice with the seats swapped. All-in equity: a hand that is all in before the river is
  scored by its equity over the cards to come. bb/100 with its SE over deals. 200 big blinds,
  the arena's heads-up rules. Each chunk of 1,000 deals is a match with its own seed; the gate
  pools them (mean weighted by deals, SE from the chunks' SEs).
- **N** = (2.5 x sd / 10)^2 deals, with sd the pilot's sd a deal (in bb/100): the deals that
  see an edge of 10 bb/100 at 2.5 SE. Rounded up to a multiple of 1,000, at least 4,000, at most
  40,000 (`gate.py size`). At sd 400 that is 10,000 deals; at sd 801 (B0 against the blueprint
  in Phase 6) it would be 41,000 after rounding and the cap holds it to 40,000. Above sd 800 the
  cap binds, and the edge seen at 2.5 SE is 2.5 x sd / 200 bb/100 (12.5 at sd 1,000).
- **The pass rule**: the gate's head-to-head condition passes when the pooled gate match is at
  z = bb/100 / SE >= 2.5, read on that match alone. Anything below is "does not pass": no extra
  deals, no second try on other seeds, no pooling with the pilot.
- **For promotion**, beyond the gate (CLAUDE.md, ground rules): the repeat on fresh seeds (seeds
  7701 on, the same N) also at z >= 2.5, and LBR winning less against search than against the
  blueprint. Run only after the gate match passes.
- **LBR**, reported, not judged: `fcpa14` (fold, call, pot, all in) and `b56_14` (56 sizes),
  against both agents on the same deals (`search compare`, paired). At 2,000 hands each it is
  about ±110 bb/100 for each agent and about ±130 for the difference (Phase 6's spread at 200
  big blinds), so only a fall of more than about 300 bb/100 shows at 2.5 SE; it is far slower against
  search than against the blueprint (about 13 s a hand here, about 0.001 s for the blueprint).
- **Decision time**: `search bench` on 4 threads, p50, p95 and the slowest decision per street,
  checked against the bound below. The match and LBR solve times are reported beside it.
- **Hardware**: Kevin's MacBook Air, `--threads 4`, plugged in, under `caffeinate -i`. The match,
  LBR and the bench all run there; only the leaf tables may be built elsewhere.

## The leaf tables

8,669 turn starts in the 200 big blind `rich` game, 7 lanes (the blueprint and six biased
continuations), 200 x 200 cells of flop buckets: 9,709,339,447 bytes. Built with 16M deals,
seed 7 (about 400 deals a cell on average; smoothing as in the groundwork: bias 5, a
pseudo-count of 3 deals). The work is 8,669 x 16M = 1.39e11 walks (a turn start and a deal).

Measured here (4 vCPU, Intel Xeon at 2.1 GHz, 15 GB) on a 200 big blind `rich` k200 blueprint
trained for 2M iterations, all 8,669 turn starts at 65,536 deals, 34 parts: 1.60M walks a second
(399,000 a thread), parts of 5.5 to 17.7 s, 397 s for the job, peak memory 1.54 GB (a build in
one piece would need about 29 GB). At 16M deals that is about 96 thread-hours here.

| | Cloud: c4a-highcpu-64, Spot, through `tools/cloud` | Kevin's MacBook Air |
| --- | --- | --- |
| Speed assumed | an Arm thread about 1.2 times one here (Phase 6's 183,096 iterations a second on 64 threads at the projection's 1,134 states an iteration, against 2.7M states a second a thread here), 0.6 to 1.5 times | 4 performance cores at 1.5 to 2.5 times a thread here, the efficiency cores at 0.4 to 0.7 times, less when the fanless case throttles |
| The build | about 1.3 hours (1.0 to 2.5) | about 9 hours (8 to 16) |
| On top | about 15 minutes to start and build the code, 5 minutes to put the file together and upload it | none |
| In all | **1.3 to 3.3 hours** | **8 to 16 hours**, and the Mac is busy for them |
| Dollars | **$1.9 to $4.9** (central $2.4) at $1.4714 an hour, capped at $8 (5.4 hours); plus about $1.2 to download 9.7 GB and $0.39 a month in the bucket until deleted | **$0** |
| Memory | about 2 GB of 128 GB | about 1.5 GB |
| Disk | 80 GB (as Phase 6) | 19.4 GB at the end of the build, 9.7 GB after |

**The recommendation is the cloud**: about $3 to $6 in all saves 8 to 16 hours of the Mac before
the match, which itself needs the Mac for many hours. If Kevin prefers to spend nothing, 3b
overnight gives the same tables. The cloud's speed is the guess here (no Arm machine in this
container); the build's own lines in `watch` show the real speed within minutes of the start,
and the cap holds the cost whatever it turns out to be.

The same tables on any number of threads, block size or parts, bit for bit (tested). Whether an
Arm machine gives the same last bits as an x86 one isn't tested; either build is valid, and the
table file records the strategy file's hash, so it can only be used with it512M.

### The build as a cloud job

`search --config leaf.json --checkpoint-dir DIR [--resume]` keeps the `tools/cloud` trainer
contract (`tools/cloud/README.md`, "The trainer"; `engine/crates/search/README.md`, "Building
the leaf tables in parts"): its checkpoint is `leaf.ckpt` (a list of the parts done and the
build's fingerprint), the parts and the table file are artifacts uploaded as they are written
and put back on a new machine, SIGTERM gives up the part being built and exits 75, and it exits
0 when the table file is written. `tools/cloud` itself is unchanged: the settings file does it
all.

**The dress rehearsal** passed here (`leaf_rehearsal.py --deals 3000000 --part-nodes 1 --threads
2` on a 10 big blind blueprint with 11 turn starts, k200, 96 s): the real supervisor with a
local folder as the bucket; SIGTERM to every process once 2 parts were in the bucket, the job
stopped 0.2 s later with exit code 75 and the supervisor uploaded the checkpoint and the parts; a
new machine with an empty disk got them back and the job resumed 0.5 s after start with those
parts done, built the other 9 and wrote the table file; the run ended "done" with every part
and the table file in the bucket and both sessions counted; and the table file's values were
`search leaf`'s (on this computer, without the supervisor) bit for bit. The binary's contract is
also tested in `engine/crates/search/tests/cloud_job.rs` (nightly).

## Decision time

There is no time limit: every decision runs at most one solve of its street, to a target or an
iteration cap (`Settings::default()`: flop 1% of the pot or 400 iterations, turn 2% or 300,
river 0.5% or 1,000), and a decision that reuses its street's solve takes under a millisecond.
A street's tree is the blueprint's menu plus the real off-menu actions on it. So the slowest
decision is bounded by the largest tree at the cap:

- cost = solver nodes x combos (both ranges) x iterations x the cost of one, measured in the
  groundwork: 0.0105 microseconds on the turn (3.2 times faster on 4 threads; the river taken as
  the same), 0.19 on the flop (2.5 times faster on 4 threads);
- turn: 13,857 nodes (the largest tree in the pilots here) x 2,256 combos x 300 = 31 s on 4
  threads; flop: 81 nodes x 2,352 x 400 = 5.8 s; river: 81 nodes x 2,162 x 1,000 = 0.6 s;
- a re-solve after an off-menu bet adds that bet's subtree: taken as at most twice the tree.

**The bound**: twice the worst case at the caps on this container, rounded up: **flop 12 s,
turn 65 s, river 2 s**, for the slowest decision of each street in `bench` (4 threads, one
decision at a time). The Mac's cores are faster than these, so it is a loose bound there: what it
catches is a solve whose tree or iterations are not bounded, not a slow machine.

Measured here on the 2M-iteration blueprint (nearly random, so its ranges are wide and its
solves at the large end; 4 threads):

| `search bench`, 200 hands, seed 9501 | Decisions | p50 | p95 | Max | Solver nodes (mean) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flop | 45 | 745 ms | 1,303 ms | 1,442 ms | 79 |
| Turn | 28 | 4,956 ms | 18,346 ms | 21,322 ms | 13,051 |
| River | 14 | 107 ms | 268 ms | 583 ms | 80 |

184 s for the 200 hands, all within the bound.

In a match the turn is solved on one thread with 4 deals in parallel, so a match decision on
the turn can take up to about 3 times as long as in `bench`. Against LBR `b56_14` (40 hands, seed
9503) the search re-solved 157 of 302 flop solves, 106 of 205 turn solves and 58 of 60 river
solves; turn p50 6.2 s and p95 18.0 s with the hands in parallel.

## Sizes and costs

On the Mac, at this container's speeds on the 2M-iteration blueprint divided by 1.5 to 2.5
(it512M's narrower ranges should make it faster still; the pilot measures it):

| Step | Here (4 vCPU) | On the Mac (projected) |
| --- | --- | --- |
| `check`, 10 hands | | a minute or two (loading 9.7 GB of leaf tables) |
| `bench`, 200 hands | 184 s | 1 to 3 minutes |
| Pilot, 2,000 deals | 3.07 s a deal (60 deals) | 40 to 70 minutes |
| Gate match, N deals | | 1.2 to 2 s a deal: 1.4 to 2.3 hours at 4,000, 7 to 11 at 20,000, 14 to 23 at 40,000 |
| LBR against the blueprint | about 0.001 s a hand, plus 3.8 minutes of LBR's preflop tables a run | 10 to 15 minutes for the 4 runs |
| LBR against search | 12.8 s a hand (40 hands, 752 s with the tables) | 5 to 9 s a hand: 6 to 10 hours for 4,000 hands |
| Memory | 10.7 to 10.9 GB (bench, LBR) | about 11 GB |

All of it on the Mac costs nothing. The only spending in Phase 7 so far is the leaf build if it
runs in the cloud (3a): at most $8 plus about $1.2 to download.
