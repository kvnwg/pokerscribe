"""The river solver's entry point.

solve_river(spot, time_budget_ms) returns a RiverStrategy: for every decision in the
spot's betting tree, a probability for each action for every combo of the player to act.

Not written yet (Phase 2, next session). What it has to meet:
- the answer keys in app/tests/test_solver_answer_keys.py (the half-street river game from
  The Mathematics of Poker), which run as soon as this stops raising NotImplementedError;
- a low exploitability (app.solver.exploitability), reported in RiverStrategy.exploitability;
- return within time_budget_ms, with p95 decision time under 400 ms
  (tools/solver_timing.py).
Suggested method (KNOWLEDGE.md, papers): CFR+ or Discounted CFR over the tree in
app.solver.tree, vectorised over combos, with showdowns from app.solver.ranking.
"""
from __future__ import annotations

from .spot import RiverSpot
from .strategy import RiverStrategy

# The time the advice gives the solver on a river decision. The 400 ms target covers the
# whole decision, so this leaves room for building the spot and reading the answer.
DECISION_BUDGET_MS = 300


def solve_river(spot: RiverSpot, time_budget_ms: float = DECISION_BUDGET_MS) -> RiverStrategy:
    """An equilibrium strategy (approximate) for the river spot, within the time budget."""
    raise NotImplementedError("The river solver isn't written yet (Phase 2).")
