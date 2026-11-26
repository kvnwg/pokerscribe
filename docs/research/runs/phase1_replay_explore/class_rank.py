"""Where does each live bot's real hand fall within its class? Uniform if the redeal is right."""
import glob, json, math, random, sys
from collections import defaultdict
import os; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import simulate as sim, compare, hidden
from app.poker import hands
from app.poker.ranges import preflop_percentile

def pit(x, xs, rng):
    below = sum(1 for v in xs if v < x); ties = sum(1 for v in xs if v == x)
    return (below + rng.random() * ties) / len(xs)  # uniform on [0, 1] if x is a uniform draw from xs

out = defaultdict(list)
rng = random.Random(7)
for path in sorted(glob.glob(sys.argv[1])):
    d = json.load(open(path))
    base, other, table, seed = d["base"], d["other"], d["table"], d["seed"]
    for r in d["rows"]:
        k = r["k"]
        dk, rot = compare.deal(k, "duplicate")
        styles, names = sim.seating(table, seed, dk)
        hand_seed = seed * 100003 + dk
        sim.clear_advice_cache()
        sa = compare.new_stats(base, other)
        sim.play_hand(styles, dk % 6, hand_seed, 0, 100.0, sa, "even", names, None, k + 1, rotate=rot, keyed=True)
        rec = sa["last"]; j = rec["diverge_at"]
        board = list(rec["board"][:rec["spots"][j]["board_len"]])
        classes = hidden.live_classes(rec, j)
        for i, cls in classes.items():
            actual = tuple(rec["cards"][i])
            if len(classes) > 1:  # marginal weight: how many hands the other bots could hold alongside
                others = [c for b, c in classes.items() if b != i]
                w = [sum(1 for z in others[0] if not set(z) & set(y)) if len(others) == 1 else 1 for y in cls]
            else:
                w = [1] * len(cls)
            stats = {"preflop": lambda y: -preflop_percentile(hands.preflop_class(y)),
                     "strength": (lambda y: sim.strength(y, board)) if board else None}
            for name, f in stats.items():
                if f is None:
                    continue
                vals = [(f(y), wt) for y, wt in zip(cls, w)]
                x = f(actual)
                tot = sum(wt for _, wt in vals)
                below = sum(wt for v, wt in vals if v < x); ties = sum(wt for v, wt in vals if v == x)
                u = (below + rng.random() * ties) / tot
                out[(name, "heads-up" if len(classes) == 1 else "multiway")].append((u, (seed, dk)))
                out[(name, "all")].append((u, (seed, dk)))

def clustered(values, units):
    sums, sizes = defaultdict(float), defaultdict(int)
    for v, u in zip(values, units):
        sums[u] += v; sizes[u] += 1
    n = sum(sizes.values()); g = len(sums); m = sum(sums.values()) / n
    ss = sum((sums[u] - sizes[u] * m) ** 2 for u in sums)
    return m, math.sqrt(ss * g / (g - 1)) / n

for key in sorted(out):
    us = [u for u, _ in out[key]]; units = [x for _, x in out[key]]
    m, se = clustered(us, units)
    q = [sum(1 for u in us if lo <= u < lo + 0.2) for lo in (0, 0.2, 0.4, 0.6, 0.8)]
    print(f"{key[0]:9s} {key[1]:9s} n={len(us):4d} mean {m:.3f} ± {se:.3f} ({(m - 0.5)/se:+.2f} SE vs 0.5)  fifths {q}")
