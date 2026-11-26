"""Builds the LOCAL MATH block from a (corrected) GameState.

Only computes what the known values allow; anything that depends on an UNKNOWN
value is simply left out (and the missing value is listed in UNKNOWN FIELDS).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.state.model import GameState

from . import hands
from .decision import call_or_fold, facing_call
from .equity import equity
from .ranges import RangeSpec, make_range, preflop_percentile


def _known_cards(state: GameState) -> Optional[tuple]:
    if len(state.hero_cards) != 2 or not all(c.known for c in state.hero_cards):
        return None
    if not all(c.known for c in state.board) or len(state.board) not in (0, 3, 4, 5):
        return None
    hero = tuple(c.value for c in state.hero_cards)
    board = tuple(c.value for c in state.board)
    if len(set(hero + board)) != len(hero) + len(board):
        return None
    return hero, board


def opponents_in_hand(state: GameState) -> int:
    active = state.active_players()
    if active.known and active.value >= 2:
        return int(active.value) - 1
    n = sum(1 for p in state.opponents if p.in_hand.known and p.in_hand.value)
    return max(1, n)


def pot_for_odds(state: GameState) -> Optional[float]:
    """Everything the hero can win right now, before calling."""
    if not state.pot.known:
        return None
    pot = float(state.pot.value)
    if state.pot_includes_bets:
        return pot
    bets = [p.bet for p in state.players]
    if any(not b.known for b in bets):
        return None
    return pot + sum(float(b.value) for b in bets)


SAMPLES_PER_SECOND = 6000  # equity samples per second of budget (fixed, so results repeat exactly)


def compute(state: GameState, range_spec: Optional[RangeSpec] = None, budget_ms: int = 600) -> Dict[str, Any]:
    cards = _known_cards(state)
    if cards is None:
        return {}
    hero, board = cards
    out: Dict[str, Any] = {}
    if board:
        out["hand"] = hands.describe_hand(hero, board)
        note = hands.shared_note(hero, board)
        if note:
            out["hand_note"] = note  # shown in the instruction only; the text for the AI stays as it is
        d = hands.draws(hero, board)
        if d:
            out["draws"] = d
    else:
        cls = hands.preflop_class(hero)
        pct = preflop_percentile(cls)
        out["hand"] = f"{hands.describe_preflop(hero)} (top {max(1, int(round(pct * 100)))}% of starting hands)"

    n_opp = opponents_in_hand(state)
    spec = range_spec or make_range("medium")
    budget = max(0.1, budget_ms / 1000.0)
    eqs: List[Dict[str, Any]] = []
    specs = [make_range("any")] + ([spec] if spec.combos is not None else [])
    # A fixed number of samples (and a seed taken from the spot) gives the same answer for
    # the same spot every time, so the instruction doesn't flip between two reads of one
    # table. The time limit only matters on a very slow computer.
    samples = max(600, int(SAMPLES_PER_SECOND * budget))
    for s in specs:
        try:
            r = equity(hero, board, n_opp, s.combos, budget_s=max(0.5, 3 * budget / len(specs)),
                       max_iterations=samples)
        except ValueError:
            continue
        eqs.append({"label": s.label, "opponents": n_opp, "equity": r.equity, "stderr": r.stderr,
                    "iterations": r.iterations, "exact": r.exact})
    if eqs:
        out["equity"] = eqs

    pot = pot_for_odds(state)
    facing = facing_call(state, pot)
    if facing is not None:
        call, win = facing["call"], facing["pot"]
        out["pot_odds"] = {"to_call": call, "pot": win, "required_equity": round(call / (win + call), 4)}
        if eqs:
            eq = eqs[-1]  # the selected range if any, otherwise random hands
            verdict = call_or_fold(eq["equity"], eq["stderr"], win, call, facing["exact"])
            out["ev_call"] = round(verdict.ev_call, 2)
            out["verdict"] = dict(verdict.to_dict(), range=eq["label"])

    imp = hands.improvement(hero, board)
    if imp is not None:
        nxt, outs, river = imp
        out["improve"] = {"next_card": round(nxt, 4), "outs": outs,
                          "by_river": round(river, 4) if len(board) == 3 else None}

    hero_p = state.hero
    if hero_p is not None and hero_p.stack.known and state.pot.known and float(state.pot.value) > 0:
        opp = [float(p.stack.value) for p in state.opponents if p.in_hand.value and p.stack.known]
        if opp:
            eff = min(float(hero_p.stack.value), max(opp))
            total = pot if pot is not None else float(state.pot.value)
            if total > 0:
                out["spr"] = round(eff / total, 2)
    return out
