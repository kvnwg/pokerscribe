"""Phase 1 measurement: duplicate deals, keyed bot randomness and the luck adjustment
(tools/luck.py). The adjustment is only useful if it is unbiased, so the main checks are
that each correction averages exactly zero over the cards that can fall."""
import os
import random
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")


@pytest.fixture(scope="module")
def tools():
    sys.path.insert(0, TOOLS)
    try:
        import compare
        import luck
        import simulate
    finally:
        sys.path.remove(TOOLS)
    return simulate, luck, compare


CARDS = (("As", "Kd"), ("Qh", "Qc"), ("2c", "3d"), ("4h", "5h"), ("7s", "8s"), ("9d", "Tc"))


def _unseen(board):
    from app.poker import hands

    dead = set(board) | {c for pair in CARDS for c in pair}
    return [c for c in hands.DECK if c not in dead]


@pytest.mark.parametrize("board", [("Ah", "Qs", "6d", "2h"), ("Jh", "Ts", "6h"), ("Jh", "Ts", "6h", "3s")])
def test_value_before_a_card_is_the_average_after_it(tools, board):
    """The checked-down value is a martingale over the board cards, so every correction
    averages exactly zero: three players, one of them all in for less (a side pot)."""
    _, luck, _ = tools
    live, put_in = (0, 1, 3), (60.0, 100.0, 0.0, 100.0, 1.0, 2.0)
    for me in live:
        before = luck.value(CARDS, board, live, put_in, me)
        after = [luck.value(CARDS, board + (c,), live, put_in, me) for c in _unseen(board)]
        assert sum(after) / len(after) == pytest.approx(before, abs=1e-9)


def test_sampled_preflop_value_matches_the_flops(tools):
    """Before the flop the value is a sample of full boards; it agrees with the exact flop
    values averaged over random flops (and the same spot always gets the same sample)."""
    _, luck, _ = tools
    live, put_in = (0, 1), (100.0, 100.0, 0.0, 0.0, 1.0, 2.0)
    before = luck.value(CARDS, (), live, put_in, 0, key=7)
    assert before == luck.value(CARDS, (), live, put_in, 0, key=7)
    rng = random.Random(3)
    vals = []
    for _ in range(120):
        flop = tuple(rng.sample(_unseen(()), 3))
        vals.append(luck.value(CARDS, flop, live, put_in, 0))
    mean = sum(vals) / len(vals)
    se = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1) / len(vals)) ** 0.5
    assert abs(mean - before) < 4 * se + 2.0
    # AK against QQ for 100 each plus the blinds: the ace-king is a small underdog (43 to
    # 46% here, since the other dead cards are low)
    assert 203 * 0.42 - 100 < before < 203 * 0.47 - 100


def test_all_in_before_the_flop_adjusts_to_its_equity(tools):
    """All in before the flop: the luck-adjusted result is the hand's all-in value,
    whatever board came."""
    sim, luck, _ = tools
    live, put_in = (0, 1), (200.0, 200.0, 0.0, 0.0, 1.0, 2.0)
    board = ("2h", "7d", "Js", "Kc", "Ah")
    chance = [{"board": board[:a], "deal": board[a:b], "live": live, "put_in": put_in}
              for a, b in ((0, 3), (3, 4), (4, 5))]
    ranks = {i: sim.hands.evaluate(CARDS[i], board) for i in live}
    net = sim.split_pot(put_in, live, ranks)[0] - put_in[0]
    rec = {"cards": CARDS, "me": 0, "key": 11, "chance": chance, "net": net / sim.BB}
    expected = luck.value(CARDS, (), live, put_in, 0, key=luck.hash_key(11, (), live, put_in)) / sim.BB
    assert luck.adjusted(rec) == pytest.approx(expected, abs=1e-9)
    assert abs(luck.adjusted(rec)) < abs(rec["net"])  # the ace-king won a 400 pot, the adjustment takes most back


def test_all_in_luck_also_averages_zero(tools):
    """The second value (as if every live player had put in all its chips behind) is a
    checked-down value too, so its luck averages exactly zero over the next card; the extra
    feature is zero when nobody has chips behind, so the weights can't change an all-in hand."""
    _, luck, _ = tools
    board, live = ("Jh", "Ts", "6h", "3s"), (0, 1, 3)
    put_in, behind = (30.0, 30.0, 0.0, 30.0, 1.0, 2.0), (170.0, 40.0, 0.0, 90.0, 0.0, 0.0)
    full = luck.all_in(put_in, behind, live)
    assert full == (200.0, 70.0, 0.0, 120.0, 1.0, 2.0)
    for me in live:
        before = luck.values(CARDS, board, live, [put_in, full], me)
        after = [luck.values(CARDS, board + (c,), live, [put_in, full], me) for c in _unseen(board)]
        for k in (0, 1):
            assert sum(a[k] for a in after) / len(after) == pytest.approx(before[k], abs=1e-9)
    node = {"board": board, "deal": ("2d",), "live": (0, 1), "put_in": (200.0, 200.0, 0, 0, 1.0, 2.0),
            "behind": (0.0, 0.0, 0, 0, 0, 0)}
    rec = {"cards": CARDS, "me": 0, "key": 3, "chance": [node], "net": 0.0}
    f = luck.features(rec)
    assert all(x == 0 for x in f[1:])
    assert luck.adjusted(rec, weights=[5.0] * luck.N_FEATURES) == luck.adjusted(rec, weights=[0.0] * luck.N_FEATURES)


def test_frozen_weights(tools):
    """Every comparison uses the same fixed weights (fitted once on training hands)."""
    _, luck, _ = tools
    assert len(luck.WEIGHTS) == luck.N_FEATURES
    assert all(-3 < w < 3 for w in luck.WEIGHTS)
    assert luck.adjust(10.0, [2.0] + [1.0] * luck.N_FEATURES, [0.0] * luck.N_FEATURES) == 8.0


def test_duplicate_rotations_give_the_app_every_seat(tools):
    """The six rotations of a deck: the app holds each seat's cards from that seat's position."""
    sim, _, compare = tools
    seen = set()
    for r in range(6):
        stats = compare.new_stats()
        styles, names = sim.seating("mixed", 5, 0)
        sim.play_hand(styles, 2, 777, 0, 100.0, stats, names=names, rotate=r, keyed=True)
        seen.add((stats["last"]["cards"][0], stats["last"]["pos"]))
    rng = random.Random(777)
    deck = list(sim.hands.DECK)
    rng.shuffle(deck)
    slots = {(deck[2 * j], deck[2 * j + 1]): sim.POSITIONS[(j - 2) % 6] for j in range(6)}
    assert seen == set(slots.items())


def test_duplicate_paired_run_is_repeatable(tools):
    """The same variant against itself: nothing differs, every difference is zero, and two
    runs give the same hands (keyed bot randomness is deterministic)."""
    _, _, compare = tools
    a = compare.paired({}, {}, 12, "mixed", 5, method="duplicate", adjust_all=True)
    b = compare.paired({}, {}, 12, "mixed", 5, method="duplicate")
    assert a[0]["hands"] == b[0]["hands"]
    assert a[3] == 0 and all(d == 0 for d in a[2]) and all(d == 0 for d in a[4]["adjusted"])
    assert a[4]["decks"] == [0] * 6 + [1] * 6
    assert a[4]["base_adjusted"] == a[4]["other_adjusted"]


def test_keyed_randomness_aligns_the_bots(tools):
    """With keyed randomness a bot's n-th decision on a street draws the same numbers
    whatever happened before it in the hand."""
    sim, _, _ = tools
    h = sim.Hand(seats=[sim.Seat("app")] + [sim.Seat("tag") for _ in range(5)], button=0, rng_key=42)
    first = h.bot_rng(3, None).random()
    h.bot_rng(4, None)
    h2 = sim.Hand(seats=h.seats, button=0, rng_key=42)
    assert h2.bot_rng(3, None).random() == first
    assert h2.bot_rng(3, None).random() != first  # the next decision draws new numbers
    stream = random.Random(1)
    assert sim.Hand(seats=h.seats, button=0).bot_rng(3, stream) is stream  # classic: one stream


def test_clustered_standard_error(tools):
    """Decks as units: with one hand per unit it is the ordinary standard error; hands of a
    deck that cancel out count as one draw of their sum."""
    _, _, compare = tools
    vals = [1.0, -2.0, 3.5, 0.5, -1.0, 2.0]
    assert compare.summary(vals, list(range(6))) == pytest.approx(compare.summary(vals))
    m, se = compare.summary([5.0, -5.0, 3.0, -3.0], [0, 0, 1, 1])
    assert m == 0 and se == 0


def test_split_run_matches_one_process(tools):
    """compare --jobs: the hands split over processes by whole decks give exactly the same
    per-hand results as one process."""
    _, _, compare = tools
    one = compare.paired({}, {"bet_size": 0.5}, 24, "maniacs", 7, method="duplicate")
    split = compare.run_paired({}, {"bet_size": 0.5}, 24, "maniacs", 7, method="duplicate", jobs=2)
    assert one[2] == split[2] and one[0]["hands"] == split[0]["hands"] and one[1]["hands"] == split[1]["hands"]
    assert one[4]["adjusted"] == split[4]["adjusted"] and one[4]["decks"] == split[4]["decks"] and one[3] == split[3]


def test_resampling_from_the_split(tools):
    """--resample: hands where the variants differ are replayed from where they part with
    fresh bot numbers and board cards; a variant against itself never differs, and a real
    comparison gives the same averages whether split over processes or not."""
    _, _, compare = tools
    same = compare.paired({}, {}, 12, "maniacs", 3, method="duplicate", resample=3)
    assert all(x == 0 for x in same[4]["resampled"])
    one = compare.paired({}, {"bet_size": 0.5}, 24, "maniacs", 7, method="duplicate", resample=3)
    split = compare.run_paired({}, {"bet_size": 0.5}, 24, "maniacs", 7, method="duplicate", jobs=2, resample=3)
    assert one[4]["resampled"] == split[4]["resampled"] and len(one[4]["resampled"]) == 24
