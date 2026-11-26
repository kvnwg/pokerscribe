"""Preflop charts in the shape solvers give for 6-max no-limit hold'em cash games, about
100 big blinds deep: which hands to open from each seat, and against a raise which hands
to re-raise, call or fold, by your seat and the raiser's.

They are simplified to one action per hand (solvers mix some hands between two actions;
each hand is put in the action it takes most often) and follow published 100bb 6-max
solutions: opens of about 2 to 2.5 big blinds (3 from the small blind), tight from early
seats and wide on the button, re-raise or fold from the cutoff and the small blind, a
wide big blind defence (it already has a blind in and closes the action), and re-raises
with the best hands plus some suited aces and connectors as bluffs. Spot checks against
solver answers (the PokerBench preflop test set) were used to set the edges.

Hands are classes like "AKs", "T9s", "77", "KQo".
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, FrozenSet, Optional, Tuple

from .hands import RANKS
from .ranges import parse_range


@lru_cache(maxsize=None)
def _classes(text: str) -> FrozenSet[str]:
    """The hand classes in a range written in standard notation."""
    out = set()
    for a, b in parse_range(text):
        ra, rb = a[0], b[0]
        if ra == rb:
            out.add(ra + rb)
            continue
        hi, lo = (ra, rb) if RANKS.index(ra) > RANKS.index(rb) else (rb, ra)
        out.add(hi + lo + ("s" if a[1] == b[1] else "o"))
    return frozenset(out)


# --- first in: open-raise (everything else folds; the big blind checks) -----------------
OPEN = {
    # full ring early seats (9-max): tighter than 6-max under the gun
    "EP9": "66+, A9s+, A5s, KTs+, QTs+, JTs, T9s, AJo+, KQo",  # about 11%
    "UTG": "44+, A2s+, K9s+, Q9s+, J9s+, T9s, 98s, 87s, ATo+, KJo+",  # about 18%
    "HJ": "22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 98s, 87s, 76s, 65s, A9o+, KJo+, QJo",  # 23%
    "CO": "22+, A2s+, K4s+, Q6s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, 54s, A8o+, KTo+, QTo+, JTo",  # 30%
    "BTN": "22+, A2s+, K2s+, Q4s+, J6s+, T6s+, 96s+, 85s+, 74s+, 64s+, 53s+, 43s, A2o+, K8o+, Q9o+, J9o+, "
           "T9o, 98o",  # 44%
    "SB": "22+, A2s+, K2s+, Q3s+, J5s+, T6s+, 95s+, 85s+, 74s+, 64s+, 53s+, 43s, A2o+, K8o+, Q9o+, J8o+, "
          "T8o+, 98o",  # 47%: raise or fold, no limping
}
OPEN["BTN/SB"] = OPEN["BTN"]  # heads-up: the button opens very wide

# --- facing one raise, nobody called it yet: (re-raise, call) --------------------------
# A hand sits in one list only; anything in neither list folds.
# Keyed by (your seat, the raiser's seat group). Groups: "EP" (UTG and earlier, 9-max
# middle seats), "HJ", "CO", "BTN", "SB".
VS_OPEN: Dict[Tuple[str, str], Tuple[str, str]] = {
    # big blind: defends wide, it already has a blind in and closes the action
    ("BB", "EP"): ("QQ+, AKs, AKo, A5s-A4s",
                   "22-JJ, A6s-AQs, A2s-A3s, K6s+, Q8s+, J8s+, T7s+, 97s+, 86s+, 75s+, 64s+, 54s, A8o-AQo, KTo+, QTo+, JTo"),
    ("BB", "HJ"): ("JJ+, AQs+, AKo, A5s-A4s, KQs",
                   "22-TT, A6s-AJs, A2s-A3s, K4s-KJs, Q7s+, J7s+, T7s+, 96s+, 85s+, 75s+, 64s+, 54s, A8o-AQo, K9o+, Q9o+, "
                   "J9o+, T9o"),
    ("BB", "CO"): ("TT+, AJs+, KQs, A5s-A3s, AQo+",
                   "22-99, A6s-ATs, A2s, K2s-KJs, Q5s+, J6s+, T6s+, 96s+, 85s+, 74s+, 63s+, 53s+, 43s, A4o-AJo, K9o+, "
                   "Q9o+, J9o+, T9o, 98o"),
    ("BB", "BTN"): ("TT+, AJs+, KQs, A5s-A2s, K9s, QTs, J9s, T9s, 76s, 65s, AQo+",
                    "22-99, A6s-ATs, K2s-K8s, KTs-KJs, Q2s-Q9s, QJs, J4s-J8s, JTs, T6s-T8s, 95s+, 85s+, 74s-75s, "
                    "63s-64s, 53s+, 43s, A2o-AJo, K5o+, Q8o+, J8o+, T7o+, 97o+, 86o+, 76o, 65o"),
    ("BB", "SB"): ("88+, A9s+, A5s-A4s, KTs+, QTs+, JTs, T9s, 98s, 87s, ATo+, KJo+",
                   "22-77, A6s-A8s, A2s-A3s, K2s-K9s, Q2s-Q9s, J2s-J9s, T4s-T8s, 94s-97s, 84s-86s, 73s+, 63s+, 52s+, 42s+, "
                   "32s, A2o-A9o, K2o-KTo, Q7o+, J7o+, T7o+, 97o+, 86o+, 76o, 65o"),
    # small blind: out of position against everyone: re-raise or fold
    ("SB", "EP"): ("TT+, AJs+, KQs, A5s-A4s, AQo+, KQo", ""),
    ("SB", "HJ"): ("99+, ATs+, KJs+, QJs, A5s-A3s, AJo+, KQo", ""),
    ("SB", "CO"): ("77+, A9s+, A5s-A3s, KTs+, QTs+, JTs, ATo+, KJo+", ""),
    ("SB", "BTN"): ("66+, A2s+, K9s+, Q9s+, J9s+, T9s, 98s, ATo+, KJo+", ""),
    # in position behind the raiser
    ("HJ", "EP"): ("TT+, AJs+, KQs, A5s-A3s, AQo+", "77-99, ATs, KJs, QJs, JTs, T9s"),
    ("CO", "EP"): ("TT+, ATs+, KJs+, QJs, A5s-A3s, AQo+, KQo", "66-99, JTs, T9s, 98s"),
    ("CO", "HJ"): ("99+, ATs+, KTs+, QJs, A5s-A2s, AJo+, KQo", "66-88, QTs, JTs, T9s, 98s"),
    ("BTN", "EP"): ("TT+, AQs+, KQs, A5s-A4s, AQo+", "22-99, A9s-AJs, KTs-KJs, QTs+, JTs, T9s, 98s, 87s, 76s, KQo"),
    ("BTN", "HJ"): ("TT+, AJs+, KQs, A5s-A3s, K9s, AQo+",
                    "22-99, A8s-ATs, KTs-KJs, Q9s+, J9s+, T8s+, 98s, 87s, 76s, 65s, AJo, KQo"),
    ("BTN", "CO"): ("TT+, ATs+, KTs+, QTs+, A5s-A2s, K9s, 76s, 65s, AJo+, KJo+",
                    "22-99, A6s-A9s, K8s, Q9s, J9s+, T8s+, 97s+, 86s+, 75s, 54s, ATo, KTo, QTo+, JTo"),
}

# --- you raised and someone re-raised: (4-bet, call) -----------------------------------
# Keyed by (the seat you opened from, where the re-raiser sits): "behind" means a later
# seat that will act after you after the flop (you're out of position), "blind" means
# the small or big blind (you're in position, except the small blind against the big).
VS_3BET: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("EP", "behind"): ("QQ+, AKs, AKo, A5s", "99-JJ, ATs-AQs, KJs+, QJs, JTs, AQo"),
    ("EP", "blind"): ("QQ+, AKs, AKo, A5s", "88-JJ, ATs-AQs, KJs+, QJs, JTs, AQo"),
    ("HJ", "behind"): ("QQ+, AKs, AKo, AQo, KQs, KJs, ATs, A5s-A4s", "88-JJ, AJs-AQs, QJs, JTs, T9s"),
    ("HJ", "blind"): ("QQ+, AKs, AKo, A5s", "77-JJ, ATs-AQs, KTs+, QJs, JTs, T9s, AQo"),
    ("CO", "behind"): ("QQ+, AKs, AKo, AQo, A5s-A4s", "77-JJ, ATs-AQs, KTs+, QTs+, JTs, T9s, 98s"),
    ("CO", "blind"): ("QQ+, AKs, AKo, A5s-A4s", "55-JJ, A8s-AQs, KTs+, QTs+, JTs, T9s, 98s, AJo-AQo, KQo"),
    ("BTN", "blind"): ("QQ+, AKs, AKo, AJo, A5s-A4s",
                       "44-JJ, A6s-AQs, K9s+, QTs+, J9s+, T9s, 98s, 87s, 76s, 65s, ATo, AQo, KQo, KJo"),
    ("SB", "blind"): ("JJ+, AKs, AKo, AJo, A5s-A4s, KQs",
                      "55-TT, A6s-AQs, K9s-KJs, QTs+, J9s+, T9s, 98s, 87s, ATo, AQo, KQo"),
}

# --- you re-raised and someone raised again: (all in, call) ------------------------------
VS_4BET = ("KK+, AKs", "QQ, AKo")
# --- someone raised and others called: squeeze tighter, call with hands that play well multiway
SQUEEZE = ("QQ+, AKs, AKo, A5s", "22-JJ, A6s-AQs, A2s-A4s, KTs+, QTs+, J9s+, T8s+, 98s, 87s, 76s, 65s, AQo")
# --- a raise and a re-raise before you even acted: only the very best hands go on
COLD_VS_3BET = ("KK+, AKs", "QQ-JJ, AKo")
# --- players just called the big blind: raise them (isolate), call along with speculative hands
ISO = {
    "early": "77+, ATs+, KJs+, QJs, AQo+",
    "late": "55+, A8s+, A5s, KTs+, QTs+, JTs, ATo+, KJo+",
    "BB": "88+, ATs+, KQs, AQo+",  # raise from the big blind instead of checking
}
OVERLIMP = "22-66, A2s-A9s, K9s, Q9s, J9s, T8s+, 97s+, 86s+, 75s+, 64s+, 54s"

EARLY = {"UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ"}
# seats only a bigger table has, with six or more players behind: tighter than 6-max UTG.
# (The first seat is called UTG at every table size, so it always gets the 6-max UTG chart.)
NINE_MAX_EARLY = {"UTG+1", "UTG+2", "MP"}
LATE = {"CO", "BTN", "SB", "BTN/SB"}


def _group(pos: Optional[str]) -> str:
    """The raiser's seat as the charts know it: EP, HJ, CO, BTN or SB."""
    if pos in ("HJ",):
        return "HJ"
    if pos in ("CO", "BTN", "SB"):
        return pos
    if pos == "BTN/SB":
        return "BTN"
    if pos in ("UTG", "UTG+1", "UTG+2", "MP", "LJ"):
        return "EP"
    return "CO"  # unknown: a middle seat


def _side(pos: Optional[str]) -> str:
    return "early" if pos in EARLY else "late"


def opens(pos: Optional[str], cls: str) -> Optional[bool]:
    """Should this hand open-raise when folded to you? None for an unknown seat."""
    if pos in OPEN:
        key = pos
    elif pos in NINE_MAX_EARLY:
        key = "EP9"
    elif pos == "LJ":
        key = "UTG"  # at a full table the lojack has five players behind, like 6-max UTG
    else:
        return None
    return cls in _classes(OPEN[key])


def _vs_open_key(pos: Optional[str], opener: Optional[str]) -> Tuple[str, str]:
    g = _group(opener)
    if pos in ("BB", "SB"):
        # a seat misread as the raiser's own falls back to the widest chart for that blind
        return (pos, g if (pos, g) in VS_OPEN else "BTN")
    if pos in ("BTN", "BTN/SB"):
        return ("BTN", g if g in ("EP", "HJ", "CO") else "CO")
    if pos == "CO":
        return ("CO", g if g in ("EP", "HJ") else "HJ")
    # HJ and the middle seats of a full ring: only earlier seats can have raised
    return ("HJ", "EP")


def vs_open(pos: Optional[str], opener: Optional[str], cls: str) -> str:
    """'raise', 'call' or 'fold' against a single raise."""
    raise_txt, call_txt = VS_OPEN[_vs_open_key(pos, opener)]
    if cls in _classes(raise_txt):
        return "raise"
    if call_txt and cls in _classes(call_txt):
        return "call"
    return "fold"


def vs_3bet(cls: str, in_position: bool, opened_from: Optional[str] = None) -> str:
    """You opened and got re-raised: 'raise' (4-bet), 'call' or 'fold'. in_position: you
    act after the re-raiser after the flop (they're a blind)."""
    g = _group(opened_from)
    if g == "SB":
        key = ("SB", "blind")
    elif g == "BTN":
        key = ("BTN", "blind")
    else:
        key = (g, "blind" if in_position else "behind")
    raise_txt, call_txt = VS_3BET[key]
    if cls in _classes(raise_txt):
        return "raise"
    if cls in _classes(call_txt):
        return "call"
    return "fold"


def cold_vs_3bet(cls: str) -> str:
    """Someone raised and someone else re-raised before you acted."""
    raise_txt, call_txt = COLD_VS_3BET
    if cls in _classes(raise_txt):
        return "raise"
    if cls in _classes(call_txt):
        return "call"
    return "fold"


def vs_4bet(cls: str) -> str:
    """You re-raised and got raised again: 'all-in', 'call' or 'fold'."""
    shove, call = VS_4BET
    if cls in _classes(shove):
        return "all-in"
    if cls in _classes(call):
        return "call"
    return "fold"


def vs_squeeze_spot(cls: str) -> str:
    """A raise and at least one call before you: 'raise', 'call' or 'fold'."""
    raise_txt, call_txt = SQUEEZE
    if cls in _classes(raise_txt):
        return "raise"
    if cls in _classes(call_txt):
        return "call"
    return "fold"


def vs_limpers(pos: Optional[str], cls: str) -> str:
    """Players only called the big blind: 'raise' (isolate), 'call' (over-limp) or 'fold'
    ('check' for the big blind)."""
    key = "BB" if pos == "BB" else _side(pos)
    if cls in _classes(ISO[key]):
        return "raise"
    if pos == "BB":
        return "check"
    if pos in ("CO", "BTN", "SB") and cls in _classes(OVERLIMP):
        return "call"
    return "fold"


def share(text: str) -> float:
    """Share of all starting hands in a chart line (for explanations and tests)."""
    from .ranges import class_combos

    if not text:
        return 0.0
    return sum(len(class_combos(c)) for c in _classes(text)) / 1326.0
