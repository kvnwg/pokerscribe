"""Solve a reference spot with app/solver, save it as a RESULT (data/SPOT_FORMAT.md), and
measure what docs/research/RIVER_SOLVER.md reports."""
from __future__ import annotations

import time
from typing import Dict, Mapping, Tuple

from app.solver import DECISION_BUDGET_MS, solve_river
from app.solver.labels import SOLVER_NAME, SOLVER_VERSION
from app.solver.solve import DEFAULT_METHOD, TARGET_EXPLOITABILITY
from app.solver.strategy import RiverStrategy
from tools.answer_keys import result as result_mod
from tools.answer_keys.checks import check_expected, nodes_from_river_strategy, river_checks
from tools.answer_keys.spots import decision_nodes, river_spot, spot_hash

# The reference answers: solved until a perfect counter-strategy could win no more than
# 0.001% of the pot, with no clock (so a spot gives the same answer on every run). The cap
# on iterations is a safety stop; a spot that hits it is saved with "converged": false.
REFERENCE_TARGET = 0.00001
REFERENCE_MAX_ITERATIONS = 65536
ACCEPT = 0.00005  # a saved reference answer must be within this share of the pot (0.005%)


def reference_solve(spot: Mapping) -> Tuple[RiverStrategy, Dict]:
    start = time.perf_counter()
    strategy = solve_river(river_spot(spot), None, max_iterations=REFERENCE_MAX_ITERATIONS,
                           target_exploitability=REFERENCE_TARGET)
    elapsed = time.perf_counter() - start
    info = {"name": SOLVER_NAME, "version": SOLVER_VERSION, "module": "app.solver",
            "settings": {"method": DEFAULT_METHOD, "target_exploitability_pot": REFERENCE_TARGET,
                         "max_iterations": REFERENCE_MAX_ITERATIONS, "time_budget_ms": None},
            "iterations": strategy.iterations, "elapsed_s": round(elapsed, 2),
            "exploitability_pot": round(float(strategy.exploitability), 8),
            "converged": bool(strategy.exploitability <= REFERENCE_TARGET), "notes": []}
    return strategy, info


def make_result(spot: Mapping, strategy: RiverStrategy, info: Mapping) -> Tuple[dict, list]:
    """(header, node records) of the RESULT. The checks are worked out again from the
    records as they are saved (probabilities rounded to 6 places), not from the solver."""
    records = nodes_from_river_strategy(strategy)
    expected = decision_nodes(spot)
    ordered = [records[key] for key in expected]
    checks = river_checks(spot, records)
    checks["expected_failures"] = check_expected(spot, records)
    header = result_mod.make_header(spot, spot_hash(spot), info, len(ordered), checks)
    result_mod.validate_result(header, records, spot, header["spot_sha256"], expected)
    return header, ordered


def at_the_apps_budget(spot: Mapping, runs: int = 3) -> Dict:
    """The spot as the app solves it: 300 ms, stopping early at 0.1% of the pot. The run
    with the median time of a few, since a busy moment can slow any single one."""
    rs = river_spot(spot)
    got = sorted((solve_river(rs, DECISION_BUDGET_MS, target_exploitability=TARGET_EXPLOITABILITY)
                  for _ in range(runs)), key=lambda s: s.elapsed_ms)
    s = got[len(got) // 2]
    return {"ms": round(s.elapsed_ms, 1), "iterations": s.iterations,
            "exploitability_pot": round(float(s.exploitability), 8)}
