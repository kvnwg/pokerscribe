"""Thousands of random spots, with values missing the way a real read can miss them.
Whatever the strategy, some instructions are always wrong; none may appear."""
import random

from app.poker import hands
from app.poker.advice import advise
from app.poker.ranges import preflop_percentile
from app.state.model import Action, Field, GameState, Player

POS6 = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]


def random_spot(rng: random.Random):
    deck = list(hands.DECK)
    rng.shuffle(deck)
    hero_pos = rng.choice(POS6)
    n_board = rng.choice([0, 0, 3, 4, 5])
    board = deck[2:2 + n_board]
    bb = 2.0
    to_call = rng.choice([0.0, 0.0, 2.0, 6.0, 20.0, 80.0]) if n_board else rng.choice([0.0, 1.0, 2.0, 4.0, 10.0, 40.0])
    players = []
    for i, pos in enumerate(POS6):
        is_hero = pos == hero_pos
        stack = rng.choice([30.0, 200.0, 1000.0]) if not is_hero else rng.choice([20.0, 200.0, 1000.0])
        p = Player(seat=i, is_hero=is_hero, position=Field.manual(pos), stack=Field.manual(stack),
                   in_hand=Field.manual(is_hero or rng.random() < 0.6))
        if rng.random() < 0.5:
            p.bet = Field.manual(rng.choice([0.0, 1.0, 2.0, 6.0]))
        if not is_hero and rng.random() < 0.4:
            p.last_action = Field.manual(Action(rng.choice(["call", "raise", "check", "fold", "bet"])))
        players.append(p)
    st = GameState(hero_cards=[Field.manual(deck[0]), Field.manual(deck[1])],
                   board=[Field.manual(c) for c in board], players=players)
    st.pot = Field.manual(rng.choice([3.0, 10.0, 40.0, 200.0]))
    st.pot_includes_bets = rng.random() < 0.5
    if rng.random() < 0.6:
        st.blinds = Field.manual((1.0, bb))
    if rng.random() < 0.6:
        st.to_call = Field.manual(to_call)
    turn = rng.random()
    if turn < 0.6:
        st.hero_to_act = Field.manual(True)
        acts = [Action("fold"), Action("call", to_call), Action("raise")] if to_call > 0 else \
            [Action("fold"), Action("check"), Action("bet")]
        st.available_actions = Field.manual(acts)
    elif turn < 0.7:
        st.hero_to_act = Field.manual(False)
    return st, to_call


def test_no_wrong_instructions_in_random_spots():
    rng = random.Random(2026)
    bad = []
    for _ in range(1500):
        st, to_call = random_spot(rng)
        a = advise(st, budget_ms=5, numbers_checked=rng.random() < 0.8)
        my_turn = st.hero_to_act.known and st.hero_to_act.value
        acts = {x.kind for x in st.available_actions.value} if st.available_actions.known else set()
        if my_turn and "check" in acts and a.action == "fold":
            bad.append(("fold with a Check button", a.headline))
        if a.action == "fold" and st.to_call.known and st.to_call.value == 0 and not (my_turn and "call" in acts):
            bad.append(("fold with nothing to call", a.headline))
        if a.headline in ("RAISE", "BET"):
            bad.append(("no amount", a.headline))
        if my_turn and a.action in ("wait",):
            bad.append(("wait on your turn", a.headline))
        if st.hero_to_act.known and st.hero_to_act.value is False and a.action not in ("wait", "unknown"):
            bad.append(("a move when it's not your turn", a.headline))
        me = st.hero
        if (a.action == "all-in" and not a.headline.startswith("CALL") and not st.board
                and me.stack.value >= 100 and preflop_percentile(hands.preflop_class(
                    [c.value for c in st.hero_cards])) > 0.05 and (not st.to_call.known or st.to_call.value <= 4)):
            bad.append(("deep shove with a weak hand", a.headline))
    assert not bad, bad[:10]


def test_paired_simulation_is_repeatable():
    """tools/compare.py relies on the same seed giving the same hand, decision for decision."""
    import os
    import sys

    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")
    sys.path.insert(0, tools)
    try:
        import compare
    finally:
        sys.path.remove(tools)
    a = compare.paired({}, {}, 6, "mixed", 5)
    b = compare.paired({}, {}, 6, "mixed", 5)
    assert a[0]["hands"] == b[0]["hands"] and all(d == 0 for d in a[2]) and a[3] == 0
    assert not a[0]["problems"]
