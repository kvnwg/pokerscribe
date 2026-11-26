"""Table of the redeal exploration (phase1_redeal_explore.py): each estimator's standard error
as a share of the raw one, on the same hands, per comparison and seed.

    python docs/research/runs/phase1_redeal_summary.py <folder>
"""
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from compare import summary  # noqa: E402

folder = sys.argv[1]
cols = ["resampled raw", "resampled luck", "resampled exact luck", "redeal raw", "redeal luck", "redeal exact luck"]
ratios = {c: [] for c in cols}
print("| Comparison | Seed | Raw SE | " + " | ".join(cols) + " |")
print("|---|---|---|" + "---|" * len(cols))
for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
    d = json.load(open(path))
    rows, decks = d["rows"], d["decks"]
    raw = summary(rows["raw"], decks)[1]
    cells = []
    for c in cols:
        se = summary(rows[c], decks)[1]
        if raw:
            ratios[c].append(se / raw)
        cells.append(f"{se / raw:.2f}" if raw else "-")
    name = os.path.basename(path)[:-5]
    print(f"| {name.rsplit('_', 1)[0]} | {name.rsplit('_', 1)[1]} | {raw:.2f} | " + " | ".join(cells) + " |")
gm = {c: math.exp(sum(map(math.log, v)) / len(v)) for c, v in ratios.items() if v}
print("| geometric mean | | | " + " | ".join(f"{gm[c]:.2f}" for c in cols) + " |")
print("| largest | | | " + " | ".join(f"{max(ratios[c]):.2f}" for c in cols) + " |")
