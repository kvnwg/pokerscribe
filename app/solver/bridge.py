"""From the table to a river spot, and from the solver's strategy back to one action.

The spot always starts at the beginning of the river betting, with both players' ranges
there. The bets and raises actually made are in the tree at their real sizes, and they are
the only sizes offered where they were made. The hero's decision is then a node inside
that tree (subgame solving with the real bets in the tree, so no rounding of a bet to the
nearest size, and no hands spread over sizes nobody chose).

Handled: heads-up, hero first to act, checked to the hero, facing a bet, or facing a
raise of the hero's own bet or raise. Facing a raise, the hero may fold, call or go all in.

Ranges come from the betting so far (ranges.py): the line recorded while watching, with
whatever wasn't recorded guessed from the size of the pot. The hero's own combo is always
in the hero's range.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from app.poker.history import HERO, VILLAIN, Line

from .exploitability import best_response
from .ranges import river_ranges
from .spot import IP, OOP, BetSizes, Combo, RiverSpot, canonical, normalize_range
from .strategy import RiverStrategy
from .tree import GameTree, action_amount

# All in is a choice of its own up to six pots. Measured on the tuning hands (experiments.md):
# with it always on offer, answers are fine to about 10 pots deep and useless past 20 (the
# median answer 2.7% of the pot from an equilibrium, against 0.1% without it).
DEFAULT_SIZES = BetSizes(allin_within=6.0)
EPS = 0.01
MIN_REACH = 0.002  # less of the opponent's range than this gets to the node: the solver has no answer there
OWN_REACH = 0.05  # the hero's hand gets to the node less often than this: its mix there means little


@dataclass(frozen=True)
class RiverDecision:
    spot: RiverSpot
    node: str  # the hero's decision node in the spot's tree
    hero: int  # OOP or IP
    combo: Combo  # the hero's cards
    line: Optional[Line] = None  # the betting the ranges were built from (None: ranges were given)
    guessed: bool = False  # some of that line was guessed from the size of the pot


def _path(line: Optional[Line], hero_bet: float, villain_bet: float) -> Optional[List[Tuple[str, float]]]:
    """The river's bets and raises so far, in order, ending with the one the hero faces:
    [(who, chips then in front), ...]. From the record when it fits the chips in front
    now; otherwise the shortest story that does (the hero bet, the opponent raised).
    None when the chips in front make no sense for a hero decision."""
    if villain_bet <= EPS:
        return [] if hero_bet <= EPS else None
    if villain_bet <= hero_bet + EPS:
        return None  # nothing to answer: they called, or the bets were misread
    short = ([(HERO, hero_bet)] if hero_bet > EPS else []) + [(VILLAIN, villain_bet)]
    seen = list(line.river) if line is not None and line.river else None
    if seen and len(seen) >= len(short) and seen[-1][0] == VILLAIN and abs(seen[-1][1] - villain_bet) <= EPS:
        mine = [a for who, a in seen if who == HERO]
        if abs((mine[-1] if mine else 0.0) - hero_bet) <= EPS:
            return [(who, float(a)) for who, a in seen]
    return short


def river_decision(hero_cards: Sequence[str], board: Sequence[str], *, pot_now: float, hero_bet: float,
                   villain_bet: float, hero_stack: float, villain_stack: float, hero_in_position: bool,
                   hero_range=None, villain_range=None, sizes: BetSizes = DEFAULT_SIZES, max_raises: int = 1,
                   line: Optional[Line] = None, big_blind: Optional[float] = None,
                   hero_seat: Optional[str] = None, villain_seat: Optional[str] = None,
                   villain_style: Optional[str] = None,
                   villain_rates: Optional[Tuple[float, float]] = None) -> Optional[RiverDecision]:
    """pot_now: everything in the middle, the bets in front of the players included.
    hero_bet, villain_bet: chips in front of each this street. hero_stack, villain_stack:
    chips behind now. line, big_blind, the seats and the opponent's style and rates: what
    the ranges are worked out from (ranges.river_ranges), unless hero_range and
    villain_range are given. None when this isn't a spot the bridge handles."""
    if len(board) != 5:
        return None
    hero_bet, villain_bet = float(hero_bet or 0.0), float(villain_bet or 0.0)
    river_pot = float(pot_now) - hero_bet - villain_bet
    path = _path(line, hero_bet, villain_bet)
    if river_pot <= 0 or path is None:
        return None
    eff = min(float(hero_stack) + hero_bet, float(villain_stack) + villain_bet)
    if eff < 0:
        return None
    hero = IP if hero_in_position else OOP
    villain = 1 - hero
    seat = {HERO: hero, VILLAIN: villain}
    used, guessed = None, False
    try:
        combo = canonical(hero_cards)
        if hero_range is None or villain_range is None:
            est = river_ranges(board, line, hero_in_position=hero_in_position,
                               pot_bb=river_pot / big_blind if big_blind else None, hero_seat=hero_seat,
                               villain_seat=villain_seat, villain_style=villain_style,
                               villain_rates=villain_rates)
            used, guessed = est.line, est.guessed
            hero_range = est.hero if hero_range is None else hero_range
            villain_range = est.villain if villain_range is None else villain_range
        mine = normalize_range(hero_range, board)
        if not any(c == combo for c, _ in mine):
            typical = sum(w for _, w in mine) / len(mine) if mine else 1.0
            mine = mine + ((combo, typical),)  # the hero holds it, whatever the range says
        # The bets and raises already made are the only ones offered where they were made:
        # the question is what to do now that they happened, so the solution must give every
        # hand that bets there this bet, not spread them over sizes nobody chose.
        made: Dict[int, Dict[str, float]] = {OOP: {}, IP: {}}  # player -> the bet and the first raise they made
        again: Dict[int, List[float]] = {OOP: [], IP: []}  # raises of a raise that were made
        last = 0.0
        for i, (who, amount) in enumerate(path):
            amount = min(amount, eff)
            if i == 0:
                made[seat[who]]["bets"] = amount / river_pot
            elif amount > last + EPS:
                share = (amount - last) / (river_pot + 2.0 * last)
                if i == 1:
                    made[seat[who]]["raises"] = share
                else:
                    again[seat[who]].append(share)
            last = amount
        n_raises = max(0, len(path) - 1)
        if n_raises:
            max_raises = max(max_raises, n_raises + 1)  # the hero may raise again: all in
        by_player = {OOP: sizes, IP: sizes}
        if path:
            for p in (OOP, IP):
                by_player[p] = BetSizes(
                    (made[p]["bets"],) if "bets" in made[p] else sizes.bets,
                    (made[p]["raises"],) if "raises" in made[p] else sizes.raises,
                    sizes.allin,
                    tuple(again[p]) if n_raises else sizes.reraises,  # after those: all in, if at all
                    sizes.allin_within,
                    tuple(k for k in ("bets", "raises") if k in made[p]))  # no all in next to the bet made
        ranges = {hero: mine, villain: villain_range}
        spot = RiverSpot(tuple(board), river_pot, (eff, eff), ranges[OOP], ranges[IP], by_player[OOP],
                         by_player[IP], max_raises)
        spot.index(hero, combo)  # ValueError if the hero's cards clash with the board
    except ValueError:
        return None
    tree = GameTree(spot)

    if not path:
        node = "" if hero == OOP else "x"
    else:
        node = "" if seat[path[0][0]] == OOP else "x"
        for i, (who, amount) in enumerate(path):
            here = tree[node]
            if here.is_terminal or here.player != seat[who]:
                return None
            tokens = [a for a in here.actions if a.startswith("b" if i == 0 else "r")]
            if not tokens:
                return None
            target = min(amount, eff)
            node = here.child(min(tokens, key=lambda a: abs(action_amount(a) - target)))
    if tree[node].is_terminal or tree[node].player != hero:
        return None
    return RiverDecision(spot, node, hero, combo, used, guessed)


def recommend(strategy: RiverStrategy, decision: RiverDecision) -> Optional[Tuple[str, Dict[str, float]]]:
    """(the hero's action at the decision, every action's probability for the hero's hand).

    None when the solution has no answer here: next to none of the opponent's range gets
    to this node in it (they made a bet the solver thinks nobody makes with these ranges),
    so the strategy at the node was never worked out against anything.

    Usually the action is the most likely one in the solver's mix. When the hero's own
    hand all but never gets here in the solution (it was played differently before this
    than the solver would have), the mix for it wasn't worked out either: then the action
    is the best one for this hand against the opponent's solved strategy, at 100%."""
    node, hero = decision.node, decision.hero
    spot = strategy.spot
    theirs = spot.weights(1 - hero)
    if float(theirs @ strategy.reach(1 - hero)[node]) < MIN_REACH * float(theirs.sum()):
        return None
    probs = strategy.action_probs(node, decision.combo)
    order = list(probs)
    mine = spot.index(hero, decision.combo)
    if float(strategy.reach(hero)[node][mine]) < OWN_REACH:
        _, choice = best_response(strategy, hero)
        best = order[int(choice[node][mine])]
        return best, {a: float(a == best) for a in order}
    best = max(order, key=lambda a: (probs[a], -order.index(a)))
    return best, probs
