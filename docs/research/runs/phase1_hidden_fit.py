"""Cross-validation of the hidden-cards weights by seed: fit on one seed's training files,
report standard errors on the other seed's (and the other way round).

    python docs/research/runs/phase1_hidden_fit.py <folder with *_<seed>.json files> 303 404
"""
import glob
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
import hidden  # noqa: E402
from compare import summary  # noqa: E402

folder, seeds = sys.argv[1], sys.argv[2:]
files = {s: sorted(glob.glob(os.path.join(folder, f"*_{s}.json"))) for s in seeds}
ratios = {"resampled": [], "base": [], "fitted": []}
for test in seeds:
    train = [f for s in seeds if s != test for f in files[s]]
    w = hidden.fit_weights(hidden.load_rows(train))
    print(f"fitted on {', '.join(s for s in seeds if s != test)}, checked on {test}:")
    for path in files[test]:
        rows = hidden.load_rows([path])
        decks = [r["deck"] for r in rows]
        raw = summary([r["raw"] for r in rows], decks)[1]
        se = {"resampled": summary([r["resampled"] for r in rows], decks)[1],
              "base": summary([r["base"] for r in rows], decks)[1],
              "fitted": summary(hidden.apply_weights(rows, w), decks)[1]}
        if raw:
            for k, v in se.items():
                ratios[k].append(v / raw)
        print(f"   {os.path.basename(path):22s} raw {raw:5.2f}  " + "  ".join(f"{k} {v:5.2f}" for k, v in se.items()))
print("geometric mean of SE / raw SE, out of sample: " +
      ", ".join(f"{k} {math.exp(sum(map(math.log, v)) / len(v)):.2f}" for k, v in ratios.items() if v))
