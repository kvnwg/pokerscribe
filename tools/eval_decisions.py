"""Decision-quality benchmark for the call-or-fold verdict.

Plays random heads-up spots where calling ends the betting (river calls and
all-ins on the turn, flop and preflop), lets the app decide exactly as it would in
use (same equity code, same time budget), and measures the chips it gives up
against the true best decision, computed with exact enumeration (river, turn,
flop) or a very long simulation (preflop).

    python tools/eval_decisions.py [spots_per_street]
"""
import os
import random
import sys
import time
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from treys import Evaluator  # noqa: E402

from app.poker.decision import call_or_fold, ev_of_call  # noqa: E402
from app.poker.equity import equity  # noqa: E402
from app.poker.hands import DECK, to_int  # noqa: E402
from app.poker.ranges import make_range  # noqa: E402

EV = Evaluator()
RANGE_KEYS = ["any", "loose", "medium", "tight", "very_tight"]


def exact_equity(hero, board, combos):
    """Exact heads-up equity for any street from the flop on."""
    dead = set(hero) | set(board)
    hero_i = [to_int(c) for c in hero]
    board_i = [to_int(c) for c in board]
    if combos is None:
        rest = [c for c in DECK if c not in dead]
        combos = list(combinations(rest, 2))
    total = count = 0.0
    for a, b in combos:
        if a in dead or b in dead:
            continue
        v = [to_int(a), to_int(b)]
        deck = [to_int(c) for c in DECK if c not in dead and c not in (a, b)]
        need = 5 - len(board)
        for run in combinations(deck, need):
            full = board_i + list(run)
            m, t = EV.evaluate(full, hero_i), EV.evaluate(full, v)
            total += 1.0 if m < t else 0.5 if m == t else 0.0
            count += 1
    return total / count


def random_spot(rng, street):
    n_board = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street]
    cards = rng.sample(DECK, 2 + n_board)
    hero, board = cards[:2], cards[2:]
    key = rng.choice(RANGE_KEYS if street != "flop" else ["tight", "very_tight"])
    pot = rng.choice([60, 120, 250, 500, 1000])
    call = round(pot * rng.choice([0.25, 0.33, 0.5, 0.66, 0.75, 1.0, 1.5, 2.0, 3.0]))
    return hero, board, key, pot, call


def run(per_street=200, streets=("river", "turn", "flop", "preflop"), seed=11, flop_limit=None, verbose=True):
    rng = random.Random(seed)
    totals = {"spots": 0, "loss": 0.0, "staked": 0.0, "wrong": 0, "close": 0, "max_loss_pct": 0.0}
    per = {}
    for street in streets:
        n = per_street if street != "flop" or flop_limit is None else min(per_street, flop_limit)
        st = {"spots": 0, "loss": 0.0, "staked": 0.0, "wrong": 0, "close": 0, "max_loss_pct": 0.0}
        for _ in range(n):
            hero, board, key, pot, call = random_spot(rng, street)
            spec = make_range(key)
            # what the app does (same call and budget as calculator.compute)
            app = equity(hero, board, 1, spec.combos, budget_s=0.3)
            verdict = call_or_fold(app.equity, app.stderr, pot, call, exact=True)
            # ground truth
            if street == "preflop":
                truth = equity(hero, board, 1, spec.combos, budget_s=60, max_iterations=400000).equity
            else:
                truth = exact_equity(hero, board, spec.combos)
            ev_true = ev_of_call(truth, pot, call)
            best = "call" if ev_true > 0 else "fold"
            if verdict.action == "close":
                loss = abs(ev_true)  # worst case: the user picks the wrong one
                st["close"] += 1
            elif verdict.action != best:
                loss = abs(ev_true)
                st["wrong"] += 1
            else:
                loss = 0.0
            st["spots"] += 1
            st["loss"] += loss
            st["staked"] += pot + call
            st["max_loss_pct"] = max(st["max_loss_pct"], 100.0 * loss / (pot + call))
        per[street] = st
        for k in ("spots", "loss", "staked", "wrong", "close"):
            totals[k] += st[k]
        totals["max_loss_pct"] = max(totals["max_loss_pct"], st["max_loss_pct"])
        if verbose:
            print(f"{street:8s} spots {st['spots']:4d}  wrong {st['wrong']:3d}  too-close {st['close']:3d}  "
                  f"EV lost {100 * st['loss'] / st['staked']:.4f}% of chips at stake  worst spot {st['max_loss_pct']:.3f}%")
    if verbose:
        print(f"TOTAL    spots {totals['spots']:4d}  wrong {totals['wrong']:3d}  too-close {totals['close']:3d}  "
              f"EV lost {100 * totals['loss'] / totals['staked']:.4f}% of chips at stake  worst spot {totals['max_loss_pct']:.3f}%")
    return totals, per


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    t = time.time()
    run(n, flop_limit=max(10, n // 5))
    print(f"{time.time() - t:.0f} s")
