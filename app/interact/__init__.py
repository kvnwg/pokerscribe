"""Interaction with our own programs: the simulator, the demo table and PokerScribe's own windows.

A caller describes what to do as a Plan (click a named target, type into it, press a key, and
what should be on screen afterwards). A Runner carries plans out on its own thread, one at a
time, through a Backend, and checks each step: the target is there and enabled before it acts,
the expected state shows afterwards. Clicking and typing can be switched off separately, a dry
run logs what would be done without doing it, and stop() halts everything at once.

Every backend acts inside our own process: the simulator's game, the demo table's picture or a
Qt widget tree (through QtTest, which sends events to the widget, not to the computer's pointer).
There is no backend for the system pointer or keyboard, and none is to be added: rule 4 in
docs/research/README.md (no automated play on live sites). app/tests/test_interact.py checks
that this package imports nothing that could drive the system pointer or keyboard, and that the
poker engine and the reader don't import it. See docs/research/INTERACT.md.
"""
from .backend import Backend, BackendError
from .intents import Click, Expect, Intent, Plan, PressKey, Step, Target, TypeText
from .moves import PlanError, plan_for_move
from .runner import Outcome, Runner, Settings, StepResult

__all__ = [
    "Backend", "BackendError", "Click", "Expect", "Intent", "Outcome", "Plan", "PlanError", "PressKey", "Runner",
    "Settings", "Step", "StepResult", "Target", "TypeText", "plan_for_move",
]
