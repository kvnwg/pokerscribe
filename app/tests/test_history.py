"""The betting so far in a hand, kept from read to read (app/poker/history.py)."""
import pytest

from app.poker.history import HERO, OTHER, VILLAIN, BettingRecord, Line, StreetLine
from app.poker.profiles import Profiles
from app.state.model import GameState

from .test_advice import table

FLOP = ["Ac", "8d", "5c"]
TURN = FLOP + ["2h"]
RIVER = TURN + ["Js"]
HEADS_UP = ["SB", "UTG", "HJ", "CO"]  # folded: the hero in the big blind against the button


def read(board=(), bets=None, pot=0.0, folded=HEADS_UP, **kw):
    """One read of the table: blinds 5/10, hero in the big blind."""
    return table(["Ah", "Kd"], "BB", board, bets=bets or {}, pot=pot, folded=folded, **kw)


def feed(record, *reads, hand=1):
    for st in reads:
        record.update(st, hand)
    return record.line(reads[-1])


# ------------------------------------------------------------ before the flop
def test_their_raise_before_the_flop():
    # the button raises to 25 (2.5 big blinds), the hero calls: the call is never seen
    line = feed(BettingRecord(),
                read(bets={"SB": 5, "BB": 10}, folded=["UTG", "HJ", "CO"]),
                read(bets={"SB": 5, "BB": 10, "BTN": 25}, folded=["UTG", "HJ", "CO"]),
                read(FLOP, pot=55))
    assert line.preflop == StreetLine(2.5, VILLAIN)


def test_your_raise_before_the_flop():
    line = feed(BettingRecord(),
                read(bets={"SB": 5, "BB": 10, "BTN": 10}, folded=["UTG", "HJ", "CO"]),  # the button only called
                read(bets={"SB": 5, "BB": 40, "BTN": 10}, folded=["UTG", "HJ", "CO"]),  # the hero raised to 40
                read(FLOP, pot=85))
    assert line.preflop == StreetLine(4.0, HERO)


def test_nobody_raised_before_the_flop():
    line = feed(BettingRecord(), read(bets={"SB": 5, "BB": 10, "BTN": 10}, folded=["UTG", "HJ", "CO"]),
                read(FLOP, pot=25))
    assert line.preflop == StreetLine(1.0, None)


def test_a_raise_by_someone_who_folded_later():
    # the cutoff raised to 30, the button and the hero called; the cutoff folded on the flop
    line = feed(BettingRecord(),
                read(bets={"SB": 5, "BB": 10, "CO": 30}, folded=["UTG", "HJ"]),
                read(bets={"SB": 5, "BB": 10, "CO": 30, "BTN": 30}, folded=["UTG", "HJ"]),
                read(FLOP, pot=95, folded=["SB", "UTG", "HJ"]),
                read(TURN, pot=95))
    assert line.preflop == StreetLine(3.0, OTHER)


def test_no_big_blind_no_size_before_the_flop():
    line = feed(BettingRecord(), read(bets={"BB": 10, "BTN": 25}, blinds=None), read(FLOP, pot=55, blinds=None))
    assert line.preflop == StreetLine()


# --------------------------------------------------------------- flop and turn
def test_their_bet_is_a_share_of_the_pot_the_round_began_with():
    # 30 into 55 on the flop, then the turn is checked through
    line = feed(BettingRecord(), read(FLOP, {"BTN": 30}, pot=55), read(TURN, pot=115), read(RIVER, pot=115))
    assert line.flop == StreetLine(pytest.approx(30 / 55), VILLAIN)
    assert line.turn == StreetLine(0.0, None)


def test_your_bet_seen_before_their_call():
    line = feed(BettingRecord(), read(FLOP, pot=55), read(FLOP, {"BB": 40}, pot=55),
                read(FLOP, {"BB": 40, "BTN": 40}, pot=55), read(TURN, pot=135))
    assert line.flop == StreetLine(pytest.approx(40 / 55), HERO)


def test_your_bet_first_seen_together_with_their_call_is_still_yours():
    # you only ever call after a read that shows their bet alone, so this was your bet
    line = feed(BettingRecord(), read(FLOP, pot=55), read(FLOP, {"BB": 40, "BTN": 40}, pot=55), read(TURN, pot=135))
    assert line.flop.aggressor == HERO


def test_a_raise_takes_the_round():
    # the hero bets 40, the button raises to 120, the hero calls
    line = feed(BettingRecord(), read(FLOP, {"BB": 40}, pot=55), read(FLOP, {"BB": 40, "BTN": 120}, pot=55),
                read(TURN, pot=295))
    assert line.flop == StreetLine(pytest.approx(120 / 55), VILLAIN)


def test_a_bet_by_someone_who_folded_later():
    three = ["SB", "UTG", "HJ"]  # the cutoff is still in on the flop
    line = feed(BettingRecord(), read(FLOP, {"CO": 30}, pot=85, folded=three),
                read(FLOP, {"CO": 30, "BTN": 30}, pot=85, folded=three), read(TURN, pot=175, folded=three),
                read(TURN, {"BB": 90}, pot=175, folded=three), read(RIVER, pot=355))
    assert line.flop == StreetLine(pytest.approx(30 / 85), OTHER)
    assert line.turn == StreetLine(pytest.approx(90 / 175), HERO)


def test_two_opponents_first_seen_level_is_not_known():
    three = ["SB", "UTG", "HJ"]
    line = feed(BettingRecord(), read(FLOP, {"CO": 30, "BTN": 30}, pot=85, folded=three), read(TURN, pot=175))
    assert line.flop == StreetLine(pytest.approx(30 / 85), None)


def test_a_round_without_a_read_stays_unknown():
    # watching began on the turn
    line = feed(BettingRecord(), read(TURN, {"BTN": 50}, pot=100), read(RIVER, pot=200))
    assert (line.preflop, line.flop) == (StreetLine(), StreetLine())
    assert line.turn == StreetLine(0.5, VILLAIN) and not line.empty


def test_a_pot_that_includes_the_bets():
    # the client's pot already holds this round's bets: 85 with their 30 means the round began at 55
    line = feed(BettingRecord(), read(FLOP, {"BTN": 30}, pot=85, includes_bets=True), read(TURN, pot=115))
    assert line.flop.size == pytest.approx(30 / 55)


def test_unread_bets_leave_the_round_unknown():
    st = read(FLOP, {"BTN": 30}, pot=55)
    for p in st.players:
        if not p.is_hero:
            p.bet.value = None
    assert feed(BettingRecord(), st, read(TURN, pot=115)).flop == StreetLine()


# --------------------------------------------------------------------- hands
def test_a_new_hand_starts_a_new_record():
    record = BettingRecord()
    feed(record, read(FLOP, {"BTN": 30}, pot=55), read(TURN, pot=115))
    line = feed(record, read(TURN, pot=80), hand=2)
    assert line.flop == StreetLine() and line.turn == StreetLine(0.0, None)


def test_without_hand_numbers_a_shorter_board_starts_a_new_record():
    record = BettingRecord()
    for st in (read(FLOP, {"BTN": 30}, pot=55), read(TURN, pot=115), read(bets={"BB": 10, "BTN": 25}),
               read(FLOP, pot=55)):
        record.update(st)
    line = record.line(read(FLOP, pot=55))
    assert line.preflop == StreetLine(2.5, VILLAIN) and line.flop == StreetLine(0.0, None)
    assert line.turn == StreetLine()


def test_no_line_with_two_opponents_left_or_nothing_recorded():
    record = BettingRecord()
    assert record.line(read(RIVER, pot=100)) is None
    record.update(read(RIVER, pot=100, folded=["SB", "UTG", "HJ"]), 1)
    assert record.line(read(RIVER, pot=100, folded=["SB", "UTG", "HJ"])) is None
    assert record.line(read(RIVER, pot=100)) is not None


# ------------------------------------------------------------------ the river
def test_the_rivers_bets_in_order():
    record = BettingRecord()
    line = feed(record, read(RIVER, pot=200))
    assert line.river == ()
    line = feed(record, read(RIVER, {"BTN": 50}, pot=200))
    assert line.river == ((VILLAIN, 50.0),)
    line = feed(record, read(RIVER, {"BTN": 50, "BB": 150}, pot=200), read(RIVER, {"BTN": 400, "BB": 150}, pot=200))
    assert line.river == ((VILLAIN, 50.0), (HERO, 150.0), (VILLAIN, 400.0))


def test_a_missed_river_read_is_not_guessed():
    # their bet of 50 was never seen: 150 then 400 could be a bet and a raise, or more
    line = feed(BettingRecord(), read(RIVER, pot=200), read(RIVER, {"BTN": 400, "BB": 150}, pot=200))
    assert line.river == ((HERO, 150.0), (VILLAIN, 400.0))  # the shortest story, and it takes turns
    two_of_theirs = feed(BettingRecord(), read(RIVER, {"BTN": 50}, pot=200), read(RIVER, {"BTN": 400}, pot=200))
    assert two_of_theirs.river is None
    assert feed(BettingRecord(), read(TURN, pot=100)).river is None


# -------------------------------------------------------------------- wording
def test_line_in_words():
    line = Line(StreetLine(2.5, VILLAIN), StreetLine(0.66, VILLAIN), StreetLine(0.0, None))
    assert line.describe() == ("before the flop they raised to 2.5 big blinds; on the flop they bet 66% of the pot; "
                               "the turn was checked")
    assert Line(StreetLine(1.0), StreetLine(), StreetLine(0.5, HERO)).describe() == (
        "nobody raised before the flop; on the turn you bet 50% of the pot")
    assert Line().describe() == "" and Line().empty
    assert StreetLine(0.5, HERO).swapped() == StreetLine(0.5, VILLAIN)
    assert StreetLine(0.5, OTHER).swapped() == StreetLine(0.5, OTHER)


# ------------------------------------------------- carried by the profiles
def test_profiles_put_the_line_on_the_river_state_only():
    prof = Profiles()
    reads = [read(bets={"SB": 5, "BB": 10, "BTN": 25}, folded=["UTG", "HJ", "CO"]), read(FLOP, {"BTN": 30}, pot=55),
             read(TURN, pot=115), read(RIVER, {"BTN": 60}, pot=115)]
    for st in reads:
        prof.update(st, None, 1)
        prof.annotate(st)
    assert all(st.betting is None for st in reads[:3])
    line = reads[3].betting
    assert (line.preflop, line.turn) == (StreetLine(2.5, VILLAIN), StreetLine(0.0, None))
    assert line.flop == StreetLine(pytest.approx(30 / 55), VILLAIN) and line.river == ((VILLAIN, 60.0),)
    # a new hand: nothing from the last one
    nxt = read(RIVER, pot=80)
    prof.update(nxt, None, 2)
    prof.annotate(nxt)
    assert nxt.betting.flop == StreetLine()


def test_the_line_is_never_saved_or_exported():
    st = read(RIVER, pot=115)
    st.betting = Line(StreetLine(2.5, VILLAIN))
    saved = st.to_json()
    assert "betting" not in saved and "villain" not in str(saved)
    assert GameState.from_json(saved).betting is None
