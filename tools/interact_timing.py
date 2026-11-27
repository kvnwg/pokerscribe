"""How fast app/interact is, and that it costs nothing while idle.

    python tools/interact_timing.py [--plans 2000]

Measures, on our own backends only: how long submit() holds up the caller, the runner's own
time per plan (a backend that does nothing), a move on the simulator's buttons (type the amount,
click, check your turn is over), a click on a Qt window of our own (offscreen), how soon stop()
ends a plan that is waiting, and the CPU an idle runner uses. Results: docs/research/INTERACT.md.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.interact import Backend, Click, Expect, Plan, Runner, Settings, Step, Target, plan_for_move  # noqa: E402


class Null(Backend):
    name = "null"

    def __init__(self):
        super().__init__()
        self.t = {"call": Target("call", (0, 0, 10, 10), "Call")}
        self.n = 0

    def targets(self):
        return self.t

    def click(self, target, point):
        self.n += 1

    def snapshot(self):
        return self.n


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def row(name, xs, unit=1000.0):
    return f"| {name} | {len(xs)} | {pct(xs, 50) * unit:.3f} | {pct(xs, 95) * unit:.3f} | {max(xs) * unit:.3f} |"


def null_runner(n):
    r = Runner(Null())
    submits, plans = [], []
    try:
        for _ in range(n):
            t0 = time.perf_counter()
            fut = r.submit(Plan([Step(Click("call"))]))
            submits.append(time.perf_counter() - t0)
            plans.append(fut.result(5).seconds)
    finally:
        r.close()
    return submits, plans


def simulator(n):
    from tools.interact_backends import TURN_OVER, SimBackend
    from tools.simulate import BB, SB, Hand, Seat

    sim = SimBackend()
    r = Runner(sim)
    out = []
    try:
        for k in range(n):
            seats = [Seat("app", stack=200.0, name=f"P{i}") for i in range(3)]
            h = Hand(seats, button=2)
            seats[0].stack, seats[0].bet = 200 - SB, SB
            seats[1].stack, seats[1].bet = 200 - BB, BB
            h.current = BB
            sim.open_turn(h)
            plan = plan_for_move("raise", 6.0 + k % 5, sim.targets(), expect=TURN_OVER, money=repr)
            res = r.run(plan)
            assert res.ok, res.reason
            out.append(res.seconds)
    finally:
        r.close()
    return out


def qt_window(n):
    from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

    from app.interact.qt import QtBackend

    app = QApplication.instance() or QApplication([])
    w = QWidget()
    lay = QHBoxLayout(w)
    clicks = [0]
    for name in ("fold", "call", "raise"):
        b = QPushButton(name.title(), w)
        b.setObjectName(name)
        b.clicked.connect(lambda _=False: clicks.__setitem__(0, clicks[0] + 1))
        lay.addWidget(b)
    w.show()
    app.processEvents()
    r = Runner(QtBackend(w))
    out = []
    try:
        for k in range(n):
            want = k + 1
            fut = r.submit(Plan([Step(Click("call"), Expect("clicked", lambda s, want=want: clicks[0] >= want))]))
            while not fut.done():
                app.processEvents()
            res = fut.result()
            assert res.ok, res.reason
            out.append(res.seconds)
    finally:
        r.close()
        w.close()
    return out


def stop_latency(n):
    out = []
    r = Runner(Null(), Settings(verify_timeout=30.0))
    try:
        for _ in range(n):
            fut = r.submit(Plan([Step(Click("call"), Expect("never", lambda s: False))]))
            time.sleep(0.02)
            t0 = time.perf_counter()
            r.stop("timing")
            fut.result(5)
            out.append(time.perf_counter() - t0)
            r.reset()
    finally:
        r.close()
    return out


def idle_cpu(seconds=2.0):
    r = Runner(Null())
    try:
        r.run(Plan([Step(Click("call"))]))
        t0, c0 = time.perf_counter(), time.process_time()
        time.sleep(seconds)
        return (time.process_time() - c0) / (time.perf_counter() - t0)
    finally:
        r.close()


def main() -> None:
    import logging

    logging.getLogger("app.interact").setLevel(logging.ERROR)  # the stops below are on purpose
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plans", type=int, default=2000)
    args = ap.parse_args()
    n = args.plans
    submits, plans = null_runner(n)
    print("| What | Plans | p50 ms | p95 ms | max ms |")
    print("| --- | --- | --- | --- | --- |")
    print(row("submit() returns (the caller is held up)", submits))
    print(row("a click on a backend that does nothing (the runner's own time)", plans))
    print(row("simulator: type the amount, click raise, check the turn is over", simulator(n)))
    print(row("Qt window: click a button, check it was clicked", qt_window(max(50, n // 10))))
    print(row("stop() to the end of a plan that is waiting", stop_latency(max(20, n // 50))))
    print(f"\nidle runner: {100 * idle_cpu():.2f}% of one core")


if __name__ == "__main__":
    main()
