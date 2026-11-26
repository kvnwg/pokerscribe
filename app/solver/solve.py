"""The river solver's entry point.

solve_river(spot, time_budget_ms) returns a RiverStrategy: for every decision in the
spot's betting tree, a probability for each action for every combo of the player to act.

The method is Discounted CFR (app/solver/cfr.py); "cfr+" is kept for comparison (it needs
about three times the iterations for the same exploitability, see experiments.md). The
strategy comes back with its iterations, its time and its exploitability as a share of
the pot, worked out exactly on the returned strategy.

decision_settings(spot, big_blind) is how the advice asks for a solve:

- When to stop early follows the size of the pot (target_for): the same accuracy in chips
  for every pot. A share of the pot treats 0.1% of 2 big blinds like 0.1% of 100, so the
  small pots, which are most of them, took all the time while the big ones stopped after
  a tenth of it.
- With repeatable=True (the simulator) the clock is replaced by a fixed amount of work
  (reference_iterations), so the same spot gives the same answer on every run.
"""
from __future__ import annotations

from typing import Optional

from . import cfr
from .spot import RiverSpot
from .strategy import RiverStrategy
from .tree import GameTree

# The time the advice gives the solver on a river decision. The 400 ms target covers the
# whole decision, so this leaves room for building the spot and reading the answer.
DECISION_BUDGET_MS = 300
# Stop early once a perfect counter-strategy could win no more than this share of the pot.
TARGET_EXPLOITABILITY = 0.001
DEFAULT_METHOD = "dcfr"

# The advice's stop target: a perfect counter-strategy could win no more than this many
# big blinds. At 10 big blinds in the pot that is the 0.1% above; smaller pots stop sooner,
# bigger ones go on longer.
TARGET_BB = 0.01
# ... as a share of the pot never tighter than the first (past it more accuracy is lost in
# the ranges anyway) nor looser than the second (half the bar an answer must pass to be used).
TARGET_SHARES = (0.0001, 0.005)

# What one iteration costs on the machine the timings in experiments.md were made on, in
# ms: a fixed part, plus a part for every (combo of either player) x (end of the hand in
# the tree). Fitted on 272 river spots from simulated hands: within 11% for half of them,
# 24% for nine in ten. Only used to turn a time budget into a number of iterations.
REFERENCE_MS = (0.064, 7.0e-5)
MIN_ITERATIONS = 16


def solve_river(spot: RiverSpot, time_budget_ms: Optional[float] = DECISION_BUDGET_MS, *,
                max_iterations: Optional[int] = None, method: str = DEFAULT_METHOD,
                target_exploitability: float = TARGET_EXPLOITABILITY) -> RiverStrategy:
    """An approximate equilibrium strategy for the river spot.

    It stops at whichever comes first: the time budget (None = no limit), max_iterations
    (for runs that must repeat exactly), or exploitability at or under
    target_exploitability (0 = never stop early). At least one iteration always runs, so a
    budget too small for even that is overrun: check elapsed_ms if it matters."""
    return cfr.solve(spot, time_budget_ms, max_iterations, method, target_exploitability)


def target_for(pot_bb: Optional[float]) -> float:
    """The exploitability, as a share of the pot, at which a solve for the advice may stop
    early, for a pot of this many big blinds (None: not known, the usual 0.1%)."""
    if not pot_bb or pot_bb <= 0:
        return TARGET_EXPLOITABILITY
    tightest, loosest = TARGET_SHARES
    return min(loosest, max(tightest, TARGET_BB / pot_bb))


def reference_iterations(spot: RiverSpot, budget_ms: float = DECISION_BUDGET_MS) -> int:
    """How many iterations the budget buys on the reference machine. It depends on the
    spot alone (the sizes of the ranges and of the tree), never on the clock."""
    fixed, per_unit = REFERENCE_MS
    ends = sum(1 for _ in GameTree(spot).terminals())
    work = (len(spot.combos(0)) + len(spot.combos(1))) * ends
    return max(MIN_ITERATIONS, int(budget_ms / (fixed + per_unit * work)))


def decision_settings(spot: RiverSpot, big_blind: Optional[float] = None, repeatable: bool = False) -> dict:
    """How the advice solves this spot: solve_river(spot, **decision_settings(...)).

    The stop target follows the pot in big blinds. Usually the clock ends the solve
    (DECISION_BUDGET_MS). With repeatable=True there is no clock: the solve runs the
    iterations the budget buys on the reference machine, so the answer is the same on
    every run, however busy the machine is."""
    target = target_for(spot.pot / big_blind if big_blind else None)
    if repeatable:
        return {"time_budget_ms": None, "max_iterations": reference_iterations(spot),
                "target_exploitability": target}
    return {"time_budget_ms": DECISION_BUDGET_MS, "max_iterations": None, "target_exploitability": target}
