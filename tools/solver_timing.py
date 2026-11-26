"""Time the river solver: p50 and p95 decision time against the 400 ms target, and how
close to an equilibrium each answer is when the clock stops it.

    python tools/solver_timing.py [--spots 200] [--seed 1] [--ranges narrow|medium|wide|all]
                                  [--budget-ms 300] [--target-ms 400] [--bar 0.01]

Each decision is one solve_river call on a benchmark spot (a random board, a pot of 20 to
200, stack-to-pot ratios from 0.5 to 8, both ranges a top share of preflop hands) with
the time budget the advice gives it. The solver stops when its answer is good enough or
the budget is nearly spent, so the time passes almost by construction; what tells the
spots apart is the exploitability reached. A spot misses when a perfect counter-strategy
could still win more than --bar of the pot; every miss and every decision over the time
target is listed with its range sizes, stack-to-pot ratio and iterations.

Exits 0 when p95 is under the target and nothing misses, 1 otherwise, 2 when the solver
isn't there.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import DECISION_BUDGET_MS, solve_river  # noqa: E402
from app.solver.timing import (QUALITY_BAR, RANGE_SHARES, TARGET_MS, QualityReport,  # noqa: E402
                               benchmark_spots, time_decisions)


def _describe(spot, strategy, ms: float) -> str:
    its = getattr(strategy, "iterations", "?")
    expl = getattr(strategy, "exploitability", None)
    quality = f"{100 * expl:.3f}% of the pot" if expl is not None else "unknown"
    return (f"{' '.join(spot.board)}, {len(spot.oop_range)} v {len(spot.ip_range)} combos, stack {spot.effective_stack / spot.pot:g}x "
            f"pot: {ms:.0f} ms, {its} iterations, exploitable for {quality}")


def run(ranges: str, args, solver: Callable) -> bool:
    spots = benchmark_spots(args.spots, args.seed, ranges)
    answers: list = []
    report = time_decisions(spots, lambda spot: answers.append(solver(spot, args.budget_ms)), target_ms=args.target_ms)
    print(f"River solver, {ranges} ranges, budget {args.budget_ms:g} ms, seed {args.seed}")
    print("  " + str(report))
    ok = report.passed
    slow = [i for i, t in enumerate(report.times_ms) if t > args.target_ms]
    for i in slow:
        print(f"  over {args.target_ms:g} ms: spot {i}: " + _describe(spots[i], answers[i], report.times_ms[i]))
    values = [getattr(a, "exploitability", None) for a in answers]
    if all(v is not None for v in values):
        quality = QualityReport(tuple(values), args.bar)
        print("  " + str(quality))
        for i in quality.misses:
            print(f"  over the bar: spot {i}: " + _describe(spots[i], answers[i], report.times_ms[i]))
        ok = ok and quality.passed
    return ok


def main(argv: Optional[List[str]] = None, solver: Callable = solve_river) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spots", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ranges", choices=sorted(RANGE_SHARES) + ["all"], default="medium")
    ap.add_argument("--budget-ms", type=float, default=DECISION_BUDGET_MS, help="time budget given to the solver")
    ap.add_argument("--target-ms", type=float, default=TARGET_MS, help="p95 must be under this")
    ap.add_argument("--bar", type=float, default=QUALITY_BAR, help="exploitability (share of the pot) that counts as a miss")
    args = ap.parse_args(argv)

    kinds = ["narrow", "medium", "wide"] if args.ranges == "all" else [args.ranges]
    try:
        results = [run(k, args, solver) for k in kinds]
    except NotImplementedError:
        print("The river solver isn't there: nothing to time.")
        return 2
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
