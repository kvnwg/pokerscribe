"""The bot interface for playing Slumbot, a check/call bot, and the B0 adapter stub.

A bot gets a ``BotState`` (our cards, the board, the parsed history, what is legal) and returns
a ``Decision``. Amounts are chips as Slumbot counts them (blinds 50/100, stacks 20,000); a bet or
raise names the street total, like ``b<n>`` in the action string. ``BotState`` also gives the
same numbers in big blinds for bots that think in big blinds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .protocol import (BIG_BLIND, SEAT_NAMES, SMALL_BLIND, STACK, STREETS, ActionHistory,
                       incr_for)


@dataclass(frozen=True)
class Decision:
    kind: str  # "fold", "check", "call", "bet" or "raise" ("bet" and "raise" are the same to Slumbot)
    to: Optional[int] = None  # street total in chips for a bet or raise

    def incr(self) -> str:
        return incr_for(self.kind, self.to)


@dataclass
class BotState:
    me: int  # our seat: 0 big blind, 1 small blind (button)
    hole_cards: List[str]
    board: List[str]
    history: ActionHistory
    hand_number: int = 0  # 1-based within the session
    small_blind: int = SMALL_BLIND
    big_blind: int = BIG_BLIND
    stack: int = STACK

    @property
    def position(self) -> str:
        return SEAT_NAMES[self.me]

    @property
    def street(self) -> str:
        return STREETS[self.history.street]

    @property
    def pot(self) -> int:
        return self.history.pot

    @property
    def to_call(self) -> int:
        return self.history.to_call()

    @property
    def stack_behind(self) -> int:
        return self.history.stack_behind(self.me)

    @property
    def raise_bounds(self) -> Optional[Tuple[int, int]]:
        return self.history.raise_bounds()

    def legal(self) -> Dict[str, object]:
        return {"fold": self.history.can_fold(), "check": self.history.can_check(),
                "call": self.history.can_call(), "raise": self.raise_bounds}

    def is_legal(self, d: Decision) -> bool:
        if d.kind == "fold":
            return self.history.can_fold()
        if d.kind == "check":
            return self.history.can_check()
        if d.kind == "call":
            return self.history.can_call()
        if d.kind in ("bet", "raise"):
            b = self.raise_bounds
            return b is not None and d.to is not None and b[0] <= d.to <= b[1]
        return False

    def in_bb(self) -> dict:
        """The decision in big blinds, the unit the app and the simulator use."""
        bb = float(self.big_blind)
        b = self.raise_bounds
        return {
            "position": self.position, "street": self.street, "hole_cards": list(self.hole_cards),
            "board": list(self.board), "pot_bb": self.pot / bb, "to_call_bb": self.to_call / bb,
            "stack_bb": self.stack_behind / bb, "eff_stack_bb": min(
                self.history.stack_behind(0), self.history.stack_behind(1)) / bb,
            "min_raise_to_bb": None if b is None else b[0] / bb,
            "max_raise_to_bb": None if b is None else b[1] / bb,
            "history": [f"{a.street_name}:{SEAT_NAMES[a.seat]}:{a.kind}"
                        + (f" {a.to / bb:g}" if a.kind in ("bet", "raise") else "")
                        for a in self.history.actions],
        }


class Bot:
    """Subclass and implement ``act``. ``start_hand`` and ``end_hand`` are optional hooks."""

    name = "bot"
    version = "1"

    def start_hand(self, state: BotState) -> None:
        pass

    def act(self, state: BotState) -> Decision:
        raise NotImplementedError

    def end_hand(self, state: BotState, result: dict) -> None:
        pass


class CheckCallBot(Bot):
    """Never folds, never bets: checks when it can, calls otherwise. The usual API smoke test."""

    name = "checkcall"

    def act(self, state: BotState) -> Decision:
        return Decision("check") if state.history.can_check() else Decision("call")


class B0Bot(Bot):
    """Adapter for the frozen baseline B0 (``docs/research/baseline_tuning.json``). Not wired yet.

    B0 is ``app.poker.advice.advise`` with the default ``TUNING``, as ``tools/simulate.py`` drives
    it at a 6-max table. It gets wired here once the simulator has a heads-up mode, so the
    heads-up ``GameState`` is built in one place and Slumbot results line up with the simulator.

    The plan for ``act``:
    1. ``state.in_bb()`` gives the decision in big blinds (Slumbot: blinds 0.5/1, 200bb stacks).
       Our seat is ``BB`` or ``SB``; the small blind is the button.
    2. Build the simulator's heads-up ``GameState`` from it (two players, button = SB).
    3. Call ``advise`` and map the instruction to a ``Decision``: fold / check / call, or a raise
       to ``round(to_bb * 100)`` chips clamped into ``state.raise_bounds``; an all-in is the top.
    4. If the advice is not legal here (for example a fold when checking is free), check or call
       and count it, as the simulator's checks do.
    """

    name = "b0"

    def __init__(self):
        raise NotImplementedError(
            "B0 is wired up once tools/simulate.py has a heads-up mode; use --bot checkcall for now")

    def act(self, state: BotState) -> Decision:  # pragma: no cover - not wired yet
        raise NotImplementedError


BOTS = {"checkcall": CheckCallBot, "b0": B0Bot}


def make_bot(name: str) -> Bot:
    try:
        cls = BOTS[name]
    except KeyError:
        raise SystemExit(f"unknown bot {name!r}; choose from {', '.join(sorted(BOTS))}")
    return cls()
