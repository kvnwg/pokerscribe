# PokerScribe: notes for Claude

## What this is

Kevin's macOS app (Python, PySide6). It reads a poker table from screen captures (cards by template
matching, amounts by OCR, layout analysis, a hand tracker between reads) and shows one instruction
per decision. Built and tested on 247 Free Poker (play money, bots). The long-term goal is a
solver-based No-Limit Hold'em agent: Modicum (heads-up) first, then Pluribus (six-max), following
the roadmap in `docs/research/README.md`.

This repo is the source of truth. It replaced the zip builds shared in chat on 26 Nov 2026.

## Ground rules

- Rule 4 in `docs/research/README.md`: testing and automated play stay offline or in environments we
  own or may use. No auto-play on live sites, no detection evasion, no real-money use. Reader work
  targets 247; don't tune it for real-money poker clients.
- The baseline agent B0 (`docs/research/baseline_tuning.json`) is frozen and is the floor. A new
  agent version replaces the previous one only if it beats it by 2.5 standard errors in paired
  simulation (`tools/compare.py`), LBR (local best response) wins less against it, and the result
  repeats on fresh seeds. Log every run in `docs/research/experiments.md`.
- Plain bug fixes (a misread, folding when checking is free) need a regression test, not a simulation.
- Recorded human or Pluribus actions are observations, never labels of correct play.
- The `TUNING` dict rule applies only to the frozen rule engine: new options for it go in `TUNING`
  in `app/poker/advice.py`, off by default until they pass the bar above. B0 itself isn't tuned
  any more (shelved).
- Outside solvers (TexasSolver, postflop-solver) are AGPL. Run them as black boxes to check our
  results; never copy their code.

## Setup and tests

```
./setup_mac.sh                      # creates .venv and installs everything
./run_mac.sh                        # starts the app
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # every test should pass
./run_mac.sh --image app/assets/demo/demo_flop.png   # try it without a poker client
```

GitHub Actions runs the tests on every pull request and every push to `main` (`.github/workflows/`):
`rust.yml` (`cargo test --release` in `engine/`), `python.yml` (`python -m pytest` on Linux, on Python
3.12 and 3.13) and `rust-slow.yml` (the `#[ignore]` tests, nightly and on demand). Never skip, disable
or loosen a test to make a check pass. The Python check fails if any test is skipped: when a new
test needs a program or package, install it in `python.yml`. To run the Python tests in a Linux
session, install what `python.yml` installs (Xvfb, the Qt libraries, Tesseract, the fonts) and build
the Rust engine as it does. README.md, "Checks", has the rest.

## Where things are

- `README.md`: the user guide and the project structure.
- `docs/research/SCREEN_READING.md`: the reading steps in order, with what's done and what isn't.
  Start here for any reader work.
- `docs/research/`: the research report link, `KNOWLEDGE.md` (book and paper principles),
  `experiments.md`, `DATASET.md`, `DEMO.md`, and `runs/` (raw experiment scripts and logs).
- `tools/replay_reads.py "<saved reads folder>"`: replays a "Save last reads" folder through the
  current reader, tracker and advice, and prints then vs now for each picture.
- `tools/simulate.py`, `tools/compare.py`: the simulator (six-max, or heads-up with `--players 2`)
  and paired comparisons. By default a comparison deals duplicate decks (heads-up: each deal twice
  with the seats swapped) and replays each hand that differs 6 times from where the variants part,
  dealing the opponents fresh hands they could have held: use the "replayed 6 times" figure.
  `--method classic` rebuilds results from before Phase 1; `--jobs 4` splits a run over processes
  with identical results.
- `tools/luck.py`: the AIVAT-style luck adjustment for board cards. `tools/hidden.py`: the opponents'
  classes (what they could hold), the redeal, and AIVAT's imaginary observations (`--hidden`).
- `tools/weakness.py`: ranks the spots where another move would have won more; `--check-flaws`
  tests it on planted flaws.
- Held-out opponents: the `heldout`, `regulars`, `switchers` and `wildcards` tables in
  `tools/simulate.py` (`HELD_OUT_TABLES`). Never tune on them; judge promotions on them.
- `app/solver/`: the Phase 2 solvers. `solve_river` (Discounted CFR on a river spot),
  `solve_push_fold` (heads-up jam-or-fold), the exploitability checker, timing and the label
  format. `ranges.py` works out both players' river ranges from the betting so far, which
  `app/poker/history.py` records while watching. See `docs/research/SOLVER.md`.
- `engine/`: the Rust core (Phase 3 on), a Cargo workspace with crates in `engine/crates/*`. Speed
  critical code (rules engine, hand evaluator, CFR, subgame solver, blueprint) goes here. Python
  stays for the app, analysis and experiment scripts, not for speed-critical loops.
- `engine/crates/subgame`: the Rust river and turn solver (Phase 4), Discounted CFR over every combo
  with an exact best response, a SPOT in and a RESULT out (`subgame-solve`). Default target 0.2% of
  the pot; passes every Phase 4 gate on the 40 answer-key spots (`docs/research/PHASE4.md`).
  `app/solver/rust_backend.py` runs it, behind the `rust_solver` switch (off).
- `engine/crates/abstract_game`: the shrunk heads-up game the `cfr` crate trains on (Phase 5): bet-size
  menus, the pseudo-harmonic mapping for bets off the menu, a `Bucketer` trait and `AbstractGame`.
- `engine/crates/lbr`: local best response (Lisy and Bowling 2017) for heads-up play (Phase 5). What it
  wins against a `Strategy` is a lower bound on how exploitable that strategy is.
- `engine/crates/arena`: matches between agents, heads-up to six-max, duplicate deals and the all-in
  equity adjustment, bb/100 with its standard error (the tool behind the 2.5 SE rule). The `arena`
  binary plays the built-in bots.
- `engine/crates/py`: Python bindings (PyO3, module `pokerscribe_engine`) for `eval` and `nlhe`, and
  arena matches from Python (`run_match`, with Rust agents by name or Python agents).
  `./setup_mac.sh` builds it when Rust is installed; `app/tests/test_engine_bindings.py` tests it.
- `data/answer_keys/`, `tools/answer_keys/`: 40 river and turn spots and TexasSolver's answers to them, the
  keys the solvers are checked against. Format: `data/SPOT_FORMAT.md`. All 40 solved. TexasSolver is AGPL: it is
  built and run from `~/answer-keys`, never in the repo (`data/answer_keys/README.md`).
- `data/reference_spots/python_solver/`, `tools/reference_spots/`: 20 river spots solved by the Python
  solver to 0.001% of the pot (12 with answers known by hand), the reference a faster solver is checked
  against. `python -m tools.reference_spots rust` checks the Rust solver. Write-up:
  `docs/research/RIVER_SOLVER.md`.
- `tools/slumbot/`: heads-up benchmark against Slumbot through its public bot API (client, action-string
  parser, check/call bot, B0 stub, JSONL hand log, bb/100). See `tools/slumbot/README.md`.
- `tools/b0_arena.py`: B0 against any Rust agent heads-up in the Rust arena (each deal twice with the
  seats swapped, all-in equity, bb/100 with SE), through `pokerscribe_engine.run_match`, which takes
  any Python agent too (`engine/crates/py/README.md`). A Rust agent (a `Player` or a `Strategy`)
  becomes playable from Python with one line in `engine/crates/py/src/agents.rs`.
- `tools/phh/`: the hand history dataset pipeline (PokerKit 0.7.8), shelved for now. The built data
  isn't in the repo (112 MB, from a 17 GB source); rebuild it as `tools/phh/README.md` describes.

## Status, 26 Nov 2026

The roadmap changed today: the rule-engine plan is replaced by a solver-based agent (Modicum
heads-up, then Pluribus six-max). The old plan is kept under "Previous roadmap" in
`docs/research/README.md`, along with what's shelved.

- Phase 0 is done: correct inputs, capture log, frozen B0.
- Phase 1 is done (27 Nov 2026): duplicate deals, luck adjustment, heads-up simulator mode. Its
  gate is standard error at least halved and B0 playing heads-up.
  Built (for the old roadmap's Phase 1): duplicate deals, the luck adjustment, replays that
  redeal the opponents, AIVAT imaginary observations, held-out tables and the weakness report.
  The SE gate as written was not passed: gate run 5 (pre-registered, seeds 808 and 909) gave a
  geometric mean of 0.46 (bar 0.5) at 1.24 times the CPU (bar 1.25), but `texture_sizing` was at
  0.7507, over the 0.75 per-comparison bar. Kevin then closed it as good enough (`experiments.md`,
  Phase 1, gate run 5). Pooled over runs 4 and 5, the SE is 0.41 to 0.65 of classic on the four
  sizing comparisons and 0.16 on `push_chart`. The "replayed 6 times" figure was checked
  against the raw difference on large runs: no bias (pre-registered, 48000 new hands; a gap on
  the gate runs' hands was luck in the raw figure; `experiments.md`, Phase 1 check).
  The heads-up mode came last (`--players 2` in `tools/simulate.py` and `tools/compare.py`, each
  deal played twice with the seats swapped; `experiments.md`, Phase 1: the heads-up mode). B0
  plays heads-up with no always-wrong instruction in 37629 instructions, and six-max plays exactly
  as before.
  Its gate run (pre-registered, run 5's rule, seeds 1111 to 1414) gave a geometric mean of 0.38
  and a largest r of 0.53, but 1.41 times the CPU (bar 1.25): it fails as written, on CPU only.
  The manager session accepted it under Kevin's delegation (`experiments.md`, The gate,
  heads-up, Decision): per CPU second the SE is 0.45 of classic's. The bots keep their six-max
  styles, so heads-up they fold a lot and B0 beats every table. Head-to-head play (two agents
  against each other heads-up) is in the Rust arena now, B0 included: `tools/b0_arena.py` and
  `pokerscribe_engine.run_match` (Phase 6 groundwork, below).
- Fixed on 27 Nov 2026 (found by the heads-up work): B0 said a bet under the minimum in a tiny
  pot (BET 1.5 into two big blinds, six-max, about 1 in 5200 instructions). A last check in
  `advise()` (`_legal_size`) keeps every bet and raise between the minimum and the stack. No
  simulated hand's result changed (`experiments.md`, B0 fix: no bet under the minimum).
- Phase 2 is basically done: the river solver and the push-or-fold solver in `app/solver/` match the
  closed-form and published results, with p95 decision time under 400 ms. They are now the
  reference that the Phase 4 Rust solver must match. The switch `river_solver` stays off.
  Also there, built under the old roadmap on the day it was replaced: river ranges from the
  betting so far (on held-out simulated hands the opponent's real cards are in the range 89% to
  98% of the time, 59% to 81% before, mostly thanks to the profile), an answer to a raise of
  your bet (checked on made-up raises only: the simulator's bots almost never raise the river),
  a fixed amount of work in place of the clock in the simulator so runs repeat exactly, and an
  accuracy that follows the pot. The old roadmap's comparison of `river_solver` against B0 was
  run once, before those additions (both ranges the "medium" preset): it passed on the first
  seeds (mixed, +5.8 ± 2.0 bb/100, 2.94 SE; no loss on fish247 or the held-out tables) but didn't
  repeat on fresh seeds (+2.0 ± 2.2), so the switch stays off (`experiments.md`, Phase 2, the
  river solver against B0). It hasn't been run with the new ranges, and the new roadmap doesn't
  ask for it.
- Phase 3 is under way: the Rust core on toy games in `engine/`. Crates so far: `cfr` (CFR
  library), `toygames` (Kuhn, Leduc), `nlhe` (rules engine) and `eval` (hand evaluator). Its gate:
  Kuhn value -1/18 and exploitability under 0.001, Leduc matches OpenSpiel, evaluator exact on all
  7-card hands. Model for all sessions: Claude Opus 5.5 at extra-high effort (Kevin's choice, 26 Nov
  2026). Don't use Fable.
- Phase 6 groundwork, 27 Nov 2026: B0 plays any Rust agent heads-up in the arena
  (`tools/b0_arena.py`; `experiments.md`, Phase 6 groundwork). It sees each spot exactly as in
  the simulator. No instruction was illegal in 41145. B0 against B0 is exactly 0, and it beats
  always-fold and always-call by 29 and 12.5 SE. B0 is the slow part: 22 to 32 hands per second
  on one process against near-equal bots (tag +8.2 ± 5.6, tag-loose +2.5 ± 7.4), 94% of it in
  B0's Monte Carlo equity. At their sd (300 to 400 per deal) a 2.5 SE test of a 5 bb/100 edge
  needs 47,000 to 81,000 hands, and one of 10 bb/100 needs 12,000 to 20,000. The simulator's
  always-wrong check flagged 9 jams with AKo facing big re-raises from the LBR random
  strategies: a false alarm (the check ignores the bet faced). B0 calls a 100 big blind jam with
  JJ or better only.
- Reader bugs already reported still get fixed (no new reader work otherwise). Kevin presses "Save
  last reads" when an instruction is wrong (folders go to `~/Documents/PokerScribe reads/<time>`).
  For each folder: run `tools/replay_reads.py`, find the cause, fix it, add a regression test.
  Waiting for saved reads: it can't tell whose turn it is; it said to fold the big blind; it said
  to bet half the starting stack with 9-6; it mixed up the pot and the bets.
- Known reader gaps: other players' turn (the timer bar on their seats isn't read yet), and the
  "Total pot = Pot + bets" and Call amount checks don't block advice yet.
- Unconfirmed: whether the Q9 offsuit all-in hand was at 1/2 blinds.
- Possible goal: a demo at Web Summit Vancouver, 25 to 28 May 2027 (`docs/research/DEMO.md`, not
  approved). A heads-up challenge needs Phase 7; six-max won't be ready by then.

## Writing for Kevin

Never use em dashes.
