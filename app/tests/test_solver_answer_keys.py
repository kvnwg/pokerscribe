"""Answer keys for the river solver: the half-street game of The Mathematics of Poker.

A balanced bettor using s times the pot bluffs s/(1+2s) of its bets; the caller defends
1/(1+s) of its range (KNOWLEDGE.md). The game, and the hand check of every expected number,
are in solver_games.py. test_solver_exploitability.py already proves these numbers are an
equilibrium (the hand-built strategy can't be exploited at all).

Skipped until solve_river exists: they run by themselves once it stops raising
NotImplementedError. Phase 2 gate: "matches closed-form results".
"""
import pytest

from app.solver import IP, OOP, solve_river
from app.solver.exploitability import exploitability

from .solver_games import (HALF_STREET, POT, bluff_share_of_bets, call_share, half_street_spot,
                           value_bet_share)

BUDGET_MS = 2000  # offline: the answer keys get more time than a live decision
MAX_EXPLOITABILITY = 0.002  # share of the pot
FREQ_TOL = 0.02  # how close each frequency must be


def _solver_ready() -> bool:
    try:
        solve_river(half_street_spot(1.0), 10)
    except NotImplementedError:
        return False
    return True


requires_solver = pytest.mark.skipif(not _solver_ready(), reason="the river solver isn't written yet (Phase 2)")


@requires_solver
@pytest.mark.parametrize("s", sorted(HALF_STREET))
def test_half_street_game(s):
    bluffs, calls, value = HALF_STREET[s]
    # s = 0.5: bluffs 1/4 of bets, calls 2/3, bettor wins 400/19 = 21.05 of the 100 pot
    # s = 0.75: bluffs 3/10, calls 4/7, bettor wins 3000/133 = 22.56
    # s = 1: bluffs 1/3, calls 1/2, bettor wins 450/19 = 23.68
    # s = 2: bluffs 2/5, calls 1/3, bettor wins 500/19 = 26.32
    st = solve_river(half_street_spot(s), BUDGET_MS)
    e = exploitability(st)
    assert e.pot_share <= MAX_EXPLOITABILITY, str(e)
    assert bluff_share_of_bets(st, s) == pytest.approx(float(bluffs), abs=FREQ_TOL)
    assert call_share(st, s) == pytest.approx(float(calls), abs=FREQ_TOL)
    assert value_bet_share(st, s) >= 1 - FREQ_TOL  # KK always bets
    assert e.value[IP] == pytest.approx(float(value), abs=MAX_EXPLOITABILITY * POT * 2)
    assert e.value[OOP] == pytest.approx(POT - float(value), abs=MAX_EXPLOITABILITY * POT * 2)


@requires_solver
def test_solver_reports_its_own_exploitability_and_respects_the_budget():
    st = solve_river(half_street_spot(1.0), 200)
    assert st.exploitability is not None
    assert st.exploitability == pytest.approx(exploitability(st).pot_share, abs=1e-6)
    assert st.elapsed_ms <= 200
