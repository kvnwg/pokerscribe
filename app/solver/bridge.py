"""From the table to a river spot, and from the solver's strategy back to one action.

The spot always starts at the beginning of the river betting, with both players' ranges
there, and the opponent's actual bet added to their bet sizes. The hero's decision is then
a node inside that tree (subgame solving with the real bet in the tree, so no rounding
of their bet to the nearest size).

Handled: heads-up, hero first to act, checked to the hero, or facing one bet. Not yet:
facing a raise of the hero's own bet (returns None, and the advice uses its rules).

Ranges are a placeholder until the opponent model (Phase 3): the "medium" preset for both
players, with the hero's own combo added to the hero's range.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from .spot import IP, OOP, BetSizes, Combo, RiverSpot, canonical, normalize_range
from .strategy import RiverStrategy
from .tree import GameTree, action_amount

DEFAULT_SIZES = BetSizes()
PLACEHOLDER_RANGE = "medium"


@dataclass(frozen=True)
class RiverDecision:
    spot: RiverSpot
    node: str  # the hero's decision node in the spot's tree
    hero: int  # OOP or IP
    combo: Combo  # the hero's cards


def _placeholder_range():
    from app.poker.ranges import make_range

    return make_range(PLACEHOLDER_RANGE).combos


def river_decision(hero_cards: Sequence[str], board: Sequence[str], *, pot_now: float, hero_bet: float,
                   villain_bet: float, hero_stack: float, villain_stack: float, hero_in_position: bool,
                   hero_range=None, villain_range=None, sizes: BetSizes = DEFAULT_SIZES,
                   max_raises: int = 1) -> Optional[RiverDecision]:
    """pot_now: everything in the middle, the bets in front of the players included.
    hero_bet, villain_bet: chips in front of each this street. hero_stack, villain_stack:
    chips behind now. None when this isn't a spot the bridge handles."""
    if len(board) != 5:
        return None
    hero_bet, villain_bet = float(hero_bet or 0.0), float(villain_bet or 0.0)
    river_pot = float(pot_now) - hero_bet - villain_bet
    if river_pot <= 0 or hero_bet > 0:
        return None  # nothing in the pot, or the hero already bet this street (facing a raise)
    eff = min(float(hero_stack) + hero_bet, float(villain_stack) + villain_bet)
    if eff < 0:
        return None
    hero = IP if hero_in_position else OOP
    villain = 1 - hero
    try:
        combo = canonical(hero_cards)
        mine = normalize_range(hero_range if hero_range is not None else _placeholder_range(), board)
        if not any(c == combo for c, _ in mine):
            mine = mine + ((combo, 1.0),)  # the hero holds it, whatever the range says
        theirs = villain_range if villain_range is not None else _placeholder_range()
        hero_sizes = villain_sizes = sizes
        if villain_bet > 0:
            villain_sizes = BetSizes(tuple(sizes.bets) + (villain_bet / river_pot,), sizes.raises, True)
        by_player = {hero: (mine, hero_sizes), villain: (theirs, villain_sizes)}
        spot = RiverSpot(tuple(board), river_pot, (eff, eff), by_player[OOP][0], by_player[IP][0],
                         by_player[OOP][1], by_player[IP][1], max_raises)
        spot.index(hero, combo)  # ValueError if the hero's cards clash with the board
    except ValueError:
        return None
    tree = GameTree(spot)

    if villain_bet <= 0:
        node = "" if hero == OOP else "x"
    else:
        parent = tree["x" if hero == OOP else ""]
        bets = [a for a in parent.actions if a.startswith("b")]
        if not bets:
            return None
        target = min(villain_bet, eff)
        token = min(bets, key=lambda a: abs(action_amount(a) - target))
        node = parent.child(token)
    if tree[node].is_terminal or tree[node].player != hero:
        return None
    return RiverDecision(spot, node, hero, combo)


def recommend(strategy: RiverStrategy, decision: RiverDecision) -> Tuple[str, Dict[str, float]]:
    """(the hero's most likely action at the decision, every action's probability)."""
    probs = strategy.action_probs(decision.node, decision.combo)
    order = list(probs)
    best = max(order, key=lambda a: (probs[a], -order.index(a)))
    return best, probs
