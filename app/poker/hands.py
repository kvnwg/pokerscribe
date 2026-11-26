"""Hand evaluation (via the treys library) and plain-English hand descriptions."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import List, Optional, Sequence, Tuple

from treys import Card, Evaluator

RANKS = "23456789TJQKA"
SUITS = "shdc"
DECK = [r + s for r in RANKS for s in SUITS]
_EVAL = Evaluator()

NAME = {"A": "Ace", "K": "King", "Q": "Queen", "J": "Jack", "T": "Ten", "9": "Nine", "8": "Eight", "7": "Seven",
        "6": "Six", "5": "Five", "4": "Four", "3": "Three", "2": "Two"}
PLURAL = {"A": "Aces", "K": "Kings", "Q": "Queens", "J": "Jacks", "T": "Tens", "9": "Nines", "8": "Eights",
          "7": "Sevens", "6": "Sixes", "5": "Fives", "4": "Fours", "3": "Threes", "2": "Twos"}
# treys classes: 1 straight flush ... 9 high card
CATEGORY = {1: "Straight Flush", 2: "Four of a Kind", 3: "Full House", 4: "Flush", 5: "Straight",
            6: "Three of a Kind", 7: "Two Pair", 8: "Pair", 9: "High Card"}


@lru_cache(maxsize=None)
def to_int(card: str) -> int:
    return Card.new(card)


def evaluate(hole: Sequence[str], board: Sequence[str]) -> int:
    """treys rank: 1 (royal flush) .. 7462 (worst high card). Lower is better."""
    return _EVAL.evaluate([to_int(c) for c in board], [to_int(c) for c in hole])


def category(hole: Sequence[str], board: Sequence[str]) -> int:
    return _EVAL.get_rank_class(evaluate(hole, board))


def _straight_high(ranks: set) -> Optional[int]:
    vals = {RANKS.index(r) for r in ranks}
    if 12 in vals:
        vals.add(-1)  # wheel
    for top in range(12, 2, -1):
        if all(v in vals for v in range(top - 4, top + 1)):
            return top
    return None


def describe(cards: Sequence[str]) -> str:
    """Best five-card hand among 5-7 cards, e.g. 'Two Pair, Aces and Eights'."""
    ranks = [c[0] for c in cards]
    suits = Counter(c[1] for c in cards)
    flush_suit = next((s for s, n in suits.items() if n >= 5), None)
    if flush_suit:
        fr = {c[0] for c in cards if c[1] == flush_suit}
        hi = _straight_high(fr)
        if hi is not None:
            return "Royal Flush" if hi == 12 else f"Straight Flush, {NAME[RANKS[hi]]} high"
    counts = Counter(ranks)
    by = sorted(counts.items(), key=lambda kv: (-kv[1], -RANKS.index(kv[0])))
    if by[0][1] == 4:
        return f"Four of a Kind, {PLURAL[by[0][0]]}"
    trips = [r for r, n in by if n == 3]
    pairs = [r for r, n in by if n == 2]
    if trips and (len(trips) > 1 or pairs):
        full = trips[1] if len(trips) > 1 else pairs[0]
        return f"Full House, {PLURAL[trips[0]]} full of {PLURAL[full]}"
    if flush_suit:
        top = max((c[0] for c in cards if c[1] == flush_suit), key=RANKS.index)
        return f"Flush, {NAME[top]} high"
    hi = _straight_high(set(ranks))
    if hi is not None:
        return f"Straight, {NAME['5' if hi == 3 else RANKS[hi]]} high"
    if trips:
        return f"Three of a Kind, {PLURAL[trips[0]]}"
    if len(pairs) >= 2:
        return f"Two Pair, {PLURAL[pairs[0]]} and {PLURAL[pairs[1]]}"
    if pairs:
        return f"Pair of {PLURAL[pairs[0]]}"
    return f"High Card, {NAME[max(ranks, key=RANKS.index)]}"


def describe_hand(hole: Sequence[str], board: Sequence[str]) -> str:
    """Your hand in words, from your point of view: with no pair, the high card that counts
    is your own. "Ace high" when the ace is on the board would make it sound like you have
    the ace, when everyone does."""
    if len(board) < 3:
        return describe(list(hole) + list(board))
    if category(hole, board) != 9:
        return describe(list(hole) + list(board))
    mine = max((c[0] for c in hole), key=RANKS.index)
    top = max((c[0] for c in list(hole) + list(board)), key=RANKS.index)
    if mine == top:
        return f"{NAME[mine]} high, no pair"
    return f"No pair, {NAME[mine]} high"


def preflop_class(hole: Sequence[str]) -> str:
    a, b = sorted(hole, key=lambda c: -RANKS.index(c[0]))
    if a[0] == b[0]:
        return a[0] + b[0]
    return a[0] + b[0] + ("s" if a[1] == b[1] else "o")


def describe_preflop(hole: Sequence[str]) -> str:
    cls = preflop_class(hole)
    if len(cls) == 2:
        return f"Pocket {PLURAL[cls[0]]}"
    return f"{NAME[cls[0]]} {NAME[cls[1]]} {'suited' if cls[2] == 's' else 'offsuit'}"


def draws(hole: Sequence[str], board: Sequence[str]) -> List[str]:
    """Flush and straight draws that use at least one hole card (flop and turn only)."""
    if len(board) not in (3, 4):
        return []
    cards = list(hole) + list(board)
    out = []
    cat = category(hole, board)
    suits = Counter(c[1] for c in cards)
    if cat > 4:  # not already a flush or better
        for s, n in suits.items():
            if n == 4 and any(c[1] == s for c in hole):
                out.append("flush draw")
            elif n == 3 and len(board) == 3 and sum(c[1] == s for c in hole) >= 1 and sum(c[1] == s for c in board) <= 2:
                out.append("backdoor flush draw")
    if cat > 5:  # not already a straight or better
        mine = {c[0] for c in cards}
        board_only = {c[0] for c in board}
        outs = [r for r in RANKS if r not in mine and _straight_high(mine | {r}) is not None
                and _straight_high(board_only | {r}) is None]
        if len(outs) >= 2:
            out.append("open-ended straight draw")
        elif len(outs) == 1:
            out.append("gutshot straight draw")
    # keep only the strongest flush draw label
    if "flush draw" in out and "backdoor flush draw" in out:
        out.remove("backdoor flush draw")
    return out


def board_category(cards: Sequence[str]) -> int:
    """treys-style class (1 best .. 9 worst) of the cards on their own, any count."""
    counts = sorted(Counter(c[0] for c in cards).values(), reverse=True)
    suits = Counter(c[1] for c in cards)
    flush = any(n >= 5 for n in suits.values())
    straight = len(cards) >= 5 and _straight_high({c[0] for c in cards}) is not None
    if len(cards) >= 5 and flush:
        flush_ranks = {c[0] for c in cards if suits[c[1]] >= 5}
        if _straight_high(flush_ranks) is not None:
            return 1
    if counts and counts[0] >= 4:
        return 2
    if counts and counts[0] >= 3 and len(counts) > 1 and counts[1] >= 2:
        return 3
    if flush:
        return 4
    if straight:
        return 5
    if counts and counts[0] >= 3:
        return 6
    if len(counts) > 1 and counts[0] >= 2 and counts[1] >= 2:
        return 7
    if counts and counts[0] >= 2:
        return 8
    return 9


def shared_note(hole: Sequence[str], board: Sequence[str]) -> str:
    """What the board already gives everyone, when that is most of your hand: the cards in
    the middle are shared, so a pair, straight or flush lying there isn't yours alone."""
    if len(board) < 3:
        return ""
    mine = evaluate(hole, board)
    cat = _EVAL.get_rank_class(mine)
    if len(board) == 5:
        b = [to_int(c) for c in board]
        if mine == _EVAL.evaluate(b[:3], b[3:]):
            return "all on the board, so everyone has it"
    b_cat = board_category(board)
    if b_cat <= 8 and cat == b_cat:
        return "but that's on the board, so everyone has it"
    counts = Counter(c[0] for c in board)
    if b_cat == 8 and cat == 7:
        pair = max((r for r, n in counts.items() if n >= 2), key=RANKS.index)
        return f"the pair of {PLURAL[pair]} is on the board, so everyone has it"
    if cat == 9:
        mine = max((c[0] for c in hole), key=RANKS.index)
        top = max((c[0] for c in board), key=RANKS.index)
        if RANKS.index(top) > RANKS.index(mine):
            return f"the {NAME[top].lower()} is on the board, so everyone has it"
    if cat == 4:
        suits = Counter(c[1] for c in board)
        s, n = suits.most_common(1)[0]
        if n >= 4:
            return "four of that suit are on the board, so anyone with one more has a flush too"
    return ""


def _improves(hole, board_after, current) -> bool:
    new = category(hole, board_after)
    # an improvement the board makes for everyone (e.g. the board pairing) does not count
    return new < current and new < board_category(board_after)


def improvement(hole: Sequence[str], board: Sequence[str]) -> Optional[Tuple[float, int, Optional[float]]]:
    """(chance the hero's own hand category improves on the next card, outs, chance by the river)."""
    if len(board) not in (3, 4):
        return None
    known = set(hole) | set(board)
    rest = [c for c in DECK if c not in known]
    current = category(hole, board)
    outs = sum(1 for c in rest if _improves(hole, list(board) + [c], current))
    next_card = outs / len(rest)
    if len(board) == 3:
        better = total = 0
        for i in range(len(rest)):
            for j in range(i + 1, len(rest)):
                total += 1
                if _improves(hole, list(board) + [rest[i], rest[j]], current):
                    better += 1
        by_river = better / total
    else:
        by_river = next_card
    return next_card, outs, by_river
