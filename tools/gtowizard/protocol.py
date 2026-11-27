"""The GTO Wizard Benchmark's game state, read into the picture of a hand the Slumbot tools use.

The game is the same as Slumbot's: heads-up no-limit hold'em, blinds 50 and 100, 20,000 chips each
(200 big blinds), stacks reset every hand. So this module does not have its own rules. It turns the
server's ``action_history`` into a Slumbot action string, parses it with
``tools.slumbot.protocol.parse_action``, and hands bots the same ``BotState`` they get against
Slumbot. Any bot written for one benchmark plays the other unchanged.

What the server sends (``GameServiceResponse`` in the API spec, read 26 Nov 2026)::

    {"hand_id": 123,
     "game": {"game_name": "HUNL 200BB", "starting_stack": 20000, "blinds": [50, 100], ...},
     "game_state": {
        "street": "flop", "common_pot": 400, "total_pot": 600, "board_cards": "AhKd3c",
        "is_hand_over": false, "player_to_act": "user",
        "players": [{"name": ..., "stack": ..., "position": "BB", "hole_cards": "Qd9s"},
                    {"name": ..., "stack": ..., "position": "SB", "hole_cards": null}],
        "legal_actions": ["f", "c", "b"], "raise_range": {"min": 400, "max": 20000},
        "action_history": ["b200", "c", "_", "k", "b200"],
        "has_gto_wizard_folded": false, "winnings": null, "aivat_score": null}}

- ``action_history``: ``f`` fold, ``k`` check, ``c`` call, ``bX`` bet or raise to X chips in this
  betting round (blinds included before the flop), ``_`` end of a round. The same meanings as
  Slumbot's string, with ``_`` for ``/``.
- We are the player whose ``hole_cards`` are shown while the hand is on.
- ``winnings`` and ``aivat_score`` (the luck-adjusted result, in chips) arrive when the hand is over.

The server is the judge of what is legal: bots get its ``legal_actions`` and ``raise_range``. Our
own parse is a cross-check. If the two disagree about whose turn it is, about the pot, or about
checking and calling, the state is flagged (``View.hard``) and the session plays the hand out
safely instead of guessing. A different raise range or fold rule is only noted (``View.soft``).

Nobody has run this against the real server yet, so anything the public spec leaves open is
read leniently here and listed in the README under "What isn't known yet".
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from ..slumbot.bots import BotState, Decision
from ..slumbot.protocol import (BB_SEAT, BIG_BLIND, SB_SEAT, SEAT_NAMES, SMALL_BLIND, STACK,
                                ActionHistory, ActionParseError, parse_action)

GAME_NAME = "HUNL 200BB"
USER = "user"  # ``player_to_act`` when it is our turn
OPPONENT = "gto_wizard"  # the opponent's label in logs
ACTION_CODES = {"fold": "f", "check": "k", "call": "c", "bet": "b", "raise": "b"}

_CARD = re.compile(r"(10|[2-9TJQKA])([cdhs])", re.I)


class ProtocolError(ValueError):
    """The server sent something this client can't read."""


# --- cards and actions ----------------------------------------------------------------------------

def split_cards(cards) -> List[str]:
    """``"AhKd3c"`` -> ``["Ah", "Kd", "3c"]``. None and ``""`` give ``[]``."""
    if cards is None:
        return []
    if isinstance(cards, (list, tuple)):
        cards = "".join(str(c) for c in cards)
    text = re.sub(r"[\s,]", "", str(cards))
    out, pos = [], 0
    for m in _CARD.finditer(text):
        if m.start() != pos:
            break
        pos = m.end()
        rank = "T" if m.group(1) == "10" else m.group(1).upper()
        out.append(rank + m.group(2).lower())
    if pos != len(text):
        raise ProtocolError(f"can't read the cards {cards!r}")
    return out


def slumbot_action(tokens: Sequence[str]) -> str:
    """The server's action list as a Slumbot action string: ``["b200", "c", "_", "k"]`` -> ``"b200c/k"``."""
    parts = []
    for raw in tokens:
        t = str(raw).strip()
        if t == "_":
            parts.append("/")
        elif t in ("f", "k", "c"):
            parts.append(t)
        elif t[:1] == "b":
            try:
                x = float(t[1:])
            except ValueError:
                raise ProtocolError(f"can't read the bet {raw!r} in the action history") from None
            if not math.isfinite(x) or x != int(x) or x <= 0:
                raise ProtocolError(f"the bet {raw!r} is not a whole number of chips")
            parts.append(f"b{int(x)}")
        else:
            raise ProtocolError(f"unknown action {raw!r} in the action history")
    return "".join(parts)


def parse_history(tokens: Sequence[str], postflop_first: int = BB_SEAT) -> ActionHistory:
    """Parse the server's action list with Slumbot's parser.

    Round ends that the server may write after the hand is over (after a fold, a called all-in or
    the last river action) are dropped: Slumbot's string has none there, or all of them.
    """
    s = slumbot_action(tokens)
    try:
        return parse_action(s, postflop_first)
    except ActionParseError as e:
        trimmed = s.rstrip("/")
        if trimmed != s:
            try:
                h = parse_action(trimmed, postflop_first)
            except ActionParseError:
                h = None
            if h is not None and h.over:
                return h
        raise ProtocolError(f"can't follow the action history {list(tokens)!r}: {e}") from e


def seat_of(position) -> int:
    """The server's position name as Slumbot's seat number: 0 big blind, 1 small blind (button).

    The benchmark paper's prompt names the positions "SB" and "BB". Longer spellings and the
    button's names are accepted too: heads-up, the button is the small blind.
    """
    p = re.sub(r"[^A-Z]", "", str(position).upper())
    if p in ("BB", "BIGBLIND"):
        return BB_SEAT
    if p in ("SB", "SMALLBLIND", "BTN", "BU", "BUTTON", "DEALER"):
        return SB_SEAT
    raise ProtocolError(f"unknown position {position!r}")


def request_for(d: Decision) -> Tuple[str, Optional[int]]:
    """The action and amount to send for a bot's decision. A bet names the total for the round."""
    code = ACTION_CODES.get(d.kind)
    if code is None:
        raise ValueError(f"unknown action kind {d.kind!r}")
    if code == "b":
        if d.to is None:
            raise ValueError("a bet needs a total for the round")
        return code, int(d.to)
    return code, None


def safe_action(legal: Sequence[str]) -> Tuple[str, Optional[int]]:
    """Check when it is free, fold otherwise: how a hand is finished when the bot can't play it."""
    codes = [str(a) for a in legal] if isinstance(legal, (list, tuple)) else []
    for code in ("k", "f", "c"):
        if code in codes:
            return code, None
    raise ProtocolError(f"no check, fold or call among the legal actions {legal!r}")


# --- the state a bot sees -------------------------------------------------------------------------

@dataclass
class BenchmarkState(BotState):
    """``BotState`` with the server's word on what is legal.

    ``raise_bounds``, ``legal`` and ``is_legal`` answer from the server's ``legal_actions`` and
    ``raise_range``. Everything else (pot, amount to call, the history) comes from our parse of
    the action history, which the session has checked against the server before a bot sees it.
    """

    hand_id: int = 0
    server_legal: Tuple[str, ...] = ()
    server_raise_range: Optional[Tuple[int, int]] = None

    @property
    def raise_bounds(self) -> Optional[Tuple[int, int]]:
        return self.server_raise_range if "b" in self.server_legal else None

    def legal(self) -> dict:
        return {"fold": "f" in self.server_legal, "check": "k" in self.server_legal,
                "call": "c" in self.server_legal, "raise": self.raise_bounds}

    def is_legal(self, d: Decision) -> bool:
        code = ACTION_CODES.get(d.kind)
        if code is None or code not in self.server_legal:
            return False
        if code == "b":
            b = self.raise_bounds
            return b is not None and d.to is not None and b[0] <= d.to <= b[1]
        return True


# --- reading a response ---------------------------------------------------------------------------

@dataclass
class View:
    """One server response, read."""

    hand_id: int
    me: int  # our seat: 0 big blind, 1 small blind (button)
    hole_cards: List[str]
    opponent_cards: Optional[List[str]]  # shown after a showdown only
    board: List[str]
    tokens: List[str]  # the server's action_history, as sent
    history: Optional[ActionHistory]  # None when the action history can't be parsed
    over: bool
    our_turn: bool
    legal: Tuple[str, ...]
    raise_range: Optional[Tuple[int, int]]
    total_pot: Optional[float]
    winnings: Optional[float]
    aivat_score: Optional[float]
    opponent_folded: bool
    hard: List[str] = field(default_factory=list)  # our parse and the server disagree: don't trust the parse
    soft: List[str] = field(default_factory=list)  # differences worth a note; the server's word is used

    def our_actions(self) -> Optional[int]:
        """How many actions of ours the history holds, or None when it couldn't be parsed."""
        if self.history is None:
            return None
        return sum(1 for a in self.history.actions if a.seat == self.me)

    def bot_state(self, hand_number: int = 0) -> BenchmarkState:
        if self.history is None:
            raise ProtocolError("no parsed history to build a bot state from")
        return BenchmarkState(me=self.me, hole_cards=list(self.hole_cards), board=list(self.board),
                              history=self.history, hand_number=hand_number, hand_id=self.hand_id,
                              server_legal=self.legal, server_raise_range=self.raise_range)


def game_differences(game) -> List[str]:
    """What the reply's ``game`` block says that isn't the game the parser knows.

    The parser plays blinds 50/100 with 20,000 chips, reset every hand. A different description
    is only noted, not refused: the spec doesn't say in which unit the block is written, and a
    hand that really runs on other rules shows up in the pot and turn checks.
    """
    if not isinstance(game, dict):
        return []
    out = []
    try:
        blinds = game.get("blinds")
        if blinds is not None and sorted(float(b) for b in blinds) != [SMALL_BLIND, BIG_BLIND]:
            out.append(f"the game's blinds are given as {blinds!r}, not {SMALL_BLIND}/{BIG_BLIND}")
        stack = game.get("starting_stack")
        if stack is not None and float(stack) != STACK:
            out.append(f"the game's starting stack is given as {stack!r}, not {STACK}")
    except (TypeError, ValueError):
        out.append(f"the game description can't be read: {game!r}")
    if game.get("stack_reset_per_hand") is False:
        out.append("the game says stacks don't reset every hand")
    return out


def _two_cards(cards) -> Optional[List[str]]:
    """Two readable hole cards, or None (hidden, masked or missing)."""
    try:
        out = split_cards(cards)
    except ProtocolError:
        return None
    return out if len(out) == 2 else None


def number(x) -> Optional[float]:
    """A finite number, or None for null and for anything that isn't one."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _raise_range(gs: dict) -> Optional[Tuple[int, int]]:
    r = gs.get("raise_range")
    if not r:
        return None
    lo, hi = math.ceil(float(r["min"])), math.floor(float(r["max"]))
    return (lo, hi) if lo <= hi else None


def read_state(resp: dict, me: Optional[int] = None, postflop_first: int = BB_SEAT) -> View:
    """Read one ``GameServiceResponse``.

    ``me`` is our seat if an earlier response of this hand already told us; otherwise we are the
    one player whose hole cards are shown. Raises ``ProtocolError`` when the basics can't be read
    (no game state, no way to tell who we are), and nothing else: a reply that strays from the
    spec in a way not foreseen here must not crash a session in the middle of a hand. A history
    that can't be parsed, or that disagrees with the server, does not raise: it is reported in
    ``View.hard``.
    """
    try:
        return _read_state(resp, me, postflop_first)
    except ProtocolError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        raise ProtocolError(f"a reply that doesn't have the expected shape "
                            f"({type(e).__name__}: {e})") from e


def _read_state(resp: dict, me: Optional[int], postflop_first: int) -> View:
    try:
        hand_id = int(resp["hand_id"])
        gs = resp["game_state"]
        players = list(gs["players"])
        over = bool(gs["is_hand_over"])
        tokens = [str(t) for t in gs["action_history"]]
    except (KeyError, TypeError, ValueError) as e:
        raise ProtocolError(f"a reply without the expected fields ({type(e).__name__}: {e})") from e
    if len(players) != 2:
        raise ProtocolError(f"{len(players)} players in a heads-up game")
    seats = [seat_of(p.get("position")) for p in players]
    if sorted(seats) != [BB_SEAT, SB_SEAT]:
        raise ProtocolError(f"positions {[p.get('position') for p in players]!r} are not one SB and one BB")
    cards = [_two_cards(p.get("hole_cards")) for p in players]
    if me is None:
        shown = [i for i, c in enumerate(cards) if c]
        if len(shown) != 1:
            raise ProtocolError("can't tell which player we are: hole cards are shown for "
                                f"{len(shown)} players")
        mine = shown[0]
        me = seats[mine]
    else:
        mine = seats.index(me)
    legal = tuple(str(a) for a in (gs.get("legal_actions") or ()))
    view = View(hand_id=hand_id, me=me, hole_cards=cards[mine] or [], opponent_cards=cards[1 - mine],
                board=[], tokens=tokens, history=None, over=over,
                our_turn=not over and gs.get("player_to_act") == USER, legal=legal,
                raise_range=None, total_pot=number(gs.get("total_pot")),
                winnings=number(gs.get("winnings")), aivat_score=number(gs.get("aivat_score")),
                opponent_folded=bool(gs.get("has_gto_wizard_folded")))
    view.soft.extend(game_differences(resp.get("game")))
    try:
        view.raise_range = _raise_range(gs)
    except (KeyError, TypeError, ValueError, OverflowError):
        view.soft.append(f"the raise range {gs.get('raise_range')!r} can't be read; no bet is offered to the bot")
        view.legal = tuple(a for a in legal if a != "b")
    if view.total_pot is None and gs.get("total_pot") is not None:
        view.hard.append(f"the total pot {gs.get('total_pot')!r} is not a number")
    if not cards[mine]:
        view.hard.append(f"our hole cards are {players[mine].get('hole_cards')!r}")
    try:
        view.board = split_cards(gs.get("board_cards"))
    except ProtocolError as e:
        view.hard.append(str(e))
    try:
        view.history = parse_history(tokens, postflop_first)
    except ProtocolError as e:
        view.hard.append(str(e))
        return view
    _compare(view)
    return view


def _compare(v: View) -> None:
    """Our parse against the server's own description of the same state."""
    h = v.history
    if h.over != v.over:
        v.hard.append(f"the server says the hand is {'over' if v.over else 'not over'}, "
                      f"our parse of {h.action!r} says the opposite")
        return
    if v.over or not v.our_turn:
        return
    if h.to_act != v.me:
        v.hard.append(f"the server says it is our turn ({SEAT_NAMES[v.me]}), our parse of "
                      f"{h.action!r} says it is the {SEAT_NAMES[h.to_act]}'s")
        return
    if v.total_pot is not None and v.total_pot != h.pot:
        v.hard.append(f"the server's total pot is {v.total_pot:g}, ours is {h.pot} at {h.action!r}")
    if ("k" in v.legal) != h.can_check() or ("c" in v.legal) != h.can_call():
        v.hard.append(f"the server's legal actions {list(v.legal)!r} don't fit {h.action!r} "
                      f"(to call: {h.to_call()})")
    if ("f" in v.legal) != h.can_fold():
        v.soft.append(f"fold is {'legal' if 'f' in v.legal else 'not legal'} at the server and "
                      f"{'legal' if h.can_fold() else 'not legal'} for us at {h.action!r}")
    ours = h.raise_bounds()
    theirs = v.raise_range if "b" in v.legal else None
    if ours != theirs:
        v.soft.append(f"the server's raise range is {theirs}, ours is {ours} at {h.action!r}")


class Reader:
    """Reads responses, and settles which seat opens the betting after the flop.

    In heads-up hold'em the big blind acts first after the flop, and the benchmark says it follows
    the ACPC's rules, which do the same. But the benchmark paper's own rules text says the small
    blind acts first on every round. The first decision after a flop settles it: only one order
    makes it our turn. If the standard order doesn't fit and the other does, the reader switches
    for good and ``switched`` is set, so the session can say so loudly.
    """

    def __init__(self, postflop_first: int = BB_SEAT):
        self.postflop_first = postflop_first
        self.confirmed = False
        self.switched = False

    def read(self, resp: dict, me: Optional[int] = None) -> View:
        view = read_state(resp, me, self.postflop_first)
        if self.confirmed or view.history is None or view.over or not view.our_turn \
                or view.history.street == 0:
            return view
        if not view.hard:
            self.confirmed = True
            return view
        other = read_state(resp, me, 1 - self.postflop_first)
        if other.history is not None and not other.hard:
            self.postflop_first = 1 - self.postflop_first
            self.confirmed = self.switched = True
            return other
        return view
