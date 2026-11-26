"""TUNING["river_solver"]: the advice uses the river solver only when the switch is on and
the solver answers in time, and the rules otherwise. Plus the bridge between the two."""
import time

import pytest

import app.solver as solver
from app.poker import advice
from app.poker.history import HERO, VILLAIN, Line, StreetLine
from app.solver import IP, OOP, GameTree, RiverStrategy
from app.solver import bridge as bridge_mod
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


def facing_raise(hero=("Ah", "Kd"), stack=1000.0):  # hero in the big blind bet 100 into 200, the button raised to 300
    return table(list(hero), "BB", BOARD, bets={"BB": 100, "BTN": 300}, pot=200, to_call=200,
                 stacks={"BB": stack - 100, "BTN": stack - 300}, last={"BTN": Action("raise", 300)},
                 actions=[Action("fold"), Action("call", 200), Action("raise", 500)], **HEADS_UP)


SPOTS = [first_to_act, checked_to, facing_bet, facing_raise]


def picks(wanted, at=None):
    """A fake solver that plays `wanted` wherever it can (or only at the node `at`), and
    every action equally often elsewhere (so both players get to every node)."""
    def solve(spot, time_budget_ms=None, **how):
        return RiverStrategy.from_rule(spot, lambda node, combo: (
            {wanted: 1.0} if wanted in node.actions and at in (None, node.key)
            else [1 / len(node.actions)] * len(node.actions)))
    return solve


@pytest.fixture
def switch_on(monkeypatch):
    monkeypatch.setitem(advice.TUNING, "river_solver", True)


def _never_called(spot, time_budget_ms=None, **how):
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
    def not_written(spot, time_budget_ms=None, **how):
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

    def slow(spot, time_budget_ms=None, **how):
        time.sleep(0.04)
        return picks("x")(spot)

    monkeypatch.setattr(solver, "solve_river", slow)
    assert go(make()).to_dict() == before


def test_a_failing_solver_falls_back_to_the_rules(monkeypatch, switch_on):
    def broken(spot, time_budget_ms=None, **how):
        raise RuntimeError("bug")

    monkeypatch.setattr(solver, "solve_river", broken)
    monkeypatch.setitem(advice.TUNING, "river_solver", False)
    before = go(facing_bet()).to_dict()
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    assert go(facing_bet()).to_dict() == before


def test_a_rough_answer_falls_back_to_the_rules(monkeypatch):
    # the solver ran out of time 5% of the pot away from an equilibrium (the bar is 1%)
    def rough(spot, time_budget_ms=None, **how):
        st = picks("f")(spot)
        st.exploitability = 0.05
        return st

    before = go(facing_bet()).to_dict()
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    monkeypatch.setattr(solver, "solve_river", rough)
    assert go(facing_bet()).to_dict() == before
    # the same answer, close enough: it is used
    def fine(spot, time_budget_ms=None, **how):
        st = picks("f")(spot)
        st.exploitability = 0.004
        return st

    monkeypatch.setattr(solver, "solve_river", fine)
    assert go(facing_bet()).basis == "solver"


def test_the_solver_is_only_used_heads_up_on_the_river_with_reliable_numbers(monkeypatch, switch_on):
    monkeypatch.setattr(solver, "solve_river", _never_called)
    flop = table(["Ah", "Kd"], "BB", BOARD[:3], bets={}, pot=200, to_call=0,
                 actions=[Action("check"), Action("bet", 10)], **HEADS_UP)
    multiway = table(["Ah", "Kd"], "BB", BOARD, bets={}, pot=200, to_call=0, folded=["SB", "UTG", "HJ"],
                     actions=[Action("check"), Action("bet", 10)])
    for st in (flop, multiway):
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


def test_solver_answers_a_raise_of_your_bet(monkeypatch, switch_on):
    here = "b100 r300"  # the hero bet 100, the button raised to 300
    monkeypatch.setattr(solver, "solve_river", picks("c", at=here))
    a = go(facing_raise())
    assert (a.action, a.headline, a.amount, a.basis) == ("call", "CALL 200", 200.0, "solver")
    monkeypatch.setattr(solver, "solve_river", picks("f", at=here))
    a = go(facing_raise())
    assert (a.action, a.headline, a.basis) == ("fold", "FOLD", "solver")
    # raising again is going all in: the only raise in the tree after a raise
    monkeypatch.setattr(solver, "solve_river", picks("r1000", at=here))
    a = go(facing_raise())
    assert (a.action, a.headline, a.amount, a.basis) == ("all-in", "ALL IN (1000)", 1000.0, "solver")


def test_the_solver_sees_the_raise(monkeypatch, switch_on):
    seen = {}

    def spy(spot, time_budget_ms=None, **how):
        seen["spot"] = spot
        return picks("c")(spot)

    monkeypatch.setattr(solver, "solve_river", spy)
    go(facing_raise())
    spot = seen["spot"]
    tree = GameTree(spot)
    assert spot.pot == 200 and spot.effective_stack == 1000  # the pot before either river bet
    assert tree["b100 r300"].player == OOP and tree["b100 r300"].actions == ("f", "c", "r1000")


def test_the_ranges_come_from_the_betting_so_far(monkeypatch, switch_on):
    seen = {}
    real = bridge_mod.river_decision

    def spy(*args, **kw):
        seen.update(kw)
        seen["decision"] = real(*args, **kw)
        return seen["decision"]

    monkeypatch.setattr(bridge_mod, "river_decision", spy)
    monkeypatch.setattr(solver, "solve_river", picks("c"))
    st = facing_bet()
    st.betting = Line(StreetLine(2.5, VILLAIN), StreetLine(0.66, VILLAIN), StreetLine(0.0), ((VILLAIN, 100.0),))
    button = next(p for p in st.players if p.position.value == "BTN")
    button.style, button.played = "station", (0.5, 0.05)
    a = go(st)
    assert a.basis == "solver"
    assert seen["line"] is st.betting and seen["big_blind"] == 10
    assert (seen["hero_seat"], seen["villain_seat"], seen["villain_style"]) == ("BB", "BTN", "station")
    assert seen["villain_rates"] == (0.5, 0.05)
    d = seen["decision"]
    assert not d.guessed and d.line.flop == StreetLine(0.66, VILLAIN)
    # the small print says what the hands were judged from
    assert "Hands judged from: before the flop they raised to 2.5 big blinds; on the flop they bet 66%" in a.detail
    # no record (a single screenshot): the same spot is still solved, on a line guessed from the pot
    seen.clear()
    a = go(facing_bet())
    assert a.basis == "solver" and "Hands guessed from the size of the pot" in a.detail
    assert seen["line"] is None and seen["villain_rates"] is None and seen["decision"].guessed


def test_the_solver_sees_the_real_spot(monkeypatch, switch_on):
    seen = {}

    def spy(spot, time_budget_ms=None, **how):
        seen["spot"], seen["budget"], seen["how"] = spot, time_budget_ms, how
        return picks("c")(spot)

    monkeypatch.setattr(solver, "solve_river", spy)
    go(facing_bet())
    spot = seen["spot"]
    assert spot.board == tuple(BOARD) and spot.pot == 200 and spot.effective_stack == 1000
    assert "b100" in GameTree(spot)["x"].actions  # their real bet is in the tree
    assert seen["budget"] == solver.DECISION_BUDGET_MS
    # by the clock, and stopping early at a hundredth of a big blind: the pot is 20 of them
    assert seen["how"] == {"max_iterations": None, "target_exploitability": pytest.approx(0.01 / 20)}
    assert spot.index(OOP, ("Ah", "Kd")) >= 0  # the hero's hand is in the hero's range


def test_fixed_work_takes_the_clock_away(monkeypatch, switch_on):
    # TUNING["river_solver_fixed_work"], which the simulator turns on: no time budget, and
    # the iterations the budget buys on the reference machine
    seen = {}

    def spy(spot, time_budget_ms=None, **how):
        seen["spot"], seen["budget"], seen["how"] = spot, time_budget_ms, how
        time.sleep(0.03)
        return picks("c")(spot)

    monkeypatch.setitem(advice.TUNING, "river_solver_fixed_work", True)
    monkeypatch.setattr(solver, "DECISION_BUDGET_MS", 20)  # the solve above takes longer than this
    monkeypatch.setattr(solver, "solve_river", spy)
    a = go(facing_bet())
    assert a.basis == "solver" and a.action == "call"  # a slow run still gives the solver's answer
    assert seen["budget"] is None
    assert seen["how"] == {"max_iterations": solver.reference_iterations(seen["spot"]),
                           "target_exploitability": pytest.approx(0.01 / 20)}
    # by the clock the same slow solve is too late, and the rules decide
    monkeypatch.setitem(advice.TUNING, "river_solver_fixed_work", False)
    assert go(facing_bet()).basis != "solver"


def test_fixed_work_gives_the_same_instruction_every_run(monkeypatch, switch_on):
    monkeypatch.setitem(advice.TUNING, "river_solver_fixed_work", True)
    for make in (checked_to, facing_bet):
        first, again = go(make()).to_dict(), go(make()).to_dict()
        assert first["basis"] == "solver" and "%" in first["detail"]
        assert first == again  # the mix in the small print too, to the last percent


def test_the_simulator_turns_fixed_work_on(monkeypatch):
    from tools import simulate as sim

    assert advice.TUNING["river_solver_fixed_work"] is False  # the app itself goes by the clock
    with sim.variant({"river_solver": True}):
        assert advice.TUNING["river_solver_fixed_work"] is True and advice.TUNING["river_solver"] is True
    assert advice.TUNING["river_solver_fixed_work"] is False and advice.TUNING["river_solver"] is False
    with sim.variant(None):  # the baseline: the switch stays off, so the solver isn't reached
        assert advice.TUNING["river_solver"] is False
        monkeypatch.setattr(solver, "solve_river", _never_called)
        go(facing_bet())


# ------------------------------------------------- the real solver, end to end
def test_real_solver_through_the_advice(monkeypatch, switch_on):
    # The real solver with a fixed amount of work in place of the clock, as the simulator
    # runs it, so a busy machine can't make it late or rough (either would be a correct
    # fall back to the rules, but not what this test is about).
    monkeypatch.setitem(advice.TUNING, "river_solver_fixed_work", True)
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
    # A set of eights, bet and raised: the solver's answer, never a fold.
    a = go(facing_raise(hero=("8h", "8s")))
    assert a.basis == "solver" and a.action in ("call", "all-in")


def test_the_switch_is_still_off_with_the_real_solver(monkeypatch):
    def never(spot, time_budget_ms=None, **how):
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


def test_bridge_offers_only_the_bet_that_was_made():
    # facing 70 into 200: the button's bet after the check is 70 and nothing else,
    # while the hero's own first bet (not taken) keeps the usual sizes and all in
    d = _decision(pot_now=270, villain_bet=70)
    tree = GameTree(d.spot)
    assert tree["x"].actions == ("x", "b70")
    assert tree[""].actions == ("x", "b100", "b200", "b1000")
    assert tree["x b70"].actions == ("f", "c", "r410", "r1000")  # fold, call, a pot-sized raise, all in
    # facing a raise: the hero's bet and their raise are the only ones on the way here
    d = _decision(hero_bet=100, villain_bet=300, pot_now=600)
    tree = GameTree(d.spot)
    assert tree[""].actions == ("x", "b100") and tree["b100"].actions == ("f", "c", "r300")


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


def test_bridge_facing_a_raise():
    # the hero bet 100 into 200 and was raised to 300: the spot starts at 200, both real sizes are in the tree
    d = _decision(hero_bet=100, villain_bet=300, pot_now=600)
    assert (d.node, d.hero, d.spot.pot) == ("b100 r300", OOP, 200)
    # stacks behind are 1000 each now, so 1100 and 1300 at the start of the river: 1100 is the most at stake
    assert d.spot.effective_stack == 1100
    tree = GameTree(d.spot)
    assert tree[d.node].actions == ("f", "c", "r1100")  # fold, call, or all in
    # in position: they checked, the hero bet, they check-raised
    d = _decision(hero_bet=100, villain_bet=300, pot_now=600, hero_in_position=True)
    assert (d.node, d.hero) == ("x b100 r300", IP)
    # a raise that is all in leaves only fold or call
    d = _decision(hero_bet=100, villain_bet=700, pot_now=1000, hero_stack=600, villain_stack=0)
    assert GameTree(d.spot)[d.node].actions == ("f", "c") and d.node == "b100 r700"


def test_bridge_leaves_out_an_all_in_of_many_pots():
    # a limped pot of 5 with 198 behind: all in would be a bet of 40 pots
    d = _decision(pot_now=5, hero_stack=198, villain_stack=198)
    tree = GameTree(d.spot)
    assert tree[""].actions == ("x", "b2.5", "b5") and tree["x"].actions == ("x", "b2.5", "b5")
    # raising a pot-sized bet all in is (198 - 5) / (5 + 2 x 5) = 12.9 pots: left out too
    assert tree["b5"].actions == ("f", "c", "r20")
    # the usual 200 pot with 1000 behind is 5 pots deep: all in stays a choice
    assert GameTree(_decision().spot)[""].actions == ("x", "b100", "b200", "b1000")
    # a bet they did make is in the tree however big it is
    d = _decision(pot_now=203, villain_bet=198, hero_stack=198, villain_stack=0)
    assert d.node == "x b198" and GameTree(d.spot)[d.node].actions == ("f", "c")
    # the hero bet 5 and was raised to 20: all in is (198 - 20) / (5 + 2 x 20) = 3.96 pots, a choice
    d = _decision(pot_now=30, hero_bet=5, villain_bet=20, hero_stack=193, villain_stack=178)
    assert d.node == "b5 r20" and GameTree(d.spot)[d.node].actions == ("f", "c", "r198")
    # five times deeper it is 21.8 pots: fold or call
    d = _decision(pot_now=30, hero_bet=5, villain_bet=20, hero_stack=995, villain_stack=980)
    assert GameTree(d.spot)[d.node].actions == ("f", "c")


def test_bridge_follows_the_recorded_river_bets():
    # the hero checked, they bet 50, the hero raised to 150, they raised again to 400
    path = ((VILLAIN, 50.0), (HERO, 150.0), (VILLAIN, 400.0))
    d = _decision(hero_bet=150, villain_bet=400, pot_now=750, line=Line(river=path))
    assert d.node == "x b50 r150 r400" and d.spot.pot == 200
    assert GameTree(d.spot)[d.node].actions == ("f", "c", "r1150")
    # without the record the same chips read as: the hero bet 150, they raised to 400
    assert _decision(hero_bet=150, villain_bet=400, pot_now=750).node == "b150 r400"
    # a record that doesn't fit the chips in front now is ignored
    stale = Line(river=((VILLAIN, 50.0), (HERO, 120.0), (VILLAIN, 400.0)))
    assert _decision(hero_bet=150, villain_bet=400, pot_now=750, line=stale).node == "b150 r400"
    # facing a bet, the record changes nothing
    d = _decision(pot_now=270, villain_bet=70, line=Line(river=((VILLAIN, 70.0),)))
    assert d.node == "x b70"


def test_bridge_ranges_from_the_line():
    line = Line(StreetLine(2.5, VILLAIN), StreetLine(0.75, VILLAIN), StreetLine(0.75, VILLAIN))
    told = _decision(line=line, big_blind=10, hero_seat="BB", villain_seat="BTN")
    blind = _decision()
    assert told.line.turn == StreetLine(0.75, VILLAIN) and not told.guessed
    assert blind.guessed and blind.line.preflop.known
    assert told.spot.combos(IP) != blind.spot.combos(IP)
    # ranges given by the caller are used as they are
    given = _decision(hero_range="AKo, QQ", villain_range="JJ+, AK")
    # JJ and AA have three combos each (a jack and an ace are on the board), QQ and KK six, AK twelve
    assert given.line is None and len(given.spot.combos(IP)) == 3 + 6 + 6 + 3 + 12
    assert given.spot.index(OOP, ("Ah", "Kd")) >= 0


def test_bridge_leaves_odd_spots_to_the_rules():
    assert _decision(hero_bet=300, villain_bet=300, pot_now=800) is None  # nothing to answer
    assert _decision(hero_bet=300, villain_bet=100, pot_now=600) is None
    assert _decision(pot_now=0) is None
    assert _decision(board=BOARD[:4]) is None
    assert _decision(hero_cards=("Ac", "Kd")) is None  # Ac is on the board


def test_no_answer_when_the_solution_never_gets_there(monkeypatch):
    # a "solution" in which the button never bets: its strategy against a bet means nothing
    def never_bets(spot, time_budget_ms=None, **how):
        return RiverStrategy.from_rule(spot, lambda node, combo: {node.actions[0]: 1.0})

    d = _decision(pot_now=300, villain_bet=100)
    assert recommend(never_bets(d.spot, 0), d) is None
    before = go(facing_bet())
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    monkeypatch.setattr(solver, "solve_river", never_bets)
    after = go(facing_bet())
    assert after.basis != "solver" and after.to_dict() == before.to_dict()  # the rules decide


def test_a_hand_the_solution_never_brings_here_gets_its_best_action():
    # The "solution": the hero always bets first (so never checks), the button bets 100 when
    # checked to and calls any raise, and the hero's row against that bet is "fold".
    def rule(node, combo):
        if node.key == "":
            return {node.actions[1]: 1.0}
        if node.key == "x":
            return {"b100": 1.0}
        return {"f": 1.0} if node.key == "x b100" else {"c": 1.0}

    # Top pair, top kicker against JJ+ and AK: it beats QQ and KK (9 combos without the hero's
    # king), loses to JJ and AA (4), and splits with AK (6). Calling 100 to win 300 is clearly right.
    d = _decision(pot_now=300, villain_bet=100, hero_range="AKo, QQ", villain_range="JJ+, AK")
    best, probs = recommend(RiverStrategy.from_rule(d.spot, rule), d)
    assert best != "f" and probs[best] == 1.0 and probs["f"] == 0.0
    # a pair of twos beats nothing they hold: folding is its best action
    d = _decision(hero_cards=("7c", "2d"), pot_now=300, villain_bet=100, hero_range="AKo, QQ",
                  villain_range="JJ+, AK")
    assert recommend(RiverStrategy.from_rule(d.spot, rule), d)[0] == "f"


def test_recommend_takes_the_most_likely_action():
    d = _decision()
    st = RiverStrategy.from_rule(d.spot, lambda node, combo: [1 / len(node.actions)] * len(node.actions))
    best, probs = recommend(st, d)
    assert best == "x" and sum(probs.values()) == pytest.approx(1)  # a tie: the first action
    st = RiverStrategy.from_rule(d.spot, lambda node, combo: {node.actions[-1]: 0.6, node.actions[0]: 0.4})
    assert recommend(st, d)[0] == "b1000"
