"""Phase 1, exploratory: replays from where the variants part, with and without dealing the
opponents new hands from their classes (tools/hidden.live_classes, redeal), on the same hands.

    python docs/research/runs/phase1_redeal_explore.py '{"ev_sizing": true}' 1500 --table mixed --seed 303

For each hand where the variants differ, besides the original pair of plays:
  resampled      5 more pairs from the split with fresh bot numbers and board cards (run 3)
  redeal         the same, but each pair also deals the live opponents a fresh draw from their
                 classes (the hands they could hold given what they did before the split)
Each is reported raw, luck-adjusted (tools/luck.py, board cards after the split), and with
the luck of only the board cards after which nobody can bet again ("exact luck": there the
checked-down value is exact).
Every version is unbiased: given everything known at the split, each replay is a fresh draw
of the rest of the hand, opponents' cards included.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
import compare  # noqa: E402
import hidden  # noqa: E402
import luck  # noqa: E402
import simulate as sim  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("other")
    ap.add_argument("hands", type=int, nargs="?", default=1500)
    ap.add_argument("--table", default="mixed")
    ap.add_argument("--stacks", default="even")
    ap.add_argument("--seed", type=int, default=303)
    ap.add_argument("--resample", type=int, default=6)
    ap.add_argument("--save")
    a = ap.parse_args()
    other = json.loads(a.other)
    names_ = ["raw", "resampled raw", "resampled luck", "redeal raw", "redeal luck", "redeal exact luck",
              "resampled exact luck"]
    rows = {n: [] for n in names_}
    decks, cpu = [], {"resampled": 0.0, "redeal": 0.0, "classes": 0.0}
    for k in range(a.hands):
        d, r = divmod(k, 6)
        styles, names = sim.seating(a.table, a.seed, d)
        seed = a.seed * 100003 + d
        st = compare.new_stats({}, other)
        sim.play_hand(styles, d % 6, seed, 0, 100.0, st, a.stacks, names, None, k + 1, rotate=r, keyed=True)
        decks.append(d)
        if not st["diverged"]:
            for n in names_:
                rows[n].append(0.0)
            continue
        rec_a = st["last"]
        j = rec_a["diverge_at"]

        def pair(hole=None, salt=None):
            out = []
            for v in ({}, other):
                s2 = compare.new_stats(v)
                sim.play_hand(styles, d % 6, seed, 0, 100.0, s2, a.stacks, names, None, k + 1, rotate=r, keyed=True,
                              split_at=j if salt else None, resample=salt, hole_override=hole)
                out.append(s2["last"])
            return out

        orig = pair()
        t0 = time.process_time()
        classes = hidden.live_classes(rec_a, j)
        draws = hidden.redeal(classes, a.resample - 1, (seed, r, "redeal"))
        cpu["classes"] += time.process_time() - t0
        t0 = time.process_time()
        res = [orig] + [pair(salt=s) for s in range(1, a.resample)]
        cpu["resampled"] += time.process_time() - t0
        t0 = time.process_time()
        red = [orig] + [pair(hole=draws[s - 1], salt=s) for s in range(1, a.resample)]
        cpu["redeal"] += time.process_time() - t0
        after = rec_a["spots"][j]["board_len"]

        def lk(p, exact=False):
            f0, f1 = (luck.features(x, after=after, exact_only=exact) for x in p)
            return luck.adjust(p[1]["net"] - p[0]["net"], [b_ - a_ for a_, b_ in zip(f0, f1)])
        mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
        rows["raw"].append(orig[1]["net"] - orig[0]["net"])
        rows["resampled raw"].append(mean([p[1]["net"] - p[0]["net"] for p in res]))
        rows["resampled luck"].append(mean([lk(p) for p in res]))
        rows["redeal raw"].append(mean([p[1]["net"] - p[0]["net"] for p in red]))
        rows["redeal luck"].append(mean([lk(p) for p in red]))
        rows["redeal exact luck"].append(mean([lk(p, True) for p in red]))
        rows["resampled exact luck"].append(mean([lk(p, True) for p in res]))
    print(f"{a.other} on {a.table} ({a.stacks}), seed {a.seed}: {a.hands} hands, "
          f"{sum(1 for x in rows['resampled raw'] if x)} differ; CPU s: " +
          ", ".join(f"{k} {v:.0f}" for k, v in cpu.items()))
    for n in names_:
        m, se = compare.summary(rows[n], decks)
        print(f"  {n:16s} {m:+7.2f} ± {se:5.2f} bb/100")
    if a.save:
        with open(a.save, "w") as f:
            json.dump({"rows": rows, "decks": decks, "args": vars(a), "cpu": cpu}, f)


if __name__ == "__main__":
    main()
