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
  format. See `docs/research/SOLVER.md`.
- `tools/phh/`: the hand history dataset pipeline (PokerKit 0.7.8). The built data isn't in the repo
  (112 MB, from a 17 GB source); rebuild it as `tools/phh/README.md` describes.

## Status, 26 Nov 2026

- Phase 1 was started on 26 Nov at Kevin's request while Phase 0 waits for saved reads. Its tools
  are built (duplicate deals, luck adjustment, replays that redeal the opponents, AIVAT imaginary
  observations, held-out tables, weakness report). Gate run 4 failed the 0.75 per-comparison bar
  on two comparisons with almost no differing hands. Kevin then chose to judge only comparisons
  where at least 1% of hands differ, confirmed on fresh seeds. Gate run 5 (pre-registered, seeds
  808 and 909): geometric mean 0.46 (bar 0.5), CPU 1.24 (bar 1.25), but `texture_sizing` 0.7507
  is over the 0.75 bar, so the gate as written is not passed. After run 5 Kevin decided it is
  good enough: Phase 1 is closed on his call, not on a pass, and Phase 2's B0 comparison may go
  ahead (`experiments.md`, Phase 1, gate run 5). Pooled over runs 4 and 5, the SE is 0.41 to 0.65 of
  classic on the four sizing comparisons and 0.16 on `push_chart`; a run of this size fails about
  one time in three by chance.
- Phase 0 is in progress. Kevin plays on 247 with watching on and presses "Save last reads" when an
  instruction is wrong (folders go to `~/Documents/PokerScribe reads/<time>`). For each folder: run
  `tools/replay_reads.py`, find the cause, fix it, add a regression test.
- Reports waiting for saved reads: it can't tell whose turn it is; it said to fold the big blind; it
  said to bet half the starting stack with 9-6; it mixed up the pot and the bets.
- Known reader gaps: other players' turn (the timer bar on their seats isn't read yet), and the
  "Total pot = Pot + bets" and Call amount checks don't block advice yet.
- Unconfirmed: whether the Q9 offsuit all-in hand was at 1/2 blinds.
- After Phases 0 and 1 comes Phase 2, the river CFR solver. Suggested model from Phase 2 on: Claude Fable.
  Phase 2 status: the river solver and the push-or-fold solver are written and match the
  closed-form and published results, with p95 decision time under 400 ms. The switch
  `river_solver` is still off. Simulations now give the solver a fixed 300 iterations
  (`tools/simulate.py`, `SOLVER_ITERATIONS`) so they repeat exactly; the app keeps its 300 ms
  budget. The B0 comparison (pre-registered, 26 Nov): stage 1 passed (mixed, +5.8 ± 2.0 bb/100,
  2.94 SE; no loss on fish247 or the held-out tables), but on fresh seeds it didn't repeat (+2.0
  ± 2.2), so the switch stays off and B0 is unchanged. All 24000 mixed hands together: +3.9 ±
  1.5 (a description, not a test). A new try needs a new rule first, Kevin's call
  (`experiments.md`, Phase 2, the river solver against B0).
- Possible goal: a demo at Web Summit Vancouver, 25 to 28 May 2027 (`docs/research/DEMO.md`, not approved).

## Writing for Kevin

Never use em dashes.
