"""River hand ranking (app/solver/ranking.py), checked against treys."""
import random
import time

import numpy as np
import pytest

from app.poker import hands
from app.poker.hands import DECK
from app.solver.ranking import (FLUSH, FULL_HOUSE, HIGH_CARD, PAIR, QUADS, STRAIGHT, STRAIGHT_FLUSH, TRIPS,
                                TWO_PAIR, BoardRanker, RiverRanker, category, dense_ranks, hand_value, matchups,
                                rank_range)

SPECIAL_BOARDS = [
    ("As", "Ks", "7s", "4s", "2s"),  # a flush on the board
    ("Ah", "Kh", "Qh", "Jh", "Th"),  # a royal flush on the board: everyone splits
    ("5c", "4d", "3h", "2s", "9c"),  # wheels and six-high straights
    ("7s", "7h", "7d", "7c", "2s"),  # quads on the board
    ("8s", "8h", "8d", "2c", "2s"),  # a full house on the board
    ("9h", "8h", "7h", "2c", "2d"),  # straight flushes possible, paired
    ("Ts", "Js", "Qs", "2h", "3d"),  # three to a flush and a straight
    ("Kc", "Kd", "5h", "5s", "9c"),  # two pair on the board
    ("Ac", "Kd", "Qh", "Js", "Tc"),  # a straight on the board
    ("6h", "6d", "6s", "Kc", "Kh"),  # full house, boats over boats
]


def _all_combos(board):
    rest = [c for c in DECK if c not in board]
    return [(rest[i], rest[j]) for i in range(len(rest)) for j in range(i + 1, len(rest))]


def _same_order(board):
    """Our values and treys ranks must order every combo the same way, ties included."""
    combos = _all_combos(board)
    ours = RiverRanker(board).values(combos)
    theirs = [hands.evaluate(c, board) for c in combos]
    pairs = {}
    for o, t in zip(ours.tolist(), theirs):
        pairs.setdefault(o, set()).add(t)
    assert all(len(v) == 1 for v in pairs.values()), "one of our values covers two treys ranks"
    by_value = sorted((o, next(iter(v))) for o, v in pairs.items())
    treys_ranks = [t for _, t in by_value]
    # higher value = better = lower treys rank, strictly, so no two values share a treys rank
    assert all(a > b for a, b in zip(treys_ranks, treys_ranks[1:]))


@pytest.mark.parametrize("board", SPECIAL_BOARDS, ids=lambda b: "".join(b))
def test_every_combo_orders_like_treys_on_special_boards(board):
    _same_order(board)


def test_every_combo_orders_like_treys_on_random_boards():
    rng = random.Random(7)
    for _ in range(20):
        _same_order(tuple(rng.sample(DECK, 5)))


def test_plain_evaluator_matches_treys_on_random_hands():
    rng = random.Random(11)
    for n in (5, 6, 7):
        prev = None
        for _ in range(400):
            cards = rng.sample(DECK, n)
            v, t = hand_value(cards), hands.evaluate(cards[:2], cards[2:])
            assert category(v) == 9 - hands._EVAL.get_rank_class(t)  # treys classes: 1 best .. 9 worst
            if prev is not None:
                assert (v > prev[0]) == (t < prev[1]) and (v == prev[0]) == (t == prev[1])
            prev = (v, t)


def test_table_lookup_equals_the_plain_evaluator():
    rng = random.Random(3)
    for _ in range(10):
        board = tuple(rng.sample(DECK, 5))
        ranker = RiverRanker(board)
        for combo in rng.sample(_all_combos(board), 100):
            assert ranker.value(combo) == hand_value(list(combo) + list(board))


def test_flop_and_turn_boards_rank_the_hand_made_so_far():
    rng = random.Random(8)
    for n in (3, 4):
        for _ in range(10):
            board = tuple(rng.sample(DECK, n))
            ranker = BoardRanker(board)
            for combo in rng.sample(_all_combos(board), 100):
                assert ranker.value(combo) == hand_value(list(combo) + list(board))
    with pytest.raises(ValueError):
        BoardRanker(("As", "Kd"))
    with pytest.raises(ValueError):
        RiverRanker(("As", "Kd", "7c", "2h"))  # the river ranker still wants five cards


def test_categories_and_known_orders():
    v = lambda *cards: hand_value(list(cards))  # noqa: E731
    assert category(v("Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d")) == STRAIGHT_FLUSH
    assert category(v("Ah", "Ad", "Ac", "As", "Kh", "Kc", "Qd")) == QUADS
    assert category(v("Ah", "Ad", "Ac", "Ks", "Kh", "Qc", "Qd")) == FULL_HOUSE
    assert category(v("Ah", "9h", "7h", "4h", "2h", "Ac", "Ad")) == FLUSH
    assert category(v("Ah", "2d", "3c", "4s", "5h", "Kc", "Kd")) == STRAIGHT
    assert category(v("7h", "7d", "7c", "4s", "2h", "Kc", "Qd")) == TRIPS
    assert category(v("7h", "7d", "4c", "4s", "2h", "2c", "Qd")) == TWO_PAIR
    assert category(v("7h", "7d", "4c", "9s", "2h", "Jc", "Qd")) == PAIR
    assert category(v("7h", "8d", "4c", "9s", "2h", "Jc", "Qd")) == HIGH_CARD
    wheel = v("Ah", "2d", "3c", "4s", "5h")
    six_high = v("6h", "2d", "3c", "4s", "5h")
    assert six_high > wheel  # the wheel is the lowest straight
    # three pairs: the best two count, then the best other card (the third pair's rank here)
    assert v("Kh", "Kd", "Qc", "Qs", "3h", "3c", "2d") < v("Kh", "Kd", "Qc", "Qs", "2h", "2c", "Ad")  # KKQQ3 < KKQQA
    assert v("Kh", "Kd", "Qc", "Qs", "Ah", "3c", "3d") > v("Kh", "Kd", "Qc", "Qs", "Jh", "3c", "3d")
    assert v("Kh", "Kd", "Qc", "Qs", "4h", "3c", "3d") == v("Kh", "Kd", "Qc", "Qs", "4c", "2c", "2d")  # KKQQ4 both


def test_board_plays_is_a_split():
    board = ("Ah", "Kh", "Qh", "Jh", "Th")
    assert len(set(rank_range(board, [("2c", "3d"), ("As", "Ad"), ("9h", "8h")]).tolist())) == 1


def test_ranking_a_whole_range_is_fast():
    board = ("Ts", "Js", "Qs", "2h", "3d")
    combos = _all_combos(board)  # 1081 combos, every possible hand
    RiverRanker(board).values(combos)  # warm up
    start = time.perf_counter()
    for _ in range(5):
        rank_range(board, combos)
    per_board_ms = 1000 * (time.perf_counter() - start) / 5
    assert per_board_ms < 25, f"{per_board_ms:.1f} ms to rank every combo"


def test_impossible_combos_are_refused():
    ranker = RiverRanker(("Ah", "Kh", "Qh", "Jh", "Th"))
    with pytest.raises(ValueError):
        ranker.value(("Ah", "2c"))  # a board card
    with pytest.raises(ValueError):
        ranker.value(("2c", "2c"))
    with pytest.raises(ValueError):
        RiverRanker(("Ah", "Kh", "Qh", "Jh"))
    with pytest.raises(ValueError):
        hand_value(["Ah", "Ah", "Kh", "Qh", "Jh"])


def test_matchups_show_who_wins_and_which_deals_clash():
    board = ("Kh", "8d", "5c", "3s", "2h")
    a = [("Ks", "Kd"), ("Qs", "Qd"), ("As", "Ad")]
    b = [("Qs", "Qh"), ("Jc", "Tc"), ("Ac", "Ah")]
    outcome, possible = matchups(board, a, b)
    assert outcome.shape == possible.shape == (3, 3)
    assert outcome[0].tolist() == [1, 1, 1]  # trips beat everything here
    assert outcome[1].tolist() == [0, 1, -1]  # QQ splits with QQ, beats JT, loses to AA
    assert possible[1].tolist() == [False, True, True]  # QsQd and QsQh share the Qs
    assert possible[0].all() and possible[2].all()
    rev_outcome, rev_possible = matchups(board, b, a)
    assert np.array_equal(rev_outcome, -outcome.T) and np.array_equal(rev_possible, possible.T)


def test_dense_ranks():
    assert dense_ranks([50, 10, 50, 30]).tolist() == [2, 0, 2, 1]
