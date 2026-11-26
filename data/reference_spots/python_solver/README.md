# Reference river spots, solved by the Python solver

20 river spots and the answer of the Python river solver (`app/solver`, Phase 2) to each.
They are what a faster solver is checked against: today the Rust one in
`engine/crates/subgame`, later anything that replaces it.

- `spots/`: the spots, one JSON file each. Format: `data/SPOT_FORMAT.md` (SPOT).
- `results/`: the answers, one JSON Lines file each. Format: the same document (RESULT).
  `solver.name` is `pokerscribe-river`.
- `index.json`: the numbers per spot (iterations, time, exploitability, value).
- Code: `tools/reference_spots/`. Tests: `app/tests/test_reference_spots.py`.
- Write-up of the solver itself: `docs/research/RIVER_SOLVER.md`.

## Why these, when `data/answer_keys` exists

`data/answer_keys` holds TexasSolver's answers. They are up to 0.30% of the pot from an
equilibrium, so each one pins the true value of its spot down to a window up to 0.6 chips
wide in a pot of 100. That is enough for the Phase 4 gate (0.5% of the pot) and no finer.

`data/answer_keys/python_solver` (`docs/research/PHASE4.md`) holds this same solver's
answers to those 40 spots, within 0.01% of the pot. The spots here are other spots, and
differ in three ways:

1. **Tighter.** Every answer here is within 0.001% of the pot of an equilibrium, so the
   true value of each spot is known to within 0.002 chips (`checks.oop_value_bounds`).
2. **Known answers.** 12 of the 20 have an answer worked out by hand (below). A solver
   that gets those wrong is wrong, whatever any other solver says.
3. **Other shapes.** Trees with no raise at all, one player who can't bet, an all in of
   0.6 pots, three bet sizes with two raises, and four spots with the ranges the app
   really builds from the betting (any weight for any combo, up to 528 combos a player).

## The spots

Every pot is 100, so chips are also percent of the pot. "From an equilibrium" is the
exploitability: what a perfect counter-strategy would win per hand, as a share of the pot.

<!-- reference-table:start -->
Solved on: Linux x86_64, 4 cores. Reference target: 0.001% of the pot.

| Spot | What | Combos (OOP, IP) | Nodes | Reference: iterations | Time | From an equilibrium | OOP value | Known value | At 300 ms: time | From an equilibrium |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| py01 | Known answer: nuts or air in position bets 0.5 pot into a bluff catcher | 6, 19 | 3 | 4096 | 0.30 s | 0.0006% | 78.9474 | 78.9474 | 6 ms | 0.024% |
| py02 | Known answer: nuts or air in position bets 0.75 pot into a bluff catcher | 6, 19 | 3 | 4096 | 0.30 s | 0.0009% | 77.4436 | 77.4436 | 10 ms | 0.033% |
| py03 | Known answer: nuts or air in position bets 1 pot into a bluff catcher | 6, 19 | 3 | 2048 | 0.15 s | 0.0010% | 76.3158 | 76.3158 | 7 ms | 0.037% |
| py04 | Known answer: nuts or air in position bets 2 pot into a bluff catcher | 6, 19 | 3 | 32768 | 2.17 s | 0.0005% | 73.6842 | 73.6842 | 4 ms | 0.027% |
| py05 | Known answer: nuts or air in position bets 0.25 pot into a bluff catcher | 6, 19 | 3 | 2048 | 0.11 s | 0.0006% | 81.0526 | 81.0526 | 4 ms | 0.022% |
| py06 | Known answer: nuts or air in position bets 1.5 pot into a bluff catcher | 6, 19 | 3 | 16384 | 1.18 s | 0.0003% | 74.7368 | 74.7368 | 20 ms | 0.050% |
| py07 | Known answer: nuts or air out of position bets 1 pot into a bluff catcher | 19, 6 | 3 | 2048 | 0.16 s | 0.0006% | 23.6842 | 23.6842 | 10 ms | 0.047% |
| py08 | Known answer: nuts or air in position, the only bet is all in for 0.6 pot | 6, 19 | 3 | 8192 | 0.64 s | 0.0003% | 78.2895 | 78.2895 | 3 ms | 0.084% |
| py09 | Known answer: too few bluffs for a pot-sized bet, the bluff catcher always folds | 6, 13 | 3 | 128 | 0.01 s | 0.0004% | 0.0004 | 0.0000 | 2 ms | 0.023% |
| py10 | Known answer: OOP holds only air, IP only the nuts | 16, 6 | 12 | 128 | 0.03 s | 0.0004% | -0.0008 | 0.0000 | 8 ms | 0.029% |
| py11 | Known answer: OOP holds only the nuts, IP only air | 6, 16 | 12 | 128 | 0.03 s | 0.0005% | 100.0007 | 100.0000 | 8 ms | 0.026% |
| py12 | Known answer: royal flush on the board, every hand splits | 105, 42 | 12 | 128 | 0.05 s | 0.0001% | 50.0001 | 50.0000 | 7 ms | 0.065% |
| py13 | Dry Q7283, capped caller OOP against a polar bettor, SPR 1, the app's sizes | 62, 60 | 8 | 1024 | 0.24 s | 0.0005% | 60.8292 |  | 33 ms | 0.029% |
| py14 | Wet Th9h6c-Jh-2d, wide against wide, SPR 2.5, the app's sizes | 245, 226 | 12 | 4096 | 3.05 s | 0.0005% | 45.0889 |  | 186 ms | 0.042% |
| py15 | Paired AA7-7-2, SPR 0.5: a small bet or all in | 100, 53 | 8 | 512 | 0.12 s | 0.0002% | 22.1939 |  | 13 ms | 0.056% |
| py16 | Four to a straight 9876-K, SPR 5, three bet sizes and two raises | 69, 72 | 30 | 2048 | 1.51 s | 0.0005% | 18.1528 |  | 251 ms | 0.053% |
| py17 | The app's ranges: button opens, big blind (the app) calls; bet 66%, bet 75%, both called | 258, 528 | 14 | 4096 | 4.35 s | 0.0004% | 41.0277 |  | 289 ms | 0.048% |
| py18 | The app's ranges: the app opens the button, big blind calls; the app bets 50% and 66%, both called | 320, 480 | 14 | 4096 | 4.86 s | 0.0005% | 24.7260 |  | 290 ms | 0.065% |
| py19 | The app's ranges: small blind re-raises the app's button open to 10, called; bet 33%, turn checked | 186, 168 | 12 | 2048 | 1.14 s | 0.0006% | 45.1658 |  | 121 ms | 0.033% |
| py20 | The app's ranges: cutoff opens, the app calls on the button; flop checked, cutoff bets the pot on the turn | 429, 201 | 16 | 4096 | 4.13 s | 0.0006% | 66.8974 |  | 242 ms | 0.079% |
<!-- reference-table:end -->

"At 300 ms" is the same spot solved the way the app solves it: 300 ms at most, stopping
early at 0.1% of the pot.

### Known answers (py01 to py12)

py01 to py08 are the half-street game of The Mathematics of Poker. Board Kh 8d 5c 3s 2h.
One player holds the nuts (KK, 3 combos) or air (JT, 16 combos) and may bet one size, s
times the pot, or check. The other holds a bluff catcher (QQ, 6 combos) and may only
check, then call or fold. No two of these hands share a card rank, so card removal can't
move the numbers. At equilibrium:

- every nut hand bets;
- bluffs are s/(1+2s) of the bets;
- the bluff catcher calls 1/(1+s) of the time;
- the bettor wins (3/19) x 100 x (1 + s/(1+s)) a hand, and the caller the rest of the 100.

| Spot | Bet, pots | Bettor | Bluff share | Call share | Value for OOP |
| --- | ---: | --- | ---: | ---: | ---: |
| py05 | 0.25 | IP | 1/6 | 4/5 | 100 - 360/19 = 81.0526 |
| py01 | 0.5 | IP | 1/4 | 2/3 | 100 - 400/19 = 78.9474 |
| py08 | 0.6 (all in) | IP | 3/11 | 5/8 | 100 - 412.5/19 = 78.2895 |
| py02 | 0.75 | IP | 3/10 | 4/7 | 100 - 3000/133 = 77.4436 |
| py03 | 1 | IP | 1/3 | 1/2 | 100 - 450/19 = 76.3158 |
| py07 | 1 | OOP | 1/3 | 1/2 | 450/19 = 23.6842 |
| py06 | 1.5 | IP | 3/8 | 2/5 | 100 - 480/19 = 74.7368 |
| py04 | 2 | IP | 2/5 | 1/3 | 100 - 500/19 = 73.6842 |

The other four:

- **py09, too few bluffs.** The bettor has 9 nut combos (KK, 88, 55) and 4 of air (JTs).
  A pot-sized bet needs 4.5 air combos to make the caller indifferent. Betting everything,
  bluffs are 4 of 13 bets, under a third, so calling loses 7.7 a hand. The caller always
  folds and the bettor takes the pot every hand: value 0 for OOP.
- **py10, py11, only the nuts against only air.** Air never bets and never calls. The nuts
  take the pot: value 0 for OOP in py10, 100 in py11.
- **py12, a royal flush on the board.** Every hand splits: value 50, and nobody folds to a
  bet.

`tools/reference_spots/defs.py` has the sums, and `KNOWN` there holds the answers as exact
fractions.

### Realistic (py13 to py20)

- py13 to py16 are written as range text, like the answer keys: a dry board at SPR 1, a wet
  one with wide ranges at SPR 2.5, a paired one at SPR 0.5, and four to a straight at SPR 5
  with three bet sizes and two raises.
- py17 to py20 use the ranges `app/solver/ranges.py` builds from a betting line, with the
  sizes the advice offers (half pot, pot, all in, one raise). They have no `range_text`,
  only the weights. **These four files are frozen:** the range model may change later, a
  reference spot must not. `make-spots --lines` builds them again from today's model, which
  changes their hash and needs a new solve.

## How they were solved

`python -m tools.reference_spots solve`:

- `solve_river` with no clock, stopping when the answer is within 0.001% of the pot of an
  equilibrium (checked at iterations 8, 16, 32 and so on), or at 65,536 iterations.
- The answer is written with probabilities rounded to 6 places, then measured again as
  written with an exact best response (`checks`). It is saved only if that is at or under
  0.005% of the pot and the spot's expected checks pass.
- No clock means the same answer on every run on one machine. Another machine may differ
  in the last decimals (floating point), which the tolerances of the checks cover.

All 20 take about 30 seconds to solve on a 4-core cloud machine.

## Checking another solver against them

```bash
python -m tools.reference_spots check <folder of RESULT files named py01.jsonl, ...>
```

```bash
python -m tools.reference_spots rust
```

The second one runs `engine/target/release/subgame-solve` on every spot first (build it
with `cargo build --release -p subgame` in `engine/`).

A spot can have many equilibria, so strategies are not compared hand by hand. Every
equilibrium has the same value, so for each spot:

1. the other answer must be near an equilibrium by **our** exact best response, whatever
   the solver says of itself (default limit 0.5% of the pot, `--max-exploitability`);
2. its value must be near the reference value (default 0.5% of the pot, `--value`);
3. its bounds on the true value must meet the reference's. If they don't, one of the two is
   wrong or the two solvers are solving different games;
4. it must pass the spot's expected checks, and have the known value where there is one.

The known bluff and call shares are a fifth check, only with `--shares <tolerance>`: shares
move far more than the value. An answer 0.3% of the pot from an equilibrium can have a call
share 7 points off, so ask for them only of a tight solve:

```bash
python -m tools.reference_spots rust --target 0.01 --max-exploitability 0.02 --value 0.05 --shares 0.005
```

Result for the Rust solver, 26 Nov 2026: no problems on any of the 20, at its default
target (0.3%) and at the tight one. Numbers: `docs/research/RIVER_SOLVER.md`.

The Phase 4 harness (`docs/research/PHASE4.md`) reads this folder as well, which covers the
closed-form results that page lists under "Not covered". It adds timing and action
frequencies, and doesn't check the known shares:

```bash
python -m tools.answer_keys --spots-dir data/reference_spots/python_solver/spots run --solver engine/target/release/subgame-solve --target 0.3 --out /tmp/reference_run
```

```bash
python -m tools.answer_keys --spots-dir data/reference_spots/python_solver/spots compare /tmp/reference_run --against data/reference_spots/python_solver/results
```

On 26 Nov 2026 that passed every gate on the 20 spots, with the same numbers as `rust`.

## Making them again

```bash
python -m tools.reference_spots make-spots
```

```bash
python -m tools.reference_spots solve
```

```bash
python -m tools.reference_spots validate
```

- `make-spots` writes py01 to py16 from `defs.py`. Edit there, not the JSON.
- `solve` only solves spots that are new or changed (`--force` for all), then refreshes
  `index.json` and the table above.
- `validate` checks every file here: the spots, the results, and the known answers. The
  tests run the same checks.
