"""Each player's likely cards at the start of the river, worked out from the betting so far.

The solver's answer is only as good as the ranges it is given. This module builds them
from what happened before the river (app/poker/history.py), one round at a time:

1. Before the flop: the preflop charts (app/poker/charts.py) give the hands for each part
   played: the raiser's opening hands from that seat, the caller's hands against that
   seat, the re-raiser's hands, and so on. The hero plays by them. Opponents don't, so
   their ranges are made as wide as their style is loose (app/poker/profiles.py): the best
   so-many percent of hands for that part, joined with the chart's hands.
2. Flop and turn: every hand is scored on the board as it was then (its made hand among
   all hands, with draws counted like the pairs they play like), and the score is turned
   into its place within the player's own range so far. What the player did then keeps
   the hands that do that:
   - a bet keeps the top of the range (less of it the bigger the bet), draws, and a
     share of the weakest hands as bluffs;
   - a call keeps the hands above the folding line (1 / (1 + bet) of the range, a little
     less in practice), and fewer of the very best, which would often have raised;
   - a check keeps everything but thins out the hands that would have bet, much more so
     for the player who could have bet last.
3. The hands with next to no weight are dropped, and the range is cut to a size the
   solver can handle in time.

Weights, not yes or no: a hand that fits the line badly is unlikely, not impossible. When
a round wasn't recorded, its size is guessed from how big the pot got, and who bet stays
unknown (then both players are treated as half bettor, half caller).

The numbers below are standard poker reasoning, not fitted to any opponent. How well the
ranges predict what opponents really hold is measured in docs/research/experiments.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from types import SimpleNamespace
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from app.poker import charts, exploits
from app.poker.history import HERO, LIMP, OTHER, VILLAIN, Line, StreetLine
from app.poker.ranges import PREFLOP_RANKING, class_combos

from .ranking import RANK_INDEX, SUIT_INDEX, _STRAIGHT_TOP, BoardRanker, _flush_value
from .spot import Combo, WeightedRange, canonical

MAX_COMBOS = 700  # the most combos a range keeps (the solver stays within its time and its 1% bar)
MIN_COMBOS = 30  # never fewer than this, however unusual the line
PRUNE = 0.03  # combos with less than this share of the biggest weight are dropped
FLOOR = 0.03  # a hand that doesn't fit a round's action keeps this much of its weight

# --- before the flop ------------------------------------------------------------------
RAISED_MAX, THREE_BET_MAX = 5.5, 16.0  # big blinds each put in: up to here one raise, then a re-raise, then more
TYPICAL_OPEN = 2.75  # big blinds, when the size of the raise isn't known
DEAD_BB = 1.0  # big blinds in the pot from players who folded before the flop
# How loose each style is before the flop: (share of hands played, share of hands raised).
# These sit inside the lines profiles.classify draws between the styles. None is a player
# with no style yet: the typical player the profiles assume until they know better.
RATES = {None: (0.28, 0.18), "tag": (0.22, 0.17), "nit": (0.13, 0.09), "station": (0.45, 0.08),
         "lag": (0.33, 0.25), "maniac": (0.60, 0.40)}
CHART_RAISES = 0.20  # the charts raise about this share of hands first in, over all seats
FOLLOWS_CHARTS = 0.15  # a player who raises at least this often gets the charts' hands in full
OFF_CHART = 0.25  # ... and one who raises less often keeps this much of the chart hands outside their own share
EXTRA = 0.8  # weight of the hands a style adds beyond the charts
CALLS_RAISE = 0.6  # share of the hands a player plays that also call a raise
CALLS_3BET = 0.5  # share of a player's opening hands that call a re-raise
REDEFENDS = 1.5  # the big blind defends this many times its usual share of hands (capped)
THREE_BETS = 0.3  # share of a player's raising hands that re-raise
TRAP = 0.25  # weight of the hands that would usually have raised instead of calling
PREFLOP_ORDER = ["UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB"]

# --- flop and turn --------------------------------------------------------------------
VALUE_TOP, VALUE_SLOPE = 0.50, 1.3  # a bet of s pots is for value with the top 0.5 / (1 + 1.3 s) of the range
BLUFFS = {3: 0.50, 4: 0.35}  # hands with nothing that bet, as a share of the value hands (flop, turn)
SEMI = {3: 0.60, 4: 0.45}  # how often a flush draw or open-ended straight draw bets
WEAK = 0.35  # the bottom of the range (nothing made, no draw): where the bluffs come from
MERGED_SMALL, MERGED = 0.20, 0.08  # how often middling hands bet (small bets, bigger bets)
# the flop bet of the player who raised before the flop: more bluffs, and middling hands bet often
FOLLOW_BLUFFS, FOLLOW_MERGED = 0.80, 0.40
CONTINUE = 0.85  # callers keep this times 1 / (1 + s) of their range against a bet of s pots
RAISE_TOP, RAISES = 0.07, 0.5  # the best 7% of a calling range would have raised half the time
TYPICAL_BET = 0.6  # the bet a check is compared with
BETS_LAST, BETS_FIRST = 0.75, 0.30  # how often a hand that wants to bet does, last to act / first
EDGE = 0.03  # how sharp the lines above are, as a share of the range
# what a draw plays like, as a place among all hands on that board (flop, turn)
DRAW_SCORE = {3: {3: 0.85, 2: 0.70, 1: 0.50}, 4: {3: 0.75, 2: 0.60, 1: 0.40}}


# ------------------------------------------------------------------ every combo
@dataclass(frozen=True)
class _Universe:
    combos: Tuple[Combo, ...]
    index: Dict[Combo, int]
    cards: np.ndarray  # (1326, 2) card ids, rank * 4 + suit
    ranks: np.ndarray  # (1326, 2)
    suits: np.ndarray  # (1326, 2)
    classes: Tuple[str, ...]  # the starting-hand class of each combo, e.g. "AKs"
    pct: np.ndarray  # share of all combos at least as strong before the flop (0 = the best)


@lru_cache(maxsize=1)
def _universe() -> _Universe:
    combos, classes, pct = [], [], []
    seen = 0
    for name in PREFLOP_RANKING:
        mine = [canonical(c) for c in class_combos(name)]
        seen += len(mine)
        combos += mine
        classes += [name] * len(mine)
        pct += [seen / 1326.0] * len(mine)
    ranks = np.array([[RANK_INDEX[c[0]] for c in combo] for combo in combos])
    suits = np.array([[SUIT_INDEX[c[1]] for c in combo] for combo in combos])
    return _Universe(tuple(combos), {c: i for i, c in enumerate(combos)}, ranks * 4 + suits, ranks, suits,
                     tuple(classes), np.array(pct))


@lru_cache(maxsize=None)
def _chart(text: str) -> np.ndarray:
    """1.0 for every combo in a chart line, 0.0 for the rest."""
    wanted = charts._classes(text) if text else frozenset()
    return np.array([1.0 if c in wanted else 0.0 for c in _universe().classes])


def _soft(x, cut: float, width: float = EDGE):
    """About 1 below the cut and 0 above it."""
    return 1.0 / (1.0 + np.exp(np.clip((np.asarray(x) - cut) / width, -50, 50)))


# ------------------------------------------------------------- before the flop
def _seat(seat: Optional[str]) -> Optional[str]:
    return "SB" if seat == "BTN/SB" else seat


def _earlier(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    """a acts before b before the flop. None when a seat isn't known."""
    a, b = _seat(a), _seat(b)
    if a not in PREFLOP_ORDER or b not in PREFLOP_ORDER or a == b:
        return None
    return PREFLOP_ORDER.index(a) < PREFLOP_ORDER.index(b)


def pot_type(size: float) -> str:
    """"limped", "raised", "3bet" or "4bet", from the big blinds each player put in."""
    if size <= LIMP:
        return "limped"
    if size <= RAISED_MAX:
        return "raised"
    return "3bet" if size <= THREE_BET_MAX else "4bet"


def _open_chart(seat: Optional[str]) -> str:
    if seat == "BB":
        return charts.ISO["BB"]  # the big blind raised players who only called
    if seat in charts.OPEN:
        return charts.OPEN[seat]
    if seat in charts.NINE_MAX_EARLY:
        return charts.OPEN["EP9"]
    return charts.OPEN["UTG" if seat == "LJ" else "CO"]


def _vs_3bet_key(seat: Optional[str], raiser: Optional[str]) -> Tuple[str, str]:
    g = charts._group(seat)
    if g in ("SB", "BTN"):
        return (g, "blind")
    key = (g, "blind" if _seat(raiser) in ("SB", "BB") else "behind")
    return key if key in charts.VS_3BET else ("CO", "blind")


def _charts(seat: Optional[str], other_seat: Optional[str], kind: str, raised: bool) -> Tuple[np.ndarray, np.ndarray]:
    """(the chart's hands for this part, the stronger hands that would usually have raised
    instead), for a player who raised or called in a raised, 3bet or 4bet pot."""
    none = np.zeros(1326)
    if kind == "raised":
        if raised:
            if _earlier(other_seat, seat) and seat != "BB":  # the caller acted first: they limped, this raised them
                return _chart(charts.ISO[charts._side(seat)]), none
            return _chart(_open_chart(seat)), none
        reraise, call = charts.VS_OPEN[charts._vs_open_key(seat, other_seat)]
        if not call:  # the chart re-raises or folds from the small blind; real players also call
            call = charts.VS_OPEN[charts._vs_open_key("BB", other_seat)][1]
        return _chart(call), _chart(reraise)
    if kind == "3bet":
        if raised:
            return _chart(charts.VS_OPEN[charts._vs_open_key(seat, other_seat)][0]), none
        again, call = charts.VS_3BET[_vs_3bet_key(seat, other_seat)]
        return _chart(call), _chart(again)
    shove, call = charts.VS_4BET
    if raised:
        return np.maximum(_chart(charts.VS_3BET[_vs_3bet_key(seat, other_seat)][0]), _chart(shove)), none
    return np.maximum(_chart(call), 0.5 * _chart(shove)), none


def preflop_weights(seat: Optional[str], other_seat: Optional[str], size: float, raised: Optional[bool],
                    style=None, rates: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """A weight for each of the 1326 combos: how well it fits what this player did before
    the flop. size: big blinds each put in. raised: True when this player made the last
    raise, False when they called it, None when it isn't known who did (then the seats
    decide the likeliest story). style: one of profiles.STYLES, None, or HERO. rates: the
    share of hands this opponent has played and raised so far, when known (it replaces the
    style's typical numbers).

    The hero plays by the charts. An opponent's hands are the chart's for that part of the
    hand, made wider or narrower by how loose their style is: a player who plays 45% of
    hands calls a raise with far more than the chart does, a player who plays 13% with less.
    """
    u = _universe()
    kind = pot_type(size)
    seat, other_seat = _seat(seat), _seat(other_seat)
    hero = style == HERO
    played, raises = RATES[None if hero or style not in RATES else style]
    if rates is not None and not hero:
        played, raises = min(1.0, max(0.02, float(rates[0]))), min(1.0, max(0.01, float(rates[1])))
    opens = min(0.9, raises / CHART_RAISES * float(_chart(_open_chart(seat)).sum()) / 1326.0)  # from this seat

    if kind == "limped":
        if seat == "BB":  # checked their blind: anything, less often the hands that raise
            return 1.0 - (1.0 - TRAP) * (_chart(charts.ISO["BB"]) if hero else _soft(u.pct, 0.6 * raises, 0.02))
        if hero:  # the charts only ever call along with these
            return np.maximum(_chart(charts.OVERLIMP), 0.05)
        return _soft(u.pct, min(0.9, 1.1 * played), 0.05) * (1.0 - (1.0 - TRAP) * _soft(u.pct, opens, 0.03))
    if raised is None:
        first = _earlier(seat, other_seat)  # the earlier seat opens; a re-raise comes from the later one
        if first is None:  # seats unknown: a plain share of the best hands for both
            return _soft(u.pct, {"raised": 0.35, "3bet": 0.12, "4bet": 0.05}[kind], 0.04)
        raised = first if kind in ("raised", "4bet") else not first

    chart, stronger = _charts(seat, other_seat, kind, raised)
    if hero:
        return np.maximum(np.maximum(chart, TRAP * stronger), 0.02)
    if kind == "raised" and not raised and _earlier(seat, other_seat) and seat != "BB":
        # acted before the raiser and still called: they limped first, then called the raise
        return _soft(u.pct, min(0.9, 0.8 * played), 0.05) * (1.0 - (1.0 - TRAP) * _soft(u.pct, opens, 0.03))
    if raised:
        share = {"raised": opens, "3bet": THREE_BETS * raises, "4bet": 0.1 * raises + 0.01}[kind]
    elif kind == "raised":
        share = min(0.9, REDEFENDS * played) if seat == "BB" else CALLS_RAISE * played
    else:
        share = CALLS_3BET * opens if kind == "3bet" else 0.25 * opens
    own = _soft(u.pct, share, 0.03)  # the best `share` of hands, which is what their style plays here
    keep = 1.0 if raises >= FOLLOWS_CHARTS else OFF_CHART
    w = np.maximum(EXTRA * own, chart * np.maximum(keep, own))
    return w * (1.0 - (1.0 - TRAP) * stronger) if raises >= FOLLOWS_CHARTS else w


# --------------------------------------------------------------- flop and turn
@lru_cache(maxsize=256)
def _straight_outs(board_mask: int) -> np.ndarray:
    """For each pair of hole-card ranks (13 x 13): how many ranks would complete a straight
    that the board alone wouldn't make with that card. 0 when a straight is already made."""
    out = np.zeros((13, 13), dtype=np.int8)
    shared = [r for r in range(13) if _STRAIGHT_TOP[board_mask | 1 << r] >= 0]
    for r1 in range(13):
        for r2 in range(r1, 13):
            mask = board_mask | 1 << r1 | 1 << r2
            if _STRAIGHT_TOP[mask] >= 0:
                continue
            n = sum(1 for r in range(13) if r not in shared and not mask >> r & 1
                    and _STRAIGHT_TOP[mask | 1 << r] >= 0)
            out[r1, r2] = out[r2, r1] = n
    return out


@lru_cache(maxsize=128)
def street_scores(board: Tuple[str, ...]) -> Tuple[np.ndarray, np.ndarray]:
    """(score, draw) for each of the 1326 combos on a flop or turn board.

    score: the hand's place among all hands that can be held on this board, 0 (worst) to 1
    (best), by the hand made so far; a draw is lifted to the place of the made hands it
    plays like. -1 for combos that use a board card.
    draw: 3 = a flush draw with a straight draw, 2 = a flush draw or an open-ended straight
    draw, 1 = a gutshot, 0 = none.
    """
    u = _universe()
    n = len(board)
    ranker = BoardRanker(board)
    ids = np.array([RANK_INDEX[c[0]] * 4 + SUIT_INDEX[c[1]] for c in board])
    live = ~np.isin(u.cards, ids).any(axis=1)
    r1, r2, s1, s2 = u.ranks[:, 0], u.ranks[:, 1], u.suits[:, 0], u.suits[:, 1]
    values = np.array(ranker._table, dtype=np.int64)[r1 * 13 + r2]
    fs = ranker._flush_suit
    if fs is not None:  # three or more of one suit on the board: some hands hold a flush
        masks = ranker._flush_mask | np.where(s1 == fs, 1 << r1, 0) | np.where(s2 == fs, 1 << r2, 0)
        for m in np.unique(masks[live]):
            if bin(int(m)).count("1") >= 5:
                hit = live & (masks == m)
                values[hit] = np.maximum(values[hit], _flush_value(int(m)))
    # place among all live hands, equal hands sharing the middle of their stretch
    _, inverse, counts = np.unique(values[live], return_inverse=True, return_counts=True)
    below = np.cumsum(counts) - counts
    place = (below[inverse] + 0.5 * counts[inverse]) / max(1, int(live.sum()))
    score = np.full(len(u.combos), -1.0)
    score[live] = place

    draw = np.zeros(len(u.combos), dtype=np.int8)
    if n < 5:
        board_suits = np.bincount(ids % 4, minlength=4)
        flush_draw = np.zeros(len(u.combos), dtype=bool)
        for s in range(4):
            held = (s1 == s).astype(int) + (s2 == s)
            top = np.maximum(np.where(s1 == s, r1, -1), np.where(s2 == s, r2, -1))
            # four to a flush with both cards, or with one card that is a jack or better
            flush_draw |= (board_suits[s] + held == 4) & ((held == 2) | ((held == 1) & (top >= RANK_INDEX["J"])))
        board_mask = 0
        for c in ids:
            board_mask |= 1 << int(c // 4)
        outs = _straight_outs(board_mask)[r1, r2]
        draw = np.where(flush_draw & (outs >= 1), 3,
                        np.where(flush_draw | (outs >= 2), 2, np.where(outs == 1, 1, 0))).astype(np.int8)
        for level, at_least in DRAW_SCORE[n].items():
            score = np.where(live & (draw == level), np.maximum(score, at_least), score)
    draw[~live] = 0
    return score, draw


def _place(score: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Each hand's place within this range: the share of the range's weight below it, plus
    half of what is level with it. 0 = the bottom of the range, 1 = the top."""
    _, inverse = np.unique(score, return_inverse=True)
    grouped = np.bincount(inverse, weights=weights)
    below = np.cumsum(grouped) - grouped
    total = float(grouped.sum())
    if total <= 0:
        return np.full(len(score), 0.5)
    return (below[inverse] + 0.5 * grouped[inverse]) / total


def _top(q: np.ndarray, share: float) -> np.ndarray:
    """About 1 for the top `share` of the range and 0 below it."""
    return 1.0 - _soft(q, 1.0 - share)


def bets(q: np.ndarray, draw: np.ndarray, size: float, cards: int, style=None, follows: bool = False) -> np.ndarray:
    """How often each hand bets `size` pots on this round (cards: 3 on the flop, 4 on the
    turn), from its place q in the player's range. follows: the player raised before the
    flop and this is the flop (a bet that follows a raise comes from far more hands)."""
    value = VALUE_TOP / (1.0 + VALUE_SLOPE * size)
    air = (FOLLOW_BLUFFS if follows else BLUFFS[cards]) * value
    value, air = exploits.betting_share(SimpleNamespace(style=style), value, air)
    p = _top(q, value)
    p = np.maximum(p, min(1.0, air / WEAK) * _soft(q, WEAK))  # some of the weakest hands bluff
    middling = FOLLOW_MERGED if follows else (MERGED_SMALL if size < 0.4 else MERGED)
    p = np.maximum(p, middling)  # middling hands bet now and then
    p = np.maximum(p, SEMI[cards] * (draw >= 2))
    return np.clip(p, 0.0, 1.0)


def calls(q: np.ndarray, size: float, style=None) -> np.ndarray:
    """How often each hand calls a bet of `size` pots (and doesn't fold or raise)."""
    keep = min(1.0, CONTINUE / (1.0 + size))
    keep = min(1.0, exploits.continue_share(SimpleNamespace(style=style), keep))
    return _top(q, keep) * (1.0 - RAISES * _top(q, RAISE_TOP))


def checks(q: np.ndarray, draw: np.ndarray, cards: int, last: bool, style=None) -> np.ndarray:
    """How often each hand checks when it could have bet. last: nobody acts after them."""
    return 1.0 - (BETS_LAST if last else BETS_FIRST) * bets(q, draw, TYPICAL_BET, cards, style)


def _acted(street: StreetLine, me: str, q, draw, cards: int, in_position: bool, style,
           follows: bool = False) -> np.ndarray:
    """How well each hand fits what `me` (HERO or VILLAIN) did on this round. follows: `me`
    raised before the flop and this is the flop."""
    if street.size <= 0:
        return checks(q, draw, cards, in_position, style)
    if street.aggressor == me:
        return bets(q, draw, street.size, cards, style, follows)
    if street.aggressor is None:  # a bet went in, but whose isn't known
        return 0.5 * (bets(q, draw, street.size, cards, style) + calls(q, street.size, style))
    return calls(q, street.size, style)


# ------------------------------------------------------- what wasn't recorded
# How common each kind of pot is: (big blinds each put in before the flop, share of hands).
POT_TYPES = ((1.0, 0.25), (TYPICAL_OPEN, 0.60), (9.0, 0.12), (22.0, 0.03))
BET_ROUNDS = (0.35, 0.35, 0.30)  # how often neither, one or both of the flop and turn see a bet
NO_BET, BIG_BET = 1.25, 1.25  # the pot grew by less than this: no bet; a guessed bet is at most this share of the pot


def _bets_needed(growth: float, rounds: int) -> Optional[int]:
    """How many of `rounds` unknown rounds must have seen a bet for the pot to grow this
    much. None when even a big bet in each doesn't explain it, or the pot is too small."""
    if growth < 0.75:
        return None
    for n in range(rounds + 1):
        if growth <= (NO_BET if n == 0 else (1.0 + 2.0 * BIG_BET) ** n):
            return n
    return None


def fill_in(line: Optional[Line], pot_bb: Optional[float]) -> Line:
    """The line with the rounds that weren't recorded guessed from the size of the pot at
    the start of the river (in big blinds): the likeliest kind of pot before the flop and
    number of bets after it that explain that size. Who bet in a guessed round stays
    unknown. Without a pot size, a typical raise before the flop is assumed and unknown
    rounds are left alone."""
    line = line or Line()
    pre, flop, turn = line.streets
    if not pot_bb or pot_bb <= 0:
        return Line(pre if pre.known else StreetLine(TYPICAL_OPEN), flop, turn, line.river)
    grown = 1.0
    for s in (flop, turn):
        if s.known:
            grown *= 1.0 + 2.0 * s.size
    unknown = sum(1 for s in (flop, turn) if not s.known)

    def left(each: float) -> float:
        """How much the unknown rounds grew the pot, if each put in this much before the flop."""
        return pot_bb / ((2.0 * each + DEAD_BB) * grown)

    if not pre.known:
        best = None
        for each, share in POT_TYPES:
            n = _bets_needed(left(each), unknown)
            if n is not None:
                likely = share * (BET_ROUNDS[n] if unknown == 2 else 0.5 if unknown == 1 else 1.0)
                if best is None or likely > best[0]:
                    best = (likely, each)
        if best is None:  # nothing fits: the pot type whose size before the flop is nearest
            best = (0.0, min((e for e, _ in POT_TYPES), key=lambda e: abs(math.log(max(left(e), 1e-9)))))
        pre = StreetLine(best[1])
    growth = left(pre.size)
    n = _bets_needed(growth, unknown)
    if n is None:
        n = unknown if growth > 1.0 else 0
    each_bet = StreetLine(min(3.0, max(0.0, (growth ** (1.0 / n) - 1.0) / 2.0))) if n else StreetLine(0.0)
    if unknown == 2:  # one bet: the flop's, the commonest
        flop, turn = each_bet, (each_bet if n == 2 else StreetLine(0.0))
    elif unknown == 1:
        flop, turn = (each_bet, turn) if not flop.known else (flop, each_bet)
    return Line(pre, flop, turn, line.river)


# ------------------------------------------------------------------- the ranges
@dataclass(frozen=True)
class RangeEstimate:
    hero: WeightedRange
    villain: WeightedRange
    line: Line  # the line the ranges were built from, guesses included
    guessed: bool  # some of it was guessed from the size of the pot


def _as_range(weights: np.ndarray, live: np.ndarray, max_combos: int) -> WeightedRange:
    u = _universe()
    w = np.where(live, weights, 0.0)
    top = float(w.max())
    if top <= 0:
        w, top = live.astype(float), 1.0
    order = np.argsort(-w, kind="stable")
    keep = [int(i) for i in order[:max_combos] if w[i] >= PRUNE * top]
    if len(keep) < MIN_COMBOS:
        keep = [int(i) for i in order[:MIN_COMBOS] if live[i]]
    keep.sort()
    return tuple((u.combos[i], round(float(max(w[i] / top, 1e-4)), 4)) for i in keep)


@lru_cache(maxsize=64)
def _estimate(board: Tuple[str, ...], line: Line, hero_in_position: bool, hero_seat: Optional[str],
              villain_seat: Optional[str], villain_style: Optional[str],
              villain_rates: Optional[Tuple[float, float]], max_combos: int):
    u = _universe()
    ids = np.array([RANK_INDEX[c[0]] * 4 + SUIT_INDEX[c[1]] for c in board])
    live = ~np.isin(u.cards, ids).any(axis=1)
    pre = line.preflop
    who = {HERO: (hero_seat, villain_seat, HERO, hero_in_position),
           VILLAIN: (villain_seat, hero_seat, villain_style, not hero_in_position)}
    out = {}
    for me, (seat, other_seat, style, in_position) in who.items():
        raised = None if pre.aggressor is None else pre.aggressor == me
        if pre.aggressor == OTHER and pot_type(pre.size) == "raised":
            other_seat = None  # both called a third player's raise
        w = np.where(live, preflop_weights(seat, other_seat, pre.size, raised, style,
                                           None if me == HERO else villain_rates), 0.0)
        for cards, street in ((3, line.flop), (4, line.turn)):
            if not street.known or len(board) < cards:
                continue
            score, draw = street_scores(tuple(board[:cards]))
            follows = cards == 3 and pre.aggressor == me and pot_type(pre.size) != "limped"
            fit = _acted(street, me, _place(score, w), draw, cards, in_position,
                         None if style == HERO else style, follows)
            w = w * (FLOOR + (1.0 - FLOOR) * fit)
        out[me] = _as_range(w, live, max_combos)
    return out[HERO], out[VILLAIN]


def river_ranges(board: Sequence[str], line: Optional[Line] = None, *, hero_in_position: bool,
                 pot_bb: Optional[float] = None, hero_seat: Optional[str] = None,
                 villain_seat: Optional[str] = None, villain_style: Optional[str] = None,
                 villain_rates: Optional[Tuple[float, float]] = None,
                 max_combos: int = MAX_COMBOS) -> RangeEstimate:
    """Both players' ranges at the start of the river.

    line: the betting so far (None or partly unknown: guessed from pot_bb, the pot at the
    start of the river in big blinds). Seats are position codes ("BTN", "BB", ...).
    villain_style is one of profiles.STYLES or None; villain_rates the share of hands they
    have played and raised before the flop so far (profiles.rates), when known.
    """
    board = tuple(board)
    if len(board) != 5 or len(set(board)) != 5:
        raise ValueError("A river board has five different cards.")
    full = fill_in(line, pot_bb)
    guessed = line is None or any(not s.known for s in line.streets)
    key = Line(full.preflop, full.flop, full.turn)  # the river's own bets don't change the ranges
    seen = None if villain_rates is None else (round(float(villain_rates[0]), 2), round(float(villain_rates[1]), 2))
    hero, villain = _estimate(board, key, bool(hero_in_position), hero_seat, villain_seat, villain_style,
                              seen, int(max_combos))
    return RangeEstimate(hero, villain, full, guessed)
