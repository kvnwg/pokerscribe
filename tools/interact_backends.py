"""Backends for app/interact on our own game: the simulator, and the demo table's picture.

SimBackend: the hero's buttons as the self-test's table shows them, and an amount box. A click
makes the move in the simulator's game (tools/simulate.py act), exactly as the self-test does
when it plays the instruction itself, so a self-test run plays the same with or without it
(tools/selftest.py --interact).

DemoTableBackend: the targets are the buttons the reader finds in the demo table's picture
(app/tests/demo_table.py), so it checks that the buttons are found where they were drawn, at
any picture size. A click is checked against where each button was really drawn; the button it
lands on is the move made. Afterwards the table is drawn and read again: the buttons are gone
once your turn is over.

Both act only on our own game in this process. Nothing here touches a real poker client.
"""
from __future__ import annotations

import tempfile
from typing import Dict, List, Optional, Tuple

from app.interact.backend import Backend, BackendError
from app.interact.intents import Expect, Target
from app.state.model import Action
from tools.simulate import BB, Hand, act


def _money(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


class SimBackend(Backend):
    name = "simulator"
    keyboard = True  # the amount box

    def __init__(self, hero: int = 0):
        super().__init__()
        self.hero = hero
        self.hand: Optional[Hand] = None
        self._open = False
        self._typed: Optional[str] = None
        self.moves = 0

    def open_turn(self, h: Hand) -> None:
        """It's the hero's turn in `h`: the buttons show."""
        self.hand, self._open, self._typed = h, True, None

    def buttons(self) -> List[Tuple[str, str]]:
        """(name, label) of the buttons on screen, left to right."""
        h = self.hand
        if h is None or not self._open:
            return []
        s = h.seats[self.hero]
        to_call = h.current - s.bet
        total = s.stack + s.bet
        if to_call > 0:
            if to_call >= s.stack:
                return [("fold", "Fold"), ("all-in", f"All in {_money(s.stack)}")]
            return [("fold", "Fold"), ("call", f"Call {_money(to_call)}"),
                    ("raise", f"Raise to {_money(min(total, h.current + h.min_raise))}")]
        if s.stack <= 0:
            return [("check", "Check")]
        if h.current > 0:
            return [("check", "Check"), ("raise", f"Raise to {_money(min(total, h.current + h.min_raise))}")]
        return [("check", "Check"), ("bet", f"Bet {_money(min(total, BB))}")]

    def targets(self) -> Dict[str, Target]:
        out = {name: Target(name, (110.0 * k, 0.0, 100.0, 40.0), label) for k, (name, label) in enumerate(self.buttons())}
        if any(n in out for n in ("bet", "raise")):
            out["amount"] = Target("amount", (0.0, -60.0, 140.0, 40.0), self._typed or "")
        return out

    def click(self, target: Target, point: Tuple[float, float]) -> None:
        h = self.hand
        if h is None or not self._open:
            raise BackendError("it isn't your turn")
        hit = [t for t in self.targets().values() if t.contains(*point)]
        if not hit:
            raise BackendError(f"the click at {point} hit nothing")
        name = hit[0].name
        if name != target.name:
            raise BackendError(f"the click landed on {name}, not {target.name}")
        if name == "amount":
            return  # clicking the box only gives it the focus
        if name in ("bet", "raise"):
            s = h.seats[self.hero]
            to = float(self._typed) if self._typed else min(s.stack + s.bet, h.current + h.min_raise)
            act(h, self.hero, "raise", to)
        elif name == "all-in":
            act(h, self.hero, "call", 0.0)  # the button for calling with every chip
        else:
            act(h, self.hero, name, 0.0)
        self._open, self._typed = False, None
        self.moves += 1

    def type_text(self, target: Target, text: str, clear: bool) -> None:
        if target.name != "amount":
            raise BackendError(f"{target.name} takes no typing")
        new = text if clear or not self._typed else self._typed + text
        try:
            float(new)
        except ValueError:
            raise BackendError(f"{new!r} is not an amount") from None
        self._typed = new

    def press_key(self, key: str, target: Optional[Target]) -> None:
        raise BackendError("the simulator takes no keys")

    def snapshot(self) -> dict:
        return {"your_turn": self._open, "moves": self.moves, "typed": self._typed}


TURN_OVER = Expect("your turn is over", lambda snap: not snap["your_turn"])


class DemoTableBackend(Backend):
    """Reading a picture takes a second or two: give the runner a call_timeout to match."""

    name = "demo-table"

    def __init__(self, lay, recognizer=None):
        super().__init__()
        self.lay = lay
        if recognizer is None:
            from app.recognition.recognizer import TableRecognizer
            from app.vision.card_recognizer import CardRecognizer
            from app.vision.ocr import FallbackOcr

            recognizer = TableRecognizer(CardRecognizer(tempfile.mkdtemp(prefix="interact-cards-"), 0.70),
                                         FallbackOcr("auto"), 0.70)
        self.reader = recognizer
        self.hand: Optional[Hand] = None
        self.hand_no = 0
        self.img = None
        self.meta: dict = {}
        self.read = None
        self.clicks: List[Tuple[float, float]] = []  # where every click landed, in picture pixels
        self.moves: List[Tuple[str, float]] = []
        self._stale = False  # a move was made since the picture was drawn

    def open_turn(self, h: Hand, hand_no: int = 1, img=None, meta=None, read=None) -> None:
        """Your turn in `h`. The caller can hand over the picture it drew and read already."""
        self.hand, self.hand_no, self._stale = h, hand_no, False
        if img is None:
            self._draw(0)
        else:
            self.img, self.meta, self.read = img, meta, read

    def _draw(self, acting: Optional[int]) -> None:
        from app.tests.demo_table import render
        from tools.selftest import view_of

        view = view_of(self.hand, acting, self.hand_no, self.lay)
        self.img, self.meta = render(view, self.lay)
        self.read = self.reader.recognize(self.img)

    def targets(self) -> Dict[str, Target]:
        if self._stale:
            self._draw(None)  # your move is made: the table is drawn and read again
            self._stale = False
        out: Dict[str, Target] = {}
        if self.read is None:
            return out
        for b in getattr(self.read.layout, "action_boxes", None) or []:
            a = Action.parse(b.text)
            if a is not None and a.kind not in out:
                out[a.kind] = Target(a.kind, (float(b.x), float(b.y), float(b.w), float(b.h)), b.text)
        return out

    def click(self, target: Target, point: Tuple[float, float]) -> None:
        if self.hand is None:
            raise BackendError("no table")
        self.clicks.append(point)
        hit = [label for label, (x, y, w, h) in self.meta.get("buttons", [])
               if x <= point[0] <= x + w and y <= point[1] <= y + h]
        if not hit:
            raise BackendError(f"the click at ({point[0]:.0f}, {point[1]:.0f}) hit no button")
        drawn = Action.parse(hit[0])
        if drawn is None or drawn.kind != target.name:
            raise BackendError(f"the click landed on {hit[0]!r}, not {target.name}")
        h = self.hand
        s = h.seats[0]
        if drawn.kind in ("bet", "raise"):
            to = drawn.amount / self.lay.unit if drawn.amount is not None else \
                min(s.stack + s.bet, h.current + h.min_raise)
            act(h, 0, "raise", to)
            self.moves.append(("raise", to))
        elif drawn.kind == "all-in":
            act(h, 0, "call", 0.0)
            self.moves.append(("call", 0.0))
        else:
            act(h, 0, drawn.kind, 0.0)
            self.moves.append((drawn.kind, 0.0))
        self._stale = True

    def snapshot(self) -> dict:
        return {"buttons": sorted(self.targets()), "your_turn": bool(self.read and self.read.state.hero_to_act.known
                                                                     and self.read.state.hero_to_act.value)}


BUTTONS_GONE = Expect("the buttons are gone", lambda snap: not snap["buttons"])
