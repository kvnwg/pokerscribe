"""Summary of the Phase 2 comparison of river_solver against B0 (phase2_solver_b0.sh; the rule
is in its header).

    python docs/research/runs/phase2_solver_b0_summary.py <stage>
"""
import argparse
import json
import math
import os
import sys

RUNS = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(RUNS, "phase2_solver_b0")
# stage: (tables, seeds, condition); the same as in phase2_solver_b0.sh
OTHERS = ("fish247", "heldout", "regulars", "switchers", "wildcards")
STAGES = {
    "1": (("mixed",), (1111, 2222, 3333, 4444), "gain"),
    "2": (OTHERS, (1111, 2222), "no loss"),
    "3": (("mixed",), (5555, 6666, 7777, 8888), "gain"),
    "4": (OTHERS, (5555, 6666), "no loss"),
}
GAIN, LOSS = 2.5, -2.0  # in standard errors


def load(table, seed):
    path = os.path.join(OUT, f"{table}_{seed}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return next(iter(json.load(f)["tables"].values()))


def pooled(runs):
    """Mean per hand and its SE, decks as units, over several runs (one per seed)."""
    groups = []
    for t in runs:
        sums, sizes = {}, {}
        for v, d in zip(t["resampled"], t["decks"]):
            sums[d] = sums.get(d, 0.0) + v
            sizes[d] = sizes.get(d, 0) + 1
        groups += [(sums[d], sizes[d]) for d in sums]
    n = sum(s for _, s in groups)
    mean = sum(v for v, _ in groups) / n
    var = sum((v - s * mean) ** 2 for v, s in groups) / max(1, len(groups) - 1) / (n / len(groups))
    return mean, math.sqrt(var / n), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=sorted(STAGES))
    a = ap.parse_args()
    tables, seeds, condition = STAGES[a.stage]
    print(f"Stage {a.stage}: seeds {', '.join(map(str, seeds))}; passes if "
          + ("the difference is at least 2.5 SE" if condition == "gain" else "no table loses by 2 SE or more"))
    print("\n| Table | Hands | Hands that differ | river_solver minus B0 (bb/100) | In SE |")
    print("|---|---|---|---|---|")
    ok, missing = True, []
    for table in tables:
        runs = [load(table, s) for s in seeds]
        missing += [f"{table}_{s}" for s, t in zip(seeds, runs) if t is None]
        runs = [t for t in runs if t]
        if not runs:
            continue
        differ = sum(t["replayed"] for t in runs)
        mean, se, n = pooled(runs)
        z = mean / se if se else 0.0
        ok = ok and (z >= GAIN if condition == "gain" else z > LOSS)
        print(f"| {table} | {n} | {differ} ({100 * differ / n:.2f}%) | {100 * mean:+.1f} ± {100 * se:.1f} | {z:+.2f} |")
    if missing:
        print(f"\nNot finished: {', '.join(missing)}")
        sys.exit(1)
    print(f"\nStage {a.stage} {'PASSES' if ok else 'FAILS'}.")


if __name__ == "__main__":
    main()
