"""Imaginary observations: AIVAT's correction for the opponent's hidden cards (Burch, Schmid,
Moravcik, Morrill and Bowling, 2018), for the simulator's bots, whose strategies are known.

When the two variants of a paired comparison part ways (tools/compare.py) heads-up after the
flop, what is left of the variance is mostly the opponent: the cards it happens to hold and
its random choices decide how it answers each variant's bets. This replaces each variant's
result by an estimate that averages over both, using only what the hand showed.

Setting. Let K be everything known when the variants part (the split), except the opponent's
hole cards Y: the moves so far, the app's cards, the folded bots' cards, the board so far and
the bots' random numbers before the split.

  1. Given K, Y is uniform over the class C of pairs that are not among the known cards and
     with which the opponent would have made exactly its moves so far. (The deal is uniform,
     and with its random numbers fixed a bot's move is a function of its cards:
     bot_move() asks simulate.bot_decide itself, with the recorded seed.)
  2. After the split the opponent's random numbers are fresh, so its move at each decision
     has known probabilities given its cards (move_probs(), worked out from bot_decide).
     Each move multiplies each candidate hand's weight by that hand's probability of it.
  3. A river card c falls with probability proportional to the weight of the candidate
     hands that don't hold it (all unseen cards are equally likely given the hole cards).
     Hands that hold it drop out.

The estimate for one variant's hand, in big blinds:

    estimate = sum over candidate hands of weight x result with that hand / sum of weights
               - sum over the opponent's moves after the split of (V(move) - sum P(m) V(m))
               - sum over river cards after the split of (V(card) - sum P(c) V(c))

V is the app's checked-down value averaged over the candidate hands that would make that
move (or that don't hold that card). The first term is the expected result given the whole
public hand; each correction has expectation zero given what came before it, whatever V is.
So the estimate has the same expected value as the result given K (and the paired difference
the same as the raw one), and it no longer depends on which hand of its range the opponent
held, or on which of its random choices it drew. (The turn card is corrected the same way
as the river card.)

Approximations change only the variance, never the expected value: V ignores betting still
to come, and it averages a fixed sample of the class (SAMPLE hands, chosen by the hand's
seed before anything after the split is known), whose showdowns against the app are
tabulated once for every runout (Split). The probabilities and the final average use every
hand of the class with its exact weight, as they must.
"""
from __future__ import annotations

import os
import random
import sys
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from treys import Evaluator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulate as sim  # noqa: E402
from app.poker.hands import DECK, to_int  # noqa: E402

_EVAL = Evaluator()
BB = sim.BB

Hand2 = Tuple[str, str]


# ------------------------------------------------------------------ the opponent's moves
class _View:
    """What simulate.bot_decide reads of a hand."""

    __slots__ = ("seats", "current", "board", "pot", "number")

    def __init__(self, seats, current, board, pot, number):
        self.seats, self.current, self.board, self.pot, self.number = seats, current, board, pot, number


def table_move(kind: str, to: float, current: float, bet: float, stack: float, min_raise: float) -> tuple:
    """What simulate.act makes of a move, without changing anything: ("raise", to),
    ("call", chips added), ("check", 0) or ("fold", 0), as in the hand's log."""
    to_call = current - bet
    if kind == "fold" and to_call <= 0:
        kind = "check"
    if kind == "check" and to_call > 0:
        kind = "fold"
    if kind == "raise":
        to = min(max(to, current + min_raise), stack + bet)
        if to > current:
            return "raise", to
        kind = "call"
    if kind == "call":
        return "call", min(to_call, stack)
    return kind, 0


def _seat(rec: dict, snap: dict, cards) -> sim.Seat:
    style, name = rec["seats"][snap["i"]]
    return sim.Seat(style, stack=snap["stack"], name=name, cards=tuple(cards), bet=snap["bet"])


def bot_move(rec: dict, snap: dict, cards) -> tuple:
    """The move the bot at this recorded decision would have made with these hole cards and
    the same random numbers (simulate.bot_decide, with the decision's seed)."""
    view = _View({snap["i"]: _seat(rec, snap, cards)}, snap["current"], list(snap["board"]), snap["pot"],
                 snap["number"])
    kind, to = sim.bot_decide(view, snap["i"], random.Random(snap["spec"]))
    return table_move(kind, to, snap["current"], snap["bet"], snap["stack"], snap["min_raise"])


def category(snap: dict, move: Optional[tuple] = None) -> str:
    """A move's kind as move_probs counts it: checked to "check" or "bet"; facing a bet
    "fold", "call" or "raise"."""
    kind = (move or snap["action"])[0]
    if snap["current"] > snap["bet"]:
        return kind
    return "bet" if kind == "raise" else kind


def move_probs(rec: dict, snap: dict, cards) -> Dict[str, float]:
    """The chance of each kind of move at this postflop decision with these hole cards, over
    the bot's own random numbers: simulate.bot_decide after the flop, worked out. A bet's
    size follows the same law whatever the cards, so only its kind tells anything about them."""
    seat = _seat(rec, snap, cards)
    style, numbers, extra = sim.bot_style(_View(None, 0, [], 0, snap["number"]), seat)
    _vpip, _pfr, _three, bet_s, call_s, bluff, aggr = numbers
    board = list(snap["board"])
    st = sim.strength(seat.cards, board)
    to_call = snap["current"] - snap["bet"]
    if to_call <= 0:
        enter = 1.0 if st >= bet_s else (bluff if st < 0.35 else 0.0)
        trap = extra["trap"] if extra.get("trap") and st >= 0.9 else 0.0
        bet = enter * (1.0 - trap) * (1.0 if st >= 0.9 else aggr)
        return {"bet": bet, "check": 1.0 - bet}
    pot = snap["pot"]
    price = to_call / (pot + to_call)
    p_raise = extra.get("raise", aggr) if st >= max(bet_s + 0.15, 0.85) else 0.0
    need = price * (0.6 if style == "station" else 1.0)
    calls = st >= max(call_s * (0.6 + price), need + 0.1) or (style == "station" and st >= 0.3)
    raise_to = min(snap["stack"] + snap["bet"], snap["current"] * 3 + pot * 0.2)
    raised = table_move("raise", raise_to, snap["current"], snap["bet"], snap["stack"], snap["min_raise"])[0]
    out = {"fold": 0.0, "call": 0.0, "raise": 0.0}
    out[raised] += p_raise  # "call" when it can't raise
    out["call" if calls else "fold"] += 1.0 - p_raise
    return out


# ------------------------------------------------------------------ who could hold what
def split_event(rec: dict, j: int) -> int:
    """Index in rec["events"] of the app's decision number j."""
    return next(e for e, (kind, idx) in enumerate(rec["events"]) if kind == "app" and idx == j)


def opponent(rec: dict, j: int) -> Optional[int]:
    """The one bot still in at the app's decision j after the flop, or None (not heads-up,
    or before the flop): only then is the hidden-cards estimate used."""
    sp = rec["spots"][j]
    live = [i for i in sp["live"] if i != rec["me"]]
    return live[0] if len(live) == 1 and sp["board_len"] >= 3 else None


def split_class(rec: dict, b: int, j: int) -> List[Hand2]:
    """Every hand bot b could hold at the app's decision j given all it did before: pairs of
    cards no other seat holds and not on the board, with which its moves come out the same."""
    board = rec["board"][:rec["spots"][j]["board_len"]]
    known = {c for k, pair in enumerate(rec["cards"]) if k != b for c in pair} | set(board)
    unseen = [c for c in DECK if c not in known]
    e0 = split_event(rec, j)
    pre = [rec["bot_decisions"][idx] for kind, idx in rec["events"][:e0]
           if kind == "bot" and rec["bot_decisions"][idx]["i"] == b]
    return [y for y in combinations(unseen, 2) if all(bot_move(rec, snap, y) == tuple(snap["action"])
                                                       for snap in pre)]


def live_classes(rec: dict, j: int) -> Dict[int, List[Hand2]]:
    """For every bot still in at the app's decision j: the hands it could hold given all it did
    before (pairs not among the known cards: the app's, the folded bots', the board so far;
    with which its moves come out the same). Given the split, the live bots' cards are uniform
    over the assignments of one hand of its class to each bot with no card twice."""
    me = rec["me"]
    sp = rec["spots"][j]
    live = [i for i in sp["live"] if i != me]
    board = rec["board"][:sp["board_len"]]
    known = {c for i, pair in enumerate(rec["cards"]) if i not in live for c in pair} | set(board)
    unseen = [c for c in DECK if c not in known]
    e0 = split_event(rec, j)
    out = {}
    for i in live:
        pre = [rec["bot_decisions"][idx] for kind, idx in rec["events"][:e0]
               if kind == "bot" and rec["bot_decisions"][idx]["i"] == i]
        out[i] = [y for y in combinations(unseen, 2)
                  if all(bot_move(rec, snap, y) == tuple(snap["action"]) for snap in pre)]
    return out


def redeal(classes: Dict[int, List[Hand2]], n: int, key) -> List[Dict[int, Hand2]]:
    """n draws of the live bots' hands from their classes, uniform over assignments with no
    card twice (rejection), from a seed that depends only on the hand. With one bot the draws
    go through its class in a shuffled order (without replacement while it lasts)."""
    rng = random.Random(str(key))
    if len(classes) == 1:
        (i, cls), = classes.items()
        order = list(cls)
        rng.shuffle(order)
        return [{i: order[s % len(order)]} for s in range(n)]
    out = []
    while len(out) < n:
        pick = {i: rng.choice(cls) for i, cls in classes.items()}
        cards = [c for y in pick.values() for c in y]
        if len(set(cards)) == len(cards):
            out.append(pick)
    return out


# ------------------------------------------------------------------ values
class Split:
    """What is fixed when the variants part, for one hand: the opponent b, its class, a fixed
    sample of the class (chosen by the hand's seed, without looking at anything to come), and
    for each sampled hand its showdown against the app for every way the board can finish. So
    every value is a lookup, the same for both variants and every replay from the split."""

    def __init__(self, rec: dict, j: int, b: int, cls: Optional[Sequence[Hand2]] = None):
        self.me, self.b, self.j = rec["me"], b, j
        self.street = rec["spots"][j]["board_len"]
        self.board0 = tuple(rec["board"][:self.street])
        self.dead = {c for k, pair in enumerate(rec["cards"]) if k != b for c in pair}
        self.cls = list(split_class(rec, b, j) if cls is None else cls)
        self.sample = _sample(self.cls, SAMPLE, rec["key"])
        self.app = [to_int(c) for c in rec["cards"][self.me]]
        self.unseen = [c for c in DECK if c not in self.dead and c not in self.board0]
        need = 5 - self.street
        self.runouts = [tuple(sorted(p)) for p in combinations(self.unseen, need)]
        self._b0 = [to_int(c) for c in self.board0]
        self.app_rank = {ro: _EVAL.evaluate(self._b0 + [to_int(c) for c in ro], self.app) for ro in self.runouts}
        self._codes: Dict[Hand2, dict] = {}
        self._counts: Dict[Hand2, dict] = {}
        self._nets: Dict[tuple, tuple] = {}
        for y in self.sample:
            self.counts(y)

    def codes(self, y: Hand2) -> dict:
        """Showdown against the app for every runout missing y: 0 the app wins, 1 it loses,
        2 a tie."""
        if y not in self._codes:
            yi = [to_int(c) for c in y]
            out = {}
            for ro in self.runouts:
                if ro and (ro[0] in y or ro[-1] in y):
                    continue
                ra, rb = self.app_rank[ro], _EVAL.evaluate(self._b0 + [to_int(c) for c in ro], yi)
                out[ro] = 0 if ra < rb else 1 if ra > rb else 2
            self._codes[y] = out
        return self._codes[y]

    def counts(self, y: Hand2) -> dict:
        """Wins, losses and ties for y over every runout (key ()), and on the flop over every
        river given each turn card (key the turn card)."""
        if y not in self._counts:
            out = {(): [0, 0, 0]}
            for ro, code in self.codes(y).items():
                out[()][code] += 1
                if len(ro) == 2:
                    for t in ro:
                        out.setdefault(t, [0, 0, 0])[code] += 1
            self._counts[y] = out
        return self._counts[y]

    def nets(self, put_in, live) -> Optional[tuple]:
        """The app's net for a win, a loss and a tie (chips), or None if the hand is over for
        one of them (then the net doesn't depend on the cards)."""
        me, b = self.me, self.b
        if me not in live or b not in live:
            return None
        k = (put_in, live)
        if k not in self._nets:
            self._nets[k] = tuple(sim.split_pot(put_in, live, r).get(me, 0.0) - put_in[me]
                                  for r in ({me: 0, b: 1}, {me: 1, b: 0}, {me: 0, b: 0}))
        return self._nets[k]

    def value(self, board: tuple, put_in, live, y: Hand2) -> float:
        """The app's checked-down value (chips) with the opponent holding y, for these chips in
        (pass the all-in chips for the all-in value)."""
        nets = self.nets(put_in, live)
        if nets is None:
            return -put_in[self.me] if self.me not in live else sum(put_in) - put_in[self.me]
        extra = tuple(board[self.street:])
        if len(board) == 5:
            return nets[self.codes(y)[tuple(sorted(extra))]]
        c = self.counts(y)[extra[0] if extra else ()]
        return (c[0] * nets[0] + c[1] * nets[1] + c[2] * nets[2]) / (c[0] + c[1] + c[2])

    def average(self, pairs, board: tuple, put_in, live) -> float:
        """Weighted average value over (hand, weight) pairs of the sample (or, if none of the
        sample is among them, of the first three in a fixed order)."""
        sample = set(self.sample)
        use = [(y, m) for y, m in pairs if y in sample] or sorted(pairs)[:3]
        mass = sum(m for _, m in use)
        return sum(m * self.value(board, put_in, live, y) for y, m in use) / mass

    def final(self, rec: dict, y: Hand2) -> float:
        """The app's net at the end of the hand had the opponent held y (chips)."""
        put_in, live, board = rec["final_put_in"], rec["final_live"], tuple(rec["final_board"])
        nets = self.nets(put_in, live)
        if nets is None:
            return -put_in[self.me] if self.me not in live else sum(put_in) - put_in[self.me]
        ro = tuple(sorted(board[self.street:]))
        if y in self._codes:
            return nets[self._codes[y][ro]]
        ra, rb = self.app_rank[ro], _EVAL.evaluate([to_int(c) for c in board], [to_int(c) for c in y])
        return nets[0 if ra < rb else 1 if ra > rb else 2]


SAMPLE = 48  # candidate hands with showdown tables, used for every value (probabilities use them all)


def _sample(members: list, limit: int, key) -> list:
    if len(members) <= limit:
        return list(members)
    return random.Random(str(key)).sample(list(members), limit)


def _after(snap: dict, kind: str, b: int) -> tuple:
    """Chips in and seats still in after the opponent's move of this kind. A bet or raise the
    app has not called comes back to the opponent in a showdown, so for a checked-down value
    a raise counts as a call and a bet as a check."""
    put_in, live = list(snap["put_in"]), tuple(snap["live"])
    if kind == "fold":
        return tuple(put_in), tuple(i for i in live if i != b)
    if kind in ("call", "raise"):
        put_in[b] += min(snap["current"] - snap["bet"], snap["stack"])
    return tuple(put_in), live


# ------------------------------------------------------------------ the estimate
# How much of the all-in value each kind of correction mixes in: (node kind, board cards at
# the node, SPR band) -> weight. Any fixed weights keep the estimate unbiased; these were
# fitted once by least squares on training comparisons (fit_weights) and are frozen.
WEIGHTS: Dict[tuple, float] = {}


def group(kind: str, node: dict, me: int) -> tuple:
    """The weight group of a correction: "bot" or "card", the board cards when it happens, and
    the SPR band (tools/luck.py)."""
    import luck

    return kind, len(node["board"]), luck.spr_band(node, me) if "behind" in node else 0


def estimate_parts(rec: dict, sp: Split, mode: str = "hidden", cards: str = "both") -> Tuple[float, Dict[tuple, float]]:
    """The estimate as base - sum over groups of weight x part (big blinds): base uses the
    checked-down value everywhere, and each part is what mixing in the all-in value instead
    (as if everyone still in put in all its chips behind) changes in that group's corrections.
    See estimate."""
    import luck

    b, me = sp.b, sp.me
    w = {y: 1.0 for y in sp.cls}
    corr = 0.0
    parts: Dict[tuple, float] = {}
    e0 = split_event(rec, sp.j)
    for kind, idx in rec["events"][e0 + 1:]:
        if kind == "bot":
            snap = rec["bot_decisions"][idx]
            if snap["i"] != b:
                raise ValueError("another bot moved in a heads-up hand")
            if mode == "hidden":
                probs = {y: move_probs(rec, snap, y) for y in w}
                real = category(snap)
            else:
                probs = {y: {bot_move(rec, snap, y): 1.0} for y in w}
                real = tuple(snap["action"])
            total = sum(w.values())
            board = tuple(snap["board"])
            full = luck.all_in(snap["put_in"], snap["behind"], snap["live"]) if "behind" in snap else None
            exp_cd = exp_ai = 0.0
            real_cd = real_ai = None
            for a in {a for p in probs.values() for a, q in p.items() if q > 0}:
                support = [(y, w[y] * probs[y][a]) for y in w if probs[y].get(a, 0.0) > 0]
                put_in, live = _after(snap, a if mode == "hidden" else category(snap, a), b)
                v_cd = sp.average(support, board, put_in, live)
                v_ai = sp.average(support, board, full, live) if full is not None and b in live else v_cd
                share = sum(m for _, m in support) / total
                exp_cd += share * v_cd
                exp_ai += share * v_ai
                if a == real:
                    real_cd, real_ai = v_cd, v_ai
            corr += real_cd - exp_cd
            g = group("bot", snap, me)
            parts[g] = parts.get(g, 0.0) + ((real_ai - exp_ai) - (real_cd - exp_cd)) / BB
            w = {y: w[y] * probs[y][real] for y in w if probs[y].get(real, 0.0) > 0}
        elif kind == "card":
            node = rec["chance"][idx]
            if cards == "both" or (cards == "river" and len(node["board"]) == 4):
                c_cd, c_ai = _card_correction(sp, node, w)
                corr += c_cd
                g = group("card", node, me)
                parts[g] = parts.get(g, 0.0) + (c_ai - c_cd) / BB
            c = node["deal"][0]
            w = {y: m for y, m in w.items() if c not in y}
    mass = sum(w.values())
    final = sum(m * sp.final(rec, y) for y, m in w.items()) / mass
    return (final - corr) / BB, parts


def estimate(rec: dict, sp: Split, mode: str = "hidden", cards: str = "both",
             weights: Optional[Dict[tuple, float]] = None) -> float:
    """One variant's luck-adjusted result in big blinds for a hand that parts from the other
    variant at the app's decision sp.j, heads-up against bot sp.b after the flop. sp is built
    once for the hand (Split) and serves both variants and every replay from the split.

    mode "hidden": the opponent's random numbers after the split count as unknown (its moves
    have probabilities, move_probs). mode "known": they count as known (each move is the
    deterministic bot_move with the recorded seed); used to check the method exactly.
    cards: which board cards after the split get a correction ("both", "river", "none").
    weights: how much all-in value each group's corrections mix in (default WEIGHTS)."""
    base, parts = estimate_parts(rec, sp, mode, cards)
    wts = WEIGHTS if weights is None else weights
    return base - sum(wts.get(g, 0.0) * v for g, v in parts.items())


def _card_correction(sp: Split, node: dict, w: Dict[Hand2, float]) -> Tuple[float, float]:
    """V(the card that came) - sum over cards x of P(x) V(x), in chips, with V checked down and
    with V all in. Given the opponent holds y, the next card is uniform over the n - 2 cards
    that are neither known nor in y (n: the cards not known), so P(x) = m(x) / (total weight x
    (n - 2)), m(x) being the weight of the candidate hands without x. V(x) is the app's value
    after x, averaged over the sample's candidate hands without x."""
    import luck

    board, put_in, live = tuple(node["board"]), node["put_in"], tuple(node["live"])
    full = luck.all_in(put_in, node["behind"], live)
    came = node["deal"][0]
    options = [x for x in sp.unseen if x not in board]
    total = sum(w.values())
    by_card: Dict[str, float] = {}
    for y, m in w.items():
        by_card[y[0]] = by_card.get(y[0], 0.0) + m
        by_card[y[1]] = by_card.get(y[1], 0.0) + m
    exp_cd = exp_ai = 0.0
    came_cd = came_ai = None
    for x in options:
        m_x = total - by_card.get(x, 0.0)
        if m_x <= 1e-12 * total:
            continue
        pairs = [(y, m) for y, m in w.items() if x not in y]
        v_cd = sp.average(pairs, board + (x,), put_in, live)
        v_ai = sp.average(pairs, board + (x,), full, live)
        p_x = m_x / (total * (len(options) - 2))
        exp_cd += p_x * v_cd
        exp_ai += p_x * v_ai
        if x == came:
            came_cd, came_ai = v_cd, v_ai
    return came_cd - exp_cd, came_ai - exp_ai


def diff(rec_a: dict, rec_b: dict, j: int, sp: Optional[Split] = None) -> Optional[float]:
    """The hidden-cards estimate of the paired difference (other minus base) for a hand where
    the variants part at the app's decision j, or None when that is not heads-up after the
    flop (then the plain luck adjustment is used)."""
    b = opponent(rec_a, j)
    if b is None:
        return None
    sp = Split(rec_a, j, b) if sp is None else sp
    return estimate(rec_b, sp) - estimate(rec_a, sp)


# ------------------------------------------------------------------ fitting the weights
def load_rows(paths: Sequence[str]) -> List[dict]:
    """Rows saved by docs/research/runs/phase1_hidden_explore.py (one file per comparison),
    with the weight groups as tuples again."""
    import json

    out = []
    for path in paths:
        with open(path) as f:
            data = json.load(f)
        for r in data["rows"]:
            r = dict(r, parts={tuple(json.loads(g)): v for g, v in r["parts"].items()}, source=path)
            out.append(r)
    return out


def fit_weights(rows: Sequence[dict], ridge: float = 1e-3) -> Dict[tuple, float]:
    """Least-squares weights for the hidden-cards estimate: minimise the sum over hands of
    (base - sum over groups of weight x part)^2, no intercept (every part averages zero). A
    small ridge keeps groups with little data near 0."""
    import numpy as np

    groups = sorted({g for r in rows for g in r["parts"]})
    if not groups:
        return {}
    x = np.array([[r["parts"].get(g, 0.0) for g in groups] for r in rows if r["eligible"]])
    y = np.array([r["base"] for r in rows if r["eligible"]])
    xtx = x.T @ x
    lam = ridge * (np.trace(xtx) / len(groups) + 1e-12)
    w = np.linalg.solve(xtx + lam * np.eye(len(groups)), x.T @ y)
    return {g: float(v) for g, v in zip(groups, w)}


def apply_weights(rows: Sequence[dict], weights: Dict[tuple, float]) -> List[float]:
    """Each hand's estimate with these weights (hands not using the hidden-cards estimate keep
    their resampled luck-adjusted difference, saved as base)."""
    return [r["base"] - sum(weights.get(g, 0.0) * v for g, v in r["parts"].items()) for r in rows]


def main():
    import argparse

    from compare import summary

    ap = argparse.ArgumentParser(description="Fit the hidden-cards estimate's weights on training files.")
    ap.add_argument("command", choices=["fit"])
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    rows = load_rows(a.files)
    w = fit_weights(rows)
    print("WEIGHTS = {")
    for g, v in sorted(w.items()):
        print(f"    {g!r}: {v:.3f},")
    print("}")
    for path in a.files:
        sub = [r for r in rows if r["source"] == path]
        decks = [r["deck"] for r in sub]
        cells = [f"{name} {summary([r[name] for r in sub], decks)[1]:.2f}" for name in ("raw", "resampled", "base")]
        cells.append(f"fitted {summary(apply_weights(sub, w), decks)[1]:.2f}")
        print(f"{os.path.basename(path)}: " + ", ".join(cells) + " (SE, bb/100, in the fit)")


if __name__ == "__main__":
    main()
