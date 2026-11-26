"""Summarise the Phase 1 gate runs (phase1_gate.sh): standard errors by method, the ratios
the gate is judged on, and run times.

    python docs/research/runs/phase1_gate_summary.py docs/research/runs/phase1_gate_404

Two luck adjustments are reported: "checked down" (the checked-down value only, the
meaning of "luck-adjusted" in run 1) and "fitted" (tools/luck.py's mix with the all-in value,
frozen weights, run 2), and "resampled" (the fitted adjustment averaged over replays from
where the variants part, run 3). Runs saved before an estimator existed lack it.
"""
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from compare import summary  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "docs/research/runs/phase1_gate"
runs = {}
for path in sorted(glob.glob(os.path.join(out, "*.json"))):
    name, method = os.path.basename(path)[:-5].rsplit("_", 1)
    with open(path) as f:
        data = json.load(f)
    t = next(iter(data["tables"].values()))
    units = t["decks"] if method == "duplicate" else None
    checked = t.get("checked_down") or t["adjusted"]
    fitted = t["adjusted"] if t.get("checked_down") else None
    resampled = t.get("resampled") or None
    runs[(name, method)] = {
        "raw": summary(t["diffs"], units), "checked": summary(checked, units),
        "fitted": summary(fitted, units) if fitted else None, "base": summary(t["base"], units),
        "resampled": summary(resampled, units) if resampled else None,
        "replayed": t["replayed"], "hands": len(t["diffs"]), "seconds": t["seconds"], "weights": t.get("weights")}


def fmt(x):
    return f"{x[0]:+.1f} ± {x[1]:.1f}" if x else "-"


names = sorted({n for n, _ in runs})
print("| Comparison | Method | Hands | Differ | Raw difference | Checked down | Fitted | Resampled | Base win rate | "
      "Seconds |")
print("|---|---|---|---|---|---|---|---|---|---|")
for n in names:
    for m in ("classic", "keyed", "duplicate"):
        r = runs.get((n, m))
        if r is None:
            continue
        print(f"| {n} | {m} | {r['hands']} | {r['replayed']} | {fmt(r['raw'])} | {fmt(r['checked'])} | "
              f"{fmt(r['fitted'])} | {fmt(r['resampled'])} | {fmt(r['base'])} | {r['seconds']:.0f} |")


def ratios_table(which: str):
    print(f"\nStandard error as a share of classic raw, luck adjustment = {which}:\n")
    print("| Comparison | Classic, adjusted | Keyed | Keyed, adjusted | Duplicate | Duplicate, adjusted (r) | "
          "Time, duplicate / classic |")
    print("|---|---|---|---|---|---|---|")
    ratios, times = [], []
    for n in names:
        c, k, d = runs.get((n, "classic")), runs.get((n, "keyed")), runs.get((n, "duplicate"))
        if c is None or d is None or d[which] is None:
            continue
        if d["replayed"] == 0:
            print(f"| {n} | - | - | - | - | (no hand differs: left out) | - |")
            continue
        base = c["raw"][1]

        def ratio(x):
            return x[1] / base if (base and x) else float("nan")
        r = ratio(d[which])
        ratios.append(r)
        times.append(d["seconds"] / c["seconds"])
        kk = f"{ratio(k['raw']):.2f} | {ratio(k[which]):.2f}" if k and k[which] else "- | -"
        print(f"| {n} | {ratio(c[which]):.2f} | {kk} | {ratio(d['raw']):.2f} | **{r:.2f}** | {times[-1]:.2f} |")
    ratios = [x for x in ratios if x > 0 and not math.isnan(x)]  # (a run too short to differ anywhere)
    if ratios:
        gm = math.exp(sum(math.log(x) for x in ratios) / len(ratios))
        tm = sum(times) / len(times)
        ok = gm <= 0.5 and max(ratios) <= 0.75 and tm <= 1.25
        print(f"\nGeometric mean of r: {gm:.2f}; largest r: {max(ratios):.2f}; mean time ratio: {tm:.2f}. "
              f"Gate {'PASSES' if ok else 'FAILS'} (needs at most 0.5, 0.75 and 1.25).")


ratios_table("checked")
if any(r["fitted"] for r in runs.values()):
    ratios_table("fitted")
if any(r["resampled"] for r in runs.values()):
    ratios_table("resampled")
    ws = next((r["weights"] for r in runs.values() if r["weights"]), None)
    if ws:
        print("\nWeights used (flop, turn, river; SPR up to 1.5, up to 4, above): " + " ".join(f"{w:+.2f}" for w in ws))


def same_hands():
    """Ratios on the same hands (duplicate runs): much less noisy than the ratios above,
    which compare standard errors from different hands."""
    print("\nOn the same hands (duplicate runs), standard error as a share of the raw one:\n")
    print("| Comparison | Checked down | Fitted | Resampled |")
    print("|---|---|---|---|")
    cols = {"checked": [], "fitted": [], "resampled": []}
    for n in names:
        d = runs.get((n, "duplicate"))
        if d is None or d["replayed"] == 0 or not d["raw"][1]:
            continue
        cells = []
        for c in cols:
            if d[c] and d[c][1]:
                cols[c].append(d[c][1] / d["raw"][1])
                cells.append(f"{cols[c][-1]:.2f}")
            else:
                cells.append("-")
        print(f"| {n} | " + " | ".join(cells) + " |")
    gms = [f"{math.exp(sum(map(math.log, v)) / len(v)):.2f}" if v else "-" for v in cols.values()]
    print("| geometric mean | " + " | ".join(gms) + " |")


same_hands()
