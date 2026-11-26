"""Phase 1 check: do the replays from the split keep the hand's expected value?

    python docs/research/runs/phase1_replay_check.py arms '<base json>' '<other json>' <table> <seed> <hands> <out.json>
    python docs/research/runs/phase1_replay_check.py test '<glob of arms files>'

arms: plays a duplicate comparison like tools/compare.py and, for every hand where the variants
differ, replays it from the split with salts 1 to 5 (both variants each time) in three arms: the
bots' real hands (as compare.py does without --redeal), and two fresh draws from their classes
(tools/hidden.redeal, key (hand seed, rotation, "arms")). It also keeps the original pair.

test: if the redeal draws from the right hands, the three arms are exchangeable, so which one is
the real one is random. The statistic is the sum over hands of the real arm's mean difference
minus the mean of the two redealt arms; p is the share of 10000 random relabellings (per hand)
at or above it.
"""
import glob
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import compare  # noqa: E402
import hidden  # noqa: E402
import simulate as sim  # noqa: E402


def arms(base, other, table, seed, n, out_path):
    rows = []
    t0 = time.time()
    for k in range(n):
        sim.clear_advice_cache()
        d, r = compare.deal(k, "duplicate")
        styles, names = sim.seating(table, seed, d)
        hs = seed * 100003 + d
        sa, sb = compare.new_stats(base, other), compare.new_stats(other)
        sim.play_hand(styles, d % 6, hs, 0, 100.0, sa, "even", names, None, k + 1, rotate=r, keyed=True)
        if not sa["diverged"]:
            continue
        rec = sa["last"]
        sim.play_hand(styles, d % 6, hs, 0, 100.0, sb, "even", names, None, k + 1, rotate=r, keyed=True)
        j = rec["diverge_at"]
        classes = hidden.live_classes(rec, j)
        row = {"k": k, "deck": d, "street": rec["spots"][j]["board_len"], "live": len(rec["spots"][j]["live"]),
               "orig": [rec["net"], sb["last"]["net"]], "arms": []}
        for over in [None] + hidden.redeal(classes, 2, (hs, r, "arms")):
            plays = []
            for salt in range(1, 6):
                nets = []
                for v in (base, other):
                    st = compare.new_stats(v)
                    sim.play_hand(styles, d % 6, hs, 0, 100.0, st, "even", names, None, k + 1, rotate=r,
                                  keyed=True, split_at=j, resample=salt, hole_override=over)
                    nets.append(st["last"]["net"])
                plays.append(nets)
            row["arms"].append(plays)
        rows.append(row)
    with open(out_path, "w") as f:
        json.dump({"base": base, "other": other, "table": table, "seed": seed, "n": n, "rows": rows,
                   "seconds": time.time() - t0}, f)


def test(pattern):
    files = sorted(glob.glob(pattern))
    data = [json.load(open(p)) for p in files]
    rows = [r for d in data for r in d["rows"]]
    hands_played = sum(d["n"] for d in data)
    means = [[sum(o - b for b, o in arm) / len(arm) for arm in r["arms"]] for r in rows]

    def stat(pick):
        return sum(m[i] - (sum(m) - m[i]) / 2 for m, i in zip(means, pick))

    obs = stat([0] * len(means))
    rng = random.Random(11)
    null = [stat([rng.randrange(3) for _ in means]) for _ in range(10000)]
    p = sum(1 for x in null if x >= obs) / len(null)
    sd = math.sqrt(sum(x * x for x in null) / len(null))
    orig = [r["orig"][1] - r["orig"][0] for r in rows]
    real = [m[0] for m in means]
    red = [sum(m[1:]) / 2 for m in means]
    per100 = 100.0 / hands_played
    print(f"{len(files)} seeds, {hands_played} hands, {len(rows)} differ")
    print(f"real arm minus redealt arms: {obs:+.1f} bb ({obs * per100:+.2f} bb/100), z {obs / sd:+.2f}, "
          f"exact one-sided p {p:.4f}")
    print(f"means in bb/100: original {sum(orig) * per100:+.2f}, real arm {sum(real) * per100:+.2f}, "
          f"redealt arms {sum(red) * per100:+.2f}")


if __name__ == "__main__":
    if sys.argv[1] == "arms":
        arms(json.loads(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4], int(sys.argv[5]), int(sys.argv[6]),
             sys.argv[7])
    else:
        test(sys.argv[2])
