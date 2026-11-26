"""Replay s with the real hands against replay s with redealt hands (same salt): if the redeal draws
from the right hands, the two are exchangeable, so their difference is symmetric around 0."""
import json, glob, math, random, sys
rows = [r for p in sorted(glob.glob(sys.argv[1])) for r in json.load(open(p))["rows"]]
for s in range(5):
    x = [(r["plain"][s][1] - r["plain"][s][0]) - (r["redeal"][s][1] - r["redeal"][s][0]) for r in rows]
    nz = [v for v in x if v != 0]
    pos = sum(1 for v in nz if v > 0)
    z = (pos - len(nz) / 2) / math.sqrt(len(nz) / 4)
    obs = sum(x)
    rng = random.Random(s)
    null = [sum(v if rng.random() < 0.5 else -v for v in nz) for _ in range(4000)]
    p_hi = sum(1 for t in null if t >= obs) / 4000
    print(f"salt {s+1}: sum {obs:+8.1f} bb, share of sign-flip null at or above {p_hi:.4f}; signs +{pos}/-{len(nz)-pos} (z {z:+.2f})")
