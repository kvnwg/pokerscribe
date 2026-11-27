"""Every bet and raise B0 says is one the table takes: at least the minimum (the biggest bet
plus the last raise, and at least one big blind), at most your chips. Going all in for less
than the minimum is allowed.

Found by the heads-up work (#21): in six-max, B0 said BET 1.5 into a pot of two big blinds,
under the minimum bet of one big blind (2 chips)."""
import os
import sys
from collections import defaultdict

import pytest

from app.poker import advice
from app.poker.advice import Advice, advise
from app.state.model import Action, Field

from .test_advice import table

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")
CHECK, BET = Action("check"), Action("bet")
SIX = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]


@pytest.fixture(scope="module")
def sim():
    sys.path.insert(0, TOOLS)
    try:
        import simulate
    finally:
        sys.path.remove(TOOLS)
    return simulate


# ------------------------------------------------------------------ the spot that was found
def test_the_bet_under_the_minimum_found_by_the_heads_up_work(sim):
    """Hand 665 of the six-max check run on fish247, 500 big blinds deep, seed 43
    (docs/research/runs/phase1_heads_up_b0.sh): the small blind completed, the big blind (B0,
    3d Ah) checked, and both checked the flop. On the turn the small blind checks again, and the
    `stab` rule bets a third of the 4-chip pot: 1.5, under the minimum bet of 2."""
    seats = [sim.Seat("app", 998.0, "You", ("3d", "Ah"), put_in=2.0)]
    for name in ("fish2474", "fish2471", "fish2473", "fish2472"):  # UTG, HJ, CO and the button folded
        seats.append(sim.Seat("fish247", 1000.0, name, ("2c", "2d"), folded=True, last=Action("fold"), acted=True))
    seats.append(sim.Seat("fish247", 998.0, "fish2470", ("4h", "4c"), put_in=2.0, last=Action("check"), acted=True))
    seats[1].cards, seats[2].cards, seats[3].cards, seats[4].cards = ("5s", "9d"), ("6c", "2s"), ("Js", "5d"), ("8d", "7d")
    h = sim.Hand(seats, button=4, board=["Kh", "3c", "9h", "Kd"], pot_before=4.0, current=0.0, min_raise=2.0)
    assert h.position(0) == "BB" and h.position(5) == "SB"

    adv = sim.decision(h, 0, None)
    assert (adv.action, adv.headline, adv.amount) == ("bet", "BET 2", 2.0)
    assert "They checked on a dry board" in adv.reason  # still the stab rule, at the smallest bet allowed
    assert "That's the smallest bet allowed." in adv.detail
    stats = {"problems": defaultdict(int), "examples": []}
    sim.check_advice(h, 0, adv, stats)
    assert not stats["problems"], dict(stats["problems"])


# ------------------------------------------------------------------ tiny pots
def checked_to(pot, stack=1000.0, blinds=(1, 2), conf=None, board=("Kh", "7c", "2d")):
    """B0 on the button after the flop, heads-up, checked to: stab territory on a dry board."""
    st = table(("Ah", "Td"), "BTN", board=board, stacks={"BTN": stack, "BB": 1000.0}, bets={},
               folded=["UTG", "HJ", "CO", "SB"], last={"BB": Action("check")}, pot=pot, to_call=0.0,
               actions=[CHECK, BET], blinds=blinds)
    if conf is not None:
        st.hero.stack = Field(stack, conf, "auto")
    return st


# stab: 0.33 of the pot. Equity fixed so the rule that bets is always the stab.
STAB = {"equity": [{"equity": 0.5, "stderr": 0.005}], "hand": "Ace high"}


@pytest.mark.parametrize("pot,blinds,want", [
    (4.0, (1, 2), 2.0),  # two big blinds: a third is 1.5, under the big blind
    (5.0, (1, 2), 2.0),  # 1.65 rounds to 1.5
    (6.0, (1, 2), 2.0),  # 1.98 rounds to 2: the minimum already
    (20.0, (5, 10), 10.0),  # 6.6 rounds to 6.5, under the big blind of 10
    (30.0, (5, 10), 10.0),  # 9.9 rounds to 10
    (40.0, (5, 10), 13.0),  # 13.2: over the minimum, unchanged
    (0.08, (0.02, 0.04), 0.04),  # cents: 0.0264 rounds to 0.03
])
def test_small_bets_in_small_pots_go_up_to_the_big_blind(pot, blinds, want):
    adv = advise(checked_to(pot, blinds=blinds), dict(STAB))
    assert (adv.action, adv.amount) == ("bet", want), adv.headline
    assert adv.headline == f"BET {advice.fmt_amount(want)}"
    raised = advice._chips(0.33 * pot) < blinds[1] - 1e-9  # the size before the fix
    assert ("That's the smallest bet allowed." in adv.detail) == raised


def test_a_bet_that_was_legal_is_left_alone():
    plain = advise(checked_to(100.0), dict(STAB))
    assert (plain.action, plain.headline, plain.amount, plain.detail) == ("bet", "BET 33", 33.0, "")


# ------------------------------------------------------------------ short stacks
def test_the_minimum_is_most_of_a_short_stack_so_all_in():
    # 3.5 behind: a third of the pot (1.5) wasn't half the stack, the minimum (2) is
    adv = advise(checked_to(4.0, stack=3.5), dict(STAB))
    assert (adv.action, adv.headline, adv.amount) == ("all-in", "ALL IN (3.5)", 3.5)
    assert "The smallest bet allowed, 2, is most of your chips." in adv.detail


def test_all_in_for_less_than_the_minimum_is_allowed():
    # 1.5 behind and the stack wasn't read reliably, so no ALL IN headline: the bet is all of it
    adv = advise(checked_to(4.0, stack=1.5, conf=0.5), dict(STAB))
    assert (adv.action, adv.amount) == ("bet", 1.5), adv.headline
    assert "is more than you have: all in for less is allowed" in adv.detail
    # read reliably, it says ALL IN
    adv = advise(checked_to(4.0, stack=1.5), dict(STAB))
    assert (adv.action, adv.amount) == ("all-in", 1.5)


# ------------------------------------------------------------------ the minimum itself
def spot(st):
    return advice._spot(st, {}, tuple(c.value for c in st.hero_cards), tuple(c.value for c in st.board))


@pytest.mark.parametrize("pos,bets,to_call,board,kind,want", [
    ("UTG", {"SB": 1, "BB": 2}, 2, (), "raise", 4),  # nobody raised: twice the big blind
    ("BB", {"SB": 1, "BB": 2}, 0, (), "raise", 4),  # the big blind's option
    ("BTN", {"SB": 1, "BB": 2, "UTG": 6}, 6, (), "raise", 10),  # an open to 6 raised by 4: at least 6 + 4
    ("BTN", {"SB": 1, "BB": 2, "UTG": 6, "HJ": 20}, 20, (), "raise", 34),  # a re-raise by 14
    ("BTN", {}, 0, ("Kh", "7c", "2d"), "bet", 2),  # a first bet: one big blind
    ("BTN", {"BB": 10}, 10, ("Kh", "7c", "2d"), "raise", 20),  # a bet of 10: raise to 20 at least
    ("BTN", {"BB": 1}, 1, ("Kh", "7c", "2d"), "raise", 3),  # under a big blind (an all-in): raise by 2
    ("BTN", {"BTN": 10, "BB": 30}, 20, ("Kh", "7c", "2d"), "raise", 50),  # your bet raised by 20
    ("BTN", {"UTG": 10, "HJ": 10}, 10, ("Kh", "7c", "2d"), "raise", 20),  # a bet and a call
])
def test_the_minimum_bet_or_raise(pos, bets, to_call, board, kind, want):
    st = table(("Ah", "Td"), pos, board=board, bets=bets, blinds=(1, 2), to_call=to_call, pot=10.0)
    assert advice._min_to(spot(st), kind) == want


def test_no_minimum_without_the_big_blind_or_a_bet():
    st = table(("Ah", "Td"), "BTN", board=("Kh", "7c", "2d"), bets={}, blinds=None, to_call=0.0, pot=10.0)
    assert advice._min_to(spot(st), "bet") is None


def test_a_bigger_bet_on_screen_when_there_is_nothing_to_call_is_ignored():
    # the Check button says nobody bet: a 50 read next to a player is a misread, not a bet to raise
    st = table(("Ah", "Td"), "BTN", board=("Kh", "7c", "2d"), bets={"BB": 50}, blinds=(1, 2), to_call=0.0,
               pot=10.0, actions=[CHECK, BET])
    assert advice._min_to(spot(st), "bet") == 2


# ------------------------------------------------------------------ raises, and any rule
def facing(bet, stack=1000.0):
    return table(("Ah", "Td"), "BTN", board=("Kh", "7c", "2d"), stacks={"BTN": stack}, bets={"BB": bet},
                 folded=["UTG", "HJ", "CO", "SB"], blinds=(1, 2), to_call=bet, pot=10.0 + bet,
                 actions=[Action("fold"), Action("call", bet), Action("raise")])


def test_a_raise_under_the_minimum_goes_up_to_it():
    # whatever made it (the river solver goes through the same check): facing 10, raising to 15
    # isn't allowed, 20 is
    s = spot(facing(10.0))
    adv = advice._legal_size(s, Advice("raise", "RAISE TO 15", "Raise.", amount=15.0, basis="solver", close=True))
    assert (adv.action, adv.headline, adv.amount, adv.basis, adv.close) == ("raise", "RAISE TO 20", 20.0, "solver", True)
    assert "That's the smallest raise allowed." in adv.detail


def test_a_bet_or_raise_over_the_stack_is_all_in():
    s = spot(facing(10.0, stack=150.0))
    adv = advice._legal_size(s, Advice("raise", "RAISE TO 400", "Raise.", amount=400.0))
    assert (adv.action, adv.headline, adv.amount) == ("all-in", "ALL IN (150)", 150.0)


def test_legal_amounts_and_other_instructions_pass_unchanged():
    s = spot(facing(10.0))
    for adv in (Advice("raise", "RAISE TO 30", "Raise.", amount=30.0), Advice("call", "CALL 10", "Call.", amount=10.0),
                Advice("raise", "RAISE TO 3X THEIR BET", "Raise."), Advice("all-in", "ALL IN (1000)", "Go.", amount=1000.0),
                Advice("fold", "FOLD", "Fold.")):
        assert advice._legal_size(s, adv) is adv


def test_an_estimated_size_keeps_its_about():
    # no big blind read: the size comes from one worked out from the pot, and says so
    st = table(("Ah", "Ad"), "CO", bets={"SB": 1, "BB": 2}, blinds=None, to_call=2.0, pot=0.0,
               folded=["UTG", "HJ"], actions=[Action("fold"), Action("call", 2), Action("raise")])
    s = spot(st)
    adv = advice._legal_size(s, Advice("raise", "RAISE TO ABOUT 3", "Raise.", amount=3.0))
    assert adv.headline.startswith("RAISE TO ABOUT ") and adv.amount >= 4


def test_an_estimated_size_over_the_stack_is_capped_but_never_all_in():
    # a random spot from test_advice_fuzz: no big blind read, a pot of 200 before the flop, so
    # the big blind guessed from it is 133 and the open "about 2.5 big blinds" is 333, with 200
    # chips. Capped at the stack; a guessed size never becomes ALL IN.
    st = table(("Ah", "Ad"), "UTG", bets={"SB": 1}, blinds=None, pot=200.0, stacks={"UTG": 200.0},
               hero_to_act=None)
    s = spot(st)
    adv = advice._legal_size(s, Advice("raise", "RAISE TO ABOUT 333", "Raise.", amount=333.0))
    assert (adv.action, adv.headline, adv.amount) == ("raise", "RAISE TO ABOUT 200", 200.0)


@pytest.mark.parametrize("x,want", [(2.0, 2.0), (2.25, 2.5), (1.2, 1.5), (9.6, 10.0), (10.4, 11.0), (10.5, 11.0),
                                    (0.333, 0.34), (0.04, 0.04), (13.0, 13.0)])
def test_rounding_a_minimum_never_goes_under_it(x, want):
    assert advice._chips_up(x) == want
