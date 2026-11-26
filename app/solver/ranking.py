"""Fast hand ranking on a fixed river board.

On the river the board never changes, so most of the work can be done once per board:

- Without a flush, a hand's value depends only on the ranks of the two hole cards. There
  are 91 rank pairs (13 pairs plus 78 unpaired), so the board's 91 values are worked out
  once and every combo is then a table lookup.
- A flush needs at least three cards of one suit on the board, so at most one suit can make
  one. For that suit the value depends only on which hole cards share it, and the few
  flush masks that occur are cached.

A value is an int and higher is better (the opposite of treys, where 1 is the best). It
encodes the hand category and up to five tie-breaking ranks, so two hands tie exactly
when their values are equal. The tests check the order against treys on every combo of
many boards.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}
SUIT_INDEX = {s: i for i, s in enumerate(SUITS)}

# hand categories, worst to best (the value's top bits)
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
CATEGORY_NAMES = ("High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush", "Full House",
                  "Four of a Kind", "Straight Flush")
_SHIFT = 20  # category << 20, then five 4-bit ranks


def _straight_table() -> List[int]:
    """For every 13-bit rank mask: the top rank of the best straight in it, or -1."""
    windows = [(top, sum(1 << r for r in range(top - 4, top + 1))) for top in range(12, 3, -1)]
    windows.append((3, (1 << 12) | 0b1111))  # the wheel, A-2-3-4-5, is five high
    table = []
    for mask in range(1 << 13):
        table.append(next((top for top, w in windows if mask & w == w), -1))
    return table


_STRAIGHT_TOP = _straight_table()


def _pack(category: int, ranks: Sequence[int]) -> int:
    v = category
    for i in range(5):
        v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
    return v


def _top_ranks(mask: int, n: int) -> List[int]:
    out = []
    for r in range(12, -1, -1):
        if mask >> r & 1:
            out.append(r)
            if len(out) == n:
                break
    return out


def _rank_value(counts: Sequence[int]) -> int:
    """Best hand that ignores suits (no flushes), from the count of each rank (5 to 7 cards)."""
    mask = 0
    quads, trips, pairs = [], [], []
    for r in range(12, -1, -1):
        c = counts[r]
        if not c:
            continue
        mask |= 1 << r
        if c == 4:
            quads.append(r)
        elif c == 3:
            trips.append(r)
        elif c == 2:
            pairs.append(r)
    if quads:
        q = quads[0]
        return _pack(QUADS, [q] + _top_ranks(mask & ~(1 << q), 1))
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max(trips[1] if len(trips) > 1 else -1, pairs[0] if pairs else -1)
        return _pack(FULL_HOUSE, [t, p])
    top = _STRAIGHT_TOP[mask]
    if top >= 0:
        return _pack(STRAIGHT, [top])
    if trips:
        t = trips[0]
        return _pack(TRIPS, [t] + _top_ranks(mask & ~(1 << t), 2))
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        return _pack(TWO_PAIR, [p1, p2] + _top_ranks(mask & ~(1 << p1) & ~(1 << p2), 1))
    if pairs:
        p = pairs[0]
        return _pack(PAIR, [p] + _top_ranks(mask & ~(1 << p), 3))
    return _pack(HIGH_CARD, _top_ranks(mask, 5))


def _flush_value(suit_mask: int) -> int:
    """Best flush (or straight flush) from the ranks of one suit (five or more of them)."""
    top = _STRAIGHT_TOP[suit_mask]
    if top >= 0:
        return _pack(STRAIGHT_FLUSH, [top])
    return _pack(FLUSH, _top_ranks(suit_mask, 5))


def _split(card: str) -> Tuple[int, int]:
    try:
        return RANK_INDEX[card[0]], SUIT_INDEX[card[1]]
    except (KeyError, IndexError, TypeError):
        raise ValueError(f"Not a card: {card!r}") from None


def hand_value(cards: Sequence[str]) -> int:
    """Value of the best five-card hand among 5 to 7 cards (higher is better). The plain
    version, used to check the table-based ranking."""
    if not 5 <= len(cards) <= 7 or len(set(cards)) != len(cards):
        raise ValueError("Need 5 to 7 different cards.")
    counts = [0] * 13
    suit_masks = [0] * 4
    for c in cards:
        r, s = _split(c)
        counts[r] += 1
        suit_masks[s] |= 1 << r
    best = _rank_value(counts)
    for m in suit_masks:
        if bin(m).count("1") >= 5:
            best = max(best, _flush_value(m))
    return best


def category(value: int) -> int:
    return value >> _SHIFT


def category_name(value: int) -> str:
    return CATEGORY_NAMES[category(value)]


class RiverRanker:
    """Values of hole-card combos on one five-card board, from tables built once."""

    def __init__(self, board: Sequence[str]):
        board = tuple(board)
        if len(board) != 5 or len(set(board)) != 5:
            raise ValueError("A river board has five different cards.")
        self.board = board
        counts = [0] * 13
        suit_masks = [0] * 4
        for c in board:
            r, s = _split(c)
            counts[r] += 1
            suit_masks[s] |= 1 << r
        self._dead = set(board)
        # the one suit that can make a flush (three or more on the board), if any
        self._flush_suit: Optional[int] = next((s for s in range(4) if bin(suit_masks[s]).count("1") >= 3), None)
        self._flush_mask = suit_masks[self._flush_suit] if self._flush_suit is not None else 0
        self._flush_cache: Dict[int, int] = {}
        self._table = [0] * 169
        for r1 in range(13):
            for r2 in range(r1, 13):
                c = list(counts)
                c[r1] += 1
                c[r2] += 1
                v = -1 if max(c) > 4 else _rank_value(c)  # -1: no such combo exists on this board
                self._table[r1 * 13 + r2] = self._table[r2 * 13 + r1] = v

    def value(self, combo: Sequence[str]) -> int:
        a, b = combo
        if a == b or a in self._dead or b in self._dead:
            raise ValueError(f"{a}{b} can't be held on {' '.join(self.board)}.")
        r1, s1 = _split(a)
        r2, s2 = _split(b)
        v = self._table[r1 * 13 + r2]
        fs = self._flush_suit
        if fs is not None:
            m = self._flush_mask | (1 << r1 if s1 == fs else 0) | (1 << r2 if s2 == fs else 0)
            if bin(m).count("1") >= 5:
                fv = self._flush_cache.get(m)
                if fv is None:
                    fv = self._flush_cache[m] = _flush_value(m)
                v = max(v, fv)
        return v

    def values(self, combos: Sequence[Sequence[str]]) -> np.ndarray:
        return np.fromiter((self.value(c) for c in combos), dtype=np.int64, count=len(combos))


def rank_range(board: Sequence[str], combos: Sequence[Sequence[str]]) -> np.ndarray:
    """The value of every combo in a range on this river board (higher is better)."""
    return RiverRanker(board).values(combos)


def dense_ranks(values: Sequence[int]) -> np.ndarray:
    """0 for the weakest value, 1 for the next, ...; equal values share a rank."""
    v = np.asarray(values)
    _, inverse = np.unique(v, return_inverse=True)
    return inverse.astype(np.int64)


def card_index(card: str) -> int:
    r, s = _split(card)
    return r * 4 + s


def matchups(board: Sequence[str], combos_a: Sequence[Sequence[str]],
             combos_b: Sequence[Sequence[str]]) -> Tuple[np.ndarray, np.ndarray]:
    """Showdowns between two ranges on a river board.

    Returns (outcome, possible), both shaped (len(combos_a), len(combos_b)):
    outcome is +1 where a's combo wins, -1 where it loses and 0 for a split; possible is
    False where the two combos share a card (that deal can't happen, so it carries no
    weight).
    """
    ranker = RiverRanker(board)
    va, vb = ranker.values(combos_a), ranker.values(combos_b)
    outcome = np.sign(va[:, None] - vb[None, :]).astype(np.int8)
    ca = np.array([[card_index(x) for x in c] for c in combos_a], dtype=np.int16).reshape(-1, 2)
    cb = np.array([[card_index(x) for x in c] for c in combos_b], dtype=np.int16).reshape(-1, 2)
    clash = np.zeros((len(ca), len(cb)), dtype=bool)
    for i in range(2):
        for j in range(2):
            clash |= ca[:, i, None] == cb[None, :, j]
    return outcome, ~clash
