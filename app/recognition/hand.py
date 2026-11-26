"""Remember the hand being played from one check to the next (watch mode).

Every read of the table stands on its own: a card half covered by flying chips, or a
frame caught just as a card was dealt, can come back unsure even though the read a
moment earlier knew it. HandMemory carries what is known about the current hand across
checks:

- a card read for sure, or confirmed by you, stays known for the rest of the hand;
- new board cards are added as they come (matched by where they lie on the table, so a
  card missed in one read keeps its place);
- a new hand is recognised from clear evidence: different hole cards, a different card
  where a board card was, the pot starting over, the stacks showing a new hand began, or
  the board and your cards gone and back. One odd frame is not enough.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.state.model import Field, GameState

SAME_SPOT = 0.5  # board cards within half a card width are the same card
POT_RESET = 0.6  # the pot fell below this share of what it was: the hand is over


@dataclass
class _BoardCard:
    x: float  # centre, image pixels
    w: float  # width
    field: Field  # known value with its confidence and source


class HandMemory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.number = 0  # hands seen since watching began
        self._hero: List[Optional[Field]] = [None, None]
        self._board: List[_BoardCard] = []
        self._view: List[Tuple[float, float]] = []  # (x, w) of each card in the board last shown
        self._last_pot: Optional[float] = None
        self._empty_reads = 0  # reads in a row with no cards of yours and no board
        self._started = False
        self._content = False  # this hand has known cards (so a new one counts as another hand)

    # ------------------------------------------------------------ public
    def update(self, state: GameState, board_boxes: List[Tuple[float, float, float, float]],
               stacks_new_hand: bool = False) -> bool:
        """Merge one read into the hand (filling in cards known earlier in it) and return
        True when this read starts a new hand. board_boxes: (x, y, w, h) of each board card
        in `state.board`, in the same order."""
        with self._lock:
            reads = [(x + w / 2.0, float(w), f) for (x, _, w, _), f in zip(board_boxes, state.board)]
            new = self._new_hand(state, reads, stacks_new_hand)
            if new:
                self._begin()
            self._merge_hero(state)
            self._merge_board(state, reads)
            self._content = self._content or any(self._hero) or bool(self._board)
            if state.pot.known:
                self._last_pot = float(state.pot.value)
            return new

    def confirm(self, kind: str, index: int, code: str, field: Optional[Field] = None) -> None:
        """The user (or Claude) said which card this is: keep it for the rest of the hand."""
        with self._lock:
            f = field if field is not None else Field.manual(code)
            if kind == "hero":
                if 0 <= index < 2:
                    self._hero[index] = f
                return
            if not 0 <= index < len(self._view):
                return
            x, w = self._view[index]
            slot = self._find(x, w)
            if slot is not None:
                slot.field = f
            else:
                self._board.append(_BoardCard(x, w, f))
                self._board.sort(key=lambda c: c.x)

    def board_x(self, index: int) -> Optional[float]:
        """Where the board card at this index (as last shown) lies, in image pixels."""
        with self._lock:
            return self._view[index][0] if 0 <= index < len(self._view) else None

    @property
    def hero_cards(self) -> List[Optional[str]]:
        return [f.value if f is not None else None for f in self._hero]

    @property
    def board_cards(self) -> List[str]:
        return [c.field.value for c in self._board]

    # ----------------------------------------------------------- private
    def _begin(self) -> None:
        if self._content or not self._started:
            self.number += 1  # (a stretch between hands with nothing on the table isn't a hand)
        self._hero = [None, None]
        self._board = []
        self._last_pot = None
        self._started = True
        self._content = False

    def _find(self, x: float, w: float) -> Optional[_BoardCard]:
        best = None
        for c in self._board:
            d = abs(c.x - x)
            if d <= SAME_SPOT * max(c.w, w) and (best is None or d < best[0]):
                best = (d, c)
        return best[1] if best else None

    def _new_hand(self, state: GameState, reads, stacks_new_hand: bool) -> bool:
        if not self._started or stacks_new_hand:
            return True
        # different hole cards: two cards read for sure that aren't the ones we had
        mine = {f.value for f in self._hero if f is not None}
        seen = {f.value for f in state.hero_cards if f.known}
        if len(mine) == 2 and seen and not seen <= mine:
            return True
        # a different card where a board card was
        for x, w, f in reads:
            slot = self._find(x, w)
            if slot is not None and f.known and f.value != slot.field.value:
                return True
        # the pot started over
        if (state.pot.known and self._last_pot is not None and self._last_pot > 0
                and float(state.pot.value) < POT_RESET * self._last_pot):
            return True
        # your cards and the board gone (the hand ended), then cards again
        has_cards = any(f.known or f.guess for f in state.hero_cards)
        if not has_cards and not state.board:
            self._empty_reads += 1
            return False
        came_back = self._empty_reads >= 2 and has_cards
        self._empty_reads = 0
        if came_back and not (seen and seen <= mine and len(mine) == 2):
            return True  # (the same two cards back again: just a gap in the reads)
        return False

    def _merge_hero(self, state: GameState) -> None:
        fields = state.hero_cards
        if len(fields) != 2:
            return
        if not any(f.known or f.guess for f in fields):
            return  # no cards in this read (folded, or between hands): nothing to fill in
        # learn what this read knows
        for i, f in enumerate(fields):
            if f.known and f.value not in {h.value for h in self._hero if h is not None}:
                if self._hero[i] is None:
                    self._hero[i] = Field(f.value, f.confidence, f.source)
                elif self._hero[1 - i] is None:
                    self._hero[1 - i] = Field(f.value, f.confidence, f.source)
        # fill in what this read missed
        mine = [h for h in self._hero if h is not None]
        known_here = {f.value for f in fields if f.known}
        spare = [h for h in mine if h.value not in known_here]
        for i, f in enumerate(fields):
            if not f.known and spare:
                h = spare.pop(0)
                fields[i] = Field(h.value, h.confidence, h.source)

    def _merge_board(self, state: GameState, reads) -> None:
        out: List[Tuple[float, float, Field]] = []
        used = set()
        for x, w, f in reads:
            slot = self._find(x, w)
            if slot is not None:
                used.add(id(slot))
                out.append((x, w, slot.field if not f.known or f.source != "manual" and slot.field.source == "manual"
                            else f))
            else:
                if f.known:
                    self._board.append(_BoardCard(x, w, Field(f.value, f.confidence, f.source)))
                    self._board.sort(key=lambda c: c.x)
                    used.add(id(self._find(x, w)))
                out.append((x, w, f))
        # known cards this read missed (covered for a moment) keep their place
        for c in self._board:
            if id(c) not in used:
                out.append((c.x, c.w, c.field))
        out.sort(key=lambda t: t[0])
        out = out[:5]
        state.board = [Field(f.value, f.confidence, f.source, f.guess) for _, _, f in out]
        self._view = [(x, w) for x, w, _ in out]
