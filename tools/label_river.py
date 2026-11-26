"""Save solver-labelled river decisions for later (format: app/solver/labels.py).

    python tools/label_river.py --synthetic 100 --out river_labels.jsonl [--seed 1]
                                [--ranges narrow|medium|wide] [--budget-ms 2000]
    python tools/label_river.py --phh <decisions.parquet> --out river_labels.jsonl   (not yet)

--synthetic N solves N benchmark spots (app/solver/timing.py) and writes one record per
decision node, with the strategy of every combo that can reach it. Labelling runs
offline, so it can take a bigger time budget than the 400 ms a live decision gets.

--phh will read heads-up river decisions from the hand history dataset (tools/phh), with
the recorded action kept as "observed": an observation, never the label. That needs
range estimates from the hand's history (the Phase 3 opponent model) and is not written.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import solve_river  # noqa: E402
from app.solver.labels import make_label, write_labels  # noqa: E402
from app.solver.timing import RANGE_SHARES, benchmark_spots  # noqa: E402


def synthetic_labels(n: int, seed: int, ranges: str, budget_ms: float, solver: Callable = solve_river):
    for i, spot in enumerate(benchmark_spots(n, seed, ranges)):
        strategy = solver(spot, budget_ms)
        for node in strategy.tree.decision_nodes():
            yield make_label(strategy, node.key, source=f"synthetic:seed={seed}:spot={i}", time_budget_ms=budget_ms)


def main(argv: Optional[List[str]] = None, solver: Callable = solve_river) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", type=int, metavar="N", help="label N benchmark spots")
    src.add_argument("--phh", metavar="PARQUET", help="label river decisions from the hand history dataset (not yet)")
    ap.add_argument("--out", required=True, help="JSON Lines file to append to")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ranges", choices=sorted(RANGE_SHARES), default="medium")
    ap.add_argument("--budget-ms", type=float, default=2000.0)
    args = ap.parse_args(argv)

    if args.phh:
        print("Labelling hand history decisions isn't written yet: it needs range estimates from each "
              "hand's history (Phase 3). Use --synthetic for now.")
        return 2
    try:
        n = write_labels(args.out, synthetic_labels(args.synthetic, args.seed, args.ranges, args.budget_ms, solver))
    except NotImplementedError:
        print("The river solver isn't there: nothing was labelled.")
        return 2
    print(f"Wrote {n} labelled decisions to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
