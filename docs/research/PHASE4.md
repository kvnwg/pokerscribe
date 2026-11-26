# Phase 4: checking the Rust subgame solver

Phase 4 of the roadmap (`README.md`) is the Rust subgame solver, river then turn. This page is
how it gets checked: the gates, the commands, and the results so far.

Status, 26 Nov 2026:

- **The harness is written** (`tools/answer_keys`: `export-python`, `compare`, `run`), with tests
  in `app/tests/test_answer_keys.py`.
- **The Python solver's numbers are in the table below.** It passes the EV and exploitability
  gates on all 30 river spots, and the time gate on this machine.
- **The Rust solver hasn't been run yet.** Its rows go in the same table.
- **One finding about the answer keys:** TexasSolver's turn answers are for a slightly different
  game from the exact one. See "TexasSolver on the turn" before reading any turn number.

## The gates

From the roadmap: "Matches Phase 2, closed-form results and TexasSolver within 0.5% pot EV; under
0.5% pot exploitability; river p95 under 400 ms."

| Gate | Checked by | On |
| --- | --- | --- |
| EV within 0.5% of the pot of Phase 2 | `compare --against python_solver` | 30 river spots |
| EV within 0.5% of the pot of TexasSolver | `compare` (TexasSolver is the default) | 30 river spots, 10 turn spots |
| Exploitability under 0.5% of the pot | `compare`, recomputed by us | every spot |
| River p95 under 400 ms | `run`, wall time | 30 river spots |
| Closed-form results | the expected checks of the three trivial spots (r01 to r03), in `compare` | see "Not covered" |

The spots and the answer keys are described in `data/answer_keys/README.md`, the formats in
`data/SPOT_FORMAT.md`.

## How to run the check

```
# 1. Once, or when app/solver or the spots change: the Phase 2 reference answers
.venv/bin/python -m tools.answer_keys export-python

# 2. Run the Rust binary on the spots (3 runs each), save its RESULTs, time it
.venv/bin/python -m tools.answer_keys run --solver engine/target/release/subgame-solve --name rust_solver --spots river

# 3. Compare what it saved with each reference
.venv/bin/python -m tools.answer_keys compare rust_solver --against python_solver
.venv/bin/python -m tools.answer_keys compare rust_solver
```

- `run` saves to `data/answer_keys/<name>/` (the binary's file name when `--name` is left out; never
  `texassolver` or `python_solver`). `--spots` is `river`, `turn` or `all`; spot ids after the
  command limit it further (`run --solver ... r05 r07`). `--target` (default 0.5), `--max-iterations`,
  `--time-ms` and `--threads` are passed on to the binary. `--repeat` is 3 by default.
- `compare` takes a folder, or the name of one in `data/answer_keys`. It prints one row per spot,
  then a pass/fail line per gate, and exits with 1 when a gate fails. `-v` adds the node where each
  spot's frequencies differ most. `--markdown` prints the table in Markdown and the row for the
  results table below.
- To try it all before the Rust binary exists, use the stand-in, which answers the same command
  line with `app/solver` (river spots only):

  ```
  .venv/bin/python -m tools.answer_keys run --solver tools/answer_keys/standin_solver.py --spots river --out /tmp/standin
  .venv/bin/python -m tools.answer_keys compare /tmp/standin --spots river
  ```

## What the binary must do

The harness knows the binary only by its command line:

```
subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.3] [--max-iterations N] [--time-ms N] [--threads N]
```

Three things the harness assumes, which the Rust side should confirm:

1. **`--target-exploitability` is in percent of the pot** (0.3 means 0.3%), as TexasSolver's accuracy
   is written. `run --target 0.5` passes `--target-exploitability 0.5`.
2. **The file at `--out` is the spot's RESULT** as `data/SPOT_FORMAT.md` defines it: JSON Lines, the
   header first, then one record per decision node, with exactly the spot's nodes and actions and
   the spot's `spot_sha256`. One JSON array of the same records, or `{"header": ..., "nodes": [...]}`,
   is read too, and so is gzip.
3. **The header's `solver` block has** `elapsed_s` (or `elapsed_ms`), `iterations` and
   `exploitability_pot` (a share of the pot: 0.003 is 0.3%).

A run that exits with a status other than 0, writes no file, or writes a result that doesn't fit
the spot is reported as failed with the reason, and isn't timed. When it saves a result, `run`
fills the header's `checks` block with our own numbers and leaves the rest as the binary wrote it.

## What `compare` measures

- **EV.** A RESULT holds strategies, not values, so each player's EV is worked out here from the
  strategies, exactly, over every deal with card removal (`tools/answer_keys/values.py`). The
  column is the answer's EV minus the reference's, for each player, in percent of the pot. The two
  are opposite, since the players' EVs add up to the pot. Gate: within 0.5.
- **Exploitability**, in percent of the pot: what a perfect counter-strategy wins.
  - River spots: recomputed by `app/solver`'s checker.
  - Turn spots: recomputed by an exact best response in `values.py`, which deals every river card.
    It takes about a second a spot. `--turn-exploitability reported` uses the solver's own number
    instead.
  - The solver's own number is shown next to it ("Reported"), and a line is printed when the two
    disagree.

  Gate: under 0.5.
- **Expected checks.** The trivial spots (r01 to r03) have answers anyone can see. A result that
  fails one fails the comparison.
- **Action frequencies**, reported only. A spot can have more than one equilibrium, so a difference
  isn't a mistake. At each decision node: how often the acting player takes each action, over the
  combos that get there. A node's difference is the largest difference for one action, in points.
  - "Freq mean": the mean over the nodes, each weighted by the chance that play reaches it (the
    smaller of the two answers' chances).
  - "Freq max": the largest over the nodes both answers reach at least 5% of the time. For a river
    node of a turn spot that means 5% of the time once its river card has come. `--min-reach`
    changes the 5%.
- **Time.** `run` measures the whole process, from starting it to its exit, so start-up, reading the
  spot and writing the result all count. p50 and p95 are nearest-rank percentiles over every run
  of a street (90 runs for the river spots at 3 runs each). The solver's own solve time, from its
  header, is shown beside it. `run` writes both to `index.json` in the results folder, and
  `compare` repeats them.

The maths in `values.py` is checked three ways in the tests: on river spots it gives `app/solver`'s
EV and exploitability to rounding error; on a small turn spot it gives the same EV, reach and
frequencies as playing every deal out one at a time; and with TexasSolver's rule for river cards
(next section) it gives TexasSolver's own exploitability on turn spots to the fifth decimal.

## Results

Measured in a cloud session (Linux x86_64, 4 cores, Python 3.13), 26 Nov 2026. Times mean nothing
on another machine: measure both solvers on the same one. Add a row with `compare --markdown`.

| Solver | Spots | Against | Largest EV difference | Largest exploitability | Expected checks | Freq mean / max (points) | River solve p50 / p95 (ms) | River wall p50 / p95 (ms) | Turn solve p50 / p95 (ms) | Turn wall p50 / p95 (ms) | Gates |
| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| python_solver | 30 | texassolver | 0.304% (r01) | 0.010% (r08) | 3 of 3 | 4.6 / 70.8 | 128 / 488 | - | - | - | PASS |
| standin (Python through the command line, target 0.5%) | 30 | texassolver | 0.265% (r17) | 0.450% (r21) | 3 of 3 | 3.9 / 69.4 | 20 / 53 | 129 / 210 | - | - | PASS |
| standin (the same run) | 30 | python_solver | 0.366% (r17) | 0.450% (r21) | 3 of 3 | 2.1 / 21.5 | 20 / 53 | 129 / 210 | - | - | PASS |
| Rust solver, river | | | | | | | | | | | to do |
| Rust solver, turn | | | | | | | | | | | to do |

- **`python_solver`** is the Phase 2 reference: `solve_river` (Discounted CFR) run to 0.01% of the
  pot with no clock, saved in `data/answer_keys/python_solver/`. Its solve times are for that tight
  target, in process, so they aren't the decision time. Its EVs are within 0.02% of the pot of each
  spot's true value.
- **`standin`** is the same solver run the way the Rust binary will be: one process per spot, at the
  gate's target of 0.5%. About 100 ms of its wall time is Python starting. It isn't saved in the
  repo. This is the row the Rust solver is measured against.
- The freq max of 70.8 is r03, where a royal flush is on the board: every hand splits, so any
  betting is an equilibrium. Without the three trivial spots the largest is 27.4 (r12).
- TexasSolver's own river answers pass the same check against `python_solver`: largest EV
  difference 0.304% (r01), largest exploitability 0.300% (r22).

Two things the Python rows say about the Rust solver's settings:

- **Stopping at 0.5% leaves little room on EV.** The stand-in stopped between 0.08% and 0.45%
  exploitability and was up to 0.37% of the pot from the reference's EV. An answer can be off in EV
  by up to twice its exploitability. A solver that stops just under 0.5% may pass one gate and miss
  the other, so 0.3% or lower is the safer target for the gate runs.
- **The time gate is not hard on these spots.** Python reaches 0.5% in 20 ms (p50) and 53 ms (p95)
  of solve time. The spots have at most 299 combos a side and 26 decision nodes.

### The Python reference, spot by spot

`compare python_solver --spots river --markdown`. EV and exploitability are in percent of the pot,
frequencies in points.

| Spot | Street | EV oop | dEV oop | dEV ip | Exploit. | Reported | Expected | Freq mean | Freq max | Solve ms | Iter. | Gates |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |
| r01 | river | 100.00 | -0.304 | +0.304 | 0.002 | 0.002 | ok | 13.4 | 23.3 | 12.9 | 64 | pass |
| r02 | river | -0.01 | +0.217 | -0.217 | 0.003 | 0.003 | ok | 4.5 | 12.5 | 24.3 | 128 | pass |
| r03 | river | 50.00 | +0.005 | -0.005 | 0.005 | 0.005 | ok | 54.8 | 70.8 | 7.4 | 32 | pass |
| r04 | river | 40.77 | -0.133 | +0.133 | 0.003 | 0.003 | - | 1.2 | 2.6 | 95.8 | 512 | pass |
| r05 | river | 38.36 | -0.143 | +0.143 | 0.009 | 0.009 | - | 0.5 | 1.2 | 215.5 | 512 | pass |
| r06 | river | 47.20 | +0.037 | -0.037 | 0.006 | 0.006 | - | 0.7 | 0.8 | 47.2 | 256 | pass |
| r07 | river | 45.59 | -0.011 | +0.011 | 0.003 | 0.003 | - | 1.1 | 2.6 | 587.3 | 1024 | pass |
| r08 | river | 37.32 | +0.024 | -0.024 | 0.010 | 0.010 | - | 2.1 | 4.3 | 198.1 | 512 | pass |
| r09 | river | 30.76 | -0.018 | +0.018 | 0.010 | 0.010 | - | 0.7 | 1.5 | 142.2 | 512 | pass |
| r10 | river | 10.85 | -0.104 | +0.104 | 0.004 | 0.004 | - | 2.1 | 5.6 | 66.1 | 256 | pass |
| r11 | river | 26.67 | -0.136 | +0.136 | 0.009 | 0.009 | - | 1.0 | 2.7 | 146.9 | 512 | pass |
| r12 | river | 43.82 | +0.030 | -0.030 | 0.007 | 0.007 | - | 8.2 | 27.4 | 97.1 | 512 | pass |
| r13 | river | 6.05 | -0.112 | +0.112 | 0.003 | 0.003 | - | 8.0 | 21.3 | 145.4 | 512 | pass |
| r14 | river | 9.65 | -0.020 | +0.020 | 0.001 | 0.001 | - | 1.1 | 2.6 | 58.4 | 256 | pass |
| r15 | river | 15.29 | -0.054 | +0.054 | 0.007 | 0.007 | - | 0.5 | 1.3 | 149.4 | 512 | pass |
| r16 | river | 53.96 | -0.010 | +0.010 | 0.005 | 0.005 | - | 4.1 | 9.5 | 127.8 | 512 | pass |
| r17 | river | -0.01 | +0.101 | -0.101 | 0.006 | 0.006 | - | 0.5 | 1.3 | 136.6 | 256 | pass |
| r18 | river | 43.01 | +0.046 | -0.046 | 0.006 | 0.006 | - | 1.4 | 2.0 | 182.5 | 512 | pass |
| r19 | river | 82.00 | +0.139 | -0.139 | 0.003 | 0.003 | - | 1.1 | 11.1 | 93.2 | 512 | pass |
| r20 | river | -0.00 | +0.191 | -0.191 | 0.003 | 0.003 | - | 3.7 | 9.9 | 59.9 | 256 | pass |
| r21 | river | 39.79 | +0.052 | -0.052 | 0.004 | 0.004 | - | 5.0 | 6.5 | 289.5 | 512 | pass |
| r22 | river | 68.65 | +0.065 | -0.065 | 0.009 | 0.009 | - | 6.3 | 19.7 | 133.6 | 512 | pass |
| r23 | river | 26.56 | -0.096 | +0.096 | 0.003 | 0.003 | - | 1.2 | 1.9 | 51.6 | 256 | pass |
| r24 | river | 55.59 | -0.005 | +0.005 | 0.005 | 0.005 | - | 0.5 | 3.4 | 488.3 | 1024 | pass |
| r25 | river | 42.89 | +0.024 | -0.024 | 0.010 | 0.010 | - | 5.0 | 11.0 | 148.9 | 256 | pass |
| r26 | river | -0.00 | +0.238 | -0.238 | 0.001 | 0.001 | - | 6.0 | 16.3 | 74.8 | 256 | pass |
| r27 | river | 22.19 | +0.025 | -0.025 | 0.001 | 0.001 | - | 1.3 | 2.5 | 52.4 | 256 | pass |
| r28 | river | 17.10 | -0.142 | +0.142 | 0.002 | 0.002 | - | 0.6 | 1.6 | 348.9 | 1024 | pass |
| r29 | river | 94.57 | +0.034 | -0.034 | 0.008 | 0.008 | - | 1.0 | 1.4 | 255.7 | 512 | pass |
| r30 | river | 47.76 | -0.066 | +0.066 | 0.002 | 0.002 | - | 0.6 | 1.5 | 112.4 | 512 | pass |

"EV oop" is the out of position player's EV. "dEV" is the Python answer's EV minus TexasSolver's.
TexasSolver stopped at 0.12% to 0.30% exploitability on these spots, so most of each difference is
TexasSolver's own distance from the true value.

## TexasSolver on the turn

**TexasSolver weighs each river card 1/46. The exact weight is 1/44.** On a turn board, a pair of
combos leaves 52 - 4 - 2 - 2 = 44 river cards. TexasSolver leaves out the opponent's two cards and
divides by 52 - 4 - 2 = 46. So in the game it solves, everything after the river card (the river
betting, and the showdown after an all-in on the turn) counts 44/46 as much as it should next to a
fold on the turn.

How it was found: our exact check of TexasSolver's turn answers gave about twice the exploitability
TexasSolver reports. Valuing the same answers with 1/46 in place of 1/44 gives TexasSolver's
reported number on all 10 turn spots, to the fifth decimal. `Game(spot, river_cards=46)` in
`values.py` is that rule, and a test keeps the evidence. The river spots have no card to deal and
are not affected: there our check and TexasSolver's number agree, as before.

| Spot | TexasSolver reports | Our check, by its rule (1/46) | Our check, exact (1/44) | Exact solve minus TexasSolver, EV oop |
| --- | ---: | ---: | ---: | ---: |
| t01 | 0.264% | 0.264% | 0.504% | +0.018% |
| t02 | 0.235% | 0.235% | 0.482% | +0.021% |
| t03 | 0.283% | 0.283% | 0.693% | -0.023% |
| t04 | 0.202% | 0.202% | 0.454% | +0.061% |
| t05 | 0.221% | 0.221% | 0.552% | -0.029% |
| t06 | 0.245% | 0.245% | 0.710% | -0.015% |
| t07 | 0.210% | 0.210% | 0.703% | -0.024% |
| t08 | 0.221% | 0.221% | 0.447% | +0.036% |
| t09 | 0.233% | 0.233% | 0.417% | -0.051% |
| t10 | 0.165% | 0.165% | 0.611% | +0.323% |

The last column is from a one-off experiment in the session that wrote this page, not from code in
the repo: a plain Discounted CFR in numpy on `values.Game`, run to 0.05% of the pot on each turn
spot in the exact game (5 to 25 s a spot), then compared with TexasSolver's answer by `compare`.

What it means:

- **TexasSolver's turn answers fail the exploitability gate themselves** when valued exactly: 0.42%
  to 0.71% of the pot, six of ten over 0.5%. `compare texassolver --spots turn` shows it. They are
  good answers to TexasSolver's game, not exact answers to ours.
- **The EV gate against them still works.** Both answers are valued by the exact rule, and an exact
  solve came within 0.33% of the pot of TexasSolver's EV on every turn spot, within 0.07% on nine
  of them. A correct Rust solver should pass, with least room on t10.
- **EVs must be worked out by one rule for both answers.** The same TexasSolver strategies valued
  by its own rule give EVs up to 1.4% of the pot away from the exact ones (t04). `compare` always
  uses the exact rule.
- **Turn frequencies will differ from TexasSolver's** by more than on the river (in the experiment:
  mean 0.8 to 12.4 points, with single nodes 2 to 55 points apart), partly because the games differ.
  They were never a gate.
- **This is why turn exploitability is recomputed** and not taken as reported. A solver with this
  mistake reports a low number and looks fine. Ours is exact and costs about a second a spot.

Options, for Kevin to choose:

1. Leave the turn keys as they are and use them as above. Nothing more to do.
2. Add an exact turn reference in Python: the experiment's solver, cleaned up and tested, with its
   answers saved next to the river reference. The Rust solver would then have a like-for-like turn
   reference, frequencies included. About 5 MB of results.
3. Look for a TexasSolver build or setting that deals exactly. Not checked here.

## Not covered

- **Closed-form results.** The gate names them. The 40 spots hold only the three trivial ones. The
  half-street game of The Mathematics of Poker is tested for the Python solver in
  `app/tests/test_solver_answer_keys.py`, on spots built in code. To put the Rust solver through it
  with this harness, write those spots as SPOT files in a folder of their own
  (`python -m tools.answer_keys --spots-dir <folder> run ...`), or test it in Rust.
- **A Phase 2 reference for turn spots.** `app/solver` solves river spots only, so
  `--against python_solver` checks EV on the 30 river spots and says so for the rest.
- **Bigger spots.** The time gate is measured on these 30 river spots. Wider ranges and bigger
  trees need their own timing run (`app/solver/timing.py` has the Phase 2 benchmark spots).
- **These files weren't edited** and are now out of date on the turn: `data/answer_keys/README.md`
  says every answer is under 0.3% of the pot (true by TexasSolver's rule only, for the turn spots)
  and that no turn checker exists; `data/SPOT_FORMAT.md` says the same of `checks.exploitability_pot`.

## Files

| File | What |
| --- | --- |
| `tools/answer_keys/values.py` | EVs, reach, action frequencies and an exact best response, for river and turn spots |
| `tools/answer_keys/compare.py` | The comparison and the gates |
| `tools/answer_keys/runner.py` | Runs and times a binary, saves its RESULTs and `index.json` |
| `tools/answer_keys/python_solver.py` | `export-python`: the river spots solved by `app/solver` |
| `tools/answer_keys/standin_solver.py` | The command line answered by `app/solver`, to test the harness |
| `data/answer_keys/python_solver/` | The Phase 2 reference answers (30 river RESULTs and `index.json`) |
