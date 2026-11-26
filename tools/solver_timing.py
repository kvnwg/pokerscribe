"""Time the river solver: p50 and p95 decision time against the 400 ms target.

    python tools/solver_timing.py [--spots 200] [--seed 1] [--ranges narrow|medium|wide]
                                  [--budget-ms 300] [--target-ms 400]

Each decision is one solve_river call on a benchmark spot (a random board, a pot of 20 to
200, stack-to-pot ratios from 0.5 to 8, both ranges a top share of preflop hands) with
the time budget the advice gives it. Exits 0 when p95 is under the target, 1 when it
isn't, 2 when the solver isn't written yet.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import DECISION_BUDGET_MS, solve_river  # noqa: E402
from app.solver.timing import RANGE_SHARES, TARGET_MS, benchmark_spots, time_decisions  # noqa: E402


def main(argv: Optional[List[str]] = None, solver: Callable = solve_river) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spots", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ranges", choices=sorted(RANGE_SHARES), default="medium")
    ap.add_argument("--budget-ms", type=float, default=DECISION_BUDGET_MS, help="time budget given to the solver")
    ap.add_argument("--target-ms", type=float, default=TARGET_MS, help="p95 must be under this")
    args = ap.parse_args(argv)

    spots = benchmark_spots(args.spots, args.seed, args.ranges)
    try:
        report = time_decisions(spots, lambda spot: solver(spot, args.budget_ms), target_ms=args.target_ms)
    except NotImplementedError:
        print("The river solver isn't written yet (Phase 2): nothing to time.")
        return 2
    print(f"River solver, {args.ranges} ranges, budget {args.budget_ms:g} ms, seed {args.seed}")
    print(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
