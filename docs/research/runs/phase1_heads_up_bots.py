"""How the bots play heads-up before the flop: each bot's first decision of the hand, as the
button first in (against the big blind) and in the big blind facing an open raise.

    python docs/research/runs/phase1_heads_up_bots.py [hands] [table] [seed]   (default 2500 mixed 3)

Output of the default: phase1_heads_up_b0/bots.txt.
"""
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import simulate as sim  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 2500
table = sys.argv[2] if len(sys.argv) > 2 else "mixed"
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 3
counts = defaultdict(Counter)
_play = sim.play_hand


def play(*a, **k):
    net = _play(*a, **k)
    rec = (a[5] if len(a) > 5 else k["stats"])["last"]
    seen = set()
    for snap in rec["bot_decisions"]:
        if snap["board"] or snap["i"] in seen:
            continue
        seen.add(snap["i"])  # the bot's first decision of the hand
        style = rec["seats"][snap["i"]][0]
        if snap["bet"] == sim.BB and snap["current"] > sim.BB:
            counts[(style, "big blind facing an open")][snap["action"][0]] += 1
        elif snap["bet"] == sim.SB:
            counts[(style, "button, first in")][snap["action"][0]] += 1
    return net


sim.play_hand = play
sim.run(n, table, seed, quiet=True, players=2)
print(f"heads-up, {table}, {n} hands, seed {seed}")
for (style, kind), c in sorted(counts.items()):
    total = sum(c.values())
    print(f"{style:8s} {kind:25s} {total:4d} decisions: "
          + ", ".join(f"{a} {100 * v / total:.0f}%" for a, v in sorted(c.items())))
