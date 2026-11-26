"""Phase 1: the heads-up simulator mode (tools/simulate.py and tools/compare.py --players 2).

Heads-up rules: the button posts the small blind and the other player the big blind; the
button acts first before the flop and last after it. Each deal is played twice with the
seats swapped. B0 plays heads-up without always-wrong instructions, and six-max plays
exactly as it did before the heads-up mode was added."""
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
        import simulate
    finally:
        sys.path.remove(TOOLS)
    return simulate, compare


def _moves(rec):
    """(board cards, seat) of every move in a played hand, in order."""
    out = []
    for kind, idx in rec["events"]:
        if kind == "app":
            out.append((rec["spots"][idx]["board_len"], rec["me"]))
        elif kind == "bot":
            snap = rec["bot_decisions"][idx]
            out.append((len(snap["board"]), snap["i"]))
    return out


def test_heads_up_blinds_and_order_of_play(tools):
    """On every street the right player acts first: the button (the small blind) before the
    flop, the big blind after it; and the button has the small blind in, the other the big."""
    sim, compare = tools
    streets, app_seats = set(), set()
    for k in range(40):
        stats = compare.new_stats()
        styles, names = sim.seating("maniacs", 9, k, players=2)
        sim.play_hand(styles, k % 2, 1000 + k, 0, 100.0, stats, names=names)
        rec = stats["last"]
        me = rec["me"]
        button = me if rec["pos"] == "BTN/SB" else 1 - me
        app_seats.add(rec["pos"])
        moves = _moves(rec)
        for board in sorted({b for b, _ in moves}):
            first = next(i for b, i in moves if b == board)
            assert first == (button if board == 0 else 1 - button), (k, board, moves)
            streets.add(board)
        # the first move of the hand is the button's, facing the big blind with the small one in
        if moves[0][1] == me:
            sp = rec["spots"][0]
            assert (sp["pos"], sp["put_in_bb"], sp["to_call_bb"], sp["current_bb"]) == ("BTN/SB", 0.5, 0.5, 1.0)
        else:
            snap = rec["bot_decisions"][0]
            assert (snap["bet"], snap["current"], snap["put_in"][me]) == (sim.SB, sim.BB, sim.BB)
        assert rec["final_put_in"][button] >= sim.SB and rec["final_put_in"][1 - button] >= sim.BB
    assert streets == {0, 3, 4, 5} and app_seats == {"BTN/SB", "BB"}


def test_heads_up_seats_are_named_as_the_app_reads_them(tools):
    """The simulator names the two seats as the reader does (app.state.positions): the button
    is "BTN/SB", the other "BB"."""
    sim, _ = tools
    from app.state.positions import assign_positions

    h = sim.Hand(seats=[sim.Seat("app", stack=200.0, cards=("As", "Kd")), sim.Seat("tag", stack=200.0)], button=1)
    assert [h.position(i) for i in range(2)] == ["BB", "BTN/SB"]
    assert assign_positions([0, 1], 1) == {1: "BTN/SB", 0: "BB"}
    st = sim.app_state(h, 0)
    assert [(p.seat, p.position.value, p.is_hero) for p in st.players] == [(0, "BB", True), (1, "BTN/SB", False)]
    assert sim.blind_seats(1, 2) == (1, 0) and sim.blind_seats(1, 6) == (2, 3)
    assert sim.first_to_act(1, 2, preflop=True) == 1 and sim.first_to_act(1, 2, preflop=False) == 0
    assert sim.first_to_act(1, 6, preflop=True) == 4 and sim.first_to_act(1, 6, preflop=False) == 2


def test_each_heads_up_deal_is_played_twice_with_the_seats_swapped(tools):
    """Duplicate heads-up: the two plays of a deck give the app each player's cards once, from
    that player's seat, against the same bot and on the same board."""
    sim, compare = tools
    recs = []
    for k in (14, 15):
        d, r = compare.deal(k, "duplicate", players=2)
        assert (d, r) == (7, k - 14)
        stats = compare.new_stats()
        styles, names = sim.seating("mixed", 5, d, players=2)
        sim.play_hand(styles, d % 2, 777, 0, 100.0, stats, names=names, rotate=r, keyed=True)
        recs.append(stats["last"])
    a, b = recs
    deck = list(sim.hands.DECK)
    random.Random(777).shuffle(deck)
    assert a["cards"] == b["cards"][::-1]  # the app (seat 0) holds the bot's cards of the other play
    assert {a["cards"][0], b["cards"][0]} == {(deck[0], deck[1]), (deck[2], deck[3])}
    assert {a["pos"], b["pos"]} == {"BTN/SB", "BB"}
    assert a["seats"] == b["seats"] and len(a["seats"]) == 2  # the same bot
    assert a["board"] == b["board"] == tuple(deck[4:9])


def test_heads_up_paired_runs(tools):
    """A variant against itself never differs; a real comparison repeats exactly and gives the
    same hands split over two processes; standard errors count the two hands of a deck as one."""
    _, compare = tools
    same = compare.paired({}, {}, 8, "mixed", 5, method="duplicate", resample=3, redeal=True, exact_luck=True,
                          players=2)
    assert same[3] == 0 and all(x == 0 for x in same[2]) and all(x == 0 for x in same[4]["resampled"])
    assert same[4]["decks"] == [0, 0, 1, 1, 2, 2, 3, 3]
    kw = dict(method="duplicate", resample=3, redeal=True, exact_luck=True, players=2)
    one = compare.paired({}, {"bet_size": 0.5}, 16, "stations", 4, **kw)
    split = compare.run_paired({}, {"bet_size": 0.5}, 16, "stations", 4, jobs=2, **kw)
    assert one[3] > 0  # some hands differ, so the replays were used
    assert one[2] == split[2] and one[4]["resampled"] == split[4]["resampled"] and one[4]["decks"] == split[4]["decks"]
    assert one[0]["hands"] == split[0]["hands"] and one[3] == split[3]
    classic = compare.paired({}, {"bet_size": 0.5}, 6, "stations", 4, method="classic", players=2)
    assert classic[4]["decks"] == list(range(6))


def test_check_advice_flags_moves_the_table_cant_take(tools):
    """The always-wrong checks added with the heads-up mode: a bet under the minimum (B0 once
    said BET 1.5 into a pot of two big blinds, six-max), CALL or CHECK when the other is the
    move, and folding aces before the flop."""
    sim, compare = tools
    from app.poker.advice import Advice

    h = sim.Hand(seats=[sim.Seat("app", stack=198.0, cards=("As", "3d")), sim.Seat("tag", stack=198.0)], button=1,
                 board=["Kh", "3c", "9h", "Kd"], pot_before=4.0)
    stats = compare.new_stats()
    sim.check_advice(h, 0, Advice("bet", "BET 1.5", "x", amount=1.5), stats)
    sim.check_advice(h, 0, Advice("bet", "BET 2", "x", amount=2.0), stats)  # the minimum: fine
    sim.check_advice(h, 0, Advice("call", "CALL", "x"), stats)
    h.current = 4.0  # now they bet 4
    sim.check_advice(h, 0, Advice("check", "CHECK", "x"), stats)
    sim.check_advice(h, 0, Advice("raise", "RAISE TO 500", "x", amount=500.0), stats)
    h.board, h.seats[0].cards = [], ("Ah", "Ad")
    sim.check_advice(h, 0, Advice("fold", "FOLD", "x"), stats)
    assert dict(stats["problems"]) == {"below the minimum bet or raise": 1, "call with nothing to call": 1,
                                       "check facing a bet": 1, "more than the stack": 1,
                                       "folded AA before the flop": 1}


@pytest.mark.parametrize("table,stacks", [("mixed", "even"), ("fish247", "tourney"), ("heldout", "uneven")])
def test_b0_plays_heads_up_without_always_wrong_instructions(tools, table, stacks):
    """B0 (the frozen defaults) heads-up: no instruction that is wrong whatever the strategy
    (simulate.check_advice), from both seats."""
    sim, _ = tools
    st = sim.run(60, table, 4, quiet=True, stacks=stacks, players=2)
    assert len(st["hands"]) == 60 and not st["problems"], (dict(st["problems"]), st["examples"][:3])
    assert set(st["by_pos"]) == {"BTN/SB", "BB"}


def test_six_max_unchanged_by_the_heads_up_mode(tools):
    """Six-max deals, plays and replays exactly as before the heads-up mode (values from the
    commit before it, d0b6db0)."""
    sim, compare = tools
    sa, _, diffs, replayed, extra = compare.paired({}, {"bet_size": 0.5}, 24, "stations", 4, method="duplicate",
                                                   resample=3, redeal=True, exact_luck=True)
    assert (round(sum(sa["hands"]), 4), round(sum(diffs), 4), round(sum(extra["resampled"]), 4), replayed) == (
        81.1624, -21.0, -25.6813, 3)
    st = sim.run(18, "heldout", 3, quiet=True, stacks="uneven")
    assert round(sum(st["hands"]), 4) == 2.2178
    assert [round(x, 4) for x in st["hands"][:6]] == [0.0, 0.0, 0.0, 0.0, 4.2178, -0.5]
