"""Misreads found by tools/selftest.py on tables drawn with round player pictures and numbers
that are neither stacks nor bets (levels, a countdown, an experience counter, a bonus, a
notification count). The layouts follow three screenshots Kevin sent on 26 Nov. Each test
draws the moment that went wrong on our own demo table (app/tests/demo_table.py)."""
from typing import Dict, List, Optional

import numpy as np
import pytest

from app.recognition.amounts import parse_amount
from app.recognition.layout import analyse
from app.recognition.recognizer import TableRecognizer
from app.tests.demo_table import SeatView, TableView, layouts, render
from app.vision.card_recognizer import CardRecognizer
from app.vision.ocr import RapidOcrEngine, TextBox

needs_ocr = pytest.mark.skipif(not RapidOcrEngine.available(), reason="RapidOCR not installed")
LAY = layouts()
NAMES = ["You", "Marlow", "Quinn", "Jasper", "Rhea", "Toby"]


@pytest.fixture(scope="module")
def rec():
    return TableRecognizer(CardRecognizer(), RapidOcrEngine(), threshold=0.70)


def table(folded=(), bets: Optional[Dict[int, float]] = None, all_in=(), hero_cards=("As", "Kh"), board=(),
          collected=0.0, button=0, acting: Optional[int] = None, buttons: List[str] = (),
          stacks: Optional[Dict[int, float]] = None, timer_left: float = 0.6) -> TableView:
    bets, stacks = bets or {}, stacks or {}
    seats = []
    for i, name in enumerate(NAMES):
        stack = 0.0 if i in all_in else stacks.get(i, 200.0 - bets.get(i, 0.0))
        seats.append(SeatView(name, stack, bets.get(i, 0.0), has_cards=i not in folded, all_in=i in all_in))
    return TableView(seats, list(hero_cards), list(board), collected, button, acting, list(buttons), hand_no=7,
                     timer_left=timer_left)


def read(rec, view, layout):
    """The reading, and the layout's seats keyed by the screen seat they were read at."""
    img, meta = render(view, LAY[layout])
    res = rec.recognize(img)
    plates = meta["plates"]

    def seat_of(center):
        return min(range(len(plates)), key=lambda i: (plates[i][0] - center[0]) ** 2 + (plates[i][1] - center[1]) ** 2)

    return res, {seat_of(s.center): s for s in res.layout.seats}


def bet(seat) -> float:
    return 0.0 if seat.bet is None else seat.bet.value


# ------------------------------------------------------------------ amounts
def test_currency_after_the_number():
    """"12,400$" (the currency after the number) was not read as an amount: every stack on
    that table came back UNKNOWN."""
    assert parse_amount("12,400$").value == 12400
    assert parse_amount("930$").value == 930
    assert parse_amount("20 €").value == 20
    assert parse_amount("+100%") is None
    assert parse_amount("300512 / 512000") is None


def test_a_level_beside_the_name_is_not_a_bet():
    """A level ("33") printed on the name's line, next to it, sits between the seat and the
    middle for a seat on the left: it was taken for that player's bet."""
    W, H = 1280, 900
    spots = [(640, 760), (166, 578), (166, 272), (640, 156), (1114, 272), (1114, 578)]
    boxes = []
    for (x, y), name in zip(spots, NAMES):
        boxes.append(TextBox(name, 0.9, x - 35, y - 26, 70, 24))
        boxes.append(TextBox("$200", 0.9, x - 30, y, 60, 24))
    boxes.append(TextBox("33", 0.9, 166 + 50, 578 - 26, 26, 22))  # Marlow's level, on his name's line
    boxes.append(TextBox("$6", 0.9, 330, 540, 30, 22))  # Marlow's real bet, toward the middle
    res = analyse(np.zeros((H, W, 3), np.uint8), [], boxes)
    marlow = next(s for s in res.seats if s.name == "Marlow")
    assert marlow.bet is not None and marlow.bet.value == 6


# --------------------------------------------------------------- pictures
@needs_ocr
def test_levels_on_pictures_are_not_bets_and_stacks_end_in_dollars(rec):
    """Green app: a level on each player's picture, stacks as "1,000$" (blinds 5/10). Every
    stack was UNKNOWN, and a level by a bottom seat's picture could pass for its bet."""
    view = table(bets={4: 5, 5: 10}, folded=(2,), acting=1, button=3)
    res, seats = read(rec, view, "avatars")
    assert sorted(seats) == [0, 1, 2, 3, 4, 5]
    assert [seats[i].stack.value for i in (1, 3)] == [1000, 1000]
    assert [bet(seats[i]) for i in (1, 2, 3)] == [0, 0, 0]
    assert [bet(seats[i]) for i in (4, 5)] == [25, 50]


@needs_ocr
def test_a_folded_players_picture_is_not_card_backs(rec):
    """The hair and shoulders in a player's picture looked like card backs, so folded players
    stayed in the hand (and the tracker took their chips for bets)."""
    res, seats = read(rec, table(folded=(2, 5), acting=3, button=1), "avatars")
    assert [seats[i].has_cards for i in (1, 2, 3, 4, 5)] == [True, False, True, True, False]


@needs_ocr
def test_the_ring_round_the_acting_picture_is_their_turn(rec):
    """Whose turn it is: a coloured ring (the time left) round that player's picture. Card
    backs touching another picture are not a ring."""
    for layout, acting in (("avatars", 3), ("stock", 5), ("portrait", 3)):
        res, seats = read(rec, table(acting=acting, button=1, timer_left=0.5), layout)
        assert res.layout.acting_seat is not None, layout
        assert res.layout.seats[res.layout.acting_seat] is seats[acting], layout


@needs_ocr
def test_bonus_and_a_notification_count_are_not_players(rec):
    """"Bonus" over "+100%" (top left) was read as a seventh player, shifting every position."""
    res, seats = read(rec, table(acting=2, button=4), "stock")
    assert len(res.layout.seats) == 6
    assert not any("bonus" in s.name.lower() for s in res.layout.seats)


@needs_ocr
def test_buttons_stacked_in_a_column(rec):
    """RAISE, CALL and FOLD one above the other at the right edge: not a row, so your turn was
    missed."""
    view = table(bets={1: 6}, acting=0, button=3, buttons=["Fold", "Call $ 60", "Raise"])
    res, seats = read(rec, view, "stock")
    assert res.state.hero_to_act.value is True
    assert sorted(a.kind for a in res.layout.actions) == ["call", "fold", "raise"]
    assert res.state.to_call.value == 60


@needs_ocr
def test_bets_without_a_dollar_next_to_stacks_with_one(rec):
    """Stacks "$ 2,000", bets a bare "60" by a chip stack: every bet came back UNKNOWN, as a
    second read without "$" never counted on a table whose amounts mostly have one."""
    res, seats = read(rec, table(bets={1: 6, 4: 47}, acting=5, button=3), "stock")
    assert seats[1].bet is not None and seats[1].bet.value == 60
    assert seats[4].bet is not None and seats[4].bet.value == 470
    assert res.state.players[[s is seats[1] for s in res.layout.seats].index(True)].bet.known


@needs_ocr
def test_name_above_the_picture_and_stack_under_it(rec):
    """Phone table: the name above the picture, the stack under it, the seconds left in big
    digits on the acting player's picture. Five of six seats were lost, and "Pot Amt." with
    the pot under it was read as a player."""
    view = table(bets={1: 6, 4: 6}, folded=(2,), acting=3, button=5, collected=24, board=("Ks", "7d", "2h"))
    res, seats = read(rec, view, "portrait")
    assert sorted(seats) == [0, 1, 2, 3, 4, 5]
    assert [seats[i].stack.value for i in (0, 3, 5)] == [20000, 20000, 20000]
    assert [bet(seats[i]) for i in range(6)] == [0, 600, 0, 0, 600, 0]  # the countdown is no bet
    assert res.state.pot.value == 2400
    assert not any("pot" in s.name.lower() for s in res.layout.seats)


@needs_ocr
def test_your_stack_just_above_a_button_bar(rec):
    """On a phone the buttons run across the bottom, right under your stack: it was taken for
    a bet-size box next to the buttons and your seat was lost."""
    view = table(bets={1: 6}, acting=0, button=3, buttons=["Fold", "Call $ 600", "Raise"])
    res, seats = read(rec, view, "portrait")
    assert 0 in seats and seats[0].is_hero
    assert seats[0].stack.value == 20000
    assert res.state.hero_to_act.value is True


@needs_ocr
def test_a_level_box_on_the_plate_is_not_cards_or_a_bet(rec):
    """Gold level boxes on the name's line looked like card backs: folded players stayed in."""
    res, seats = read(rec, table(folded=(1, 2, 5), bets={3: 6}, acting=4, button=0), "levels")
    assert [seats[i].has_cards for i in (1, 2, 3, 4, 5)] == [False, False, True, True, False]
    assert [bet(seats[i]) for i in (1, 2, 4, 5)] == [0, 0, 0, 0]
    assert bet(seats[3]) == 6


@needs_ocr
def test_a_pictures_white_rim_is_not_the_dealer_button(rec):
    """The white rim round each player's picture is a bright disc, like the dealer button:
    the button was put on the wrong seat and every position was off."""
    for layout in ("avatars", "stock", "portrait"):
        res, seats = read(rec, table(acting=2, button=4), layout)
        assert res.layout.button_seat is not None, layout
        assert res.layout.seats[res.layout.button_seat] is seats[4], layout


@needs_ocr
def test_the_dealer_button_touching_a_bet(rec):
    """The dealer button beside a bet was read with it, "$ 200D", and the D repaired as a 0:
    a bet of 2000, "someone raised" and FOLD when checking was free."""
    view = table(bets={0: 2, 4: 2, 5: 2}, button=4, acting=0, buttons=["Check", "Raise"])
    res, seats = read(rec, view, "portrait")
    assert bet(seats[4]) == 200
    assert res.state.to_call.value == 0


@needs_ocr
def test_two_buttons_across_the_bottom_of_a_phone(rec):
    """CHECK and RAISE fill the bottom edge, far apart: only RAISE was taken for a button, so
    checking looked impossible."""
    view = table(bets={0: 2, 5: 2}, button=4, acting=0, buttons=["Check", "Raise"])
    res, seats = read(rec, view, "portrait")
    assert sorted(a.kind for a in res.layout.actions) == ["check", "raise"]


@needs_ocr
def test_your_seat_after_you_folded(rec):
    """No cards of yours to show which seat is yours: the lowest seat in the middle band was
    taken, and on this table that is the player at the bottom right."""
    view = table(folded=(0, 2), hero_cards=(), acting=3, button=1)
    res, seats = read(rec, view, "stock")
    assert seats[0].is_hero and not seats[5].is_hero


def test_a_big_blind_who_re_raised_is_not_the_stakes():
    """No stakes printed: the big blind's chips stood in for the big blind. The big blind had
    re-raised, so the re-raise looked like the stakes and nobody seemed to have raised:
    "RAISE TO 2.5 BIG BLINDS" (an open) when the truth was "they re-raised you"."""
    from app.poker.advice import advise
    from app.state.model import Action, Field, GameState, Player

    def player(seat, pos, stack, bet, hero=False, folded=False):
        return Player(seat=seat, is_hero=hero, position=Field.manual(pos), stack=Field.manual(stack),
                      bet=Field.manual(bet), in_hand=Field.manual(not folded))

    players = [player(0, "BTN", 975, 25, hero=True), player(1, "SB", 995, 5, folded=True),
               player(2, "BB", 920, 80), player(3, "UTG", 1000, 0, folded=True),
               player(4, "HJ", 1000, 0, folded=True), player(5, "CO", 1000, 0, folded=True)]
    st = GameState(hero_cards=[Field.manual("Qs"), Field.manual("7s")], players=players)
    st.street, st.pot, st.pot_includes_bets = Field.manual("preflop"), Field.manual(0.0), False
    st.to_call, st.hero_to_act = Field.manual(55.0), Field.manual(True)
    st.available_actions = Field.manual([Action("fold"), Action("call", 55), Action("raise")])
    adv = advise(st)
    assert "open" not in adv.reason.lower()
    assert adv.action == "fold"


def test_board_cards_are_all_the_same_size():
    """Your cards, cut by your picture's rim drawn over them, were found as three pieces
    (43, 15 and 71 pixels wide) and taken for the board. The middle of the table moved and
    every bet went to the wrong player."""
    from app.recognition.layout import split_cards
    from app.vision.card_recognizer import CardReading

    def card(x, w):
        return CardReading(code=None, guess=None, confidence=0.5, rank_confidence=0.5, suit_confidence=0.5,
                           box=(x, 546, w, 118))

    pieces = [card(656, 43), card(699, 15), card(714, 71)]
    hero, board, others = split_cards(pieces, 1440, 860)
    assert board == []


@needs_ocr
def test_your_all_in_status_is_not_a_button(rec):
    """You are all in: "All in" under "High Card" by your picture, near the bottom right. The
    lone-button rule took it for your action button: your turn on someone else's, and your
    seat lost."""
    view = table(all_in=(0,), bets={0: 200, 2: 162}, acting=2, button=0, hero_cards=("7d", "Qd"))
    res, seats = read(rec, view, "avatars")
    assert res.state.hero_to_act.value is not True
    assert 0 in seats and seats[0].is_hero
