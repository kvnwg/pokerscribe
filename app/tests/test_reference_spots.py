"""The reference river spots (data/reference_spots/python_solver): 20 spots and the Python
river solver's answer to each, which the Rust solver is checked against.

Three kinds of test:

1. The files: every spot is a valid SPOT, every answer a valid RESULT for it
   (data/SPOT_FORMAT.md), and the numbers stored with an answer are what the answer gives.
2. Known answers. The closed forms are worked out here from the formulas, not read from
   the tool that made the files, and are asked both of the saved answers and of fresh
   solves. app/tests/test_solver_answer_keys.py already has the half-street game at bet
   sizes 0.5, 0.75, 1 and 2; here are sizes it doesn't have (0.25, 0.6 as an all in, 1.5),
   the bettor out of position, and a range with too few bluffs.
3. A solver is checked against a reference answer by value, not hand by hand
   (tools/reference_spots/compare.py): a fresh solve passes, wrong answers don't.

Tolerances, stated up front:
- a saved answer is within 0.005% of the pot of an equilibrium (solve.ACCEPT);
- saved answers: known shares within 0.002, known values within 0.01 chips of a pot of 100;
- fresh solves stop at 0.02% of the pot: shares within 0.01, values within 0.05 chips.
"""
import os
from fractions import Fraction

import pytest

from app.solver import solve_river
from tools.answer_keys import result as result_mod
from tools.answer_keys.checks import check_expected, nodes_from_river_strategy, river_checks
from tools.answer_keys.spots import SpotError, decision_nodes, load_spots, river_spot, spot_hash, validate_spot
from tools.reference_spots import build, compare, defs, known, solve
from tools.reference_spots.__main__ import check_folder, load_index, saved, validate_all

SPOTS = {s["id"]: s for s in load_spots(build.SPOTS_DIR)}
IDS = sorted(SPOTS)
POLAR = sorted(i for i, k in defs.KNOWN.items() if "bettor" in k)
REALISTIC = sorted(i for i in IDS if i not in defs.KNOWN)

SAVED_SHARE_TOL, SAVED_VALUE_TOL = 0.002, 0.01
FRESH_TARGET, FRESH_SHARE_TOL, FRESH_VALUE_TOL = 0.0002, 0.01, 0.05


def answer(spot_id):
    got = saved(spot_id)
    assert got is not None, f"{spot_id} has no saved answer"
    return got


def fresh_nodes(spot_id, target=FRESH_TARGET, max_iterations=20000):
    """A new solve of a spot, with no clock so that it repeats, as RESULT node records."""
    strategy = solve_river(river_spot(SPOTS[spot_id]), None, max_iterations=max_iterations, target_exploitability=target)
    assert strategy.exploitability <= target
    return nodes_from_river_strategy(strategy)


# ---------------------------------------------------------------- the files
def test_there_are_enough_spots_simple_and_realistic():
    assert len(IDS) >= 15
    assert IDS == sorted(d["id"] for d in defs.SPOTS + defs.LINES)
    assert len(defs.KNOWN) >= 8 and set(defs.KNOWN) <= set(IDS)
    assert len(REALISTIC) >= 4
    assert sorted(os.listdir(build.SPOTS_DIR)) == [f"{i}.json" for i in IDS]
    assert sorted(os.listdir(build.RESULTS_DIR)) == [f"{i}.jsonl" for i in IDS]


@pytest.mark.parametrize("spot_id", IDS)
def test_every_spot_is_a_valid_river_spot(spot_id):
    spot = SPOTS[spot_id]
    validate_spot(spot)  # raises SpotError
    assert spot["street"] == "river" and len(spot["board"]) == 5 and spot["pot"] == 100
    # only the size fields the format's tree knows (not app/solver's reraises, allin_within, exact)
    assert all(set(spot["sizes"][p]) == {"bets", "raises", "allin"} for p in ("oop", "ip"))
    rs = river_spot(spot)  # app/solver reads it
    assert [len(rs.combos(0)), len(rs.combos(1))] == [len(spot["ranges"][p]) for p in ("oop", "ip")]  # nothing was dropped


def test_hand_written_spot_files_are_what_defs_gives():
    for defn in defs.SPOTS:
        assert SPOTS[defn["id"]] == build.build_spot(defn), defn["id"]


def test_a_bad_spot_is_refused():
    bad = dict(SPOTS["py13"], pot=0)
    with pytest.raises(SpotError):
        validate_spot(bad)
    with pytest.raises(ValueError):  # a size field the format's tree doesn't know
        build._finish({**build.build_spot(defs.SPOTS[0]), "sizes": {"oop": {**defs.NOBODY, "allin_within": 6}, "ip": defs.NOBODY}})


def test_the_spots_with_the_apps_ranges_are_frozen_files():
    """py17 to py20 came from app/solver/ranges.py once. They are not built again here:
    the range model may change, a reference spot must not."""
    for defn in defs.LINES:
        spot = SPOTS[defn["id"]]
        assert "app-ranges" in spot["tags"] and "range_text" not in spot
        assert spot["board"] == defn["board"].split()
        for player in ("oop", "ip"):
            weights = spot["ranges"][player].values()
            assert len(weights) > 150 and all(0 < w <= 1 for w in weights)
            assert len(set(weights)) > 10  # real weights, not a list of classes


@pytest.mark.parametrize("spot_id", IDS)
def test_every_saved_answer_is_a_valid_result_and_near_an_equilibrium(spot_id):
    spot = SPOTS[spot_id]
    header, nodes = answer(spot_id)
    result_mod.validate_result(header, nodes, spot, spot_hash(spot), decision_nodes(spot))
    assert header["solver"]["name"] == "pokerscribe-river" and header["solver"]["module"] == "app.solver"
    assert header["solver"]["converged"] and header["solver"]["settings"]["time_budget_ms"] is None
    # the stored numbers are what the stored strategy gives, by an exact best response
    checks = river_checks(spot, nodes)
    assert checks == {k: header["checks"][k] for k in checks}
    assert checks["filled_rows"] == 0 and header["checks"]["expected_failures"] == [] == check_expected(spot, nodes)
    assert 0 <= checks["exploitability_pot"] <= solve.ACCEPT
    # the two values share the pot, and the true value is pinned down to twice the exploitability
    assert checks["values"]["oop"] + checks["values"]["ip"] == pytest.approx(spot["pot"], abs=1e-5)
    low, high = checks["oop_value_bounds"]
    assert low - 1e-6 <= checks["values"]["oop"] <= high + 1e-6
    assert high - low == pytest.approx(2 * checks["exploitability_pot"] * spot["pot"], abs=1e-5)


def test_the_index_and_the_readme_list_every_answer():
    index = load_index()
    readme = open(os.path.join(build.HOME, "README.md")).read()
    assert sorted(index["spots"]) == IDS
    for spot_id in IDS:
        header, _ = answer(spot_id)
        entry = index["spots"][spot_id]
        assert entry["spot_sha256"] == header["spot_sha256"] == spot_hash(SPOTS[spot_id])
        assert entry["exploitability_pot"] == header["checks"]["exploitability_pot"]
        assert entry["oop_value"] == header["checks"]["values"]["oop"]
        assert f"| {spot_id} | {SPOTS[spot_id]['title']} |" in readme


def test_validate_finds_no_problems():
    assert validate_all() == []


# ------------------------------------------------------------ known answers
def closed_form(s, nuts=3, air=16, pot=100):
    """The half-street game (The Mathematics of Poker): a player with `nuts` combos of the
    nuts and `air` combos of air bets s pots or checks, into one hand that beats only the air.

    - The caller must be indifferent: calling s wins pot + s against a bluff and loses s
      to the nuts, so bluffs / bets = s / (1 + 2s).
    - Air must be indifferent to bluffing: it wins the pot when the caller folds and loses
      s when called, so pot x (1 - call) = s x pot x call, call = 1 / (1 + s).
    - Air then wins nothing either way. The nuts win pot + s x pot when called and the pot
      when not: pot x (1 + s x call). So the bettor wins nuts / (nuts + air) of that.
    """
    s = Fraction(s).limit_denominator(1000)
    call = 1 / (1 + s)
    return {"bluffs": s / (1 + 2 * s), "calls": call,
            "bettor_value": Fraction(nuts, nuts + air) * pot * (1 + s * call),
            "air_that_bets": nuts * s / (1 + s)}  # combos: bluffs / (bluffs + nuts) = s / (1 + 2s)


def test_the_closed_form_by_hand():
    # a pot-sized bet: one bluff for every two value bets, called half the time; the nuts
    # win 100 + 100/2 = 150 on 3 of 19 hands
    assert closed_form(1) == {"bluffs": Fraction(1, 3), "calls": Fraction(1, 2), "bettor_value": Fraction(450, 19),
                              "air_that_bets": Fraction(3, 2)}
    # a quarter of the pot: 100 + 0.8 x 25 = 120 on 3 of 19 hands
    assert closed_form(0.25)["bettor_value"] == Fraction(360, 19)
    assert closed_form(0.25)["bluffs"] == Fraction(1, 6) and closed_form(0.25)["calls"] == Fraction(4, 5)


@pytest.mark.parametrize("spot_id", POLAR)
def test_the_table_of_known_answers_is_the_closed_form(spot_id):
    want, exact = defs.KNOWN[spot_id], closed_form(defs.KNOWN[spot_id]["s"])
    assert want["bluffs"] == exact["bluffs"] and want["calls"] == exact["calls"]
    bettor_value = exact["bettor_value"]
    assert want["oop_value"] == (bettor_value if want["bettor"] == "oop" else 100 - bettor_value)
    # and the spot really is that game: one bet of s pots for one player, nothing else
    spot = SPOTS[spot_id]
    actions = {key: node.actions for key, node in decision_nodes(spot).items()}
    bet = f"b{round(100 * want['s'])}"
    first = "" if want["bettor"] == "oop" else "x"
    assert actions[first] == ("x", bet) and actions[(first + " " + bet).strip()] == ("f", "c")
    assert len(actions) == 3  # the third node is the caller's forced check (py07: the check behind)
    counts = sorted(len(spot["ranges"][p]) for p in ("oop", "ip"))
    assert counts == [6, 19]  # QQ against KK (3 combos, Kh is on the board) and JT (16)


def polar_problems(spot_id, nodes, share_tol, value_tol):
    spot = SPOTS[spot_id]
    return known.known_failures(spot, nodes, river_checks(spot, nodes), tol_value=value_tol, tol_share=share_tol)


@pytest.mark.parametrize("spot_id", POLAR)
def test_saved_answers_match_the_closed_form(spot_id):
    spot, (_, nodes) = SPOTS[spot_id], answer(spot_id)
    want = defs.KNOWN[spot_id]
    got = known.polar_shares(spot, nodes)
    assert got["bluffs"] == pytest.approx(float(want["bluffs"]), abs=SAVED_SHARE_TOL)
    assert got["calls"] == pytest.approx(float(want["calls"]), abs=SAVED_SHARE_TOL)
    assert got["nuts_bet"] >= 1 - SAVED_SHARE_TOL
    assert river_checks(spot, nodes)["values"]["oop"] == pytest.approx(float(want["oop_value"]), abs=SAVED_VALUE_TOL)
    assert polar_problems(spot_id, nodes, SAVED_SHARE_TOL, SAVED_VALUE_TOL) == []


@pytest.mark.parametrize("spot_id", ["py05", "py06", "py07", "py08"])
def test_a_fresh_solve_finds_the_closed_form(spot_id):
    """Bet sizes 0.25 and 1.5, the bettor out of position, and the bet as an all in of 0.6
    pots: none of them in test_solver_answer_keys.py."""
    spot, nodes = SPOTS[spot_id], fresh_nodes(spot_id)
    want = defs.KNOWN[spot_id]
    got = known.polar_shares(spot, nodes)
    assert got["bluffs"] == pytest.approx(float(want["bluffs"]), abs=FRESH_SHARE_TOL)
    assert got["calls"] == pytest.approx(float(want["calls"]), abs=FRESH_SHARE_TOL)
    assert got["nuts_bet"] >= 1 - FRESH_SHARE_TOL
    assert river_checks(spot, nodes)["values"]["oop"] == pytest.approx(float(want["oop_value"]), abs=FRESH_VALUE_TOL)


def test_polar_shares_reads_a_strategy_written_by_hand():
    """The reader of the shares, on a strategy typed in: all three nut combos bet, 2 of the
    16 air combos bet, the caller calls 3 of its 6 combos. Bluffs are 2 of 5 bets."""
    spot = SPOTS["py03"]
    air = [c for c in spot["ranges"]["ip"] if c[0] != c[2]]
    bettor = {c: {"x": 0.0, "b100": 1.0} for c in spot["ranges"]["ip"] if c[0] == c[2]}
    bettor.update({c: ({"x": 0.0, "b100": 1.0} if i < 2 else {"x": 1.0, "b100": 0.0}) for i, c in enumerate(air)})
    caller = {c: ({"f": 0.0, "c": 1.0} if i < 3 else {"f": 1.0, "c": 0.0}) for i, c in enumerate(spot["ranges"]["oop"])}
    nodes = {"x": {"actor": "ip", "actions": ["x", "b100"], "strategy": bettor},
             "x b100": {"actor": "oop", "actions": ["f", "c"], "strategy": caller}}
    assert known.polar_shares(spot, nodes) == pytest.approx({"bluffs": 0.4, "calls": 0.5, "nuts_bet": 1.0})


def test_with_too_few_bluffs_the_bluff_catcher_always_folds():
    """py09: 9 nut combos (KK, 88, 55) and 4 of air (JTs) bet the pot. Even if all the air
    bets, bluffs are 4 of 13 bets, under the third a call needs: calling wins 200 on 4/13
    and loses 100 on 9/13, -7.7 a hand. So the caller folds everything and the bettor takes
    the whole pot whatever it holds: value 0 for the caller."""
    assert Fraction(4, 13) < closed_form(1)["bluffs"]
    assert float(Fraction(4, 13) * 200 - Fraction(9, 13) * 100) == pytest.approx(-7.69, abs=0.01)
    spot = SPOTS["py09"]
    assert sorted(len(spot["ranges"][p]) for p in ("oop", "ip")) == [6, 13]
    for nodes in (answer("py09")[1], fresh_nodes("py09")):
        folds = [row["f"] for row in nodes["x b100"]["strategy"].values()]
        assert min(folds) >= 0.98
        assert river_checks(spot, nodes)["values"]["oop"] == pytest.approx(0, abs=FRESH_VALUE_TOL)
        assert check_expected(spot, nodes) == []


@pytest.mark.parametrize("spot_id, value", [("py10", 0), ("py11", 100), ("py12", 50)])
def test_trivial_spots_have_their_value(spot_id, value):
    """py10: OOP holds only air against only the nuts, and wins nothing. py11: the same
    the other way round, OOP takes the pot. py12: a royal flush on the board, every hand
    splits the pot."""
    spot = SPOTS[spot_id]
    assert float(defs.KNOWN[spot_id]["oop_value"]) == value
    assert river_checks(spot, answer(spot_id)[1])["values"]["oop"] == pytest.approx(value, abs=SAVED_VALUE_TOL)
    nodes = fresh_nodes(spot_id)
    assert river_checks(spot, nodes)["values"]["oop"] == pytest.approx(value, abs=FRESH_VALUE_TOL)
    assert check_expected(spot, nodes) == []


# ------------------------------------------- checking a solver against them
@pytest.mark.parametrize("spot_id", ["py03", "py13", "py15", "py16", "py19"])
def test_a_fresh_solve_passes_the_check_against_the_saved_answer(spot_id):
    """What the Rust solver is asked, asked of app/solver itself at the accuracy the app
    stops at (0.1% of the pot): near an equilibrium, the reference value within 0.2% of the
    pot, and bounds on the true value that meet the reference's."""
    spot = SPOTS[spot_id]
    nodes = fresh_nodes(spot_id, target=0.001)
    numbers, problems = compare.check_answer(spot, nodes, answer(spot_id)[0]["checks"], max_exploitability=0.001,
                                             value_tol=0.002)
    assert problems == [] and numbers["bounds_meet"]
    assert abs(numbers["difference"]) <= 0.2


def uniform(spot):
    return {key: {"actor": node.actor, "actions": list(node.actions),
                  "strategy": {c: {a: 1 / len(node.actions) for a in node.actions} for c in spot["ranges"][node.actor]}}
            for key, node in decision_nodes(spot).items()}


def test_the_check_catches_wrong_answers():
    spot, (header, nodes) = SPOTS["py13"], answer("py13")
    ref = header["checks"]
    assert compare.check_answer(spot, nodes, ref, share_tol=0.005) == (
        {"exploitability_pot": ref["exploitability_pot"], "oop_value": ref["values"]["oop"], "difference": 0.0,
         "bounds_meet": True, "filled_rows": 0}, [])
    # every action equally often: far from an equilibrium, and its value is off
    numbers, problems = compare.check_answer(spot, uniform(spot), ref)
    assert numbers["exploitability_pot"] > 0.05 and any("from an equilibrium" in p for p in problems)
    # a right answer to another game (here: the reference moved by 2 chips): the value is
    # off and the bounds no longer meet
    moved = {"values": {"oop": ref["values"]["oop"] + 2}, "oop_value_bounds": [b + 2 for b in ref["oop_value_bounds"]]}
    numbers, problems = compare.check_answer(spot, nodes, moved)
    assert not numbers["bounds_meet"] and len(problems) == 2
    # a loose answer may miss the known shares and still pass on value: shares are only
    # checked when asked for
    polar = SPOTS["py05"]
    loose = fresh_nodes("py05", target=0.004)
    assert compare.check_answer(polar, loose, answer("py05")[0]["checks"])[1] == []
    lopsided = uniform(polar)
    assert any("known" in p for p in compare.check_answer(polar, lopsided, answer("py05")[0]["checks"], share_tol=0.02)[1])
    # the known value is asked even without the shares
    assert any("known" in p for p in compare.check_answer(polar, lopsided, answer("py05")[0]["checks"])[1])


def test_check_folder_reads_another_solvers_results(tmp_path):
    """The saved answers checked against themselves pass, a missing file and an answer to
    a changed spot are reported."""
    for spot_id in IDS:
        header, nodes = answer(spot_id)
        if spot_id == "py20":
            continue  # missing
        if spot_id == "py02":
            header = dict(header, spot_sha256="0" * 64)  # solved from another version of the spot
        ordered = [dict(nodes[key], node=key, kind="node") for key in decision_nodes(SPOTS[spot_id])]
        result_mod.write_result(str(tmp_path), header, ordered)
    rows = {r["id"]: r for r in check_folder(str(tmp_path), share_tol=0.005)}
    assert sorted(rows) == IDS
    assert rows["py20"]["problems"] == ["no answer"]
    assert len(rows["py02"]["problems"]) == 1 and "py02" in rows["py02"]["problems"][0]
    good = [r for i, r in rows.items() if i not in ("py02", "py20")]
    assert all(r["problems"] == [] and r["difference"] == 0 and r["bounds_meet"] for r in good)
