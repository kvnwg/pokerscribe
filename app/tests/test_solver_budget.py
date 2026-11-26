"""How the advice asks for a solve (app/solver/solve.py): a stop target that follows the
size of the pot, and a fixed amount of work in place of the clock for runs that must
repeat exactly (the simulator)."""
import time

import numpy as np
import pytest

import app.solver as solver
from app.solver import BetSizes, GameTree, RiverSpot, decision_settings, reference_iterations, solve_river, target_for
from app.solver import solve as solve_mod
from app.solver.timing import QUALITY_BAR, benchmark_spots

BOARD = ("Kh", "8d", "5c", "3s", "2h")


def spot(pot=100.0, stack=300.0, oop="TT+, AK, AQ, KQ, KJs, A5s, 76s, 65s, 44", ip="99+, AK, AQ, KQ, QJs, 87s, 33"):
    return RiverSpot(BOARD, pot, (stack, stack), oop, ip)


# ------------------------------------------------------------ the stop target
def test_the_target_is_the_same_in_chips_for_every_pot():
    # a hundredth of a big blind: 0.1% of 10 big blinds, 0.02% of 50, 0.4% of 2.5
    assert target_for(10) == pytest.approx(0.001)
    assert target_for(50) == pytest.approx(0.0002)
    assert target_for(2.5) == pytest.approx(0.004)
    for pot_bb in (2.5, 6.5, 16.5, 44, 65, 100):
        assert target_for(pot_bb) * pot_bb == pytest.approx(solve_mod.TARGET_BB)


def test_the_target_stays_between_its_limits():
    tightest, loosest = solve_mod.TARGET_SHARES
    assert target_for(1) == loosest and target_for(0.2) == loosest  # 1% and 5% of the pot would be too rough
    assert target_for(400) == tightest and target_for(1e6) == tightest
    assert loosest <= QUALITY_BAR / 2  # an answer that stopped at its target is always good enough to use
    assert all(target_for(a) >= target_for(b) for a, b in zip((1, 2, 5, 20, 80, 300), (2, 5, 20, 80, 300, 900)))


def test_an_unknown_pot_keeps_the_usual_target():
    for unknown in (None, 0, -3.0):
        assert target_for(unknown) == solve_mod.TARGET_EXPLOITABILITY


# ------------------------------------------------------------- a fixed amount of work
def test_reference_iterations_follow_the_size_of_the_spot():
    small, big = spot(oop="AA, KK", ip="QQ, JJ"), spot()
    # fixed + per unit x (combos of both players) x (ends of the hand in the tree), by hand
    fixed, per_unit = solve_mod.REFERENCE_MS
    ends = sum(1 for _ in GameTree(big).terminals())
    work = (len(big.combos(0)) + len(big.combos(1))) * ends
    assert reference_iterations(big) == int(300 / (fixed + per_unit * work))
    assert reference_iterations(small) > reference_iterations(big)  # fewer combos, more iterations
    assert reference_iterations(big, 600) > reference_iterations(big, 300) > reference_iterations(big, 100)
    # a smaller tree (one bet size, no raise) is cheaper per iteration
    plain = RiverSpot(BOARD, 100, (300, 300), big.oop_range, big.ip_range, BetSizes((1.0,), (), False),
                      BetSizes((1.0,), (), False), 0)
    assert reference_iterations(plain) > reference_iterations(big)
    assert reference_iterations(big, 0.001) == solve_mod.MIN_ITERATIONS  # never next to nothing


def test_reference_iterations_never_look_at_the_clock(monkeypatch):
    s = spot()
    usual = reference_iterations(s)
    monkeypatch.setattr(time, "perf_counter", lambda: 1e9)
    assert reference_iterations(s) == usual == reference_iterations(RiverSpot.from_dict(s.to_dict()))


def test_decision_settings():
    s = spot(pot=100.0)
    by_clock = decision_settings(s, big_blind=2.0)  # 50 big blinds in the pot
    assert by_clock == {"time_budget_ms": solver.DECISION_BUDGET_MS, "max_iterations": None,
                        "target_exploitability": pytest.approx(0.0002)}
    fixed = decision_settings(s, big_blind=2.0, repeatable=True)
    assert fixed == {"time_budget_ms": None, "max_iterations": reference_iterations(s),
                     "target_exploitability": pytest.approx(0.0002)}
    # the big blind isn't known: the usual share of the pot
    assert decision_settings(s)["target_exploitability"] == solve_mod.TARGET_EXPLOITABILITY
    assert decision_settings(s, big_blind=20.0)["target_exploitability"] == pytest.approx(0.002)


def _same(a, b) -> bool:
    return (a.iterations == b.iterations and a.exploitability == b.exploitability
            and all(np.array_equal(a.probs[k], b.probs[k]) for k in a.probs))


def test_fixed_work_gives_the_same_answer_every_run():
    for s in benchmark_spots(3, seed=5, ranges="narrow") + [spot()]:
        how = decision_settings(s, big_blind=s.pot / 30.0, repeatable=True)
        first, again = solve_river(s, **how), solve_river(s, **how)
        assert _same(first, again)
        assert first.iterations <= how["max_iterations"]


def test_fixed_work_does_not_depend_on_how_fast_the_machine_is(monkeypatch):
    s = spot()
    how = decision_settings(s, big_blind=2.0, repeatable=True)
    usual = solve_river(s, **how)
    ticks = iter(range(0, 10 ** 9, 50))  # a clock on which every look takes 50 seconds
    monkeypatch.setattr(time, "perf_counter", lambda: float(next(ticks)))
    slow = solve_river(s, **how)
    assert _same(usual, slow)


def test_a_small_pot_stops_sooner_than_a_big_one():
    # the same spot, counted as 2.5 and as 100 big blinds: the looser target needs fewer iterations
    s = spot()
    small = solve_river(s, **decision_settings(s, big_blind=s.pot / 2.5, repeatable=True))
    big = solve_river(s, **decision_settings(s, big_blind=s.pot / 100.0, repeatable=True))
    assert small.iterations < big.iterations
    assert small.exploitability <= target_for(2.5) < QUALITY_BAR
    assert big.exploitability < small.exploitability
