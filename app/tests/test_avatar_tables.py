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
from app.tests.demo_table import SeatView, TableView, for_players, layouts, render
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


def test_a_chip_icon_glued_to_the_bet():
    """Self-test round 6 (stock): the chip icon read as a letter stuck to the number, "C210".
    The leftover "C" made it no amount, and the top seat's bet of 210 came back as nothing."""
    assert parse_amount("C210").value == 210
    assert parse_amount("©70").value == 70
    assert parse_amount("c1,550").value == 1550
    assert parse_amount("C$2,100").value == 2100
    # a name or a card is not an amount: one digit, or letters after it
    assert parse_amount("Q9") is None
    assert parse_amount("C3PO") is None


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
def test_cards_shown_on_the_boards_line_are_not_the_board(rec):
    """Showdown (self-test round 6): the player at the left side shows his cards on the board's
    line, smaller. Seven cards in a row were no board at all, and the board cards were then
    given to the nearest player: the folded player at the top was read as still in."""
    board = ("Qd", "8s", "Ad", "Ac", "Jc")
    view = table(folded=(0, 3, 4, 5), hero_cards=(), board=board, collected=390, button=1,
                 shown={2: ("5h", "5c"), 1: ("9c", "Ah")})
    res, seats = read(rec, view, "avatars")
    assert len(res.layout.board) == 5 and len(res.layout.other_cards) == 4
    assert [seats[i].has_cards for i in (1, 2, 3, 4, 5)] == [True, True, False, False, False]


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


@needs_ocr
def test_the_blinds_come_from_the_chips_the_blinds_posted(rec):
    """No stakes printed on this table: the small and big blind's chips (25$ and 50$) are the
    blinds, so the big blind's own chips are no raise and a raise has an amount in chips."""
    view = table(bets={4: 5, 5: 10}, folded=(1, 2), button=3, acting=0, hero_cards=("Kh", "Qs"),
                 buttons=["Fold", "Call 50$", "Raise"])
    res, seats = read(rec, view, "avatars")
    assert tuple(res.state.blinds.value) == (25, 50)
    from app.poker.advice import advise
    adv = advise(res.state)
    assert adv.action == "raise" and adv.amount is not None


# ------------------------------------------------------------------ eight players
NAMES8 = NAMES + ["Ines", "Otto"]


def read8(rec, layout, stacks, bets=None, folded=(), button=5, buttons=(), acting=None, hero_cards=("8c", "2d"),
          board=(), collected=0.0, shown=None, timer_left=0.6):
    """Eight players on a layout's seat spots (Kevin: "it also needs to be trained on an 8
    people table"): the reading and its seats keyed by screen seat."""
    lay = for_players(LAY[layout], 8)
    bets, shown = bets or {}, shown or {}
    seats = [SeatView(name, stacks[i], bets.get(i, 0.0), has_cards=i not in folded, shown=shown.get(i))
             for i, name in enumerate(NAMES8)]
    view = TableView(seats, list(hero_cards), list(board), collected, button, acting, list(buttons), hand_no=7,
                     timer_left=timer_left)
    img, meta = render(view, lay)
    res = rec.recognize(img)
    plates = meta["plates"]

    def seat_of(center):
        return min(range(len(plates)), key=lambda i: (plates[i][0] - center[0]) ** 2 + (plates[i][1] - center[1]) ** 2)

    return res, {seat_of(s.center): s for s in res.layout.seats}, lay.unit


def test_a_coin_icon_before_the_currency_sign():
    """8-player phone table: the coin before a stack read as a "+" ("+$ 19700"), so the stack
    was no amount and the seat was lost; every position after it moved one seat."""
    assert parse_amount("+$ 19700").value == 19700
    assert parse_amount("·$ 5").value == 5
    assert parse_amount("+30") is None  # a time bank is no amount


@needs_ocr
def test_eight_on_a_phone_table(rec):
    """8-player self-test, phone table, before the flop: the small blind's bet beside the next
    seat's name was taken for a level, a coin icon read as "+" lost a seat, and card backs lying
    across the table's rim were missed. You (under the gun) were read as the big blind and told
    to CHECK over a Call 200 button."""
    stacks = [194, 207.5, 189, 400, 184, 197, 197, 218.5]
    res, seats, unit = read8(rec, "portrait", stacks, bets={6: 1, 7: 2}, button=5, acting=0,
                             buttons=["Fold", "Call 2", "Raise"])
    assert sorted(seats) == list(range(8))
    assert [bet(seats[i]) for i in (5, 6, 7)] == [0, 1 * unit, 2 * unit]
    assert all(seats[i].has_cards for i in range(1, 8))
    positions = {p.seat: p.position.value for p in res.state.players}
    hero = next(p for p in res.state.players if p.is_hero)
    assert hero.position.value == "UTG", positions


@needs_ocr
def test_eight_round_pictures_the_top_stack_is_not_the_pot(rec):
    """8-player self-test, round pictures, between hands: the top seat's stack sits on the
    table's rim, and with no pot on the felt it was taken for the pot. That seat was lost and
    every position after it moved one seat."""
    stacks = [192, 240.5, 189, 400, 157, 197, 197, 217.5]
    res, seats, unit = read8(rec, "avatars", stacks, button=7, folded=range(8), hero_cards=())
    assert sorted(seats) == list(range(8))
    assert seats[4].stack.value == 157 * unit
    assert res.state.pot.value is None


@needs_ocr
def test_eight_backs_on_the_far_side_of_the_picture(rec):
    """8-player self-test, round pictures: a seat on the right has its backs on the left of its
    picture, further out than the name is wide. The search beside the name cut the outer card
    off, and the inner one, between the picture and the timer ring round it (most of his time
    left), was no clean card: the player read as folded on their turn."""
    stacks = [191, 290.5, 191, 361, 129, 176, 194, 239.5]
    res, seats, unit = read8(rec, "avatars", stacks, folded=(0, 1, 2, 4, 5, 7), button=2, acting=6, hero_cards=(),
                             board=("7s", "Js", "Qc"), collected=18, timer_left=0.9)
    assert sorted(seats) == list(range(8))
    assert seats[6].has_cards is True  # Ines, to act
    assert seats[3].has_cards is True
    assert [seats[i].has_cards for i in (1, 2, 4, 5, 7)] == [False] * 5


@needs_ocr
def test_eight_shown_cards_stay_together(rec):
    """8-player self-test, showdown: Quinn's second card lies nearer Jasper's name than Quinn's,
    and one card at a time it made Jasper, who had folded, a player still in."""
    stacks = [199, 198, 192, 200, 192, 200, 200, 192]
    shown = {2: ("Tc", "Qc"), 4: ("Ah", "5c"), 7: ("9h", "Ac")}
    res, seats, unit = read8(rec, "stock", stacks, folded=(0, 1, 3, 5, 6), button=7, hero_cards=(),
                             board=("6h", "7c", "Jc", "Ks", "4s"), collected=27, shown=shown)
    assert sorted(seats) == list(range(8))
    assert [seats[i].has_cards for i in (2, 4, 7)] == [True, True, True]
    assert seats[3].has_cards is False  # Jasper folded


@needs_ocr
def test_eight_a_bet_goes_to_its_own_seat_on_the_flop(rec):
    """8-player self-test, stock table, on the flop: the three cards dealt fill the board's left
    places, and taken for the table's middle they put it one card to the left. Otto's bet then
    lay a little nearer the line from Ines (folded) to that middle than his own, and went to her:
    two bets counted for one and the pot came out 140 too big."""
    stacks = [192, 207.5, 194, 376, 154, 176, 199, 239.5]
    res, seats, unit = read8(rec, "stock", stacks, bets={1: 14, 7: 14}, folded=(2, 3, 4, 5, 6), button=6, acting=0,
                             hero_cards=("Kh", "8h"), board=("3s", "Th", "Qs"), collected=24,
                             buttons=["Fold", "Call 14", "Raise"])
    assert sorted(seats) == list(range(8))
    assert [bet(seats[i]) for i in (1, 6, 7)] == [14 * unit, 0, 14 * unit]


@needs_ocr
def test_a_blind_beside_a_stack_is_a_bet_by_its_chip(rec):
    """The eight-player phone table drawn in another font (DejaVu, as on a machine without
    Inter): the OCR loses the "$" beside the big blind's chip and reads a bare "200". On the
    line of the next seat's stack, with no currency sign, it was dropped as a level number, and
    the big blind had no bet. The chip picture just before it makes it a bet."""
    import dataclasses

    from app.tests.synthetic import find_font

    lay = dataclasses.replace(for_players(LAY["portrait"], 8), text_font=find_font("DejaVuSans.ttf"))
    stacks = [194, 207.5, 189, 400, 184, 197, 197, 218.5]
    bets = {6: 1, 7: 2}
    seats = [SeatView(name, stacks[i], bets.get(i, 0.0)) for i, name in enumerate(NAMES8)]
    view = TableView(seats, ["8c", "2d"], [], 0.0, 5, 0, ["Fold", "Call 2", "Raise"], hand_no=7, timer_left=0.6)
    img, meta = render(view, lay)
    res = rec.recognize(img)
    plates = meta["plates"]
    seat = {min(range(8), key=lambda i: (plates[i][0] - s.center[0]) ** 2 + (plates[i][1] - s.center[1]) ** 2): s
            for s in res.layout.seats}
    assert [bet(seat[i]) for i in (5, 6, 7)] == [0, 1 * lay.unit, 2 * lay.unit]


def test_a_plate_end_or_a_wide_colon_beside_an_amount():
    """Self-test with the tables drawn in another font (DejaVu): the OCR read the rounded end
    of a stack plate as a bracket ("[1,136$"), the "$" before a bet as a full-width colon
    ("：1300") and the coin before a stack as an O ("O$ 19700"). None was an amount, so a seat
    was lost or your own bet was missed."""
    assert parse_amount("[1,136$").value == 1136
    assert parse_amount("(1,185$").value == 1185
    assert parse_amount("904$)").value == 904
    assert parse_amount("：1300").value == 1300
    assert parse_amount("O$ 19700").value == 19700
    assert parse_amount("(3)") is None  # brackets on both sides: not a plate's end
    assert parse_amount("O") is None
    # eight-player stock table: the second read of "$ 3,940" had a gap after the comma, so no
    # two reads agreed and the stack was left unknown
    assert parse_amount("$ 3, 940").value == 3940
    assert parse_amount("3, 94") is None


@needs_ocr
def test_round_pictures_in_another_font_keep_every_seat(rec):
    """Six-player self-test, round pictures drawn in DejaVu: two stacks were read with the
    plate's rounded end as a bracket ("[1,136$", "(1,185$"). One seat had no stack and the
    other was lost, so every position after it moved one seat."""
    import dataclasses

    from app.tests.synthetic import find_font

    lay = dataclasses.replace(LAY["avatars"], text_font=find_font("DejaVuSans.ttf"))
    stacks = [180.8, 237, 329, 227.2, 178, 197]
    seats = [SeatView(name, stacks[i], 0.0, has_cards=i in (2, 3)) for i, name in enumerate(NAMES)]
    view = TableView(seats, [], ["Th", "5h", "Kh"], 16.0, 1, 2, [], hand_no=7, timer_left=0.6)
    img, meta = render(view, lay)
    res = rec.recognize(img)
    plates = meta["plates"]
    seat = {min(range(6), key=lambda i: (plates[i][0] - s.center[0]) ** 2 + (plates[i][1] - s.center[1]) ** 2): s
            for s in res.layout.seats}
    assert sorted(seat) == list(range(6))
    assert [seat[i].stack.value for i in range(6)] == [s * lay.unit for s in stacks]
    positions = {p.seat: p.position.value for p in res.state.players}
    assert [positions[i] for i in range(6)] == ["CO", "BTN", "SB", "BB", "UTG", "HJ"], positions


@needs_ocr
def test_a_turn_ring_hugging_a_picture_in_another_font(rec):
    """Six-player self-test, phone table drawn in DejaVu: with 6 seconds left the turn ring is
    a short arc hugging the picture, and the name touches the picture's top. A circle a few
    pixels too big (on the ring, the name and the stack plate) matched as well as the picture's
    own outline and was kept, so the ring lay inside it and went unseen. Nobody was acting,
    and you were shown a move on Panther's turn."""
    import dataclasses

    from app.tests.synthetic import find_font

    lay = dataclasses.replace(LAY["portrait"], text_font=find_font("DejaVuSans.ttf"))
    stacks = [175.5, 206, 312, 269.5, 352, 188]
    bets = {0: 2.0, 5: 1.0}
    seats = [SeatView(name, stacks[i], bets.get(i, 0.0)) for i, name in enumerate(NAMES)]
    view = TableView(seats, ["As", "Qh"], [], 0.0, 4, 1, [], hand_no=16, timer_left=0.42)
    img, meta = render(view, lay)
    res = rec.recognize(img)
    plates = meta["plates"]
    acting = res.layout.seats[res.layout.acting_seat] if res.layout.acting_seat is not None else None
    assert acting is not None, res.layout.warnings
    x, y = acting.center
    assert min(range(6), key=lambda i: (plates[i][0] - x) ** 2 + (plates[i][1] - y) ** 2) == 1


@needs_ocr
def test_a_bet_beside_a_folded_stack_with_its_dollar_lost(rec):
    """Eight-player self-test, phone table drawn in DejaVu: Otto's bet ("$ 800", chip first)
    lies beside folded Ines's stack. The OCR read "800" without its "$", so the chip was a
    sign's width before the number: too far for the chip check, and the bet was taken for a
    level and dropped (53 bets wrong in that run)."""
    import dataclasses

    from app.tests.demo_table import amount_text
    from app.tests.synthetic import find_font

    lay = dataclasses.replace(for_players(LAY["portrait"], 8), text_font=find_font("DejaVuSans.ttf"))
    stacks = [199, 198, 192, 200, 192, 200, 200, 192]
    bets = {0: 1, 1: 2, 2: 8, 4: 8, 7: 8}
    seats = [SeatView(name, stacks[i], bets.get(i, 0.0), has_cards=i not in (3, 5, 6))
             for i, name in enumerate(NAMES8)]
    view = TableView(seats, ["Th", "Qd"], [], 0.0, 7, 0, ["Fold", "Call " + amount_text(7, lay), "Raise"],
                     hand_no=1, timer_left=0.48)
    img, meta = render(view, lay)
    res = rec.recognize(img)
    plates = meta["plates"]
    seat = {min(range(8), key=lambda i: (plates[i][0] - s.center[0]) ** 2 + (plates[i][1] - s.center[1]) ** 2): s
            for s in res.layout.seats}
    assert sorted(seat) == list(range(8))
    assert [bet(seat[i]) for i in range(8)] == [bets.get(i, 0) * lay.unit for i in range(8)]


@needs_ocr
def test_eight_stacks_in_another_font_on_the_stock_table(rec):
    """Eight-player self-test, stock table drawn in DejaVu: a stack's second read came back as
    "$ 3, 940" (a gap after the comma), no two reads agreed, and the stack was left unknown
    (65 times in that run)."""
    import dataclasses

    from app.tests.synthetic import find_font

    lay = dataclasses.replace(for_players(LAY["stock"], 8), text_font=find_font("DejaVuSans.ttf"))
    stacks = [200, 290.5, 194, 394, 180, 210, 205, 199]
    seats = [SeatView(name, stacks[i], 0.0) for i, name in enumerate(NAMES8)]
    view = TableView(seats, ["As", "Kd"], [], 0.0, 5, None, [], hand_no=14, timer_left=0.6)
    img, meta = render(view, lay)
    res = rec.recognize(img)
    assert [p.stack.value for p in res.state.players] == [s * lay.unit for s in stacks]


@needs_ocr
def test_a_bet_whose_dollar_reads_as_a_colon_is_confirmed(rec):
    """Eight-player self-test, phone table drawn in DejaVu: Otto's call of 800 (no "$" in the
    first read) starts with an 8, which on a table full of "$" amounts may be a "$" read as an 8.
    So only re-reads showing the sign counted, and the one that read it as "：800" didn't: no
    two reads agreed and the bet was unknown. The chips then didn't add up, the blinds went
    unknown, Panther's raise to 800 was taken for the big blind, and K-8 suited in the big blind
    was told to fold."""
    import dataclasses

    from app.tests.demo_table import amount_text
    from app.tests.synthetic import find_font

    lay = dataclasses.replace(for_players(LAY["portrait"], 8), text_font=find_font("DejaVuSans.ttf"))
    stacks = [198, 221.5, 194, 376, 154, 176, 199, 253.5]
    bets = {0: 2, 1: 8, 7: 8}
    seats = [SeatView(name, stacks[i], bets.get(i, 0.0), has_cards=i not in (2, 3, 4, 5, 6))
             for i, name in enumerate(NAMES8)]
    view = TableView(seats, ["Kh", "8h"], [], 0.0, 6, 0, ["Fold", "Call " + amount_text(6, lay), "Raise"],
                     hand_no=16, timer_left=0.84)
    img, meta = render(view, lay)
    res = rec.recognize(img)
    plates = meta["plates"]
    by_seat = {}
    for p in res.state.players:
        x, y = p.anchor if p.anchor else (None, None)
        if p.is_hero:
            by_seat[0] = p
        elif x is not None:
            by_seat[min(range(8), key=lambda i: (plates[i][0] - x) ** 2 + (plates[i][1] - y) ** 2)] = p
    assert by_seat[7].bet.known and by_seat[7].bet.value == 8 * lay.unit
