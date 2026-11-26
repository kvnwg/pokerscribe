"""RiverSpot, the betting tree and RiverStrategy (app/solver)."""
import numpy as np
import pytest

from app.solver import IP, OOP, BetSizes, GameTree, RiverSpot, RiverStrategy
from app.solver.tree import FOLD, SHOWDOWN, action_amount, describe_action

BOARD = ("Kh", "8d", "5c", "3s", "2h")


def spot(**kw):
    args = dict(board=BOARD, pot=100, stacks=(1000, 1000), oop_range="QQ", ip_range="KK, JT")
    args.update(kw)
    return RiverSpot(**args)


# ----------------------------------------------------------------- the spot
def test_board_clashes_are_removed():
    s = spot(ip_range="KK")  # Kh is on the board: 3 of the 6 KK combos are left
    assert len(s.ip_range) == 3
    assert all("Kh" not in c for c, _ in s.ip_range)


def test_same_card_twice_duplicates_and_zero_weights_are_removed():
    s = spot(oop_range=[("Qs", "Qd"), ("Qd", "Qs"), "QsQd", ("Ac", "Ac"), "AcAc", ("Ah", "Ad"), (("Jc", "Tc"), 0.0)])
    assert [c for c, _ in s.oop_range] == [("Qs", "Qd"), ("Ah", "Ad")]
    s = spot(oop_range=[(("Qs", "Qd"), 0.25), (("Qd", "Qs"), 1.0)])
    assert s.oop_range == ((("Qs", "Qd"), 0.25),)  # a combo listed twice keeps its first weight


def test_ranges_from_text_mappings_and_weighted_lists():
    assert len(spot(oop_range="QQ").oop_range) == 6
    s = spot(oop_range={"QsQd": 0.5, ("Ad", "Ac"): 1})
    assert s.oop_range == ((("Qs", "Qd"), 0.5), (("Ad", "Ac"), 1.0))
    s = spot(oop_range=[("QsQd", 0.5), (("As", "Ad"), 2.0)])
    assert s.weights(OOP).tolist() == [0.5, 2.0]
    assert s.combos(OOP) == [("Qs", "Qd"), ("As", "Ad")]


def test_combos_are_kept_in_one_order():
    s = spot(oop_range=["KdAh", "2c3c", "ThTs"])
    assert s.combos(OOP) == [("Ah", "Kd"), ("3c", "2c"), ("Ts", "Th")]
    assert s.index(OOP, "AhKd") == s.index(OOP, ("Kd", "Ah")) == 0
    with pytest.raises(ValueError):
        s.index(OOP, "AsKs")


def test_bad_input_is_an_error():
    with pytest.raises(ValueError):
        spot(board=BOARD[:4])
    with pytest.raises(ValueError):
        spot(board=BOARD[:4] + ("Kh",))
    with pytest.raises(ValueError):
        spot(pot=0)
    with pytest.raises(ValueError):
        spot(stacks=(100, -1))
    with pytest.raises(ValueError):
        spot(oop_range="KhKs")  # nothing left once the board's Kh is removed
    with pytest.raises(ValueError):
        spot(oop_range={"QsQd": -1})
    with pytest.raises(ValueError):
        spot(oop_range=["Qx Qd"])
    with pytest.raises(ValueError):
        BetSizes(bets=(0.5, -1))


def test_effective_stack_and_round_trip():
    s = spot(stacks=(300, 700), oop_range={"QsQd": 0.5, "QhQc": 1}, ip_sizes=BetSizes((0.33,), (), False))
    assert s.effective_stack == 300
    assert RiverSpot.from_dict(s.to_dict()) == s


# ------------------------------------------------------------------ the tree
def test_default_tree():
    t = GameTree(spot())
    assert t.root.player == OOP
    assert t.root.actions == ("x", "b50", "b100", "b1000")  # half pot, pot, all in
    assert t["x"].player == IP and t["x"].actions == ("x", "b50", "b100", "b1000")
    # facing a bet of 50: raise the pot after calling (50 + 1.0 x 200 = 250) or all in
    assert t["b50"].actions == ("f", "c", "r250", "r1000")
    assert t["b50 r250"].actions == ("f", "c")  # one raise allowed by default
    assert t["x x"].terminal == SHOWDOWN and t["x x"].put_in == (0, 0)
    assert t["b50 f"].terminal == FOLD and t["b50 f"].folder == IP and t["b50 f"].put_in == (50, 0)
    assert t["b50 c"].terminal == SHOWDOWN and t["b50 c"].put_in == (50, 50)
    assert t["x b100 r1000 c"].put_in == (1000, 1000)
    for node in t.nodes.values():
        assert all(child in t for child in node.children)
    assert t["x b100"].actions == ("f", "c", "r400", "r1000")  # 100 + 1.0 x (100 + 2 x 100) = 400
    assert [n.key for n, _ in t.path("x b100 r400")] == ["", "x", "x b100"]


def test_short_stacks_turn_bets_into_all_in():
    t = GameTree(spot(stacks=(60, 500)))
    assert t.root.actions == ("x", "b50", "b60")  # the pot bet is capped at 60, the all in
    assert t["b50"].actions == ("f", "c", "r60")
    assert t["b60"].actions == ("f", "c")  # nothing left to raise


def test_raises_are_at_least_the_bet_they_answer():
    t = GameTree(spot(ip_sizes=BetSizes((0.5,), (0.1,), False), oop_sizes=BetSizes((0.5,), (0.1,), False)))
    assert t["b50"].actions == ("f", "c", "r100")  # 50 + 0.1 x 200 = 70 is under a min raise to 100


def test_a_raise_of_a_raise_can_have_its_own_sizes():
    # two raises allowed; after the first one the only raise is all in
    only_allin = BetSizes((0.5,), (1.0,), True, reraises=())
    t = GameTree(spot(oop_sizes=only_allin, ip_sizes=only_allin, max_raises=2))
    assert t["b50"].actions == ("f", "c", "r250", "r1000")
    assert t["b50 r250"].actions == ("f", "c", "r1000")
    assert t["b50 r250 r1000"].actions == ("f", "c")
    # the same sizes again when none are given
    same = GameTree(spot(max_raises=2))
    assert same["b50 r250"].actions == ("f", "c", "r850", "r1000")  # 250 + 1.0 x (100 + 2 x 250) = 850
    # saved and read back, with or without them
    for sizes in (only_allin, BetSizes((0.5,), (1.0,), False, reraises=(0.5, 2.0)), BetSizes()):
        assert BetSizes.from_dict(sizes.to_dict()) == sizes
    assert "reraises" not in BetSizes().to_dict()
    with pytest.raises(ValueError):
        BetSizes(reraises=(0.5, -1))


def test_no_stacks_means_check_down():
    t = GameTree(spot(stacks=(0, 500)))
    assert t.root.actions == ("x",) and t["x"].actions == ("x",)


def test_half_street_tree():
    t = GameTree(spot(oop_sizes=BetSizes((), (), False), ip_sizes=BetSizes((1.0,), (), False), max_raises=0))
    assert sorted(t.nodes) == ["", "x", "x b100", "x b100 c", "x b100 f", "x x"]
    assert t["x b100"].actions == ("f", "c")


def test_action_words():
    assert action_amount("r250") == 250 and action_amount("x") is None
    assert [describe_action(a) for a in ("x", "c", "f", "b33.5", "r250")] == [
        "check", "call", "fold", "bet 33.5", "raise to 250"]


# -------------------------------------------------------------- the strategy
def test_uniform_and_rule_strategies():
    s = spot()
    u = RiverStrategy.uniform(s)
    assert u.action_probs("", "QsQd") == {"x": 0.25, "b50": 0.25, "b100": 0.25, "b1000": 0.25}
    r = RiverStrategy.from_rule(s, lambda node, combo: {node.actions[0]: 1.0})
    assert r.action_probs("x b50", "QsQd") == {"f": 1.0, "c": 0.0, "r250": 0.0, "r1000": 0.0}
    assert "fold 100%" == r.describe("x b50", "QsQd")


def test_strategies_must_be_complete_probabilities():
    s = spot()
    good = RiverStrategy.uniform(s).probs
    missing = {k: v for k, v in good.items() if k != "x"}
    with pytest.raises(ValueError, match="No strategy"):
        RiverStrategy(s, missing)
    bad = dict(good, x=good["x"] * 2)
    with pytest.raises(ValueError, match="add up to 1"):
        RiverStrategy(s, bad)
    with pytest.raises(ValueError, match="shape"):
        RiverStrategy(s, dict(good, x=good["x"][:, :2]))
    with pytest.raises(ValueError, match="not negative"):
        neg = good["x"].copy()
        neg[0] = [1.5, -0.5, 0, 0]
        RiverStrategy(s, dict(good, x=neg))
    with pytest.raises(ValueError, match="aren't in the tree"):
        RiverStrategy(s, dict(good, nowhere=good["x"]))
    with pytest.raises(ValueError, match="no action"):
        RiverStrategy.from_rule(s, lambda node, combo: {"jump": 1.0})


def test_reach_and_frequencies_count_only_own_choices():
    s = spot()
    # OOP checks QsQd always and the other QQ half the time; IP always bets 50 after a check
    def rule(node, combo):
        if node.key == "":
            return {"x": 1.0} if combo == ("Qs", "Qd") else {"x": 0.5, "b50": 0.5}
        if node.key == "x":
            return {"b50": 1.0}
        return {node.actions[0]: 1.0}

    st = RiverStrategy.from_rule(s, rule)
    reach = st.reach(OOP)
    i = s.index(OOP, "QsQd")
    assert reach["x"][i] == 1.0 and np.allclose(np.delete(reach["x"], i), 0.5)
    assert np.allclose(reach["x b50"], reach["x"])  # IP's bet doesn't count in OOP's reach
    assert st.frequencies("")["x"] == pytest.approx((1 + 5 * 0.5) / 6)
    assert st.frequencies("x") == {"x": 0.0, "b50": 1.0, "b100": 0.0, "b1000": 0.0}
