"""Where does the app lose? A ranked list of the decisions that cost the most.

    python tools/weakness.py [hands] [--table mixed] [--seed 11] [--stacks even] [--flaw NAME]
    python tools/weakness.py 1200 --check-flaws          # does it find flaws planted on purpose?

For each decision the app makes, the hand is replayed with every other move at that
decision (fold, check or call, a small and a big bet or raise, all in), on the same cards
and the same bot random numbers, with the app's own advice after it. A move's gain is its
luck-adjusted result (tools/luck.py) minus the luck-adjusted result of what the app did.
Gains are grouped by spot (street, what the app faced, its hand, what it did) and ranked
by big blinds per 100 hands at stake, after taking off one and a half standard errors so
that a few lucky replays don't top the list. This is a one-step improvement against these
opponents, in the spirit of local best response (Lisy and Bowling, 2017): it says where a
different move would have won more, not what the best strategy is.

Preflop folds with nothing better than a call to make are most of the decisions and
rarely the problem, so only one in --fold-sample of them is replayed (each counts that
many times, so the totals stay unbiased).

Below the ranked list, the luck-adjusted results by position, pot type and line (the
app's moves street by street).

--flaw plants a known mistake in the app (FLAWS below). --check-flaws plays the app and
each flawed copy on the same deals and checks that each flaw's spot is in that copy's top
ten (the Phase 1 success test: at least 90% of planted flaws found).
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import luck  # noqa: E402
import simulate as sim  # noqa: E402
from app.poker import hands  # noqa: E402
from app.poker.ranges import preflop_percentile  # noqa: E402

BB = sim.BB
MOVES = ("fold", "passive", "small", "big", "all-in")  # passive: check or call


# ------------------------------------------------------------------ planted flaws
def _flaw_folds_to_3bets(h, me, adv, move):
    """Folds to every re-raise before the flop unless it holds the top 2% of hands."""
    seat = h.seats[me]
    if not h.board and sim.situation(h, me) == "facing a 3-bet+" and move[0] != "fold":
        if preflop_percentile(hands.preflop_class(seat.cards)) > 0.02:
            return "fold", 0.0
    return move


def _flaw_never_bets_river(h, me, adv, move):
    """Never bets the river when checked to: no value bets, no bluffs."""
    if len(h.board) == 5 and h.current <= h.seats[me].bet and move[0] == "raise":
        return "check", 0.0
    return move


def _flaw_calls_river_bets(h, me, adv, move):
    """Calls every bet on the river."""
    if len(h.board) == 5 and h.current > h.seats[me].bet and move[0] == "fold":
        return "call", 0.0
    return move


def _flaw_overbets(h, me, adv, move):
    """Bets one and a half times the pot whenever it bets after the flop."""
    seat = h.seats[me]
    if h.board and h.current <= seat.bet and move[0] == "raise":
        return "raise", min(seat.stack + seat.bet, 1.5 * h.pot)
    return move


def _flaw_limps(h, me, adv, move):
    """Limps instead of raising when first in."""
    if not h.board and sim.situation(h, me) == "first in" and move[0] == "raise":
        return "call", 0.0
    return move


# name: (what it does, the hook, its spot: street, situations, the flawed move)
FLAWS: Dict[str, Tuple[str, Callable, Tuple[str, Tuple[str, ...], str]]] = {
    "folds_to_3bets": (_flaw_folds_to_3bets.__doc__, _flaw_folds_to_3bets, ("preflop", ("facing a 3-bet+",), "fold")),
    "never_bets_river": (_flaw_never_bets_river.__doc__, _flaw_never_bets_river, ("river", ("checked to",), "check")),
    "calls_river_bets": (_flaw_calls_river_bets.__doc__, _flaw_calls_river_bets,
                         ("river", ("facing a bet", "facing a raise"), "call")),
    "overbets": (_flaw_overbets.__doc__, _flaw_overbets, ("postflop", ("checked to",), "bet")),
    "limps": (_flaw_limps.__doc__, _flaw_limps, ("preflop", ("first in",), "call")),
}


def matches(key: tuple, signature: tuple) -> bool:
    street, situations, move = signature
    k_street, k_situation, _strength, k_move = key
    street_ok = k_street == street or (street == "postflop" and k_street != "preflop")
    return street_ok and k_situation in situations and k_move == move


# ------------------------------------------------------------------ moves and spots
def alternative(kind: str, current: float, pot: float, to_call: float, total: float,
                board_len: int) -> Optional[Tuple[str, float]]:
    """The table move for one of MOVES at a decision (None if it makes no sense there):
    `current` is the bet to match, `total` the app's stack plus its bet this round."""
    if kind == "fold":
        return ("fold", 0.0) if to_call > 0 else None
    if kind == "passive":
        return ("call", 0.0) if to_call > 0 else ("check", 0.0)
    if kind == "all-in":
        # only where going all in is a real option: a short stack, or a pot that is big next to it
        if total <= current or (total > 25 * BB if not board_len else total > 2.5 * (pot + to_call)):
            return None
        return "raise", total
    if total <= current:
        return None
    if not board_len:
        frac = {"small": 2.5, "big": 4.0}[kind] if current <= BB else {"small": 3.0, "big": 4.5}[kind]
        to = frac * max(current, BB)
    else:
        to = current + {"small": 0.4, "big": 1.0}[kind] * (pot + to_call)
    if to >= total * 0.9:
        return None  # that is all in
    return "raise", to


def alternative_at(h: sim.Hand, me: int, kind: str) -> Optional[Tuple[str, float]]:
    seat = h.seats[me]
    return alternative(kind, h.current, h.pot, max(0.0, h.current - seat.bet), seat.stack + seat.bet, len(h.board))


def alternative_for(sp: dict, kind: str) -> Optional[Tuple[str, float]]:
    """The same from a recorded decision (amounts in chips)."""
    return alternative(kind, sp["current_bb"] * BB, sp["pot_bb"] * BB, sp["to_call_bb"] * BB, sp["stack_bb"] * BB,
                       sp["board_len"])


def strength_label(sp: dict) -> str:
    if sp["street"] == "preflop":
        return sp["made"]
    made = sp["made"]
    if made in ("High Card",):
        return "draw" if sp["draw"] else "nothing"
    if made == "Pair":
        return "pair + draw" if sp["draw"] else "pair"
    if made in ("Two Pair", "Three of a Kind"):
        return "two pair or trips"
    return "straight or better"


def move_label(sp: dict) -> str:
    m = sp["move"]
    if m == "raise":
        if sp["to_bb"] >= sp["stack_bb"] - 1e-6:
            return "all in"
        return "raise" if sp["facing"] else "bet"
    return m


def spot_key(sp: dict) -> tuple:
    return sp["street"], sp["situation"], strength_label(sp), move_label(sp)


def same_move(a: Tuple[str, float], b: Tuple[str, float]) -> bool:
    if a[0] != b[0]:
        return False
    return a[0] != "raise" or abs(a[1] - b[1]) <= 0.15 * max(a[1], b[1])


# ------------------------------------------------------------------ playing and replaying
def new_stats(hook=None) -> dict:
    return {"hands": [], "by_pos": defaultdict(list), "by_street": defaultdict(list), "all_in": [],
            "preflop_first": defaultdict(int), "advice": defaultdict(int), "problems": defaultdict(int),
            "examples": [], "hook": hook}


def luck_before(record: dict, board_len: int) -> float:
    """Luck of the chance events up to this street (shared by every move made on it), the
    same measure as luck.adjusted."""
    nodes = [n for n in record["chance"] if len(n["board"]) + len(n["deal"]) <= board_len]
    return record["net"] - luck.adjusted({**record, "chance": nodes})


def analyse(n: int, table: str, seed: int, flaw: Optional[str] = None, depth_bb: float = 100.0,
            stacks: str = "even", fold_sample: int = 10, quiet: bool = False) -> dict:
    """Play n hands (duplicate deals, six rotations a deck) and replay every decision with
    every other move. Returns the decisions with their gains, and each hand's result."""
    flaw_hook = FLAWS[flaw][1] if flaw else None
    out = {"decisions": [], "hands": [], "table": table, "seed": seed, "flaw": flaw, "n": n}
    pick = random.Random(seed * 7919 + 1)
    t0 = time.time()
    for k in range(n):
        d, r = divmod(k, 6)
        styles, names = sim.seating(table, seed, d)
        args = (styles, d % 6, seed * 100003 + d, 0, depth_bb)
        kw = dict(stacks=stacks, names=names, number=k + 1, rotate=r, keyed=True)
        st = new_stats(flaw_hook)
        sim.play_hand(*args, st, **kw)
        rec = st["last"]
        adj = luck.adjusted(rec)
        out["hands"].append({"adj": adj, "net": rec["net"], "pos": rec["pos"], "deck": d,
                             "pot_type": rec["pot_type"],
                             "line": " / ".join("".join(x[0] for x in moves) for moves in _line(rec["spots"]))})
        for j, sp in enumerate(rec["spots"]):
            weight = 1.0
            if sp["street"] == "preflop" and sp["move"] == "fold" and sp["situation"] in ("first in", "facing a raise"):
                if pick.random() * fold_sample >= 1:
                    continue
                weight = float(fold_sample)
            gains = {}
            for kind in MOVES:
                gains[kind] = _replay_gain(args, kw, flaw_hook, rec, adj, j, sp, kind)
            out["decisions"].append({"key": spot_key(sp), "weight": weight, "gains": gains, "spot": sp, "deck": d})
        if not quiet and (k + 1) % 300 == 0:
            print(f"  {k + 1} hands, {len(out['decisions'])} decisions replayed, {time.time() - t0:.0f}s", flush=True)
    return out


def _line(spots):
    by = defaultdict(list)
    for sp in spots:
        by[sp["board_len"]].append(move_label(sp))
    return [by[b] for b in sorted(by)]


def _replay_gain(args, kw, flaw_hook, rec, adj, j, sp, kind) -> Optional[float]:
    """Luck-adjusted gain of playing `kind` at the app's j-th decision instead of its move."""
    state = {}

    planned = alternative_for(sp, kind)
    taken = (sp["move"], sp["to_bb"] * BB)
    if planned is None or same_move(planned, taken):
        return None  # not a move here, or what the app did anyway: no replay

    def hook(h, me, adv, move):
        if len(h.spots) == j:
            alt = alternative_at(h, me, kind)
            state["alt"] = alt
            if alt is None or same_move(alt, move):
                state["same"] = True
                return move
            return alt
        return flaw_hook(h, me, adv, move) if flaw_hook else move

    if kind == "fold":
        # no replay needed: folding now loses what is in, after the board luck so far
        if sp["to_call_bb"] <= 0 or sp["move"] == "fold":
            return None
        return -sp["put_in_bb"] - luck_before(rec, sp["board_len"]) - adj
    st = new_stats(hook)
    sim.play_hand(*args, st, **kw)
    if state.get("same") or "alt" not in state:
        return None
    return luck.adjusted(st["last"]) - adj


# ------------------------------------------------------------------ ranking
def rank(result: dict) -> List[dict]:
    """Spots ranked by the bb/100 a better move would have gained (minus 1.5 standard errors)."""
    hands_n = len(result["hands"])
    groups: Dict[tuple, List[dict]] = defaultdict(list)
    for dec in result["decisions"]:
        groups[dec["key"]].append(dec)
    items = []
    for key, decs in groups.items():
        count = sum(d["weight"] for d in decs)
        best = None
        for kind in MOVES:
            vals = [(d["gains"][kind], d["weight"], d["deck"]) for d in decs if d["gains"].get(kind) is not None]
            if len(vals) < 3:
                continue
            # total gain per 100 hands, its standard error with decks as units
            per_deck = defaultdict(float)
            for g, w, deck in vals:
                per_deck[deck] += g * w
            decks_n = max(1, hands_n // 6)
            total = sum(per_deck.values())
            mean_deck = total / decks_n
            ss = sum((v - mean_deck) ** 2 for v in per_deck.values()) + (decks_n - len(per_deck)) * mean_deck ** 2
            se_total = math.sqrt(ss * decks_n / max(1, decks_n - 1)) if decks_n > 1 else 0.0
            per100, se100 = 100 * total / hands_n, 100 * se_total / hands_n
            score = per100 - 1.5 * se100
            if best is None or score > best["score"]:
                n_alt = sum(w for _, w, _ in vals)
                best = {"key": key, "better": kind, "per100": per100, "se100": se100, "score": score,
                        "decisions": count, "per_decision": total / n_alt if n_alt else 0.0}
        if best is not None and best["per100"] > 0:
            items.append(best)
    items.sort(key=lambda x: -x["score"])
    return items


def describe(item: dict) -> str:
    street, situation, strength, move = item["key"]
    better = {"passive": "check or call", "small": "a small bet or raise", "big": "a big bet or raise",
              "fold": "fold", "all-in": "all in"}[item["better"]]
    return (f"{street}, {situation}, {strength}: it chose {move}; {better} gains "
            f"{item['per100']:+.1f} ± {item['se100']:.1f} bb/100 ({item['per_decision']:+.2f} bb a decision, "
            f"{item['decisions']:.0f} decisions)")


def summary(result: dict, top: int = 15) -> str:
    hands_n = len(result["hands"])
    adj = [h["adj"] for h in result["hands"]]
    raw = [h["net"] for h in result["hands"]]
    lines = [f"{result['table']} table, seed {result['seed']}, {hands_n} hands"
             + (f", planted flaw: {result['flaw']}" if result["flaw"] else "")
             + f": {100 * sum(raw) / hands_n:+.1f} bb/100 raw, {100 * sum(adj) / hands_n:+.1f} luck-adjusted"]
    lines.append(f"Where a different move gains most (top {top} of {len(result['decisions'])} decisions replayed):")
    for i, item in enumerate(rank(result)[:top], 1):
        lines.append(f"{i:3d}. {describe(item)}")
    for title, field in (("position", "pos"), ("pot type", "pot_type"), ("line", "line")):
        by = defaultdict(list)
        for h in result["hands"]:
            by[h[field]].append(h["adj"])
        rows = sorted(by.items(), key=lambda kv: sum(kv[1]))
        if field == "line":
            rows = [kv for kv in rows if len(kv[1]) >= 10][:12]
            lines.append("Luck-adjusted by line (f fold, c check or call, b bet, r raise, a all in), "
                         "biggest losses first, lines seen 10+ times:")
        else:
            lines.append(f"Luck-adjusted by {title}:")
        for name, vals in rows:
            lines.append(f"     {name or '-':28s} {len(vals):5d} hands  {sum(vals):+8.1f} bb  "
                         f"({100 * sum(vals) / hands_n:+.1f} bb/100 of all hands)")
    return "\n".join(lines)


def check_flaws(n: int, table: str, seed: int, top: int = 10, flaws=None, **kw) -> Tuple[str, int, int]:
    found = 0
    lines = []
    names = flaws or list(FLAWS)
    for name in names:
        doc, _hook, signature = FLAWS[name]
        res = analyse(n, table, seed, flaw=name, quiet=True, **kw)
        items = rank(res)[:top]
        pos = next((i for i, it in enumerate(items, 1) if matches(it["key"], signature)), None)
        found += pos is not None
        lines.append(f"{name}: {'found at ' + str(pos) if pos else 'NOT in the top ' + str(top)} ({doc.strip()})")
        if pos:
            lines.append(f"     {describe(items[pos - 1])}")
    return "\n".join(lines), found, len(names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hands", nargs="?", type=int, default=1200)
    ap.add_argument("--table", default="mixed", choices=sorted(sim.TABLES))
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--stacks", default="even", choices=["even"] + sorted(sim.STACKS))
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--flaw", choices=sorted(FLAWS))
    ap.add_argument("--fold-sample", type=int, default=10)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--check-flaws", action="store_true")
    ap.add_argument("--save", help="write the ranked spots to this JSON file")
    a = ap.parse_args()
    if a.hands % 6:
        a.hands += 6 - a.hands % 6
    kw = dict(depth_bb=500.0 if a.deep else 100.0, stacks=a.stacks, fold_sample=a.fold_sample)
    t0 = time.time()
    if a.check_flaws:
        text, found, total = check_flaws(a.hands, a.table, a.seed, flaws=[a.flaw] if a.flaw else None, **kw)
        print(text)
        print(f"{found} of {total} planted flaws in the top 10 ({time.time() - t0:.0f}s)")
        return
    res = analyse(a.hands, a.table, a.seed, flaw=a.flaw, **kw)
    print(summary(res, a.top))
    print(f"({time.time() - t0:.0f}s)")
    if a.save:
        import json

        with open(a.save, "w") as f:
            json.dump({"args": vars(a), "ranked": [{**it, "key": list(it["key"])} for it in rank(res)],
                       "adjusted": [h["adj"] for h in res["hands"]]}, f)


if __name__ == "__main__":
    main()
