"""The river solver's entry point.

solve_river(spot, time_budget_ms) returns a RiverStrategy: for every decision in the
spot's betting tree, a probability for each action for every combo of the player to act.

The method is Discounted CFR (app/solver/cfr.py); "cfr+" is kept for comparison (it needs
about three times the iterations for the same exploitability, see experiments.md). The
strategy comes back with its iterations, its time and its exploitability as a share of
the pot, worked out exactly on the returned strategy.
"""
from __future__ import annotations

from typing import Optional

from . import cfr
from .spot import RiverSpot
from .strategy import RiverStrategy

# The time the advice gives the solver on a river decision. The 400 ms target covers the
# whole decision, so this leaves room for building the spot and reading the answer.
DECISION_BUDGET_MS = 300
# Stop early once a perfect counter-strategy could win no more than this share of the pot.
TARGET_EXPLOITABILITY = 0.001
DEFAULT_METHOD = "dcfr"


def solve_river(spot: RiverSpot, time_budget_ms: Optional[float] = DECISION_BUDGET_MS, *,
                max_iterations: Optional[int] = None, method: str = DEFAULT_METHOD,
                target_exploitability: float = TARGET_EXPLOITABILITY) -> RiverStrategy:
    """An approximate equilibrium strategy for the river spot.

    It stops at whichever comes first: the time budget (None = no limit), max_iterations
    (for runs that must repeat exactly), or exploitability at or under
    target_exploitability (0 = never stop early). At least one iteration always runs, so a
    budget too small for even that is overrun: check elapsed_ms if it matters."""
    return cfr.solve(spot, time_budget_ms, max_iterations, method, target_exploitability)
