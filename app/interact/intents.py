"""What to do, in terms a backend understands: named targets, and steps on them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple, Union

Box = Tuple[float, float, float, float]  # x, y, width, height in the backend's own coordinates


@dataclass(frozen=True)
class Target:
    """Something on screen that can be clicked or typed into: a button, an amount box."""
    name: str  # what plans call it: "fold", "call", "raise", "amount", a widget's object name
    box: Box
    label: str = ""  # the text it shows ("Call 40")
    enabled: bool = True
    visible: bool = True

    @property
    def center(self) -> Tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2

    def contains(self, x: float, y: float) -> bool:
        bx, by, bw, bh = self.box
        return bx <= x <= bx + bw and by <= y <= by + bh


@dataclass(frozen=True)
class Click:
    target: str


@dataclass(frozen=True)
class TypeText:
    target: str
    text: str
    clear: bool = True  # replace what the box holds


@dataclass(frozen=True)
class PressKey:
    key: str  # "Enter", "Escape", "Tab", "Space", "Backspace", "Up", "F1", or one character
    target: Optional[str] = None  # the widget to send it to (None: the one with the focus)


Intent = Union[Click, TypeText, PressKey]


@dataclass(frozen=True)
class Expect:
    """A state the backend should show: `check` is given backend.snapshot()."""
    description: str
    check: Callable[[Any], bool]


@dataclass(frozen=True)
class Step:
    intent: Intent
    expect: Optional[Expect] = None  # checked after the step; None: nothing to wait for


@dataclass
class Plan:
    steps: List[Step]
    label: str = ""
    require: Optional[Expect] = None  # must hold before the first step, or nothing is done
    meta: dict = field(default_factory=dict)  # the caller's own notes, copied to the log


def describe(intent: Intent) -> str:
    if isinstance(intent, Click):
        return f"click {intent.target}"
    if isinstance(intent, TypeText):
        return f"type {intent.text!r} into {intent.target}"
    return f"press {intent.key}" + (f" in {intent.target}" if intent.target else "")
