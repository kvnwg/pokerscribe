"""How each opponent plays, learned while watching (watch mode only).

Every read of the table adds to simple counts per opponent, once per hand:

- hands: hands they were dealt into (seen with chips and cards, an action or a bet);
- VPIP: hands where they put chips in before the flop beyond their blind (call or raise);
- PFR: hands where they raised before the flop;
- after the flop: bets and raises against calls, and folds when facing a bet.

The chips come from the hand tracker (what left each stack, valid only when it adds up
to the pot) and the action labels the client shows ("Call", "Raise", "Fold"). A raise
is credited to the player whose chips first went above everyone else's; a player who
only matches that amount called.

From about 12 hands on, each opponent gets a style that the advice can use:

    station  plays a lot of hands and rarely raises: calls too much, rarely bluffs
    nit      plays very few hands: when they put chips in, they have something
    tag      a solid regular: plays a normal share of hands and raises most of them
    lag      plays many hands and raises a lot of them
    maniac   plays most hands and raises most of those

Players are told apart by the name on screen, or by their seat when no name was read.
Names and styles are for the screen and the advice only: they are never part of the
text sent to an AI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from app.state.model import GameState, Player

MIN_HANDS = 12  # fewer hands than this: no style yet
SEAT_TOLERANCE = 40.0  # px: a seat is drawn in the same place on every read
PRIOR_HANDS = 4.0  # small samples lean towards a typical player (25% played, 18% raised)
PRIOR_VPIP, PRIOR_PFR = 0.25, 0.18
EPS = 0.01

STYLES = ("station", "nit", "tag", "lag", "maniac")


@dataclass
class PlayerStats:
    hands: int = 0
    vpip: int = 0
    pfr: int = 0
    post_aggr: int = 0  # streets on which they bet or raised
    post_calls: int = 0  # streets on which they called a bet
    faced_bets: int = 0  # streets on which they had to answer a bet and we saw what they did
    folds_to_bet: int = 0

    @property
    def vpip_rate(self) -> float:
        return self.vpip / self.hands if self.hands else 0.0

    @property
    def pfr_rate(self) -> float:
        return self.pfr / self.hands if self.hands else 0.0

    @property
    def aggression(self) -> Optional[float]:
        """Share of their after-the-flop actions (bets, raises, calls) that were bets or raises."""
        n = self.post_aggr + self.post_calls
        return self.post_aggr / n if n else None

    @property
    def fold_to_bet(self) -> Optional[float]:
        return self.folds_to_bet / self.faced_bets if self.faced_bets else None

    def added(self, other: "PlayerStats") -> "PlayerStats":
        return PlayerStats(self.hands + other.hands, self.vpip + other.vpip, self.pfr + other.pfr,
                           self.post_aggr + other.post_aggr, self.post_calls + other.post_calls,
                           self.faced_bets + other.faced_bets, self.folds_to_bet + other.folds_to_bet)


@dataclass
class _HandFlags:
    """What one player did in the hand being played (each counted once per hand)."""
    dealt: bool = False
    vpip: bool = False
    pfr: bool = False
    aggr_streets: Set[int] = field(default_factory=set)
    call_streets: Set[int] = field(default_factory=set)
    faced_streets: Set[int] = field(default_factory=set)
    folded_to_bet: bool = False
    folded: bool = False

    def as_stats(self) -> PlayerStats:
        if not self.dealt:
            return PlayerStats()
        return PlayerStats(1, int(self.vpip), int(self.pfr), len(self.aggr_streets),
                           len(self.call_streets - self.aggr_streets), len(self.faced_streets),
                           int(self.folded_to_bet))


def classify(stats: PlayerStats) -> Optional[str]:
    """One of STYLES, or None below MIN_HANDS hands."""
    if stats.hands < MIN_HANDS:
        return None
    n = stats.hands + PRIOR_HANDS
    vpip = (stats.vpip + PRIOR_VPIP * PRIOR_HANDS) / n
    pfr = (stats.pfr + PRIOR_PFR * PRIOR_HANDS) / n
    if vpip >= 0.50 and pfr >= 0.30:
        return "maniac"
    if vpip >= 0.28 and pfr >= 0.20:
        return "lag"
    if vpip >= 0.35 and pfr <= 0.12:
        return "station"
    if vpip <= 0.15:
        return "nit"
    if vpip < 0.28:
        return "tag"
    # loose, raising somewhere between the two: whichever it raises more like
    return "lag" if pfr >= 0.5 * vpip else "station"


def describe(stats: PlayerStats) -> str:
    """Short wording for the screen, e.g. "plays 48% of hands, raises 6%"."""
    if not stats.hands:
        return ""
    text = f"plays {round(100 * stats.vpip_rate)}% of hands, raises {round(100 * stats.pfr_rate)}%"
    aggr = stats.aggression
    if aggr is not None and stats.post_aggr + stats.post_calls >= 8:
        text += f", bets or raises {round(100 * aggr)}% of the time after the flop"
    return text


def _name_key(name: str) -> Optional[str]:
    norm = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return f"name:{norm}" if len(norm) >= 2 else None


class Profiles:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._totals: Dict[str, PlayerStats] = {}
        self._hand: Optional[int] = None
        self._flags: Dict[str, _HandFlags] = {}
        self._seats: List[Tuple[float, float]] = []  # seats seen, as first seen
        self._names: Dict[Tuple[float, float], str] = {}  # seat -> the name last read there
        self._top: Dict[int, float] = {}  # per street: most chips anyone had put in that street so far

    # ------------------------------------------------------------ public
    def key_for(self, p: Player) -> Optional[str]:
        """Who this is: the name on screen, else the name last read at that seat, else the seat."""
        if p.is_hero:
            return None
        seat = self._seat(p.anchor) if p.anchor else None
        key = _name_key(p.name)
        if key is not None:
            if seat is not None:
                self._names[seat] = key
            return key
        if seat is None:
            return None
        return self._names.get(seat, f"seat:{seat[0]:.0f},{seat[1]:.0f}")

    def update(self, state: GameState, info=None, hand_number: Optional[int] = None) -> None:
        """Feed one read (after the tracker and the hand memory have seen it). `info` is the
        tracker's TrackInfo for this read; `hand_number` the hand memory's count."""
        if hand_number is not None and hand_number != self._hand:
            self._flush()
            self._hand = hand_number
        street = len(state.board)
        valid = bool(info is not None and getattr(info, "valid", False))
        contrib: Dict[int, float] = dict(getattr(info, "contributions", {}) or {}) if valid else {}
        street_bets: Dict[int, float] = dict(getattr(info, "street_bets", {}) or {}) if valid else {}
        sb, bb = self._blinds(state, info)

        # Who put chips above everyone else this street on this read: that's a bet or a
        # raise. Someone who only matches the most put in called.
        amounts = contrib if street == 0 else street_bets
        floor = (bb or 0.0) if street == 0 else 0.0
        top_before = self._top.get(street, floor)
        raiser = None
        if amounts and (street > 0 or bb):
            above = {i: v for i, v in amounts.items() if v > top_before + EPS}
            if above:
                best = max(above.values())
                leaders = [i for i, v in above.items() if abs(v - best) <= EPS]
                if len(leaders) == 1:
                    raiser = leaders[0]
                self._top[street] = best
        facing_bet = self._top.get(street, floor) > floor + EPS

        for i, p in enumerate(state.players):
            key = self.key_for(p)
            if key is None:
                continue
            f = self._flags.setdefault(key, _HandFlags())
            act = p.last_action.value.kind if p.last_action.known else None
            c = contrib.get(i)
            has_hand = (p.in_hand.known and p.in_hand.value) or act is not None or (c is not None and c > EPS)
            if has_hand and (p.stack.known or c is not None):
                f.dealt = True
            if f.folded:
                continue  # a label left over from when they folded: nothing new
            if street == 0:
                self._preflop(f, p, act, c, sb, bb, raiser == i)
            else:
                self._postflop(f, act, street_bets.get(i), street, raiser == i, facing_bet)
            if act == "fold":
                f.folded = True

    def stats_for(self, key: Optional[str]) -> PlayerStats:
        """Counts for this player, the hand in progress included."""
        if key is None:
            return PlayerStats()
        total = self._totals.get(key, PlayerStats())
        cur = self._flags.get(key)
        return total.added(cur.as_stats()) if cur is not None else total

    def style_for(self, key: Optional[str]) -> Optional[str]:
        return classify(self.stats_for(key))

    def label_for(self, key: Optional[str]) -> str:
        return describe(self.stats_for(key))

    def annotate(self, state: GameState) -> None:
        """Put each opponent's style and wording on the state (fields for the screen and the
        advice only)."""
        for p in state.opponents:
            stats = self.stats_for(self.key_for(p))
            p.style = classify(stats)
            p.style_note = describe(stats) if p.style else ""

    # ----------------------------------------------------------- private
    @staticmethod
    def _preflop(f: _HandFlags, p: Player, act, c, sb, bb, raised_here: bool) -> None:
        if c is not None:
            pos = p.position.value if p.position.known else None
            if pos in ("SB", "BTN/SB"):
                forced = sb
            elif pos == "BB":
                forced = bb
            elif pos is not None:
                forced = 0.0
            else:
                forced = bb  # seat unknown: only chips above a big blind are surely by choice
            if forced is not None and c > forced + EPS:
                f.vpip = True
        if act in ("call", "raise", "bet", "all-in"):
            f.vpip = True
        if act in ("raise", "bet") or (act == "all-in" and bb and c is not None and c > bb + EPS):
            f.pfr = True
        if raised_here:
            f.pfr = f.vpip = True

    @staticmethod
    def _postflop(f: _HandFlags, act, street_bet, street: int, raised_here: bool, facing_bet: bool) -> None:
        if act in ("bet", "raise", "all-in") or raised_here:
            f.aggr_streets.add(street)
            if facing_bet and act == "raise":
                f.faced_streets.add(street)
        elif act == "call" or (street_bet is not None and street_bet > EPS and facing_bet
                               and street not in f.aggr_streets):
            f.call_streets.add(street)
            f.faced_streets.add(street)
        elif act == "fold" and facing_bet:
            f.faced_streets.add(street)
            f.folded_to_bet = True

    def _flush(self) -> None:
        for key, f in self._flags.items():
            if f.dealt:
                self._totals[key] = self._totals.get(key, PlayerStats()).added(f.as_stats())
        self._flags = {}
        self._top = {}

    def _seat(self, anchor) -> Tuple[float, float]:
        x, y = float(anchor[0]), float(anchor[1])
        for k in self._seats:
            if abs(k[0] - x) + abs(k[1] - y) <= SEAT_TOLERANCE:
                return k
        self._seats.append((x, y))
        return (x, y)

    @staticmethod
    def _blinds(state: GameState, info) -> Tuple[Optional[float], Optional[float]]:
        b = None
        if state.blinds.known and state.blinds.value:
            b = state.blinds.value
        elif info is not None and getattr(info, "blinds", None):
            b = info.blinds
        try:
            return (float(b[0]), float(b[1])) if b else (None, None)
        except (TypeError, ValueError, IndexError):
            return None, None
