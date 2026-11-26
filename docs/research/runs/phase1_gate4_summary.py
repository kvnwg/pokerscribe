"""Summary of Phase 1 gate run 4 (phase1_gate4.sh): the rule is in that script's header.

    python docs/research/runs/phase1_gate4_summary.py docs/research/runs/phase1_gate4
"""
import json
import math
import os
import sys

RUNS = os.path.dirname(os.path.abspath(__file__))
NAMES = ["ev_mixed", "ev_fish", "bet_half", "semibluff_never", "texture", "push_chart", "commit", "no_stab"]
NEW_SEEDS, OLD_SEEDS = (606, 707), (303, 404, 606, 707)


def load(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return next(iter(json.load(f)["tables"].values()))


def sd_per_hand(sets):
    """sd per hand of a mean over hands, decks as units, pooled over runs: sets is a list of
    (values, decks or None). With six hands a deck the variance of a deck's sum is shared out
    over its hands."""
    groups = []
    for values, decks in sets:
        if decks is None:
            groups += [(v, 1) for v in values]
        else:
            sums, sizes = {}, {}
            for v, d in zip(values, decks):
                sums[d] = sums.get(d, 0.0) + v
                sizes[d] = sizes.get(d, 0) + 1
            groups += [(sums[d], sizes[d]) for d in sums]
    n = sum(s for _, s in groups)
    mean = sum(v for v, _ in groups) / n
    var = sum((v - s * mean) ** 2 for v, s in groups) / max(1, len(groups) - 1) / (n / len(groups))
    return math.sqrt(var), mean, n


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RUNS, "phase1_gate4")
    rows, ratios, cpu_new, cpu_old, hands_new, hands_old = [], [], 0.0, 0.0, 0, 0
    for name in NAMES:
        new_sets, old_sets = [], []
        for seed in NEW_SEEDS:
            t = load(os.path.join(out, f"{name}_duplicate_{seed}.json"))
            if t:
                new_sets.append((t["resampled"], t["decks"]))
                if t.get("cpu_seconds"):
                    cpu_new += t["cpu_seconds"]
                    hands_new += len(t["diffs"])
        for seed in OLD_SEEDS:
            path = {303: os.path.join(RUNS, "phase1_gate", f"{name}_classic.json"),
                    404: os.path.join(RUNS, "phase1_gate_404", f"{name}_classic.json")}.get(
                seed, os.path.join(out, f"{name}_classic_{seed}.json"))
            t = load(path)
            if t:
                old_sets.append((t["diffs"], None))
                if seed in NEW_SEEDS and t.get("cpu_seconds"):
                    cpu_old += t["cpu_seconds"]
                    hands_old += len(t["diffs"])
        if not new_sets or not old_sets:
            continue
        sd_new, m_new, n_new = sd_per_hand(new_sets)
        sd_old, m_old, n_old = sd_per_hand(old_sets)
        differ = sum(1 for values, _ in new_sets for v in values if v)
        if not differ or not sd_old:
            rows.append(f"| {name} | {n_new} | {n_old} | - | - | no hand differs: left out |")
            continue
        r = sd_new / sd_old
        ratios.append(r)
        rows.append(f"| {name} | {n_new} | {n_old} | {100 * m_new:+.1f} ± {100 * sd_new / math.sqrt(n_new):.1f} | "
                    f"{100 * m_old:+.1f} ± {100 * sd_old / math.sqrt(n_old):.1f} | **{r:.2f}** |")
    print("| Comparison | Hands, new | Hands, old | New way (bb/100) | Old way (bb/100) | r |")
    print("|---|---|---|---|---|---|")
    print("\n".join(rows))
    if ratios:
        gm = math.exp(sum(map(math.log, ratios)) / len(ratios))
        t = (cpu_new / hands_new) / (cpu_old / hands_old) if hands_new and hands_old else float("nan")
        ok = gm <= 0.5 and max(ratios) <= 0.75 and t <= 1.25
        print(f"\nGeometric mean of r: {gm:.2f}; largest r: {max(ratios):.2f}; CPU per hand, new / old: {t:.2f}. "
              f"Gate {'PASSES' if ok else 'FAILS'} (needs at most 0.5, 0.75 and 1.25).")


if __name__ == "__main__":
    main()
