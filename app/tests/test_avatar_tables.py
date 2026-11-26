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
          stacks: Optional[Dict[int, float]] = None, timer_left: float = 0.6, shown=None) -> TableView:
    bets, stacks, shown = bets or {}, stacks or {}, shown or {}
    seats = []
    for i, name in enumerate(NAMES):
        stack = 0.0 if i in all_in else stacks.get(i, 200.0 - bets.get(i, 0.0))
        seats.append(SeatView(name, stack, bets.get(i, 0.0), has_cards=i not in folded, all_in=i in all_in,
                              shown=shown.get(i)))
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


# -------------------------------------------------- round 4 (seed 23) misreads
@needs_ocr
def test_plain_grey_card_backs_beside_pictures(rec):
    """Dark grey card backs, no colour: only backs with colour counted, so on the phone table
    every opponent looked folded (or, when one was found, the rest did). One pair sits where
    the felt turns from green to the dark surround, one is touched by the timer ring."""
    for acting in (0, 3):
        view = table(folded=(2, 5), bets={1: 6, 4: 47}, all_in=(4,), board=("Ks", "7d", "2h"), collected=24,
                     button=3, acting=acting, buttons=["Fold", "Call $41", "Raise"] if acting == 0 else [])
        res, seats = read(rec, view, "portrait")
        assert [seats[i].has_cards for i in (1, 2, 3, 4, 5)] == [True, False, True, True, False], acting


@needs_ocr
def test_the_table_rim_is_not_card_backs(rec):
    """The brown rim of the table runs under the top player's name. Cut by the name and the
    stack into short straight pieces, it looked like card backs: a folded player stayed in."""
    view = table(folded=(3,), bets={0: 1, 1: 2, 2: 2}, button=5, acting=4, hero_cards=("2s", "8h"))
    res, seats = read(rec, view, "stock")
    assert seats[3].has_cards is False
    assert [seats[i].has_cards for i in (1, 2, 4, 5)] == [True, True, True, True]


@needs_ocr
def test_an_opponents_cards_at_showdown_are_not_yours(rec):
    """You folded; at showdown a player near the bottom turns his cards face up. They were
    taken for yours, so his seat became yours (your stack read as his, positions shifted)."""
    board = ("6h", "3c", "6c", "8h", "Ts")
    for layout, opp in (("avatars", 1), ("stock", 5)):
        view = table(folded=(0, 3, 4), hero_cards=(), board=board, collected=17, button=5,
                     shown={opp: ("Jd", "Ks"), 2: ("As", "9h")})
        res, seats = read(rec, view, layout)
        assert seats[0].is_hero and not seats[opp].is_hero, layout
        assert res.layout.hero_cards == [], layout
        assert seats[0].stack.value == 200 * LAY[layout].unit, layout


@needs_ocr
def test_the_dealer_button_beside_a_level_badge(rec):
    """The dealer button and the level badge on the picture's rim were read as one word,
    "D19". The button was dropped from the wrong end, the D repaired as a 0: a bet of 1."""
    view = table(bets={0: 1, 1: 2, 2: 2, 5: 7}, folded=(3, 4), button=5, acting=0, hero_cards=("2s", "8h"),
                 buttons=["Fold", "Call 30$", "Raise"])
    res, seats = read(rec, view, "avatars")
    assert bet(seats[5]) == 35
    assert res.state.to_call.value == 30


@needs_ocr
def test_your_hand_strength_is_not_your_name(rec):
    """"High Card" beside your picture, over your stack, was taken for your name."""
    res, seats = read(rec, table(bets={0: 1, 1: 2}, button=5, acting=0, hero_cards=("2s", "8h"),
                                 buttons=["Fold", "Call 5$", "Raise"]), "avatars")
    assert seats[0].name == "You"


@needs_ocr
def test_a_short_timer_ring_is_still_their_turn(rec):
    """Little time left: the ring round the acting player's picture is a short arc. The rim
    of the table beside your stack and the red suits on your cards counted as a highlight on
    your seat too, so neither stood out, and you were shown a move on their turn."""
    for layout, acting, left in (("stock", 4, 0.25), ("stock", 4, 0.12), ("portrait", 2, 0.2)):
        view = table(bets={0: 1, 1: 2, 2: 2}, stacks={0: 224}, button=5, acting=acting, hero_cards=("Ah", "Ac"),
                     timer_left=left)
        res, seats = read(rec, view, layout)
        assert res.layout.acting_seat is not None, layout
        assert res.layout.seats[res.layout.acting_seat] is seats[acting], layout
        assert res.state.hero_to_act.value is not True, layout


# -------------------------------------------------- round 5 (seed 24) misreads
def test_a_comma_read_as_a_point():
    """"2,035$": the small comma was read as a point, a stack of 2.035. Money never has
    three digits after the point, so that point separates thousands (as in Europe)."""
    assert parse_amount("2.035$").value == 2035
    assert parse_amount("$1.250").value == 1250
    assert parse_amount("12.50").value == 12.5
    assert parse_amount("0.035").value == 0.035


def test_a_chip_icon_read_as_a_zero():
    """A bet drawn beside a stack of chips: OCR read the chips as a "0", "0 210", and two
    numbers in one box are no amount. Marlow's bet of 210 came back as nothing."""
    assert parse_amount("0 210").value == 210
    assert parse_amount("o 630").value == 630
    assert parse_amount("@ $ 40").value == 40
    assert parse_amount("10 20") is None
    assert parse_amount("0").value == 0


@needs_ocr
def test_face_up_cards_at_showdown_are_still_in_the_hand(rec):
    """Showdown: the players left turn their cards face up. With no card backs anywhere,
    a player showing his cards was read as folded, and the dealer button beside a folded
    player's picture passed for grey card backs."""
    board = ("7h", "Ts", "5c", "Qs", "Kh")
    view = table(folded=(0, 1, 2, 3), hero_cards=(), board=board, collected=211, button=3, all_in=(4,),
                 shown={4: ("Jd", "Js"), 5: ("Ad", "9d")})
    res, seats = read(rec, view, "avatars")
    assert [seats[i].has_cards for i in (1, 2, 3, 4, 5)] == [False, False, False, True, True]


@needs_ocr
def test_the_dealer_button_between_hands_is_not_card_backs(rec):
    """Between hands nobody has cards. The dealer button beside a picture, a solid disc
    differing from the felt, passed for plain grey card backs: that player looked in."""
    for button in (1, 3):
        view = table(folded=(0, 1, 2, 3, 4, 5), hero_cards=(), button=button)
        res, seats = read(rec, view, "avatars")
        assert not any(seats[i].has_cards for i in (1, 2, 3, 4, 5)), button


def test_your_seat_when_your_name_is_not_read():
    """"You" is drawn across the edge of the table and OCR missed it: your seat was lost and
    the player beside you (lower right) taken for you. A CALL instead of a RAISE followed."""
    from app.vision.card_recognizer import CardReading

    def card(code, x):
        return CardReading(code=code, guess=code, confidence=0.95, rank_confidence=0.95, suit_confidence=0.95,
                           box=(x, 546, 61, 87))

    W, H = 1440, 860
    boxes = [TextBox("$ 1,600", 0.8, 682, 693, 76, 24),  # your stack; your name above it was not read
             TextBox("10", 0.9, 738, 517, 24, 20)]  # your bet
    for name, x, y, stack in (("Marlow", 245, 583, "$ 1,740"), ("Quinn", 245, 291, "$ 1,970"),
                              ("Jasper", 720, 153, "$ 1,750"), ("Rhea", 1195, 291, "$ 4,100"),
                              ("Toby", 979, 704, "$ 2,020")):
        boxes.append(TextBox(name, 0.85, x - 35, y - 12, 70, 26))
        boxes.append(TextBox(stack, 0.85, x - 40, y + 15, 80, 24))
    res = analyse(np.zeros((H, W, 3), np.uint8), [card("Qh", 656), card("Kd", 724)], boxes)
    hero = next(s for s in res.seats if s.is_hero)
    assert hero.stack.value == 1600
    assert hero.bet is not None and hero.bet.value == 10
    assert len(res.seats) == 6


@needs_ocr
def test_a_dim_picture_between_hands_is_still_a_seat(rec):
    """Between hands every picture is dimmed. The circle finder settled on a wrong, larger
    circle round one of them (radius 57, not 34), so that picture, and with it the seat
    (name above, stack below), was lost: every position after it shifted."""
    view = table(folded=(0, 1, 2, 3, 4, 5), hero_cards=(), button=0,
                 stacks={0: 138, 1: 254, 2: 197, 3: 156, 4: 407, 5: 171})
    res, seats = read(rec, view, "portrait")
    assert sorted(seats) == [0, 1, 2, 3, 4, 5]
    assert seats[1].stack.value == 25400
