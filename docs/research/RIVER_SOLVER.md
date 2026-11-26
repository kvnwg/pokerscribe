# The Python river solver, as a reference (Phase 2)

The solver in `app/solver` is no longer headed for the app. The production solver is the
Rust one in `engine/crates/subgame`. The Python one is now the reference: the thing the
Rust solver, and anything after it, is checked against. This page says what it does, where
it stops, how accurate it is and how long it takes.

For the package file by file, the conventions and how the advice would call it, see
`SOLVER.md`. This page doesn't repeat that.

Measured 26 Nov 2026 on the cloud session (Linux, 4 cores, Python 3.13). Every number here
comes from `runs/phase2_reference.py`, raw output in `runs/phase2_reference.log`.

## In short

- **It finds the known answers.** On the 12 spots whose answer can be worked out by hand,
  it gets the bluff share and the call share right to within 0.0002 and the value of the
  game to within 0.001 chips of a pot of 100.
- **It gets as close to an equilibrium as you pay for.** Left to run, every one of the 20
  reference spots is within 0.001% of the pot. In the 300 ms the app allows, they are
  within 0.02% to 0.08%.
- **It agrees with two other solvers.** TexasSolver on its 30 river answer keys, and the
  new Rust solver on all 20 reference spots.
- **It is slow next to the Rust solver**: 5 to 7 times slower to the same accuracy on the
  widest spots here, and far more on small ones. That is why it is the reference and not
  the product.
- **It only knows the river, two players and a fixed menu of bet sizes.**

## What it does

**The river solver** (`solve_river(spot, time_budget_ms)`) takes one river spot between two
players:

- the five board cards, the pot and both stacks;
- each player's range: any hands, each with a weight;
- the bet and raise sizes each player may use, and how many raises are allowed.

It gives back, for every decision point in the betting, how often each hand takes each
action, and one number saying how good that answer is.

- **Method.** Discounted CFR (Brown and Sandholm 2019) over every hand in both ranges, with
  exact card removal: two hands that share a card are never dealt together. Nothing is
  bucketed or sampled.
- **When it stops.** At the first of: the time limit, a number of iterations, or an answer
  good enough (0.1% of the pot unless told otherwise, checked at iterations 8, 16, 32 and
  so on).
- **The measure.** Exploitability: how much a perfect counter-strategy would win per hand
  against the answer, averaged over the two players, as a share of the pot. It is 0 exactly
  at an equilibrium. `app/solver/exploitability.py` works it out exactly, apart from the
  solve, so it can grade any solver's answer, not only this one's.
- **Value and bounds.** The same code gives each player's winnings per hand when both
  follow the answer, and a low and a high bound on the spot's true value. The window is
  twice the exploitability wide. Every equilibrium of a spot has the same value, which is
  what makes two solvers comparable.

**The push-or-fold solver** (`solve_push_fold(stack_bb)`) is separate and much smaller:
heads-up before the flop, where the small blind may only go all in or fold and the big
blind may only call or fold. For each of the 169 starting hands it gives how often to jam
and how often to call, using exact all-in equities with card removal.

## The reference spots

`data/reference_spots/python_solver/` holds 20 river spots and this solver's answer to each,
in the formats of `data/SPOT_FORMAT.md`. Its README lists them and shows the sums behind
the known answers.

- **py01 to py12: known answers.** Eight sizes and shapes of the half-street game from The
  Mathematics of Poker (a player with the nuts or air bets into a bluff catcher), one range
  with too few bluffs, two where one side holds only the nuts, and one where the board
  plays.
- **py13 to py16: realistic, written as ranges.** Dry, wet and paired boards, stacks from
  half a pot to five pots, up to three bet sizes and two raises.
- **py17 to py20: realistic, with the app's own ranges.** The weighted ranges
  `app/solver/ranges.py` builds from a betting line, up to 528 combos a player.

## How accurate it is

### Against answers worked out by hand

For a bet of s times the pot: bluffs are s/(1+2s) of the bets, and the bluff catcher calls
1/(1+s) of the time. "OOP" is the player out of position (first to act).

| Spot | Bet, pots | Bluff share: known | solver | Call share: known | solver | OOP value: known | solver |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| py01 | 0.5 | 0.2500 | 0.2501 | 0.6667 | 0.6667 | 78.9474 | 78.9474 |
| py02 | 0.75 | 0.3000 | 0.3001 | 0.5714 | 0.5715 | 77.4436 | 77.4436 |
| py03 | 1 | 0.3333 | 0.3334 | 0.5000 | 0.5001 | 76.3158 | 76.3158 |
| py04 | 2 | 0.4000 | 0.4000 | 0.3333 | 0.3334 | 73.6842 | 73.6842 |
| py05 | 0.25 | 0.1667 | 0.1668 | 0.8000 | 0.8001 | 81.0526 | 81.0526 |
| py06 | 1.5 | 0.3750 | 0.3750 | 0.4000 | 0.4000 | 74.7368 | 74.7368 |
| py07 | 1 | 0.3333 | 0.3333 | 0.5000 | 0.5001 | 23.6842 | 23.6842 |
| py08 | 0.6 | 0.2727 | 0.2727 | 0.6250 | 0.6250 | 78.2895 | 78.2895 |
| py09 |  |  |  |  |  | 0.0000 | 0.0004 |
| py10 |  |  |  |  |  | 0.0000 | -0.0008 |
| py11 |  |  |  |  |  | 100.0000 | 100.0007 |
| py12 |  |  |  |  |  | 50.0000 | 50.0001 |

py09 to py12 have no mixing to compare: the caller always folds (py09), air never bets or
calls (py10, py11), every hand splits (py12). The solver's values are within 0.001 chips
of 0, 0, 100 and 50.

The same checks as tests:

- `app/tests/test_solver_answer_keys.py`: the half-street game solved fresh at bet sizes
  0.5, 0.75, 1 and 2, with tolerances set before the solver existed.
- `app/tests/test_reference_spots.py`: the formulas worked out again in the test, asked of
  the saved answers and of fresh solves at sizes the first file doesn't have (0.25, 1.5,
  0.6 as an all in), with the bettor out of position, and with too few bluffs.
- `app/tests/test_solver_pushfold.py`: push-or-fold against the published chart (below).

### Per spot: how far from an equilibrium

"Reference answer" is the saved one: no clock, stopped at 0.001% of the pot. "At 300 ms" is
the same spot the way the app would solve it: 300 ms at most, stopping early at 0.1%.

| Spot | What | Combos (OOP, IP) | Decision points | Reference answer: iterations | Time | From an equilibrium | At 300 ms: iterations | Time | From an equilibrium |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| py01 | Known: nuts or air bets 0.5 pot | 6, 19 | 3 | 4,096 | 0.30 s | 0.0006% | 64 | 6 ms | 0.024% |
| py02 | Known: bets 0.75 pot | 6, 19 | 3 | 4,096 | 0.30 s | 0.0009% | 128 | 10 ms | 0.033% |
| py03 | Known: bets 1 pot | 6, 19 | 3 | 2,048 | 0.15 s | 0.0010% | 64 | 7 ms | 0.037% |
| py04 | Known: bets 2 pots | 6, 19 | 3 | 32,768 | 2.17 s | 0.0005% | 64 | 4 ms | 0.027% |
| py05 | Known: bets 0.25 pot | 6, 19 | 3 | 2,048 | 0.11 s | 0.0006% | 64 | 4 ms | 0.022% |
| py06 | Known: bets 1.5 pots | 6, 19 | 3 | 16,384 | 1.18 s | 0.0003% | 256 | 20 ms | 0.050% |
| py07 | Known: the bettor is out of position, 1 pot | 19, 6 | 3 | 2,048 | 0.16 s | 0.0006% | 128 | 10 ms | 0.047% |
| py08 | Known: the bet is all in for 0.6 pot | 6, 19 | 3 | 8,192 | 0.64 s | 0.0003% | 32 | 3 ms | 0.084% |
| py09 | Known: too few bluffs, always fold | 6, 13 | 3 | 128 | 0.01 s | 0.0004% | 32 | 2 ms | 0.023% |
| py10 | Known: only air against only the nuts | 16, 6 | 12 | 128 | 0.03 s | 0.0004% | 32 | 8 ms | 0.029% |
| py11 | Known: only the nuts against only air | 6, 16 | 12 | 128 | 0.03 s | 0.0005% | 32 | 8 ms | 0.026% |
| py12 | Known: royal flush on the board | 105, 42 | 12 | 128 | 0.05 s | 0.0001% | 16 | 7 ms | 0.065% |
| py13 | Dry board, SPR 1 | 62, 60 | 8 | 1,024 | 0.24 s | 0.0005% | 128 | 33 ms | 0.029% |
| py14 | Wet board, wide ranges, SPR 2.5 | 245, 226 | 12 | 4,096 | 3.05 s | 0.0005% | 256 | 186 ms | 0.042% |
| py15 | Paired board, SPR 0.5 | 100, 53 | 8 | 512 | 0.12 s | 0.0002% | 64 | 13 ms | 0.056% |
| py16 | Four to a straight, SPR 5, three sizes, two raises | 69, 72 | 30 | 2,048 | 1.51 s | 0.0005% | 256 | 251 ms | 0.053% |
| py17 | The app's ranges: big blind against button, two bets called | 258, 528 | 14 | 4,096 | 4.35 s | 0.0004% | 253 | 289 ms | 0.048% |
| py18 | The app's ranges: button against big blind, two bets called | 320, 480 | 14 | 4,096 | 4.86 s | 0.0005% | 225 | 290 ms | 0.065% |
| py19 | The app's ranges: re-raised pot | 186, 168 | 12 | 2,048 | 1.14 s | 0.0006% | 256 | 121 ms | 0.033% |
| py20 | The app's ranges: cutoff against button, pot-sized turn bet | 429, 201 | 16 | 4,096 | 4.13 s | 0.0006% | 256 | 242 ms | 0.079% |

- Every saved answer is within 0.001% of the pot, measured on the file as written
  (probabilities rounded to 6 places). So each spot's true value is known to within 0.002
  chips of a pot of 100.
- In 300 ms the answers are 0.02% to 0.08% of the pot from an equilibrium. The two widest
  spots (py17, py18) use the whole 300 ms. The rest stop early, the known ones in 2 to 20 ms.
- These 20 spots are not the hardest the app can meet. On 600 random benchmark spots
  (`experiments.md`, "Decision time") the widest ranges with the deepest stacks reached
  0.31% at p95 and 0.53% at worst inside 300 ms. Nothing there missed 1% of the pot.

### Against TexasSolver

TexasSolver is an outside solver (AGPL, run only as a separate program, never copied). Its
answers to 30 river spots are in `data/answer_keys`. They are up to 0.30% of the pot from an
equilibrium, so each of its values can be off by about that much.

- The bounds on the true value meet on all 30: the two solvers are solving the same game.
- The value from `app/solver` differs from TexasSolver's by 0.09 chips on average and
  0.31 at most (pot 100) when solved tight, and by 0.18 at most at 300 ms.
- The largest gap is r01, where the true value is exactly 100. `app/solver` says 100.000
  and TexasSolver 100.307, so that gap is TexasSolver's.
- At 300 ms `app/solver` was 0.02% to 0.10% of the pot from an equilibrium on those spots,
  in 4 to 199 ms.

The table for each spot is section 5 of the log.

### Against the Rust solver

`python -m tools.reference_spots rust` runs the Rust solver on the 20 reference spots and
checks each answer with the Python best response: near an equilibrium, value near the
reference, bounds that meet the reference's, known answers right.

| Spot | Reference value for OOP | Rust at its default target (0.3%): from an equilibrium | Value, less the reference | Rust at 0.01%: from an equilibrium | Value, less the reference | Bounds meet |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| py01 | 78.9474 | 0.1049% | +0.0026 | 0.0100% | +0.0000 | yes |
| py02 | 77.4436 | 0.2708% | -0.0092 | 0.0100% | +0.0000 | yes |
| py03 | 76.3158 | 0.1480% | -0.0021 | 0.0099% | +0.0000 | yes |
| py04 | 73.6842 | 0.2351% | -0.0035 | 0.0077% | -0.0000 | yes |
| py05 | 81.0526 | 0.2808% | +0.1002 | 0.0060% | +0.0000 | yes |
| py06 | 74.7368 | 0.2804% | -0.0055 | 0.0077% | +0.0000 | yes |
| py07 | 23.6842 | 0.1437% | +0.0019 | 0.0045% | -0.0000 | yes |
| py08 | 78.2895 | 0.2972% | -0.0111 | 0.0046% | +0.0000 | yes |
| py09 | 0.0004 | 0.1728% | +0.2055 | 0.0082% | +0.0095 | yes |
| py10 | -0.0008 | 0.2196% | -0.3774 | 0.0077% | -0.0124 | yes |
| py11 | 100.0007 | 0.1985% | +0.3428 | 0.0095% | +0.0157 | yes |
| py12 | 50.0001 | 0.1490% | +0.1312 | 0.0085% | +0.0074 | yes |
| py13 | 60.8292 | 0.2622% | -0.0953 | 0.0070% | -0.0025 | yes |
| py14 | 45.0889 | 0.2831% | -0.0171 | 0.0096% | +0.0009 | yes |
| py15 | 22.1939 | 0.2500% | -0.1724 | 0.0078% | -0.0038 | yes |
| py16 | 18.1528 | 0.2978% | -0.0843 | 0.0086% | +0.0002 | yes |
| py17 | 41.0277 | 0.2825% | +0.0981 | 0.0092% | +0.0018 | yes |
| py18 | 24.7260 | 0.2911% | -0.0130 | 0.0098% | +0.0046 | yes |
| py19 | 45.1658 | 0.2721% | -0.0314 | 0.0097% | -0.0020 | yes |
| py20 | 66.8974 | 0.2819% | -0.1289 | 0.0094% | -0.0021 | yes |

- No problems on any of the 20, at either target.
- At its default target the Rust value is within 0.38 chips of the reference on every spot
  (the Phase 4 gate allows 0.5). Solved to 0.01% it is within 0.016 chips, and its bluff and
  call shares on py01 to py08 are within half a point of the known ones.
- The two programs measure alike. On all 20 spots, what the Rust solver writes about its
  own answer (exploitability, values, bounds) is exactly what the Python best response
  gives for that answer, to the last stored decimal.

### Push-or-fold

| Stack, big blinds | ms | Iterations | Exploitability, big blinds a hand | Jam share | chart | Call share | chart | Small blind's result, big blinds a hand |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 15 | 200 | 0.0000009 | 71.5% | 72.2% | 62.1% | 62.3% | +0.0562 |
| 8 | 21 | 300 | 0.0000007 | 61.9% | 62.3% | 45.0% | 45.4% | -0.0041 |
| 10 | 12 | 200 | 0.0000008 | 58.3% | 58.4% | 37.4% | 37.3% | -0.0454 |
| 12 | 11 | 200 | 0.0000005 | 53.2% | 53.2% | 33.0% | 33.0% | -0.0825 |
| 15 | 14 | 250 | 0.0000005 | 45.7% | 45.7% | 28.5% | 28.8% | -0.1272 |

- The chart is the published heads-up equilibrium read hand by hand
  (`app/tests/pushfold_chart.py`). Shares are within 0.7 points of it at every stack.
  Where single hands differ from the chart, the two choices are worth within 0.01 big
  blinds of each other, and the chart itself is an equilibrium of our game to within 0.0002
  big blinds a hand (`test_solver_pushfold.py`).
- The research notes in `experiments.md` quote The Mathematics of Poker: the small blind
  jams about 58% of hands at 10 big blinds and 62% at 8. The solver says 58.3% and 61.9%.

## How long it takes

One iteration costs about 0.1 ms on the smallest spots and 1.3 ms on the widest ranges
here (258 against 528 combos). The cost follows the two ranges multiplied together and the
number of decision points.

Time to reach a given accuracy, with no clock (median of three runs):

| Spot | Combos (OOP, IP) | Nodes | To 0.5% of the pot: iterations | ms | To 0.1%: iterations | ms | To 0.01%: iterations | ms | ms an iteration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| py01 | 6, 19 | 3 | 32 | 4 | 64 | 6 | 256 | 23 | 0.09 |
| py02 | 6, 19 | 3 | 32 | 4 | 128 | 11 | 512 | 43 | 0.08 |
| py03 | 6, 19 | 3 | 32 | 4 | 64 | 6 | 1024 | 73 | 0.07 |
| py04 | 6, 19 | 3 | 16 | 2 | 64 | 5 | 2048 | 175 | 0.09 |
| py05 | 6, 19 | 3 | 16 | 2 | 64 | 7 | 256 | 24 | 0.09 |
| py06 | 6, 19 | 3 | 32 | 3 | 256 | 23 | 1024 | 116 | 0.11 |
| py07 | 19, 6 | 3 | 32 | 3 | 128 | 11 | 512 | 59 | 0.12 |
| py08 | 6, 19 | 3 | 16 | 3 | 32 | 5 | 512 | 37 | 0.07 |
| py09 | 6, 13 | 3 | 16 | 1 | 32 | 3 | 64 | 4 | 0.07 |
| py10 | 16, 6 | 12 | 16 | 5 | 32 | 10 | 64 | 19 | 0.30 |
| py11 | 6, 16 | 12 | 16 | 5 | 32 | 12 | 64 | 23 | 0.36 |
| py12 | 105, 42 | 12 | 8 | 5 | 16 | 8 | 32 | 15 | 0.47 |
| py13 | 62, 60 | 8 | 64 | 19 | 128 | 33 | 256 | 64 | 0.25 |
| py14 | 245, 226 | 12 | 64 | 43 | 256 | 202 | 1024 | 779 | 0.76 |
| py15 | 100, 53 | 8 | 32 | 9 | 64 | 16 | 128 | 43 | 0.34 |
| py16 | 69, 72 | 30 | 128 | 119 | 256 | 206 | 1024 | 790 | 0.77 |
| py17 | 258, 528 | 14 | 64 | 76 | 256 | 294 | 1024 | 1356 | 1.32 |
| py18 | 320, 480 | 14 | 64 | 99 | 256 | 382 | 1024 | 1366 | 1.33 |
| py19 | 186, 168 | 12 | 64 | 34 | 256 | 135 | 1024 | 666 | 0.65 |
| py20 | 429, 201 | 16 | 128 | 131 | 256 | 254 | 1024 | 1223 | 1.19 |

| Accuracy | Median spot | Slowest spot |
| --- | ---: | ---: |
| 0.5% of the pot (the Phase 4 gate) | 5 ms | 131 ms |
| 0.1% (where the app stops early) | 12 ms | 382 ms |
| 0.01% | 61 ms | 1.4 s |
| 0.001% (the reference answers) | 0.3 s | 4.9 s |

- All 20 reference answers together take about 25 seconds of solving.
- The 382 ms is py18 running on to iteration 256, the next point where the early stop is
  checked. With the app's 300 ms limit the same spot stops at iteration 225 and is at
  0.065%. So under the limit nothing here runs late, but the check points are coarse.
- For the app's own decisions (ranges from the betting, 400 held-out river decisions), the
  whole decision took about 300 ms at p95 against a target of 400 ms (`SOLVER.md`).
- Push-or-fold solves in 11 to 21 ms.
- For scale, the Rust solver reaches 0.01% on the two widest spots here in about 0.2 s
  where Python needs 1.4 s. On the smallest spots it takes about a millisecond or less
  where Python takes 20 to 175 ms (single runs, section 4 of the log).

## Limits

What it can't do:

1. **River only.** No turn or flop: it can't deal a card. The Rust solver does the turn.
2. **Two players only.**
3. **A fixed menu of bet sizes.** It solves the game with the sizes it is given, which is
   not quite poker. A real bet between two sizes has to be put in the tree by the caller
   (the advice does this for bets already made).
4. **The ranges are an input.** The answer is only as good as the ranges it is handed.
   Building them from the betting is a separate piece (`ranges.py`) with its own error.
5. **Push-or-fold is the short-stack game only.** Heads-up, blinds of 0.5 and 1, no ante,
   and no choice but all in or fold. It is the right model up to about 10 big blinds.

What to know when using it as a reference:

6. **Compare values, not hands.** A spot can have many equilibria. Two right answers can
   play single hands differently, so check exploitability, value and bounds. Hand
   frequencies are only pinned down in the small known games.
7. **Frequencies move far more than values.** An answer 0.3% of the pot from an equilibrium
   can have a call share 7 points off the known one (the Rust solver on py05 at its
   default target). Ask for the known shares only of a tight solve.
8. **The same answer every run, on one machine.** With no clock a solve repeats exactly.
   With the clock the number of iterations depends on how busy the machine is. Between
   machines the last decimals can differ, and the Python and Rust solvers part ways after a
   few iterations on exact ties (the Rust README, "Things to know", 3). The checks have
   tolerances for this.
9. **The last decimals are expensive.** py04 needs 2,048 iterations for 0.01% and 32,768
   for 0.001%.
10. **The SPOT format knows fewer tree options than `app/solver` does.** `BetSizes` has
    `reraises`, `allin_within` and `exact` (`SOLVER.md`), which the format can't say. So the
    reference spots use only bets, raises and all in, and the trees the advice builds when
    it faces a bet (the real bet as the only size there) are not among them.
11. **Speed.** Python with NumPy. Fine for a reference and for a single river decision,
    not for anything that solves many spots. The roadmap keeps Python out of
    speed-critical loops.
12. **The early stop is only checked at iterations 8, 16, 32 and so on**, so a solve can
    run up to twice as long as it needed.

It also isn't switched on: `TUNING["river_solver"]` stays off, and nothing in this work
changes the app or B0.

## Checking a solver against it

```bash
python -m tools.reference_spots check <folder of RESULT files>
```

```bash
python -m tools.reference_spots rust
```

```bash
python -m tools.reference_spots validate
```

- `check` takes any solver's answers to the 20 spots, as RESULT files named `py01.jsonl`
  and so on. `rust` builds that folder with `subgame-solve` first.
- `validate` checks the reference files themselves. The tests run it too.
- What is checked, and the options for tighter limits:
  `data/reference_spots/python_solver/README.md`.
- To add a spot, edit `tools/reference_spots/defs.py`, then `make-spots`, `solve` and
  `validate`.
