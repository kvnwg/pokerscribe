"""app/interact: the runner (order, dry run, switches, checks, stop, timeouts, log), moves as
plans, the simulator backend, and what the package may import."""
import ast
import copy
import json
import os
import threading
import time

import pytest

from app.interact import (Backend, BackendError, Click, Expect, Plan, PlanError, PressKey, Runner, Settings, Step,
                          Target, TypeText, plan_for_move)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Fake(Backend):
    """Buttons in a row; a click records itself and can be slow, hang or fail."""

    name = "fake"
    keyboard = True

    def __init__(self, names=("fold", "call", "raise", "amount"), delay=0.0):
        super().__init__()
        self.shown = {n: Target(n, (100.0 * k, 0.0, 80.0, 30.0), n.title()) for k, n in enumerate(names)}
        self.delay = delay
        self.clicks, self.typed, self.keys = [], [], []
        self.threads = set()
        self.state = {"moves": 0}
        self.hang = None  # an Event a click waits for
        self.fail = None  # the message a click fails with

    def targets(self):
        self.threads.add(threading.current_thread().name)
        return dict(self.shown)

    def click(self, target, point):
        if self.hang is not None:
            self.hang.wait(5)
        if self.fail:
            raise BackendError(self.fail)
        time.sleep(self.delay)
        assert target.contains(*point)
        self.clicks.append(target.name)
        self.state["moves"] += 1

    def type_text(self, target, text, clear):
        self.typed.append((target.name, text))

    def press_key(self, key, target):
        self.keys.append((key, target.name if target else None))

    def snapshot(self):
        return dict(self.state)


def moved(n):
    return Expect(f"{n} moves made", lambda snap: snap["moves"] >= n)


def test_plans_run_in_order_on_the_runners_thread_and_submit_does_not_wait():
    fake = Fake(delay=0.15)
    r = Runner(fake)
    try:
        t0 = time.monotonic()
        futs = [r.submit(Plan([Step(Click(n))], n)) for n in ("call", "fold", "raise")]
        assert time.monotonic() - t0 < 0.1  # the caller isn't held up by the backend
        outs = [f.result(5) for f in futs]
        assert [o.status for o in outs] == ["done"] * 3
        assert fake.clicks == ["call", "fold", "raise"]
        assert threading.current_thread().name not in fake.threads
        assert all(o.steps[0].point == fake.shown[o.label].center for o in outs)  # the middle of the button
    finally:
        r.close()


def test_a_dry_run_checks_every_target_and_does_nothing():
    fake = Fake()
    r = Runner(fake, Settings(dry_run=True))
    try:
        out = r.run(Plan([Step(TypeText("amount", "40")), Step(Click("raise"), moved(1))]))
        assert out.status == "dry-run" and out.ok
        assert [s.status for s in out.steps] == ["dry-run", "dry-run"]
        assert fake.clicks == [] and fake.typed == []
        bad = r.run(Plan([Step(Click("check"))]))  # a dry run still finds a missing button
        assert bad.status == "failed" and "check is not on screen" in bad.reason
    finally:
        r.close()


def test_clicking_or_keys_switched_off_skips_the_whole_plan():
    fake = Fake()
    r = Runner(fake, Settings(clicks=False))
    try:
        out = r.run(Plan([Step(TypeText("amount", "40")), Step(Click("raise"))]))
        assert out.status == "skipped" and "clicking is switched off" in out.reason
        assert fake.typed == [] and fake.clicks == []  # no half plan: the amount isn't typed either
        assert r.run(Plan([Step(PressKey("Enter"))])).status == "done"  # keys are still on
    finally:
        r.close()
    r = Runner(fake, Settings(keys=False))
    try:
        assert r.run(Plan([Step(TypeText("amount", "40")), Step(Click("raise"))])).status == "skipped"
        assert r.run(Plan([Step(Click("call"))])).status == "done"
    finally:
        r.close()


def test_a_missing_hidden_or_switched_off_target_fails_before_anything_is_done():
    fake = Fake()
    fake.shown["raise"] = Target("raise", (0, 0, 10, 10), "Raise", enabled=False)
    fake.shown["fold"] = Target("fold", (0, 0, 10, 10), "Fold", visible=False)
    r = Runner(fake)
    try:
        for name, why in (("check", "check is not on screen (on screen: amount, call, fold, raise)"),
                          ("raise", "raise is switched off"), ("fold", "fold is hidden")):
            out = r.run(Plan([Step(Click("call")), Step(Click(name))]))
            assert out.status == "failed" and why in out.reason
        assert fake.clicks == ["call"] * 3  # the steps before it were made; the failed one wasn't
    finally:
        r.close()


def test_a_backend_without_keys_refuses_typing():
    fake = Fake()
    fake.keyboard = False
    r = Runner(fake)
    try:
        out = r.run(Plan([Step(TypeText("amount", "40")), Step(Click("raise"))]))
        assert out.status == "failed" and "takes no typing" in out.reason and fake.clicks == []
    finally:
        r.close()


def test_the_expected_state_is_waited_for_and_retried():
    fake = Fake()
    r = Runner(fake, Settings(verify_timeout=1.0))
    try:
        # shows a little later: waited for
        threading.Timer(0.2, lambda: fake.state.update(moves=5)).start()
        out = r.run(Plan([Step(Click("call"), moved(5))]))
        assert out.status == "done" and out.steps[0].seconds >= 0.15
    finally:
        r.close()
    fake = Fake()
    r = Runner(fake, Settings(verify_timeout=0.1, retries=1))
    try:
        out = r.run(Plan([Step(Click("call"), moved(9))]))
        assert out.status == "failed" and "expected 9 moves made, not seen within 0.1 s" in out.reason
        assert out.steps[0].attempts == 2 and fake.clicks == ["call", "call"]
    finally:
        r.close()


def test_require_is_checked_before_the_first_step():
    fake = Fake()
    r = Runner(fake)
    try:
        out = r.run(Plan([Step(Click("call"))], require=Expect("your turn", lambda s: s.get("turn"))))
        assert out.status == "failed" and "not in the expected state (your turn)" in out.reason
        assert fake.clicks == []
        fake.state["turn"] = True
        assert r.run(Plan([Step(Click("call"))], require=Expect("your turn", lambda s: s.get("turn")))).ok
    finally:
        r.close()


def test_a_check_that_raises_has_not_seen_the_state():
    fake = Fake()
    r = Runner(fake, Settings(verify_timeout=0.05))
    try:
        out = r.run(Plan([Step(Click("call"), Expect("a key", lambda s: s["missing"]))]))
        assert out.status == "failed" and "the check failed" in out.reason
    finally:
        r.close()


def test_the_emergency_stop_ends_the_plan_under_way_and_drops_the_rest():
    fake = Fake()
    r = Runner(fake, Settings(verify_timeout=10.0))
    try:
        first = r.submit(Plan([Step(Click("call"), moved(99)), Step(Click("raise"))], "first"))
        later = [r.submit(Plan([Step(Click("fold"))], f"later {k}")) for k in range(3)]
        time.sleep(0.15)  # the first plan is waiting for its state
        t0 = time.monotonic()
        r.stop("test stop")
        out = first.result(2)
        assert time.monotonic() - t0 < 0.5  # at once, not after the 10 s wait
        assert out.status == "stopped" and out.reason == "test stop"
        assert [f.result(2).status for f in later] == ["stopped"] * 3
        assert fake.clicks == ["call"]  # nothing after the stop
        assert r.run(Plan([Step(Click("fold"))])).status == "stopped"  # refused until reset
        r.reset()
        assert r.run(Plan([Step(Click("fold"))])).status == "done"
    finally:
        r.close()


def test_stop_all_stops_every_runner():
    a, b = Runner(Fake()), Runner(Fake())
    try:
        Runner.stop_all("panic")
        assert a.stopped and b.stopped and a.stop_reason == "panic"
    finally:
        a.close()
        b.close()


def test_a_backend_call_that_hangs_stops_the_runner():
    fake = Fake()
    fake.hang = threading.Event()
    r = Runner(fake, Settings(call_timeout=0.2))
    try:
        out = r.run(Plan([Step(Click("call"))]), timeout=5)
        assert out.status == "stopped" and "did not answer within 0.2 s and may still act" in out.reason
        assert r.stopped
    finally:
        fake.hang.set()
        r.close()


def test_a_backend_error_fails_the_plan_and_the_runner_goes_on():
    fake = Fake()
    fake.fail = "the button moved"
    r = Runner(fake)
    try:
        out = r.run(Plan([Step(Click("call"))]))
        assert out.status == "failed" and "the button moved" in out.reason and not r.stopped
        fake.fail = None
        assert r.run(Plan([Step(Click("call"))])).status == "done"
    finally:
        r.close()
    r = Runner(fake, Settings(stop_on_failure=True))
    try:
        fake.fail = "the button moved"
        assert r.run(Plan([Step(Click("call"))])).status == "failed" and r.stopped
    finally:
        r.close()


def test_every_step_and_plan_goes_in_the_log(tmp_path):
    path = tmp_path / "interact.jsonl"
    r = Runner(Fake(), Settings(log_path=str(path)))
    try:
        r.run(Plan([Step(TypeText("amount", "40")), Step(Click("raise"))], "raise 40", meta={"hand": 3}))
        r.run(Plan([Step(Click("check"))], "check"))
        r.stop("done here")
    finally:
        r.close()
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    steps = [x for x in lines if x["event"] == "step"]
    plans = [x for x in lines if x["event"] == "plan"]
    assert [s["action"] for s in steps] == ["type '40' into amount", "click raise", "click check"]
    assert steps[1]["point"] == [240.0, 15.0] and steps[1]["status"] == "done"
    assert [p["status"] for p in plans] == ["done", "failed"] and plans[0]["meta"] == {"hand": 3}
    assert any(x["event"] == "stop" and x["reason"] == "done here" for x in lines)


def test_an_idle_runner_uses_no_cpu():
    r = Runner(Fake())
    try:
        r.run(Plan([Step(Click("call"))]))
        t0 = time.process_time()
        time.sleep(0.5)
        used = time.process_time() - t0
        assert used < 0.05, used  # blocked on its queue, not polling
    finally:
        r.close()


# ---------------------------------------------------------------- moves as plans
def shown(*names, labels=None):
    labels = labels or {}
    return {n: Target(n, (0, 0, 1, 1), labels.get(n, n.title())) for n in names}


def kinds(plan):
    return [(type(s.intent).__name__, s.intent.target, getattr(s.intent, "text", None)) for s in plan.steps]


def test_each_move_becomes_its_button():
    assert kinds(plan_for_move("fold", None, shown("fold", "call"))) == [("Click", "fold", None)]
    assert kinds(plan_for_move("check", None, shown("check", "bet"))) == [("Click", "check", None)]
    assert kinds(plan_for_move("call", None, shown("fold", "call"))) == [("Click", "call", None)]
    # calling every chip: the "All in" button
    assert kinds(plan_for_move("call", None, shown("fold", "all-in"))) == [("Click", "all-in", None)]
    assert kinds(plan_for_move("raise", 120, shown("fold", "call", "raise", "amount"))) == \
        [("TypeText", "amount", "120"), ("Click", "raise", None)]
    # a bet where the button says Raise, and the other way round
    assert kinds(plan_for_move("bet", 7.5, shown("check", "raise", "amount")))[1] == ("Click", "raise", None)
    assert kinds(plan_for_move("raise", 7.5, shown("check", "bet", "amount")))[0] == ("TypeText", "amount", "7.5")
    # no amount box: only the amount the button already shows
    assert kinds(plan_for_move("raise", 240, shown("fold", "raise", labels={"raise": "Raise to $240"}))) == \
        [("Click", "raise", None)]


def test_a_move_that_cant_be_made_is_refused_not_changed():
    with pytest.raises(PlanError, match="no fold button"):
        plan_for_move("fold", None, shown("check", "bet"))  # never turned into a check
    with pytest.raises(PlanError, match="no check button"):
        plan_for_move("check", None, shown("fold", "call"))
    with pytest.raises(PlanError, match="needs an amount"):
        plan_for_move("raise", None, shown("raise", "amount"))
    with pytest.raises(PlanError, match="no amount box"):
        plan_for_move("raise", 300, shown("fold", "raise", labels={"raise": "Raise to $240"}))
    with pytest.raises(PlanError, match="no raise button"):
        plan_for_move("raise", 300, shown("fold", "call"))
    with pytest.raises(PlanError, match="not a move"):
        plan_for_move("wait", None, shown("fold"))


# ---------------------------------------------------------------- the simulator backend
def a_hand(to_call=True, short=False):
    from tools.simulate import BB, SB, Hand, Seat

    seats = [Seat("app", stack=200.0, name=f"P{i}") for i in range(3)]
    h = Hand(seats, button=2)
    seats[0].stack, seats[0].bet, seats[0].put_in = 200 - SB, SB, SB
    seats[1].stack, seats[1].bet, seats[1].put_in = 200 - BB, BB, BB
    h.current = BB
    if not to_call:
        seats[0].bet = seats[0].put_in = BB
        seats[0].stack = 200 - BB
    if short:
        seats[1].stack -= 60
        seats[1].bet = seats[1].put_in = 62.0
        h.current = 62.0
        h.min_raise = 60.0
        seats[0].stack = 20.0
    return h


@pytest.mark.parametrize("case,kind,to", [
    ("call", "call", 0.0), ("call", "fold", 0.0), ("call", "raise", 7.0), ("call", "raise", 13.333333333333334),
    ("call", "raise", 3.0),  # under the minimum: raised to the minimum
    ("call", "raise", 900.0),  # over your chips: all in
    ("free", "check", 0.0), ("free", "fold", 0.0),  # folding when checking is free is a check
    ("free", "raise", 6.0), ("short", "raise", 50.0), ("short", "call", 0.0), ("short", "fold", 0.0),
])
def test_moves_through_the_runner_play_exactly_as_direct_ones(case, kind, to):
    from tools.interact_backends import TURN_OVER, SimBackend
    from tools.selftest import applied_move
    from tools.simulate import act

    h = a_hand(to_call=case != "free", short=case == "short")
    direct = copy.deepcopy(h)
    act(direct, 0, kind, to)
    sim = SimBackend()
    r = Runner(sim)
    try:
        move, amount = applied_move(h, kind, to)
        sim.open_turn(h)
        out = r.run(plan_for_move(move, amount, sim.targets(), expect=TURN_OVER, money=repr))
        assert out.status == "done", out.reason
    finally:
        r.close()
    assert h.log == direct.log
    assert [(s.stack, s.bet, s.put_in, s.folded, s.all_in, s.last) for s in h.seats] == \
           [(s.stack, s.bet, s.put_in, s.folded, s.all_in, s.last) for s in direct.seats]
    assert (h.current, h.min_raise) == (direct.current, direct.min_raise)
    assert sim.targets() == {}  # the buttons are gone


def test_the_simulator_refuses_a_click_off_its_button():
    from tools.interact_backends import SimBackend

    sim = SimBackend()
    sim.open_turn(a_hand())
    call = sim.targets()["call"]
    with pytest.raises(BackendError, match="landed on fold"):
        sim.click(call, sim.targets()["fold"].center)
    with pytest.raises(BackendError, match="hit nothing"):
        sim.click(call, (-500.0, -500.0))
    with pytest.raises(BackendError, match="not an amount"):
        sim.type_text(sim.targets()["amount"], "12abc", True)


# ---------------------------------------------------------------- what may import what
FORBIDDEN_INPUT = {"pyautogui", "pynput", "Quartz", "AppKit", "Cocoa", "CoreGraphics", "win32api", "win32con",
                   "win32gui", "pywinauto", "Xlib", "evdev", "uinput", "keyboard", "mouse", "autopy", "ctypes",
                   "pyscreeze", "pydirectinput", "subprocess"}
ENGINE = ("app.poker", "app.solver", "app.recognition", "app.vision", "app.capture", "app.ai", "tools")


def imports_of(path):
    tree = ast.parse(open(path).read())
    package = os.path.relpath(os.path.dirname(path), ROOT).split(os.sep)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # relative to the file's own package
                parent = package[:len(package) - (node.level - 1)]
                base = ".".join(parent + ([base] if base else []))
            out.add(base)
    return out


def py_files(*parts):
    top = os.path.join(ROOT, *parts)
    for d, _, files in os.walk(top):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


def test_interact_drives_nothing_outside_our_own_programs():
    files = list(py_files("app", "interact")) + [os.path.join(ROOT, "tools", "interact_backends.py")]
    for path in files:
        for mod in imports_of(path):
            assert mod.split(".")[0] not in FORBIDDEN_INPUT, f"{path} imports {mod}"
        text = open(path).read()
        assert "QCursor" not in text and "setPos" not in text, f"{path} moves the system pointer"


def test_interact_is_independent_of_the_poker_engine():
    for path in py_files("app", "interact"):
        for mod in imports_of(path):
            assert not mod.startswith(ENGINE), f"{path} imports {mod}"
    for pkg in ("poker", "solver", "recognition", "vision", "state", "capture", "ai"):
        for path in py_files("app", pkg):
            for mod in imports_of(path):
                assert not mod.startswith("app.interact"), f"{path} imports {mod}"
