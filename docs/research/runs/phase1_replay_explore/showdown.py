"""Does the live bots' real hand beat the app's on the original deal's full board as often as its
class predicts (class members not using a board card, weighted by the other bots' compatible hands)?"""
import glob, json, math, sys
from collections import defaultdict
import os; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import simulate as sim, compare, hidden
from app.poker import hands

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
        sa = compare.new_stats(base, other)
        sim.play_hand(styles, dk % 6, hs, 0, 100.0, sa, "even", names, None, k + 1, rotate=rot, keyed=True)
        rec = sa["last"]; j = rec["diverge_at"]
        board = tuple(rec["board"])  # the deck's five board cards, dealt or not
        me = rec["me"]
        app_rank = hands.evaluate(rec["cards"][me], list(board))
        classes = hidden.live_classes(rec, j)
        for i, cls in classes.items():
            others = [c for b, c in classes.items() if b != i]
            ok = [y for y in cls if not set(y) & set(board)]
            if len(others) == 1:
                o2 = [z for z in others[0] if not set(z) & set(board)]
                w = [sum(1 for z in o2 if not set(z) & set(y)) for y in ok]
            else:
                w = [1] * len(ok)
            tot = sum(w)
            if not tot:
                continue
            share_win = sum(wt for y, wt in zip(ok, w) if hands.evaluate(y, list(board)) < app_rank) / tot
            share_tie = sum(wt for y, wt in zip(ok, w) if hands.evaluate(y, list(board)) == app_rank) / tot
            real = hands.evaluate(rec["cards"][i], list(board))
            win = 1.0 if real < app_rank else 0.0
            grp = "heads-up" if len(classes) == 1 else "multiway"
            street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[rec["spots"][j]["board_len"]]
            for g in ("all", grp, street):
                res[g].append((win, share_win, (seed, dk)))

def clustered(values, units):
    sums, sizes = defaultdict(float), defaultdict(int)
    for v, u in zip(values, units):
        sums[u] += v; sizes[u] += 1
    n = sum(sizes.values()); g = len(sums); m = sum(sums.values()) / n
    ss = sum((sums[u] - sizes[u] * m) ** 2 for u in sums)
    return m, math.sqrt(ss * g / (g - 1)) / n

for g in sorted(res):
    wins = sum(x[0] for x in res[g]); exp = sum(x[1] for x in res[g])
    m, se = clustered([x[0] - x[1] for x in res[g]], [x[2] for x in res[g]])
    print(f"{g:9s} bots {len(res[g]):4d}: real hand beats the app {wins:4.0f} times, class predicts {exp:6.1f}  ({m/se:+.2f} SE)")
