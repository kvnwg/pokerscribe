"""Follow a hand across live captures (watch mode).

Some poker clients never print bet amounts: chips go straight into the pot. By
watching each player's stack, the tracker recovers how much everyone has put in this
hand and this betting round, how much the hero has invested, the amount to call and
the blinds. It only fills those in when the numbers add up: the chips that left the
stacks must equal the pot (or the pot plus the bets shown in front of the players, on
clients whose pot leaves out the current round). When they don't (a stack was misread,
watching began in the middle of a hand), the values stay UNKNOWN.

Where the hand began is found from the numbers, not from guessing when a hand starts:
the tracker keeps the stacks it has seen, and the start of this hand is the most recent
set of stacks from which the chips that have left add up exactly to the pot. That holds
from the stacks just before the blinds went in, and from no moment after it (the pot
was never empty again). So a missed capture, a pause to confirm cards or a payout shown
late doesn't throw it off.

Why the amount to call is simply "most chips anyone has put in this hand minus what you
have put in": every earlier betting round ended with all remaining players level, so
the difference can only come from the current round.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.state.model import Field, GameState, Player

SEAT_TOLERANCE = 40.0  # px: a seat is drawn in the same place on every capture
CONFIDENCE = 0.85
HISTORY = 300  # sets of stacks kept to find where the hand began

Key = Tuple[float, ...]
HERO: Key = ("hero",)  # type: ignore[assignment]


@dataclass
class TrackInfo:
    new_hand: bool = False
    valid: bool = False  # the stack changes add up to the pot
    hero_invested: Optional[float] = None  # chips the hero has put in this hand
    contributions: Dict[int, float] = field(default_factory=dict)  # index in state.players -> chips this hand
    street_bets: Dict[int, float] = field(default_factory=dict)  # index in state.players -> chips this round
    to_call: Optional[float] = None
    blinds: Optional[Tuple[float, float]] = None
    pot_includes_bets: Optional[bool] = None
    note: str = ""


class HandTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._seats: Dict[Key, float] = {}  # latest known stack per seat
        self._history: List[Dict[Key, float]] = []  # earlier sets of stacks, oldest first
        self._dropped = 0  # snapshots dropped from the front, so positions stay comparable
        self._start_at: Optional[int] = None  # snapshot this hand started from
        self._blinds: Optional[Tuple[float, float]] = None
        self._table_blinds: Optional[Tuple[float, float]] = None  # last blinds seen cleanly, kept across hands
        self._new_blinds: Optional[Tuple[float, float]] = None  # different blinds seen once, not yet believed
        self._levels: Dict[int, float] = {}  # board size -> most chips anyone had put in by then
        self.hands_seen = 0

    # -------------------------------------------------------------- seats
    @staticmethod
    def _key(p: Player) -> Optional[Key]:
        if p.is_hero:
            return HERO
        if not p.anchor:
            return None
        return (float(p.anchor[0]), float(p.anchor[1]))

    @staticmethod
    def _match(key: Key, keys) -> Optional[Key]:
        if key in keys:
            return key
        if len(key) != 2:
            return None
        best = None
        for k in keys:
            if len(k) != 2:
                continue
            d = abs(k[0] - key[0]) + abs(k[1] - key[1])
            if d <= SEAT_TOLERANCE and (best is None or d < best[0]):
                best = (d, k)
        return best[1] if best else None

    def _canon(self, key: Key) -> Key:
        """The name this seat already has, so every snapshot uses the same keys."""
        found = self._match(key, self._seats.keys())
        return found if found is not None else key

    # ------------------------------------------------------------- update
    def update(self, state: GameState, apply: bool = True) -> TrackInfo:
        """Feed every capture in order. With `apply`, missing values in `state` are filled in."""
        info = TrackInfo()
        seen: Dict[Key, Tuple[int, float]] = {}
        for i, p in enumerate(state.players):
            k = self._key(p)
            if k is not None and p.stack.known:
                seen[self._canon(k)] = (i, float(p.stack.value))
        current = dict(self._seats)
        current.update({k: v for k, (_, v) in seen.items()})
        pot = float(state.pot.value) if state.pot.known else None
        shown_bets = [float(p.bet.value) for p in state.players if p.bet.known and p.bet.value]
        board_len = len(state.board)

        found = self._find_start(current, pot, sum(shown_bets)) if pot is not None and HERO in seen else None
        if found is None:
            info.note = ("Watching for the start of a hand." if self._start_at is None
                         else "The chips that left the stacks don't add up to the pot.")
        else:
            at, contrib_by_seat, includes = found
            if at != self._start_at:
                info.new_hand = True
                self.hands_seen += 1
                self._start_at = at
                self._blinds = None
                self._levels = {}
            # nothing was captured between the start of the hand and this read
            fresh = at - self._dropped == len(self._history) - 1
            self._fill(info, state, seen, contrib_by_seat, includes, board_len, fresh)

        # remember these stacks: they may be where the next hand starts
        if seen:
            self._seats = current
            if not self._history or self._history[-1] != current:
                self._history.append(dict(current))
                if len(self._history) > HISTORY:
                    self._history.pop(0)
                    self._dropped += 1

        if apply and info.valid:
            self._apply(state, info)
        return info

    def _find_start(self, current: Dict[Key, float], pot: float, shown_bets: float):
        """The most recent snapshot from which the chips that left the stacks equal the
        pot: (its position, chips per seat, whether the pot includes this round's bets)."""
        targets = [(pot, True)] + ([(pot + shown_bets, False)] if shown_bets > 0 else [])
        for idx in range(len(self._history) - 1, -1, -1):
            found = self._adds_up(idx, current, targets)
            if found is None:
                continue
            contrib, includes = found
            if includes and shown_bets > 0 and self._start_at is not None and self._start_at - self._dropped != idx:
                # This adds up to the middle pot alone, with bets printed in front of the players.
                # If the start already found adds up to the pot plus those bets, keep it: a bet
                # the size of the pot makes a later set of stacks add up to the pot by chance.
                kept = self._adds_up(self._start_at - self._dropped, current, targets[1:])
                if kept is not None:
                    return self._start_at, kept[0], False
            return self._dropped + idx, contrib, includes
        return None

    def _adds_up(self, idx: int, current: Dict[Key, float], targets):
        """(chips per seat, whether the pot includes this round's bets) when the stacks that
        left since snapshot `idx` add up to one of the targets."""
        if not 0 <= idx < len(self._history):
            return None
        snap = self._history[idx]
        contrib: Dict[Key, float] = {}
        for k, now in current.items():
            if k not in snap:
                continue
            c = snap[k] - now
            if c < -0.5:
                return None  # a stack grew since then: a hand ended in between
            contrib[k] = max(0.0, c)
        if HERO not in contrib or len(contrib) < 2:
            return None
        total = sum(contrib.values())
        for target, includes in targets:
            if target > 0 and abs(total - target) <= max(1.0, 0.02 * target):
                return contrib, includes
        return None

    def _fill(self, info: TrackInfo, state: GameState, seen: Dict[Key, Tuple[int, float]],
              contrib_by_seat: Dict[Key, float], includes: bool, board_len: int, fresh: bool = True) -> None:
        index = {k: i for k, (i, _) in seen.items()}
        hero_c = contrib_by_seat.get(HERO, 0.0)
        top = max(contrib_by_seat.values())
        # the level everyone still in the hand had reached when this round began
        first_read = board_len not in self._levels
        self._levels[board_len] = max(self._levels.get(board_len, 0.0), top)
        earlier = [v for b, v in self._levels.items() if b < board_len]
        level = max(earlier, default=0.0)
        if board_len > 0 and first_read:
            # The first read of this round. Everyone still in had matched the level when it
            # began, so it is at least what the smallest of them has put in: the end of the last
            # round may not have been seen (missed pictures, or the pot wasn't shown before).
            seats = [(contrib_by_seat[k], state.players[i].in_hand) for k, (i, stack) in seen.items()
                     if k in contrib_by_seat and stack > 0]
            live = [c for c, f in seats if f.known and f.value]  # (you without cards: folded)
            if not live and not any(f.known for _, f in seats):
                live = [c for c, _ in seats]  # nothing says who is still in
            if live and (not earlier or min(live) > level):
                level = min(live)
                self._levels[board_len - 1] = max(self._levels.get(board_len - 1, 0.0), level)
        info.valid = True
        info.pot_includes_bets = includes
        info.contributions = {index[k]: c for k, c in contrib_by_seat.items() if k in index}
        info.street_bets = {index[k]: max(0.0, c - level) for k, c in contrib_by_seat.items() if k in index}
        info.hero_invested = hero_c
        to_call = max(0.0, max((c for k, c in contrib_by_seat.items() if k != HERO), default=0.0) - hero_c)
        hero_i = index.get(HERO)
        if hero_i is not None and state.players[hero_i].stack.known:
            to_call = min(to_call, float(state.players[hero_i].stack.value))
        info.to_call = to_call
        if board_len == 0 and self._blinds is None and fresh:
            # Only from the first capture of a hand: later the blinds may have raised, and a
            # raise to 6 and a re-raise to 18 would look like blinds of 6/18.
            seen_now = self._infer_blinds(state, info.contributions)
            if seen_now is None:
                pass
            elif self._table_blinds is None or seen_now == self._table_blinds or seen_now == self._new_blinds:
                self._table_blinds, self._new_blinds, self._blinds = seen_now, None, seen_now
            else:
                # different blinds from the last hands: believed once seen in two hands. Until
                # then the smaller ones count, which can never make you look short-stacked.
                self._new_blinds = seen_now
                self._blinds = min(seen_now, self._table_blinds, key=lambda b: b[1])
        blinds = self._blinds
        if blinds is None and self._table_blinds and self._fits(state, info.contributions, self._table_blinds):
            blinds = self._table_blinds  # blinds don't change from hand to hand at the same table
        info.blinds = blinds

    @staticmethod
    def _infer_blinds(state: GameState, contrib: Dict[int, float]) -> Optional[Tuple[float, float]]:
        """At the start of a hand the small and big blinds have put in exactly the blinds."""
        sb = bb = None
        for i, p in enumerate(state.players):
            if not p.position.known or i not in contrib:
                continue
            if p.position.value in ("SB", "BTN/SB"):
                sb = contrib[i]
            elif p.position.value == "BB":
                bb = contrib[i]
        if sb and bb and sb < bb <= 3 * sb:  # 1/2, 2/5, 1/3, 25/50 ...
            return (sb, bb)
        return None

    @staticmethod
    def _fits(state: GameState, contrib: Dict[int, float], blinds: Tuple[float, float]) -> bool:
        """The blinds of an earlier hand still fit this one: the players in the blinds have
        put in at least that much. A table with smaller blinds can't inherit bigger ones."""
        checked = False
        for i, p in enumerate(state.players):
            if not p.position.known or i not in contrib:
                continue
            need = blinds[0] if p.position.value in ("SB", "BTN/SB") else blinds[1] if p.position.value == "BB" else None
            if need is None:
                continue
            if contrib[i] + 1e-9 < need:
                return False
            checked = True
        return checked

    def _apply(self, state: GameState, info: TrackInfo) -> None:
        if info.pot_includes_bets:
            state.pot_includes_bets = True  # the pot on screen already holds every bet
        if not state.to_call.known and info.to_call is not None:
            state.to_call = Field.derived(info.to_call, CONFIDENCE)
        # each player's bet this round, worked out from the stacks where none is printed
        for i, c in info.street_bets.items():
            p = state.players[i]
            if not p.bet.known:
                p.bet = Field.derived(c, CONFIDENCE)
            elif p.bet.source == "auto" and float(p.bet.value) == 0.0 and c > 0 and p.bet.confidence < 0.8:
                # "no bet seen" only because the number was missed (a lone "6" is easy to miss):
                # the chips that left the stack say otherwise
                p.bet = Field.derived(c, CONFIDENCE)
        if info.blinds and (not state.blinds.known or (
                state.blinds.source == "auto" and tuple(float(v) for v in state.blinds.value[:2]) != info.blinds)):
            # the chips the blinds put in are the proof; a line of text that disagrees loses
            state.blinds = Field.derived(info.blinds, CONFIDENCE)
