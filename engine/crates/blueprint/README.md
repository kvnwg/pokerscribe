# blueprint: the heads-up blueprint (Phases 5 and 6)

A blueprint is a strategy for the whole game, trained in a shrunk version of it and played in
the real one. This crate trains one for heads-up No-Limit Hold'em:

- the game is `abstract_game`'s (a bet menu and a betting tree), with `abstraction`'s bucket
  tables as the card abstraction, through the adapter in that crate's README ("With the
  abstract game");
- training is external-sampling Monte Carlo CFR from `cfr`, on several threads, with
  checkpoints, so a run can be stopped and resumed on the same machine or a bigger one;
- the result is a compact, checked strategy file;
- the file plays as `lbr`'s `Strategy`, with real bets that are not on the menu read by
  `abstract_game`'s pseudo-harmonic mapping, so LBR can measure it and the arena can play it.

Status, 27 Nov 2026: built and tested; the Phase 5 gate has been run with it ("The Phase 5
gate" below).

In short: bet sizes lower LBR's win rate a lot at 20 big blinds, buckets don't, so the gate
fails (3 of 7 conditions). Phase 6 keeps OCHS on the river and the default reading of small
bets. The Phase 6 game (200bb, a rich preflop, 200 buckets: 97M information sets) needs about 5
to 7 GB, so memory is not what limits it; its training time is uncertain by a factor of about
100 (below).

## Use

```bash
cd engine
cargo build --release -p blueprint
```

Bucket tables first (`engine/crates/abstraction/README.md`): about 1, 3 and 8 minutes on 4
cores for 10, 50 and 200 buckets, 138 MB each, whatever the bucket count.

```bash
./target/release/abstraction-build build --out ~/abstraction/k50 --buckets 50
```

A run is a spec (JSON) and a directory:

```json
{"stack_bb": 20, "menu": "standard", "abstraction": "/root/abstraction/k50",
 "training": {"seed": 1, "threads": 4, "compact_scale": 100.0, "regret_floor": -3100000.0,
              "linear": [200000, 20000000], "pruning": null}}
```

```bash
./target/release/blueprint train --spec spec.json --dir runs/standard-k50 --until 64000000 --every-minutes 10
./target/release/blueprint lbr --strategy runs/standard-k50/strategy-64000000.bps --settings paper --hands 100000
./target/release/blueprint reference --stack 20 --settings paper --hands 100000
./target/release/blueprint gate --plan plan.json
```

| Command | What it does |
| --- | --- |
| `train --spec F --dir D --until N [--every-minutes M] [--threads T]` | Trains the run in `D` to `N` iterations in all, resuming its checkpoint if there is one (the spec must be the same, apart from the threads), saving every `M` minutes and on SIGTERM, then writes `strategy-N.bps`, `latest.txt` and a line in `stages.jsonl` |
| `lbr --strategy F[,F...] [--label L[,L...]] [--settings LIST] [--hands N] [--seed S] [--deals DIR] [--small-bets smallest\|check-or-call]` | LBR against strategy files, one after the other, on every core. `LIST` is short names (`fc14`, `fc34`, `fcpa14`, `fcpa34`, `b56_14`, `b56_34`) or `paper`. Several files in one call share LBR's exact preflop win probabilities, which take minutes the first time (3.5 minutes on 4 cores here) |
| `reference --stack BB ...` | The same for always call, random action and random kind of action |
| `compare --a DEALS --b DEALS` | The difference between two matches on the same deals, with its paired standard error |
| `gate --plan F` | A whole gate plan in one process (`src/gate.rs`): stages, LBR after each, a stop rule, a final measurement. Started again, it carries on where it stopped |
| `bench --spec F [--seconds S] [--warmup S] [--threads 1,2,4]` | Training speed and memory |
| `size --stack BB --menu NAME --buckets B` | Information sets and regret slots of a game, without building it |
| `info F` | A strategy file's header |
| `export (--config F \| --spec F) --checkpoint C --out S [--tables DIR]` | The strategy file of any saved checkpoint, off the machine that trained it: the spec (a trainer config or a run's `spec.json`), the checkpoint, and the tables (`--tables`, or the directory the spec names) |
| `--config F --checkpoint-dir D [--resume] [--threads T]` | The trainer contract of `tools/cloud` (below) |

Every command prints one JSON object per result. Menus by name: `abstract_game`'s
`push_fold`, `minimal`, `small`, `standard` and `wide`, and `rich` (the standard menu after
the flop with the wide menu's preflop: 8 opens, 5 3-bets, 4 4-bets and 2 5-bets, each with
all in), the kind of game the Phase 6 run is planned for.

From Rust:

```rust
use blueprint::{Blueprint, Run, Spec};
use lbr::{play_match, LbrConfig, MatchConfig};

let spec = Spec::from_json(&std::fs::read_to_string("spec.json")?)?;
let mut run = Run::open(spec, "runs/standard-k50".as_ref())?;
run.train(64_000_000, Some(10.0))?;
run.export().file.save("strategy.bps".as_ref())?;

let blueprint = Blueprint::load("strategy.bps".as_ref(), None)?; // with the tables it names
let table = MatchConfig { stack: 2_000, ..MatchConfig::acpc(100_000, 1) };
println!("{}", play_match(&blueprint, &LbrConfig::default(), &table));
```

From Python, in the arena (`engine/crates/py/README.md`): the agent `blueprint:<file>`.

```bash
python tools/b0_arena.py blueprint:runs/standard-k50/strategy-64000000.bps --stack-bb 20 --deals 1000
```

## Training

`Run` (`src/train.rs`) holds a run's directory: `spec.json`, `checkpoint.ckpt` (cfr's
checkpoint: every regret and strategy sum) and `log.jsonl` (one line per session: iterations,
seconds, speed, memory, saves). It trains with `cfr`'s `Mccfr` as configured by the spec's
`training`:

| Setting | Meaning | Default |
| --- | --- | --- |
| `seed` | cfr's seed | 1 |
| `threads` | Lock-free threads sharing the tables, as Pluribus ran it. May change on resume | 4 |
| `compact_scale` | Regrets as 32-bit integers, `round(regret * scale)`. Regrets are in big blinds, so 100 is one unit a chip at blinds 50/100 | 100 |
| `regret_floor` | Regrets never go below this many big blinds (Pluribus: -310 million chips, which is -3.1 million big blinds at 100 chips a big blind) | -3.1 million |
| `linear` | `[interval, until]`: linear weighting every `interval` iterations up to `until` | none |
| `pruning` | `{warmup, threshold, probability}`: Pluribus's negative-regret pruning, the threshold in big blinds (Pluribus: -300 million chips, -3 million big blinds). The river is never pruned (`abstract_game`) | none |

A stop asked for with SIGTERM saves and returns (`Session::stopped`). The strategy file is
written from the run at any point (`Run::export`), so a stage of a long run can be measured
while it goes on.

### On a rented machine (`tools/cloud`)

```bash
blueprint --config trainer.json --checkpoint-dir DIR [--resume] [--threads 64]
```

is the trainer contract of `tools/cloud/README.md` ("The trainer"). `trainer.json` is
`{"spec": {...}, "until": N, "every_minutes": M}`. It trains in `DIR` in sessions of about `M`
minutes, each ending with a save of `checkpoint.ckpt` (written to a temporary name, then
renamed) and a progress line (`{"iterations": ..., "target_iterations": ...}`, with the speed
and memory). On SIGTERM it saves, prints `{"event": "saved on SIGTERM", ...}` and exits with
75; with `--resume` it carries on from the checkpoint; at `N` it writes `strategy.bps` and
exits with 0. `--resume` with no checkpoint is an error, not a fresh start.

With `"strategies": {"first": F, "factor": K}` in `trainer.json` it also writes the strategy at
fixed stages, `F`, `F x K`, `F x K x K`, ... and `N`, as `strategy-<iterations>.bps` in `DIR`
(the last one is also `strategy.bps`, a hard link). A session never runs past the next stage.
At each stage a line goes to `stages.jsonl` in `DIR` (and to standard output) with:

- `change` and `change_from`: how far the average strategy moved since the latest earlier
  stage file in `DIR` (`StrategyFile::change_from`, each information set weighted by how often
  it is reached). It needs the solver's weights, so it is measured here, when the file is
  written, not afterwards; on a new machine `tools/cloud` puts the earlier files back first.
- `regrets`: by street, the share of regret slots below -1,000, -10,000, -100,000 and
  -1,000,000 big blinds, below the pruning threshold and at the floor, and the lowest;
- `pruning`: the solver's counters (traversals and actions pruned, states visited);
- the time the export and the measures took, and the process's memory.

A stop between a stage's save and its file is caught up when the run resumes. The streaming
export (`Mccfr::for_each_set`, no copy of the tables) needs about 1.3 GB on top of the run, so
the Phase 6 game peaks at about 8 GB.

Checked end to end with the real supervisor (`docs/research/runs/phase5_gate/cloud_local_test.py`):
machine 1 trains, every process gets SIGTERM, the trainer saves at 2,558,692 iterations and
the supervisor uploads it; machine 2 starts with an empty disk, downloads it, resumes at
exactly 2,558,692 and finishes; the run's state is "done". The Phase 6 run copies the tables
in the bundle (`TRAINER_FILES`, at `/opt/pscloud/bundle/files/k200`), and its dress rehearsal
on this machine (`docs/research/runs/phase6/README.md`) runs the stages through a SIGTERM, a
new machine and a stop. `tests/tables.rs` checks the stages on a small game: a SIGTERM after
the first stage, a resume, every stage once, the change measured from the second on, pruning
counted, and `export` from the last checkpoint giving the same strategy.

## The strategy file

`src/file.rs`. Every information set of the abstract game is a decision point of the betting
tree and a bucket of its street, so the strategy is one block per decision point, `buckets x
actions` probabilities each, in decision point order, with no keys:

| Bytes | What |
| --- | --- |
| 8 | `PSBLUEP` and a newline |
| 4 | Format version, now 1 |
| 4 | Length `H` of the header |
| `H` | The header as JSON: the game (stack, blinds, menu in words, decision points, actions, buckets), the spec, the tables' bucket counts, checksums and river feature, information sets, how many were reached, iterations and training seconds |
| slots x 2 | Each probability times 65,535 as a little-endian `u16`. An information set's numbers sum to exactly 65,535, or are all 0 when training never reached it (it is then played uniformly) |
| 8 | XXH64 of every byte before it |

- It holds the average strategy. Information sets reached only while their own player was
  traversing have no strategy sums; they get the current strategy (regret matching).
- Two bytes a probability: 5.5 MB for standard-k200 at 20 big blinds, 0.50 GB for the Phase 6
  game (251.7M slots).
- Loading checks the magic, version, length and checksum, that the file fits the game, and
  that the tables are the ones it was trained with (their checksums), so a strategy is never
  played with other tables.

## Playing in the real game

`Blueprint` (`src/play.rs`) answers `lbr`'s `Strategy`: for a public state and a hand, a
probability for each legal action. It walks the real betting through the abstract tree, one
action at a time:

- fold, check and call are the abstract fold and check or call;
- a real all in is the menu's all in where the menu has one;
- any other raise is read as one of the two menu raises around it, with
  `abstract_game::map_size` (the pseudo-harmonic mapping) on sizes measured as shares of the
  pot. The draw comes from a hash of the betting and public cards up to that raise, so the
  same public state is always read the same way, and the strategy LBR reads is the strategy
  that plays;
- a raise smaller than every menu raise is read as the smallest (the mapping's rule as
  written, and the default), or, with `SmallBets::CheckOrCall`, between a check or call and
  the smallest raise (the mapping with 0 first on the menu, as `map_size`'s documentation
  suggests). A raise read as a check or call that ends the abstract street is answered with
  a call before the abstract game moves on.

The answer is the stored strategy at the decision point reached for the hand's bucket on this
street, each menu raise turned back into a real one: the same share of the real pot (all in
stays all in), rounded and kept in the legal range, with raises that land on the same amount
merged. Where the abstract game can't follow (a raise where the menu has none, or a hand over
in the abstract game but not in the real one) it checks or calls for the rest of the hand;
`off_tree_share` counts how often.

## The Phase 5 gate

Run on 27 Nov 2026 with this crate (`docs/research/experiments.md`, "Phase 5: the gate"; plan,
logs, scripts and tables in `docs/research/runs/phase5_gate/`). Heads-up at 20 big blinds, two
menus (small, standard) and three bucket counts (10, 50 and 200 per postflop street, OCHS on the
river), plus 50 buckets with equity on the river; each run trained until LBR was flat and the
strategy changed by at most 8% over a doubling of the iterations, then measured on the same
100,000 deals (seed 778) with five LBR settings. M is the largest.

| Run | Information sets | Iterations | M, bb/100 |
| --- | ---: | ---: | ---: |
| small-k10 | 14,828 | 8M | 120.4 ± 1.8 |
| small-k50 | 66,028 | 16M | 125.3 ± 1.8 |
| small-k200 | 258,028 | 64M | 128.9 ± 1.9 |
| standard-k10 | 64,580 | 32M | 105.1 ± 1.8 |
| standard-k50 | 282,340 | 64M | 111.7 ± 1.9 |
| standard-k200 | 1,098,940 | 64M | 112.3 ± 1.9 |
| small-k50eq (equity river) | 66,028 | 32M | 127.9 ± 1.8 |
| standard-k50eq (equity river) | 282,340 | 64M | 107.3 ± 1.8 |
| Always call (reference) | | | 320.8 ± 2.1 |
| Random kind of action (reference) | | | 353.3 ± 3.5 |
| Random action (reference) | | | 465.4 ± 3.8 |

- **The gate fails: 3 of its 7 conditions hold.** More bet sizes lower M by 13.6 to 16.6
  bb/100 at every bucket count (8.5 to 10.5 paired SE). More buckets don't: from 10 to 50, M
  rises on both menus (+4.9 and +6.6, 3.2 and 4.6 SE), and from 50 to 200 it rises again on
  the small menu (+3.6, 2.5 SE) and stays flat on the standard one (+0.6 ± 1.4).
- **OCHS against equity on the river:** neither is better on both menus (on M, over both deal
  sets, equity +0.2 ± 1.1 on the small menu and -5.2 ± 1.0 on the standard one), so Phase 6
  keeps OCHS, as pre-registered. Equity on the standard menu is worth checking again deeper.
- **Small bets** are best read as the smallest menu size (the default). Reading them as a check
  or call is worse on every run (by 14 to 32 bb/100 with `b56_34`).
- **What LBR wins comes mostly from bets that are not on the menu.** With the 56 bet sizes,
  about 18% of the blueprint's decisions are off the tree, where it checks or calls whatever it
  holds, and LBR wins 105 to 129 bb/100. With pot and all in only (fcpa) it is under 0.5% and
  LBR wins -1 to 16.

Checks added after the gate (not pre-registered; `docs/research/runs/phase5_gate/checks.md`):

- **Fresh deals**: all eight runs again on a third deal set (seed 779, `b56_14`). The verdict is
  the same. Pooled over both deal sets, more sizes lower M by 14.3 to 17.6 bb/100, and more
  buckets raise it by 4.9 and 4.6 from 10 to 50, then move it by +2.3 and -0.6 from 50 to 200.
- **Longer training**: small-k10 trained to 8 times its stop and small-k200 to 4 times. Both rose
  further (+4.6 and +2.5), and small-k200 stayed 6.4 ± 1.4 above small-k10.
- **Repeatability**: the same strategy file, setting and seed give the same result deal by deal,
  in another process.

## Speed and memory

At 20 big blinds, 4 threads (this machine: 4 Intel Xeon cores at 2.1 GHz):

| Menu | 10 buckets | 50 buckets | 200 buckets |
| --- | ---: | ---: | ---: |
| small, iterations/s | 160,289 | 145,148 | 122,991 |
| standard, iterations/s | 76,890 | 64,522 | 53,464 |

- An iteration visits about 190 game states on the small menu and 360 to 380 on the standard
  one, so in states the speed is 18 to 30 million a second, falling as the table grows.
- **Threads** (standard-k200, linear weighting): 15,027 iterations/s on 1 thread, 28,042 on 2
  (1.87 times), 45,055 on 3 (3.00), 56,058 on 4 (3.73, 93% of linear).
- **Memory**: 60 to 65 bytes an information set (12 bytes a slot, 2.5 slots a set, and about 30
  bytes of index). standard-k200 at 20bb: 1.1M information sets, a 67 MB table, 424 MB for the
  process with the bucket tables and LBR's tables, a 54 MB checkpoint, a 5.5 MB strategy file.
- **Pruning** (Pluribus's, thresholds of -10,000 and -100,000 big blinds from 10M iterations):
  2% faster at 17M iterations, because few regrets are that low yet.
- **The Phase 6 game** (200bb, `rich`, 200 buckets: 97.2M information sets, 251.7M slots),
  trained here for 25 minutes on 4 threads and 5 on 1 through the cloud trainer contract:
  10 to 11 million states a second on 4 threads, 2.7M a thread, the same as on 1
  thread; 1,134 states an iteration by 15M iterations, with 93.3M information sets met. The table
  was 5.06 GB (7.22 GB after the resume, which sizes the index with room to grow), the process
  6.4 to 7.4 GB, the checkpoint 4.69 GB.

## Phase 6 projection

`docs/research/runs/phase5_gate/projection.py` (output in `projection.md` there); the method
and the caveats are in `docs/research/experiments.md`, "Phase 6 projection".

- **Size**: 97.2M information sets, 251.7M slots.
- **Memory**: a 5.2 GB table in a fresh run, 7.3 GB after a resume; the process 6.4 to 7.4 GB
  here; a 4.9 GB checkpoint and a 0.5 GB strategy file. The 512 GB of a c4a-highmem-64 is about
  60 times that. A c4a-highcpu-64 (the same 64 cores, 128 GB) is enough, at $1.45 an hour spot
  against $2.25 (Google's prices, 27 Nov 2026; the projection used $1.31 and $2.05). The run's
  plan: `docs/research/runs/phase6/README.md`.
- **Hours on 64 threads**: at the central speed, 2.5 (a power law in iterations fitted to the
  gate's runs) to 13.9 (states per information set as at 20bb), about $5 to $28 spot. Across all
  the ranges, 0.5 to 47 hours ($96 at the high end).
- **The uncertainty is a factor of about 100**, mostly in the work: convergence is read off 20bb
  games of up to 1.1M information sets and extrapolated 88 times, to a 200bb game. The speed of
  an Axion core and the scaling to 64 threads are guesses (no Arm machine here). A few hours on
  the rented machine, with LBR and the change measure at each doubling, would narrow it.

## Tests

```bash
cargo test --release -p blueprint
BLUEPRINT_TABLES=~/abstraction/k10 BLUEPRINT_OTHER_TABLES=~/abstraction/k50 \
    cargo test --release -p blueprint --test tables -- --include-ignored
```

The first takes about 40 seconds. The tests use a small card abstraction of their own (169
preflop classes, then the 9 hand categories), so they need no built tables:

- `tests/file.rs`: the file holds the average strategy (or the current one where there is no
  average), survives a round trip, and is refused when damaged or for another game; the change
  between two strategies.
- `tests/play.rs`: on the menu the blueprint plays exactly the stored strategy, from either
  seat; off the menu every answer is legal, sums to one, and is the same from both interfaces
  of `Strategy`, with both readings of small bets; bets between two menu sizes are read with
  the mapping's probabilities (within 4 standard errors over 4,000 seeds); small bets read as
  a check or call follow the mapping too, and the street goes on as described; when the
  abstract hand is over the blueprint checks or calls.
- `tests/lbr.rs`: LBR wins much less against a trained strategy than against the same menu
  played uniformly (more than 5 standard errors).
- `tests/tables.rs`: the adapter gives the tables' own buckets, and tables for a smaller deck
  are refused. With `BLUEPRINT_TABLES`: a run trains, stops, resumes, saves and plays, and
  refuses another spec and other tables; the cloud trainer keeps its contract (progress lines,
  75 on SIGTERM, `--resume`, 0 and a strategy at the end); a small gate plan trains in stages,
  logs everything, stops by its rule, and reads its results back when started again. Without
  `BLUEPRINT_TABLES` these three pass without checking anything. The nightly "Rust slow tests"
  workflow builds k10 and k50 first (cached until `abstraction`'s code changes) and sets
  `BLUEPRINT_TABLES` and `BLUEPRINT_OTHER_TABLES`, so it checks them.
- Unit tests: quantizing, the spec's JSON and menus, and paired differences on the same deals.

## Layout

| File | What |
| --- | --- |
| `src/buckets.rs` | The adapter: `abstraction`'s tables as `abstract_game`'s `Bucketer`, with what identifies them |
| `src/spec.rs` | A run's game and training settings, and the menus by name |
| `src/train.rs` | `Run`: training with threads and checkpoints, the session log, export |
| `src/file.rs` | The strategy file |
| `src/play.rs` | `Blueprint`: the strategy in the real game, as `lbr`'s `Strategy` |
| `src/matches.rs` | LBR matches that keep each deal's result, for paired differences |
| `src/gate.rs` | The gate procedure |
| `src/bin/blueprint.rs` | The command |
