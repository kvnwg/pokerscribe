"""Compare two strategy variants on exactly the same hands (paired simulation).

    python tools/compare.py '{"pot_control": 0.08}' [hands] [--tables mixed,stations,maniacs,fish247]
    python tools/compare.py '{}' 2000 --base '{"texture_sizing": true}'
    python tools/compare.py '{"bully": true}' 1000 --stacks uneven

Each hand is dealt from a seed, and the bots' choices come from a seed too, so both
variants see the same cards and the same opponents. The hand is played with the base
variant; at each of the app's decisions the other variant is asked as well. If they
never disagree the result is the same and the hand counts as a difference of zero; if
they do, the hand is replayed with the other variant from the start. The win-rate
difference and its standard error come from these per-hand differences, which removes
most of the luck of the cards from the comparison.

Variants are overrides of app.poker.advice.TUNING, given as JSON.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulate as sim  # noqa: E402


def new_stats(variant=None, shadow=None) -> dict:
    return {"hands": [], "by_pos": defaultdict(list), "by_street": defaultdict(list), "all_in": [],
            "preflop_first": defaultdict(int), "advice": defaultdict(int), "problems": defaultdict(int),
            "examples": [], "variant": variant, "shadow": shadow}


def paired(base: dict, other: dict, n: int, table: str, seed: int, depth_bb: float = 100.0, stacks: str = "even",
           profiles: bool = False):
    """With profiles, the app learns the bots' styles from the hands as in watch mode. They are
    learned from the base variant's hands; a replayed hand starts from the same profiles."""
    sa, sb = new_stats(base, other), new_stats(other)
    diffs, replayed = [], 0
    prof = sim.new_profiles() if profiles else None
    sa["profiles"] = prof
    for k in range(n):
        styles, names = sim.seating(table, seed, k)
        hand_seed = seed * 100003 + k
        before = copy.deepcopy(prof) if prof is not None else None
        net_a = sim.play_hand(styles, k % 6, hand_seed, 0, depth_bb, sa, stacks, names, prof, k + 1)[0] / sim.BB
        if sa["diverged"]:
            replayed += 1
            net_b = sim.play_hand(styles, k % 6, hand_seed, 0, depth_bb, sb, stacks, names, before, k + 1)[0] / sim.BB
        else:
            net_b = net_a
            sb["hands"].append(net_b)
        diffs.append(net_b - net_a)
    return sa, sb, diffs, replayed


def summary(values):
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in values) / max(1, n - 1))
    return 100 * mean, 100 * sd / math.sqrt(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("other", help="JSON overrides of advice.TUNING to compare against the base")
    ap.add_argument("hands", nargs="?", type=int, default=1000)
    ap.add_argument("--base", default="{}", help="JSON overrides for the base variant")
    ap.add_argument("--tables", default="mixed,stations,maniacs,fish247")
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--stacks", default="even", choices=["even"] + sorted(sim.STACKS))
    ap.add_argument("--profiles", action="store_true", help="the app learns the bots' styles as it plays")
    ap.add_argument("--short-raise", action="store_true", help="short bots raise small instead of moving all in")
    a = ap.parse_args()
    sim.SHORT_RAISE = a.short_raise
    base, other = json.loads(a.base), json.loads(a.other)
    total = []
    t0 = time.time()
    for table in a.tables.split(","):
        sa, sb, diffs, replayed = paired(base, other, a.hands, table, a.seed, 500.0 if a.deep else 100.0, a.stacks,
                                         a.profiles)
        wa, ea = summary(sa["hands"])
        wb, eb = summary(sb["hands"])
        d, de = summary(diffs)
        total += diffs
        probs = dict(sa["problems"]) or "none"
        print(f"{table:9s} base {wa:+7.1f} (±{ea:5.1f})  other {wb:+7.1f} (±{eb:5.1f})  "
              f"difference {d:+6.1f} ± {de:4.1f} bb/100  [{replayed}/{a.hands} hands differ, problems {probs}]",
              flush=True)
        if sa.get("profiles") is not None:
            print("          styles learned: " + sim.profile_report(sa["profiles"], table), flush=True)
    d, de = summary(total)
    print(f"ALL       difference {d:+6.1f} ± {de:4.1f} bb/100 over {len(total)} hands ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
