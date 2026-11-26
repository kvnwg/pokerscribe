"""For each live bot, its first decision after the split in each variant (same random numbers):
how often the real hand answers the two bets differently, against the share of its class that does."""
import glob, json, math, random, sys
from collections import defaultdict
import os; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import simulate as sim, compare, hidden
from app.poker.ranges import preflop_percentile

def first_after(rec, j, i):
    e0 = hidden.split_event(rec, j)
    for kind, idx in rec["events"][e0 + 1:]:
        if kind == "bot" and rec["bot_decisions"][idx]["i"] == i:
            return rec["bot_decisions"][idx]
    return None

res = defaultdict(list)
for path in sorted(glob.glob(sys.argv[1])):
    d = json.load(open(path))
    base, other, table, seed = d["base"], d["other"], d["table"], d["seed"]
    for r in d["rows"]:
        k = r["k"]
        dk, rot = compare.deal(k, "duplicate")
        styles, names = sim.seating(table, seed, dk)
        hs = seed * 100003 + dk
        sim.clear_advice_cache()
        sa, sb = compare.new_stats(base, other), compare.new_stats(other)
        sim.play_hand(styles, dk % 6, hs, 0, 100.0, sa, "even", names, None, k + 1, rotate=rot, keyed=True)
        sim.play_hand(styles, dk % 6, hs, 0, 100.0, sb, "even", names, None, k + 1, rotate=rot, keyed=True)
        ra, rb = sa["last"], sb["last"]; j = ra["diverge_at"]
        classes = hidden.live_classes(ra, j)
        for i, cls in classes.items():
            sna, snb = first_after(ra, j, i), first_after(rb, j, i)
            if sna is None or snb is None:
                continue
            others = [c for b, c in classes.items() if b != i]
            w = [sum(1 for z in others[0] if not set(z) & set(y)) if len(others) == 1 else 1 for y in cls]
            tot = sum(w)
            def resp(y):
                return (hidden.category(sna, hidden.bot_move(ra, sna, y)), hidden.category(snb, hidden.bot_move(rb, snb, y)))
            actual = tuple(ra["cards"][i])
            ra_ = resp(actual)
            assert ra_ == (hidden.category(sna), hidden.category(snb)), (k, i, ra_)
            share = defaultdict(float)
            for y, wt in zip(cls, w):
                share[resp(y)] += wt / tot
            grp = "heads-up" if len(classes) == 1 else "multiway"
            for key in set(share) | {ra_}:
                res[(grp, key)].append(((1.0 if key == ra_ else 0.0) - share.get(key, 0.0), (seed, dk)))
                res[("all", key)].append(((1.0 if key == ra_ else 0.0) - share.get(key, 0.0), (seed, dk)))

def clustered(values, units):
    sums, sizes = defaultdict(float), defaultdict(int)
    for v, u in zip(values, units):
        sums[u] += v; sizes[u] += 1
    n = sum(sizes.values()); g = len(sums); m = sum(sums.values()) / n
    ss = sum((sums[u] - sizes[u] * m) ** 2 for u in sums)
    return m, math.sqrt(ss * g / (g - 1)) / n if g > 1 else float("nan")

for key in sorted(res, key=lambda k: (k[0], -len(res[k]))):
    vals = [v for v, _ in res[key]]; units = [u for _, u in res[key]]
    if len(vals) < 20:
        continue
    m, se = clustered(vals, units)
    hits = sum(1 for v in vals if v > 0)
    expected = sum(v for v in vals if v <= 0) * -1 + sum(1 - v for v in vals if v > 0)
    print(f"{key[0]:9s} base {key[1][0]:5s} / other {key[1][1]:5s}: real hands {hits:4d}, class shares add to {expected:7.1f}  "
          f"(per bot {m:+.4f} ± {se:.4f}, {m/se:+.2f} SE)  n={len(vals)}")
