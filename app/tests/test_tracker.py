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


def test_missed_end_of_a_round_doesnt_turn_old_chips_into_new_bets():
    """Found by tools/selftest.py: the pictures of the last raise and call before the flop
    were missed. The level seen before the flop was 2, so on the flop 18 of each player's
    chips looked like flop bets. Everyone still in had matched 20 when the flop came."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    t.update(capture(dict(FULL, John=999, Mike=998), pot=3))  # blinds
    # (missed: George raises to 20, you fold, Deja and John fold, Mike calls)
    st = capture(dict(FULL, John=999, Mike=980, George=980), cards=None, board=("Kh", "9d", "2c"), pot=41)
    for name in ("Mike", "George"):
        st.players[SEATS.index(name)].in_hand = Field.manual(True)
    for name in ("Deja", "John"):
        st.players[SEATS.index(name)].in_hand = Field.manual(False)
    info = t.update(st)
    assert info.valid
    assert [p.bet.value for p in st.players] == [0, 0, 0, 0, 0]


def test_a_pot_sized_bet_does_not_look_like_a_new_hand():
    """On a client whose pot leaves out this round's bets, a bet the size of the pot makes the
    stacks since the flop add up to the pot by chance. The hand start already found still
    adds up (to the pot plus the bet), so it stays."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    t.update(capture(dict(FULL, John=999, Mike=998), pot=3))  # blinds
    t.update(capture(dict(FULL, hero=994, John=999, Mike=998), pot=9))  # hero raises to 6
    t.update(capture(dict(FULL, hero=994, John=999, Mike=994), board=("Kh", "9d", "2c"), pot=13))
    st = capture(dict(FULL, hero=994, John=999, Mike=981), board=("Kh", "9d", "2c"), pot=13)
    st.players[SEATS.index("Mike")].bet = Field.manual(13.0)  # printed in front of Mike
    info = t.update(st)
    assert info.valid and not info.new_hand and info.pot_includes_bets is False
    assert st.to_call.value == 13 and info.hero_invested == 6


def test_last_hands_start_doesnt_carry_into_the_next_hand():
    """Found by tools/selftest.py: the stacks from where the last hand began added up to the
    new hand's pot by chance, the old start was kept, and your blind from the last hand
    counted as a bet in this one: "someone raised", fold. The newest set of stacks that adds
    up is the start, unless only the old one adds up with the printed bets."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, hero=999, Deja=998), pot=3)  # last hand: you posted 1, Deja 2
    st.players[0].bet, st.players[1].bet = Field.manual(1.0), Field.manual(2.0)
    t.update(st)
    t.update(capture(dict(FULL, hero=999, Deja=1001), cards=None))  # you folded, Deja won 3
    t.update(capture(dict(FULL, hero=999, Deja=1001), cards=None))  # between hands
    st = capture(dict(FULL, hero=999, Deja=1001, John=999, Mike=998), pot=3)  # new hand: blinds
    st.players[SEATS.index("John")].bet = Field.manual(1.0)
    st.players[SEATS.index("Mike")].bet = Field.manual(2.0)
    info = t.update(st)
    assert info.valid and info.hero_invested == 0 and st.to_call.value == 2


def test_before_the_flop_with_no_pot_printed():
    """Clients whose pot holds only the earlier rounds print nothing in the middle before the
    flop. The tracker waited for a pot, so on a table that doesn't print the stakes the
    blinds stayed unknown until the flop. Nothing in the middle and the bets in front add up:
    the middle is empty."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))  # between hands
    st = capture(dict(FULL, John=995, Mike=990, George=990))
    for name, bet in (("John", 5.0), ("Mike", 10.0), ("George", 10.0)):
        st.players[SEATS.index(name)].bet = Field.manual(bet)
    info = t.update(st)
    assert info.valid and st.blinds.value == (5, 10) and st.to_call.value == 10
    assert st.pot.value == 0 and st.pot_includes_bets is False
    # a misread stack: the bets no longer add up, nothing is filled in
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=995, Mike=900, George=990))
    for name, bet in (("John", 5.0), ("Mike", 10.0), ("George", 10.0)):
        st.players[SEATS.index(name)].bet = Field.manual(bet)
    assert not t.update(st).valid and not st.blinds.known and not st.pot.known
