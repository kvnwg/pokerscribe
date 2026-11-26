"""The internal game-state model. Every value carries a confidence and a source.

A Field whose value is None is UNKNOWN. A low-confidence detection keeps its best
guess in `guess` for the correction UI, but the guess never reaches the text
output or the AI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA = "pokerscribe.state/1"
STREETS = ["preflop", "flop", "turn", "river"]
ACTION_KINDS = ["fold", "check", "call", "bet", "raise", "all-in"]
CARD_RE = re.compile(r"^[2-9TJQKA][shdc]$")


@dataclass
class Action:
    kind: str
    amount: Optional[float] = None

    def __post_init__(self):
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"Unknown action: {self.kind}")
        if self.amount is not None:
            self.amount = float(self.amount)

    def describe(self) -> str:
        from .text_format import fmt_amount

        name = {"fold": "Fold", "check": "Check", "call": "Call", "bet": "Bet", "raise": "Raise", "all-in": "All-in"}[self.kind]
        if self.amount is None or self.kind in ("fold", "check"):
            return name
        if self.kind == "raise":
            return f"Raise to {fmt_amount(self.amount)}"
        return f"{name} {fmt_amount(self.amount)}"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "amount": self.amount}

    @staticmethod
    def from_dict(d: dict) -> "Action":
        return Action(d["kind"], d.get("amount"))

    _WORDS = [
        (re.compile(r"^\s*(all[\s-]?in|allin|shove)(?![a-z])", re.I), "all-in"),
        (re.compile(r"^\s*folds?(?![a-z])", re.I), "fold"),
        (re.compile(r"^\s*checks?(?![a-z])", re.I), "check"),
        (re.compile(r"^\s*calls?(?![a-z])", re.I), "call"),
        (re.compile(r"^\s*bets?(?![a-z])", re.I), "bet"),
        (re.compile(r"^\s*raises?(?:\s*to)?(?![a-z])", re.I), "raise"),
    ]

    @staticmethod
    def parse(text: str) -> Optional["Action"]:
        """'Call 60', 'Raise to 240', 'Bet 1.5K', 'All-in 950', 'Check', 'Fold', 'Call60'."""
        from app.recognition.amounts import first_amount

        t = text.strip()
        t = re.sub(r"(?i)^(calls?|bets?|raises?|raise\s*to|all[\s-]?in|allin)(?=[\d$€£])", r"\1 ", t)
        for pattern, kind in Action._WORDS:
            m = pattern.match(t)
            if m:
                amt = first_amount(t[m.end():])
                return Action(kind, amt.value if amt else None)
        return None

    @staticmethod
    def parse_list(text: str) -> List["Action"]:
        """Comma separated: 'Fold, Call 60, Raise to 240'."""
        out = []
        for part in re.split(r"[,;]", text):
            if part.strip():
                a = Action.parse(part)
                if a is None:
                    raise ValueError(f"Not an action: {part.strip()}")
                out.append(a)
        return out


def _encode(v: Any) -> Any:
    if isinstance(v, Action):
        return v.to_dict()
    if isinstance(v, (list, tuple)):
        return [_encode(x) for x in v]
    return v


@dataclass
class Field:
    value: Any = None
    confidence: float = 0.0
    source: str = "none"  # auto | manual | derived | none
    guess: Any = None  # low-confidence best guess, UI only

    @property
    def known(self) -> bool:
        return self.value is not None

    @staticmethod
    def manual(value: Any) -> "Field":
        return Field(value, 1.0, "manual") if value is not None else Field(None, 1.0, "manual")

    @staticmethod
    def auto(value: Any, confidence: float, threshold: float) -> "Field":
        confidence = round(float(max(0.0, min(1.0, confidence))), 3)
        if value is None:
            return Field(None, confidence, "auto")
        if confidence >= threshold:
            return Field(value, confidence, "auto")
        return Field(None, confidence, "auto", guess=value)

    @staticmethod
    def derived(value: Any, confidence: float) -> "Field":
        return Field(value, round(float(confidence), 3), "derived")

    def to_dict(self) -> dict:
        d = {"value": _encode(self.value), "confidence": self.confidence, "source": self.source}
        if self.guess is not None:
            d["guess"] = _encode(self.guess)
        return d

    @staticmethod
    def from_dict(d: Optional[dict], kind: str = "plain") -> "Field":
        if not d:
            return Field()

        def dec(v):
            if v is None:
                return None
            if kind == "action":
                return Action.from_dict(v)
            if kind == "actions":
                return [Action.from_dict(x) for x in v]
            if kind == "pair":
                return tuple(v)
            return v

        return Field(dec(d.get("value")), float(d.get("confidence", 0.0)), d.get("source", "none"), dec(d.get("guess")))


def _f() -> Field:
    return Field()


@dataclass
class Player:
    seat: int  # 0 = hero's seat, then clockwise
    is_hero: bool = False
    position: Field = field(default_factory=_f)  # code, e.g. "BTN"
    stack: Field = field(default_factory=_f)
    bet: Field = field(default_factory=_f)  # chips in front of the player this street
    last_action: Field = field(default_factory=_f)  # Action
    in_hand: Field = field(default_factory=_f)  # bool
    # UI only, never exported to text:
    name: str = ""
    anchor: Optional[tuple] = None
    style: Optional[str] = None  # how they play, learned while watching: station, nit, tag, lag, maniac
    style_note: str = ""  # e.g. "plays 48% of hands, raises 6%"

    def to_dict(self) -> dict:
        return {
            "seat": self.seat,
            "is_hero": self.is_hero,
            "position": self.position.to_dict(),
            "stack": self.stack.to_dict(),
            "bet": self.bet.to_dict(),
            "last_action": self.last_action.to_dict(),
            "in_hand": self.in_hand.to_dict(),
            "ui": {"name": self.name, "anchor": list(self.anchor) if self.anchor else None,
                   "style": self.style, "style_note": self.style_note},
        }

    @staticmethod
    def from_dict(d: dict) -> "Player":
        ui = d.get("ui") or {}
        return Player(
            seat=int(d.get("seat", 0)),
            is_hero=bool(d.get("is_hero", False)),
            position=Field.from_dict(d.get("position")),
            stack=Field.from_dict(d.get("stack")),
            bet=Field.from_dict(d.get("bet")),
            last_action=Field.from_dict(d.get("last_action"), "action"),
            in_hand=Field.from_dict(d.get("in_hand")),
            name=ui.get("name") or "",
            anchor=tuple(ui["anchor"]) if ui.get("anchor") else None,
            style=ui.get("style") or None,
            style_note=ui.get("style_note") or "",
        )


@dataclass
class GameState:
    game: str = "Texas Hold'em"
    street: Field = field(default_factory=_f)
    hero_cards: List[Field] = field(default_factory=lambda: [Field(), Field()])
    board: List[Field] = field(default_factory=list)
    pot: Field = field(default_factory=_f)
    pot_includes_bets: bool = False
    blinds: Field = field(default_factory=_f)  # (small blind, big blind)
    players: List[Player] = field(default_factory=list)
    hero_to_act: Field = field(default_factory=_f)  # bool
    available_actions: Field = field(default_factory=_f)  # list of Action
    to_call: Field = field(default_factory=_f)
    computed: Dict[str, Any] = field(default_factory=dict)  # local maths, filled later

    # ------------------------------------------------------------ helpers
    @property
    def hero(self) -> Optional[Player]:
        for p in self.players:
            if p.is_hero:
                return p
        return None

    @property
    def opponents(self) -> List[Player]:
        return [p for p in self.players if not p.is_hero]

    def active_players(self) -> Field:
        """Players still in the hand, hero included."""
        flags = [p.in_hand for p in self.players]
        if not flags or any(not f.known for f in flags):
            return Field(None, 0.0, "derived")
        conf = min(f.confidence for f in flags)
        return Field.derived(sum(1 for f in flags if f.value), conf)

    def street_from_board(self) -> Optional[str]:
        return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(self.board))

    # ---------------------------------------------------------------- JSON
    def to_json(self) -> dict:
        return {
            "schema": SCHEMA,
            "game": self.game,
            "street": self.street.to_dict(),
            "hero_cards": [c.to_dict() for c in self.hero_cards],
            "board": [c.to_dict() for c in self.board],
            "pot": self.pot.to_dict(),
            "pot_includes_bets": self.pot_includes_bets,
            "blinds": self.blinds.to_dict(),
            "players": [p.to_dict() for p in self.players],
            "hero_to_act": self.hero_to_act.to_dict(),
            "available_actions": self.available_actions.to_dict(),
            "to_call": self.to_call.to_dict(),
            "computed": self.computed,
        }

    @staticmethod
    def from_json(d: dict) -> "GameState":
        if d.get("schema") != SCHEMA:
            raise ValueError("Not a PokerScribe game state.")
        return GameState(
            game=d.get("game", "Texas Hold'em"),
            street=Field.from_dict(d.get("street")),
            hero_cards=[Field.from_dict(c) for c in d.get("hero_cards", [])] or [Field(), Field()],
            board=[Field.from_dict(c) for c in d.get("board", [])],
            pot=Field.from_dict(d.get("pot")),
            pot_includes_bets=bool(d.get("pot_includes_bets", False)),
            blinds=Field.from_dict(d.get("blinds"), "pair"),
            players=[Player.from_dict(p) for p in d.get("players", [])],
            hero_to_act=Field.from_dict(d.get("hero_to_act")),
            available_actions=Field.from_dict(d.get("available_actions"), "actions"),
            to_call=Field.from_dict(d.get("to_call")),
            computed=d.get("computed") or {},
        )

    def validate(self) -> List[str]:
        """Problems that would make the description inconsistent."""
        problems = []
        cards = [c.value for c in self.hero_cards + self.board if c.known]
        for c in cards:
            if not CARD_RE.match(str(c)):
                problems.append(f"Invalid card code: {c}")
        dupes = {c for c in cards if cards.count(c) > 1}
        if dupes:
            problems.append("The same card appears twice: " + ", ".join(sorted(dupes)))
        if len(self.board) not in (0, 1, 2, 3, 4, 5):
            problems.append("The board can hold at most 5 cards.")
        if self.street.known and self.street.value not in STREETS:
            problems.append(f"Unknown street: {self.street.value}")
        if self.street.known and self.street_from_board() and self.street.value != self.street_from_board():
            problems.append(f"Street {self.street.value} does not match {len(self.board)} board cards.")
        for f, name in ((self.pot, "Pot"), (self.to_call, "To call")):
            if f.known and float(f.value) < 0:
                problems.append(f"{name} cannot be negative.")
        for p in self.players:
            for f, name in ((p.stack, "stack"), (p.bet, "bet")):
                if f.known and float(f.value) < 0:
                    problems.append(f"A {name} cannot be negative.")
        return problems
