"""The published heads-up push-or-fold equilibrium, to compare the solver against.

Source: HoldemResources, "HeadsUp Push/Fold Nash Equilibrium", the No Ante tables
(https://www.holdemresources.net/hune, read 26 Nov 2026; the page says the solution was
first published in 2007). The game is the same as ours: the small blind goes all in or
folds, the big blind calls or folds, blinds 0.5 and 1, and "the effective stack size is
the smaller of the two, before posting any blinds".

Each number is the highest effective stack, in big blinds, at which the hand is still
pushed (first table) or called (second table); "20+" means at every stack up to 20. Rows
and columns run A to 2, pairs on the diagonal, suited hands above it and offsuit hands
below, the same layout as app.solver.pushfold.CLASSES.

Three suited hands are pushed in two separate stack ranges (the page's footnotes):
63s from 5.1 to 7.1 and up to 2.3; 53s from 3.8 to 12.9 and up to 2.4; 43s from 4.9 to
10.0 and up to 2.2.

The page shows thresholds only. A second page, PokerStrategy's "Nash Ranges for the
Push-or-Fold Play" (https://www.pokerstrategy.com/strategy/sit-and-go/1779/), lists the
share of hands at each stack from the same calculator, and warns that programs differ by
about half a point; those shares are in PUBLISHED_SHARES. The Mathematics of Poker's own
table isn't online; the two figures this repo already quotes from it are in BOOK_JAM_SHARES.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from app.solver.pushfold import CLASSES, COMBOS

ALWAYS = 99.0  # "20+"

_PUSH = """
20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  20+
20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  19.9 19.3
20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  16.3 13.5 12.7
20+  20+  20+  20+  20+  20+  20+  20+  18.6 14.7 13.5 10.6 8.5
20+  20+  20+  20+  20+  20+  20+  20+  20+  11.9 10.5 7.7  6.5
20+  20+  20+  20+  20+  20+  20+  20+  20+  14.4 6.9  4.9  3.7
20+  18.0 13.0 13.3 17.5 20+  20+  20+  20+  18.8 10.1 2.7  2.5
20+  16.1 10.3 8.5  9.0  10.8 14.7 20+  20+  20+  13.9 2.5  2.1
20+  15.1 9.6  6.5  5.7  5.2  7.0  10.7 20+  20+  16.3 gap  2.0
20+  14.2 8.9  6.0  4.1  3.5  3.0  2.6  2.4  20+  20+  gap  2.0
20+  13.1 7.9  5.4  3.8  2.7  2.3  2.1  2.0  2.1  20+  gap  1.8
20+  12.2 7.5  5.0  3.4  2.5  1.9  1.8  1.7  1.8  1.6  20+  1.7
20+  11.6 7.0  4.6  2.9  2.2  1.8  1.6  1.5  1.5  1.4  1.4  20+
"""

_CALL = """
20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  20+  20+
20+  20+  20+  20+  20+  20+  17.6 15.2 14.3 13.2 12.1 11.4 10.7
20+  20+  20+  20+  20+  16.1 13.0 10.5 9.9  8.9  8.4  7.8  7.2
20+  20+  19.5 20+  18.0 13.4 10.6 8.8  7.0  6.9  6.1  5.8  5.6
20+  20+  15.3 12.7 20+  11.5 9.3  7.4  6.3  5.2  5.2  4.8  4.5
20+  17.1 11.7 9.5  8.4  20+  8.2  7.0  5.8  5.0  4.3  4.1  3.9
20+  13.8 9.7  7.6  6.6  6.0  20+  6.5  5.6  4.8  4.1  3.6  3.5
20+  12.4 8.0  6.4  5.5  5.0  4.7  20+  5.4  4.8  4.1  3.6  3.3
20+  11.0 7.3  5.4  4.6  4.2  4.1  4.0  20+  4.9  4.3  3.8  3.3
20+  10.2 6.8  5.1  4.0  3.7  3.6  3.6  3.7  20+  4.6  4.0  3.6
18.3 9.1  6.2  4.7  3.8  3.3  3.2  3.2  3.3  3.5  20+  3.8  3.4
16.6 8.7  5.9  4.5  3.6  3.1  2.9  2.9  2.9  3.1  3.0  20+  3.3
15.8 8.1  5.6  4.2  3.5  3.0  2.8  2.6  2.7  2.8  2.7  2.6  15.0
"""

# hand: stack ranges (low, high) in which it is pushed
PUSH_GAPS: Dict[str, List[Tuple[float, float]]] = {
    "63s": [(5.1, 7.1), (0.0, 2.3)],
    "53s": [(3.8, 12.9), (0.0, 2.4)],
    "43s": [(4.9, 10.0), (0.0, 2.2)],
}

# stack: (share of hands the small blind pushes, share the big blind calls), PokerStrategy's table
PUBLISHED_SHARES = {5: (0.741, 0.686), 8: (0.626, 0.484), 10: (0.566, 0.385), 12: (0.514, 0.330),
                    15: (0.457, 0.284)}
# stack: share the small blind jams, as quoted from The Mathematics of Poker in app/poker/advice.py
BOOK_JAM_SHARES = {8: 0.62, 10: 0.58}


def _parse(text: str) -> Dict[str, float]:
    cells = text.split()
    assert len(cells) == 169
    return {hand: (ALWAYS if cell == "20+" else -1.0 if cell == "gap" else float(cell))
            for hand, cell in zip(CLASSES, cells)}


PUSH_UP_TO = _parse(_PUSH)
CALL_UP_TO = _parse(_CALL)


def chart_pushes(hand: str, stack: float) -> bool:
    if hand in PUSH_GAPS:
        return any(lo <= stack <= hi for lo, hi in PUSH_GAPS[hand])
    return stack <= PUSH_UP_TO[hand]


def chart_calls(hand: str, stack: float) -> bool:
    return stack <= CALL_UP_TO[hand]


def chart_margin(hand: str, stack: float, seat: str) -> float:
    """How far (in big blinds) the stack is from the nearest point where the chart's
    answer for this hand changes."""
    if seat == "jam" and hand in PUSH_GAPS:
        return min(abs(stack - edge) for rng in PUSH_GAPS[hand] for edge in rng if edge > 0)
    return abs(stack - (PUSH_UP_TO if seat == "jam" else CALL_UP_TO)[hand])


def chart_share(stack: float, seat: str) -> float:
    plays = chart_pushes if seat == "jam" else chart_calls
    return float(sum(n for hand, n in zip(CLASSES, COMBOS) if plays(hand, stack)) / COMBOS.sum())
