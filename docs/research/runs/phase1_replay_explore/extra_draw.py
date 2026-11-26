"""For each hand that differs (from a replays.py file): replay one extra redealt hand Y* with the
same 5 salts as the real-card replays, and (control) the real hands passed through hole_override."""
import json, sys, time
import os; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import simulate as sim, compare, hidden

src, out_path = sys.argv[1], sys.argv[2]
d = json.load(open(src))
base, other, table, seed = d["base"], d["other"], d["table"], d["seed"]
rows = []
t0 = time.time()
for r in d["rows"]:
    k = r["k"]
    dk, rot = compare.deal(k, "duplicate")
    styles, names = sim.seating(table, seed, dk)
    hs = seed * 100003 + dk
    sim.clear_advice_cache()
    sa = compare.new_stats(base, other)
    sim.play_hand(styles, dk % 6, hs, 0, 100.0, sa, "even", names, None, k + 1, rotate=rot, keyed=True)
    rec = sa["last"]; j = rec["diverge_at"]
    assert j == r["j"]
    classes = hidden.live_classes(rec, j)
    ystar = hidden.redeal(classes, 1, (hs, rot, "ystar"))[0]
    real = {i: tuple(rec["cards"][i]) for i in classes}
    row = {"k": k, "deck": r["deck"], "street": r["street"], "live": r["live"], "plain": r["plain"],
           "same_as_real": ystar == real}
    for name, over, salts in (("ystar", ystar, range(1, 6)), ("control", real, range(1, 3))):
        plays = []
        for salt in salts:
            nets = []
            for v in (base, other):
                st = compare.new_stats(v)
                sim.play_hand(styles, dk % 6, hs, 0, 100.0, st, "even", names, None, k + 1, rotate=rot, keyed=True,
                              split_at=j, resample=salt, hole_override=over)
                nets.append(st["last"]["net"])
            plays.append(nets)
        row[name] = plays
    rows.append(row)
json.dump({"seed": seed, "rows": rows, "seconds": time.time() - t0}, open(out_path, "w"))
