"""Misreads found by tools/selftest.py, where PokerScribe plays on our own demo table
(app/tests/demo_table.py). Each test draws the moment that went wrong."""
from typing import Dict, List, Optional

import pytest

from app.recognition.recognizer import TableRecognizer
from app.tests.demo_table import SeatView, TableView, layouts, render
from app.vision.card_recognizer import CardRecognizer
from app.vision.ocr import RapidOcrEngine

needs_ocr = pytest.mark.skipif(not RapidOcrEngine.available(), reason="RapidOCR not installed")
LAY = layouts()
NAMES = ["You", "Marlow", "Quinn", "Jasper", "Rhea", "Toby"]


@pytest.fixture(scope="module")
def rec():
    return TableRecognizer(CardRecognizer(), RapidOcrEngine(), threshold=0.70)


def table(folded=(), bets: Optional[Dict[int, float]] = None, tags: Optional[Dict[int, str]] = None,
          all_in=(), shown: Optional[Dict[int, tuple]] = None, hero_cards=("As", "Kh"), board=(),
          collected=0.0, button=0, acting: Optional[int] = None, buttons: List[str] = ()) -> TableView:
    bets = bets or {}
    seats = []
    for i, name in enumerate(NAMES):
        s = SeatView(name, 0.0 if i in all_in else 200.0 - bets.get(i, 0.0), bets.get(i, 0.0),
                     has_cards=i not in folded, all_in=i in all_in)
        s.tag = (tags or {}).get(i)
        s.shown = (shown or {}).get(i)
        seats.append(s)
    return TableView(seats, list(hero_cards), list(board), collected, button, acting, list(buttons), hand_no=7)


def read(rec, view, layout):
    img, meta = render(view, LAY[layout])
    res = rec.recognize(img)
    plates = meta["plates"]

    def seat_of(center):
        return min(range(len(plates)), key=lambda i: (plates[i][0] - center[0]) ** 2 + (plates[i][1] - center[1]) ** 2)

    by_seat = {seat_of(s.center): s for s in res.layout.seats}
    return res, by_seat, seat_of


@needs_ocr
def test_card_backs_on_a_grey_felt(rec):
    """A grey felt has almost no colour: the teal card backs were taken for the felt."""
    res, seats, _ = read(rec, table(folded=(1, 4, 5), acting=2), "wireframe")
    assert [seats[i].has_cards for i in (1, 2, 3, 4, 5)] == [False, True, True, False, False]


@needs_ocr
def test_card_backs_close_to_the_felt_colour(rec):
    """Teal backs on a green felt: the backs are separate patches, not part of the felt."""
    res, seats, _ = read(rec, table(folded=(1, 5), acting=3), "ninemax")
    assert [seats[i].has_cards for i in (1, 2, 3, 4, 5)] == [False, True, True, True, False]


@needs_ocr
def test_a_bet_on_the_same_line_as_the_pot(rec):
    """Quinn's big blind lies on the line of "Total pot: $3": it is a bet, not the pot."""
    res, seats, _ = read(rec, table(bets={1: 1, 2: 2}, acting=3), "wireframe")
    assert seats[2].bet is not None and seats[2].bet.value == 2
    assert seats[1].bet is not None and seats[1].bet.value == 1


@needs_ocr
def test_action_tags_on_the_plates_are_not_your_buttons(rec):
    """"Call" at the lower left and "Fold" at the lower right are seat tags, far apart on one
    line: not a row of action buttons, so it isn't your turn and every seat is found."""
    view = table(folded=(5,), bets={1: 2, 2: 2}, tags={1: "Call", 5: "Fold", 3: "Check"}, acting=4)
    res, seats, _ = read(rec, view, "tags")
    assert res.state.hero_to_act.value is not True
    assert not res.layout.actions
    assert sorted(seats) == [0, 1, 2, 3, 4, 5]


@needs_ocr
def test_all_in_shown_in_place_of_the_name(rec):
    res, seats, _ = read(rec, table(tags={2: "All in"}, all_in=(2,), bets={2: 200}, acting=3), "tags")
    assert 2 in seats and seats[2].stack.value == 0


@needs_ocr
def test_showdown_cards_of_others_are_not_yours(rec):
    """After you fold, the others turn their cards face up: none of them is your seat."""
    view = table(folded=(0, 2, 3, 5), shown={1: ("Ad", "7h"), 4: ("Ks", "7d")}, hero_cards=(),
                 board=("3d", "8c", "Ac", "9h", "Jd"), collected=40)
    res, seats, _ = read(rec, view, "compact")
    hero = next(s for s in res.layout.seats if s.is_hero)
    assert hero.name == "You"
    assert not res.layout.hero_cards


@needs_ocr
@pytest.mark.parametrize("layout", ["wireframe", "green", "compact"])
def test_whose_turn_from_the_timer_bar_or_glow(rec, layout):
    """The timer bar (or the glow ring alone) on another seat: it's their turn, not yours."""
    res, seats, seat_of = read(rec, table(bets={1: 1, 2: 2}, acting=3), layout)
    assert res.layout.acting_seat is not None
    assert seat_of(res.layout.seats[res.layout.acting_seat].center) == 3
    assert res.state.hero_to_act.value is False


@needs_ocr
def test_your_turn_with_the_buttons(rec):
    view = table(bets={1: 1, 2: 2}, acting=0, buttons=["Fold", "Call $2", "Raise"])
    res, seats, seat_of = read(rec, view, "wireframe")
    assert res.state.hero_to_act.value is True
    assert res.layout.acting_seat is None or seat_of(res.layout.seats[res.layout.acting_seat].center) == 0


@needs_ocr
def test_hand_number_is_read_and_never_an_amount(rec):
    res, seats, _ = read(rec, table(acting=3), "wireframe")
    assert res.layout.hand_id == "357618007"
    assert all(s.stack.value != 357618007 for s in res.layout.seats if s.stack)


@needs_ocr
def test_a_king_close_to_the_card_edge_on_a_dark_felt(rec):
    """A serif K touching the card's top edge by a pixel, on a near-black felt, was taken
    for felt showing through: both kings vanished and the flop had two cards."""
    view = table(folded=(3, 4), hero_cards=("4h", "Kc"), board=("Ks", "8h", "9s"), collected=8, acting=5)
    res, _, _ = read(rec, view, "tags")
    assert len(res.layout.board) == 3 and len(res.layout.hero_cards) == 2


def test_ocr_slip_i_for_1_in_an_amount():
    from app.recognition.amounts import parse_amount

    assert parse_amount("$25i").value == 251
    assert parse_amount("Rhea") is None


def test_a_seat_whose_stack_cant_be_read_still_counts():
    """One unreadable stack must not remove the seat: every position after it would shift."""
    import numpy as np

    from app.recognition.layout import analyse
    from app.vision.ocr import TextBox

    W, H = 1280, 900
    spots = [(640, 760), (166, 578), (166, 272), (640, 156), (1114, 272), (1114, 578)]
    boxes = []
    for (x, y), name, stack in zip(spots, NAMES, ["$200", "$199", "$198", "$200", "$200", "$2#~"]):
        boxes.append(TextBox(name, 0.85, x - 35, y - 26, 70, 24))
        boxes.append(TextBox(stack, 0.8, x - 30, y, 60, 24))
    res = analyse(np.zeros((H, W, 3), np.uint8), [], boxes)
    assert len(res.seats) == 6
    toby = next(s for s in res.seats if s.name == "Toby")
    assert toby.stack is None


def test_ocr_slips_inside_a_pot_label_and_full_width_digits():
    from app.recognition.amounts import first_amount, parse_amount

    assert first_amount("Total pot:$1o").value == 10  # "$10" read as "$1o"
    assert parse_amount("６").value == 6  # a full-width "6"


@needs_ocr
def test_a_short_bet_the_text_finder_skips(rec):
    """"$2" by Marlow's chip (and lone digits on a table without "$") were never found, so
    the bet counted as nothing: a raise could look like no raise at all."""
    res, seats, _ = read(rec, table(bets={0: 1, 1: 2}, acting=2, button=5), "ninemax")
    assert seats[1].bet is not None and seats[1].bet.value == 2


@needs_ocr
def test_lone_digit_bets_are_never_read_as_no_bet(rec):
    res, seats, _ = read(rec, table(bets={0: 1, 1: 2, 2: 6, 5: 6}, acting=0, button=5,
                                    buttons=["Fold", "Call 5", "Raise to 10"]), "green")
    for i, amount in {1: 2, 2: 6, 5: 6}.items():
        assert seats[i].bet is not None and seats[i].bet.value == amount


def test_ocr_dropping_spaces_in_the_pot_label_and_raise_button():
    """"Totalpot:$51" and "Raiseto$46": the pot was lost (no pot odds), and the raise button
    wasn't a button."""
    from app.recognition.layout import ACTION_RE, POT_RE
    from app.state.model import Action

    m = POT_RE.search("Totalpot:$51")
    assert m and m.group(1)
    assert POT_RE.search("Jackpot 500") is None
    assert ACTION_RE.match("Raiseto$46") and Action.parse("Raiseto$46") == Action("raise", 46)
    assert not ACTION_RE.match("Betty")
