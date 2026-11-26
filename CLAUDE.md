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
- `tools/simulate.py`, `tools/compare.py`: the 6-max simulator and paired comparisons.
- `app/solver/`: the Phase 2 solvers. `solve_river` (Discounted CFR on a river spot),
  `solve_push_fold` (heads-up jam-or-fold), the exploitability checker, timing and the label
  format. `ranges.py` works out both players' river ranges from the betting so far, which
  `app/poker/history.py` records while watching. See `docs/research/SOLVER.md`.
- `tools/slumbot/`: heads-up benchmark against Slumbot through its public bot API (client, action-string
  parser, check/call bot, B0 stub, JSONL hand log, bb/100). See `tools/slumbot/README.md`.
- `tools/phh/`: the hand history dataset pipeline (PokerKit 0.7.8). The built data isn't in the repo
  (112 MB, from a 17 GB source); rebuild it as `tools/phh/README.md` describes.

## Status, 26 Nov 2026

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
  closed-form and published results, with p95 decision time under 400 ms. The solver's ranges
  now come from the betting so far (who bet how much on each round, the seats, the opponent's
  profile), and it also answers a raise of your bet. On held-out simulated hands the
  opponent's real cards are in the range 89% to 98% of the time (59% to 81% before), mostly
  thanks to the profile; the raise answers were only checked on made-up raises, because the
  simulator's bots almost never raise the river. The switch `river_solver` is still off.
  Left for its gate: beating B0 by 2.5 SE, which waits for Phase 1 (run that comparison with
  `--profiles`, or the solver sees no betting record). In the simulator the solver now does a
  fixed amount of work in place of the clock, so that comparison repeats exactly, and its
  accuracy follows the pot (the same in chips for every pot, inside the same 300 ms).
- Possible goal: a demo at Web Summit Vancouver, 25 to 28 May 2027 (`docs/research/DEMO.md`, not approved).

## Writing for Kevin

Never use em dashes.
