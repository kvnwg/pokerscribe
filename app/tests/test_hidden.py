"""Imaginary observations over the opponent's hidden cards (tools/hidden.py).

The estimate is only worth having if its expected value is exactly the result's, so the main
tests deal every hand the opponent could hold (and every river card still to come) and check
that the average estimate equals the average result to rounding error."""
import itertools
import math
import os
import random
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")


@pytest.fixture(scope="module")
def tools():
    sys.path.insert(0, TOOLS)
    try:
        import compare
        import hidden
        import simulate
    finally:
        sys.path.remove(TOOLS)
    return simulate, hidden, compare


def _play(tools, table, seed, k, variant, shadow=None, hole=None, board=None):
    sim, _, compare = tools
    d, r = divmod(k, 6)
    styles, names = sim.seating(table, seed, d)
    st = compare.new_stats(variant, shadow)
    sim.play_hand(styles, d % 6, seed * 100003 + d, 0, 100.0, st, "even", names, None, k + 1, rotate=r, keyed=True,
                  hole_override=hole, board_override=board)
    return st


def test_bot_move_and_probabilities_match_every_recorded_decision(tools):
    """bot_move (bot_decide with the recorded seed) gives the move each bot made, and
    move_probs gives that move a positive chance (probabilities summing to 1)."""
    sim, hidden, _ = tools
    n = 0
    for table in ("mixed", "heldout", "switchers", "wildcards", "fish247"):
        for k in range(12):
            rec = _play(tools, table, 13, k, {})["last"]
            for snap in rec["bot_decisions"]:
                cards = rec["cards"][snap["i"]]
                assert hidden.bot_move(rec, snap, cards) == tuple(snap["action"])
                if len(snap["board"]) >= 3:
                    p = hidden.move_probs(rec, snap, cards)
                    assert sum(p.values()) == pytest.approx(1.0) and p[hidden.category(snap)] > 0
                n += 1
    assert n > 300


def test_move_probabilities_match_the_bot(tools):
    """move_probs against bot_decide run with many fresh seeds, for random hole cards."""
    sim, hidden, _ = tools
    rng = random.Random(3)
    checked = 0
    for table in ("mixed", "heldout", "maniacs"):
        for k in range(12):
            rec = _play(tools, table, 29, k, {})["last"]
            for snap in rec["bot_decisions"]:
                if len(snap["board"]) < 3 or checked >= 40:
                    continue
                dead = {c for i, p in enumerate(rec["cards"]) if i != snap["i"] for c in p} | set(snap["board"])
                y = tuple(rng.sample([c for c in sim.hands.DECK if c not in dead], 2))
                p = hidden.move_probs(rec, snap, y)
                counts, n = {}, 2000
                for s in range(n):
                    view = hidden._View({snap["i"]: hidden._seat(rec, snap, y)}, snap["current"], list(snap["board"]),
                                        snap["pot"], snap["number"])
                    kind, to = sim.bot_decide(view, snap["i"], random.Random(1000 * checked + s))
                    c = hidden.category(snap, hidden.table_move(kind, to, snap["current"], snap["bet"], snap["stack"],
                                                                snap["min_raise"]))
                    counts[c] = counts.get(c, 0) + 1
                for c, q in p.items():
                    f = counts.get(c, 0) / n
                    if q in (0.0, 1.0):
                        assert f == q
                    else:
                        assert abs(f - q) < 5 * math.sqrt(q * (1 - q) / n) + 1e-3
                checked += 1
    assert checked >= 20


class _Every(dict):
    """Weights: the same for every group."""

    def __init__(self, w):
        super().__init__()
        self.w = w

    def get(self, key, default=None):
        return self.w


def _split(tools, table, seed, k, other):
    sim, hidden, _ = tools
    st = _play(tools, table, seed, k, {}, shadow=other)
    rec = st["last"]
    j = rec["diverge_at"]
    b = hidden.opponent(rec, j)
    assert st["diverged"] and b is not None
    return rec, j, b


def _pre_split(hidden, rec, j):
    out = []
    for kind, idx in rec["events"][:hidden.split_event(rec, j) + 1]:
        if kind == "bot":
            out.append(tuple(rec["bot_decisions"][idx]["action"]))
        elif kind == "app":
            out.append((rec["spots"][idx]["move"], round(rec["spots"][idx]["to_bb"], 9)))
        else:
            out.append(rec["chance"][idx]["deal"])
    return out


def test_class_matches_dealing_the_hands(tools):
    """The opponent's class at the split: dealing it any other hand changes the hand before
    the split exactly when that hand is outside the class."""
    sim, hidden, _ = tools
    rec, j, b = _split(tools, "tags", 9, 49, {"ev_sizing": True})
    cls = set(hidden.split_class(rec, b, j))
    known = {c for i, p in enumerate(rec["cards"]) if i != b for c in p} | set(rec["board"][:rec["spots"][j]["board_len"]])
    unseen = [c for c in sim.hands.DECK if c not in known]
    ref = _pre_split(hidden, rec, j)
    sample = random.Random(2).sample(list(itertools.combinations(unseen, 2)), 30) + list(cls)[:10]
    for y in sample:
        last = _play(tools, "tags", 9, 49, {}, hole={b: y})["last"]
        same = len(last["spots"]) > j and _pre_split(hidden, last, j) == ref
        assert same == (y in cls), y


@pytest.mark.parametrize("case", [("tags", 9, 49, {"ev_sizing": True}, "ab"), ("mixed", 31, 454, {"bet_size": 0.5}, "a")])
def test_estimate_is_exact_given_the_split(tools, case):
    """Deal every hand in the class (and on the turn every river card): the average estimate
    equals the average result exactly, for each variant. The first case parts on the river,
    the second on the turn (so the river-card correction and card removal are checked)."""
    sim, hidden, _ = tools
    table, seed, k, other, which = case
    rec, j, b = _split(tools, table, seed, k, other)
    sp = hidden.Split(rec, j, b)
    cls = sp.cls
    street = rec["spots"][j]["board_len"]
    known = {c for i, p in enumerate(rec["cards"]) if i != b for c in p} | set(rec["board"][:street])
    checked = []
    for tag in which:
        variant = {} if tag == "a" else other
        results, estimates, odd = [], [], []
        for y in cls:
            rivers = [None] if street == 5 else [c for c in sim.hands.DECK if c not in known and c not in y]
            for c in rivers:
                last = _play(tools, table, seed, k, variant, hole={b: y}, board=None if c is None else {4: c})["last"]
                results.append(last["net"])
                estimates.append(hidden.estimate(last, sp, mode="known"))
                odd.append(hidden.estimate(last, sp, mode="known", weights=_Every(0.7)))
        mean = sum(results) / len(results)
        assert sum(estimates) / len(estimates) == pytest.approx(mean, abs=1e-9)
        assert sum(odd) / len(odd) == pytest.approx(mean, abs=1e-9)  # any fixed weights: still exact
        spread = lambda xs: sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)  # noqa: E731
        assert spread(estimates) <= spread(results) + 1e-12
        checked.append(spread(results))
    assert max(checked) > 0  # at least one variant's result depends on the deal


def test_paired_runs_with_hidden_cards(tools):
    """A variant against itself is zero everywhere; a real comparison gives the same numbers
    split over processes."""
    _, _, compare = tools
    same = compare.paired({}, {}, 12, "maniacs", 3, method="duplicate", resample=2, use_hidden=True)
    assert all(x == 0 for x in same[4]["hidden"])
    one = compare.paired({}, {"bet_size": 0.5}, 24, "mixed", 31, method="duplicate", resample=2, use_hidden=True)
    split = compare.run_paired({}, {"bet_size": 0.5}, 24, "mixed", 31, method="duplicate", jobs=2, resample=2,
                               use_hidden=True)
    assert one[4]["hidden"] == split[4]["hidden"] and len(one[4]["hidden"]) == 24


def test_bet_size_does_not_depend_on_the_cards(tools):
    """hidden.move_probs counts a bet as one kind of move, which is right only if its size
    follows the same law whether the bot bets for value or bluffs (simulate.bot_decide uses
    one formula with a fresh random number on both paths). If bot_decide ever sizes bluffs
    differently, this fails and tools/hidden.py must weigh sizes too."""
    sim, hidden, _ = tools
    for style in ("lag", "maniac", "overbettor", "minbettor"):
        seat_v = sim.Seat(style, stack=180.0, name=style + "0", cards=("As", "Ah"))
        seat_b = sim.Seat(style, stack=180.0, name=style + "0", cards=("2c", "7d"))
        sizes = {}
        for tag, seat, board in (("value", seat_v, ["Ad", "Ac", "9h"]), ("bluff", seat_b, ["Kh", "Qs", "4d"])):
            out = []
            for s in range(4000):
                view = hidden._View({1: seat}, 0.0, board, 20.0, 5)
                kind, to = sim.bot_decide(view, 1, random.Random(s))
                if kind == "raise":
                    out.append(to / 20.0)
            sizes[tag] = sorted(out)
        assert len(sizes["value"]) > 500 and len(sizes["bluff"]) > 20, (style, len(sizes["bluff"]))
        for q in (0.1, 0.5, 0.9):
            a = sizes["value"][int(q * len(sizes["value"]))]
            b = sizes["bluff"][int(q * len(sizes["bluff"]))]
            assert abs(a - b) < 0.12, (style, q, a, b)


def test_lean_mode_gives_the_same_estimate(tools):
    """compare --lean skips the luck-adjusted diagnostics but not the hidden-cards estimate."""
    _, _, compare = tools
    full = compare.paired({}, {"bet_size": 0.5}, 24, "mixed", 31, method="duplicate", resample=2, use_hidden=True)
    lean = compare.paired({}, {"bet_size": 0.5}, 24, "mixed", 31, method="duplicate", resample=2, use_hidden=True,
                          lean=True)
    assert full[4]["hidden"] == lean[4]["hidden"] and full[2] == lean[2]


def test_redealt_replays_keep_the_hand_before_the_split(tools):
    """compare --redeal: every replay deals the bots still in a hand from their classes (no
    card twice) and the hand up to the split comes out exactly the same, for heads-up,
    multiway and preflop splits alike."""
    sim, hidden, compare = tools
    kinds = set()
    for table, other in (("mixed", {"bet_size": 0.5}), ("maniacs", {"push_chart": True}), ("stations", {"stab": 0.0})):
        for k in range(120):
            st = _play(tools, table, 37, k, {}, shadow=other)
            if not st["diverged"]:
                continue
            rec = st["last"]
            j = rec["diverge_at"]
            classes = hidden.live_classes(rec, j)
            kinds.add((len(classes) > 1, rec["spots"][j]["board_len"] == 0))
            ref = _pre_split(hidden, rec, j)
            for draw in hidden.redeal(classes, 3, (k, "test")):
                cards = [c for y in draw.values() for c in y]
                assert len(set(cards)) == len(cards) and all(y in classes[i] for i, y in draw.items())
                d, r = divmod(k, 6)
                styles, names = sim.seating(table, 37, d)
                s2 = compare.new_stats({})
                sim.play_hand(styles, d % 6, 37 * 100003 + d, 0, 100.0, s2, "even", names, None, k + 1, rotate=r,
                              keyed=True, split_at=j, resample=1, hole_override=draw)
                assert _pre_split(hidden, s2["last"], j) == ref
                assert all(tuple(s2["last"]["cards"][i]) == tuple(y) for i, y in draw.items())
    assert (True, True) in kinds or (True, False) in kinds  # a multiway split was checked
