"""The river solver (app/solver/cfr.py, solve_river): it converges, it repeats exactly, it
keeps to its budget, and its own exploitability number is the checker's."""
import numpy as np
import pytest

from app.solver import IP, OOP, BetSizes, RiverSpot, solve_river
from app.solver.cfr import RiverCFR
from app.solver.exploitability import exploitability
from app.solver.timing import benchmark_spots

from .solver_games import half_street_spot

BOARD = ("Kh", "8d", "5c", "3s", "2h")


def real_spot(pot=100.0, stack=300.0):
    """Two overlapping ranges, the default sizes (half pot, pot, all in, one raise)."""
    return RiverSpot(BOARD, pot, (stack, stack), "TT+, AK, AQ, KQ, KJs, A5s, 76s, 65s, 44",
                     "88+, AK, AQs, KQ, KTs, QJs, JTs, A4s, 64s, 33")


def _trace(spot, method, checkpoints):
    solver = RiverCFR(spot, method)
    out = {}
    for t in range(1, max(checkpoints) + 1):
        solver.iterate()
        if t in checkpoints:
            out[t] = solver.exploitability()
    return out


# ------------------------------------------------- 2. it converges to zero
@pytest.mark.parametrize("method", ["dcfr", "cfr+"])
@pytest.mark.parametrize("make", [lambda: half_street_spot(1.0), real_spot, lambda: benchmark_spots(1, 3, "narrow")[0]],
                         ids=["half-street", "two ranges", "benchmark spot"])
def test_exploitability_falls_toward_zero_as_iterations_grow(make, method):
    e = _trace(make(), method, (10, 100, 1000))
    assert e[10] > e[100] > e[1000] >= -1e-12
    assert e[100] < e[10] / 3 and e[1000] < e[100] / 3  # each tenfold run cuts it at least threefold
    assert e[1000] < 0.001  # under 0.1% of the pot after 1000 iterations


def test_many_iterations_get_very_close_to_zero():
    e = _trace(half_street_spot(1.0), "dcfr", (5000,))
    assert e[5000] < 1e-5  # a thousandth of a percent of the pot


def test_dcfr_is_the_default_because_it_converges_faster():
    # the same four spots, the same 200 iterations: Discounted CFR ends lower on every one
    for spot in benchmark_spots(4, seed=2, ranges="narrow"):
        assert _trace(spot, "dcfr", (200,))[200] < _trace(spot, "cfr+", (200,))[200]


# ------------------------------------------------------- the entry point
def test_solver_repeats_exactly_and_reports_the_checkers_number():
    a = solve_river(real_spot(), None, max_iterations=150, target_exploitability=0)
    b = solve_river(real_spot(), None, max_iterations=150, target_exploitability=0)
    assert a.iterations == b.iterations == 150
    assert all(np.array_equal(a.probs[k], b.probs[k]) for k in a.probs)
    assert a.exploitability == pytest.approx(exploitability(a).pot_share, abs=1e-9)


def test_solver_stops_at_its_target():
    loose = solve_river(real_spot(), None, target_exploitability=0.01)
    tight = solve_river(real_spot(), None, target_exploitability=0.001)
    assert loose.exploitability <= 0.01 and tight.exploitability <= 0.001
    assert loose.iterations < tight.iterations


def test_solver_keeps_to_its_time_budget():
    spot = benchmark_spots(1, seed=5, ranges="medium")[0]
    st = solve_river(spot, 80, target_exploitability=0)
    assert st.iterations > 5
    assert st.elapsed_ms <= 80 * 1.25  # the budget, with room for a slow moment on a busy machine


def test_one_iteration_always_runs_and_something_must_stop_it():
    st = solve_river(real_spot(), 0.001)
    assert st.iterations == 1 and st.exploitability > 0
    with pytest.raises(ValueError):
        solve_river(real_spot(), None, target_exploitability=0)
    with pytest.raises(ValueError):
        solve_river(real_spot(), 100, method="guess")


def test_the_answer_does_not_depend_on_the_chip_unit():
    # the same spot in chips and in pots: same strategy at every node
    a = solve_river(real_spot(100.0, 300.0), None, max_iterations=100, target_exploitability=0)
    b = solve_river(real_spot(1.0, 3.0), None, max_iterations=100, target_exploitability=0)
    assert a.exploitability == pytest.approx(b.exploitability, abs=1e-9)
    ka = [n.key for n in a.tree.decision_nodes()]
    kb = [n.key for n in b.tree.decision_nodes()]
    assert len(ka) == len(kb)
    for x, y in zip(ka, kb):
        assert np.allclose(a.probs[x], b.probs[y], atol=1e-9)


# ------------------------------------------------- the play makes sense
def test_the_nuts_never_fold_and_air_never_calls():
    # In position holds the nuts (KK, top set) or nothing (JT); out of position holds QQ
    # and may bet into them or check and call.
    spot = RiverSpot(BOARD, 100, (300, 300), "QQ", "KK, JT", BetSizes((0.5,), (1.0,), True),
                     BetSizes((0.5, 1.0), (1.0,), True))
    st = solve_river(spot, None, target_exploitability=0.0005)
    facing = st.tree["b50"]  # out of position bets 50
    kings = st.action_probs("b50", ("Ks", "Kd"))
    jack_ten = st.action_probs("b50", ("Js", "Ts"))
    assert kings["f"] < 0.001  # the nuts never fold
    assert jack_ten["c"] < 0.001  # jack high can't win a showdown: it never just calls
    assert set(facing.actions) >= {"f", "c"}
    e = exploitability(st)
    assert e.value[OOP] + e.value[IP] == pytest.approx(100.0)
