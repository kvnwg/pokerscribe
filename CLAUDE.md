# PokerScribe: notes for Claude

## What this is

Kevin's macOS app (Python, PySide6). It reads a poker table from screen captures (cards by template
matching, amounts by OCR, layout analysis, a hand tracker between reads) and shows one instruction
per decision. Built and tested on 247 Free Poker (play money, bots). The long-term goal is a
solver-based No-Limit Hold'em agent: Modicum (heads-up) first, then Pluribus (six-max), following
the roadmap in `docs/research/README.md`. This repo is the source of truth (it replaced the zip
builds shared in chat on 26 Nov 2026).

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
- Held-out opponents (`HELD_OUT_TABLES` in `tools/simulate.py`): never tune on them; judge
  promotions on them.

## Setup and tests

```
./setup_mac.sh                      # creates .venv and installs everything
./run_mac.sh                        # starts the app
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # every test should pass
./run_mac.sh --image app/assets/demo/demo_flop.png   # try it without a poker client
```

GitHub Actions (`.github/workflows/`) runs on every pull request and push to `main`: `rust.yml`
(`cargo test --release` in `engine/`), `python.yml` (`python -m pytest` on Linux, Python 3.12 and
3.13) and `rust-slow.yml` (the `#[ignore]` tests, nightly and on demand). Never skip, disable or
loosen a test to make a check pass. The Python check fails if any test is skipped: when a new test
needs a program or package, install it in `python.yml`. To run the Python tests in a Linux session,
install what `python.yml` installs (Xvfb, the Qt libraries, Tesseract, the fonts) and build the
Rust engine as it does. README.md, "Checks", has the rest.

## Where things are

- `README.md`: the user guide and the project structure.
- `docs/research/SCREEN_READING.md`: the reading steps, done and not. Start here for reader work.
- `docs/research/`: roadmap (`README.md`), `KNOWLEDGE.md`, `experiments.md` (every run),
  `runs/` (raw scripts and logs).
- `docs/research/MANAGER.md`: the manager session's state file and its token habits.
- `tools/fetch_reads.py`, `tools/replay_reads.py`: Kevin's saved reads (see Reader work below).
- `tools/selftest.py`: plays our demo table (`app/tests/demo_table.py`) and checks every read and
  instruction against the truth. Run it after any reader change. Log: `runs/selftest.md`.
- `app/interact/`: clicks and keys in our own programs only; no backend for the system pointer or
  keyboard, and none is to be added (rule 4). `docs/research/INTERACT.md`.
- `tools/simulate.py`, `tools/compare.py`: simulator (six-max, `--players 2` heads-up) and paired
  comparisons; use the "replayed 6 times" figure. `tools/luck.py`, `tools/hidden.py`,
  `tools/weakness.py`: luck adjustment, opponents' hidden cards, weakness report.
- `app/solver/`: Python river and push-or-fold solvers (`docs/research/SOLVER.md`).
- `engine/`: the Rust core, for speed-critical code (Python for the app and analysis).
  Crates in `engine/crates/*`, each with a README: `cfr`, `toygames`, `nlhe`, `eval`, `subgame`
  (river and turn solver, `docs/research/PHASE4.md`), `abstract_game`, `abstraction`, `lbr`,
  `blueprint` (heads-up blueprint, the `tools/cloud` trainer), `search` (depth-limited search),
  `arena` (matches, bb/100 with SE), `py` (Python bindings `pokerscribe_engine`).
- `data/answer_keys/`, `tools/answer_keys/`: 40 spots with TexasSolver's answers (built and run
  outside the repo, `data/answer_keys/README.md`). `data/reference_spots/`: Python solver
  references (`docs/research/RIVER_SOLVER.md`).
- `tools/slumbot/`: Slumbot benchmark; `tools/b0_arena.py`: B0 against Rust agents; `tools/phh/`:
  hand histories, shelved. Each has a README or docstring.

## Status, 28 Nov 2026

The old rule-engine plan and what's shelved are under "Previous roadmap" in
`docs/research/README.md`. Every phase's details are in `docs/research/experiments.md`.

- **Phase 0** done: correct inputs, capture log, frozen B0.
- **Phase 1** done: duplicate deals, luck adjustment, replays, heads-up simulator mode. Gate failed
  narrowly as written (one comparison at 0.7507 of classic SE; heads-up 1.41 times the CPU) and
  was accepted. `experiments.md`, Phase 1.
- **Phase 2** done: Python river and push-or-fold solvers match the known results, p95 under
  400 ms; the reference for Phase 4. `river_solver` stays off (didn't repeat on fresh seeds).
  `SOLVER.md`, `experiments.md`, Phase 2.
- **Phase 3** done: Rust `cfr`, `toygames`, `nlhe`, `eval`; gate passed (Kuhn, Leduc against
  OpenSpiel, evaluator exact). `docs/research/README.md`, crate READMEs.
- **Phase 4** done: `subgame` passes every gate on the 40 answer-key spots at 0.2% of the pot.
  `rust_solver` switch off. `PHASE4.md`.
- **Phase 5** done: `abstract_game`, `lbr`, `abstraction`, `blueprint`. Gate failed 3 of 7 and
  Kevin accepted it; more bet sizes help, more buckets don't show in LBR; 200 buckets kept.
  `experiments.md`, Phase 5; `runs/phase5_gate/`.
- **Phase 6** done, gate passed: the heads-up 200bb blueprint (512M iterations) beats the 1M file
  by +147.7 ± 3.9 bb/100 and B0 by +16.3 ± 4.1. `experiments.md`, Phase 6; `runs/phase6/`.
- **Next, Phase 7**: depth-limited search on every postflop decision (Modicum) on this blueprint.
  Gate: beat the blueprint by 2.5 SE, a luck-adjusted Slumbot match, the GTO Wizard Benchmark.
  Groundwork (`search` crate): `experiments.md`, Phase 7 groundwork.
- Possible goal: a Web Summit demo, May 2027 (`DEMO.md`, not approved).

Sessions: Opus 5.5, never Fable. Effort (Kevin, 28 Nov 2026): xhigh for solver and engine code and
experiment design, high for normal coding, medium for write-ups, docs and routine checks.

## Reader work

Reported reader bugs still get fixed (no new reader work otherwise, unless Kevin asks). Kevin
presses "Save last reads" when an instruction is wrong. Folders go to
`~/Documents/PokerScribe reads/<time>`, and to his private reads repository once Settings, Send
reads is set up: attach it with add_repo, then `python tools/fetch_reads.py` lists them with his
notes and `--replay` replays the newest. Work only on reads from 247 or other play-money tables
(rule 4): a buy-in, prize pool or real currency in the title means a real-money table, and those
reads are not worked on. For each folder: run `tools/replay_reads.py "<folder>"` (then vs now for
each picture), find the cause, fix it, add a regression test.

Waiting for saved reads (some may already be fixed; confirm on 247):
- it can't tell whose turn it is;
- it said to fold the big blind;
- it said to bet half the starting stack with 9-6;
- it mixed up the pot and the bets;
- it didn't read a 5 in the middle (where, and on which table, not known yet).

Known gaps: `SCREEN_READING.md`, "Next".

## Writing for Kevin

Never use em dashes.
