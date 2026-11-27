# Phase 6: the heads-up blueprint, ready to launch

Phase 6 of the roadmap (`docs/research/README.md`): a heads-up blueprint trained with Linear
Monte Carlo CFR (external sampling) and Pluribus-style negative-regret pruning, on a rented
Google Cloud machine. Everything here is ready: when Kevin approves the spending, one
`python -m tools.cloud launch` on his computer starts the run, and every strategy it writes
can be measured afterwards with one command. Nothing has been rented or launched.

| File | What it is |
| --- | --- |
| `trainer.json` | The run: the game, the training settings, the stages. Passed to the trainer as `--config` |
| `cloud.env.example` | The `tools/cloud` settings for the run, without a project or bucket. Copy it to `~/.config/pokerscribe/cloud.env` |
| `pruning_check.py` | The small-scale check that the settings train: two runs of the Phase 6 game here, pruning on and off |
| `check.md` | Its results |
| `eval-early.md` | The evaluation command's summary on the rehearsal's first two strategy files |
| `rehearsal.log` | The dress rehearsal's output |
| `rehearsal-stages.jsonl`, `rehearsal-log.jsonl` | The trainer's stage lines (change, regrets by street, pruning counters, times, memory) and session lines (speed, table, saves) in the rehearsal |

## The run, step by step

On Kevin's computer, from the repo root.

1. **The bucket tables** (once, about 8 minutes; see "The bucket tables"):

   ```
   cd engine && cargo build --release --bin abstraction-build --bin blueprint && cd ..
   engine/target/release/abstraction-build build --out ~/abstraction/k200 --buckets 200
   engine/target/release/abstraction-build check ~/abstraction/k200
   ```

   Check that `~/abstraction/k200/build_log.jsonl` has the checksums river `e7ff8e349b9587b6`,
   turn `e8f2df9a3d04e8b8` and flop `7e143f5b92504f9b` (this machine's). If they differ, the
   tables are still valid: the run trains and is measured with Kevin's own, and every strategy
   file records their checksums. It would only mean the build differs between x86 and Arm, so
   strategy files trained with one set of tables can't be played with the other.

2. **The settings:** `cp docs/research/runs/phase6/cloud.env.example ~/.config/pokerscribe/cloud.env`,
   then fill in `PROJECT` and `BUCKET`, and read the current Spot price of c4a-highcpu-64 in
   us-central1 into `SPOT_PRICE_PER_HOUR`.

3. **Check, then launch the calibration run** (about 2 hours, $3 cap):

   ```
   python -m tools.cloud check                      # ends with "all checks passed"
   python -m tools.cloud launch
   caffeinate -i python -m tools.cloud recover      # second terminal, leave it running
   python -m tools.cloud watch --every 60
   ```

4. **Measure the calibration** once it stops at the cap (state "budget"):

   ```
   python -m tools.cloud artifacts --download ~/phase6/run1
   python tools/blueprint_eval.py ~/phase6/run1/strategy-*.bps --tables ~/abstraction/k200 --out ~/phase6/eval --b0 none
   ```

   and update the projection ("The plan").

5. **The full run** is the same run going on: raise `BUDGET_USD` to the cost agreed, then
   `python -m tools.cloud resume`. After each new stage, download and run the evaluation again
   (it measures only the new files) and read its stop rule. When it says stop, or at the cap:
   `python -m tools.cloud stop`, then the evaluation with B0 (`--b0 last`), then
   `python -m tools.cloud cleanup` and `leftovers`.

## The game and the training settings

`trainer.json`:

| Setting | Value | Why |
| --- | --- | --- |
| Stacks | 200 big blinds | The Phase 6 game of the Phase 5 projection, and Slumbot's depth (Phase 7) |
| Bet menu | `rich` | The wide menu's preflop (8 opens, 5 3-bets, 4 4-bets, 2 5-bets, each with all in), the standard menu after the flop. At 20bb more bet sizes lowered LBR at every bucket count (Phase 5) |
| Buckets | 200 a postflop street, OCHS on the river | `abstraction-build` defaults (seed 1). More buckets didn't lower LBR at 20bb, so 200 is enough to start; the table is 97,158,404 information sets, 251,686,705 slots |
| Seed | 1 | |
| Threads | 64 | The machine's vCPUs (`--threads` can override it without changing the run) |
| Regrets | 32-bit integers, 100 a big blind, floor -3.1 million big blinds | One unit a chip at 50/100 blinds, so Pluribus's integers carry over as they are: its floor was -310 million chips |
| Linear weighting | every 1,750,000 iterations up to 70,000,000 | Pluribus's schedule scaled to this run (below) |
| Pruning | from 35,000,000 iterations, threshold -3 million big blinds, probability 0.95 | Pluribus's, scaled the same way; the river is never pruned |
| `until` | 8,192,000,000 | The last stage, 1M x 2^13: past both central projections and at the high one (5.7e9 to 8.6e9 iterations: 9.7e12 states at 1,134 to 1,700 states an iteration). The stop rule or the cap ends the run sooner |
| `every_minutes` | 30 | A checkpoint every 30 minutes (below) |
| `strategies` | first 1,000,000, factor 2 | A strategy file at 1M, 2M, 4M, ... 8,192M iterations (14 stages) |

### Linear weighting and pruning: Pluribus's values, scaled to this run

Pluribus trained for 8 days (11,520 minutes) on 64 cores. It applied Linear CFR for the first
400 minutes, discounting every 10 minutes (40 discounts in the first 3.5% of the run), and
pruned from minute 200 (after the first 1.7%), with probability 0.95 and a threshold of -300
million chips, with regrets floored at -310 million. Its iterations are not published, so its
schedule is carried over as fractions of the run.

This run's length is not known until the calibration: the Phase 5 projection says 7.4e8
iterations (power law) or 4.9e9 (states per information set as at 20bb), central. The schedule
is set for a nominal run of 2e9 iterations, the geometric middle of the two (1.9e9), rounded:

- linear weighting until 3.5% of it, 70M iterations, in 40 discounts of 1.75M;
- pruning from 1.75% of it, 35M iterations;
- probability 0.95 and floor -3.1M big blinds, Pluribus's.

Both are stored in the checkpoint and can't change during the run (a resume with other settings
is refused), so the calibration run is the start of the full run, not a separate one. If the
run turns out shorter than 2e9, linear weighting covers more of it (9.5% of a 7.4e8 run); if
longer, less (0.9% of 8e9). Either way it does what it is for, discounting the first,
nearly random iterations. Carried over in minutes instead, Pluribus's 400 minutes would be
1.2e9 to 4.8e9 iterations at this run's projected speeds (50,000 to 200,000 a second), most or
all of the run, which is why the schedule is carried over as fractions.

**The threshold.** Pluribus's -300 million chips is -3 million big blinds here (the same chip
units). The cfr crate's advice is to pick it relative to the game's regret scale, so it was
checked against the regrets this game actually reaches, measured at each stage of the dress
rehearsal (`rehearsal-stages.jsonl`, `regrets`; no pruning yet, as its warm-up is 35M):

| Stage | Preflop below -10,000 bb | Preflop below -100,000 | Flop below -10,000 | Turn below -10,000 | Lowest (preflop, flop, turn) |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1M | 0.73% | 0.0044% | 0.067% | 0.019% | -193k, -122k, -72k |
| 2M | 0.63% | 0.0039% | 0.057% | 0.018% | -169k, -106k, -74k |
| 4M | 1.34% | 0.0063% | 0.17% | 0.056% | -254k, -148k, -161k |
| 8M | 2.36% | 0.0099% | 0.46% | 0.19% | -439k, -250k, -264k |

Nothing is near -1 million at 8M. Regrets grow in proportion to the iterations (the lowest
preflop regret went from -254k to -439k from 4M to 8M, both inside the linear phase, which
halves the growth; it stops halving at 70M). Extrapolating each slot at its 8M rate, a slot
at -x big blinds at 8M reaches -3M at about 35M + 1.2e13 / x iterations:

- the lowest preflop slots (about -440k) at about 55M to 60M, soon after pruning starts;
- the 0.01% of preflop slots below -100,000 by about 155M;
- the 2.4% of preflop, 0.5% of flop and 0.2% of turn slots below -10,000 by about 1.2B.

So -3M prunes nothing in the first tens of millions, starts on the worst preflop actions
(the subtrees behind a 200bb open jam with trash, say) around 60M and reaches a few percent of
preflop and flop slots in the second half of a 2e9 run, which is where most of the hours are.
A threshold 10 times nearer zero would prune those slots 10 times sooner, while they are still
moving: the risk the cfr crate warns about (an action only briefly bad gets frozen out; it is
still explored in 5% of the traversals, so it can recover, but slowly). Pruning is only a
speed-up: a threshold that prunes too little costs time, not quality. So the run keeps
Pluribus's -3M, and the calibration's stages measure what it prunes (the share of slots below
the threshold and the trainer's pruning counters, at 64M to 512M).

The small-scale check below runs these settings with every iteration count and the threshold
scaled to an 8M-iteration run.

### Checkpoints and stages

- **A checkpoint every 30 minutes**, and at every stage (a session never runs past the next
  stage, and cfr saves when a session ends). A checkpoint is 4.9 GB once the table is full; on
  the disk's free 140 MiB/s it takes about 35 seconds to write (here, on a faster disk, 8 to 10
  seconds for 3.3 to 3.6 GB), during which training waits: 2% of the time at 30 minutes. A
  preemption costs the work since the last checkpoint that reached the bucket; with the
  2-minute notice the trainer saves on SIGTERM and that save is uploaded, so usually nothing is
  lost. At a preemption every 20 hours, 30 minutes is about the best trade (the save costs
  35 s each time; a lost checkpoint costs 15 minutes on average). The save on SIGTERM (35 s) and its upload
  (reading it back off the disk, about as long) fit in the notice. Provisioned throughput
  (`DISK_THROUGHPUT_MBPS`, which costs extra) would shorten both; it is left at the free
  baseline, and `watch` shows the real times (a checkpoint written, then uploaded) in the
  calibration run.
- **A strategy file at each doubling**, 1M to 8,192M: 14 files of 0.50 GB, 7 GB in all, kept on
  the machine and in the bucket (`artifacts/`). Each stage also measures the change from the
  stage before (which needs the solver's weights, so only the trainer can do it), the regrets by
  street and the pruning counters (`stages.jsonl`). At each stage training waits for the export
  (47 to 64 seconds here) and the measures (20 to 35 seconds): about 1.5 minutes, 21 minutes over
  all 14 stages.
- **Any other checkpoint** can be turned into a strategy file off the machine: download it
  (`gcloud storage cp gs://<BUCKET>/runs/<RUN>/checkpoints/<name> .`), then

  ```
  engine/target/release/blueprint export --config docs/research/runs/phase6/trainer.json \
      --checkpoint <name> --out strategy.bps --tables ~/abstraction/k200
  ```

  It needs about 9 GB of memory and a minute or two. The bucket keeps the last 3 checkpoints.

## The bucket tables

Copied, not built on the machine. They go into the launch bundle (`TRAINER_FILES`), 138 MB,
uploaded once from Kevin's computer and downloaded by each new machine in seconds, to
`/opt/pscloud/bundle/files/k200`, the path `trainer.json` names.

- **Cheaper.** Building them takes 7.6 minutes on this machine's 4 cores (28.9 core-minutes;
  peak memory 2.9 GB). On 64 cores that would be 1 to 3 minutes of a $1.33-an-hour machine,
  plus building `abstraction-build`, and again on every new machine after a preemption that
  deletes one. Copying costs a 138 MB upload and $0.003 a month of storage.
- **Safer.** A strategy file can only be played with the tables it was trained with (their
  checksums are in its header, and loading checks them). The evaluation runs on Kevin's computer
  with his copy of the tables. Copied, the machine trains with exactly those bytes. Built on the
  machine, the run would depend on the Arm build giving the same tables as Kevin's, which is
  not tested (the build is deterministic on one machine: the same checksums here as in Phase 5).

`python -m tools.cloud check` refuses a config that names a path under
`/opt/pscloud/bundle/files/` that `TRAINER_FILES` doesn't provide.

## Sizes and costs

| | Size | Cost |
| --- | --- | --- |
| Machine | c4a-highcpu-64: 64 Arm cores, 128 GB | $1.3146 an hour Spot ($2.4243 on demand), us-central1, read 22 Nov 2026 |
| Trainer's memory | 4.6 to 6.6 GB while training in the rehearsal (86.6M information sets met), 7.4 GB in Phase 5 after a resume with the table nearly full, 8.9 GB at the peak (a stage, during the export) | 128 GB is 14 times that |
| Disk | 80 GB Hyperdisk Balanced: 4 checkpoints (19.6 GB), the strategy files (7 GB), 30 GB for the system and the Rust build | about $0.011 an hour (at the settings' rough $0.10 a GB a month) |
| External IP | | $0.005 an hour |
| Bucket | 3 checkpoints (14.6 GB), 14 strategy files (7 GB), the bundle (0.14 GB), logs | about $0.44 a month (Standard, $0.02 a GB) |
| Downloads | the 14 strategy files, 7 GB, to Kevin's computer | about $0.85 (internet egress at about $0.12 a GB; not checked against the price list) |

All in, the machine costs $1.33 an hour while it runs.

## The evaluation command

```
python tools/blueprint_eval.py <strategy files> --tables ~/abstraction/k200 --out <folder> [--b0 last|all|none]
```

For the files given, sorted by their iterations:

1. **LBR**, `fcpa14` (LBR betting only the pot and all in, which are menu bets, thinking from
   the preflop) and `b56_14` (56 bet sizes from 5% of the pot to all in), 20,000 hands, seed
   6001, the same deals for every file, every deal's result kept. Each file is compared with the
   one before it and the last with the first, deal by deal (`blueprint compare`).
2. **Head to head** in the arena, each file against the one before it and the last against the
   first: 200,000 deals, each played twice with the seats swapped, all-in hands scored by their
   equity, bb/100 with its standard error, 200bb, seed 6101. About 2 seconds of play and 15 of
   loading the two files for each pair.
3. **B0 heads-up** (`tools/b0_arena.py`) against the last file (`--b0 all`: every file), at 200
   big blinds, split over one process per core with seeds 6201, 6202, ... and pooled. It reports
   the standard deviation per deal and the hands a 2.5 SE result needs at 5, 10 and 20 bb/100
   and at the edge measured.
4. **The change** at each stage, from `stages.jsonl`.

It writes `summary.md` and `summary.json`: the tables, the stop rule at each stage, and the gate
under each wording. Work already in the folder is reused, so after each new stage it measures
only the new file.

**Why B0 plays at 200 big blinds.** The blueprint's game is 200bb: its stacks are part of every
information set, so at another depth it would play a game it wasn't trained for, and the match
would measure the mapping more than the blueprint. 200bb is also Slumbot's depth, the Phase 7
benchmark, so the two results can be read side by side. B0 reads the stacks from the spot and
plays any depth; it is frozen, so its 200bb play is the floor the gate asks about.

**LBR's start-up.** With `14` settings LBR works out exact preflop win probabilities the first
time each starting hand comes up: 3.5 to 4 minutes on 4 cores here, then 1,100 hands a second
(`b56_14`) at 200bb. So the command runs every file and setting in one LBR process
(`blueprint lbr --strategy A,B,...`, changed for this), which pays it once.

**The projection** at the end of the summary: a straight line through the change against the
iterations (both on log scales) over the last 4 stages gives the factor the change is multiplied
by at each doubling, the stage where the stop rule could first say stop, and, at the trainer's
last speed (`log.jsonl`, downloaded with the strategy files), the hours left.

### On the rehearsal's first two files

`python tools/blueprint_eval.py strategy-1000000.bps strategy-2000000.bps --tables ~/abstraction/k200
--out eval-early --b0-processes 4`, here, on two files of the dress rehearsal (`eval-early.md` is
its summary). At 0.05% and 0.1% of the nominal run they are nearly random, so the numbers only
show that every measurement works, and what each costs.

| Measurement | 1M | 2M | 2M against 1M |
| --- | ---: | ---: | ---: |
| LBR `fcpa14`, bb/100 | +311 ± 34 | +264 ± 30 | -48 ± 36 (z -1.3) |
| LBR `b56_14`, bb/100 | +476 ± 36 | +394 ± 32 | -81 ± 39 (z -2.1) |
| Head to head, 20,000 deals | | | 2M wins +150.4 ± 14.2 (z +10.6) |
| B0, 4,000 deals | | the blueprint loses -96 ± 20 (z -4.7) | |

- **LBR**: 3.7 minutes once for the exact preflop equity, then 6 seconds (`fcpa14`) and 17 to
  19 seconds (`b56_14`) per file at 20,000 hands. All 14 stages at 20,000 hands take about 10
  minutes; at 200,000 hands (an SE of about 10 bb/100) about an hour and a half.
- **Head to head**: 40,000 hands of play in 0.14 seconds, plus loading the two files.
- **B0**: 15 to 18 hands a second per process at 200bb (41 to 43 ms an instruction, about 1.5
  instructions a hand), 61 a second on 4 processes. 11,752 instructions, none that couldn't be
  played as said and none flagged by the simulator's always-wrong checks.
- **B0's sd** was 1,291 bb/100 a deal (two hands), against 300 to 400 for B0 against the bots
  at 100bb. At that sd a 2.5 SE result needs 833,000 hands at an edge of 5 bb/100, 208,000 at
  10 and 52,000 at 20: on a computer with 10 cores at 16 hands a second each, 1.4 hours, 22
  minutes and 5 minutes. A nearly random 200bb strategy plays very large pots, so the sd against
  a trained one may be quite different; the summary measures it again on every file B0 plays.

## The dress rehearsal

`python -m tools.cloud local-test --trainer engine/target/release/blueprint --config
docs/research/runs/phase6/trainer.json --files ~/abstraction/k200 --trainer-args "--threads 4"`:
the real supervisor, the real trainer, `trainer.json` unchanged except the tables' path, a
folder as the bucket, on this machine's 4 threads. 19.2 minutes in all; output in
`rehearsal.log`.

| Step | What happened |
| --- | --- |
| Machine 1 | Fresh start. Stages at 1M and 2M (strategy file, change, regrets, pruning counters), both uploaded |
| SIGTERM, as Google sends on a preemption | The trainer saved at 2,038,070 iterations and exited 75, 12.7 seconds after it; the save was uploaded |
| Machine 2, empty disk | The checkpoint and the 4 artifacts came back from the bucket; the trainer resumed at exactly 2,038,070, 15.0 seconds after the start |
| Stages 4M and 8M | The 4M stage measured its change from the restored 2M file (0.1869); 8M from 4M (0.2051) |
| `stop` marker | Stopped 13.5 seconds after it, saved at 8,033,450, uploaded; state "stopped" |

Measured, for the rented machine:

- **Memory**: 4.6 to 6.6 GB resident while training (`log.jsonl`), 6.0 to 7.9 GB at the
  stages and 8.86 GB at the most, during an export. `TRAINER_MEMORY_GB=9`; 128 GB is 14 times
  it.
- **Checkpoint**: 3.34 GB at 2M iterations (86.6M of the 97.2M information sets met by 8M), 4.87
  GB once all are; saves took 8.9 to 10.2 seconds here.
- **A stage**: the export took 47 to 64 seconds and the measures (change and regrets) 20 to 35,
  one thread, while training waits.
- **Speed**: 10,000 to 13,700 iterations a second on 4 threads (6.9M to 10.1M states a
  second, 656 to 972 states an iteration), as in Phase 5.
- **The bucket** held 14.6 GB at the end: 3 checkpoints and the artifacts.
- **The change** from each stage to the next: 0.120 (1M to 2M), 0.187, 0.205. It grows at first:
  inside the linear phase the strategy is still leaving uniform play.

## The small-scale check of the settings

TBD_CHECK

## The plan

### Before the first paid run

1. **The cheap real test** (`tools/cloud/README.md`, "The cheap real test"): the fake trainer on
   a c4a-standard-1 for about 17 minutes, a stop as Google would, `recover`, a new machine from
   the bucket. A few cents. It checks the Google side, which nothing here can (nothing was
   rented), on the same Arm family.
2. `python -m tools.cloud check` with the Phase 6 settings: the machine type in the zones, its
   memory against `TRAINER_MEMORY_GB`, the disk against `CHECKPOINT_GB` and `ARTIFACTS_GB`,
   the tables in `TRAINER_FILES`, the price, the budget. It ends with "all checks passed".

### The calibration run: about 2 hours, $3

`BUDGET_USD=3` in `cloud.env.example`. At $1.3306 an hour that buys 2.25 hours: `launch` sets
Google's own stop (`--max-run-duration`) to 2 hours 15 minutes, and the supervisor stops the
trainer 15 minutes before the cap (`BUDGET_MARGIN_MINUTES`), saves and uploads. About 2 hours of
training, less the start (installing Rust and building the trainer, a few minutes, not timed on
Arm).

At the Phase 5 projection's speeds (57M, 112M and 227M states a second at about 1,134 states an
iteration) 2 hours reach the stage at 256M (slow), 512M (central) or 1,024M (fast): 9 to 11
strategy files. Each stage pauses training about 1.5 minutes (the export and the measures run
on one thread), so 9 to 11 stages cost 14 to 17 minutes of the 2 hours, most of them in the
first minutes, where the stages come quickly. What it gives:

- **the speed on 64 Arm threads**, measured (`watch`, and `log.jsonl`): it replaces the three
  guesses of the projection (an Axion core against a Xeon core, 64 threads against 64 times one,
  the table met), which make a factor of 4 between slow and fast;
- **the change at each doubling** and the regrets by street (`stages.jsonl`), with what pruning
  skipped from 35M on;
- **LBR and head to head at each stage**, on Kevin's computer, with
  `python -m tools.cloud artifacts --download ~/phase6/run1`, then
  `python tools/blueprint_eval.py ~/phase6/run1/strategy-*.bps --tables ~/abstraction/k200 --out ~/phase6/eval --b0 none`
  (about 10 minutes for LBR at 20,000 hands, a few minutes for the downloads);
- **the projection** at the end of the summary: the stage where the change reaches 0.08 at the
  rate it fell over the last 4 stages, and the hours left at the measured speed. It narrows the
  factor of 100 in the Phase 5 projection, most of which is the work, to whatever the curve
  shows; if the change hasn't started to fall by then (as in the rehearsal's first 8M), the
  projection says so, and the high estimate below stands.

### The full run

The same run going on: raise `BUDGET_USD` and `python -m tools.cloud resume` (a resume with
other settings would be refused, so nothing about the run changes). `recover` stays running on
Kevin's computer for preemptions.

- **The stop rule** (Phase 5's, `runs/phase5_gate/plan.json`): stop at the first stage where the
  strategy changed by at most 0.08 since the stage before, and LBR `b56_14` moved by less than
  3% of its value or less than 2 standard errors of the paired difference. After each new stage
  (every doubling, so the stages come further apart: at the central speed 512M to 1,024M takes
  about 85 minutes, 4,096M to 8,192M about 11.5 hours), download and run the evaluation again; it
  measures only the new file. When the summary says "stop here":
  `python -m tools.cloud stop`, then the evaluation with B0 (`--b0 last`), then `cleanup` and
  `leftovers`.
- **Stages are doublings**, so the run trains on to the first stage past the point where the
  change reaches 0.08: up to twice the iterations that point needs. A stop by hand at any time
  (`stop`) keeps the last checkpoint, which can be exported (above) and judged like any stage,
  but without a change measure.
- **The cap.** The stop rule decides when to stop; `BUDGET_USD` decides what is the most it can
  cost. Set it from the calibration's projection, with room: the hours to the stage the
  projection names, and 20% more.
- **The cost**, machine and disk at $1.33 an hour, at the projection's speeds and 1,134 states
  an iteration, if the calibration doesn't change the projection:

  | Estimate | Iterations needed | Stage where it can stop | Hours to that stage | Cost |
  | --- | ---: | --- | ---: | ---: |
  | Central, power law in iterations (central speed) | 7.4e8 | 1,024M | 2.9 | $3.80 |
  | Central, states per information set as at 20bb (central speed) | 4.9e9 | 8,192M (4,096M if the change is a little faster) | 23.0 (11.5) | $30.60 ($15.30) |
  | High: the 20bb model's high work at the slow speed | 5.7e9 to 8.6e9 | 8,192M, the end of `until` | 45.3 | $60.30 |

  The Phase 5 projection's hours (2.5, 13.9 and 46.9) are to the point itself; the table adds
  the rest of the doubling. If the run reaches 8,192M without the stop rule saying stop, the
  run is past every projection, and going on is a decision for Kevin, not for the cap.

  plus 21 minutes of stage pauses at most (14 stages, $0.47), the bucket (about 22 GB, $0.44 a
  month while it is kept) and downloading the strategy files (7 GB, about $0.85). A preemption
  costs the minutes to restart and, if a checkpoint is lost, up to 30 minutes of training.

## The gate: waiting for Kevin's decision

The roadmap's wording now: **"LBR falls at every checkpoint; beats B0 heads-up by 2.5 SE."**
Kevin is deciding whether to keep it. Phase 5 found that at 20bb LBR rose as training went on
in every run (the blueprint's strategy sharpens and LBR's off-menu bets find more to exploit),
and about 18% of the blueprint's decisions against LBR's 56 sizes are off the menu, so "falls at
every checkpoint" may not hold for a blueprint that is training well.

The evaluation measures every wording below for any list of files, and its summary ends with
each reading. Which files are "the checkpoints", and which is "first", is decided by the files
given: the 14 stages by default; any other list, such as the stages from 64M on, works the same.

| Wording | Measured by | Passes when |
| --- | --- | --- |
| (a) As written: LBR falls at every checkpoint | LBR (`fcpa14` and `b56_14`), each file against the one before, deal by deal on the same deals | the paired difference is below zero at every step, for the setting chosen. The summary also counts the steps where it fell by 2.5 SE and rose by 2.5 SE, since at 20,000 hands most steps late in a run will be within noise |
| (b) The last checkpoint beats the first head to head by 2.5 SE | the arena, last against first, duplicate deals, all-in equity | z ≥ 2.5 |
| (c) LBR with menu bets only falls from first to last | LBR `fcpa14` (bets of the pot and all in only, so off-menu mapping plays no part), last against first, deal by deal | the paired difference is below zero (the summary also says whether by 2.5 SE) |
| In every case: beats B0 heads-up by 2.5 SE | `tools/b0_arena.py` at 200bb against the last file, pooled over processes | z ≥ 2.5 |

Points to weigh:

- **"First" matters for (b) and (c).** The first stage is at 1M iterations, a nearly random
  strategy (the 2M file beat the 1M one by 150 bb/100), so last against first passes easily.
  A stricter reading is the first file after the linear phase (128M), or the stage before the
  last.
- **(a) needs enough hands.** At 20,000 hands an LBR difference has an SE of 30 to 40 bb/100,
  so late steps that move a few bb/100 fall or rise at random, and 13 steps all falling would
  then happen by chance about once in 8,000 times. Judged on "every step falls by 2.5 SE",
  it would need far more hands than any step's difference supports. `--lbr-hands` sets the
  hands (200,000 is about an hour and a half for 14 files).
- **B0**: the hands follow from the sd and the edge, both measured by the first match
  (`--b0-deals`, default 4,000). A suggestion, to pre-register when Kevin decides: after the
  stop, 4,000 deals (seed 6201 on) to measure them, then a match of the deals the summary says
  the measured edge needs, twice over, on fresh seeds (`b0_arena.py --seed` 7201 on), judged
  on that match alone.
