"""Opponent ranges: simple presets by hand strength, or a range written in standard notation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from typing import List, Optional, Tuple

from .hands import RANKS, SUITS

# 169 starting hands ranked by all-in equity against one random hand
# (built with tools/build_preflop_ranking.py using treys).
PREFLOP_RANKING = [
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "AKs", "77", "AQs", "AJs", "AKo",
    "AQo", "ATs", "KQs", "AJo", "ATo", "A9s", "KJs", "66", "KQo", "A7s", "55", "A8s",
    "KTs", "A9o", "QJs", "QTs", "A6s", "KJo", "KTo", "K9s", "A4s", "A5s", "A8o", "JTs",
    "A7o", "A3s", "QTo", "K8s", "A5o", "A6o", "K7s", "QJo", "K9o", "A2s", "A4o", "Q9s",
    "44", "J9s", "A3o", "K8o", "K6s", "K7o", "K5s", "K3s", "JTo", "Q8s", "A2o", "Q7s",
    "T9s", "Q9o", "33", "K4s", "K2s", "Q8o", "K6o", "K5o", "Q6s", "Q5s", "J8s", "Q7o",
    "T8s", "J9o", "K3o", "J7s", "T9o", "J8o", "Q6o", "Q5o", "K4o", "K2o", "Q3s", "98s",
    "Q4s", "Q2s", "J6s", "J7o", "T7s", "J5s", "97s", "22", "T8o", "J6o", "Q4o", "Q3o",
    "J4s", "J3s", "T6s", "87s", "Q2o", "98o", "J2s", "J4o", "96s", "97o", "J5o", "T7o",
    "T4s", "86s", "T6o", "T5s", "76s", "J3o", "T3s", "95s", "85s", "J2o", "87o", "94s",
    "T2s", "96o", "T4o", "75s", "T5o", "93s", "65s", "76o", "86o", "84s", "T2o", "T3o",
    "85o", "64s", "95o", "74s", "54s", "92s", "82s", "83s", "75o", "73s", "93o", "65o",
    "92o", "53s", "94o", "84o", "63s", "52s", "43s", "74o", "72s", "62s", "54o", "83o",
    "64o", "32s", "73o", "82o", "53o", "63o", "42s", "43o", "72o", "52o", "62o", "42o",
    "32o",
]

PRESETS = {
    "any": ("Any two cards", 1.00),
    "loose": ("Loose range", 0.50),
    "medium": ("Medium range", 0.25),
    "tight": ("Tight range", 0.12),
    "very_tight": ("Very tight range", 0.05),
}

Combo = Tuple[str, str]


def class_combos(cls: str) -> List[Combo]:
    a, b = cls[0], cls[1]
    if a == b:
        return [(a + s1, b + s2) for s1, s2 in combinations(SUITS, 2)]
    if cls[2] == "s":
        return [(a + s, b + s) for s in SUITS]
    return [(a + s1, b + s2) for s1 in SUITS for s2 in SUITS if s1 != s2]


@lru_cache(maxsize=None)
def top_fraction(fraction: float) -> Tuple[Combo, ...]:
    """Strongest classes until `fraction` of the 1326 combos is covered."""
    target = fraction * 1326
    out: List[Combo] = []
    for cls in PREFLOP_RANKING:
        if len(out) >= target - 1e-9:
            break
        out.extend(class_combos(cls))
    return tuple(out)


_TOKEN = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so])?(\+)?$")
_DASH = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so])?-([2-9TJQKA])([2-9TJQKA])([so])?$")
_EXACT = re.compile(r"^([2-9TJQKA][shdc])([2-9TJQKA][shdc])$")


def _classes(a: str, b: str, kind: Optional[str]) -> List[str]:
    if a == b:
        return [a + b]
    hi, lo = (a, b) if RANKS.index(a) > RANKS.index(b) else (b, a)
    return [hi + lo + k for k in (kind,)] if kind else [hi + lo + "s", hi + lo + "o"]


def parse_range(text: str) -> Tuple[Combo, ...]:
    """Standard notation: 'QQ+, AKs, AJo+, KTs+, 76s-54s, 22-55, AhKh'."""
    combos: List[Combo] = []
    for raw in re.split(r"[,\s]+", text.strip()):
        tok = raw.strip()
        if not tok:
            continue
        tok = tok[:2].upper() + tok[2:].lower() if len(tok) <= 4 else tok
        m = _EXACT.match(raw.strip()[:1].upper() + raw.strip()[1:2].lower() + raw.strip()[2:3].upper() + raw.strip()[3:4].lower())
        if m and m.group(1) != m.group(2):
            combos.append((m.group(1), m.group(2)))
            continue
        m = _TOKEN.match(tok)
        if m:
            a, b, kind, plus = m.groups()
            if not plus:
                for cls in _classes(a, b, kind):
                    combos.extend(class_combos(cls))
            elif a == b:  # 77+
                for r in RANKS[RANKS.index(a):]:
                    combos.extend(class_combos(r + r))
            else:  # A9s+ : raise the kicker up to one below the top card
                hi, lo = (a, b) if RANKS.index(a) > RANKS.index(b) else (b, a)
                for r in RANKS[RANKS.index(lo): RANKS.index(hi)]:
                    for cls in _classes(hi, r, kind):
                        combos.extend(class_combos(cls))
            continue
        m = _DASH.match(tok)
        if m:
            a1, b1, k1, a2, b2, k2 = m.groups()
            if a1 == b1 and a2 == b2:  # 22-55
                lo, hi = sorted((RANKS.index(a1), RANKS.index(a2)))
                for r in RANKS[lo: hi + 1]:
                    combos.extend(class_combos(r + r))
                continue
            if a1 == a2:  # A2s-A5s (same top card)
                lo, hi = sorted((RANKS.index(b1), RANKS.index(b2)))
                for r in RANKS[lo: hi + 1]:
                    for cls in _classes(a1, r, k1 or k2):
                        combos.extend(class_combos(cls))
                continue
            gap = RANKS.index(a1) - RANKS.index(b1)
            if gap == RANKS.index(a2) - RANKS.index(b2):  # 76s-54s (same gap)
                lo, hi = sorted((RANKS.index(b1), RANKS.index(b2)))
                for r in range(lo, hi + 1):
                    for cls in _classes(RANKS[r + gap], RANKS[r], k1 or k2):
                        combos.extend(class_combos(cls))
                continue
        raise ValueError(f"Cannot read range token: {raw}")
    seen = set()
    unique = []
    for c in combos:
        key = frozenset(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return tuple(unique)


@dataclass(frozen=True)
class RangeSpec:
    key: str  # preset key or "custom"
    label: str  # wording used in the text output
    combos: Optional[Tuple[Combo, ...]]  # None = any two cards

    @property
    def fraction(self) -> float:
        return 1.0 if self.combos is None else len(self.combos) / 1326.0


def make_range(key: str, custom_text: str = "") -> RangeSpec:
    if key == "custom":
        combos = parse_range(custom_text)
        if not combos:
            raise ValueError("The custom range is empty.")
        pct = round(100 * len(combos) / 1326.0, 1)
        return RangeSpec("custom", f"custom range, {pct:g}% of hands", combos)
    name, frac = PRESETS.get(key, PRESETS["medium"])
    if frac >= 1.0:
        return RangeSpec("any", "random hands", None)
    return RangeSpec(key, f"{name}, top {int(round(frac * 100))}%", top_fraction(frac))


def preflop_percentile(cls: str) -> float:
    """Share of all combos that rank at or above this class (lower is stronger)."""
    total = 0
    for c in PREFLOP_RANKING:
        total += len(class_combos(c))
        if c == cls:
            return total / 1326.0
    return 1.0


def betting_range(combos: Tuple[Combo, ...], board: Tuple[str, ...], dead: Tuple[str, ...], share: float,
                  bluffs: float = 0.0) -> Tuple[Combo, ...]:
    """The part of a range that bets or raises on this board: its strongest `share` (made
    hands, and big draws counted like a middling pair), plus the weakest `bluffs` share
    (hands with nothing, which some players bet anyway). Players who bet big don't hold
    their whole range, so judging a call against the whole range overrates your hand."""
    from .hands import draws, evaluate

    live = [c for c in combos if c[0] not in dead and c[1] not in dead]
    if not live or len(board) < 3:
        return tuple(live)
    scored = []
    for c in live:
        rank = evaluate(c, board)  # 1 best .. 7462 worst
        if len(board) < 5 and rank > 3325:  # weaker than a decent pair: does it have a big draw?
            d = draws(c, board)
            if "flush draw" in d or "open-ended straight draw" in d:
                rank = min(rank, 4500)  # plays like a middling pair: it bets and calls
        scored.append((rank, c))
    scored.sort(key=lambda t: t[0])
    keep = max(1, int(round(share * len(scored))))
    out = [c for _, c in scored[:keep]]
    n_bluff = int(round(bluffs * len(scored)))
    if n_bluff:
        out += [c for _, c in scored[-n_bluff:] if c not in out]
    return tuple(out)
