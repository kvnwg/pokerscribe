"""Table positions from the dealer button and the clockwise seat order."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

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


def posted_blinds(players: Sequence) -> Optional[Tuple[float, float]]:
    """The blinds from the chips in front of the small and big blind before the flop: the big
    blind's about twice the small blind's, and every other bet at least the big blind. With the
    dealer button found, the seats' positions say whose chips they are. Without it: the
    smallest bet, and at the next seat round the table one twice as big (2:5 and 1:3 blinds
    then wait for the button, as a raise to twice the bet could look the same)."""
    bets = {i: float(p.bet.value) for i, p in enumerate(players)
            if p.bet.known and p.bet.value is not None and float(p.bet.value) > 0}
    if len(bets) < 2:
        return None
    if any(p.position.known for p in players):
        sb_i = next((i for i in bets if players[i].position.known and players[i].position.value in ("SB", "BTN/SB")),
                    None)
        bb_i = next((i for i in bets if players[i].position.known and players[i].position.value == "BB"), None)
        if sb_i is None or bb_i is None or not 1.5 <= bets[bb_i] / bets[sb_i] <= 2.5:
            return None  # (a small blind that raised, or a big blind that re-raised)
    else:
        sb_i = min(bets, key=lambda i: bets[i])
        if sum(1 for v in bets.values() if abs(v - bets[sb_i]) < 1e-9) > 1:
            return None
        bb_i = (sb_i + 1) % len(players)
        if bb_i not in bets or not 1.9 <= bets[bb_i] / bets[sb_i] <= 2.1:
            return None
    sb, bb = bets[sb_i], bets[bb_i]
    if any(v < bb - 1e-9 for i, v in bets.items() if i not in (sb_i, bb_i)):
        return None  # someone else put in less than the big blind: these are not the blinds
    return sb, bb
