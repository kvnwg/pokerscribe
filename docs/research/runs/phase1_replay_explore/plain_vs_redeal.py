import json, math, glob, sys
from collections import defaultdict
def clustered(values, units):
    sums, sizes = defaultdict(float), defaultdict(int)
    for v, u in zip(values, units):
        sums[u] += v; sizes[u] += 1
    n = sum(sizes.values()); g = len(sums); m = sum(sums.values()) / n
    ss = sum((sums[u] - sizes[u] * m) ** 2 for u in sums)
    return m, math.sqrt(ss * g / (g - 1)) / n
v, u = defaultdict(list), defaultdict(list)
for p in sorted(glob.glob(sys.argv[1])):
    d = json.load(open(p))
    for r in d["rows"]:
        pl = sum(o - b for b, o in r["plain"]) / 5; rd = sum(o - b for b, o in r["redeal"]) / 5
        key = (d["seed"], r["deck"])
        for name in ("all", f"street {r['street']}", f"{r['live']} players"):
            v[name].append(pl - rd); u[name].append(key)
for name in sorted(v):
    m, se = clustered(v[name], u[name])
    pos = sum(1 for x in v[name] if x > 0); neg = sum(1 for x in v[name] if x < 0)
    print(f"plain - redeal {name:10s} {m:+7.3f} ± {se:6.3f} bb per hand ({m/se:+.2f} SE)  n={len(v[name])}  +{pos}/-{neg}")
