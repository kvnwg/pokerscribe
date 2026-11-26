"""TUNING["river_solver"]: the advice uses the river solver only when the switch is on and
the solver answers in time, and the rules otherwise. Plus the bridge between the two."""
import time

import pytest

import app.solver as solver
from app.poker import advice
from app.solver import IP, OOP, GameTree, RiverStrategy
from app.solver.bridge import recommend, river_decision
from app.state.model import Action

from .test_advice import go, table

BOARD = ["Ac", "8d", "5c", "2h", "Js"]
HEADS_UP = dict(folded=["SB", "UTG", "HJ", "CO"])  # the big blind against the button


def first_to_act():  # hero in the big blind, out of position, nobody has bet
    return table(["Ah", "Kd"], "BB", BOARD, bets={}, pot=200, to_call=0,
                 actions=[Action("check"), Action("bet", 10)], **HEADS_UP)


def checked_to():  # hero on the button, the big blind checked
    return table(["Ah", "Kd"], "BTN", BOARD, bets={}, pot=200, to_call=0, last={"BB": Action("check")},
                 actions=[Action("check"), Action("bet", 10)], **HEADS_UP)


def facing_bet(stack=1000.0):  # hero in the big blind checked, the button bet 100 into 200
    return table(["Ah", "Kd"], "BB", BOARD, bets={"BTN": 100}, pot=200, to_call=100,
                 stacks={"BB": stack, "BTN": stack}, last={"BTN": Action("bet", 100)},
                 actions=[Action("fold"), Action("call", 100), Action("raise", 200)], **HEADS_UP)


SPOTS = [first_to_act, checked_to, facing_bet]


def picks(wanted):
    """A fake solver that plays `wanted` wherever it can (else the node's first action)."""
    def solve(spot, budget_ms):
        return RiverStrategy.from_rule(spot, lambda node, combo: {wanted if wanted in node.actions
                                                                  else node.actions[0]: 1.0})
    return solve


@pytest.fixture
def switch_on(monkeypatch):
    monkeypatch.setitem(advice.TUNING, "river_solver", True)


def _never_called(spot, budget_ms):
    raise AssertionError("the solver must not be called")


# ------------------------------------------------------------- the switch
def test_the_switch_is_off_in_the_baseline():
    assert advice.TUNING["river_solver"] is False


@pytest.mark.parametrize("make", SPOTS)
def test_switch_off_never_calls_the_solver(make, monkeypatch):
    monkeypatch.setattr(solver, "solve_river", _never_called)
    assert go(make()).basis != "solver"


@pytest.mark.parametrize("make", SPOTS)
def test_a_missing_solver_falls_back_to_the_rules(make, monkeypatch):
    def not_written(spot, budget_ms):
        raise NotImplementedError

    before = go(make()).to_dict()
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    monkeypatch.setattr(solver, "solve_river", not_written)
    assert go(make()).to_dict() == before


@pytest.mark.parametrize("make", SPOTS)
def test_a_slow_solver_falls_back_to_the_rules(make, monkeypatch):
    before = go(make()).to_dict()
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    monkeypatch.setattr(solver, "DECISION_BUDGET_MS", 20)

    def slow(spot, budget_ms):
        time.sleep(0.04)
        return picks("x")(spot, budget_ms)

    monkeypatch.setattr(solver, "solve_river", slow)
    assert go(make()).to_dict() == before


def test_a_failing_solver_falls_back_to_the_rules(monkeypatch, switch_on):
    def broken(spot, budget_ms):
        raise RuntimeError("bug")

    monkeypatch.setattr(solver, "solve_river", broken)
    monkeypatch.setitem(advice.TUNING, "river_solver", False)
    before = go(facing_bet()).to_dict()
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    assert go(facing_bet()).to_dict() == before


def test_the_solver_is_only_used_heads_up_on_the_river_with_reliable_numbers(monkeypatch, switch_on):
    monkeypatch.setattr(solver, "solve_river", _never_called)
    flop = table(["Ah", "Kd"], "BB", BOARD[:3], bets={}, pot=200, to_call=0,
                 actions=[Action("check"), Action("bet", 10)], **HEADS_UP)
    multiway = table(["Ah", "Kd"], "BB", BOARD, bets={}, pot=200, to_call=0, folded=["SB", "UTG", "HJ"],
                     actions=[Action("check"), Action("bet", 10)])
    raised = table(["Ah", "Kd"], "BB", BOARD, bets={"BB": 100, "BTN": 300}, pot=200, to_call=200,
                   last={"BTN": Action("raise", 300)},
                   actions=[Action("fold"), Action("call", 200), Action("raise", 500)], **HEADS_UP)
    for st in (flop, multiway, raised):
        assert go(st).basis != "solver"
    unchecked = advice.advise(facing_bet(), budget_ms=250, numbers_checked=False)
    assert unchecked.basis != "solver"


# ---------------------------------------------------- the solver's action
def test_solver_bet_becomes_the_instruction(monkeypatch, switch_on):
    monkeypatch.setattr(solver, "solve_river", picks("b100"))  # half the pot of 200
    a = go(first_to_act())
    assert (a.action, a.headline, a.amount, a.basis) == ("bet", "BET 100", 100.0, "solver")
    assert "river solver" in a.reason and "bet 100 100%" in a.detail


def test_solver_check_when_checked_to(monkeypatch, switch_on):
    monkeypatch.setattr(solver, "solve_river", picks("x"))
    a = go(checked_to())
    assert (a.action, a.headline, a.basis) == ("check", "CHECK", "solver")


def test_solver_call_fold_and_raise_facing_a_bet(monkeypatch, switch_on):
    monkeypatch.setattr(solver, "solve_river", picks("c"))
    a = go(facing_bet())
    assert (a.action, a.headline, a.amount, a.basis) == ("call", "CALL 100", 100.0, "solver")
    monkeypatch.setattr(solver, "solve_river", picks("f"))
    a = go(facing_bet())
    assert (a.action, a.headline, a.basis) == ("fold", "FOLD", "solver")
    # raise the pot after calling: 100 + 1.0 x (200 + 2 x 100) = 500; deep enough to stay a raise
    monkeypatch.setattr(solver, "solve_river", picks("r500"))
    a = go(facing_bet(stack=2000.0))
    assert (a.action, a.headline, a.amount, a.basis) == ("raise", "RAISE TO 500", 500.0, "solver")


def test_the_solver_sees_the_real_spot(monkeypatch, switch_on):
    seen = {}

    def spy(spot, budget_ms):
        seen["spot"], seen["budget"] = spot, budget_ms
        return picks("c")(spot, budget_ms)

    monkeypatch.setattr(solver, "solve_river", spy)
    go(facing_bet())
    spot = seen["spot"]
    assert spot.board == tuple(BOARD) and spot.pot == 200 and spot.effective_stack == 1000
    assert "b100" in GameTree(spot)["x"].actions  # their real bet is in the tree
    assert seen["budget"] == solver.DECISION_BUDGET_MS
    assert spot.index(OOP, ("Ah", "Kd")) >= 0  # the hero's hand is in the hero's range


# ------------------------------------------------- the real solver, end to end
def test_real_solver_through_the_advice(monkeypatch, switch_on):
    # The real solver, given half its usual time so a slow moment on a busy machine can't
    # push it past the budget the advice checks (that would be a correct fall back to the
    # rules, but not what this test is about).
    real = solver.solve_river
    monkeypatch.setattr(solver, "solve_river", lambda spot, budget_ms: real(spot, budget_ms / 2))
    # A set of eights facing a half-pot bet: the solver's instruction, never a fold.
    st = table(["8h", "8s"], "BB", BOARD, bets={"BTN": 100}, pot=200, to_call=100,
               last={"BTN": Action("bet", 100)},
               actions=[Action("fold"), Action("call", 100), Action("raise", 200)], **HEADS_UP)
    a = go(st)
    assert a.basis == "solver" and a.action in ("call", "raise", "all-in")
    assert "river solver" in a.reason and "%" in a.detail
    # Seven high, checked to on the button: the solver may bluff or give up, but it decides.
    air = table(["7c", "4d"], "BTN", BOARD, bets={}, pot=200, to_call=0, last={"BB": Action("check")},
                actions=[Action("check"), Action("bet", 10)], **HEADS_UP)
    a = go(air)
    assert a.basis == "solver" and a.action in ("check", "bet", "all-in")


def test_the_switch_is_still_off_with_the_real_solver(monkeypatch):
    def never(spot, budget_ms):
        raise AssertionError("the solver must not be called while the switch is off")

    monkeypatch.setattr(solver, "solve_river", never)
    assert advice.TUNING["river_solver"] is False
    assert go(facing_bet()).basis != "solver"


# ---------------------------------------------------------------- bridge
def _decision(**kw):
    args = dict(hero_cards=("Kd", "Ah"), board=BOARD, pot_now=200, hero_bet=0, villain_bet=0, hero_stack=1000,
                villain_stack=1000, hero_in_position=False)
    args.update(kw)
    return river_decision(**args)


def test_bridge_finds_the_hero_node():
    d = _decision()
    assert (d.node, d.hero, d.combo, d.spot.pot) == ("", OOP, ("Ah", "Kd"), 200)
    assert _decision(hero_in_position=True).node == "x"
    # facing a bet of 70 into 200: the spot starts at the river pot (270 - 70) and holds the real bet
    d = _decision(pot_now=270, villain_bet=70)
    assert (d.node, d.spot.pot) == ("x b70", 200)
    d = _decision(pot_now=270, villain_bet=70, hero_in_position=True)
    assert (d.node, d.hero) == ("b70", IP)


def test_bridge_caps_a_bet_bigger_than_the_hero_stack():
    d = _decision(pot_now=1700, villain_bet=1500, hero_stack=400, villain_stack=500)
    assert d.spot.effective_stack == 400 and d.node == "x b400"


def test_bridge_adds_the_hero_hand_to_the_hero_range():
    d = _decision(hero_cards=("7c", "2d"))  # far outside the medium range
    assert d.spot.index(OOP, ("7c", "2d")) >= 0


def test_bridge_leaves_raises_and_empty_pots_to_the_rules():
    assert _decision(hero_bet=100, villain_bet=300, pot_now=600) is None
    assert _decision(pot_now=0) is None
    assert _decision(board=BOARD[:4]) is None
    assert _decision(hero_cards=("Ac", "Kd")) is None  # Ac is on the board


def test_recommend_takes_the_most_likely_action():
    d = _decision()
    st = RiverStrategy.from_rule(d.spot, lambda node, combo: [1 / len(node.actions)] * len(node.actions))
    best, probs = recommend(st, d)
    assert best == "x" and sum(probs.values()) == pytest.approx(1)  # a tie: the first action
    st = RiverStrategy.from_rule(d.spot, lambda node, combo: {node.actions[-1]: 0.6, node.actions[0]: 0.4})
    assert recommend(st, d)[0] == "b1000"
