"""pokerscribe_engine: the Rust engine from Python (engine/crates/py).

The module is built from Rust and is optional: the app runs without it. When it isn't
built, every test here is skipped. To build it: engine/crates/py/README.md.

Checked here: the evaluator against treys (the evaluator the app already uses), and the
rules engine against the 10,000 PokerKit hands the Rust tests replay, so the bindings are
known to hand over exactly what the engine works out.
"""
import copy
import os
import random
import re

import pytest

pe = pytest.importorskip("pokerscribe_engine", reason="the Rust engine module isn't built (engine/crates/py/README.md)")

from app.poker import hands  # noqa: E402
from app.solver import ranking  # noqa: E402

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "engine", "crates")
FIXTURES = os.path.join(ENGINE, "nlhe", "tests", "fixtures", "pokerkit_nlhe.txt")
DECK = [r + s for r in "23456789TJQKA" for s in "cdhs"]  # in the engine's order: 2c is 0, As is 51
STREETS = ["preflop", "flop", "turn", "river"]


def test_the_module_is_the_one_in_the_repo():
    with open(os.path.join(ENGINE, "py", "Cargo.toml")) as f:
        version = re.search(r'^version = "([^"]+)"', f.read(), re.M).group(1)
    assert pe.__version__ == version, "an older build is installed: build it again (engine/crates/py/README.md)"
    assert pe.MAX_PLAYERS == 6 and pe.MAX_RANK == 7462


def test_the_type_stubs_name_what_the_module_has():
    """engine/crates/py/pokerscribe_engine.pyi is written by hand: keep it in step."""
    import ast

    with open(os.path.join(ENGINE, "py", "pokerscribe_engine.pyi")) as f:
        stub = ast.parse(f.read())

    def names(body):
        return ({n.name for n in body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
                | {n.target.id for n in body if isinstance(n, ast.AnnAssign)})

    public = {n for n in dir(pe) if not n.startswith("_") and n != "pokerscribe_engine"} | {"__version__"}
    assert names(stub.body) - {"Card", "Cards"} == public
    for cls in (pe.State, pe.LegalActions):
        node = next(n for n in stub.body if isinstance(n, ast.ClassDef) and n.name == cls.__name__)
        assert {n for n in names(node.body) if not n.startswith("_")} == {n for n in dir(cls) if not n.startswith("_")}


# --------------------------------------------------------------- the cards
def test_a_card_is_a_string_or_the_engines_number():
    assert [pe.card_index(c) for c in ("2c", "2d", "2h", "2s", "3c", "Ah", "As")] == [0, 1, 2, 3, 4, 50, 51]
    assert [pe.card_string(i) for i in range(52)] == DECK
    assert all(pe.card_index(pe.card_string(i)) == i for i in range(52))
    assert pe.card_index("ah") == pe.card_index("AH") == 50  # either case, like the eval crate
    assert pe.card_string("td") == "Td" and pe.card_index(7) == 7


def test_the_engines_numbers_are_not_the_python_solvers():
    # Both are rank * 4 + suit, but the engine orders the suits c, d, h, s and
    # app/solver/ranking.py orders them s, h, d, c. Pass strings between the two.
    assert pe.card_index("As") == 51 and ranking.card_index("As") == 48
    assert pe.card_index("Ah") == ranking.card_index("Ad") == 50


@pytest.mark.parametrize("bad, error", [("1h", ValueError), ("Ax", ValueError), ("Ahh", ValueError), ("", ValueError),
                                        (52, ValueError), (-1, ValueError), (2 ** 70, TypeError),
                                        (True, TypeError), (1.0, TypeError), (None, TypeError), (["Ah"], TypeError)])
def test_what_is_not_a_card_is_refused(bad, error):
    with pytest.raises(error):
        pe.card_index(bad)
    with pytest.raises(error):
        pe.eval7(["2c", "3d", "4h", "5s", "7c", "8d", bad])


# ----------------------------------------------------------- the evaluator
def test_eval7_takes_strings_ints_or_one_string():
    royal = ["Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d"]
    assert pe.eval7(royal) == pe.MAX_RANK == 7462
    assert pe.eval7(tuple(royal)) == pe.eval7([pe.card_index(c) for c in royal]) == 7462
    assert pe.eval7("AhKh QhJhTh 2c3d") == pe.eval7("Ah,Kh,Qh,Jh,Th,2c,3d") == 7462
    assert pe.eval7(["Ah", 46, "Qh", 38, "Th", 0, "3d"]) == 7462  # mixed is fine too
    assert pe.eval7(iter(royal)) == 7462  # anything that can be looped over
    assert pe.eval5("7c5d4h3s2c") == 1  # the worst hand there is
    assert pe.eval7("AhAd KcKs QhQc 4d") == pe.eval7("AhAd KcKs Qh2c 4d")  # the kicker plays either way
    assert pe.eval7("AsAd 2c7h9s JdQc") > pe.eval7("KsKd 2c7h9s JdQc")  # higher is better


def test_the_evaluator_is_treys_upside_down():
    # treys counts from 1 (royal flush) to 7462 (the worst hand); the engine the other way.
    rng = random.Random(20261126)
    for _ in range(20000):
        cards = rng.sample(DECK, 7)
        assert pe.eval7(cards) == 7463 - hands.evaluate(cards[:2], cards[2:]), cards
    for _ in range(3000):
        cards = rng.sample(DECK, 6)
        assert pe.eval6(cards) == 7463 - hands.evaluate(cards[:2], cards[2:]), cards
        assert pe.eval5(cards[:5]) == 7463 - hands.evaluate(cards[:2], cards[2:5]), cards


def test_the_evaluator_orders_hands_as_the_python_ranking_does():
    rng = random.Random(7)
    for _ in range(3000):
        cards = rng.sample(DECK, 9)
        a, b = cards[:2] + cards[4:], cards[2:4] + cards[4:]
        engine = (pe.eval7(a) > pe.eval7(b)) - (pe.eval7(a) < pe.eval7(b))
        python = (ranking.hand_value(a) > ranking.hand_value(b)) - (ranking.hand_value(a) < ranking.hand_value(b))
        assert engine == python, cards


def test_hand_categories():
    names = [pe.hand_category(pe.eval5(h)) for h in (
        "AhKd9c7s2h", "AhAd9c7s2h", "AhAd9c9s2h", "AhAdAc7s2h", "5h4d3c2sAh", "AhKh9h7h2h", "AhAdAc7s7h", "AhAdAcAs2h",
        "5h4h3h2hAh")]
    assert names == ["high card", "pair", "two pair", "three of a kind", "straight", "flush", "full house",
                     "four of a kind", "straight flush"]
    assert pe.hand_category(1) == "high card" and pe.hand_category(7462) == "straight flush"
    for bad in (0, 7463):
        with pytest.raises(ValueError):
            pe.hand_category(bad)


def test_the_evaluator_wants_the_right_number_of_different_cards():
    with pytest.raises(ValueError, match="eval7 takes 7 cards, got 6"):
        pe.eval7("AhKhQhJhTh2c")
    with pytest.raises(ValueError, match="eval5 takes 5 cards, got 7"):
        pe.eval5("AhKhQhJhTh2c3d")
    with pytest.raises(ValueError, match="Ah is there twice"):
        pe.eval7(["Ah", "Kh", "Qh", "Jh", "Th", "2c", 50])
    with pytest.raises(TypeError):
        pe.eval7(7)


# ------------------------------------------------------------- a new hand
def heads_up(**kw):
    """1/2 blinds, 200 each, the button on seat 0. AhKd against 7c2d on a queen-high board."""
    args = dict(hole=[["Ah", "Kd"], ["7c", "2d"]], board=["Qs", "Jh", "2c", "7d", "Th"])
    args.update(kw)
    return pe.new_hand([200, 200], 1, 2, **args)


def test_a_new_hand_posts_the_blinds():
    h = heads_up()
    assert (h.num_players, h.button, h.small_blind_seat, h.big_blind_seat) == (2, 0, 0, 1)
    assert (h.small_blind, h.big_blind, h.ante) == (1, 2, 0)
    assert h.starting_stacks == [200, 200] and h.stacks == [199, 198] and h.bets == [1, 2]
    assert h.committed == [1, 2] and h.pot == 3 and h.max_bet == 2 and h.full_raise == 2
    assert h.street == "preflop" and h.board == [] and not h.is_terminal
    assert h.current_player == 0  # heads-up, the button posts the small blind and acts first
    assert h.hole_cards(0) == ["Ah", "Kd"] and h.hole_cards(1) == ["7c", "2d"]
    assert repr(h) == "State(2 players, preflop, pot 3, seat 0 to act)"
    assert isinstance(h, pe.State)


def test_state_takes_the_arguments_of_new_hand():
    args = ([300, 250, 100], 5, 10)
    a = pe.new_hand(*args, ante=1, button=2, seed=99)
    b = pe.State(*args, ante=1, button=2, seed=99)
    assert a == b and a.ante == 1 and a.button == 2 and a.small_blind_seat == 0 and a.big_blind_seat == 1
    assert a.committed == [6, 11, 1] and a.current_player == 2  # the seat after the big blind


def test_cards_can_be_given_as_strings_ints_or_pairs():
    board = ["Qs", "Jh", "2c", "7d", "Th"]
    a = heads_up()
    b = pe.new_hand([200, 200], 1, 2, hole=["AhKd", "7c2d"], board="QsJh2c 7d Th")
    c = pe.new_hand([200, 200], 1, 2, hole=[(pe.card_index("Ah"), pe.card_index("Kd")), ("7c", "2d")],
                    board=[pe.card_index(x) for x in board])
    assert a == b == c


def test_a_seed_always_gives_the_same_cards():
    a, b, c = (pe.new_hand([200] * 6, 1, 2, seed=s) for s in (42, 42, 43))
    cards = lambda h: [h.hole_cards(s) for s in range(6)]  # noqa: E731
    assert cards(a) == cards(b) != cards(c) and a == b and a != c
    dealt = [x for pair in cards(a) for x in pair]
    assert len(set(dealt)) == 12 and all(x in DECK for x in dealt)
    assert pe.new_hand([200, 200], 1, 2, seed=2 ** 64 - 1).current_player == 0  # any 64-bit seed


@pytest.mark.parametrize("args, kw, message", [
    (([200], 1, 2), dict(seed=1), "1 players"),
    (([200] * 7, 1, 2), dict(seed=1), "7 players"),
    (([200, 0], 1, 2), dict(seed=1), "seat 1 has no chips"),
    (([200, 200], 3, 2), dict(seed=1), "small blind is larger"),
    (([200, 200], 1, 0), dict(seed=1), "big blind must be at least 1"),
    (([200, 200], 1, 2), dict(seed=1, button=2), "button 2 is not a seat"),
    (([200, 200], 1, 2), dict(), "give either seed"),
    (([200, 200], 1, 2), dict(seed=1, hole=["AhKd", "7c2d"], board="QsJh2c7dTh"), "give either seed"),
    (([200, 200], 1, 2), dict(hole=["AhKd", "7c2d"]), "give either seed"),
    (([200, 200], 1, 2), dict(hole=["AhKd"], board="QsJh2c7dTh"), "hole cards for 1 seats, but 2 stacks"),
    (([200, 200], 1, 2), dict(hole=["AhKd", "7c"], board="QsJh2c7dTh"), "two hole cards, got 1"),
    (([200, 200], 1, 2), dict(hole=["AhKd", "7c2d"], board="QsJh2c7d"), "five cards"),
    (([200, 200], 1, 2), dict(hole=["AhKd", "Ah2d"], board="QsJh2c7dTh"), "Ah is dealt twice"),
    (([200, 200], 1, 2), dict(hole=["AhKd", "7c2d"], board="QsJh2c7dKd"), "Kd is dealt twice"),
])
def test_a_table_that_makes_no_sense_is_refused(args, kw, message):
    with pytest.raises(ValueError, match=message):
        pe.new_hand(*args, **kw)


def test_chips_are_whole_numbers():
    with pytest.raises(TypeError):
        pe.new_hand([200.5, 200], 1, 2, seed=1)
    with pytest.raises(OverflowError):
        pe.new_hand([-200, 200], 1, 2, seed=1)
    h = heads_up()
    with pytest.raises(TypeError):
        h.apply("raise", 6.0)


# ------------------------------------------------------------ legal actions
def test_legal_actions():
    h = heads_up()
    legal = h.legal_actions()
    assert (legal.fold, legal.check, legal.call) == (True, False, 1)
    assert (legal.min_raise_to, legal.max_raise_to, legal.can_raise) == (4, 200, True)
    assert legal.names() == ["fold", "call", "raise"]
    assert repr(legal) == "LegalActions(fold=True, check=False, call=1, min_raise_to=4, max_raise_to=200)"
    assert legal.allows("fold") and legal.allows("call") and not legal.allows("check")
    assert legal.allows("raise", 4) and legal.allows("raise", 200) and legal.allows("bet", 50)
    assert not legal.allows("raise", 3) and not legal.allows("raise", 201)
    assert legal == h.legal_actions() and hash(legal) == hash(h.legal_actions())
    with pytest.raises(AttributeError):
        legal.fold = False  # read-only

    h.apply("call")
    legal = h.legal_actions()  # the big blind's option
    assert (legal.fold, legal.check, legal.call, legal.min_raise_to, legal.max_raise_to) == (False, True, None, 4, 200)
    assert legal.names() == ["check", "raise"]


def test_nothing_is_legal_once_the_hand_is_over():
    h = heads_up()
    h.apply("fold")
    legal = h.legal_actions()
    assert legal.names() == [] and not legal.can_raise and legal.call is None
    with pytest.raises(ValueError, match="the hand is over"):
        h.apply("check")


# -------------------------------------------------------------------- apply
def test_a_hand_to_the_showdown():
    h = heads_up()
    h.apply("raise", 6)  # to 6 in all
    assert h.bets == [6, 2] and h.current_player == 1 and h.legal_actions().call == 4
    h.apply("call")
    assert h.street == "flop" and h.board == ["Qs", "Jh", "2c"] and h.bets == [0, 0] and h.pot == 12
    assert h.current_player == 1  # after the flop the big blind acts first
    h.apply("check")
    h.apply("bet", 8)  # an opening bet is a raise to the engine; "bet" is another name for it
    h.apply("call")
    assert h.street == "turn" and h.board == ["Qs", "Jh", "2c", "7d"] and h.pot == 28
    h.apply("check")
    h.apply("check")
    assert h.street == "river" and h.board == ["Qs", "Jh", "2c", "7d", "Th"]
    with pytest.raises(ValueError, match="not over"):
        h.payouts()
    with pytest.raises(ValueError, match="not over"):
        h.final_stacks()
    h.apply("check")
    h.apply("check")
    assert h.is_terminal and h.current_player is None
    # AhKd makes the broadway straight; 7c2d has two pair
    assert h.payouts() == [14, -14] and h.final_stacks() == [214, 186]
    assert h.pots() == [(28, [0, 1])]
    assert repr(h) == "State(2 players, river, pot 28, over)"
    assert h.history() == [
        {"street": "preflop", "seat": 0, "action": "raise", "amount": 6, "added": 5},
        {"street": "preflop", "seat": 1, "action": "call", "amount": None, "added": 4},
        {"street": "flop", "seat": 1, "action": "check", "amount": None, "added": 0},
        {"street": "flop", "seat": 0, "action": "raise", "amount": 8, "added": 8},
        {"street": "flop", "seat": 1, "action": "call", "amount": None, "added": 8},
        {"street": "turn", "seat": 1, "action": "check", "amount": None, "added": 0},
        {"street": "turn", "seat": 0, "action": "check", "amount": None, "added": 0},
        {"street": "river", "seat": 1, "action": "check", "amount": None, "added": 0},
        {"street": "river", "seat": 0, "action": "check", "amount": None, "added": 0},
    ]


def test_an_action_that_is_not_legal_changes_nothing():
    h = heads_up()
    before = h.copy()
    for action, amount, message in [("check", None, "check is not legal here"),
                                    ("raise", 3, "raise to 3 is not legal here"),
                                    ("raise", 201, "raise to 201 is not legal here"),
                                    ("raise", None, "raise needs an amount"),
                                    ("bet", None, "bet needs an amount"),
                                    ("call", 1, "call takes no amount"),
                                    ("fold", 0, "fold takes no amount"),
                                    ("all in", None, "unknown action"),
                                    ("Fold", None, "unknown action")]:
        with pytest.raises(ValueError, match=message):
            h.apply(action, amount)
        assert h == before and h.history() == []


def test_a_fold_ends_the_hand_and_the_uncalled_bet_goes_back():
    h = heads_up()
    h.apply("raise", 50)
    h.apply("fold")
    assert h.is_terminal and h.payouts() == [2, -2] and h.final_stacks() == [202, 198]
    assert h.pot == 4  # the 48 nobody called went back


def test_an_all_in_runs_the_board_out_and_makes_side_pots():
    # seat 0 has the button; seat 1 is the small blind with 30, seat 2 the big blind with 100
    h = pe.new_hand([200, 30, 100], 1, 2, hole=["AsAh", "KsKh", "QsQh"], board="2c7d9hJc3s")
    assert h.current_player == 0
    h.apply("raise", 200)
    h.apply("call")  # all in for 30
    assert h.is_all_in(1) and not h.is_all_in(2) and not h.is_folded(1)
    h.apply("call")  # all in for 100
    assert h.is_terminal and h.street == "river" and len(h.board) == 5
    assert h.pots() == [(90, [0, 1, 2]), (140, [0, 2])]  # the 100 nobody could call went back
    assert h.committed == [100, 30, 100]
    assert h.payouts() == [130, -30, -100] and h.final_stacks() == [330, 0, 0]
    with pytest.raises(IndexError, match="seat 3 is not at the table"):
        h.hole_cards(3)
    with pytest.raises(IndexError):
        h.is_folded(5)


def test_a_split_pot_gives_the_odd_chip_to_the_first_winner_after_the_button():
    # everyone plays the board; the small blind folds, leaving 5 chips for two players
    h = pe.new_hand([100, 100, 100], 1, 2, hole=["2c3d", "2d3h", "2h3s"], board="AcKdQhJsTc")
    h.apply("call")  # the button
    h.apply("fold")  # the small blind
    for _ in range(7):  # the big blind's option, then three streets of checks
        h.apply("check")
    assert h.is_terminal and h.is_folded(1)
    assert h.payouts() == [0, -1, 1]  # 5 chips for seats 0 and 2: 2 each, the odd one to seat 2


def test_copies_are_independent():
    h = heads_up()
    h.apply("call")
    a, b, c = h.copy(), copy.copy(h), copy.deepcopy(h)
    h.apply("raise", 10)
    assert a == b == c != h and a.bets == [2, 2] and h.bets == [2, 10]
    a.apply("check")
    assert a.street == "flop" and b.street == "preflop"


# ------------------------------------------------- the engine, through Python
def test_random_hands_keep_every_chip():
    rng = random.Random(5)
    for k in range(2000):
        n = rng.randint(2, 6)
        stacks = [rng.randint(1, 300) for _ in range(n)]
        h = pe.new_hand(stacks, 1, 2, ante=rng.randint(0, 2), button=rng.randrange(n), seed=k)
        steps = 0
        while not h.is_terminal:
            legal = h.legal_actions()
            action = rng.choice(legal.names())
            if action == "raise":
                h.apply("raise", rng.randint(legal.min_raise_to, legal.max_raise_to))
            else:
                h.apply(action)
            steps += 1
            assert steps < 500
        assert sum(h.payouts()) == 0 and sum(h.final_stacks()) == sum(stacks)
        assert [f - s for f, s in zip(h.final_stacks(), stacks)] == h.payouts()
        assert len(h.history()) == steps


def _fixture_hands():
    with open(FIXTURES) as f:
        for line in f:
            line = line.rstrip("\n")
            if line and not line.startswith("#"):
                head, stacks, cards, steps, final, pots = line.split(" | ")
                yield ([int(x) for x in head.split()], [int(x) for x in stacks.split()],
                       [int(x) for x in cards.split()], steps.split(), [int(x) for x in final.split()], pots)


def test_the_pokerkit_hands_replay_through_the_bindings():
    """The 10,000 PokerKit hands of engine/crates/nlhe (see its README), played through
    Python: whose turn it is, the street, every stack, the legal actions and the raise
    range at each decision, then the pots and the final stacks."""
    hands_played = decisions = showdowns = 0
    for k, (head, stacks, cards, steps, final, pots) in enumerate(_fixture_hands()):
        n, small, big, ante = head
        button = k % n
        seat = lambda p: (button + 1 + p) % n  # noqa: E731 (PokerKit's player 0 sits after the button)
        by_seat = lambda values: [values[(s - button - 1) % n] for s in range(n)]  # noqa: E731
        hole = by_seat([cards[2 * p:2 * p + 2] for p in range(n)])
        h = pe.new_hand(by_seat(stacks), small, big, ante=ante, button=button, hole=hole, board=cards[2 * n:2 * n + 5])
        for step in steps:
            player, street, behind, fold, call, low, high, _flag, action = step.split(",")
            assert h.current_player == seat(int(player)) and h.street == STREETS[int(street)], (k, step)
            assert h.stacks == by_seat([int(x) for x in behind.split("/")]), (k, step)
            legal = h.legal_actions()
            assert (legal.fold, legal.check, legal.call) == (fold == "1", call == "0", int(call) or None), (k, step)
            want = (None, None) if low == "-" else (int(low), int(high))
            assert (legal.min_raise_to, legal.max_raise_to) == want, (k, step)
            if action[0] == "r":
                h.apply("raise", int(action[1:]))
            else:
                h.apply({"f": "fold", "k": "check", "c": "call"}[action])
            decisions += 1
        assert h.is_terminal and len(h.history()) == len(steps), k
        assert h.final_stacks() == by_seat(final), k
        if pots != "-":
            want_pots = [(int(amount), sorted(seat(int(p)) for p in players.split(".")))
                         for amount, players in (pot.split(":") for pot in pots.split())]
            assert h.pots() == want_pots, k
            showdowns += 1
        hands_played += 1
    assert hands_played == 10000 and decisions == 64284 and showdowns > 5000


def test_the_example_in_the_readme():
    hand = pe.new_hand([200, 200], 1, 2, seed=7)  # heads-up, 1/2 blinds, the button on seat 0
    while not hand.is_terminal:
        legal = hand.legal_actions()
        hand.apply("check" if legal.check else "call")
    assert hand.street == "river" and len(hand.board) == 5
    net = hand.payouts()
    assert sum(net) == 0 and sorted(abs(x) for x in net) in ([0, 0], [2, 2])
