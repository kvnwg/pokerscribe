"""Permutation test: if the original deal is exchangeable with its replays, picking at random
which of the six plays counts as the original gives the null distribution of the gap."""
import json, glob, random, sys
for kind in ("plain", "redeal"):
    plays = []
    for p in sorted(glob.glob(sys.argv[1])):
        for r in json.load(open(p))["rows"]:
            plays.append([r["orig"][1] - r["orig"][0]] + [o - b for b, o in r[kind]])
    def gap(pick):
        return sum((sum(v) - v[i]) / 5 - v[i] for v, i in zip(plays, pick))
    obs = gap([0] * len(plays))
    rng = random.Random(1)
    null = sorted(gap([rng.randrange(6) for _ in plays]) for _ in range(4000))
    lo = sum(1 for x in null if x <= obs) / len(null)
    print(f"{kind:6s} hands {len(plays)} observed gap {obs:+8.1f} bb; null 2.5%..97.5%: {null[100]:+.1f} .. {null[3899]:+.1f};"
          f" share of null at or below observed: {lo:.4f}")
