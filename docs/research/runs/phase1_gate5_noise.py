"""Phase 1 gate runs 4 and 5: how much one run's ratios move by chance. Descriptive only: it
was written after run 5's result was seen, so it is not part of any gate rule.

    python docs/research/runs/phase1_gate5_noise.py

1. r per comparison in run 4, in run 5, and pooled over both (new way: 12000 hands on seeds
   606, 707, 808 and 909; old way: 18000 hands on seeds 303 to 909).
2. A bootstrap: runs of run 5's size drawn again and again from the pooled hands (1000 decks
   for the new way, 18000 hands for the old way, with replacement; the same decks and hands
   for every comparison, as a run on fresh seeds would have), each judged by run 5's rule
   (the CPU condition left out).
3. CPU seconds for equal precision, new way over old way, per comparison in run 5: r squared
   times that comparison's CPU ratio.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phase1_gate4_summary as g  # noqa: E402

NAMES = g.NAMES
NEW = {4: [("phase1_gate4", 606), ("phase1_gate4", 707)], 5: [("phase1_gate5", 808), ("phase1_gate5", 909)]}
OLD = {4: [303, 404, 606, 707], 5: [303, 404, 606, 707, 808, 909]}
OUT5 = os.path.join(HERE, "phase1_gate5")
DRAWS = 2000


def table(name, folder, seed, method):
    return g.load(os.path.join(HERE, folder, f"{name}_{method}_{seed}.json"))


def ratio(name, runs, old_seeds):
    new = [(t["resampled"], t["decks"]) for t in (table(name, f, s, "duplicate") for f, s in runs)]
    old = [(g.load(g.classic_path(OUT5, name, s))["diffs"], None) for s in old_seeds]
    return g.sd_per_hand(new)[0] / g.sd_per_hand(old)[0]


def decks(name, runs):
    """Per deck, in a fixed (seed, deck) order: the sum of the new way's results, its hands and
    the hands that differ. The saved files don't mark the hands that differ, so a hand counts
    if any of its saved results isn't zero. That matches the count the rule uses to within 2
    hands a seed for the comparisons near 1%; on the bet-size comparisons it misses about a
    quarter of them (both sizes win the same pot), which leaves those far above 1% anyway."""
    rows = []
    for folder, seed in runs:
        t = table(name, folder, seed, "duplicate")
        by = {}
        for k, d in enumerate(t["decks"]):
            a = by.setdefault(d, [0.0, 0, 0])
            a[0] += t["resampled"][k]
            a[1] += 1
            a[2] += any(t[f][k] for f in ("diffs", "adjusted", "resampled", "resampled_raw"))
        rows += [by[d] for d in sorted(by)]
    return np.array(rows, dtype=float).T


def sd(sums, sizes):
    """sd per hand, units as in phase1_gate4_summary.sd_per_hand."""
    n, k = sizes.sum(), len(sums)
    mean = sums.sum() / n
    return math.sqrt(((sums - sizes * mean) ** 2).sum() / (k - 1) / (n / k))


def r_or_none(new_sd, old_sd):
    """None where a side has no hand that differs (the rule leaves those out)."""
    return new_sd / old_sd if new_sd and old_sd else None


def gm(xs):
    return math.exp(sum(map(math.log, xs)) / len(xs))


def main():
    print("1. r per comparison\n")
    print("| Comparison | Run 4 | Run 5 | Runs 4 and 5 pooled |")
    print("|---|---|---|---|")
    pooled = {}
    for name in NAMES:
        r4, r5 = ratio(name, NEW[4], OLD[4]), ratio(name, NEW[5], OLD[5])
        pooled[name] = ratio(name, NEW[4] + NEW[5], OLD[5])
        print(f"| {name} | {r4:.2f} | {r5:.2f} | {pooled[name]:.2f} |")
    judged = ["ev_mixed", "ev_fish", "bet_half", "texture", "push_chart"]
    print(f"\nPooled, the five judged in runs 4 and 5: geometric mean {gm([pooled[n] for n in judged]):.2f}; "
          f"without push_chart {gm([pooled[n] for n in judged[:4]]):.2f}")

    print(f"\n2. {DRAWS} runs of run 5's size drawn from the pooled hands\n")
    new = {n: decks(n, NEW[4] + NEW[5]) for n in NAMES}
    old = {n: np.concatenate([np.array(g.load(g.classic_path(OUT5, n, s))["diffs"], dtype=float) for s in OLD[5]])
           for n in NAMES}
    n_decks, n_old = len(new[NAMES[0]][0]), len(old[NAMES[0]])
    rng = np.random.default_rng(2026)
    rs = {n: [] for n in NAMES}
    judged_in = {n: 0 for n in NAMES}
    passes = gm_ok = max_ok = 0
    for _ in range(DRAWS):
        pick_new = rng.integers(0, n_decks, n_decks // 2)
        pick_old = rng.integers(0, n_old, n_old)
        ones = np.ones(n_old)
        kept = []
        for n in NAMES:
            sums, sizes, differ = (a[pick_new] for a in new[n])
            r = r_or_none(sd(sums, sizes), sd(old[n][pick_old], ones))
            rs[n].append(math.nan if r is None else r)
            if r is not None and differ.sum() / sizes.sum() >= 0.01:
                judged_in[n] += 1
                kept.append(r)
        a, b = gm(kept) <= 0.5, max(kept) <= 0.75
        gm_ok += a
        max_ok += b
        passes += a and b
    print("| Comparison | Middle r | 95% of draws | Judged in | r above 0.75 in |")
    print("|---|---|---|---|---|")
    for n in NAMES:
        x = np.array(rs[n])
        lo, mid, hi = np.nanpercentile(x, [2.5, 50, 97.5])
        print(f"| {n} | {mid:.2f} | {lo:.2f} to {hi:.2f} | "
              f"{100 * judged_in[n] / DRAWS:.0f}% | {100 * np.mean(x > 0.75):.0f}% |")
    print(f"\nGeometric mean at most 0.5 in {100 * gm_ok / DRAWS:.0f}% of draws, no judged r above 0.75 in "
          f"{100 * max_ok / DRAWS:.0f}%, both in {100 * passes / DRAWS:.0f}%.")

    print("\n3. Run 5: CPU seconds for equal precision, new way over old way\n")
    print("| Comparison | r | CPU per hand, new / old | CPU for equal precision |")
    print("|---|---|---|---|")
    for name in NAMES:
        cpu = [sum(table(name, f, s, m)["cpu_seconds"] for f, s in NEW[5]) for m in ("duplicate", "classic")]
        r = ratio(name, NEW[5], OLD[5])
        print(f"| {name} | {r:.2f} | {cpu[0] / cpu[1]:.2f} | {r * r * cpu[0] / cpu[1]:.2f} |")


if __name__ == "__main__":
    main()
