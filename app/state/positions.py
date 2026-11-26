"""Table positions from the dealer button and the clockwise seat order."""
from __future__ import annotations

from typing import Dict, List, Sequence

POSITION_LABELS = {
    "UTG": "Under the Gun",
    "UTG+1": "Under the Gun +1",
    "UTG+2": "Under the Gun +2",
    "MP": "Middle Position",
    "LJ": "Lojack",
    "HJ": "Hijack",
    "CO": "Cutoff",
    "BTN": "Button",
    "SB": "Small Blind",
    "BB": "Big Blind",
    "BTN/SB": "Button/Small Blind",
}
POSITION_CODES = list(POSITION_LABELS)
_LATE = {
    1: ["CO"],
    2: ["HJ", "CO"],
    3: ["UTG", "HJ", "CO"],
    4: ["UTG", "LJ", "HJ", "CO"],
    5: ["UTG", "UTG+1", "LJ", "HJ", "CO"],
    6: ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO"],
    7: ["UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO"],
}


def position_names(n_players: int) -> List[str]:
    """Position codes in clockwise order starting with the button."""
    if n_players < 2:
        return []
    if n_players == 2:
        return ["BTN/SB", "BB"]
    extra = n_players - 3
    if extra > 7:
        raise ValueError("At most 10 players are supported.")
    return ["BTN", "SB", "BB"] + _LATE.get(extra, [])


def assign_positions(seats_clockwise: Sequence[int], button_seat: int) -> Dict[int, str]:
    """Map seat id -> position code. `seats_clockwise` lists the seats dealt in."""
    seats = list(seats_clockwise)
    if button_seat not in seats or len(seats) < 2:
        return {}
    i = seats.index(button_seat)
    order = seats[i:] + seats[:i]
    return dict(zip(order, position_names(len(order))))


def label(code: str) -> str:
    return POSITION_LABELS.get(code, code)


def code_from_label(text: str) -> str:
    t = text.strip()
    for code, name in POSITION_LABELS.items():
        if t.lower() in (code.lower(), name.lower()):
            return code
    raise ValueError(f"Unknown position: {text}")
