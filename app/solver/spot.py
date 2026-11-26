"""A river decision to solve: the board, the pot, the stacks, the bet sizes each player may
use, and each player's range as weighted hand combos.

Player 0 is out of position (acts first on the river), player 1 is in position.

Building a spot cleans the ranges:
- combos that use a board card are removed;
- combos that use the same card twice are removed;
- a combo listed twice keeps its first weight;
- combos with weight 0 are removed (negative weights are an error).

Clashes between the two players' ranges can't be removed from either range: each combo
clashes with only some of the other range. Those deals are given no weight when the two
ranges meet (see `ranking.matchups`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .ranking import RANK_INDEX, SUIT_INDEX

OOP, IP = 0, 1
PLAYER_NAMES = ("oop", "ip")

Combo = Tuple[str, str]
WeightedRange = Tuple[Tuple[Combo, float], ...]
RangeInput = Union[str, Mapping, Iterable]


def check_card(card: str) -> str:
    if not isinstance(card, str) or len(card) != 2 or card[0] not in RANK_INDEX or card[1] not in SUIT_INDEX:
        raise ValueError(f"Not a card: {card!r}")
    return card


def canonical(combo: Sequence[str]) -> Combo:
    """The two cards in a fixed order (higher rank first, then by suit), so AhKh and KhAh
    are the same combo."""
    a, b = (check_card(c) for c in combo)
    ka, kb = (RANK_INDEX[a[0]], -SUIT_INDEX[a[1]]), (RANK_INDEX[b[0]], -SUIT_INDEX[b[1]])
    return (a, b) if ka >= kb else (b, a)


def combo_text(combo: Sequence[str]) -> str:
    return combo[0] + combo[1]


def parse_combo(item) -> Combo:
    """'AhKh' or ('Ah', 'Kh')."""
    if isinstance(item, str):
        text = item.strip()
        if len(text) != 4:
            raise ValueError(f"Not a combo: {item!r}")
        return canonical((text[:2], text[2:]))
    if isinstance(item, (tuple, list)) and len(item) == 2 and all(isinstance(c, str) for c in item):
        return canonical(item)
    raise ValueError(f"Not a combo: {item!r}")


def _items(spec: RangeInput) -> List[Tuple[object, float]]:
    """(combo, weight) pairs from range text, a {combo: weight} mapping, or a list of combos
    or (combo, weight) pairs."""
    if isinstance(spec, str):
        from app.poker.ranges import parse_range

        return [(c, 1.0) for c in parse_range(spec)]
    if isinstance(spec, Mapping):
        return [(k, v) for k, v in spec.items()]
    out = []
    for item in spec:
        is_pair = (isinstance(item, (tuple, list)) and len(item) == 2 and not isinstance(item[1], str))
        out.append((item[0], item[1]) if is_pair else (item, 1.0))
    return out


def normalize_range(spec: RangeInput, board: Sequence[str]) -> WeightedRange:
    dead = set(board)
    seen = set()
    out = []
    for raw, weight in _items(spec):
        combo = parse_combo(raw)
        w = float(weight)
        if math.isnan(w) or w < 0 or math.isinf(w):
            raise ValueError(f"Bad weight {weight!r} for {combo_text(combo)}")
        if combo[0] == combo[1] or w == 0 or combo[0] in dead or combo[1] in dead or combo in seen:
            continue
        seen.add(combo)
        out.append((combo, w))
    return tuple(out)


SIZE_LISTS = ("bets", "raises", "reraises")


@dataclass(frozen=True)
class BetSizes:
    """The sizes one player may use on the river.

    bets: an opening bet, as shares of the pot (0.5 = half the pot).
    raises: a raise, as shares of the pot after calling (1.0 = raise the size of the pot).
    allin: going all in is always one of the choices.
    reraises: the sizes for a raise of a raise, when they differ from `raises` (None: the
    same; () with allin: a raise can only be answered by going all in).
    allin_within: with allin, going all in is only added where it is a bet of at most this
    many pots (for a raise: the raise, in pots after calling). None: everywhere. An all in
    of 40 pots is next to never right, and offering it makes a solve many times rougher.
    exact: the lists ("bets", "raises", "reraises") that all in is not added to, whatever
    allin says: their sizes are the only choices there.
    Sizes at or above the stack become all in; equal amounts are offered once.
    """

    bets: Tuple[float, ...] = (0.5, 1.0)
    raises: Tuple[float, ...] = (1.0,)
    allin: bool = True
    reraises: Optional[Tuple[float, ...]] = None
    allin_within: Optional[float] = None
    exact: Tuple[str, ...] = ()

    def __post_init__(self):
        for name in SIZE_LISTS:
            if getattr(self, name) is None:
                continue
            vals = tuple(sorted({float(x) for x in getattr(self, name)}))
            if any(not math.isfinite(x) or x <= 0 for x in vals):
                raise ValueError(f"Bet sizes must be positive shares of the pot: {vals}")
            object.__setattr__(self, name, vals)
        object.__setattr__(self, "allin", bool(self.allin))
        if self.allin_within is not None:
            within = float(self.allin_within)
            if not math.isfinite(within) or within <= 0:
                raise ValueError(f"allin_within is a positive number of pots: {self.allin_within!r}")
            object.__setattr__(self, "allin_within", within)
        exact = tuple(sorted(set(self.exact)))
        if any(name not in SIZE_LISTS for name in exact):
            raise ValueError(f"exact names lists of sizes {SIZE_LISTS}: {self.exact!r}")
        object.__setattr__(self, "exact", exact)

    def raise_list(self, raises_so_far: int) -> str:
        """Which list holds the sizes for the next raise, after this many raises of the first bet."""
        return "raises" if raises_so_far == 0 or self.reraises is None else "reraises"

    def raise_sizes(self, raises_so_far: int) -> Tuple[float, ...]:
        """The sizes for the next raise, after this many raises of the first bet."""
        return getattr(self, self.raise_list(raises_so_far))

    def adds_allin(self, which: str, pots: float) -> bool:
        """Whether all in is added to the sizes of this list ("bets", "raises" or
        "reraises") where going all in is a bet or raise of this many pots."""
        if not self.allin or which in self.exact:
            return False
        return self.allin_within is None or pots <= self.allin_within + 1e-9

    def to_dict(self) -> dict:
        d = {"bets": list(self.bets), "raises": list(self.raises), "allin": self.allin}
        if self.reraises is not None:
            d["reraises"] = list(self.reraises)
        if self.allin_within is not None:
            d["allin_within"] = self.allin_within
        if self.exact:
            d["exact"] = list(self.exact)
        return d

    @staticmethod
    def from_dict(d: Mapping) -> "BetSizes":
        again = d.get("reraises")
        return BetSizes(tuple(d.get("bets", ())), tuple(d.get("raises", ())), bool(d.get("allin", False)),
                        tuple(again) if again is not None else None, d.get("allin_within"),
                        tuple(d.get("exact", ())))


@dataclass(frozen=True)
class RiverSpot:
    """board: the five cards. pot: chips in the middle when the river betting starts.
    stacks: chips behind for (out of position, in position) at that moment; only the
    smaller one matters, since nobody can win more than the shorter stack.
    oop_range, ip_range: weighted combos (range text, a {combo: weight} mapping or a list).
    oop_sizes, ip_sizes: the bet and raise sizes each player may use.
    max_raises: raises allowed after the first bet (0 = bet, then only call or fold)."""

    board: Tuple[str, ...]
    pot: float
    stacks: Tuple[float, float]
    oop_range: WeightedRange
    ip_range: WeightedRange
    oop_sizes: BetSizes = field(default_factory=BetSizes)
    ip_sizes: BetSizes = field(default_factory=BetSizes)
    max_raises: int = 1

    def __post_init__(self):
        board = tuple(check_card(c) for c in self.board)
        if len(board) != 5 or len(set(board)) != 5:
            raise ValueError("A river spot needs five different board cards.")
        pot = float(self.pot)
        if not math.isfinite(pot) or pot <= 0:
            raise ValueError("The pot must be more than 0.")
        stacks = tuple(float(x) for x in self.stacks)
        if len(stacks) != 2 or any(not math.isfinite(x) or x < 0 for x in stacks):
            raise ValueError("Stacks are two amounts of 0 or more: (out of position, in position).")
        if int(self.max_raises) < 0:
            raise ValueError("max_raises can't be negative.")
        set_ = lambda k, v: object.__setattr__(self, k, v)  # noqa: E731 (frozen dataclass)
        set_("board", board)
        set_("pot", pot)
        set_("stacks", stacks)
        set_("max_raises", int(self.max_raises))
        for name in ("oop_range", "ip_range"):
            r = normalize_range(getattr(self, name), board)
            if not r:
                raise ValueError(f"{name} has no combos left after removing the board cards.")
            set_(name, r)
        for name in ("oop_sizes", "ip_sizes"):
            s = getattr(self, name)
            if isinstance(s, Mapping):
                s = BetSizes.from_dict(s)
            if not isinstance(s, BetSizes):
                raise ValueError(f"{name} must be BetSizes")
            set_(name, s)

    # ---------------------------------------------------------------- views
    @property
    def effective_stack(self) -> float:
        return min(self.stacks)

    def range(self, player: int) -> WeightedRange:
        return self.oop_range if player == OOP else self.ip_range

    def sizes(self, player: int) -> BetSizes:
        return self.oop_sizes if player == OOP else self.ip_sizes

    def combos(self, player: int) -> List[Combo]:
        return [c for c, _ in self.range(player)]

    def weights(self, player: int) -> np.ndarray:
        return np.array([w for _, w in self.range(player)], dtype=float)

    def index(self, player: int, combo: Sequence[str]) -> int:
        """Position of a combo in that player's range (ValueError when it isn't in it)."""
        c = parse_combo(combo if isinstance(combo, str) else tuple(combo))
        for i, (x, _) in enumerate(self.range(player)):
            if x == c:
                return i
        raise ValueError(f"{combo_text(c)} isn't in the {PLAYER_NAMES[player]} range.")

    # ---------------------------------------------------------- save / load
    def to_dict(self) -> dict:
        return {
            "board": list(self.board), "pot": self.pot, "stacks": list(self.stacks),
            "ranges": {"oop": {combo_text(c): w for c, w in self.oop_range},
                       "ip": {combo_text(c): w for c, w in self.ip_range}},
            "sizes": {"oop": self.oop_sizes.to_dict(), "ip": self.ip_sizes.to_dict()},
            "max_raises": self.max_raises,
        }

    @staticmethod
    def from_dict(d: Mapping) -> "RiverSpot":
        return RiverSpot(board=tuple(d["board"]), pot=d["pot"], stacks=tuple(d["stacks"]),
                         oop_range=d["ranges"]["oop"], ip_range=d["ranges"]["ip"],
                         oop_sizes=BetSizes.from_dict(d["sizes"]["oop"]), ip_sizes=BetSizes.from_dict(d["sizes"]["ip"]),
                         max_raises=d.get("max_raises", 1))
