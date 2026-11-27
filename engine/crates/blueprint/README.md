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

GATE_SUMMARY

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
| `lbr --strategy F [--settings LIST] [--hands N] [--seed S] [--deals DIR] [--small-bets smallest\|check-or-call]` | LBR against a strategy file, on every core. `LIST` is short names (`fc14`, `fc34`, `fcpa14`, `fcpa34`, `b56_14`, `b56_34`) or `paper` |
| `reference --stack BB ...` | The same for always call, random action and random kind of action |
| `compare --a DEALS --b DEALS` | The difference between two matches on the same deals, with its paired standard error |
| `gate --plan F` | A whole gate plan in one process (`src/gate.rs`): stages, LBR after each, a stop rule, a final measurement. Started again, it carries on where it stopped |
| `bench --spec F [--seconds S] [--warmup S] [--threads 1,2,4]` | Training speed and memory |
| `size --stack BB --menu NAME --buckets B` | Information sets and regret slots of a game, without building it |
| `info F` | A strategy file's header |
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
| `compact_scale` | Regrets as 32-bit integers, `round(regret * scale)` (regrets are in chips) | 100 |
| `regret_floor` | Regrets never go below this, in chips (Pluribus: -310 million at a scale of 1) | -3.1 million |
| `linear` | `[interval, until]`: linear weighting every `interval` iterations up to `until` | none |
| `pruning` | `{warmup, threshold, probability}`: Pluribus's negative-regret pruning | none |

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

Checked end to end with the real supervisor (`docs/research/runs/phase5_gate/cloud_local_test.py`):
machine 1 trains, every process gets SIGTERM, the trainer saves at 2,558,692 iterations and
the supervisor uploads it; machine 2 starts with an empty disk, downloads it, resumes at
exactly 2,558,692 and finishes; the run's state is "done". The tables are not part of the
bundle: they are built on the machine (8 minutes for 200 buckets on 4 cores) or copied, at
the path the spec names.

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
- Two bytes a probability: SIZE_LINE
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

RESULTS

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
  `BLUEPRINT_TABLES` these three pass without checking anything, so the nightly run of the
  ignored tests stays green.
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
