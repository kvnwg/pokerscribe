"""Slumbot's rules and its action string, parsed into a per-street history.

Slumbot's definitions (https://slumbot.com, the API page and sample_api.py):

- Heads-up no-limit hold'em, blinds 50 and 100, both stacks 20,000 chips (200 big blinds),
  reset after every hand.
- Seat 0 is the big blind: second to act preflop, first to act on the flop, turn and river.
  Seat 1 is the small blind, which is also the button. ``client_pos`` in a response is our seat.
- The action string lists every action of the hand so far. ``k`` check, ``c`` call, ``f`` fold,
  ``b<n>`` bet or raise, and ``/`` ends a street. After an all-in call the remaining streets are
  empty: ``b20000c///``.
- ``b<n>`` is the bettor's total on that street only, blinds included preflop. In ``b200c/kb400``
  the small blind raises to 200 preflop, the big blind calls, then on the flop the big blind
  checks and the small blind bets 400 (a pot-size bet). If called, each player has put 600 in.
- A bet or raise must add at least the previous bet or raise on the street, and at least one big
  blind. A player may always go all-in for less.

``parse_action`` validates the string like the reference parser in sample_api.py and returns
an ``ActionHistory``. It raises ``ActionParseError`` for anything the reference parser rejects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

SMALL_BLIND = 50
BIG_BLIND = 100
STACK = 20_000
NUM_STREETS = 4
STREETS = ("preflop", "flop", "turn", "river")
BB_SEAT = 0  # client_pos 0: big blind, acts first after the flop
SB_SEAT = 1  # client_pos 1: small blind and button, acts first preflop
SEAT_NAMES = {BB_SEAT: "BB", SB_SEAT: "SB"}
BOARD_SIZE = (0, 3, 4, 5)  # cards on the board during each street

_TOKEN = re.compile(r"b\d*|[kcf/]|.")


class ActionParseError(ValueError):
    """The action string is not one Slumbot's reference parser would accept."""


@dataclass(frozen=True)
class Action:
    street: int  # 0 preflop .. 3 river
    seat: int  # 0 big blind, 1 small blind
    kind: str  # "fold", "check", "call", "bet" (first bet on a street) or "raise"
    to: int  # the seat's chips in on this street after the action
    added: int  # chips this action put in
    total: int  # the seat's chips in for the whole hand after the action
    all_in: bool
    code: str  # the token as it appears in the string, e.g. "b400"

    @property
    def street_name(self) -> str:
        return STREETS[self.street]

    def describe(self, me: Optional[int] = None, opponent: str = "slumbot") -> str:
        who = SEAT_NAMES[self.seat] if me is None else ("me" if self.seat == me else opponent)
        if self.kind in ("fold", "check"):
            return f"{who} {self.kind}s"
        if self.kind == "call":
            return f"{who} calls {self.added}" + (" (all-in)" if self.all_in else "")
        return f"{who} {self.kind}s to {self.to}" + (" (all-in)" if self.all_in else "")

    def to_dict(self) -> dict:
        return {"seat": self.seat, "kind": self.kind, "to": self.to, "added": self.added,
                "total": self.total, "all_in": self.all_in}


@dataclass
class ActionHistory:
    """The hand so far, from the action string alone (no cards)."""

    action: str
    streets: List[List[Action]] = field(default_factory=lambda: [[] for _ in range(NUM_STREETS)])
    street: int = 0  # the current street, or the last one reached when the hand is over
    to_act: Optional[int] = SB_SEAT  # None when the hand is over
    folded: Optional[int] = None  # the seat that folded
    contributed: List[int] = field(default_factory=lambda: [BIG_BLIND, SMALL_BLIND])  # whole hand
    street_in: List[int] = field(default_factory=lambda: [BIG_BLIND, SMALL_BLIND])  # this street
    last_raise: int = BIG_BLIND - SMALL_BLIND  # size of the last bet or raise on this street, 0 if none
    last_aggressor: Optional[int] = BB_SEAT  # who made the last bet on this street (the blind preflop)
    postflop_first: int = BB_SEAT  # who opens the flop, turn and river (the big blind, at Slumbot)

    # --- the hand ---
    @property
    def actions(self) -> List[Action]:
        return [a for s in self.streets for a in s]

    @property
    def over(self) -> bool:
        return self.to_act is None

    @property
    def showdown(self) -> bool:
        return self.over and self.folded is None

    @property
    def all_in(self) -> bool:
        return max(self.contributed) >= STACK and self.contributed[0] == self.contributed[1]

    @property
    def pot(self) -> int:
        return sum(self.contributed)

    def board_cards_needed(self) -> int:
        """How many board cards are out on the current street (all five once all-in is called)."""
        return BOARD_SIZE[NUM_STREETS - 1] if self.all_in else BOARD_SIZE[self.street]

    # --- the player to act ---
    def to_call(self) -> int:
        if self.over:
            return 0
        me = self.to_act
        return self.street_in[1 - me] - self.street_in[me]

    def stack_behind(self, seat: int) -> int:
        return STACK - self.contributed[seat]

    def can_check(self) -> bool:
        return not self.over and self.to_call() == 0

    def can_call(self) -> bool:
        return not self.over and self.to_call() > 0

    def can_fold(self) -> bool:
        return self.can_call()

    def can_raise(self) -> bool:
        """A bet or raise is possible: neither player is all-in yet."""
        return not self.over and max(self.contributed) < STACK

    def raise_bounds(self) -> Optional[Tuple[int, int]]:
        """(smallest, largest) street total a ``b<n>`` may name now, or None if no bet is allowed."""
        if not self.can_raise():
            return None
        me = self.to_act
        facing = self.street_in[1 - me]
        remaining = STACK - max(self.contributed)  # chips the bettor can add beyond the current bet
        step = max(self.last_raise, BIG_BLIND)
        step = min(step, remaining)
        return facing + step, facing + remaining

    def legal_incr(self, incr: str) -> bool:
        try:
            parse_action(self.action + incr, self.postflop_first)
        except ActionParseError:
            return False
        return True

    # --- for logs ---
    def by_street(self, me: Optional[int] = None, opponent: str = "slumbot") -> dict:
        out = {}
        for i, acts in enumerate(self.streets):
            if i <= self.street:
                out[STREETS[i]] = [a.describe(me, opponent) for a in acts]
        return out

    def to_dict(self) -> dict:
        return {STREETS[i]: [a.to_dict() for a in acts]
                for i, acts in enumerate(self.streets) if i <= self.street}


def tokenize(action: str) -> List[str]:
    return _TOKEN.findall(action)


def parse_action(action: str, postflop_first: int = BB_SEAT) -> ActionHistory:
    """Parse a full Slumbot action string. See the module docstring for the format.

    ``postflop_first`` is the seat that opens the flop, turn and river. At Slumbot that is the
    big blind, the default. ``tools/gtowizard`` passes the other seat if that server turns out
    to deal the betting the other way round.
    """
    h = ActionHistory(action=action, postflop_first=postflop_first)
    toks = tokenize(action)
    i = 0
    street_closes = False  # a check or call now would end the street
    while i < len(toks):
        tok = toks[i]
        i += 1
        if h.over:
            raise ActionParseError(f"extra characters after the end of the hand: {action!r}")
        if tok == "/":
            raise ActionParseError(f"unexpected '/' at token {i} in {action!r}")
        me = h.to_act
        opp = 1 - me
        to_call = h.street_in[opp] - h.street_in[me]
        if tok == "k" or tok == "c":
            if tok == "k" and to_call != 0:
                raise ActionParseError(f"illegal check facing a bet in {action!r}")
            if tok == "c" and to_call == 0:
                raise ActionParseError(f"illegal call with nothing to call in {action!r}")
            h.street_in[me] += to_call
            h.contributed[me] += to_call
            kind = "check" if tok == "k" else "call"
            h.streets[h.street].append(Action(h.street, me, kind, h.street_in[me], to_call,
                                              h.contributed[me], h.contributed[me] >= STACK, tok))
            if tok == "c" and h.contributed[me] >= STACK:
                # An all-in is called: the rest of the streets are empty, with or without slashes.
                rest = toks[i:]
                if any(t != "/" for t in rest) or len(rest) > NUM_STREETS - 1 - h.street:
                    raise ActionParseError(f"unexpected characters after an all-in call: {action!r}")
                if rest and len(rest) != NUM_STREETS - 1 - h.street:
                    raise ActionParseError(f"missing slash after an all-in call: {action!r}")
                h.street = NUM_STREETS - 1
                h.to_act = None
                h.last_raise = 0
                return h
            if street_closes:
                if h.street == NUM_STREETS - 1:
                    h.to_act = None  # showdown
                else:
                    if i < len(toks):
                        if toks[i] != "/":
                            raise ActionParseError(f"missing slash at the end of {STREETS[h.street]}: {action!r}")
                        i += 1
                    h.street += 1
                    h.street_in = [0, 0]
                    h.to_act = h.postflop_first
                    h.last_raise = 0
                    h.last_aggressor = None
                street_closes = False
            else:
                h.to_act = opp
                street_closes = True
                if tok == "c":
                    h.last_raise = 0
        elif tok == "f":
            if to_call == 0:
                raise ActionParseError(f"illegal fold when checking is free in {action!r}")
            h.streets[h.street].append(Action(h.street, me, "fold", h.street_in[me], 0,
                                              h.contributed[me], False, tok))
            if i < len(toks):
                raise ActionParseError(f"extra characters after a fold: {action!r}")
            h.folded = me
            h.to_act = None
        elif tok.startswith("b"):
            if len(tok) == 1:
                raise ActionParseError(f"bet with no size in {action!r}")
            to = int(tok[1:])
            bounds = h.raise_bounds()
            if bounds is None:
                raise ActionParseError(f"bet after an all-in in {action!r}")
            lo, hi = bounds
            if to < lo:
                raise ActionParseError(f"bet to {to} is below the minimum {lo} in {action!r}")
            if to > hi:
                raise ActionParseError(f"bet to {to} is above the maximum {hi} in {action!r}")
            added = to - h.street_in[me]
            kind = "bet" if h.street > 0 and h.last_aggressor is None else "raise"
            h.last_raise = to - h.street_in[opp]
            h.street_in[me] = to
            h.contributed[me] += added
            h.last_aggressor = me
            h.streets[h.street].append(Action(h.street, me, kind, to, added, h.contributed[me],
                                              h.contributed[me] >= STACK, tok))
            h.to_act = opp
            street_closes = True
        else:
            raise ActionParseError(f"unexpected character {tok!r} in {action!r}")
    return h


def incr_for(kind: str, to: Optional[int] = None) -> str:
    """The incremental action string to send: "f", "k", "c" or "b<to>"."""
    if kind == "fold":
        return "f"
    if kind == "check":
        return "k"
    if kind == "call":
        return "c"
    if kind in ("bet", "raise"):
        if to is None:
            raise ValueError("a bet needs a street total")
        return f"b{int(to)}"
    raise ValueError(f"unknown action kind {kind!r}")


def chips_won(history: ActionHistory, me: int, my_rank: Optional[int] = None,
              opp_rank: Optional[int] = None) -> Optional[int]:
    """What ``me`` wins (negative: loses) in a finished hand.

    At a showdown the hand ranks are needed (lower is better, as in treys); returns None
    without them. Each player can only lose what they put in, so the result is the smaller
    contribution either way (stacks are equal, so contributions match at a showdown).
    """
    if not history.over:
        raise ValueError("the hand is not over")
    if history.folded is not None:
        loser = history.folded
        return -history.contributed[me] if loser == me else history.contributed[loser]
    if my_rank is None or opp_rank is None:
        return None
    stake = min(history.contributed)
    if my_rank < opp_rank:
        return stake
    if my_rank > opp_rank:
        return -stake
    return 0
