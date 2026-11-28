# Phase 7: search against the blueprint at 200 big blinds, ready to launch

Phase 7 of the roadmap (`docs/research/README.md`): depth-limited search on every postflop
decision, on the Phase 6 blueprint (it512M: `strategy-512000000.bps`, 200 big blinds, the
`rich` menu, 200 buckets). The search crate is `engine/crates/search`; its groundwork at 20
big blinds is in `experiments.md`, "Phase 7 groundwork".

The gate (Kevin, 27 Nov 2026) has three conditions: the search beats the blueprint head to head
by 2.5 SE, a luck-adjusted Slumbot match, and the GTO Wizard Benchmark. This folder covers the
first: the head-to-head match, with LBR and decision time reported beside it. **Slumbot and the
GTO Wizard Benchmark are left for later**, with their own plan, once this condition is read.

**Everything runs on one rented machine, as one `tools/cloud` job.** Kevin's MacBook Air (M3,
8 GB) can't hold the leaf tables (22.2 GB), so the Mac only launches the run, watches it,
downloads the results and summarizes them. Nothing has been run on it512M and nothing has been
launched or rented. The plan is pre-registered in `docs/research/experiments.md`, "Phase 7: the
plan at 200 big blinds (28 Nov 2026)", and is binding as written there; `phase7.json` carries
its seeds and sizes, and this README is the runbook. Everything is offline and against our own
agents (rule 4).

| File | What it is |
| --- | --- |
| `phase7.json` | The plan as the job's `--config`: the leaf build, the gate agent, the bench and its bounds, the pilot, the size rule, the gate, the two variants, LBR and the repeat |
| `cloud.env.example` | The `tools/cloud` settings for the run, without a project or bucket |
| `gate.py` | Reads the downloaded results, checks the job's bound check, N, pooling and pass against the plan, and writes `summary.md` and `summary.json` |
| `plan_rehearsal.py` | The dress rehearsal of the whole job under the real `tools/cloud` supervisor, run here ("The dress rehearsal") |

## The run, step by step

On Kevin's Mac, from the repo root. Nothing is built or played on the Mac.

1. **The files** (Phase 6's): `git pull`, then
   `ls -l ~/phase6/run1/strategy-512000000.bps ~/abstraction/k200`. If they are elsewhere,
   change `TRAINER_FILES` in step 2.

2. **The settings:**
   `cp docs/research/runs/phase7/cloud.env.example ~/.config/pokerscribe/cloud-phase7.env`, then
   fill in `PROJECT`, `BUCKET` and `SERVICE_ACCOUNT` (Phase 6's), and read the current Spot
   price of c4a-highcpu-64 in us-central1 into `SPOT_PRICE_PER_HOUR` ($1.445888 on 27 Nov
   2026). It is a separate file so Phase 6's `cloud.env` stays as it was; every command below
   names it through `P`.

3. **Check and launch** (about 10 to 14 hours, capped at $30, with LBR at 10,000 hands; "Sizes
   and costs" has the other LBR sizes):

   ```
   P="--settings $HOME/.config/pokerscribe/cloud-phase7.env"
   python -m tools.cloud $P check                    # ends with "all checks passed"
   python -m tools.cloud $P launch --dry-run
   python -m tools.cloud $P launch
   caffeinate -i python -m tools.cloud $P recover    # second terminal, leave it running
   python -m tools.cloud $P watch --every 60
   ```

   The job plays the steps of "The plan" in order. `watch` shows the progress of the step being
   played: the leaf build in deals (34 parts of 16,000,000, so 544,000,000 at the end), then
   each match in deals and LBR in runs; the time left it shows is the step's. The trainer's
   own lines (`logs/<session>-trainer.log` in the run's folder of the bucket) name each step
   and its result as it ends. A Spot preemption costs at most the run being played (a part of
   the build, about 3 minutes; a chunk of 2,000 deals, about 8; an LBR run against the search,
   about 17): the next machine gets the parts and the results back and goes on from them.

4. **If it stops early:**
   - `end.json` says "a street is over its bound: no match was played": the job ended after the
     bench, by the plan. Download (step 5) and tell the manager session; don't change the bound.
   - The cap stops it ("budget"): raise `BUDGET_USD` and `python -m tools.cloud $P resume`.
     The parts and the results done are kept.

5. **The results**, when `recover` exits and `watch` says done:

   ```
   python -m tools.cloud $P artifacts --download ~/phase7/run --only '*.json'
   python -m tools.cloud $P artifacts --download ~/phase7/run --only '*.deals'
   python3 docs/research/runs/phase7/gate.py ~/phase7/run
   ```

   About a megabyte; the parts stay in the bucket. `gate.py` recomputes the bound check, the
   measure, N, the gate's pooled result and its pass from `phase7.json` and the downloaded
   files, says so (and exits 1) if any differ from the job's, and writes
   `~/phase7/run/summary.md`, with AIVAT and the plain figure side by side. The gate's
   head-to-head condition is read there, by the rule in "The plan".

6. **Clean up:** `python -m tools.cloud $P cleanup`, then `python -m tools.cloud $P leftovers`
   (only the bucket). The 34 parts (22.2 GB) stay in the bucket at about $0.44 a month: a later
   run on the same tables (Slumbot, the GTO Wizard Benchmark) gets them back instead of building
   them again. Delete them once nothing needs them:
   `gcloud storage rm -r gs://<BUCKET>/runs/hu-phase7-512m`.

7. **To the manager session:** `~/phase7/run` without the `*.deals` files, copied into
   `docs/research/runs/phase7/results/` for the write-up in `experiments.md`.

## The plan

Pre-registered in `experiments.md`, "Phase 7: the plan at 200 big blinds (28 Nov 2026)",
written before any run on it512M; `phase7.json` is its machine form. In short:

| Step | Size | Seeds | What it gives |
| --- | --- | --- | --- |
| 1. Leaf tables | 16M deals, 16 lanes, 34 parts of 256 turn starts | 7 | the values at the flop's leaves |
| 2. Bench | 200 hands against the blueprint, 4 threads, one decision at a time | 7581 | decision time per street; **the bound check**: over it, the job ends here |
| 3. Pilot | 2,000 deals | 7501 | the AIVAT sd a deal, for N; never pooled |
| 4. Size | | | N by the rule below, the chunks and their seeds (`size.json`) |
| 5. **Gate match** | N deals, chunks of 2,000 | 7601, 7602, ... (chunk k: 7600 + k) | **the gate's head-to-head condition** |
| 6. Variant `modicum` | 8,000 deals, 4 chunks | 7801 to 7804 | reported: only the opponent chooses at the leaves |
| 6. Variant `final` | 8,000 deals, 4 chunks | 7901 to 7904 | reported: the gate agent playing the last iteration |
| 7. LBR `fcpa14` | 10 runs of 1,000 hands against each agent | 7301 to 7310 | reported |
| 7. LBR `b56_14` | 10 runs of 1,000 hands against each agent | 7401 to 7410 | reported |
| 8. Repeat (only after a pass) | N deals, chunks of 2,000 | 7701, 7702, ... | for promotion (CLAUDE.md ground rules) |

- **The gate agent**: the search agent at the plan's commit with `Settings::default()`'s caps
  (flop 1% of the pot or 400 iterations, turn 2% or 300, river 0.5% or 1,000; combos under
  0.1% of the largest weight left out), **both players choosing at the flop's leaves**
  ("Both players choose at the leaves") and playing the **average** strategy of its solves, on
  it512M with the leaf tables of step 1. Its opponent is it512M itself, played as the blueprint.
- **Every match**: duplicate deals (each deal played twice with the seats swapped), 200 big
  blinds, the arena's heads-up rules, on the machine's 64 threads, scored two ways on the same
  hands, each as bb/100 with its SE over deals:
  - **AIVAT, the measure**: the arena's estimator at its defaults, shown unbiased in
    `experiments.md`, "Phase 7: AIVAT in the arena". It takes out the luck of every card and
    of both agents' choices (both report the chances they played with); the blueprint also
    says what it would play at situations the hand didn't reach, the search agent doesn't.
  - **The plain figure**, beside it: the all-in equity adjustment (a hand all in before the
    river is scored by its equity over the cards to come).

  Each chunk of 2,000 deals is a match with its own seed; chunks pool by deals (mean weighted
  by deals, SE = sqrt(sum((n x se)^2)) / sum(n)), each figure on its own.
- **When AIVAT can't be used**: a result without an AIVAT figure, or with an unexplained
  decision of either agent (chances it reported that can't be the ones it played with), is read
  on the plain figure instead, with the same N and rule. The job and `gate.py` both apply this,
  to the pilot, the gate match and the repeat, and say why.
- **N** = (2.5 x sd / 10)^2 deals, with sd the pilot's AIVAT sd a deal (bb/100): the deals that
  see an edge of 10 bb/100 at 2.5 SE. Rounded up to a multiple of 2,000, at least 4,000, at
  most 40,000. At sd 400 that is 10,000 deals; from sd 780 the cap holds it to 40,000, and the
  edge seen at 2.5 SE is 2.5 x sd / 200 bb/100. `size.json` also gives the plain figure's sd
  and the N it would have given.
- **The pass rule**: the gate's head-to-head condition passes when the pooled gate match is at
  z = bb/100 / SE >= 2.5 on AIVAT, read on that match alone. Anything below is "does not pass":
  no extra deals, no second try on other seeds, no pooling with the pilot, the variants or the
  repeat. The plain figure and its z are reported beside it, not judged.
- **For promotion**, beyond the gate (CLAUDE.md, ground rules): the repeat on fresh seeds (7701
  on, the same N) also at z >= 2.5, read alone and the same way, and LBR winning less against
  the search than against the blueprint. The job plays the repeat only after the gate match
  passes.
- **The variants**, reported, not judged: the same matches and chunk size against the
  blueprint, on their own seeds. Each is compared with the gate agent unpaired (SE =
  sqrt(se1^2 + se2^2)) on AIVAT, the plain difference beside it; at an AIVAT sd of 500 that is
  about ±7 bb/100, so only a difference above about 17 bb/100 shows at 2.5 SE.
- **LBR**, reported, not judged: `fcpa14` (fold, call, pot, all in) and `b56_14` (56 sizes),
  against the gate agent and the blueprint on the same seeds, so each run is paired deal by deal
  (`compare-SETTING-K.json`). 10,000 hands a setting against each agent: at Phase 6's spread
  (about 50 big blinds a hand) that is about ±50 bb/100 for each agent and ±58 for the
  difference, so a fall of more than about 145 bb/100 shows at 2.5 SE. Kevin chooses the size
  before the launch: `lbr.chunks` in `phase7.json` is 10 (±50), 28 (±30) or 2 (±110), with
  `BUDGET_USD` to match ("Sizes and costs"). LBR against the search is most of the run's cost.
- **Decision time**: the bench's p50, p95 and slowest decision per street on 4 threads, checked
  against the bound ("Decision time"). The match's and LBR's solve times are reported beside
  it, not checked.
- **Hardware**: one c4a-highcpu-64 (64 Arm Axion cores, 128 GB), Spot, through `tools/cloud`.
- **Why AIVAT**: the roadmap's decisions of 28 Nov 2026 let gate SEs come from AIVAT once it is
  shown unbiased, with the plain figure beside it. It passed all six of its pre-registered
  checks, and it needs 37% to 40% of the deals for the same SE (an SE ratio of 0.61 on the
  search groundwork's setup). This was settled before any run on it512M.
- **Later, not in this plan**: preflop search of off-menu raises (`experiments.md`, the plan's
  "Options and later work").

## Both players choose at the leaves

At each of the flop's leaves (a turn start) the search values the rest of the hand from the
leaf tables: for each pair of flop buckets, what each player wins if both play on in a given way.
Modicum lets only the opponent choose among four continuations there (the blueprint, or the
blueprint biased toward folds, calls or raises), so the tables hold 7 lanes: the blueprint for
both, and the three biased ones for each player. Pluribus lets both players choose: 16 lanes,
one for each pair of choices (`sb x 4 + bb`), and at each leaf of the flop solve both players
pick a continuation without seeing the other's pick (a small simultaneous game, solved with the
rest of the tree). The 16 lanes contain the 7 bit for bit (the pairs where one player plays the
blueprint; tested), so one build serves both, and the `modicum` variant plays on the same tables.

| | 7 lanes (Modicum) | 16 lanes (both choose, the plan) |
| --- | --- | --- |
| Table file | 9,709,280,000 bytes of values (9.7 GB) | 22,192,640,000 (22.2 GB) |
| Build time, measured here (the same four parts) | 1 | 1.35 times (1.29 to 1.40 a part) |
| The build's peak memory | 1.54 GB | 2.65 GB |
| Flop solve, one spot, 400 iterations | 1,056 ms | 3,546 ms (3.36 times) |
| A deal of a match | 1 | about 1.42 times (the flop is about 18% of the solve time in the bench) |

The flop's leaf values are read lane by lane, so both players choosing costs 3.4 times on the
flop. Laying the table out with a cell's 16 lanes side by side would cut that; it is later work,
not needed for this plan.

## Decision time

There is no time limit: every decision runs at most one solve of its street, to a target or an
iteration cap, and a decision that reuses its street's solve takes under a millisecond. A
street's tree is the blueprint's menu plus the real off-menu actions on it. So the slowest
decision is bounded by the largest tree at the cap:

- cost = solver nodes x combos (both ranges) x iterations x the cost of one, measured in the
  groundwork: 0.0105 microseconds on the turn (3.2 times faster on 4 threads; the river taken as
  the same), 0.19 on the flop (2.5 times faster on 4 threads);
- turn: 13,857 nodes (the largest tree in the pilots here) x 2,256 combos x 300 = 31 s on 4
  threads; river: 81 nodes x 2,162 x 1,000 = 0.6 s; flop: 81 nodes x 2,352 x 400 = 5.8 s with
  one player choosing, times 3.4 with both: 20 s;
- a re-solve after an off-menu bet adds that bet's subtree: taken as at most twice the tree.

**The bound**: twice the worst case at the caps on this container's CPU, rounded up: **flop
40 s, turn 65 s, river 2 s**, for the slowest decision of each street in the bench (4 threads,
one decision at a time, on the rented machine). An Axion core is a little faster than a thread
here, so it is a loose bound: it catches a solve whose tree or iterations are not bounded, not a
slow machine.

Measured here on the 2M-iteration blueprint with 7 lanes, only the opponent choosing (nearly
random, so its ranges are wide and its solves at the large end; 4 threads):

| Bench, 200 hands, seed 9501 | Decisions | p50 | p95 | Slowest | Solver nodes (mean) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flop | 45 | 745 ms | 1,303 ms | 1,442 ms | 79 |
| Turn | 28 | 4,956 ms | 18,346 ms | 21,322 ms | 13,051 |
| River | 14 | 107 ms | 268 ms | 583 ms | 80 |

184 s for the 200 hands, all within the bound (both choosing, the flop's slowest would be about
4.9 s). The 22 GB tables of the both-choose agent at 200 big blinds don't fit in this
container's 15 GB, so the bench on it512M (step 2) is the first one of that agent at this
depth; the flop solver's tests and the both-choose agent's test cover it at small sizes.

In a match the turn is solved on one thread, with the other deals in parallel, so a match
decision on the turn can take several times as long as in the bench. Against LBR `b56_14` (40
hands, seed 9503) the search re-solved 157 of 302 flop solves, 106 of 205 turn solves and 58 of
60 river solves.

## The job

`search --config phase7.json --checkpoint-dir DIR [--resume]` keeps the `tools/cloud` trainer
contract (`tools/cloud/README.md`, "The trainer"; `engine/crates/search/README.md`, "The Phase 7
plan as a cloud job"). A config with a `gate` is a plan; one without is the leaf build alone, as
before.

- **The checkpoint** is `plan.ckpt`: the plan's fingerprint (the config and the strategy file's
  hash) and the step. A checkpoint from another plan is refused.
- **The artifacts**, uploaded as they are written and put back on a new machine before the job
  starts: the leaf table parts (`*.leafpart`, 0.65 GB each) and every result (`*.json`,
  `*.deals`). The table file itself (22.2 GB) is not uploaded: a new machine puts it together
  from the parts again (a few minutes) and builds no part.
- **A stop**: every run (loading the tables, the bench, a chunk, an LBR run) plays on a worker
  thread while the job watches for SIGTERM; on it the job gives up that run and exits 75 within
  a second (the build gives up its part). Results are written whole and then renamed, and a step
  skips the results already there, so nothing done is played again and a run cut off is played
  again from its start, with the same seed and the same result.
- **The end**: exit 0 after `end.json`, either "every step is played" or "a street is over its
  bound: no match was played".

| File | What it holds |
| --- | --- |
| `part-NNNNN.leafpart` | the leaf table parts (34) |
| `bench.json`, `bounds.json` | decision time per street; the bound check |
| `pilot.json`, `size.json` | the pilot's match report; N, the chunks, their seeds and the projected hours |
| `match-NN.json`, `gate.json` | the gate's chunks; the pooled result, with `pass_z` and `passes` |
| `variant-NAME-NN.json`, `variant-NAME.json` | the variants' chunks; pooled, with the agent and the difference from the gate agent |
| `lbr-WHO-SETTING-K.json`, `lbr-WHO-SETTING-K.deals` | each LBR run (WHO `blueprint` or `search`): the summary, with the search's solves by street, and the deals |
| `compare-SETTING-K.json` | LBR against the search minus against the blueprint, paired |
| `repeat-NN.json`, `repeat.json` | the repeat, after a pass |
| `end.json` | how the job ended, with every pooled result |

### The dress rehearsal

`plan_rehearsal.py` runs the real supervisor (`tools/cloud/supervisor.py`) with a local folder
as the bucket, the settings of `cloud.env.example` and the plan of `phase7.json` with its sizes
cut down (leaf 20,000 deals in 6 parts of 2 turn starts, 16 lanes; caps of 40, 16 and 60
iterations; bench 4 hands; pilot 32 deals; N 64 deals in chunks of 32; variants 1 chunk; LBR 8
hands), on a 10 big blind blueprint (11 turn starts) with k200 and 4 threads. It passed here in
228 s:

| Step | What happened |
| --- | --- |
| Machine 1 | Fresh start: the 6 parts, the bench, the bounds, the pilot, N and the gate's first chunk, each uploaded as written |
| SIGTERM to every process, as Google sends on a preemption | The job gave up the second chunk and exited 75; the supervisor was done 0.2 s after the signal, with the checkpoint and 11 results in the bucket |
| Machine 2, empty disk | The checkpoint, the parts and the results came back; the job resumed 0.5 s after the start, put the table file together from the parts (no part built), skipped the bench, the pilot and the first chunk, and played the rest |
| The end | "every step is played"; 28 results in the bucket, the first chunk unchanged, no table file; both sessions counted; the trainer's peak 0.65 GB |

`gate.py`, run on the rehearsal's results with its plan, found no difference from the job's
bound check, N, pooling and pass, and wrote the summary.

The binary's contract at 16 lanes (SIGTERM after the size step: exit 75 within 5 s, last line
"saved on SIGTERM"; resumed: first line "resumed", last "done") is also tested in
`engine/crates/search/tests/cloud_job.rs` (nightly), and the job in process, with a stop, the
refusals, the resume and the table file equal to a build in one piece, in `tests/agent.rs`.

## Sizes and costs

| | Size | Cost |
| --- | --- | --- |
| Machine | c4a-highcpu-64: 64 Arm (Axion) cores, 128 GB | $1.445888 an hour Spot |
| Memory | about 45 GB in a match: the 16-lane tables (22.2 GB, one copy for every deal), the blueprint (0.5 GB) and up to 63 blocks of deals in play at about 0.33 GB each (0.23 measured here with 6 blocks in play, plus up to 0.1 for the flop's leaf values with both choosing). 70 GB if every block's solve were as large as the bench's single one | 128 GB is 2.8 times the 45 GB |
| Disk | 120 GB Hyperdisk Balanced, 400 MiB/s: the parts (22.2 GB), the table file (22.2 GB), the bundle (0.64 GB) and 30 GB for the system and the Rust build | $0.0132 an hour for the GB and $0.0142 for the throughput |
| External IP | | $0.0025 an hour |
| In all | | **about $1.476 an hour** |
| Bucket | the parts (22.2 GB) and the results | about $0.44 a month until deleted |
| Downloads | the results, about a megabyte | nothing to speak of |

**The speed assumed**: this container's (4 vCPU, Intel Xeon at 2.1 GHz) on the 2M-iteration
blueprint, which is an upper bound for it512M (its narrower ranges make smaller solves); an
Axion core taken as 1.15 of a thread here (1.1 to 1.2, from Phase 6's training speed on it
against this container's); 64 threads. Measured here: the leaf build 96 thread-hours at 7
lanes (1.60M walks a second on 4 threads), a match 12.3 thread-seconds a deal (3.07 s a deal on
4 threads, 60 deals), LBR against the search about 52 thread-seconds a hand. The arena plays a
chunk's 2,000 deals in blocks of 32 on its threads, so a chunk is one round of 63 blocks, 32
deals one after the other on each thread, and it lasts as long as its slowest block. A 192-deal
match here with every core busy (6 blocks in play) took 7.7 core-seconds a deal; the table keeps
the 60-deal match's 12.3 (cores partly idle), which leaves about 1.6 times for that tail. At 7.7
the plan with the repeat at N = 40,000 would be 22.0 hours, $32.5.

| Step | 16 lanes, both choose (the plan) | 7 lanes, Modicum |
| --- | ---: | ---: |
| Start: the machine, the Rust build | 0.25 h | 0.25 h |
| The leaf build | 1.76 h | 1.30 h |
| The table file put together and loaded | 0.05 h | 0.05 h |
| **The build** | **2.1 h, $3.0** | **1.6 h, $2.4** |
| Bench and pilot | 0.22 h | 0.16 h |
| A chunk of 2,000 deals | about 8 minutes | about 6 minutes |
| Gate match, N from 4,000 to 40,000 | 0.27 to 2.70 h | 0.19 to 1.90 h |
| Variants, 8,000 deals each | 0.92 h (both) | 0.38 h (`final` only) |
| LBR, 2 settings x 28,000 hands against each agent | 15.7 h | 11.1 h |
| Upload at the end | 0.08 h | 0.08 h |
| **The matches and LBR** | **17.2 to 19.6 h, $25.4 to $29.0** | **11.9 to 13.6 h, $17.6 to $20.1** |
| **In all, without the repeat** | **19.3 to 21.7 h, $28.4 to $32.0** | **13.5 to 15.2 h, $19.9 to $22.5** |
| The repeat, only after a pass | 0.27 to 2.70 h | 0.19 to 1.90 h |
| **In all, with the repeat** | **19.5 to 24.4 h, $28.8 to $36.0** | **13.7 to 17.1 h, $20.2 to $25.3** |
| **Cap (`BUDGET_USD`)** | **$50** | $35 |

The ranges are N, from the rule's floor to its cap; the cap is the likely case (sd 946 and 1,377
here). Both players choosing costs about 40% more than Modicum: $9.5 more at N = 40,000 without
the repeat, $10.7 with it. The plan is the 16-lane one: it is the only one that can play the
both-choose gate agent, and it plays Modicum too, as a variant. The 7-lane plan would be a change
to `phase7.json` (`lanes` 7, the gate agent `opponent`, the `final` variant only) and to the
pre-registration, made before the launch.

LBR is most of the cost. Its size decides how small a difference it can see (16 lanes; each
setting, against each agent):

| LBR hands | SE each | SE of the difference | Hours | Dollars | The plan with the repeat, and a cap |
| ---: | ---: | ---: | ---: | ---: | --- |
| 2,000 | ±112 | ±130 | 1.2 | $1.8 | 9.9 h, $14.6; cap $20 |
| 10,000 | ±50 | ±58 | 5.7 | $8.4 | 14.4 h, $21.2; cap $30 |
| **28,000 (the plan)** | **±30** | **±35** | **15.7** | **$23.2** | **24.4 h, $36.0; cap $50** |

A smaller size is a change to `phase7.json` (`lbr.chunks`) and to the pre-registration, made
before the launch.

$50 buys about 33.6 hours at $1.476 an hour after the 15-minute margin: 1.38 times the
projection with the repeat. The projection's speeds are the uncertain part; the pilot's
`size.json` gives the real hours of the gate match before it starts, and if the cap stops the
run the results so far are kept and it goes on after `resume`.

**f16 and mmap**, options only, not needed at 128 GB. The tables in 16-bit floats would halve
them to 11.1 GB, so a 64 GB machine (c4a-highcpu-32, half the threads) would hold them; the leaf
values are smoothed averages over about 400 deals a cell, so f16's 3 significant digits would
likely do, but that would need its own check. Mapping the file instead of reading it would let
the job start without reading 22 GB first and let the system page the tables in and out as
memory allows (slowly, if it is short).
