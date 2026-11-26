"""River solver (Phase 2 of docs/research/README.md).

    from app.solver import RiverSpot, solve_river
    strategy = solve_river(spot, time_budget_ms=300)

- spot.py: RiverSpot and BetSizes (the input)
- tree.py: the river betting tree of a spot
- ranking.py: fast hand values for every combo on a river board, showdown tables
- strategy.py: RiverStrategy (the output: action probabilities per node and combo)
- solve.py: solve_river (not written yet: raises NotImplementedError)
- exploitability.py: what a perfect counter-strategy wins (0 at an equilibrium)
- timing.py: p50 / p95 decision time against the 400 ms target
- labels.py: the saved format for solver-labelled river decisions
- bridge.py: from the advice's view of the table to a spot, and back to one action

See docs/research/SOLVER.md.
"""
from .exploitability import Exploitability, best_response, exploitability, strategy_values
from .solve import DECISION_BUDGET_MS, solve_river
from .spot import IP, OOP, BetSizes, RiverSpot
from .strategy import RiverStrategy
from .tree import GameTree, build_tree

__all__ = ["BetSizes", "DECISION_BUDGET_MS", "Exploitability", "GameTree", "IP", "OOP", "RiverSpot",
           "RiverStrategy", "best_response", "build_tree", "exploitability", "solve_river", "strategy_values"]
