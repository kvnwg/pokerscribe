"""A poker move as a plan: which button, and the amount typed first for a bet or raise.

It does what the move says and nothing else: no move is changed into another, and a plan
that can't be made (no such button, no way to set the amount) is refused with PlanError.
The move comes from the caller (the self-test's hero_move, say); nothing here decides one.
Target names: "fold", "check", "call", "bet", "raise", "all-in" and "amount" (the box where
a bet's size is typed).
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from .intents import Click, Expect, Plan, Step, Target, TypeText


class PlanError(ValueError):
    pass


def _money(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def plan_for_move(kind: str, amount: Optional[float], targets: Mapping[str, Target],
                  expect: Optional[Expect] = None, require: Optional[Expect] = None,
                  money: Callable[[float], str] = _money, label: str = "") -> Plan:
    """`kind` is fold, check, call, bet or raise; `amount` is what a bet or raise goes to.
    `expect` is checked after the last step (your turn is over, say), `require` before the first."""
    kind = kind.lower()
    label = label or (f"{kind} {money(amount)}" if amount is not None and kind in ("bet", "raise") else kind)
    if kind in ("fold", "check"):
        if kind not in targets:
            raise PlanError(f"no {kind} button")
        return Plan([Step(Click(kind), expect)], label, require)
    if kind == "call":
        # a call for all your chips can be the "All in" button
        name = "call" if "call" in targets else "all-in" if "all-in" in targets else None
        if name is None:
            raise PlanError("no call button")
        return Plan([Step(Click(name), expect)], label, require)
    if kind in ("bet", "raise"):
        if amount is None:
            raise PlanError(f"a {kind} needs an amount")
        name = kind if kind in targets else ({"bet": "raise", "raise": "bet"}[kind])
        if name not in targets:
            raise PlanError(f"no {kind} button")
        if "amount" in targets:
            return Plan([Step(TypeText("amount", money(amount))), Step(Click(name), expect)], label, require)
        shown = _amount_on(targets[name])
        if shown is not None and abs(shown - amount) <= 1e-6 * max(1.0, abs(amount)):
            return Plan([Step(Click(name), expect)], label, require)  # the button already says that amount
        raise PlanError(f"no amount box, and the {name} button says {targets[name].label or 'no amount'}")
    raise PlanError(f"not a move: {kind}")


def _amount_on(target: Target) -> Optional[float]:
    import re

    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*$", target.label.replace("$", "").strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None
