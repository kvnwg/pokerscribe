"""app/interact on our own Qt widgets: clicks, typing and keys reach the widget, missing or
switched-off widgets fail, and the window keeps running while a plan is carried out."""
import time

import pytest

from app.interact import Click, Expect, Plan, PressKey, Runner, Settings, Step, TypeText


@pytest.fixture()
def window(qapp):
    from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

    w = QWidget()
    w.setObjectName("window")
    lay = QHBoxLayout(w)
    w.counts = {"fold": 0, "call": 0, "enter": 0}
    for name in ("fold", "call", "raise", "secret"):
        b = QPushButton(name.title(), w)
        b.setObjectName(name)
        lay.addWidget(b)
        if name in w.counts:
            b.clicked.connect(lambda _=False, n=name: w.counts.__setitem__(n, w.counts[n] + 1))
    box = QLineEdit(w)
    box.setObjectName("amount")
    box.returnPressed.connect(lambda: w.counts.__setitem__("enter", w.counts["enter"] + 1))
    lay.addWidget(box)
    w.findChild(QPushButton, "raise").setEnabled(False)
    w.resize(640, 80)
    w.show()
    w.findChild(QPushButton, "secret").hide()
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def wait(qapp, fut, seconds=5.0):
    """The GUI thread keeps running its events while the plan is carried out."""
    deadline = time.monotonic() + seconds
    while not fut.done():
        qapp.processEvents()
        assert time.monotonic() < deadline, "the plan didn't finish"
        time.sleep(0.002)
    return fut.result()


def test_clicks_typing_and_keys_reach_our_widgets(qapp, window):
    from app.interact.qt import QtBackend

    qt = QtBackend(window)
    r = Runner(qt)
    try:
        targets = qt.targets()
        assert {"fold", "call", "raise", "secret", "amount"} <= set(targets)
        assert not targets["raise"].enabled and not targets["secret"].visible
        out = wait(qapp, r.submit(Plan([
            Step(Click("call"), Expect("call clicked", lambda s: window.counts["call"] == 1)),
            Step(TypeText("amount", "125"), Expect("125 in the box", lambda s: s["amount"].label == "125")),
            Step(TypeText("amount", "40")),  # replaces what was there
            Step(PressKey("Enter", "amount")),
        ])))
        assert out.status == "done", out.reason
        assert window.counts == {"fold": 0, "call": 1, "enter": 1}
        assert qt.targets()["amount"].label == "40"
    finally:
        r.close()


def test_a_switched_off_hidden_or_missing_widget_is_not_touched(qapp, window):
    from app.interact.qt import QtBackend

    r = Runner(QtBackend(window))
    try:
        for name, why in (("raise", "raise is switched off"), ("secret", "secret is hidden"),
                          ("allin", "allin is not on screen")):
            out = wait(qapp, r.submit(Plan([Step(Click(name))])))
            assert out.status == "failed" and why in out.reason
        assert window.counts == {"fold": 0, "call": 0, "enter": 0}
    finally:
        r.close()


def test_the_window_keeps_running_while_a_plan_waits(qapp, window):
    from PySide6.QtCore import QTimer

    from app.interact.qt import QtBackend

    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)
    # the state shows 0.3 s after the click, set by the GUI itself
    QTimer.singleShot(300, lambda: window.setWindowTitle("moved"))
    r = Runner(QtBackend(window), Settings(verify_timeout=2.0))
    try:
        t0 = time.monotonic()
        fut = r.submit(Plan([Step(Click("fold"), Expect("title moved", lambda s: window.windowTitle() == "moved"))]))
        assert time.monotonic() - t0 < 0.05
        out = wait(qapp, fut)
        assert out.status == "done" and window.counts["fold"] == 1
        assert out.seconds >= 0.25
        assert len(ticks) >= 10  # the timer kept firing: the GUI thread was never blocked
    finally:
        timer.stop()
        r.close()


def test_waiting_for_a_plan_on_the_gui_thread_is_refused(qapp, window):
    from app.interact.qt import QtBackend

    r = Runner(QtBackend(window))
    try:
        with pytest.raises(RuntimeError, match="use submit"):
            r.run(Plan([Step(Click("fold"))]))
        assert window.counts["fold"] == 0
    finally:
        r.close()


def test_a_dry_run_on_widgets_does_nothing(qapp, window):
    from app.interact.qt import QtBackend

    r = Runner(QtBackend(window), Settings(dry_run=True))
    try:
        out = wait(qapp, r.submit(Plan([Step(TypeText("amount", "9")), Step(Click("call"))])))
        assert out.status == "dry-run"
        assert window.counts["call"] == 0 and QtBackend(window).targets()["amount"].label == ""
    finally:
        r.close()
