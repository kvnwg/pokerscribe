"""app/interact on our demo table: the buttons are found by the reader at any picture size, a
click lands on the button it was meant for, the move is made and the buttons go away; and the
self-test plays exactly the same game with its moves made through app/interact."""
import dataclasses
import json

import pytest

from app.interact import BackendError, Runner, Settings, Target, plan_for_move

SLOW = Settings(call_timeout=120.0)  # a call can read a whole picture
from app.tests.demo_table import layouts


def hero_turn():
    """Six players, blinds posted, you first to act (under the gun) with A-K."""
    from tools.simulate import BB, SB, Hand, Seat

    names = ["You", "Marlow", "Quinn", "Jasper", "Rhea", "Toby"]
    seats = [Seat("app", stack=200.0, name=n) for n in names]
    for k, s in enumerate(seats):
        s.cards = ("As", "Kd") if k == 0 else ("2c", "3d")
    h = Hand(seats, button=3)
    for i, amt in ((4, SB), (5, BB)):
        seats[i].stack -= amt
        seats[i].bet = seats[i].put_in = amt
    h.current = BB
    return h


@pytest.fixture(scope="module")
def reader():
    import tempfile

    from app.recognition.recognizer import TableRecognizer
    from app.vision.card_recognizer import CardRecognizer
    from app.vision.ocr import FallbackOcr

    return TableRecognizer(CardRecognizer(tempfile.mkdtemp(prefix="interact-cards-"), 0.70), FallbackOcr("auto"), 0.70)


def drawn_kind(meta, point):
    from app.state.model import Action

    for label, (x, y, w, h) in meta["buttons"]:
        if x <= point[0] <= x + w and y <= point[1] <= y + h:
            return Action.parse(label).kind
    return None


@pytest.mark.parametrize("layout,scale", [("wireframe", 0.75), ("wireframe", 1.0), ("wireframe", 1.5),
                                          ("stock", 1.0), ("portrait", 1.0)])
def test_buttons_found_by_the_reader_are_clicked_where_they_were_drawn(reader, layout, scale):
    from tools.interact_backends import BUTTONS_GONE, DemoTableBackend

    lay = dataclasses.replace(layouts()[layout], scale=scale) if scale != 1.0 else layouts()[layout]
    table = DemoTableBackend(lay, reader)
    h = hero_turn()
    table.open_turn(h)
    targets = table.targets()
    assert {"fold", "call", "raise"} <= set(targets), [b.text for b in table.read.layout.action_boxes]
    for name, t in targets.items():
        assert drawn_kind(table.meta, t.center) == name  # the middle of what was read is on that button
    r = Runner(table, SLOW)
    try:
        out = r.run(plan_for_move("call", None, targets, expect=BUTTONS_GONE))
        assert out.status == "done", out.reason
    finally:
        r.close()
    assert table.moves == [("call", 0.0)] and h.log[-1] == (0, "call", 2.0, 0)
    assert table.targets() == {}  # drawn and read again: your buttons are gone


def test_a_raise_uses_the_amount_on_its_button(reader):
    from tools.interact_backends import BUTTONS_GONE, DemoTableBackend

    lay = layouts()["green"]  # "Raise to 4": the button says the amount
    table = DemoTableBackend(lay, reader)
    h = hero_turn()
    table.open_turn(h)
    targets = table.targets()
    r = Runner(table, SLOW)
    try:
        out = r.run(plan_for_move("raise", 4.0 * lay.unit, targets, expect=BUTTONS_GONE))
        assert out.status == "done", out.reason
    finally:
        r.close()
    assert h.log[-1] == (0, "raise", 4.0, 0) and h.current == 4.0


def test_a_click_off_the_button_is_caught_and_nothing_is_played(reader):
    from tools.interact_backends import DemoTableBackend

    table = DemoTableBackend(layouts()["wireframe"], reader)
    h = hero_turn()
    table.open_turn(h)
    fold, call = table.targets()["fold"], table.targets()["call"]
    with pytest.raises(BackendError, match="landed on"):
        table.click(call, fold.center)  # a target read in the wrong place
    with pytest.raises(BackendError, match="hit no button"):
        table.click(Target("call", (0, 0, 4, 4)), (2.0, 2.0))
    assert h.log == [] and table.moves == []


def test_the_self_test_plays_the_same_game_through_app_interact(tmp_path):
    from tools.selftest import Run

    lay = layouts()["wireframe"]
    # seed 14: in two hands you raise, check, call and bet (amounts typed in the amount box)
    plain = Run(lay, 14, None, 0.0)
    plain.go(2)
    through = Run(lay, 14, str(tmp_path), 0.0, interact=True)
    through.go(2)
    moves = through.rep.c.pop("moves through app/interact")
    assert moves == plain.rep.c["decisions"] + plain.rep.c["no instruction on your turn"] > 0
    assert through.rep.c == plain.rep.c  # every count the same, and no "interaction failed"
    assert [(s.stack, s.name) for s in through.table.seats] == [(s.stack, s.name) for s in plain.table.seats]
    plans = [json.loads(x) for x in (tmp_path / "interact.jsonl").read_text().splitlines()]
    plans = [p for p in plans if p["event"] == "plan"]
    assert len(plans) == moves and all(p["status"] == "done" for p in plans)
    assert {p["plan"].split()[0] for p in plans} >= {"raise", "check", "call", "bet"}
