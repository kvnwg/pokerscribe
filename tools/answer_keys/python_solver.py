"""The Python reference answers, saved as RESULTs in data/answer_keys/python_solver/
(python -m tools.answer_keys export-python):

- the river spots, solved by app/solver's solve_river. This is the Phase 2 reference;
- the turn spots, solved by turn_solver.py, an exact turn solver in numpy on the same
  rules and payoffs. app/solver has no turn solver, and TexasSolver's turn answers follow
  its own rule for the river card (docs/research/PHASE4.md), so this is the only exact
  answer to the turn spots.

solve_spot is also what the stand-in for the Rust binary calls (standin_solver.py).

The references are solved to a much tighter target than the Phase 4 gate (0.01% of the pot
on both streets, against 0.5%), with no clock, so their EVs are the game's value to within
0.01% of the pot and a run repeats on the same machine. The river solver checks its
exploitability at iterations 8, 16, 32, ... and the turn solver every 25 iterations; each
stops at the first check at or under the target.
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

from . import turn_solver
from .checks import check_expected, nodes_from_river_strategy, river_checks
from .result import make_header, now, validate_result, write_result
from .spots import ROOT, decision_nodes, river_spot, spot_hash
from .values import Game

RESULTS_DIR = os.path.join(ROOT, "data", "answer_keys", "python_solver")
REFERENCE_TARGET_PCT = 0.01  # the river reference stops at this exploitability, percent of the pot
TURN_REFERENCE_TARGET_PCT = 0.01  # and the turn reference at this
MAX_ITERATIONS = 100_000  # a safety stop; a spot that hits it is not converged
TURN_MAX_ITERATIONS = 20_000  # the same for a turn spot (about 40 ms an iteration)
INDEX = "index.json"


def our_checks(spot: Mapping, nodes: Mapping[str, Mapping]) -> dict:
    """The header's "checks" block (data/SPOT_FORMAT.md): the answer's exploitability, each
    player's value and the bounds on the true value (river spots by app/solver's checker,
    turn spots by values.py), the rows that had to be filled in, and the spot's expected
    checks that fail."""
    checks = river_checks(spot, nodes) if spot["street"] == "river" else Game(spot).checks(nodes)
    checks["expected_failures"] = check_expected(spot, nodes)[:20]
    return checks


def default_target_pct(spot: Mapping) -> float:
    return REFERENCE_TARGET_PCT if spot["street"] == "river" else TURN_REFERENCE_TARGET_PCT


def default_max_iterations(spot: Mapping) -> int:
    return MAX_ITERATIONS if spot["street"] == "river" else TURN_MAX_ITERATIONS


def solve_spot(spot: Mapping, target_pct: Optional[float] = None, max_iterations: Optional[int] = None,
               time_ms: Optional[float] = None) -> Tuple[dict, List[dict]]:
    """Solve a spot and return its RESULT: (header, node records in the order of the
    spot's tree). River spots go to app/solver, turn spots to turn_solver.py. target_pct is
    in percent of the pot (0 = never stop early; None = the reference's target for the
    street). With no limit at all, the reference's safety stop on iterations applies."""
    if target_pct is None:
        target_pct = default_target_pct(spot)
    if max_iterations is None and time_ms is None:
        max_iterations = default_max_iterations(spot)
    settings = {"method": DEFAULT_METHOD, "target_exploitability_pct": target_pct,
                "max_iterations": max_iterations, "time_ms": time_ms}
    if spot["street"] == "river":
        strategy = solve_river(river_spot(spot), time_ms, max_iterations=max_iterations,
                               target_exploitability=target_pct / 100.0)
        by_key = nodes_from_river_strategy(strategy)
        name, version = SOLVER_NAME, SOLVER_VERSION
        iterations, elapsed_ms, expl = strategy.iterations, strategy.elapsed_ms, float(strategy.exploitability)
    else:
        answer = turn_solver.solve(spot, target_pct / 100.0, max_iterations, time_ms)
        by_key = turn_solver.node_records(answer)
        name, version = turn_solver.NAME, turn_solver.VERSION
        settings = dict(settings, method=turn_solver.METHOD, check_every=turn_solver.CHECK_EVERY)
        iterations, elapsed_ms, expl = answer.iterations, answer.elapsed_ms, float(answer.exploitability)
    expected = decision_nodes(spot)
    nodes = [by_key[k] for k in expected]
    solver = {"name": name, "version": version, "binary_sha256": None, "settings": settings,
              "iterations": iterations, "elapsed_s": round(elapsed_ms / 1000.0, 6),
              "exploitability_pot": round(expl, 8), "converged": target_pct > 0 and expl <= target_pct / 100.0}
    header = make_header(spot, spot_hash(spot), solver, len(nodes), our_checks(spot, by_key))
    validate_result(header, by_key, spot, header["spot_sha256"], expected)
    return header, nodes


def export(spots: List[Mapping], out_dir: str = RESULTS_DIR, target_pct: float = REFERENCE_TARGET_PCT,
           max_iterations: int = MAX_ITERATIONS, turn_target_pct: float = TURN_REFERENCE_TARGET_PCT,
           turn_max_iterations: int = TURN_MAX_ITERATIONS, log=print) -> dict:
    """Solve every spot in `spots`, save the RESULTs and an index.json, and return the
    index. Spots solved earlier and not solved again keep their entry in the index, as long
    as their file is there."""
    entries: Dict[str, dict] = {}
    try:
        with open(os.path.join(out_dir, INDEX)) as f:
            entries = {k: e for k, e in json.load(f).get("spots", {}).items()
                       if os.path.exists(os.path.join(out_dir, e.get("file", "")))}
    except (OSError, ValueError):
        pass
    limits = {"river": (target_pct, max_iterations), "turn": (turn_target_pct, turn_max_iterations)}
    for spot in spots:
        target, cap = limits[spot["street"]]
        header, nodes = solve_spot(spot, target, cap)
        path = write_result(out_dir, header, nodes)
        solver, checks = header["solver"], header["checks"]
        entries[spot["id"]] = e = {
            "status": "ok" if solver["converged"] and not checks["expected_failures"] else "warn",
            "street": spot["street"], "spot_sha256": header["spot_sha256"], "nodes": len(nodes),
            "target_exploitability_pct": target,
            "iterations": solver["iterations"], "solver_ms": round(1000.0 * solver["elapsed_s"], 3),
            "exploitability_pot": solver["exploitability_pot"],
            "checked_exploitability_pot": checks["exploitability_pot"],
            "oop_value": checks["values"]["oop"],
            "expected_failures": len(checks["expected_failures"]),
            "file": os.path.basename(path), "bytes": os.path.getsize(path)}
        log(f"{spot['id']:4} {e['status']:4} {e['iterations']:6d} iterations  {e['solver_ms']:9.1f} ms  "
            f"exploitability {100 * e['exploitability_pot']:.4f}% "
            f"(checked {100 * e['checked_exploitability_pot']:.4f}%)")
    if not spots:
        return {"spots": {}}
    entries = dict(sorted(entries.items()))
    timing = {}
    for street in ("river", "turn"):
        times = [e["solver_ms"] for e in entries.values() if e["street"] == street]
        if times:
            timing[street] = {"spots": len(times), "runs": len(times),
                              "solver_ms_p50": round(percentile(times, 50), 3),
                              "solver_ms_p95": round(percentile(times, 95), 3)}
    index = {"format": "pokerscribe-run-index", "version": 1,
             "solver": {"river": {"name": SOLVER_NAME, "version": SOLVER_VERSION,
                                  "how": "export-python (solve_river in this process)"},
                        "turn": {"name": turn_solver.NAME, "version": turn_solver.VERSION,
                                 "how": "export-python (turn_solver.solve in this process)"}},
             "settings": {"river": {"method": DEFAULT_METHOD, "target_exploitability_pct": target_pct,
                                    "max_iterations": max_iterations, "time_ms": None},
                          "turn": {"method": turn_solver.METHOD, "target_exploitability_pct": turn_target_pct,
                                   "max_iterations": turn_max_iterations, "time_ms": None,
                                   "check_every": turn_solver.CHECK_EVERY}},
             "machine": machine(), "created": now(), "timing": timing, "spots": entries}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, INDEX), "w") as f:
        json.dump(index, f, indent=1, sort_keys=True)
        f.write("\n")
    return index


def machine() -> dict:
    """Where the times were measured: they mean nothing without it."""
    return {"system": platform.system(), "machine": platform.machine(), "cpus": os.cpu_count(),
            "python": platform.python_version()}
