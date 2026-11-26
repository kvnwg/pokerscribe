# PokerScribe: notes for Claude

## What this is

Kevin's macOS app (Python, PySide6). It reads a poker table from screen captures (cards by template
matching, amounts by OCR, layout analysis, a hand tracker between reads) and shows one instruction
per decision. Built and tested on 247 Free Poker (play money, bots). The long-term goal is a
research-driven 6-max No-Limit Hold'em agent toward Pluribus strength, following the roadmap in
`docs/research/README.md`.

This repo is the source of truth. It replaced the zip builds shared in chat on 26 Nov 2026.

## Ground rules

- Rule 4 in `docs/research/README.md`: testing and automated play stay offline or in environments we
  own or may use. No auto-play on live sites, no detection evasion, no real-money use. Reader work
  targets 247; don't tune it for real-money poker clients.
- The baseline agent B0 (`docs/research/baseline_tuning.json`) is frozen. A change replaces it only
  after beating it by at least 2.5 standard errors in paired simulation (`tools/compare.py`), losing
  significantly to no opponent type, and repeating on fresh seeds. Log every run in
  `docs/research/experiments.md`.
- Plain bug fixes (a misread, folding when checking is free) need a regression test, not a simulation.
- Recorded human or Pluribus actions are observations, never labels of correct play.
- New strategy options go in the `TUNING` dict in `app/poker/advice.py`, off by default until they
  pass the bar above.

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
- `tools/fetch_reads.py`: Kevin's "Save last reads" folders, sent by the app to his private repository
  (Settings, Send reads; default `kvnwg/pokerscribe-reads`). Attach it with add_repo, then
  `python tools/fetch_reads.py` lists them with Kevin's notes and `--replay` replays the newest.
  Work only on reads from 247 or other play-money tables (rule 4): a buy-in, prize pool or real
  currency in the title means a real-money table, and those reads are not worked on.
- `tools/replay_reads.py "<saved reads folder>"`: replays a "Save last reads" folder through the
  current reader, tracker and advice, and prints then vs now for each picture.
- `tools/selftest.py`: PokerScribe plays on our own demo table (`app/tests/demo_table.py`, six
  layouts) and every read and instruction is checked against the truth. Results in
  `docs/research/runs/selftest.md`. Run it after any reader change.
- `tools/simulate.py`, `tools/compare.py`: the 6-max simulator and paired comparisons.
- `app/solver/`: the Phase 2 solvers. `solve_river` (Discounted CFR on a river spot),
  `solve_push_fold` (heads-up jam-or-fold), the exploitability checker, timing and the label
  format. See `docs/research/SOLVER.md`.
- `tools/phh/`: the hand history dataset pipeline (PokerKit 0.7.8). The built data isn't in the repo
  (112 MB, from a 17 GB source); rebuild it as `tools/phh/README.md` describes.

## Status, 26 Nov 2026

- Phase 0 is in progress. Kevin plays on 247 with watching on and presses "Save last reads" when an
  instruction is wrong (folders go to `~/Documents/PokerScribe reads/<time>`). For each folder: run
  `tools/replay_reads.py`, find the cause, fix it, add a regression test.
- Reports waiting for saved reads: it can't tell whose turn it is; it said to fold the big blind; it
  said to bet half the starting stack with 9-6; it mixed up the pot and the bets.
- Self-test (26 Nov): six layouts (one held out), fresh seeds, skipped pictures. Other players'
  turn is now read from the timer bar or glow (WAIT on their turn), and the misreads it found are
  fixed with tests. Lone single-digit bets come back UNKNOWN (the OCR can't read them reliably).
  The reports above may be fixed by this; confirm with saved reads from 247.
- Known reader gaps: the "Total pot = Pot + bets" and Call amount checks don't block advice yet,
  and the predicted next actor isn't used as a check.
- Unconfirmed: whether the Q9 offsuit all-in hand was at 1/2 blinds.
- After Phases 0 and 1 comes Phase 2, the river CFR solver. Suggested model from Phase 2 on: Claude Fable.
  Phase 2 status: the river solver and the push-or-fold solver are written and match the
  closed-form and published results, with p95 decision time under 400 ms. The switch
  `river_solver` is still off. Left for its gate: beating B0 by 2.5 SE, which waits for Phase 1.
- Possible goal: a demo at Web Summit Vancouver, 25 to 28 May 2027 (`docs/research/DEMO.md`, not approved).

## Writing for Kevin

Never use em dashes.
