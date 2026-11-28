# search: depth-limited search on a blueprint (Phase 7 groundwork)

A heads-up agent that plays the blueprint before the flop and searches every decision after it,
following Modicum (Brown, Sandholm and Amos, "Depth-Limited Solving for Imperfect-Information
Games", 2018) for the flop and Pluribus (Brown and Sandholm 2019) for re-solving:

- **Ranges**: both players' ranges at the current public state, from the probabilities of every
  action taken (a Bayesian update per action, with card removal).
- **River and turn**: a subgame from the real state (real pot, stacks and bets, the real
  off-menu bets added), solved with the `subgame` crate, and played from the solved strategy.
- **Flop**: solved to the end of the flop only. At the leaves, the player who is not searching
  picks, hand by hand, one of four continuation strategies for the rest of the hand (the
  blueprint, and the blueprint biased toward folding, calling or raising); the searching player
  plays the blueprint.
- **Re-solving**: when the opponent makes a bet that is not in the street's tree, it is added and
  the street is solved again from its start.

This is groundwork, not the Phase 7 gate: it is built and measured on the 20 big blind Phase 5
blueprint on a 4 core machine. The plan and results of the measurements are in
`docs/research/runs/phase7_groundwork/` and in `docs/research/experiments.md` ("Phase 7
groundwork").

It reuses `subgame`, `blueprint` and `abstract_game` as they are, with three small additions,
each with a test:

- `subgame`: `Tree::from_parts` (a tree built from its nodes, so the search can build the turn's
  tree with the real off-menu bets in it) and frozen nodes (`Game::freeze`: a node whose
  strategy is fixed, which the solver and the best response follow; used for the searcher's own
  earlier decisions on a street when it is solved again). `tests/search_hooks.rs`.
- `blueprint`: `Blueprint::strategy_into` (the strategy at a node for one bucket, without a
  `PublicState`) and `read_action_prob_for_range` (the probability of an off-menu action as the
  blueprint reads it, for the range update). `tests/play.rs`.

## Use

```
cargo build --release -p search
S=/path/to/strategy.bps

# the leaf tables, once per strategy file (written next to it as $S.leaf); stopped, the same
# command goes on from the parts done. --lanes 16 for both players choosing at the leaves
target/release/search leaf --strategy $S --deals 16000000 --seed 7 [--lanes 16]

# search against the blueprint: duplicate deals, all-in equity, bb/100 with its SE
target/release/search match --strategy $S --deals 3000 --seed 7101 --threads 4 --out h2h.json

# LBR against either agent; compare two runs on the same deals (paired)
target/release/search lbr --strategy $S --agent search --setting fcpa14 --hands 1500 --seed 7102 --out s.deals
target/release/search lbr --strategy $S --agent blueprint --setting fcpa14 --hands 1500 --seed 7102 --out b.deals
target/release/search compare s.deals b.deals

# timing per street, tree sizes, the same solves on 1, 2 and 4 threads, the range check
target/release/search bench  --strategy $S --hands 150 --seed 7104 --threads 4 --out bench.json
target/release/search trees  --stack-bb 200
target/release/search scale  --strategy $S --hands 40 --seed 7105 --spots 6 --out scale.json
target/release/search ranges --strategy $S --hands 300 --seed 7106 --out ranges.json

# the Phase 7 plan (or a leaf build alone) as a tools/cloud job
target/release/search --config docs/research/runs/phase7/phase7.json --checkpoint-dir DIR [--resume]
```

Every command takes the settings as options (`--flop-target`, `--flop-iterations`,
`--turn-target`, `--turn-iterations`, `--river-target`, `--river-iterations`, `--prune`,
`--turn-river-menu allin|075|standard`, `--leaf-choice opponent|both`, `--play
average|final`); without them it uses `Settings::default()`. Every
command that loads a strategy file takes `--tables DIR`, the bucket tables it was trained with,
for a file trained on another machine (by default the folder the file names; the checksums are
checked either way).

In the arena and from Python the agent is `search:<strategy file>`, or
`search:<strategy file>?tables=<dir>` (with the leaf tables next to the file; without them the
flop's leaves are checked down):

```
python tools/b0_arena.py search:$S --stack-bb 20 --deals 100 --seed 7107
```

```python
import pokerscribe_engine as pe
S = "/path/strategy.bps"
report = pe.run_match([f"search:{S}", f"blueprint:{S}"], 100, seed=1, stack=2000)
print(report.summary())
```

From Rust, `SearchAgent` is an `lbr::Strategy`, so LBR (`blueprint::lbr_match`) and the arena
(`play::strategy_agent`) take it as they take the blueprint.

## How it works

### Ranges (`agent.rs`)

Both players start the hand with all 1,326 combos at weight 1. Each action multiplies the actor's
weights by that combo's probability of the action, and each board card removes the combos that
hold it. Weights under 0.1% of the range's largest are left out of a solve (`--prune`; the
blueprint plays a hand that is left out).

- The opponent's probabilities are the blueprint's: of the exact real action when the blueprint
  has it, or else of the menu action the blueprint reads it as (`read_action_prob_for_range`,
  the same pseudo-harmonic mapping and translation seed the blueprint plays with). When even that
  is 0 for every live combo the weights are kept.
- The searcher's own probabilities are the ones it really played with: the blueprint's before
  the flop, and afterwards its own solved strategy at that decision. With the blueprint's numbers
  its real hand would drop out of its own range whenever the search plays something the
  blueprint never would.

The range check (`search ranges`) plays hands against the blueprint and, at every decision of
the search agent after the flop, checks that each player's real hand has weight and is in the
solve.

### A street's tree (`street.rs`)

A street's betting is built over real `nlhe` states: at every decision the blueprint's menu
(`abstract_game::Menus::actions`, so every action is legal and sized exactly as the blueprint
sizes it), plus every real action that is not on the menu, at the decision where it was taken.
A real raise within 1% of the pot after the call (at least 2 chips) of a size in the tree counts
as that size.

### River and turn (`solve.rs`)

The tree is turned into a `subgame` spot with the real pot, stacks and bets and the two ranges,
and solved with Discounted CFR to a target exploitability:

- river: the blueprint's menu, to 0.5% of the pot or 1,000 iterations;
- turn: the turn's betting as above, and under it every river card with a smaller river menu
  (a bet of three quarters of the pot or all in, then all in only), to 2% or 300 iterations. The
  river is solved again with the full menu when it comes, so the turn's river only has to give
  the turn's actions sensible values.

### Flop (`flop.rs`, `leaf.rs`)

Discounted CFR over every combo of both ranges on the flop's betting (the same discounts as
`subgame`: alpha 1.5, beta 0, gamma 2), to 1% of the pot or 400 iterations. The ends of the flop
are valued three ways:

- a fold, exactly, with card removal;
- an all-in call, exactly, from the showdown equity of every pair of combos over all 1,176 turn
  and river cards (`equity.rs`);
- a leaf, where the flop ends with chips behind: Modicum's depth limit.

At a leaf the player who is not searching (the "chooser") makes one more decision with four
actions, one per continuation strategy, and the searcher plays the blueprint after it. The
four are the blueprint and three biased versions of it: at every decision of the rest of the hand
the probability of folding, of checking or calling, or of betting or raising (all sizes
together) is multiplied by 5 and the strategy renormalized. A factor of 5 is the one
Pluribus uses; the Modicum paper used 10. The chooser picks per hand, as the CFR iterations make it, so the searcher's
flop strategy has to hold up against whichever continuation suits each of the opponent's hands
best.

With `Settings::leaf_choice` `both` (Pluribus's way) both players choose at each leaf, four
continuations each, without seeing the other's pick: the leaf is a small simultaneous game,
solved by the same CFR as the rest of the tree, and the solve holds one table per pair of picks
(`flop::Problem::choices`, 1 or 4 per player). It needs the 16-lane tables (below) and costs
about 3.4 times as much on the flop (one spot at 400 iterations: 3,546 ms against 1,056).

The value of each continuation comes from the leaf tables. A leaf of the flop is a start of the
turn; the blueprint reads it as one of its abstract turn-start nodes `d` (133 of them in the 20
big blind standard game). For each `d` and each lane the table holds, by the two hands' flop
buckets (the blueprint's own 200), the big blind's expected share of the pot at `d`: `(net + C)
/ P`, with `net` what it wins over the rest of the hand, `C` what it had put in and `P` the pot.
A share scales with the pot, so a real flop whose pot is not the abstract line's (an off-menu
bet) uses the same table. The tables are Monte Carlo averages over random deals (two hands, a
flop, a turn and a river): for each deal the abstract subtree under every `d` is walked exactly,
every action of both players weighted by its probability, with the deal's turn and river
buckets. A cell with few deals is pulled toward an additive fit of its row and column, with a
pseudo-count of 3 deals. In the solve, a combo pair's leaf value is the table cell of their
buckets, and card removal is exact: the bucket sums over the opposing range are corrected combo
by combo for the opposing combos that share a card. Where the blueprint can't place the leaf at
one of its nodes, the leaf is checked down (the equity table).

The lanes are pairs of continuations (`leaf::lane_of`). Modicum's 7 (`--lanes 7`, the default)
are the blueprint for both, the small blind biased three ways and the big blind biased three
ways; the 16 for both choosing (`--lanes 16`) are every pair, lane `sb x 4 + bb`. The 16 lanes
hold the 7 bit for bit (tested), so 16-lane tables also serve `opponent`; `both` refuses 7-lane
tables when the agent loads them.

The tables are built once per strategy file (`search leaf`) and saved next to it as `<file>.leaf`
with a hash of the strategy file, so a table built for another blueprint is refused.

### Building the leaf tables in parts (`leaf.rs`, `leaf_job.rs`)

The 200 big blind game's tables are 9.7 GB at 7 lanes (8,669 turn starts, 200 x 200 cells,
`f32`) and 22.2 GB at 16, and a build in one piece would hold about 29 GB of sums (67 GB at 16
lanes). So a build goes in parts of 256 turn starts (34 parts): each part plays all the deals
for its turn starts, is written to its own file (`part-NNNNN.leafpart`, with a checksum) and
its memory freed; the table file is then put together from the parts without loading them all,
each part's checksum checked again on the way (a table file longer than its header says is
refused on load). A build at 200 big blinds peaks at about 1.5 GB (2.65 GB at 16 lanes, which
take 1.35 times as long).

- **The same tables, bit for bit, whatever the threads, block size or parts.** Within a block
  of deals, the deals are sorted by cell (the two hands' flop buckets) and, within a cell, by
  their place in the stream; the cells are split into 64 ranges, and each (turn start, cell
  range) is one piece of work with its own slice of the sums. So every sum adds its deals in
  the stream's order, as a build on one thread does (`build_reference`, kept for the test).
- **Stops and goes on.** A checkpoint (`leaf.ckpt`) lists the parts done and a fingerprint of
  the build (the strategy file's hash, deals, seed, part size, turn starts, buckets, the
  smoothing). A stop gives up the part being built; going on, each listed part on the disk is
  checked (header, size, checksum) and a missing or damaged one is built again. A checkpoint of
  another build, a fresh start over a checkpoint and `--resume` with none are refused.
- **As a cloud job.** `search --config FILE --checkpoint-dir DIR [--resume] [--threads T]` is the
  same job under the `tools/cloud` trainer contract (`tools/cloud/README.md`, "The trainer"):
  the config is a `leaf_job::JobConfig` in JSON (strategy file, bucket tables, deals, seed,
  lanes, part size), the parts and the table file go in the checkpoint directory (artifacts
  `*.leafpart`, `*.leaf`), JSON lines on stdout (started or resumed, progress, each part with
  its speed and memory, done), SIGTERM saves and exits 75, and it exits 0 when the table file is
  written. A config with a `gate` is a plan instead (below).

Measured here (4 vCPU, Intel Xeon at 2.1 GHz) on a 2M-iteration 200 big blind `rich` k200
blueprint, every turn start at 65,536 deals: 1.6M walks (a turn start and a deal) a second on 4
threads, 34 parts of 5.5 to 17.7 s, peak memory 1.54 GB, a 9,709,339,447 byte file. At 16M deals
that is about 96 thread-hours here: about 1.3 hours on a c4a-highcpu-64 (an Axion core taken as
1.15 threads here), 1.76 hours at 16 lanes (`docs/research/runs/phase7/README.md`, "Sizes and
costs").

### The Phase 7 plan as a cloud job (`plan_job.rs`, `runs.rs`)

`search --config phase7.json --checkpoint-dir DIR [--resume]` with a plan
(`plan_job::PlanConfig`, `docs/research/runs/phase7/phase7.json`) plays the whole of Phase 7's
head-to-head plan on one machine, in order: the leaf build (the job above, its record
`leaf.state`), the decision-time bench on its own pool of 4 threads with the bound check (over
it, the job ends there), the pilot match, N by the size rule, the gate match in chunks, the
variants (other agent settings, reported), LBR against the blueprint and the gate agent on the
same seeds, and the repeat only after the gate passes. The runs themselves are `runs.rs`, shared
with the `match`, `lbr`, `compare` and `bench` commands.

- **The contract**: one checkpoint, `plan.ckpt` (the plan's fingerprint: the config and the
  strategy file's hash; and the step). The artifacts are the parts and the results (`*.json`,
  `*.deals`); the table file is put together again from the parts on a new machine. Every run
  (loading the tables, the bench, a chunk, an LBR run) plays on a worker thread while the job
  watches for SIGTERM: on it the run is given up and the job exits 75 within a second. Results
  are written whole and renamed, and a step skips the results already there, so a stopped job
  plays nothing again but the run it gave up, with the same seed and the same result.
- **What it refuses**: a plan that can't be played as written (lanes too few for an agent's leaf
  choice; a step that isn't a multiple of the chunk; two runs sharing a seed, among the bench,
  the pilot, every match chunk and every LBR run; an unknown LBR setting or field), a checkpoint
  of another plan, a fresh start over a checkpoint and `--resume` with none.
- **Its lines** on stdout: started or resumed, the build's lines (with `"step": "leaf"`), each
  step's result, the progress of each match in deals (`iterations`, `target_iterations`, with
  the peak memory), "saved on SIGTERM" with the step, and "done" with how it ended (`end.json`).

`docs/research/runs/phase7/README.md` has the runbook and the files it writes.

### Re-solving (`agent.rs`)

At each decision on a street the street is solved from its start, with the ranges at the start
of the street. Later on the same street that solve is used again as long as the opponent's
actions are in its tree. When the opponent makes an action that is not, the action is added at
its decision and the street is solved again from its start, with the searcher's earlier
decisions on the street frozen to the strategy it played them with (for every combo), so only
the opponent's play and the searcher's later play can change.

This is unsafe re-solving, as Pluribus does it: the opponent's range at the start of the street
is taken as it is, with no gadget holding the opponent's values to what it could get in the
earlier solve (safe and Reach subgame solving, Brown and Sandholm 2017). Why unsafe:

- it is what Pluribus does round by round, and in the subgame solving paper's experiments unsafe
  solving was usually less exploitable than the blueprint, though it carries no guarantee;
- a safe gadget needs the opponent's counterfactual values from the earlier solve for every hand;
  at a flop cut off by the leaf tables those values are themselves estimates, so the guarantee
  would be weak here anyway;
- the searcher's frozen earlier decisions keep what it already did consistent with the new solve.

LBR against the search agent is the check on whether this opens holes (below).

Every solve depends only on the public state and the settings (no time limits), so solves are
cached by the public betting and a match or an LBR run repeats exactly.

## Settings

`Settings::default()`, fixed before the measured runs:

| | Target (share of the pot) | Iterations at most |
| --- | --- | --- |
| Flop (depth-limited) | 1% | 400 |
| Turn (every river card, river menu "075") | 2% | 300 |
| River (blueprint menu) | 0.5% | 1,000 |

Combos under 0.1% of the largest weight are left out. In a match each solve runs on one thread
for the turn (`turn_threads`, matches run deals in parallel) and the flop uses the global thread
pool. `leaf_choice` is `opponent` (Modicum: only the opponent chooses at the flop's leaves) or
`both` (Pluribus, on 16-lane tables); `play` is `average` (each solve's average strategy, as
CFR's guarantee is for) or `final` (its last iteration, `subgame::Play::Final`, the
exploitability then measured for that strategy).

## Results (Phase 7 groundwork, 20 big blinds)

On the Phase 5 standard-k200 blueprint (20 big blinds, the standard menu, 200 buckets a street),
on 4 cores (Intel Xeon at 2.1 GHz), pre-registered in `docs/research/runs/phase7_groundwork/`
(`README.md` the plan, `results.md` the results and the raw outputs). Groundwork, not the Phase
7 gate.

| | Result |
| --- | --- |
| Search against the blueprint, 3,000 deals | -2.51 ± 4.56 bb/100 (z -0.55): no gain, no loss |
| LBR `b56_14` (56 bet sizes), 1,500 hands | blueprint +118.0 ± 14.0, search +75.5 ± 14.3; paired -42.5 ± 12.2 (z -3.47) |
| LBR `fcpa14`, 1,500 hands | blueprint -25.1 ± 16.6, search -53.0 ± 16.2; paired -27.9 ± 11.8 (z -2.35) |
| The same on fresh seeds, 6,000 hands | `b56_14` paired -34.1 ± 6.4 (z -5.33); `fcpa14` -6.4 ± 6.0 (z -1.07) |
| Pooled, 7,500 hands | `b56_14` blueprint +112.8 ± 6.6, search +77.1 ± 6.7, paired -35.8 ± 5.7 (z -6.30); `fcpa14` paired -10.7 ± 5.3 (z -2.01) |
| Real hand in the range and in the solve, 300 hands against the blueprint | 100% of 415 decisions, both players |
| B0, 100 deals | B0 -4.70 ± 22.08 against search (+11.78 ± 18.25 against the blueprint); no illegal action |

- **Head-to-head** the search neither gains nor loses against its own blueprint. Against the
  blueprint its ranges are exact and it never re-solves (the blueprint only bets its own menu),
  so its edge can only be exact hands over 200 buckets, which at 20 big blinds is small next to
  its own solving error.
- **Against LBR** the search is less exploitable than the blueprint, most of all against
  `b56_14`, whose sizes are mostly off the menu: there the search adds each size to its tree and
  re-solves (18% of its flop solves were re-solves), which most likely is where the gain comes
  from. That is the part of the blueprint's
  weakness the Phase 5 gate found (about 18% of its decisions off the tree).

Decision time on 4 threads (`search bench`, 150 hands against the blueprint; a decision that
reuses its street's solve takes under a millisecond):

| Street | p50 | p95 | Max | Iterations (mean) | Exploitability (mean, share of the pot) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flop | 480 ms | 752 ms | 1,044 ms | 46 | 0.88% |
| Turn | 2,228 ms | 6,021 ms | 6,677 ms | 55 | 1.76% |
| River | 39 ms | 158 ms | 206 ms | 71 | 0.45% |

A turn solve costs 0.010 microseconds per solver node, iteration and combo on one thread and
runs 3.0 to 3.3 times faster on 4 threads (8% serial); a flop solve 2.3 to 3.0 times (17%
serial). For the Phase 6 game (200 big blinds, `rich` menu, 200 buckets) on 64 cores, with an
Axion core taken as fast as one here: about 0.3 to 0.6 s on the flop, 1.5 to 3 s on the turn
(2.5 to 5 s at the slow end), under 0.3 s on the river. Its leaf tables would be 9.7 GB (8,669
turn starts) and take about 2 hours to build on 64 cores at 16M deals. `results.md` has the
method.

### Not done

- Ranges against opponents that are not the blueprint: a hand the blueprint would never play
  that way gets weight 0 (the search then plays it as the blueprint). Not measured.
- A safe re-solving gadget, to compare with the unsafe form under LBR.
- Leaf values by rollout during the search (as Modicum did): a 200 big blind game's tables are
  large.
- The flop's serial share (17%): the leaf lookups and the equity table are the next things to
  parallelize.

## Tests

- `src/street.rs`: a raise within the tolerance reads as the menu size, an off-menu one is added
  as an extra action; the river conversion solves; the turn's tree deals every river card (48).
- `src/flop.rs`: exploitability falls to the target (one thread and many give the same answer);
  leaf tables made from the equity give the checked-down values, with either player or both
  picking; a player picks the continuation that pays it most; picks neither player sees play
  as a simultaneous game (rock, paper, scissors at the leaves: a third each where both reach);
  a pick that changes nothing is the same as no pick; the last iteration can be played; a
  frozen node keeps its strategy.
- `src/plan_job.rs`: the registered plan (`phase7.json`) reads, with the seeds and caps of the
  pre-registration; the size rule rounds up within its limits; chunks pool by deals; a plan that
  can't be played is refused; the bound check names the streets over.
- `src/leaf.rs`, `src/equity.rs`: the table layout and the exact equity.
- `src/leaf_job.rs`: a part damaged on the disk after it was written stops the table file (and
  leaves no half-written file); a table file with a byte too many is refused.
- `tests/agent.rs` (a small blueprint trained in the test): the leaf tables are the same on 1
  and 3 threads; built in parts, on any threads and block size, they are the sequential build's
  bit for bit, and a stop gives up its part; the leaf job stops after some parts, refuses a fresh
  start over a checkpoint, a resume with none and another build's checkpoint, builds again a
  damaged and a missing part, and gives the one-piece build's tables; 16-lane tables hold the 7
  lanes bit for bit, and both players pick on them (playing the average or the last iteration),
  while 7-lane tables are refused; the plan job plays every step, stops on request and goes on
  (nothing done is played again, no part built again, the table file the one-piece build's), and
  plays no match when a street is over its bound; the agent only plays legal
  actions and its real hand stays in its own range; an off-tree bet is added and the street is
  solved again with the searcher's check frozen, and an on-menu bet reuses the solve; the same
  public state gives the same answer.
- `tests/cloud_job.rs` (ignored; set `BLUEPRINT_TABLES`, as the nightly workflow does): the
  leaf job through the binary under the `tools/cloud` contract on a blueprint whose tables
  folder is gone (so every load needs `--tables`): `--resume` with nothing to resume and an
  unknown option fail, SIGTERM after a part exits 75, the resume goes on from the parts saved
  and finishes, the tables are the one-piece build's; `search leaf` gives the same and deletes
  its parts; the agent and `search bench` load with `--tables`. The plan job the same way at 16
  lanes: SIGTERM after the size step exits 75 within 5 s, and the resume plays the rest.
- `docs/research/runs/phase7/plan_rehearsal.py`: the real `tools/cloud` supervisor runs the plan
  with a local folder as the bucket, a SIGTERM during the gate match, and a new machine with an
  empty disk that resumes from the bucket without building a part or playing a result again.
- `../subgame/tests/closed_form.rs`: a solve can hand back its last iteration (its strategy,
  exploitability and values recomputed for it).
- `../subgame/tests/search_hooks.rs`, `../blueprint/tests/play.rs`: the hooks above.
- `app/tests/test_engine_bindings.py`: `search:<file>` (and `search:<file>?tables=<dir>`) is
  named in the arena's errors when the file is missing or damaged.

## Layout

- `src/agent.rs`: `SearchAgent` (ranges, the per-street solves, re-solving, the `Strategy`).
- `src/street.rs`: a street's tree over real states; conversion to `subgame`.
- `src/solve.rs`: `Settings`, the solve of one street.
- `src/flop.rs`: the depth-limited flop solver.
- `src/leaf.rs`: the leaf tables (build, a build's part, save, load).
- `src/leaf_job.rs`: the build in parts, resumable, and as a `tools/cloud` job.
- `src/plan_job.rs`: the Phase 7 plan as one `tools/cloud` job.
- `src/runs.rs`: a match, an LBR run, a paired comparison and the bench, for the commands and
  the plan job.
- `src/equity.rs`: exact flop all-in equity.
- `src/real.rs`, `src/cards.rs`: real states from public information; card and combo numbering.
- `src/play.rs`: a `Strategy` seated in the arena.
- `src/bin/search.rs`: the command line.
