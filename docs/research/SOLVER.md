# River solver (Phase 2)

Phase 2 gate (README.md): matches closed-form results; beats B0 by 2.5 SE; p95 decision
time under 400 ms.

Status, 26 Nov 2026:

- **Matches closed-form results: done.** The river solver reproduces the half-street game
  of The Mathematics of Poker, and the push-or-fold solver matches the published
  heads-up equilibrium.
- **p95 under 400 ms: done.** 313 ms for the whole decision, with no benchmark spot more
  than 1% of the pot from an equilibrium.
- **Beats B0 by 2.5 SE: not started.** It waits for Phase 1. The advice switch
  `river_solver` is off.

Numbers and tables: `experiments.md`, "Phase 2: river solver and push-or-fold".

## The package, `app/solver/`

| File | What |
| --- | --- |
| `spot.py` | `RiverSpot`: board, pot at the start of the river, stacks (oop, ip), bet sizes per player (`BetSizes`), each range as weighted combos. Cleans the ranges (see below). |
| `tree.py` | `GameTree`: the river betting tree of a spot. |
| `ranking.py` | Hand values for every combo on a river board (table lookups after one setup per board), and `matchups`, the showdown table between two ranges. |
| `strategy.py` | `RiverStrategy`: for every decision node, one row of action probabilities per combo of the player to act. |
| `solve.py` | `solve_river(spot, time_budget_ms) -> RiverStrategy`, the entry point. `DECISION_BUDGET_MS = 300`. |
| `cfr.py` | The method: Discounted CFR (default) and CFR+, vectorised over combos. |
| `pushfold.py` | `solve_push_fold(stack_bb)`: heads-up jam-or-fold for all 169 starting hands. |
| `data/preflop_equity.npz` | Exact all-in equity of every starting hand against every other, with card removal (210 KB). Rebuilt by `tools/build_preflop_equity.py` in about 2 minutes. |
| `exploitability.py` | Exact best responses, the value of a strategy, and `exploitability`. |
| `timing.py` | `time_decisions`, nearest-rank p50 and p95, and `benchmark_spots`. |
| `labels.py` | The saved format for solver-labelled decisions (JSON Lines). |
| `bridge.py` | From the advice's view of the table to a spot and a node, and back to one action. |

Scripts:

```
.venv/bin/python tools/solver_timing.py --ranges all         # p50 / p95 against 400 ms, and answer quality
.venv/bin/python tools/label_river.py --synthetic 100 --out river_labels.jsonl
.venv/bin/python tools/build_preflop_equity.py --verify      # rebuild the equity table
.venv/bin/python docs/research/runs/phase2_solver.py         # every table in experiments.md
```

## Conventions

- Player 0 is out of position (acts first on the river), player 1 is in position.
- Node keys are the actions so far: `""` (start), `"x"` (check), `"b50"` (bet 50), `"r150"`
  (raise to 150), `"c"`, `"f"`, separated by spaces: `"x b50 r150 c"`. Amounts are what that
  player has put in on the river so far, in the spot's chips.
- Bet sizes are shares of the pot. Raise sizes are shares of the pot after calling. A raise
  is at least the bet it answers. Sizes at or over the effective stack become all in, and
  equal amounts are offered once. `max_raises` counts raises after the first bet.
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

## Next

1. After Phase 1: compare `river_solver` on against B0 (rule 1). Nothing else may turn it
   on.
2. Better ranges for the bridge (Phase 3). The solver's answer is only as good as the
   ranges it is given, and both are the "medium" preset today.
3. Facing a raise, and bet sizes chosen by stack-to-pot ratio (KNOWLEDGE.md, Acevedo).
4. Try `solve_push_fold` in place of the `push_chart` table, as its own experiment.
5. If wider ranges or bigger trees are needed: a showdown pass that sorts by hand value in
   place of the full table would cut the cost per iteration.

## In the advice

`TUNING["river_solver"]` (off). When it's on, `_river_solver` in `app/poker/advice.py`
builds the spot through `bridge.river_decision`:

- The spot starts at the beginning of the river.
- The opponent's real bet is added to their bet sizes, so the hero's decision is a node of
  the tree, and their bet isn't rounded to the nearest size.
- Ranges are a placeholder until Phase 3: the "medium" preset for both players, plus the
  hero's own hand.
- The most likely action becomes the instruction, and the mix goes in the small print.

The rules decide instead in any of these cases:

- the solver raises an error, or takes longer than its budget;
- the hand isn't heads-up;
- the hero faces a raise;
- a number it needs is unknown, or the stacks weren't read reliably.

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
