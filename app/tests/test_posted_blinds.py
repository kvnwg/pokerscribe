"""The blinds from the chips the small and big blind put in front of them (Kevin, 26 Nov, on
247: "the guy put down big blind and u saw it as he reraised me. make sure to look for big
blind and small blind bets on screen"). A big blind's own chips are never a raise."""
from app.poker.advice import advise
from app.state.model import Action, Field, GameState, Player
from app.state.positions import posted_blinds


def player(seat, pos, stack, bet, hero=False, folded=False, tag=None, pos_known=True):
    p = Player(seat=seat, is_hero=hero, position=Field.manual(pos) if pos_known else Field(),
               stack=Field.manual(stack), bet=Field.manual(bet), in_hand=Field.manual(not folded))
    if tag:
        p.last_action = Field.manual(Action(tag, bet))
    return p


def spot(players, cards, to_call, actions):
    st = GameState(hero_cards=[Field.manual(c) for c in cards], players=players)
    st.street, st.pot, st.pot_includes_bets = Field.manual("preflop"), Field.manual(0.0), False
    st.to_call, st.hero_to_act = Field.manual(to_call), Field.manual(True)
    st.available_actions = Field.manual(actions)
    return st


def table(bets, positions=("BTN", "SB", "BB", "UTG", "HJ", "CO"), known=True, hero=0, tags=None):
    tags = tags or {}
    return [player(i, pos, 200 - b, b, hero=i == hero, folded=False, tag=tags.get(i), pos_known=known)
            for i, (pos, b) in enumerate(zip(positions, bets))]


FOLD, RAISE, CHECK = Action("fold"), Action("raise"), Action("check")


def test_the_blinds_are_the_chips_the_blinds_put_in():
    assert posted_blinds(table([0, 1, 2, 0, 0, 0])) == (1, 2)
    assert posted_blinds(table([0, 10, 20, 20, 0, 60])) == (10, 20)  # a call and a raise after them
    assert posted_blinds(table([0, 1, 8, 2, 0, 0])) is None  # the big blind re-raised
    assert posted_blinds(table([0, 2, 2, 0, 0, 0])) is None  # the small blind completed
    assert posted_blinds(table([0, 1, 2, 1, 0, 0])) is None  # a bet under the big blind: not the blinds


def test_the_blinds_without_the_dealer_button():
    """No D found: the smallest bet, and twice it at the next seat round the table."""
    assert posted_blinds(table([0, 1, 2, 0, 0, 0], known=False)) == (1, 2)
    assert posted_blinds(table([0, 1, 2, 6, 6, 0], known=False)) == (1, 2)
    # the small blind's chips gone: the big blind's 2 and a raise to 5 are not the blinds
    assert posted_blinds(table([0, 0, 2, 5, 0, 0], known=False)) is None
    assert posted_blinds(table([0, 2, 0, 4, 0, 0], known=False)) is None  # not next to each other
    assert posted_blinds(table([0, 1, 1, 2, 0, 0], known=False)) is None  # two smallest


def test_the_big_blinds_chips_are_no_raise_without_the_dealer_button():
    """No stakes printed and no D found: the smallest bet (the small blind's 1) was taken for
    the big blind, so the big blind's own 2 looked like a raise. King Queen on the button,
    folded to you: FOLD, "Someone raised"."""
    st = spot(table([0, 1, 2, 0, 0, 0], known=False), ["Kh", "Qs"], 2.0, [FOLD, Action("call", 2), RAISE])
    adv = advise(st)
    assert adv.action == "raise"
    assert "raised" not in adv.reason.lower()


def test_your_big_blind_and_a_limper_is_no_raise_without_the_dealer_button():
    """You in the big blind, the small blind's 1 and a limper's 2 in front: checking is free
    and nobody raised."""
    bets = [2, 2, 0, 0, 0, 1]
    st = spot(table(bets, positions=("BB", "UTG", "HJ", "CO", "BTN", "SB"), known=False), ["9h", "6c"], 0.0,
              [CHECK, RAISE])
    adv = advise(st)
    assert adv.action == "check"
    assert "no one raised" in adv.reason.lower()


def test_a_tag_on_your_big_blind_is_not_your_raise():
    """A tag on your plate for your own blind ("Raise 2", "Bet 2"): a later raise to 6 was taken
    for a re-raise of you ("They re-raised you"), and the hands for that are far fewer."""
    bets = [2, 6, 0, 0, 0, 1]
    st = spot(table(bets, positions=("BB", "UTG", "HJ", "CO", "BTN", "SB"), tags={0: "raise", 1: "raise"}),
              ["Ah", "Jd"], 4.0, [FOLD, Action("call", 4), RAISE])
    st.blinds = Field.manual((1.0, 2.0))
    adv = advise(st)
    assert "re-raise" not in adv.reason.lower()
    assert adv.action in ("call", "raise")
