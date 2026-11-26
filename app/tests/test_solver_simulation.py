"""Simulated comparisons with the river solver on repeat exactly, replays and split runs
included. tools/simulate.py turns on TUNING["river_solver_fixed_work"] while it asks for
advice: the solver then runs a fixed amount of work for the spot in place of its clock, so
its answers can't depend on how fast or busy the machine is (test_solver_advice.py and
test_solver_budget.py check the setting itself). In the app the clock still decides."""
import os
import sys

import pytest

from app import solver
from app.poker import advice

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")
ON = {"river_solver": True}


@pytest.fixture(scope="module")
def tools():
    sys.path.insert(0, TOOLS)
    try:
        import compare
        import simulate
    finally:
        sys.path.remove(TOOLS)
    return simulate, compare


@pytest.fixture
def calls(monkeypatch):
    """Every call the advice makes to the solver: (time budget, iterations)."""
    seen = []
    real = solver.solve_river

    def spy(spot, *args, **kw):
        seen.append((kw.get("time_budget_ms", args[0] if args else None), kw.get("max_iterations")))
        return real(spot, *args, **kw)

    monkeypatch.setattr(solver, "solve_river", spy)
    return seen


def _run(compare, jobs=1):
    """36 hands in which the solver changes some decisions, replayed 3 times from the split."""
    _, _, diffs, replayed, extra = compare.run_paired({}, ON, 36, "maniacs", 2, method="duplicate", resample=3,
                                                       jobs=jobs)
    return diffs, replayed, extra["adjusted"], extra["resampled"]


def test_simulations_with_the_solver_repeat_exactly(tools, calls, monkeypatch):
    _, compare = tools
    first = _run(compare)
    assert first[1] > 0  # the solver changed at least one decision
    assert calls and all(budget is None and iterations for budget, iterations in calls)  # fixed work, no clock
    assert advice.TUNING["river_solver_fixed_work"] is False  # on only while the simulator asks for advice
    assert _run(compare) == first
    # a budget no machine could meet changes nothing in a simulation (in the app the rules
    # would take over every time)
    monkeypatch.setattr(solver, "DECISION_BUDGET_MS", 1)
    assert _run(compare) == first
    assert _run(compare, jobs=2) == first
