"""Watch mode: bets, amount to call and blinds worked out from stack changes."""
from typing import Dict, Optional, Sequence

from app.recognition.tracker import HandTracker
from app.state.model import Field, GameState, Player

SEATS = ["hero", "Deja", "John", "Mike", "George"]
POS = {"hero": "CO", "Deja": "BTN", "John": "SB", "Mike": "BB", "George": "HJ"}


def capture(stacks: Dict[str, Optional[float]], cards: Optional[Sequence[str]] = ("7s", "4s"),
            board: Sequence[str] = (), pot: Optional[float] = None, positions=POS) -> GameState:
    players = []
    for i, name in enumerate(SEATS):
        v = stacks.get(name)
        players.append(Player(seat=i, is_hero=name == "hero", anchor=None if name == "hero" else (100.0 * i, 50.0),
                              stack=Field.manual(v) if v is not None else Field(),
                              position=Field.manual(positions[name]) if positions else Field(), name=name))
    st = GameState(hero_cards=[Field.manual(c) for c in cards] if cards else [Field(), Field()],
                   board=[Field.manual(c) for c in board], players=players)
    if pot is not None:
        st.pot = Field.manual(float(pot))
    return st


FULL = {n: 1000.0 for n in SEATS}


def test_follows_a_hand_where_bets_are_never_printed():
    t = HandTracker()
    t.update(capture(FULL, cards=None))  # between hands
    # new hand: blinds 1/2 posted, the hijack limped
    st = capture(dict(FULL, John=999, Mike=998, George=998), pot=5)
    info = t.update(st)
    assert info.new_hand and info.valid
    assert st.to_call.value == 2 and st.blinds.value == (1, 2) and st.pot_includes_bets
    assert info.hero_invested == 0
    assert [p.bet.value for p in st.players] == [0, 0, 1, 2, 2]
    # hero calls: nothing more to call
    st = capture(dict(FULL, hero=998, John=999, Mike=998, George=998), pot=7)
    info = t.update(st)
    assert info.valid and st.to_call.value == 0 and info.hero_invested == 2
    # flop: the big blind bets 4
    st = capture(dict(FULL, hero=998, John=999, Mike=994, George=998), board=("Kh", "9d", "2c"), pot=11)
    info = t.update(st)
    assert info.valid and st.to_call.value == 4 and not info.new_hand
    assert [p.bet.value for p in st.players] == [0, 0, 0, 4, 0]  # bets this round, not this hand
    # hero raises to 12, the big blind re-raises to 30: hero faces 18 more
    st = capture(dict(FULL, hero=986, John=999, Mike=968, George=998), board=("Kh", "9d", "2c"), pot=49)
    assert t.update(st).valid and st.to_call.value == 18


def test_numbers_that_dont_add_up_stay_unknown():
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    # a stack was misread (998 read as 98): the sum no longer matches the pot
    st = capture(dict(FULL, John=999, Mike=98, George=998), pot=5)
    info = t.update(st)
    assert not info.valid and not st.to_call.known and not st.blinds.known


def test_missed_start_of_hand_stays_unknown():
    t = HandTracker()
    # the app started in the middle of a hand: there is no snapshot from before the blinds
    st = capture(dict(FULL, John=999, Mike=998), pot=3)
    assert not t.update(st).valid and not st.to_call.known
    # the pot is awarded and a new hand starts: from now on it works
    t.update(capture(dict(FULL, John=999, Mike=1001), cards=None))
    st = capture(dict(FULL, John=999, Mike=1000, George=998), cards=("Ah", "Kd"), pot=3,
                 positions={"hero": "HJ", "Deja": "CO", "John": "BTN", "Mike": "SB", "George": "BB"})
    info = t.update(st)
    assert info.new_hand and info.valid and st.to_call.value == 2 and st.blinds.value == (1, 2)


def test_screen_values_win_over_tracked_ones():
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=999, Mike=998, George=998), pot=5)
    st.to_call = Field.manual(2.0)
    st.blinds = Field.manual((1.0, 2.0))
    t.update(st)
    assert st.to_call.source == "manual" and st.blinds.source == "manual"


def test_hand_start_is_found_even_when_its_first_captures_were_missed():
    t = HandTracker()
    t.update(capture(FULL, cards=None))  # between hands
    # several actions happened before the next capture: blinds, a raise to 6, a call
    st = capture(dict(FULL, John=999, Mike=998, George=994, Deja=994), pot=15)
    info = t.update(st)
    assert info.valid and info.new_hand and st.to_call.value == 6


def test_unread_cards_dont_stop_bet_tracking():
    """The hero's cards were still being confirmed: bets are worked out all the same."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=999, Mike=998, George=998), cards=None, pot=5)
    assert t.update(st).valid and st.to_call.value == 2
    st = capture(dict(FULL, John=999, Mike=998, George=998), cards=("Ah", "Kd"), pot=5)
    info = t.update(st)
    assert info.valid and not info.new_hand and st.to_call.value == 2


def test_new_hand_after_a_payout_starts_over():
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    t.update(capture(dict(FULL, John=999, Mike=998, George=998), pot=5))
    # everyone folds to the hijack, who wins 5 (net +3)
    t.update(capture(dict(FULL, John=999, Mike=998, George=1003), cards=None))
    st = capture(dict(FULL, hero=999, John=999, Mike=996, George=1003), cards=("2c", "2d"), pot=3,
                 positions={"hero": "SB", "Deja": "CO", "John": "HJ", "Mike": "BB", "George": "BTN"})
    info = t.update(st)
    assert info.new_hand and info.valid and info.hero_invested == 1 and st.to_call.value == 1


def test_client_that_shows_bets_and_leaves_them_out_of_the_pot():
    """Bets printed in front of the players, the pot only grows when a round ends."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=999, Mike=998, George=994), pot=0.0001)
    for name, bet in (("John", 1.0), ("Mike", 2.0), ("George", 6.0)):
        st.players[SEATS.index(name)].bet = Field.manual(bet)
    info = t.update(st)
    assert info.valid and info.pot_includes_bets is False and st.to_call.value == 6
    assert not st.pot_includes_bets


def test_street_bets_after_a_missed_end_of_round():
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    t.update(capture(dict(FULL, hero=998, John=999, Mike=998, George=998), pot=7))  # everyone in for 2
    # turn: George bets 10 (the flop was checked through without a capture)
    st = capture(dict(FULL, hero=998, John=999, Mike=998, George=988), board=("Kh", "9d", "2c", "5s"), pot=17)
    info = t.update(st)
    assert info.valid and st.to_call.value == 10
    assert st.players[SEATS.index("George")].bet.value == 10 and st.players[0].bet.value == 0
