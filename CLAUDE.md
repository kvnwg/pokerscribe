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

## Where things are

- `README.md`: the user guide and the project structure.
- `docs/research/SCREEN_READING.md`: the reading steps in order, with what's done and what isn't.
  Start here for any reader work.
- `docs/research/`: the research report link, `KNOWLEDGE.md` (book and paper principles),
  `experiments.md`, `DATASET.md`, `DEMO.md`, and `runs/` (raw experiment scripts and logs).
- `tools/replay_reads.py "<saved reads folder>"`: replays a "Save last reads" folder through the
  current reader, tracker and advice, and prints then vs now for each picture.
- `tools/simulate.py`, `tools/compare.py`: the 6-max simulator and paired comparisons.
- `app/solver/`: the Phase 2 solvers. `solve_river` (Discounted CFR on a river spot),
  `solve_push_fold` (heads-up jam-or-fold), the exploitability checker, timing and the label
  format. See `docs/research/SOLVER.md`.
- `engine/`: the Rust core (Phase 3 on), a Cargo workspace with crates in `engine/crates/*`. Speed
  critical code (rules engine, hand evaluator, CFR, subgame solver, blueprint) goes here. Python
  stays for the app, analysis and experiment scripts, not for speed-critical loops.
- `tools/phh/`: the hand history dataset pipeline (PokerKit 0.7.8), shelved for now. The built data
  isn't in the repo (112 MB, from a 17 GB source); rebuild it as `tools/phh/README.md` describes.

## Status, 26 Nov 2026

The roadmap changed today: the rule-engine plan is replaced by a solver-based agent (Modicum
heads-up, then Pluribus six-max). The old plan is kept under "Previous roadmap" in
`docs/research/README.md`, along with what's shelved.

- Phase 0 is done: correct inputs, capture log, frozen B0.
- Phase 1 is almost done: duplicate deals, luck adjustment, heads-up simulator mode. Its gate is
  standard error at least halved and B0 playing heads-up.
- Phase 2 is basically done: the river solver and the push-or-fold solver in `app/solver/` match the
  closed-form and published results, with p95 decision time under 400 ms. They are now the
  reference that the Phase 4 Rust solver must match. The switch `river_solver` stays off.
- Next is Phase 3: the Rust core on toy games in `engine/` (rules engine, hand evaluator, CFR
  library, exact best response), checked on Kuhn and Leduc. Suggested model: Claude Fable.
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
