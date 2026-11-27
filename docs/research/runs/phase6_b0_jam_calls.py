"""How often B0 calls a 100 big blind jam before the flop, against the arena's jam bot.

    python docs/research/runs/phase6_b0_jam_calls.py      # from the repo root

Heads-up, 100 big blinds, 300 deals (each twice, seats swapped), seed 610 (the jam match in
phase6_b0_arena.py). Prints B0's answers to a jam and the hands it called with.
"""
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import b0_arena  # noqa: E402
import pokerscribe_engine as pe  # noqa: E402
from app.poker import hands  # noqa: E402


class Watch(b0_arena.B0Player):
    """B0, noting its answer whenever it faces an all-in before the flop."""

    def __init__(self):
        super().__init__()
        self.facing = collections.Counter()
        self.called = collections.Counter()

    def act(self, view):
        a = super().act(view)
        if view.street == "preflop" and view.to_call > 0 and max(view.bets) >= view.starting_stacks[0]:
            what = a if isinstance(a, str) else a[0]
            self.facing[what] += 1
            if what == "call":
                self.called[hands.preflop_class(tuple(view.hole))] += 1
        return a


w = Watch()
pe.run_match([w, "jam"], 300, 610, stack=10_000, small_blind=50, big_blind=100)
n = sum(w.facing.values())
print(f"B0 faced {n} jams before the flop: {dict(w.facing)}; called {100 * w.facing['call'] / n:.1f}%")
print("called with:", ", ".join(f"{k} x{v}" for k, v in w.called.most_common()))
