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
- `tools/simulate.py`, `tools/compare.py`: the 6-max simulator and paired comparisons. By default a
  comparison deals duplicate decks and replays each hand that differs 6 times from where the
  variants part, dealing the opponents fresh hands they could have held: use the "replayed 6 times"
  figure. `--method classic` rebuilds results from before Phase 1; `--jobs 4` splits a run over
  processes with identical results.
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
- `data/answer_keys/`, `tools/answer_keys/`: 40 river and turn spots and TexasSolver's answers to them, the
  keys the solvers are checked against. Format: `data/SPOT_FORMAT.md`. All 40 solved. TexasSolver is AGPL: it is
  built and run from `~/answer-keys`, never in the repo (`data/answer_keys/README.md`).
- `tools/slumbot/`: heads-up benchmark against Slumbot through its public bot API (client, action-string
  parser, check/call bot, B0 stub, JSONL hand log, bb/100). See `tools/slumbot/README.md`.
- `tools/phh/`: the hand history dataset pipeline (PokerKit 0.7.8), shelved for now. The built data
  isn't in the repo (112 MB, from a 17 GB source); rebuild it as `tools/phh/README.md` describes.

## Status, 26 Nov 2026

The roadmap changed today: the rule-engine plan is replaced by a solver-based agent (Modicum
heads-up, then Pluribus six-max). The old plan is kept under "Previous roadmap" in
`docs/research/README.md`, along with what's shelved.

- Phase 0 is done: correct inputs, capture log, frozen B0.
- Phase 1 is almost done: duplicate deals, luck adjustment, heads-up simulator mode. Its gate is
  standard error at least halved and B0 playing heads-up.
  Built (for the old roadmap's Phase 1): duplicate deals, the luck adjustment, replays that
  redeal the opponents, AIVAT imaginary observations, held-out tables and the weakness report.
  The SE gate as written was not passed: gate run 5 (pre-registered, seeds 808 and 909) gave a
  geometric mean of 0.46 (bar 0.5) at 1.24 times the CPU (bar 1.25), but `texture_sizing` was at
  0.7507, over the 0.75 per-comparison bar. Kevin then closed it as good enough (`experiments.md`,
  Phase 1, gate run 5). Pooled over runs 4 and 5, the SE is 0.41 to 0.65 of classic on the four
  sizing comparisons and 0.16 on `push_chart`. The "replayed 6 times" figure was checked
  against the raw difference on large runs: no bias (pre-registered, 48000 new hands; a gap on
  the gate runs' hands was luck in the raw figure; `experiments.md`, Phase 1 check). Not built
  yet: the heads-up simulator mode (`tools/simulate.py` is six-max only).
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
  7-card hands. Suggested model: Claude Fable.
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
