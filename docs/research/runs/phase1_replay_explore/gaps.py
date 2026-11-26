"""Is the original deal exchangeable with its replays? Gaps, rank tests and tail rates."""
import glob, json, math, sys
from collections import defaultdict

def clustered(values, units):
    sums, sizes = defaultdict(float), defaultdict(int)
    for v, u in zip(values, units):
        sums[u] += v; sizes[u] += 1
    n = sum(sizes.values()); g = len(sums); m = sum(sums.values()) / n
    ss = sum((sums[u] - sizes[u] * m) ** 2 for u in sums)
    return m, math.sqrt(ss * g / (g - 1)) / n

def midrank(x, others):
    below = sum(1 for o in others if o < x); ties = sum(1 for o in others if o == x)
    return 1 + below + ties / 2  # 1..6, mean 3.5 if exchangeable

files = sorted(glob.glob(sys.argv[1]))
pooled = defaultdict(lambda: ([], []))
for path in files:
    d = json.load(open(path)); n = d["n"]; seed = d["seed"]
    rows = d["rows"]
    bad = [r["k"] for r in rows if not (r["same_pre_b"] and r["same_pre_plain"] and r["same_pre_redeal"] and r["in_class"])]
    per = defaultdict(lambda: ([], []))
    for r in rows:
        u = (seed, r["deck"])
        d0 = r["orig"][1] - r["orig"][0]
        for kind in ("plain", "redeal"):
            ds = [o - b for b, o in r[kind]]
            gap = sum(ds) / len(ds) - d0
            per["gap_" + kind][0].append(gap); per["gap_" + kind][1].append(u)
            per["rank_" + kind][0].append(midrank(d0, ds) - 3.5); per["rank_" + kind][1].append(u)
            for v, idx in (("base", 0), ("other", 1)):
                xs = [p[idx] for p in r[kind]]
                per[f"rank_{kind}_{v}"][0].append(midrank(r["orig"][idx], xs) - 3.5); per[f"rank_{kind}_{v}"][1].append(u)
                per[f"gap_{kind}_{v}"][0].append(sum(xs) / len(xs) - r["orig"][idx]); per[f"gap_{kind}_{v}"][1].append(u)
    print(f"{path.split('/')[-1]}: {len(rows)} hands differ of {n}, {d['seconds']:.0f}s, inconsistent: {bad[:10]}")
    for key, (vals, units) in sorted(per.items()):
        pooled[key][0].extend(vals); pooled[key][1].extend(units)
        if key.startswith("gap_") and key.count("_") == 1:
            # per 100 hands of the run (non-differing hands add 0)
            vals_all = vals + [0.0] * (n - len(vals)); units_all = units + [(seed, ("x", i)) for i in range(n - len(vals))]
            m, se = clustered(vals_all, units_all)
            print(f"   {key:22s} {100*m:+7.2f} ± {100*se:5.2f} bb/100 ({m/se:+.2f} SE)")
print("pooled over files (differing hands only):")
for key, (vals, units) in sorted(pooled.items()):
    m, se = clustered(vals, units)
    print(f"   {key:22s} mean {m:+7.3f} ± {se:6.3f} ({m/se:+.2f} SE)  n={len(vals)}")
# tails
for path in files:
    pass
allrows = [r for p in files for r in json.load(open(p))["rows"]]
def tail(xs, t): return sum(1 for x in xs if x > t), sum(1 for x in xs if x < -t), len(xs)
for t in (20, 40, 60):
    o = tail([r["orig"][1] - r["orig"][0] for r in allrows], t)
    p = tail([b2 - b1 for r in allrows for b1, b2 in r["plain"]], t)
    q = tail([b2 - b1 for r in allrows for b1, b2 in r["redeal"]], t)
    print(f"|diff| > {t}: orig +{o[0]}/-{o[1]} of {o[2]} ({100*o[0]/o[2]:.1f}% / {100*o[1]/o[2]:.1f}%); plain +{p[0]}/-{p[1]} of {p[2]} ({100*p[0]/p[2]:.1f}% / {100*p[1]/p[2]:.1f}%); redeal +{q[0]}/-{q[1]} of {q[2]} ({100*q[0]/q[2]:.1f}% / {100*q[1]/q[2]:.1f}%)")
