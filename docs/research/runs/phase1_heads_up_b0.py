"""B0 heads-up (and six-max, for comparison): instructions that are wrong whatever the strategy.

    python docs/research/runs/phase1_heads_up_b0.py players table stacks hands seed [deep] [profiles]

simulate.check_advice's checks plus a few more ("extra"), counted with examples. Run as it is
here on 26 Nov 2026 (phase1_heads_up_b0.sh); afterwards the extra checks except the last one
moved into simulate.check_advice, so a rerun counts them twice (as problems and as extra).
"""
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import simulate as sim  # noqa: E402
from app.poker import hands  # noqa: E402

players, table, stacks, n, seed = int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
deep = "deep" in sys.argv[6:]
profiles = "profiles" in sys.argv[6:]
extra = Counter()
examples = defaultdict(list)
orig = sim.check_advice


def check(h, me, adv, stats):
    orig(h, me, adv, stats)
    seat = h.seats[me]
    to_call = h.current - seat.bet
    total = seat.stack + seat.bet
    cls = hands.preflop_class(seat.cards)
    found = []
    if adv.action == "call" and to_call <= 1e-9:
        found.append("call with nothing to call")
    if adv.action == "check" and to_call > 1e-9:
        found.append("check facing a bet")
    if adv.action in ("bet", "raise") and adv.amount is not None:
        legal = min(total, h.current + h.min_raise)
        if adv.amount < legal - 1e-9:
            found.append("below the minimum bet or raise")
        if adv.amount > total + 1e-9:
            found.append("more than the stack")
    if adv.action == "fold" and not h.board and cls in ("AA", "KK"):
        found.append(f"folded {cls} before the flop")
    if adv.action == "all-in" and adv.amount is not None and abs(adv.amount - total) > 1e-6 and not adv.headline.startswith("CALL"):
        found.append("all in for the wrong amount")
    words = adv.reason + " " + adv.headline
    pos = h.position(me)
    if pos == "BTN/SB" and ("small blind" in adv.reason.lower() and "button" not in adv.reason.lower()):
        found.append("calls the heads-up button the small blind only")
    for f in found:
        extra[f] += 1
        if len(examples[f]) < 6:
            examples[f].append((cls, " ".join(h.board), pos, round(to_call, 1), round(h.pot, 1), round(h.current, 1),
                                round(h.min_raise, 1), adv.headline, adv.reason[:140]))


sim.check_advice = check
st = sim.run(n, table, seed, quiet=True, stacks=stacks, depth_bb=500.0 if deep else 100.0, profiles=profiles,
             players=players)
first = st["preflop_first"]
by_pos = {}
for pos in sorted({p for p, _ in first}):
    tot = sum(v for (p, _), v in first.items() if p == pos)
    by_pos[pos] = {k: round(v / tot, 3) for (p, k), v in first.items() if p == pos}
r = st["hands"]
out = {"config": sys.argv[1:], "hands": len(r), "bb100": 100 * sum(r) / len(r), "problems": dict(st["problems"]),
       "problem_examples": st["examples"][:8], "extra": dict(extra), "extra_examples": dict(examples),
       "decisions": sum(st["advice"].values()), "preflop_first": by_pos,
       "advice": {f"{k[0]}/{k[1]}": v for k, v in sorted(st["advice"].items())}}
print(json.dumps(out, default=str))
