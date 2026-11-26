"""Heads-up push-or-fold (app/solver/pushfold.py) against the published equilibrium, and
the exact equity table it stands on.

Tolerances (stated up front, see docs/research/experiments.md for the measured numbers):
- exploitability at or under 0.00001 big blinds a hand;
- jam and call shares within 1.5 points of the shares read off the published chart, and
  the two shares quoted from The Mathematics of Poker within 1 point;
- a hand may differ from the chart only where the choice hardly matters: the two actions
  are worth within 0.01 big blinds of each other. The chart gives one cutoff per hand, but
  a few suited hands switch between jam and fold more than once as the stack changes, so
  near those switches the chart is a simplification, not a mistake of either side;
- the chart itself, played in our game, can be exploited for at most 0.0002 big blinds a
  hand: proof that the game and the equities are the same ones.
"""
import itertools
import random

import numpy as np
import pytest

from app.poker import hands
from app.poker.equity import equity as sampled_equity
from app.poker.ranges import class_combos
from app.solver.pushfold import (CLASS_INDEX, CLASSES, COMBOS, _Game, class_of, load_equity, solve_push_fold)
from tools import build_preflop_equity as build

from .pushfold_chart import BOOK_JAM_SHARES, PUBLISHED_SHARES, chart_calls, chart_pushes, chart_share

STACKS = (5, 8, 10, 12, 15)
MAX_EXPLOITABILITY = 1e-5  # big blinds a hand
SHARE_TOL = 0.015
BOOK_TOL = 0.01
INDIFFERENT = 0.01  # big blinds: hands this close between their two actions may differ from the chart
CHART_EXPLOITABILITY = 2e-4


@pytest.fixture(scope="module")
def solutions():
    return {s: solve_push_fold(s, target_exploitability=1e-6) for s in STACKS}


# --------------------------------------------------------- the equity table
def test_hand_classes_are_in_chart_order():
    assert len(CLASSES) == 169 and CLASSES[0] == "AA" and CLASSES[1] == "AKs" and CLASSES[13] == "AKo"
    assert CLASSES[-1] == "22" and COMBOS.sum() == 1326
    assert class_of(("Kd", "Ah")) == "AKo" and class_of(("7s", "2s")) == "72s" and class_of(("9c", "9d")) == "99"


def test_equity_table_is_consistent():
    eq, pairs = load_equity()
    assert eq.shape == pairs.shape == (169, 169)
    assert np.allclose(eq + eq.T, 1.0, atol=1e-12)  # one side's win is the other's loss
    assert pairs.sum() == 1326 * 1225  # every pair of hands that share no card
    assert pairs[CLASS_INDEX["AA"], CLASS_INDEX["AA"]] == 6  # AsAh against AdAc, and so on
    assert pairs[CLASS_INDEX["AA"], CLASS_INDEX["KK"]] == 36
    assert pairs[CLASS_INDEX["AKs"], CLASS_INDEX["AKs"]] == 12
    # AA against KK, enumerated combo by combo over all 1,712,304 boards by the build
    # script's --verify: 0.819460505
    assert eq[CLASS_INDEX["AA"], CLASS_INDEX["KK"]] == pytest.approx(0.819460505, abs=1e-9)


@pytest.mark.parametrize("a, b", [("AKs", "QQ"), ("72o", "AA"), ("JTs", "55"), ("K9o", "Q8s"), ("A5s", "A5o")])
def test_equity_table_agrees_with_sampling(a, b):
    """The app's own equity engine (treys, random boards) on a few matchups, averaged over
    the combos of both classes; the table must sit within four standard errors."""
    eq, _ = load_equity()
    total = var = weight = 0.0
    for hero in class_combos(a):
        villains = tuple(c for c in class_combos(b) if not set(c) & set(hero))
        if not villains:
            continue
        r = sampled_equity(hero, (), 1, villains, budget_s=5.0, max_iterations=4000)
        total += len(villains) * r.equity
        var += (len(villains) * r.stderr) ** 2
        weight += len(villains)
    assert eq[CLASS_INDEX[a], CLASS_INDEX[b]] == pytest.approx(total / weight, abs=4 * var ** 0.5 / weight + 1e-3)


def test_board_counting_matches_the_slow_way():
    """The build script counts wins and ties between classes on a board with a histogram
    and takes out the pairs that share a card. Here: every pair of combos one at a time,
    ranked by treys."""
    rng = random.Random(8)
    ids = sorted(rng.sample(range(52), 5))
    wins, ties = build.board_counts(np.array(ids))
    board = [build.DECK[c] for c in ids]
    combos = list(itertools.combinations([c for c in build.DECK if c not in board], 2))
    rank = [hands.evaluate(c, board) for c in combos]  # lower is better
    cls = [CLASS_INDEX[class_of(c)] for c in combos]
    slow_wins, slow_ties = np.zeros((169, 169)), np.zeros((169, 169))
    for i, a in enumerate(combos):
        for j, b in enumerate(combos):
            if a[0] in b or a[1] in b:
                continue
            if rank[i] < rank[j]:
                slow_wins[cls[i], cls[j]] += 1
            elif rank[i] == rank[j]:
                slow_ties[cls[i], cls[j]] += 1
    assert np.array_equal(wins, slow_wins) and np.array_equal(ties, slow_ties)


# ----------------------------------------------------------------- the game
def test_payoffs_by_hand():
    game = _Game(10.0, 0.5, 1.0)
    always, never = np.ones(169), np.zeros(169)
    assert game.value_sb(never, always) == pytest.approx(-0.5)  # folding every hand loses the small blind
    assert game.value_sb(always, never) == pytest.approx(1.0)  # jamming into a folder wins the big blind
    assert game.value_sb(always, always) == pytest.approx(0.0, abs=1e-12)  # all in blind against blind: even
    # Against a big blind who never calls, the best the small blind can do is jam everything
    # (+1). Against a small blind who always folds, the big blind collects 0.5 every hand.
    # So "never jam, never call" is exploitable for (1 + 0.5) / 2 = 0.75.
    assert game.exploitability(never, never) == pytest.approx(0.75)


def test_bad_input():
    with pytest.raises(ValueError):
        solve_push_fold(0.5)
    with pytest.raises(ValueError):
        solve_push_fold(10, method="guess")


# ------------------------------------------------------- 3. known results
@pytest.mark.parametrize("stack", STACKS)
def test_equilibrium_cannot_be_exploited(stack, solutions):
    sol = solutions[stack]
    assert 0 <= sol.exploitability <= MAX_EXPLOITABILITY
    assert sol.jams("AA") == pytest.approx(1) and sol.calls("AA") == pytest.approx(1)
    assert sol.calls("32o") == pytest.approx(0, abs=1e-3) or stack <= 5


def test_exploitability_falls_as_iterations_grow():
    e = [solve_push_fold(10, max_iterations=n, target_exploitability=0).exploitability for n in (50, 500, 5000)]
    assert e[0] > e[1] > e[2] and e[2] < 1e-6


@pytest.mark.parametrize("stack", STACKS)
def test_shares_match_the_published_chart(stack, solutions):
    sol = solutions[stack]
    assert sol.jam_share == pytest.approx(chart_share(stack, "jam"), abs=SHARE_TOL)
    assert sol.call_share == pytest.approx(chart_share(stack, "call"), abs=SHARE_TOL)


@pytest.mark.parametrize("stack", sorted(BOOK_JAM_SHARES))
def test_jam_share_matches_the_book(stack, solutions):
    # The Mathematics of Poker: about 62% of hands at 8 big blinds, 58% at 10
    assert solutions[stack].jam_share == pytest.approx(BOOK_JAM_SHARES[stack], abs=BOOK_TOL)


@pytest.mark.parametrize("stack", STACKS)
def test_hands_differ_from_the_chart_only_where_it_hardly_matters(stack, solutions):
    sol = solutions[stack]
    game = _Game(float(stack), 0.5, 1.0)
    sb = game.sb_values(sol.call)
    bb = game.bb_values(sol.jam)
    faced = game.n.T @ sol.jam  # how often each big blind hand faces a jam
    differ = []
    for i, hand in enumerate(CLASSES):
        if (sol.jam[i] >= 0.5) != chart_pushes(hand, stack):
            gap = abs(sb[i, 1] - sb[i, 0]) / game.dealt[i]
            differ.append(("jam", hand))
            assert gap < INDIFFERENT, f"{hand} at {stack}bb: jamming and folding differ by {gap:.4f}bb"
        if (sol.call[i] >= 0.5) != chart_calls(hand, stack):
            gap = abs(bb[i, 1] - bb[i, 0]) / faced[i]
            differ.append(("call", hand))
            assert gap < INDIFFERENT, f"{hand} at {stack}bb: calling and folding differ by {gap:.4f}bb"
    assert len(differ) <= 3, differ


@pytest.mark.parametrize("stack", STACKS)
def test_the_published_chart_is_an_equilibrium_of_our_game(stack, solutions):
    game = _Game(float(stack), 0.5, 1.0)
    jam = np.array([1.0 if chart_pushes(h, stack) else 0.0 for h in CLASSES])
    call = np.array([1.0 if chart_calls(h, stack) else 0.0 for h in CLASSES])
    assert game.exploitability(jam, call) <= CHART_EXPLOITABILITY
    assert game.value_sb(jam, call) == pytest.approx(solutions[stack].value_sb, abs=CHART_EXPLOITABILITY)


def test_the_small_blind_stops_profiting_near_eight_big_blinds(solutions):
    # short stacks favour the jammer; from about 8 big blinds on, being forced to jam or
    # fold costs the small blind (PokerStrategy: positive under 7.5, about -0.1 at 15 to 20)
    assert solutions[5].value_sb > 0 > solutions[8].value_sb > solutions[10].value_sb > solutions[15].value_sb
    assert solutions[15].value_sb == pytest.approx(-0.13, abs=0.03)


def test_a_second_published_table_is_close_at_deeper_stacks(solutions):
    # PokerStrategy's shares come from another program and differ from the chart above at
    # short stacks; at 15 big blinds they agree with both.
    jam, call = PUBLISHED_SHARES[15]
    assert solutions[15].jam_share == pytest.approx(jam, abs=0.005)
    assert solutions[15].call_share == pytest.approx(call, abs=0.005)


def test_solution_helpers(solutions):
    sol = solutions[10]
    assert sol.grid("jam").splitlines()[1].startswith("A #")
    assert set(sol.mixed()) == {"jam", "call"}
    assert len(sol.mixed()["jam"]) <= 3 and len(sol.mixed()["call"]) <= 3  # nearly every hand is pure
