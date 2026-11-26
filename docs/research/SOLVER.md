# River solver (Phase 2)

Phase 2 gate (README.md): matches closed-form results; beats B0 by 2.5 SE; p95 decision
time under 400 ms.

Status, 26 Nov 2026: the groundwork is done and tested. The solving algorithm isn't
written: `solve_river` raises `NotImplementedError`, and the advice switch
`river_solver` is off. Log of the work: `experiments.md`, "Phase 2 groundwork".

## The package, `app/solver/`

| File | What |
| --- | --- |
| `spot.py` | `RiverSpot`: board, pot at the start of the river, stacks (oop, ip), bet sizes per player (`BetSizes`), each range as weighted combos. Cleans the ranges (see below). |
| `tree.py` | `GameTree`: the river betting tree of a spot. |
| `ranking.py` | Hand values for every combo on a river board (table lookups after one setup per board), and `matchups`, the showdown table between two ranges. |
| `strategy.py` | `RiverStrategy`: for every decision node, one row of action probabilities per combo of the player to act. |
| `solve.py` | `solve_river(spot, time_budget_ms) -> RiverStrategy`. Stub. `DECISION_BUDGET_MS = 300`. |
| `exploitability.py` | Exact best responses, the value of a strategy, and `exploitability`. |
| `timing.py` | `time_decisions`, nearest-rank p50 and p95, and `benchmark_spots`. |
| `labels.py` | The saved format for solver-labelled decisions (JSON Lines). |
| `bridge.py` | From the advice's view of the table to a spot and a node, and back to one action. |

Scripts:

```
.venv/bin/python tools/solver_timing.py --spots 200          # p50 / p95 against 400 ms
.venv/bin/python tools/label_river.py --synthetic 100 --out river_labels.jsonl
```

Both exit 2 with a message until the solver exists.

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

## What the solver session has to deliver

1. `solve_river` returns a `RiverStrategy` for the spot's tree, built with the spot's own
   `GameTree`. Every decision node needs a probability row for every combo.
2. It fills in `iterations`, `elapsed_ms` and `exploitability` (as a share of the pot, from
   `exploitability.py`, or its own exact equivalent), and it stays within `time_budget_ms`.
3. `app/tests/test_solver_answer_keys.py` then runs by itself, instead of skipping. It
   checks the half-street game of The Mathematics of Poker at bet sizes 0.5, 0.75, 1 and 2:
   - bluffs are s/(1+2s) of the bets;
   - the caller calls 1/(1+s);
   - value always bets;
   - the game value matches;
   - exploitability is under 0.2% of the pot.

   Every expected number is worked out by hand in `app/tests/solver_games.py`.
4. `tools/solver_timing.py` reports p95 under 400 ms (the advice gives it 300 ms of that).
5. Suggested method: CFR+ or Discounted CFR over the tree, vectorised over combos, with
   showdowns from `ranking.py`. Sorting by hand value gives O(n log n) showdowns; the
   checker's matrix version is the reference to test them against.

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
