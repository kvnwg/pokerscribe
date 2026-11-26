"""Luck adjustment for simulated hands (AIVAT-style; Burch, Schmid, Moravcik, Morrill and
Bowling, 2018), applied at the chance events: the flop, the turn and the river.

    adjusted = result - sum over the board cards dealt while the app was in of
               (value after the cards fell - expected value before they fell)

Any value function gives an unbiased answer, as long as the expected value before the
cards is exact; a better one removes more luck. Two are used, and mixed:

  checked down   what the app wins on average if nobody bets again: the chips already in,
                 shared out by every way the rest of the board can come, side pots included.
  all in         the same as if every player still in had also put in all the chips they
                 have behind (an uncalled part goes back, as at the table).

Both are exact here because the simulator knows every hole card (every runout for the turn
and the river; a fixed sample of full boards before the flop). Both are martingales: with
the hole cards and the chips fixed, the value before a card falls is exactly the average of
the values after it, so each correction averages zero.

The checked-down value alone misses the betting a card causes: a flush card both wins the
pot and gets the stacks in. So the correction for each card is

    checked-down luck + w(street, SPR) x (all-in luck - checked-down luck)

where SPR is the chips behind over the pot when the card falls, in three bands. The nine
weights WEIGHTS were fitted once by least squares on training hands (`python tools/luck.py
fit`, seed 505, tuning tables only) and are frozen: every comparison uses the same ones, so
the adjustment stays exactly unbiased (any fixed weights do) and no run fits anything to
its own hands. With every weight 0 this is the plain checked-down adjustment.

When the money is all in nothing is behind, so the all-in and checked-down values agree and
the adjusted result is the hand's all-in equity, whatever came.

Not corrected: the deal of the hole cards (it cancels in paired comparisons, since both
variants get the same cards) and the bots' random choices. The app's choices are
deterministic, so they need none.
"""
from __future__ import annotations

import os
import random
import sys
from itertools import combinations
from typing import Dict, List, Sequence, Tuple

from treys import Evaluator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.poker.hands import DECK, to_int  # noqa: E402
from simulate import BB, split_pot  # noqa: E402

_EVAL = Evaluator()
FLOP_SAMPLES = 3000  # full boards sampled for the value before the flop
SPR_BANDS = (1.5, 4.0)  # chips behind / pot: up to 1.5, up to 4, more
STREETS = ("flop", "turn", "river")  # the card(s) that fall
N_FEATURES = len(STREETS) * (len(SPR_BANDS) + 1)
# w(street, SPR band), flop bands then turn then river (see the module notes; refit with
# `python tools/luck.py fit` and paste the result here, with a line in experiments.md).
# Fitted 26 Nov 2026: `python tools/luck.py fit 2400` (seed 505; mixed, fish247, stations and
# maniacs; 1918 hands that saw a board card). On held-back decks the variance per hand was
# 782 raw, 412 checked down, 376 with these weights.
WEIGHTS = (0.310, 0.154, 0.046, 0.789, 0.141, 0.020, 0.206, 0.053, 0.005)


def values(cards: Sequence[Tuple[str, str]], board: Sequence[str], live: Sequence[int],
           put_ins: Sequence[Sequence[float]], me: int, key: int = 0, samples: int = FLOP_SAMPLES) -> List[float]:
    """For each chips-in vector in put_ins: the chips seat `me` wins on average, net of what
    it put in, if the hand is checked down from here. `cards` are every seat's hole cards
    (folded seats' cards are out of the deck too). Exact when two or fewer board cards are
    to come; otherwise the average over `samples` full boards drawn with a seed from `key`
    (the same key gives the same boards, so two variants in the same spot get the same value)."""
    if me not in live:
        return [-p[me] for p in put_ins]
    if len(live) == 1:
        return [sum(p) - p[me] for p in put_ins]
    dead = set(board)
    for c in cards:
        dead.update(c)
    rest = [to_int(c) for c in DECK if c not in dead]
    b = [to_int(c) for c in board]
    holes = {i: [to_int(c) for c in cards[i]] for i in live}
    need = 5 - len(board)
    if need <= 2:
        runouts = combinations(rest, need)
    else:
        rng = random.Random(key)
        runouts = (rng.sample(rest, need) for _ in range(samples))
    evaluate = _EVAL.evaluate
    totals = [0.0] * len(put_ins)
    n = 0
    for ro in runouts:
        full = b + list(ro)
        ranks = {i: evaluate(full, holes[i]) for i in live}
        for k, p in enumerate(put_ins):
            totals[k] += split_pot(p, live, ranks).get(me, 0.0)
        n += 1
    return [t / n - p[me] for t, p in zip(totals, put_ins)]


def value(cards, board, live, put_in, me, key: int = 0, samples: int = FLOP_SAMPLES) -> float:
    """The checked-down value for one chips-in vector (see values)."""
    return values(cards, board, live, [put_in], me, key, samples)[0]


def all_in(put_in: Sequence[float], behind: Sequence[float], live: Sequence[int]) -> Tuple[float, ...]:
    """Chips in if every live player also put in everything behind."""
    return tuple(p + (behind[i] if i in live else 0.0) for i, p in enumerate(put_in))


def spr_band(node: dict, me: int) -> int:
    """0, 1 or 2: the stack-to-pot ratio band when the card falls (chips the app could still
    win or lose, over the pot)."""
    others = max((node["behind"][i] for i in node["live"] if i != me), default=0.0)
    spr = min(node["behind"][me], others) / max(1e-9, sum(node["put_in"]))
    return sum(spr > x for x in SPR_BANDS)


def no_more_betting(node: dict) -> bool:
    """At most one player still in has chips behind, so nobody can bet again: the checked-down
    value is then the hand's exact value."""
    return sum(1 for i in node["live"] if node.get("behind", (1,) * 6)[i] > 1e-9) <= 1


def node_lucks(record: dict, samples: int = FLOP_SAMPLES, from_board: int = -1,
               exact_only: bool = False) -> List[Tuple[float, float, int]]:
    """For each chance event in a hand: (checked-down luck, all-in luck, feature index:
    street and SPR band), in big blinds. `record` is stats["last"] from
    tools/simulate.play_hand. With from_board = n, only the events dealing cards onto a board
    of n or more cards (those after a split on that street). With exact_only, only the events
    after which nobody can bet again (no_more_betting)."""
    cards, me, key = record["cards"], record["me"], record["key"]
    cache: Dict[tuple, List[float]] = {}

    def v(board, live, put_in, full):
        k = (board, live, put_in, full)
        if k not in cache:
            cache[k] = values(cards, board, live, [put_in, full], me, key=hash_key(key, board, live, put_in),
                              samples=samples)
        return cache[k]

    out = []
    for node in record["chance"]:
        if len(node["board"]) < from_board or (exact_only and not no_more_betting(node)):
            continue
        full = all_in(node["put_in"], node.get("behind", (0.0,) * len(node["put_in"])), node["live"])
        before = v(node["board"], node["live"], node["put_in"], full)
        after = v(node["board"] + node["deal"], node["live"], node["put_in"], full)
        band = spr_band(node, me) if "behind" in node else 0
        street = {0: 0, 3: 1, 4: 2}[len(node["board"])]
        out.append(((after[0] - before[0]) / BB, (after[1] - before[1]) / BB, street * (len(SPR_BANDS) + 1) + band))
    return out


def corrections(record: dict, samples: int = FLOP_SAMPLES) -> List[float]:
    """The checked-down luck of each chance event, in big blinds."""
    return [c for c, _, _ in node_lucks(record, samples)]


def features(record: dict, samples: int = FLOP_SAMPLES, after: int = -1, exact_only: bool = False) -> List[float]:
    """[checked-down luck, then (all-in luck - checked-down luck) for each street and SPR
    band], summed over the hand. Every entry averages exactly zero. With after = n, only the
    board cards dealt after a split on a board of n cards: two variants that part there share
    everything before it, so the earlier terms cancel in their difference and need no work."""
    f = [0.0] * (1 + N_FEATURES)
    for c, a, idx in node_lucks(record, samples, from_board=after, exact_only=exact_only):
        f[0] += c
        f[1 + idx] += a - c
    return f


def hash_key(key: int, board, live, put_in) -> int:
    """A seed for the sampled boards that depends on the spot, not on the cards to come."""
    h = key
    for x in (len(board), *live, *(round(p * 2) for p in put_in)):
        h = (h * 1000003 + int(x)) % (1 << 61)
    return h


def adjusted(record: dict, weights: Sequence[float] = None, samples: int = FLOP_SAMPLES) -> float:
    """The hand's result for the app in big blinds with the luck of the board taken out
    (weights: WEIGHTS unless given; all zero for the checked-down value only)."""
    return adjust(record["net"], features(record, samples), weights)


def adjust(net: float, f: Sequence[float], weights: Sequence[float] = None) -> float:
    """A result minus its luck, from features() (or a difference of two hands' features)."""
    w = WEIGHTS if weights is None else weights
    return net - f[0] - sum(wi * fi for wi, fi in zip(w, f[1:]))


def fit_weights(ys: Sequence[float], xs: Sequence[Sequence[float]], ridge: float = 1e-3) -> List[float]:
    """Least squares weights for ys ~ xs, with no intercept (every x averages zero). A small
    ridge keeps a band with almost no data at about 0."""
    import numpy as np

    if not xs:
        return [0.0] * N_FEATURES
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    xtx = x.T @ x
    lam = ridge * (np.trace(xtx) / max(1, x.shape[1]) + 1e-9)
    return [float(v) for v in np.linalg.solve(xtx + lam * np.eye(x.shape[1]), x.T @ y)]


def fit(n: int, tables: Sequence[str], seed: int, stacks: str = "even", jobs: int = 1) -> dict:
    """Play n hands of the baseline on each table (duplicate deals) and fit WEIGHTS to every
    hand that saw a board card. Returns the weights and how much each version cuts the
    variance, in the fit and on a held-back third of the decks."""
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=jobs) as ex:
        parts = list(ex.map(_fit_rows, [(n, t, seed, stacks) for t in tables]))
    ys, xs, raw, decks = [], [], [], []
    for p in parts:
        ys += p[0]
        xs += p[1]
        raw += p[2]
        decks += p[3]
    train = [i for i in range(len(ys)) if decks[i] % 3 != 2]
    test = [i for i in range(len(ys)) if decks[i] % 3 == 2]
    w_train = fit_weights([ys[i] for i in train], [xs[i] for i in train])
    w_all = fit_weights(ys, xs)

    def var(vals):
        m = sum(vals) / len(vals)
        return sum((v - m) ** 2 for v in vals) / max(1, len(vals) - 1)

    def resid(idx, w):
        return [ys[i] - sum(a * b for a, b in zip(w, xs[i])) for i in idx]

    return {"weights": w_all, "rows": len(ys), "hands": n * len(tables),
            "test": {"raw": var([raw[i] for i in test]), "checked_down": var([ys[i] for i in test]),
                     "fitted": var(resid(test, w_train)), "rows": len(test)}}


def _fit_rows(args):
    """One table's training rows: (result minus checked-down luck, all-in features, raw result, deck)."""
    from collections import defaultdict

    import simulate as sim

    n, table, seed, stacks = args
    ys, xs, raw, decks = [], [], [], []
    for k in range(n):
        d, r = divmod(k, 6)
        styles, names = sim.seating(table, seed, d)
        st = {"hands": [], "by_pos": defaultdict(list), "by_street": defaultdict(list), "all_in": [],
              "preflop_first": defaultdict(int), "advice": defaultdict(int), "problems": defaultdict(int),
              "examples": []}
        sim.play_hand(styles, d % 6, seed * 100003 + d, 0, 100.0, st, stacks, names, None, k + 1, rotate=r, keyed=True)
        rec = st["last"]
        if not rec["chance"]:
            continue
        f = features(rec)
        ys.append(rec["net"] - f[0])
        xs.append(f[1:])
        raw.append(rec["net"])
        decks.append(d)
    return ys, xs, raw, decks


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Fit the luck adjustment's weights on training hands.")
    ap.add_argument("command", choices=["fit"])
    ap.add_argument("hands", nargs="?", type=int, default=3000)
    ap.add_argument("--tables", default="mixed,fish247,stations,maniacs")
    ap.add_argument("--seed", type=int, default=505)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    res = fit(a.hands, a.tables.split(","), a.seed, jobs=a.jobs)
    t = res["test"]
    print(f"{res['rows']} hands that saw a board card, of {res['hands']}")
    print("WEIGHTS = (" + ", ".join(f"{w:.3f}" for w in res["weights"]) + ")")
    print(f"held-back decks ({t['rows']} hands): variance raw {t['raw']:.0f}, checked down {t['checked_down']:.0f}, "
          f"fitted {t['fitted']:.0f} (bb squared; fitted on the other decks)")


if __name__ == "__main__":
    main()
