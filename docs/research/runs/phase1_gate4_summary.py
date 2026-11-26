"""Summary of Phase 1 gate runs 4 and 5 (phase1_gate4.sh, phase1_gate5.sh): the rules are in
those scripts' headers. The defaults are run 4's.

    python docs/research/runs/phase1_gate4_summary.py docs/research/runs/phase1_gate4
    python docs/research/runs/phase1_gate4_summary.py docs/research/runs/phase1_gate5 \
        --new-seeds 808,909 --old-seeds 303,404,606,707,808,909 --min-share 0.01
    python docs/research/runs/phase1_gate4_summary.py docs/research/runs/phase1_heads_up_gate \
        --new-seeds 1111,1212 --old-seeds 1111,1212,1313,1414 --min-share 0.01 --strict   # heads-up
"""
import argparse
import json
import math
import os
import sys

RUNS = os.path.dirname(os.path.abspath(__file__))
NAMES = ["ev_mixed", "ev_fish", "bet_half", "semibluff_never", "texture", "push_chart", "commit", "no_stab"]
FOLDERS = ("phase1_gate4", "phase1_gate5")  # where the classic runs of later seeds are


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


def classic_path(out: str, name: str, seed: int) -> str:
    if seed == 303:
        return os.path.join(RUNS, "phase1_gate", f"{name}_classic.json")
    if seed == 404:
        return os.path.join(RUNS, "phase1_gate_404", f"{name}_classic.json")
    for folder in (out,) + tuple(os.path.join(RUNS, f) for f in FOLDERS):
        path = os.path.join(folder, f"{name}_classic_{seed}.json")
        if os.path.exists(path):
            return path
    return os.path.join(out, f"{name}_classic_{seed}.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=os.path.join(RUNS, "phase1_gate4"))
    ap.add_argument("--new-seeds", default="606,707")
    ap.add_argument("--old-seeds", default="303,404,606,707")
    ap.add_argument("--min-share", type=float, default=0.0,
                    help="judge only comparisons in which at least this share of the new way's hands differ")
    ap.add_argument("--strict", action="store_true", help="also say whether every judged r is at most 0.5")
    a = ap.parse_args()
    out = a.out
    new_seeds = tuple(int(x) for x in a.new_seeds.split(","))
    old_seeds = tuple(int(x) for x in a.old_seeds.split(","))
    rows, ratios, cpu_new, cpu_old, hands_new, hands_old = [], [], 0.0, 0.0, 0, 0
    for name in NAMES:
        new_sets, old_sets = [], []
        differing = played = 0
        for seed in new_seeds:
            t = load(os.path.join(out, f"{name}_duplicate_{seed}.json"))
            if t:
                new_sets.append((t["resampled"], t["decks"]))
                differing += t["replayed"]
                played += len(t["diffs"])
                if t.get("cpu_seconds"):
                    cpu_new += t["cpu_seconds"]
                    hands_new += len(t["diffs"])
        for seed in old_seeds:
            t = load(classic_path(out, name, seed))
            if t:
                old_sets.append((t["diffs"], None))
                if seed in new_seeds and t.get("cpu_seconds"):
                    cpu_old += t["cpu_seconds"]
                    hands_old += len(t["diffs"])
        if not new_sets or not old_sets:
            continue
        sd_new, m_new, n_new = sd_per_hand(new_sets)
        sd_old, m_old, n_old = sd_per_hand(old_sets)
        differ = sum(1 for values, _ in new_sets for v in values if v)
        share = differing / played if played else 0.0
        cells = f"| {name} | {n_new} | {n_old} | " + (f"{100 * share:.2f}% | " if a.min_share else "")
        if not differ or not sd_old:
            rows.append(cells + "- | - | no hand differs: left out |")
            continue
        r = sd_new / sd_old
        judged = share >= a.min_share
        if judged:
            ratios.append(r)
        rows.append(cells + f"{100 * m_new:+.1f} ± {100 * sd_new / math.sqrt(n_new):.1f} | "
                    f"{100 * m_old:+.1f} ± {100 * sd_old / math.sqrt(n_old):.1f} | "
                    + (f"**{r:.2f}** |" if judged else f"{r:.2f} (under {100 * a.min_share:g}% differ: not judged) |"))
    head = "| Comparison | Hands, new | Hands, old | " + ("Hands that differ, new | " if a.min_share else "")
    print(head + "New way (bb/100) | Old way (bb/100) | r |")
    print("|---|---|---|" + ("---|" if a.min_share else "") + "---|---|---|")
    print("\n".join(rows))
    if ratios:
        gm = math.exp(sum(map(math.log, ratios)) / len(ratios))
        t = (cpu_new / hands_new) / (cpu_old / hands_old) if hands_new and hands_old else float("nan")
        ok = gm <= 0.5 and max(ratios) <= 0.75 and t <= 1.25
        print(f"\nGeometric mean of r: {gm:.2f}; largest r: {max(ratios):.2f}; CPU per hand, new / old: {t:.2f}. "
              f"Gate {'PASSES' if ok else 'FAILS'} (needs at most 0.5, 0.75 and 1.25).")
        if a.strict:
            print(f"Every judged r at most 0.5 (the brief read strictly): {'yes' if max(ratios) <= 0.5 else 'no'}.")


if __name__ == "__main__":
    main()
