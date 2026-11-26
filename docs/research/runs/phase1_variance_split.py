"""Where is the variance left in a paired comparison? (Phase 1 diagnostic)

    python docs/research/runs/phase1_variance_split.py '{"ev_sizing": true}' 1200 --table fish247 --seed 303

Finds the hands where the two variants part ways (duplicate deals), then replays each of
them K times for both variants with fresh randomness from the first decision where they
differ: new bot random numbers and new board cards still to come (the same for both
variants in each replay). The hole cards and everything before that decision stay.

    within  = average over hands of the variance across replays: the part due to what
              happens after the split (board cards and bot random choices)
    between = what is left: the part fixed before the split (above all the bots' hole
              cards, which decide how they answer each bet)

for the raw and the luck-adjusted differences (tools/luck.py). The luck adjustment can
only reduce "within"; AIVAT's imaginary observations over the bots' cards would be needed
for "between".
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
import compare  # noqa: E402
import luck  # noqa: E402
import simulate as sim  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("other")
    ap.add_argument("hands", type=int, nargs="?", default=1200)
    ap.add_argument("--table", default="mixed")
    ap.add_argument("--stacks", default="even")
    ap.add_argument("--seed", type=int, default=303)
    ap.add_argument("--k", type=int, default=6)
    a = ap.parse_args()
    other = json.loads(a.other)
    found = []
    for k in range(a.hands):
        d, r = divmod(k, 6)
        styles, names = sim.seating(a.table, a.seed, d)
        st = compare.new_stats({}, other)
        sim.play_hand(styles, d % 6, a.seed * 100003 + d, 0, 100.0, st, a.stacks, names, None, k + 1,
                      rotate=r, keyed=True)
        if st["diverged"]:
            found.append((k, st["last"]["diverge_at"]))
    rows = []
    for k, j in found:
        d, r = divmod(k, 6)
        styles, names = sim.seating(a.table, a.seed, d)
        raws, adjs = [], []
        for s in range(a.k):
            nets = []
            for v in ({}, other):
                st = compare.new_stats(v)
                sim.play_hand(styles, d % 6, a.seed * 100003 + d, 0, 100.0, st, a.stacks, names, None, k + 1,
                              rotate=r, keyed=True, split_at=j, resample=s + 1)
                nets.append((st["last"]["net"], luck.adjusted(st["last"])))
            raws.append(nets[1][0] - nets[0][0])
            adjs.append(nets[1][1] - nets[0][1])
        rows.append((raws, adjs))

    def split(idx):
        within = sum(_var([row[idx][s] for s in range(a.k)]) for row in rows) / len(rows)
        means = [sum(row[idx]) / a.k for row in rows]
        total = sum(x * x for row in rows for x in row[idx]) / (len(rows) * a.k)
        between = sum(m * m for m in means) / len(rows) - within / a.k
        return total, within, between

    print(f"{a.other} on {a.table} ({a.stacks}), seed {a.seed}: {len(found)} of {a.hands} hands differ, "
          f"{a.k} replays each")
    for name, idx in (("raw", 0), ("luck-adjusted", 1)):
        total, within, between = split(idx)
        print(f"  {name:14s} mean square per differing hand {total:7.1f}: after the split {within:7.1f} "
              f"({within / total:.0%}), fixed before it {between:7.1f} ({between / total:.0%})")


def _var(xs):
    m = sum(xs) / len(xs)
    return sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)


if __name__ == "__main__":
    main()
