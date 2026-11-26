"""Call-or-fold verdicts from pot odds and equity.

This is only exact when calling ends the betting: heads-up on the river, or when the
hero or the opponent is all-in. Then EV(call) = equity x (pot + call) - call is the
whole story and the higher-EV choice against the assumed range is provably best.
In every other spot future betting matters (implied odds, fold equity, position),
which needs a game-theory solver; the verdict is then labelled "pot odds only".

Bet and raise decisions are never computed locally.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.state.model import GameState


@dataclass(frozen=True)
class Verdict:
    action: str  # "call", "fold" or "close"
    exact: bool  # calling ends the betting, so EV(call) is complete
    ev_call: float  # chips, relative to folding (folding = 0)
    call_amount: float
    pot: float  # what calling can win
    equity: float
    stderr: float

    def to_dict(self) -> dict:
        return {"action": self.action, "exact": self.exact, "ev_call": round(self.ev_call, 2),
                "call_amount": self.call_amount, "pot": self.pot, "equity": self.equity, "stderr": self.stderr}


def ev_of_call(equity: float, pot: float, call: float) -> float:
    return equity * (pot + call) - call


def call_or_fold(equity: float, stderr: float, pot: float, call: float, exact: bool) -> Verdict:
    """`pot` is everything the hero can win (matched chips only), `call` what the hero adds."""
    ev = ev_of_call(equity, pot, call)
    # Monte Carlo error on equity turns into EV error; inside 2 standard errors the
    # sign of EV is not reliable, but then the stake is small by construction.
    if abs(ev) <= 2.0 * stderr * (pot + call):
        action = "close"
    else:
        action = "call" if ev > 0 else "fold"
    return Verdict(action, exact, ev, call, pot, equity, stderr)


def facing_call(state: GameState, pot_for_odds: Optional[float]) -> Optional[dict]:
    """The call the hero faces: amount, what it can win, and whether it ends the betting."""
    hero = state.hero
    if hero is None or pot_for_odds is None or not state.to_call.known:
        return None
    to_call = float(state.to_call.value)
    if to_call <= 0:
        return None
    pot = pot_for_odds
    call = to_call
    in_hand = [p for p in state.opponents if p.in_hand.known and p.in_hand.value]
    heads_up = len(in_hand) == 1 and state.active_players().known
    hero_all_in = False
    if hero.stack.known:
        stack = float(hero.stack.value)
        # facing more than our stack: we can only win what we match
        bets = [p.bet for p in state.opponents]
        if hero.bet.known and bets and all(b.known for b in bets):
            raw = max(float(b.value) for b in bets) - float(hero.bet.value)
            if raw > stack:
                pot -= raw - stack
        if call >= stack:
            call = stack
            hero_all_in = True
    villain_all_in = heads_up and in_hand[0].stack.known and float(in_hand[0].stack.value) == 0
    river = state.street.known and state.street.value == "river"
    exact = heads_up and (river or hero_all_in or villain_all_in)
    return {"call": call, "pot": max(0.0, pot), "exact": exact}
