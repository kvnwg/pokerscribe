# River solver (Phase 2)

Phase 2 gate (README.md): matches closed-form results; beats B0 by 2.5 SE; p95 decision
time under 400 ms.

Status, 26 Nov 2026:

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
- **Beats B0 by 2.5 SE: not started.** It waits for Phase 1. The advice switch
  `river_solver` is off.

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

Outside the package: `app/poker/history.py` keeps the betting of the hand being played
(`BettingRecord`, `Line`). `app/poker/profiles.py` feeds it every read and puts the line on
the river state.

Scripts:

```
.venv/bin/python tools/solver_timing.py --ranges all         # p50 / p95 against 400 ms, and answer quality
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

1. After Phase 1: compare `river_solver` on against B0 (rule 1). Nothing else may turn it
   on. Run it with `--profiles`: without them the simulator keeps no record of the betting
   and the ranges are only guessed from the pot.
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

Turning it on by default needs the B0 bar like any option (README.md, rule 1).

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
