"""The betting so far in the hand being played, kept while watching.

One read of the table shows only the present: the cards, the pot and the chips in front of
each player right now. Who bet on the flop is gone by the river. BettingRecord is fed
every read (app/poker/profiles.py passes them on) and keeps, per betting round, the pot
the round began with and each different set of bets it saw, in order. From that, `line`
gives what the two players left on the river need to know about each earlier round:

- how big the last bet was (before the flop: how many big blinds each player put in;
  after it: the bet as a share of the pot the round began with; 0 = checked through);
- who made it: you, your opponent, or a player who has folded since.

How the last bettor is found: bets only grow during a round, and everyone still in has
matched the biggest one by the end of it. So the round's level is the biggest bet seen,
and the player first seen at that level made the bet the others called. You only ever
call after a read that shows the bet in front of someone else, so when your own chips
are among the first at the level, the bet was yours.

Anything a read didn't show stays unknown (None). The river's own bets and raises are kept
in order too, so a raise of your bet can be told from a re-raise of your raise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from app.state.model import GameState, Player

HERO, VILLAIN, OTHER = "hero", "villain", "other"
ROUNDS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}
EPS = 0.01
LIMP = 1.2  # each put in at most this many big blinds before the flop: nobody raised


@dataclass(frozen=True)
class StreetLine:
    """One earlier betting round, as the two players left saw it.

    size: before the flop, the big blinds each of them put in (1 = nobody raised); on the
    flop and turn, the last bet as a share of the pot the round began with (0 = checked
    through). None = not known.
    aggressor: who made that last bet or raise: HERO, VILLAIN, OTHER (a player who has
    folded since), or None when nobody did or it isn't known.
    """

    size: Optional[float] = None
    aggressor: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.size is not None

    def swapped(self) -> "StreetLine":
        """The same round from the opponent's side."""
        other = {HERO: VILLAIN, VILLAIN: HERO}.get(self.aggressor, self.aggressor)
        return StreetLine(self.size, other)


@dataclass(frozen=True)
class Line:
    """The betting before the river, and the river's bets so far.

    river: the bets and raises on the river in order, as (who, chips that player then had
    in front): (("villain", 50), ("hero", 150)) is a bet of 50 raised to 150. () = nobody
    has bet yet. None = not known.
    """

    preflop: StreetLine = StreetLine()
    flop: StreetLine = StreetLine()
    turn: StreetLine = StreetLine()
    river: Optional[Tuple[Tuple[str, float], ...]] = None

    @property
    def streets(self) -> Tuple[StreetLine, StreetLine, StreetLine]:
        return self.preflop, self.flop, self.turn

    @property
    def empty(self) -> bool:
        return not any(s.known for s in self.streets)

    def describe(self) -> str:
        """Short wording, e.g. "before the flop they raised to 3 big blinds; ..."."""
        who = {HERO: "you", VILLAIN: "they", OTHER: "someone else", None: "someone"}
        parts = []
        s = self.preflop
        if s.known:
            parts.append("nobody raised before the flop" if s.size <= LIMP
                         else f"before the flop {who[s.aggressor]} raised to {s.size:.3g} big blinds")
        for name, s in (("flop", self.flop), ("turn", self.turn)):
            if s.known:
                parts.append(f"the {name} was checked" if s.size <= 0
                             else f"on the {name} {who[s.aggressor]} bet {round(100 * s.size)}% of the pot")
        return "; ".join(parts)


@dataclass
class _Round:
    pot: Optional[float] = None  # chips in the middle when the round began
    steps: List[Dict[str, float]] = field(default_factory=list)  # each different set of bets seen, in order


def _default_key(p: Player) -> Optional[str]:
    """Who this is within one hand: the seat's position, else its place on the table."""
    if p.is_hero:
        return HERO
    if p.position.known:
        return f"pos:{p.position.value}"
    if p.anchor:
        return f"at:{float(p.anchor[0]):.0f},{float(p.anchor[1]):.0f}"
    return f"seat:{p.seat}"


class BettingRecord:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._hand: Optional[int] = None
        self._rounds: Dict[int, _Round] = {}
        self._board_len = 0
        self._cards: Tuple[str, ...] = ()
        self._bb: Optional[float] = None

    # ------------------------------------------------------------ feeding
    def update(self, state: GameState, hand_number: Optional[int] = None,
               key_for: Optional[Callable[[Player], Optional[str]]] = None) -> None:
        """Feed one read. hand_number: the hand memory's count, when there is one (a new
        number starts a new hand; without it a shorter board or different hole cards do).
        key_for: a name for each opponent that stays the same from read to read."""
        n = len(state.board)
        cards = tuple(sorted(c.value for c in state.hero_cards if c.known))
        if hand_number is not None:
            new = hand_number != self._hand
        else:
            new = n < self._board_len or (len(cards) == 2 and len(self._cards) == 2 and cards != self._cards)
        if new:
            self._rounds = {}
            self._cards = ()
            self._bb = None
        self._hand = hand_number
        self._board_len = n
        if len(cards) == 2:
            self._cards = cards
        if n not in ROUNDS:
            return
        if state.blinds.known and state.blinds.value:
            try:
                self._bb = float(state.blinds.value[1]) or self._bb
            except (TypeError, ValueError, IndexError):
                pass
        rnd = self._rounds.setdefault(n, _Round())
        bets: Dict[str, float] = {}
        for p in state.players:
            key = self._key(p, key_for)
            if key is not None and p.bet.known:
                bets[key] = float(p.bet.value)
        if rnd.pot is None:
            rnd.pot = self._pot_before(state)
        if bets and (not rnd.steps or rnd.steps[-1] != bets):
            rnd.steps.append(bets)

    @staticmethod
    def _key(p: Player, key_for) -> Optional[str]:
        if p.is_hero:
            return HERO
        key = key_for(p) if key_for is not None else None
        return key if key is not None else _default_key(p)

    @staticmethod
    def _pot_before(state: GameState) -> Optional[float]:
        """The chips from earlier rounds: the pot without this round's bets."""
        if not state.pot.known:
            return None
        pot = float(state.pot.value)
        if not state.pot_includes_bets:
            return pot
        live = [p for p in state.players if not (p.in_hand.known and p.in_hand.value is False)]
        if any(not p.bet.known for p in live):
            return None
        return pot - sum(float(p.bet.value) for p in state.players if p.bet.known)

    # ------------------------------------------------------------ reading
    def line(self, state: GameState, key_for: Optional[Callable[[Player], Optional[str]]] = None) -> Optional[Line]:
        """The betting so far for you and the one opponent left. None when more than one
        opponent is still in, or nothing was recorded for this hand."""
        left = [p for p in state.opponents if not (p.in_hand.known and p.in_hand.value is False)]
        if len(left) != 1 or state.hero is None or not self._rounds:
            return None
        villain = self._key(left[0], key_for)
        if villain is None or villain == HERO:
            return None
        return Line(self._street(0, villain), self._street(3, villain), self._street(4, villain),
                    self._river(villain))

    def _street(self, n: int, villain: str) -> StreetLine:
        rnd = self._rounds.get(n)
        if rnd is None or not rnd.steps:
            return StreetLine()
        if not any(HERO in s for s in rnd.steps) or not any(villain in s for s in rnd.steps):
            return StreetLine()  # the bets of one of the two were never read this round
        level = max(max(s.values()) for s in rnd.steps)
        if n == 0:
            if not self._bb:
                return StreetLine()
            size = level / self._bb
            if size <= LIMP:
                return StreetLine(size, None)
        else:
            if level <= EPS:
                return StreetLine(0.0, None)
            if rnd.pot is None or rnd.pot <= EPS:
                return StreetLine()
            size = level / rnd.pot
        first = next(s for s in rnd.steps if max(s.values()) >= level - EPS)
        at = {k for k, v in first.items() if v >= level - EPS}
        if HERO in at:
            who: Optional[str] = HERO
        elif at == {villain}:
            who = VILLAIN
        elif villain not in at:
            who = OTHER
        else:
            who = None  # your opponent and someone else, seen at the level together
        return StreetLine(size, who)

    def _river(self, villain: str) -> Optional[Tuple[Tuple[str, float], ...]]:
        rnd = self._rounds.get(5)
        if rnd is None or not rnd.steps:
            return None
        seen = set()
        for s in rnd.steps:
            if HERO not in s or villain not in s:
                return None
            for who, key in ((HERO, HERO), (VILLAIN, villain)):
                if s[key] > EPS:
                    seen.add((round(s[key], 2), who))
        path = tuple((who, amount) for amount, who in sorted(seen))
        # bets and raises take turns and grow: anything else means a read was missed
        for (w1, a1), (w2, a2) in zip(path, path[1:]):
            if w1 == w2 or a2 <= a1 + EPS:
                return None
        return path
