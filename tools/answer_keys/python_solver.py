"""The Phase 2 reference answers: the river spots solved by app/solver's solve_river and
saved as RESULTs in data/answer_keys/python_solver/ (python -m tools.answer_keys
export-python).

solve_spot is also what the stand-in for the Rust binary calls (standin_solver.py).

The reference is solved to a much tighter target than the Phase 4 gate (0.01% of the pot
against 0.5%), with no clock, so its EVs are the game's value to within 0.02% of the pot
and a run repeats on the same machine. The solver checks its exploitability at iterations
8, 16, 32, ... and stops at the first of those at or under the target.
"""
from __future__ import annotations

import json
import os
import platform
from typing import Dict, List, Mapping, Optional, Tuple

from app.solver import solve_river
from app.solver.labels import SOLVER_NAME, SOLVER_VERSION
from app.solver.solve import DEFAULT_METHOD
from app.solver.timing import percentile

from .checks import check_expected, nodes_from_river_strategy, river_exploitability
from .result import make_header, now, validate_result, write_result
from .spots import ROOT, SpotError, decision_nodes, river_spot, spot_hash

RESULTS_DIR = os.path.join(ROOT, "data", "answer_keys", "python_solver")
REFERENCE_TARGET_PCT = 0.01  # the reference stops at this exploitability, percent of the pot
MAX_ITERATIONS = 100_000  # a safety stop; a spot that hits it is not converged
INDEX = "index.json"


def our_checks(spot: Mapping, nodes: Mapping[str, Mapping]) -> dict:
    """The header's "checks" block (data/SPOT_FORMAT.md): the answer's exploitability by
    app/solver's checker (river spots; null for turn spots), the rows that had to be filled
    in, and the spot's expected checks that fail."""
    checks = {"exploitability_pot": None, "filled_rows": 0, "expected_failures": check_expected(spot, nodes)[:20]}
    if spot["street"] == "river":
        expl, filled = river_exploitability(spot, nodes)
        checks["exploitability_pot"], checks["filled_rows"] = round(expl, 8), filled
    return checks


def solve_spot(spot: Mapping, target_pct: float = REFERENCE_TARGET_PCT, max_iterations: Optional[int] = MAX_ITERATIONS,
               time_ms: Optional[float] = None) -> Tuple[dict, List[dict]]:
    """Solve a river spot with app/solver and return its RESULT: (header, node records in
    the order of the spot's tree). target_pct is in percent of the pot (0 = never stop
    early); at least one of the three limits must be given."""
    if spot["street"] != "river":
        raise SpotError(f"{spot['id']} is a {spot['street']} spot: app/solver solves river spots only.")
    strategy = solve_river(river_spot(spot), time_ms, max_iterations=max_iterations,
                           target_exploitability=target_pct / 100.0)
    by_key = nodes_from_river_strategy(strategy)
    expected = decision_nodes(spot)
    nodes = [by_key[k] for k in expected]
    solver = {"name": SOLVER_NAME, "version": SOLVER_VERSION, "binary_sha256": None,
              "settings": {"method": DEFAULT_METHOD, "target_exploitability_pct": target_pct,
                           "max_iterations": max_iterations, "time_ms": time_ms},
              "iterations": strategy.iterations, "elapsed_s": round(strategy.elapsed_ms / 1000.0, 6),
              "exploitability_pot": round(float(strategy.exploitability), 8),
              "converged": target_pct > 0 and strategy.exploitability <= target_pct / 100.0}
    header = make_header(spot, spot_hash(spot), solver, len(nodes), our_checks(spot, by_key))
    validate_result(header, by_key, spot, header["spot_sha256"], expected)
    return header, nodes


def export(spots: List[Mapping], out_dir: str = RESULTS_DIR, target_pct: float = REFERENCE_TARGET_PCT,
           max_iterations: int = MAX_ITERATIONS, log=print) -> dict:
    """Solve every river spot in `spots`, save the RESULTs and an index.json, and return
    the index. Turn spots are skipped: app/solver has no turn solver. Spots solved earlier
    and not solved again keep their entry in the index, as long as their file is there."""
    entries: Dict[str, dict] = {}
    skipped = [s["id"] for s in spots if s["street"] != "river"]
    try:
        with open(os.path.join(out_dir, INDEX)) as f:
            entries = {k: e for k, e in json.load(f).get("spots", {}).items()
                       if os.path.exists(os.path.join(out_dir, e.get("file", "")))}
    except (OSError, ValueError):
        pass
    solved = 0
    for spot in spots:
        if spot["street"] != "river":
            continue
        header, nodes = solve_spot(spot, target_pct, max_iterations)
        path = write_result(out_dir, header, nodes)
        solved += 1
        solver, checks = header["solver"], header["checks"]
        entries[spot["id"]] = {
            "status": "ok" if solver["converged"] and not checks["expected_failures"] else "warn",
            "street": "river", "spot_sha256": header["spot_sha256"], "nodes": len(nodes),
            "target_exploitability_pct": target_pct,
            "iterations": solver["iterations"], "solver_ms": round(1000.0 * solver["elapsed_s"], 3),
            "exploitability_pot": solver["exploitability_pot"],
            "checked_exploitability_pot": checks["exploitability_pot"],
            "expected_failures": len(checks["expected_failures"]),
            "file": os.path.basename(path), "bytes": os.path.getsize(path)}
        e = entries[spot["id"]]
        log(f"{spot['id']:4} {e['status']:4} {e['iterations']:6d} iterations  {e['solver_ms']:8.1f} ms  "
            f"exploitability {100 * e['exploitability_pot']:.4f}% "
            f"(checked {100 * e['checked_exploitability_pot']:.4f}%)")
    if skipped:
        log(f"Skipped {len(skipped)} turn spots (app/solver solves river spots only).")
    if not solved:
        return {"spots": {}}
    entries = dict(sorted(entries.items()))
    times = [e["solver_ms"] for e in entries.values()]
    index = {"format": "pokerscribe-run-index", "version": 1,
             "solver": {"name": SOLVER_NAME, "version": SOLVER_VERSION,
                        "how": "export-python (solve_river in this process)"},
             "settings": {"method": DEFAULT_METHOD, "target_exploitability_pct": target_pct,
                          "max_iterations": max_iterations, "time_ms": None},
             "machine": machine(), "created": now(),
             "timing": {"river": {"spots": len(times), "runs": len(times),
                                  "solver_ms_p50": round(percentile(times, 50), 3),
                                  "solver_ms_p95": round(percentile(times, 95), 3)}} if times else {},
             "spots": entries}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, INDEX), "w") as f:
        json.dump(index, f, indent=1, sort_keys=True)
        f.write("\n")
    return index


def machine() -> dict:
    """Where the times were measured: they mean nothing without it."""
    return {"system": platform.system(), "machine": platform.machine(), "cpus": os.cpu_count(),
            "python": platform.python_version()}
