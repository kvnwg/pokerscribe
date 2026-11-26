import glob, json, math, random, sys
from collections import defaultdict
def clustered(values, units):
    sums, sizes = defaultdict(float), defaultdict(int)
    for v, u in zip(values, units):
        sums[u] += v; sizes[u] += 1
    n = sum(sizes.values()); g = len(sums); m = sum(sums.values()) / n
    ss = sum((sums[u] - sizes[u] * m) ** 2 for u in sums)
    return m, math.sqrt(ss * g / (g - 1)) / n
for pat in sys.argv[1:]:
    T, U, bad = [], [], 0
    for p in sorted(glob.glob(pat)):
        d = json.load(open(p))
        for r in d["rows"]:
            for s in range(2):
                if r["control"][s] != r["plain"][s]:
                    bad += 1
            pl = sum(o - b for b, o in r["plain"]) / 5
            ys = sum(o - b for b, o in r["ystar"]) / 5
            T.append(pl - ys); U.append((d["seed"], r["deck"]))
    m, se = clustered(T, U)
    obs = sum(T)
    rng = random.Random(3)
    null = [sum(t if rng.random() < 0.5 else -t for t in T) for _ in range(10000)]
    p_hi = sum(1 for x in null if x >= obs) / len(null)
    p_two = sum(1 for x in null if abs(x) >= abs(obs)) / len(null)
    pos = sum(1 for t in T if t > 0); neg = sum(1 for t in T if t < 0)
    print(f"{pat.split('/')[-1]}: hands {len(T)}, control mismatches {bad}; real-card minus extra-draw replays "
          f"{m:+.3f} ± {se:.3f} bb per hand ({m/se:+.2f} SE); exact sign-flip p one-sided {p_hi:.4f}, two-sided {p_two:.4f}; signs +{pos}/-{neg}")
