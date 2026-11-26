# River solver (Phase 2)

**The roadmap was replaced on 26 Nov 2026 (README.md), the day most of this was built.**
Phase 2's gate is now "Reference for Phase 4": this Python solver is what the Rust solver
must match. The gate it was built for (old roadmap): matches closed-form results; beats B0
by 2.5 SE; p95 decision time under 400 ms. The comparison against B0 was never run and the
new roadmap doesn't ask for it (tuning the rule engine is shelved). The switch stays off.

Status against the old gate, 26 Nov 2026:

- **Matches closed-form results: done.** The river solver reproduces the half-street game
  of The Mathematics of Poker, and the push-or-fold solver matches the published
  heads-up equilibrium.
- **p95 under 400 ms: done.** About 300 ms for the whole decision with the ranges below
  (the solver uses its whole 300 ms on most decisions), and 396 of 400 held-out decisions
  answered within 1% of the pot of an equilibrium.
- **Ranges from the betting so far: done, a first version.** The solver no longer gets the
  same top 25% of hands for everyone: both ranges are worked out from who bet how much on
  each round, the seats, and what the app has learned about the opponent. On held-out
  simulated hands the opponent's real cards are in the range 89% and 98% of the time
  (mixed and fish247 tables), against 59% and 81% for the old placeholder.
- **Facing a raise: done.** A raise of the hero's bet is solved too (fold, call or all in).
  Checked on made-up raises only: the simulator's bots next to never raise the river.
- **Repeats exactly in the simulator: done.** There the clock is replaced by a fixed amount
  of work, so a comparison with the solver on gives the same result every run.
- **Time that follows the pot: done.** The solver stops at the same accuracy in chips for
  every pot, inside the same 300 ms. Small pots answer sooner, big ones are solved closer.
- **Beats B0 by 2.5 SE: never run**, and no longer planned (see the top). The advice
  switch `river_solver` is off.

Numbers and tables: `experiments.md`, "Phase 2: river solver and push-or-fold", "Phase 2:
river ranges from the betting, and facing a raise" and "Phase 2: the same answer every run,
and time by pot size".

## The package, `app/solver/`

| File | What |
| --- | --- |
| `spot.py` | `RiverSpot`: board, pot at the start of the river, stacks (oop, ip), bet sizes per player (`BetSizes`), each range as weighted combos. Cleans the ranges (see below). |
| `tree.py` | `GameTree`: the river betting tree of a spot. |
| `ranking.py` | Hand values for every combo on a river board (table lookups after one setup per board), and `matchups`, the showdown table between two ranges. |
| `strategy.py` | `RiverStrategy`: for every decision node, one row of action probabilities per combo of the player to act. |
| `solve.py` | `solve_river(spot, time_budget_ms) -> RiverStrategy`, the entry point. `DECISION_BUDGET_MS = 300`. `decision_settings`: how the advice calls it (below). |
| `cfr.py` | The method: Discounted CFR (default) and CFR+, vectorised over combos. |
| `pushfold.py` | `solve_push_fold(stack_bb)`: heads-up jam-or-fold for all 169 starting hands. |
| `data/preflop_equity.npz` | Exact all-in equity of every starting hand against every other, with card removal (210 KB). Rebuilt by `tools/build_preflop_equity.py` in about 2 minutes. |
| `exploitability.py` | Exact best responses, the value of a strategy, and `exploitability`. |
| `timing.py` | `time_decisions`, nearest-rank p50 and p95, and `benchmark_spots`. |
| `labels.py` | The saved format for solver-labelled decisions (JSON Lines). |
| `ranges.py` | `river_ranges`: both players' ranges at the start of the river, from the betting so far. |
| `bridge.py` | From the advice's view of the table to a spot and a node, and back to one action. |
| `rust_backend.py` | The Rust solver as a second way to solve a spot: writes the spot to a file, runs the program `subgame-solve`, reads its answer back as a `RiverStrategy`. The Python solver answers when the program is missing or fails. See "The Rust backend" below. |

Outside the package: `app/poker/history.py` keeps the betting of the hand being played
(`BettingRecord`, `Line`). `app/poker/profiles.py` feeds it every read and puts the line on
the river state.

Scripts:

```
.venv/bin/python tools/solver_timing.py --ranges all         # p50 / p95 against 400 ms, and answer quality
.venv/bin/python tools/rust_solver_overhead.py               # what calling the Rust program costs per decision
.venv/bin/python docs/research/runs/rust_solver_real.py      # the advice's river spots through the real Rust program
.venv/bin/python tools/label_river.py --synthetic 100 --out river_labels.jsonl
.venv/bin/python tools/build_preflop_equity.py --verify      # rebuild the equity table
.venv/bin/python docs/research/runs/phase2_solver.py         # every table in experiments.md
.venv/bin/python docs/research/runs/phase2_ranges.py         # how well the ranges predict real cards
.venv/bin/python docs/research/runs/phase2_budget.py         # time by pot size, and whether runs repeat
```

## Conventions

- Player 0 is out of position (acts first on the river), player 1 is in position.
- Node keys are the actions so far: `""` (start), `"x"` (check), `"b50"` (bet 50), `"r150"`
  (raise to 150), `"c"`, `"f"`, separated by spaces: `"x b50 r150 c"`. Amounts are what that
  player has put in on the river so far, in the spot's chips.
- Bet sizes are shares of the pot. Raise sizes are shares of the pot after calling. A raise
  is at least the bet it answers. Sizes at or over the effective stack become all in, and
  equal amounts are offered once. `max_raises` counts raises after the first bet.
  `BetSizes.reraises` gives a raise of a raise its own sizes (`()` with all in: a raise
  can only be answered by going all in). `BetSizes.allin_within` adds all in as a choice
  of its own only where it is a bet of at most that many pots (for a raise: pots after
  calling). `BetSizes.exact` names the lists of sizes that get no all in beside them.
- Ranges:
  - combos that use a board card are removed;
  - combos that use the same card twice are removed;
  - a duplicate combo keeps its first weight;
  - combos with weight 0 are dropped.

  Clashes between the two players' ranges stay in both ranges. Those deals get no weight
  when the ranges meet, which is exact card removal.
- Payoffs:
  - the winner takes the pot plus what the loser put in on the river;
  - the loser loses what they put in;
  - a split gives each half the pot.

  Both players' payoffs add up to the pot, so exploitability = (best response as OOP + best
  response as IP - pot) / 2. That is 0 exactly at an equilibrium. It is reported in chips
  and as a share of the pot.

## How the river solver works

- **Method.** Discounted CFR (Brown and Sandholm 2019; alpha 1.5, beta 0, gamma 2), with
  the players updated in turn. The average strategy is the answer. CFR+ is kept as
  `method="cfr+"` for comparison: it needs about three times the iterations.
- **One iteration.** For each player in turn:
  1. Walk down the tree, carrying the opponent's reach.
  2. Value every end of the hand at once. The reaches of all terminal nodes are the rows
     of one matrix, multiplied by the showdown tables in two matrix products.
  3. Walk back up, updating regrets.

  An iteration takes about 0.6 ms on narrow ranges and 2 ms on wide ones.
- **When it stops.** At whichever comes first:
  - the time budget;
  - `max_iterations`, for runs that must repeat exactly;
  - exploitability at or under `target_exploitability`, 0.1% of the pot by default,
    checked at iterations 8, 16, 32 and so on.

  At least one iteration always runs.
- **How the advice calls it** (`decision_settings`):
  - The early stop follows the pot (`target_for`): a hundredth of a big blind, which is
    0.1% of a pot of 10 big blinds, 0.4% of 2.5 and 0.02% of 50. Never looser than 0.5% of
    the pot, never tighter than 0.01%. A share of the pot alone had the pots of 2 to 3 big
    blinds use the whole 300 ms while pots over 50 were done in about 40 ms.
  - In the simulator (`TUNING["river_solver_fixed_work"]`, which `tools/simulate.py` turns
    on) there is no clock. The solve runs the iterations 300 ms buys on the reference
    machine (`reference_iterations`): a number worked out from the sizes of the ranges and
    of the tree, so the same spot gets the same answer on every run. The early stop is the
    same as by the clock.
- **What comes back.** A `RiverStrategy` with `iterations`, `elapsed_ms` and
  `exploitability`. The exploitability is a share of the pot, worked out exactly on the
  returned strategy with the same maths as `exploitability.py`.

## How it was checked

- `test_solver_answer_keys.py`: the book's half-street game at bet sizes 0.5, 0.75, 1 and
  2. Bluff share, call share and game value all match, within the tolerances written
  before the solver existed.
- `test_solver_cfr.py`:
  - exploitability falls at 10, 100 and 1000 iterations on three spots, for both methods;
  - runs repeat exactly;
  - the answer doesn't depend on the chip unit;
  - the nuts never fold;
  - the solver's own exploitability equals the checker's.
- `test_solver_pushfold.py`:
  - the equity table against full enumeration and against sampling;
  - the solution against the published chart at 5, 8, 10, 12 and 15 big blinds.
- `tools/solver_timing.py`: time and answer quality on 600 benchmark spots.
- `test_solver_rust_backend.py`: the Rust backend, against a stand-in for the program
  (see "The Rust backend").

## Push-or-fold

`solve_push_fold(stack_bb)` gives, for each of the 169 starting hands, how often the small
blind jams and how often the big blind calls. It also gives the small blind's result per
hand and the exploitability in big blinds.

- Stacks are in big blinds before the blinds are posted. Blinds are 0.5 and 1, no ante.
- It solves in about 20 ms.
- It isn't used by the advice. The `push_chart` option still reads its hand-typed table.

## Ranges from the betting so far (`ranges.py`)

The solver's answer is only as good as the ranges it is given.

**What is recorded.** `BettingRecord` (in `app/poker/history.py`) sees every read while
watching and keeps, per betting round, the pot the round began with and each different set
of bets. On the river, with one opponent left, it gives a `Line`:

- before the flop: how many big blinds each put in, and who made the last raise;
- flop and turn: the last bet as a share of the pot (0 = checked through), and who made it:
  you, your opponent, or a player who folded later;
- the river's own bets and raises so far, in order.

A round that wasn't read stays unknown. Its size is then guessed from the size of the pot
(`fill_in`): the likeliest kind of pot before the flop and number of bets after it that
explain it. Who bet in a guessed round stays unknown.

**How a range is built** (`river_ranges`), one round at a time, as weights for all 1326
combos:

1. Before the flop, each player's part decides the hands: opened, called a raise, limped,
   re-raised, called a re-raise. The hero's hands are the preflop charts' for that part.
   An opponent's are the best so-many percent of hands for that part, joined with the
   chart's, where "so many" comes from how many hands they play and raise: what the app
   has counted for that player (`profiles.rates`), or the typical numbers of their style.
2. On the flop and the turn, every hand is scored on the board as it was then (the made
   hand, with draws counted like the pairs they play like), and placed within the player's
   own range so far. Then:
   - a bet keeps the top of the range (less of it for a bigger bet), draws, and some of
     the weakest hands as bluffs. The flop bet of the player who raised before the flop
     comes from many more hands;
   - a call keeps what is above the folding line, with fewer of the very best hands;
   - a check keeps everything but thins out the hands that would have bet, much more for
     the player who could have bet last.
   The opponent's style shifts these the way `exploits.py` already does for the rules.
3. Hands with under 3% of the top weight are dropped, and a range keeps at most 700 combos.

The hero's own combo is always in the hero's range.

**How good it is.** `docs/research/runs/phase2_ranges.py` deals simulated hands and looks
up the cards the bots really hold in each guess. Numbers in `experiments.md`. The settings
are standard poker reasoning and were not fitted to the bots. One thing to know: against
these bots the betting record alone does little for the opponent's range. What the app has
counted about that player (hands played and raised) is what makes it good, so the ranges
are weaker in a session's first hands.

**Not done:** rates per seat, sizing tells, what a check-raise says beyond its size, and
ranges for hands with three or more players on the river.

## Next

Under the new roadmap the next solver work is the Rust one (Phases 3 and 4), with this
package as its reference. What was next here under the old one, kept in case it is wanted:

1. Compare `river_solver` on against B0 (rule 1). Nothing else may turn it on. Run it
   with `--profiles`: without them the simulator keeps no record of the betting and the
   ranges are only guessed from the pot.
2. Bet sizes chosen by stack-to-pot ratio (KNOWLEDGE.md, Acevedo). Only the all in follows
   it so far. Big pots finish with time to spare, so more sizes there are the next use of
   it.
3. Try `solve_push_fold` in place of the `push_chart` table, as its own experiment.
4. A showdown pass that sorts by hand value in place of the full table would cut the cost
   per iteration, if bigger ranges or trees are needed.
5. Check the early stop more often than at iterations 8, 16, 32 and so on. A small pot
   that is good enough at iteration 70 now runs to 128.
6. A longer limit than 300 ms for the biggest pots would need the 400 ms rule to change:
   pots over 50 big blinds are about 1 river decision in 12.

## In the advice

`TUNING["river_solver"]` (off). When it's on, `_river_solver` in `app/poker/advice.py`
builds the spot through `bridge.river_decision`:

- The spot starts at the beginning of the river.
- Ranges come from the betting so far (above).
- The bets and raises already made are in the tree at their real sizes, and they are the
  only sizes offered where they were made. The question is what to do now that this bet
  happened. Offering other sizes there lets the solution put every betting hand on a size
  nobody chose, and then it has nothing to say about the real one.
- Facing a raise, the hero may fold, call or go all in.
- All in is a choice of its own only up to six pots (`bridge.DEFAULT_SIZES`). In a limped
  pot of 2 big blinds with 100 behind, all in is a bet of 40 pots: next to never right, and
  with it on offer the solver doesn't get near an equilibrium in its 300 ms. A bet or raise
  that was really made is in the tree whatever its size.
- The most likely action in the solver's mix becomes the instruction. The small print
  gives the mix and what the hands were judged from.

The rules decide instead in any of these cases:

- the solver raises an error, or takes longer than its budget (by the clock; with fixed
  work in the simulator nothing is ever late);
- its answer is more than 1% of the pot from an equilibrium (a slow machine);
- next to none of the opponent's range makes this bet in the solution (under 0.2%), so the
  solution has no answer to it;
- the hand isn't heads-up;
- a number it needs is unknown, or the stacks weren't read reliably.

One more safeguard: when the hero's own hand all but never reaches this spot in the
solution (it was played differently earlier than the solver would have), the solver's mix
for it was never worked out. The instruction is then the best action for that hand against
the opponent's solved strategy.

Turning it on by default needs the B0 bar like any option (README.md, rule 1), and the
new roadmap doesn't plan to.

## The Rust backend (`rust_backend.py`)

The Rust river and turn solver (`engine/crates/subgame`, see its README) is a program,
`subgame-solve`. `rust_backend.solve_river` takes what `solve_river` takes (a time budget, `max_iterations`,
a target exploitability) and returns the same `RiverStrategy`, with `backend` set to
`"rust"` or `"python"`.

The advice uses it only when `TUNING["rust_solver"]` is on. It is off, and it matters
only where `river_solver` (also off) already sends a decision to the solver. So B0 does not
change. The advice asks it exactly as it asks the Python solver
(`decision_settings`): by the clock in the app, and with a fixed number of iterations and
no clock in the simulator (`river_solver_fixed_work`).

Only the program's command line and file formats are used, nothing from its crate:

```
subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.3]
              [--max-iterations N] [--time-ms N] [--threads N]
```

The spot goes in as a SPOT file and the answer comes back as a RESULT file. Both formats
are in `data/SPOT_FORMAT.md`. The program is looked for in the environment variable
`POKERSCRIBE_SUBGAME_SOLVE` (its path), and otherwise in `engine/target/release`, where
`cargo build --release` puts it.

One call:

1. The spot is written as a SPOT with the id `live`. Whole amounts are written as whole
   numbers. A range with a weight over 1 is scaled down as a whole, because a SPOT's
   weights are at most 1; that changes nothing in the answer. The bet sizes are written
   with the three keys the format has (next section).
2. The program runs with `--out`, the target exploitability, and whichever limits were
   given: `--time-ms` set to the budget less 40 ms (see "What the call costs"), and
   `--max-iterations`. With a budget it is stopped at the budget.
3. The RESULT is read and checked against the spot's own tree: the same decision nodes,
   the same actions in the same order, the same player to act, and every combo of that
   player's range with one probability per action. The file rounds probabilities to 6
   decimals, so each row is made to add up to exactly 1 again.
4. The strategy's exploitability is the program's own number
   (`solver.exploitability_pot`). When the program gives none, the Python checker works
   it out (3 to 4 ms on a spot of 500 to 650 combos), because the advice drops an answer
   that is over 1% of the pot from an equilibrium and must not take silence for "exact".

The Python solver answers instead, in what is left of the time budget, when:

- the program isn't built (this is normal and logs nothing above INFO);
- the spot's bet sizes can't be written in a SPOT (next section; also normal, logged at
  DEBUG, and the program isn't started, so the whole budget is left);
- it can't be started, exits with an error, writes no result, or is still running at the
  budget;
- its result is not a RESULT, is for another spot, or does not fit the spot's tree in any
  of the ways above.

Each of the last two logs a warning with the reason. After a slow failure nothing is left
of the budget; the Python solver still runs one iteration, the advice sees that the
budget was passed, and the rules decide, as with any slow solver.

### Bet sizes a SPOT can't say

A SPOT's `sizes` have three keys: `bets`, `raises`, `allin`. `BetSizes` has three more
since the river solver learned to answer raises: `reraises`, `allin_within` and `exact`.
`data/SPOT_FORMAT.md` doesn't describe them, and `subgame-solve` refuses a spot that has
them (its README, "Things to know", 5). The advice uses them on every spot
(`allin_within` is 6 pots, and a bet already made is `exact`).

All the three do is decide where going all in is a choice, and which list a raise takes
its sizes from. So `rust_backend.plain_sizes` says them with the three keys the format
has: `allin` off, and in each list where all in is a choice, one more size big enough to
be all in wherever it is offered (the format: "sizes at or over the effective stack
become all in"). Every try is checked by building its tree, and only sizes that give
exactly the spot's tree are sent.

One list of raise sizes per player can't say everything:

- **Stacks of 12.5 to 19 pots, with the advice's usual sizes.** All in is within six pots
  as a raise of the pot-sized bet, but not as a raise of the half-pot bet. In simulated
  hands that was 92 of 394 heads-up river decisions (table mixed, 6,000 hands, seed 77):
  23%. Nothing else in that sample failed.
- **Facing a raise, when the usual raise size isn't all in already.** After a raise the
  only raise left is all in, while a raise of a first bet keeps its usual size. None in
  that sample (the simulator's bots almost never raise the river).

Such a spot goes straight to the Python solver. The way out is on the Rust side: once
`subgame-solve` reads the three newer options the way `app/solver/tree.py` does (and
`data/SPOT_FORMAT.md` describes them), set `EXTENDED_SIZES = True` in `rust_backend.py`.
A spot the three keys can't say then goes out with its sizes as they are
(`BetSizes.to_dict()`). An answer for another tree is refused either way.

### Checked against the real program

The backend was written against the command line and the two formats alone, with a
stand-in for the program (below). `subgame-solve` reached the repo the same day, and the
backend works with it as written. What had been taken on trust, and how it turned out
(`runs/rust_solver_real.py`, log `runs/rust_solver_real.log`: the advice's 394 river
spots from 6,000 simulated hands, by the clock):

- **`--target-exploitability` is in percent of the pot**, as assumed
  (`TARGET_PERCENT = 100`): a target of 0.001 here goes out as `0.1`. The program's
  README says so, and its answers stop where the advice's target asks.
- **`--time-ms` limits the solving**, as assumed. Writing the answer comes on top and fits
  in the 40 ms kept back: no call went over the 300 ms budget.
- **A size at or over the stack becomes all in**, as the format says. The advice's spots
  rely on it (previous section): 302 spots went out that way and every answer came back
  for exactly the spot's tree. None failed.
- **The program's own exploitability is the Python checker's**: the largest difference
  over the 302 answers is 0.00003% of the pot. So the advice's quality bar can go by the
  number in the answer.

| 394 river spots, by the clock | Python solver | `subgame-solve` |
| --- | --- | --- |
| Answered | 394 | 302 (the other 92 can't be written as a SPOT) |
| The solve call, p50 / p95 / max | 287 / 290 / 303 ms | 56 / 154 / 228 ms |
| Of that, solving | all of it | 44 / 136 / 207 ms |
| Of that, everything else | | 15 / 23 / 30 ms |
| Iterations, p50 | 179 | 218 |
| From an equilibrium, % of the pot, p50 / p95 / max | 0.10 / 0.35 / 0.74 | 0.06 / 0.40 / 0.50 |
| The whole decision through `advise()`, p50 / p95 / max | 294 / 299 / 441 ms | 79 / 297 / 311 ms |
| Decisions the solver answered | 388 | 389 |

(The Python column is over all 394 spots, the Rust column's solve lines over its 302. The
last two lines are all 394 decisions with `rust_solver` off and on.)

- The Python solver uses its whole 300 ms on most spots without reaching the target. The
  Rust program reaches it and stops, after 44 ms of solving at the median, so the median
  decision drops from 294 ms to 79 ms. The p95 doesn't move, because the 92 spots that
  can't be written still go to the Python solver.
- On 289 of the 297 spots where both solvers have an answer for the hero's hand, the
  advice would act the same. The other 8 are close mixes, for example call 58% and fold
  42% against 50% and 50% (all 8 are in the log). Two solvers stopped at different
  moments don't land on the same mix, and the advice plays the most likely action, so a
  hand near 50% can flip. Through `advise()`: the same instruction on 384 of 394.
- In the simulator, with fixed work: `river_solver` with the Rust program against
  `river_solver` with the Python solver, 1,000 hands at table mixed, seed 101: 1 hand
  differs, -0.1 ± 0.1 bb/100, and a second run gives the same line. With duplicate
  decks and replays, the comparison tool's default since: 1 of 1,002 hands, -0.9 ± 0.9
  bb/100 (`runs/rust_solver_switch_check.log`). This compares two solvers on the same
  spots. It is not a test of either against B0.

`test_the_real_program_when_it_is_built` runs the real program on a plain spot and on two
spots with the advice's sizes, and checks each answer with the Python exploitability
checker. It is skipped when the program isn't built.

### What the call costs

Running a program per decision costs time that is not solving: starting it, writing the
spot, and reading the answer back. It counts against the 400 ms decision budget.
`tools/rust_solver_overhead.py --advice-hands 6000 --advice-spots 400` measures it, 5
calls a spot, on two kinds of spots:

- the benchmark spots (40 per range size);
- the advice's own spots: every heads-up river decision of the app's seat in 6,000
  simulated hands (table mixed, seed 77), 394 in all. 92 of them can't be written as a
  SPOT (see above) and cost no call; the other 302 are measured.

It was run twice. With `--binary engine/target/release/subgame-solve` the real program is
timed, and the overhead of a call is its whole time less the solving time the program
reports. Without it the program is a stand-in that does no solving
(`tools/replay_solve.rs`): it hands back an answer solved beforehand, so the whole call is
overhead, and what is left out is the program's own reading and writing of JSON. Both
runs are in `runs/rust_solver_overhead.log`.

Overhead per call with the real program:

| Spots | Combos, both ranges | Answer file | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- |
| narrow ranges | 219 to 340 | 19 to 119 kB | 8.6 ms | 12.2 ms | 29.5 ms |
| medium ranges | 462 to 685 | 39 to 242 kB | 13.3 ms | 17.8 ms | 33.1 ms |
| wide ranges | 909 to 1,145 | 72 to 400 kB | 19.3 ms | 26.6 ms | 35.1 ms |
| **the advice's spots** | 110 to 1,401 (median 833) | 9 to 453 kB | **16.8 ms** | **26.4 ms** | 36.0 ms |

With the stand-in (start-up, files and Python's side only):

| Spots | p50 | p95 | max | Writing the spot | The program | Reading the answer |
| --- | --- | --- | --- | --- | --- | --- |
| narrow ranges | 5.7 ms | 7.2 ms | 17.3 ms | 0.6 ms | 1.9 ms | 3.2 ms |
| medium ranges | 10.2 ms | 16.4 ms | 37.7 ms | 1.0 ms | 3.5 ms | 5.3 ms |
| wide ranges | 13.4 ms | 20.7 ms | 35.9 ms | 1.3 ms | 3.7 ms | 7.8 ms |
| the advice's spots | 11.7 ms | 19.7 ms | 28.4 ms | 1.8 ms | 2.7 ms | 6.8 ms |

(The last three columns are where the median call goes.)

- On the advice's spots the call costs about 17 ms that is not solving, 26 ms at p95:
  6.6% of the 400 ms budget. The stand-in's line says about 12 ms of that is there with
  any program. The rest is mostly the real program reading the spot and writing its
  answer.
- Starting a native program and waiting for it takes 1.5 ms (p95 2.0 ms). The largest
  part is Python reading the answer: parsing the JSON, then building the arrays (7 to
  9 ms at the median on the advice's spots).
- `rust_backend` keeps 40 ms back from the solver's 300 ms (`OVERHEAD_RESERVE_MS`), so the
  program is given 260 ms. The largest overhead measured in any run is 37.7 ms, so the
  reserve is not generous. A call that costs more than the reserve loses nothing but
  that decision: the advice sees the budget passed and the rules decide.
- The reserve costs little: the program rarely needs its whole 260 ms (p95 of its solving
  time on the advice's spots: 136 ms).
- Not measured: a Mac. All of this ran in a Linux cloud container (Intel Xeon at
  2.10 GHz, 4 cores).

### Tests

`app/tests/test_solver_rust_backend.py` (59 tests; 58 and one skipped when
`subgame-solve` isn't built), with `app/tests/fake_subgame_solve.py` as the program in all
but the last: a stand-in in Python that follows the command line and both file formats,
answers with the Python solver, and can be told to misbehave.

- A spot goes out as a valid SPOT and reads back as the same spot.
- The advice's bet sizes go out with the format's three keys and give exactly the same
  tree: at ten stack depths, and for spots made by the bridge (first to act, checked to,
  facing a bet, facing a raise). The spots that can't be said are refused before the
  program is started, and the Python solver answers them with no warning.
- The answer that comes back is the solver's own strategy, to the 6 decimals of the file.
- The program is called as its command line says, and the files are removed afterwards.
- Gzipped results and keys in any order are read. A result with no exploitability gets
  the Python checker's.
- Eight ways of failing (a crash, no output, not JSON, another spot, another tree, a
  missing node, a missing combo, rows that don't add up) each fall back to the Python
  solver with a warning that says why. So do a file that is not a program and a program
  that runs past the budget.
- With the switch off, or with only `rust_solver` on, the advice never touches the
  backend. With both switches on, the advice asks the backend exactly as it asks the
  Python solver, by the clock and with fixed work, and gives the same instruction on
  every run. Without the program it gives exactly what `rust_solver` off gives.

## Saved decisions (`labels.py`)

The format is one JSON object per line. Each object holds one decision node of one solved
spot:

- the spot, with its full ranges;
- the node and who acts there;
- the solver's action probabilities for every combo that can reach the node, which is the
  label;
- optional values;
- the held combo and the observed action, for decisions from recorded hands;
- the solver's name, version, budget, time, iterations and exploitability.

`label_source` is always "solver". A recorded action is only ever stored as "observed",
never as the label (README.md, rule 3).

`tools/label_river.py --phh` is left for later: labelling decisions from the hand history
dataset needs range estimates from each hand's history (Phase 3).
