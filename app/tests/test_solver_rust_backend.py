"""app/solver/rust_backend.py: a RiverSpot goes out as a SPOT file, the program
`subgame-solve` is run on it, its RESULT comes back as a RiverStrategy, and the Python
solver answers whenever the program is missing or fails.

The program here is fake_subgame_solve.py, a stand-in written in Python that follows the
program's command line and file formats (data/SPOT_FORMAT.md) and can be told to
misbehave. The last test runs the real program when it is built, and is skipped otherwise.

Plus TUNING["rust_solver"]: off by default, and with it off nothing changes.
"""
import json
import logging
import os
import sys

import numpy as np
import pytest

import app.solver as solver
from app.poker import advice
from app.solver import BetSizes, GameTree, RiverSpot, RiverStrategy, bridge, rust_backend, solve_river
from app.solver.exploitability import exploitability
from app.solver.rust_backend import RustSolverError, UnsupportedSpot
from app.state.model import Action

from .test_advice import go, table

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the stand-in program is started through a shell script")

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_subgame_solve.py")
BOARD = ("Kh", "8d", "5c", "3s", "2h")


def spot(pot=100.0, stack=300.0, **kw):
    """Two overlapping ranges, the default sizes (half pot, pot, all in, one raise)."""
    return RiverSpot(BOARD, pot, (stack, stack), "TT+, AK, AQ, KQ, KJs, A5s, 76s, 65s, 44",
                     "88+, AK, AQs, KQ, KTs, QJs, JTs, A4s, 64s, 33", **kw)


class Fake:
    """The stand-in, installed as the program the backend finds."""

    def __init__(self, tmp_path, monkeypatch):
        self.monkeypatch = monkeypatch
        self.path = tmp_path / "subgame-solve"
        self.path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        self.path.chmod(0o755)
        self.log = tmp_path / "calls.jsonl"
        monkeypatch.setenv(rust_backend.ENV_BINARY, str(self.path))
        monkeypatch.setenv("FAKE_SUBGAME_LOG", str(self.log))
        for name in ("FAKE_SUBGAME_MODE", "FAKE_SUBGAME_SLEEP_S", "FAKE_SUBGAME_MAX_ITERATIONS"):
            monkeypatch.delenv(name, raising=False)

    def mode(self, name):
        self.monkeypatch.setenv("FAKE_SUBGAME_MODE", name)

    def calls(self):
        """The arguments of every call so far, each as {flag or "spot": value}."""
        if not self.log.exists():
            return []
        out = []
        for line in self.log.read_text().splitlines():
            argv = json.loads(line)["argv"]
            flags = {"spot": argv[0]}
            flags.update(zip(argv[1::2], argv[2::2]))
            out.append(flags)
        return out


@pytest.fixture
def fake(tmp_path, monkeypatch):
    return Fake(tmp_path, monkeypatch)


@pytest.fixture
def no_program(tmp_path, monkeypatch):
    """Nothing to find: not named in the environment, not built in engine/target/release."""
    monkeypatch.delenv(rust_backend.ENV_BINARY, raising=False)
    monkeypatch.setattr(rust_backend, "DEFAULT_BINARY", str(tmp_path / "not-built" / "subgame-solve"))


def same(a: RiverStrategy, b: RiverStrategy, tol=2e-6):
    """Two strategies of one spot, equal up to the 6 decimals a RESULT keeps."""
    return set(a.probs) == set(b.probs) and all(np.allclose(a.probs[k], b.probs[k], atol=tol) for k in a.probs)


# ------------------------------------------------------------------ the SPOT
def test_a_spot_goes_out_in_the_spot_format():
    s = spot(pot=200.0, stack=1000.0)
    d = rust_backend.spot_document(s)
    assert (d["format"], d["version"], d["street"], d["id"]) == ("pokerscribe-spot", 1, "river", "live")
    assert d["board"] == list(BOARD) and d["max_raises"] == 1 and d["spr"] == 5.0
    # whole amounts are written as whole numbers, as in the answer-key spots
    assert json.dumps([d["pot"], d["stacks"]]) == "[200, [1000, 1000]]"
    assert d["sizes"] == {"oop": {"bets": [0.5, 1.0], "raises": [1.0], "allin": True},
                          "ip": {"bets": [0.5, 1.0], "raises": [1.0], "allin": True}}
    # combos are spelled as the format says (higher rank first, then s, h, d, c), none on the board
    assert "AsKs" in d["ranges"]["oop"] and "KsAs" not in d["ranges"]["oop"]
    assert not any(card in combo for combo in d["ranges"]["oop"] for card in BOARD)
    # it reads back as the same spot, through JSON
    assert RiverSpot.from_dict(json.loads(json.dumps(d))) == s


def test_amounts_that_are_not_whole_stay_exact():
    s = spot(pot=67.5, stack=212.25, oop_sizes=BetSizes((70 / 200, 0.5), (1.0,), True))
    d = json.loads(json.dumps(rust_backend.spot_document(s)))
    assert d["pot"] == 67.5 and d["stacks"] == [212.25, 212.25] and d["spr"] == 3.14
    assert d["sizes"]["oop"]["bets"] == [70 / 200, 0.5]
    assert GameTree(RiverSpot.from_dict(d)).nodes.keys() == GameTree(s).nodes.keys()


def test_weights_over_one_are_scaled_down_together():
    s = RiverSpot(BOARD, 100, (300, 300), {"AsAh": 4.0, "QsQh": 1.0, "7s6s": 0.5}, {"KsQs": 2.0, "AdQd": 2.0, "4s4d": 1.0})
    d = rust_backend.spot_document(s)
    assert d["ranges"]["oop"] == {"AsAh": 1.0, "QsQh": 0.25, "7s6s": 0.125}
    assert d["ranges"]["ip"] == {"KsQs": 1.0, "AdQd": 1.0, "4s4d": 0.5}
    # weights that already fit are left alone
    assert rust_backend.spot_document(spot())["ranges"]["oop"]["AsKs"] == 1.0
    # and the answer is the same: only how a player's combos compare matters
    small = RiverSpot.from_dict(d)
    a = solve_river(s, None, max_iterations=60, target_exploitability=0)
    b = solve_river(small, None, max_iterations=60, target_exploitability=0)
    assert all(np.allclose(a.probs[k], b.probs[k], atol=1e-9) for k in a.probs)


# ------------------------------------- bet sizes the format has no word for
ADVICE = bridge.DEFAULT_SIZES  # what the advice gives both players: all in only up to six pots


def shape(s):
    return {key: node.actions for key, node in GameTree(s).nodes.items()}


def shape_from_the_document(s):
    """The tree a program builds that reads only what data/SPOT_FORMAT.md describes."""
    d = json.loads(json.dumps(rust_backend.spot_document(s)))
    assert all(set(sizes) == {"bets", "raises", "allin"} for sizes in d["sizes"].values())
    return shape(RiverSpot.from_dict(d))


def test_plain_sizes_go_out_as_they_are():
    s = spot()
    assert rust_backend.plain_sizes(s) == (s.oop_sizes, s.ip_sizes)


@pytest.mark.parametrize("stack", [0, 40, 100, 300, 600, 601, 1000, 1250, 1901, 5000])
def test_the_advices_sizes_are_said_with_the_three_the_format_has(stack):
    # pot 100. All in is a bet up to 600 (six pots), a raise of the half-pot bet up to 1250
    # and of the pot bet up to 1900: the same tree comes out of the document every time.
    s = spot(stack=float(stack), oop_sizes=ADVICE, ip_sizes=ADVICE)
    assert shape_from_the_document(s) == shape(s)
    oop, _ = rust_backend.plain_sizes(s)
    assert (max(oop.bets) > 1.0) == (0 < stack <= 600)  # a size as big as the stack stands for all in


def test_all_in_after_one_bet_but_not_the_other_cannot_be_said():
    # 1251 to 1900: all in answers the pot bet but not the half-pot bet, and one list of
    # raise sizes can't say that
    for stack in (1251.0, 1600.0, 1900.0):
        s = spot(stack=stack, oop_sizes=ADVICE, ip_sizes=ADVICE)
        with pytest.raises(UnsupportedSpot, match="can't say the (oop|ip) bet sizes"):
            rust_backend.spot_document(s)


def decision(hero_bet=0.0, villain_bet=0.0, stack=1000.0, in_position=False, line=None):
    """A spot as the advice makes it (bridge.river_decision), pot 200 before the river bets."""
    d = bridge.river_decision(["Ah", "Kd"], list(BOARD), pot_now=200.0 + hero_bet + villain_bet, hero_bet=hero_bet,
                              villain_bet=villain_bet, hero_stack=stack - hero_bet, villain_stack=stack - villain_bet,
                              hero_in_position=in_position, hero_range="TT+, AK, AQ, KQ", villain_range="88+, AK, KQ, QJs",
                              line=line)
    assert d is not None
    return d.spot


@pytest.mark.parametrize("stack", [150.0, 1000.0, 2000.0, 9000.0])
@pytest.mark.parametrize("in_position", [False, True])
def test_a_spot_from_the_table_keeps_its_tree(stack, in_position):
    # first to act or checked to, and facing a bet of 70 (its size is the only bet offered there)
    for villain_bet in (0.0, 70.0):
        s = decision(villain_bet=villain_bet, stack=stack, in_position=in_position)
        assert shape_from_the_document(s) == shape(s)
    villain = s.sizes(0 if in_position else 1)
    assert villain.exact == ("bets",) and villain.bets == (0.35,)


def test_facing_a_raise_can_be_said_only_when_the_usual_raise_is_all_in_anyway():
    # The hero bet 100, they raised to 300: after that the only raise left is all in, while
    # a raise of a first bet still has its usual size (the pot after calling). With 1000
    # behind, that size is all in here anyway (300 + 800), so one list says both.
    s = decision(hero_bet=100.0, villain_bet=300.0)
    assert s.oop_sizes.reraises == () and s.max_raises == 2
    assert GameTree(s)["b100 r300"].actions == ("f", "c", "r1000")
    assert shape_from_the_document(s) == shape(s)
    # With 3000 behind it is a raise to 1100, which the spot doesn't offer: two lists of
    # raises for one player, and a SPOT has one.
    s = decision(hero_bet=100.0, villain_bet=300.0, stack=3000.0)
    assert GameTree(s)["b100 r300"].actions == ("f", "c", "r3000")
    with pytest.raises(UnsupportedSpot):
        rust_backend.spot_document(s)


def test_a_spot_with_the_advices_sizes_goes_through_the_program(fake):
    s = decision(villain_bet=70.0)
    got = rust_backend.solve_river(s, None, max_iterations=30, target_exploitability=0)
    assert got.backend == "rust" and len(fake.calls()) == 1
    assert got.spot is s and got.tree.nodes.keys() == GameTree(s).nodes.keys()
    assert same(got, solve_river(s, None, max_iterations=30, target_exploitability=0))


def test_a_spot_that_cannot_be_said_goes_straight_to_the_python_solver(fake, caplog):
    s = decision(hero_bet=100.0, villain_bet=300.0, stack=3000.0)
    with caplog.at_level(logging.INFO, logger="app.solver.rust_backend"):
        got = rust_backend.solve_river(s, None, max_iterations=30, target_exploitability=0)
    assert got.backend == "python" and fake.calls() == []  # the program was never started
    assert not caplog.records  # nothing failed, so nothing to report
    assert same(got, solve_river(s, None, max_iterations=30, target_exploitability=0))



def test_extended_sizes_sends_such_a_spot_as_it_is(fake, monkeypatch):
    # for the day subgame-solve reads the three newer options: one constant to flip
    monkeypatch.setattr(rust_backend, "EXTENDED_SIZES", True)
    s = spot(stack=1600.0, oop_sizes=ADVICE, ip_sizes=ADVICE)
    d = rust_backend.spot_document(s)
    assert d["sizes"]["oop"] == {"bets": [0.5, 1.0], "raises": [1.0], "allin": True, "allin_within": 6.0}
    assert RiverSpot.from_dict(json.loads(json.dumps(d))) == s
    got = rust_backend.solve_river(s, None, max_iterations=30, target_exploitability=0)
    assert got.backend == "rust" and len(fake.calls()) == 1
    # a spot the three keys can say still goes out with the three keys
    plain = rust_backend.spot_document(spot(stack=1000.0, oop_sizes=ADVICE, ip_sizes=ADVICE))
    assert all(set(sizes) == {"bets", "raises", "allin"} for sizes in plain["sizes"].values())


# ------------------------------------------------------------ the program
def test_the_program_is_found_through_the_environment_or_the_release_build(tmp_path, monkeypatch):
    built = tmp_path / "release" / "subgame-solve"
    built.parent.mkdir()
    built.write_text("#!/bin/sh\n")
    named = tmp_path / "mine"
    named.write_text("#!/bin/sh\n")
    monkeypatch.setattr(rust_backend, "DEFAULT_BINARY", str(built))
    monkeypatch.delenv(rust_backend.ENV_BINARY, raising=False)
    assert rust_backend.find_binary() is None  # there, but not a program yet
    built.chmod(0o755)
    assert rust_backend.find_binary() == str(built)
    monkeypatch.setenv(rust_backend.ENV_BINARY, str(named))
    assert rust_backend.find_binary() is None  # the named one wins, and it can't be run
    named.chmod(0o755)
    assert rust_backend.find_binary() == str(named)
    monkeypatch.setenv(rust_backend.ENV_BINARY, str(tmp_path / "nowhere"))
    assert rust_backend.find_binary() is None  # a wrong name never falls back to another build
    assert rust_backend.DEFAULT_BINARY != "" and rust_backend.BINARY_NAME == "subgame-solve"


def test_the_default_place_is_the_cargo_release_folder():
    assert rust_backend.DEFAULT_BINARY.replace(os.sep, "/").endswith("engine/target/release/subgame-solve")
    assert os.path.isdir(os.path.join(rust_backend.REPO_ROOT, "engine", "crates"))


# ---------------------------------------------------- there and back again
def test_the_answer_comes_back_as_the_solvers_strategy(fake):
    s = spot()
    want = solve_river(s, None, max_iterations=40, target_exploitability=0)
    got = rust_backend.solve_river(s, None, max_iterations=40, target_exploitability=0)
    assert got.backend == "rust" and want.backend == "python"
    assert isinstance(got, RiverStrategy) and got.spot is s
    assert same(got, want)  # what the program worked out, to the 6 decimals of the file
    assert got.iterations == 40
    assert got.exploitability == pytest.approx(want.exploitability, abs=1e-12)
    assert got.exploitability == pytest.approx(exploitability(got).pot_share, abs=1e-5)
    assert got.elapsed_ms > 0
    # rows are exact probabilities again, although the file rounds them
    for p in got.probs.values():
        assert np.all(p >= 0) and np.allclose(p.sum(axis=1), 1.0, atol=1e-12)
    assert got.action_probs("", ("As", "Ah")) == pytest.approx(want.action_probs("", ("As", "Ah")), abs=2e-6)


def test_the_program_is_called_as_its_command_line_says(fake):
    rust_backend.solve_river(spot(), 9000, max_iterations=25, target_exploitability=0.002, threads=3)
    (call,) = fake.calls()
    assert set(call) == {"spot", "--out", "--target-exploitability", "--max-iterations", "--time-ms", "--threads"}
    assert os.path.basename(call["spot"]) == "live.json"
    assert float(call["--target-exploitability"]) == pytest.approx(0.2)  # percent of the pot, for a share of 0.002
    assert call["--max-iterations"] == "25" and call["--threads"] == "3"
    # the program's own time limit leaves room for starting it and reading the answer
    assert int(call["--time-ms"]) == 9000 - rust_backend.OVERHEAD_RESERVE_MS
    # the files are gone afterwards
    assert not os.path.exists(call["spot"]) and not os.path.exists(call["--out"])


def test_limits_that_are_not_given_are_not_passed(fake):
    got = rust_backend.solve_river(spot(), None, target_exploitability=0.01)
    (call,) = fake.calls()
    assert set(call) == {"spot", "--out", "--target-exploitability"}
    assert float(call["--target-exploitability"]) == pytest.approx(1.0)
    assert got.backend == "rust" and got.exploitability <= 0.01
    with pytest.raises(ValueError):  # as the Python solver: some limit is needed
        rust_backend.solve_river(spot(), None, target_exploitability=0)


@pytest.mark.parametrize("mode", ["gzip", "sorted-keys", "no-solver-numbers"])
def test_results_the_format_allows_are_read(fake, mode):
    fake.mode(mode)
    s = spot()
    got = rust_backend.solve_river(s, None, max_iterations=30, target_exploitability=0)
    assert got.backend == "rust"
    assert same(got, solve_river(s, None, max_iterations=30, target_exploitability=0))
    if mode == "no-solver-numbers":
        # the program gave no exploitability, so the Python checker's is filled in: the
        # advice drops an answer that is too rough, and must not take silence for "exact"
        assert got.iterations == 0 and got.exploitability == pytest.approx(exploitability(got).pot_share)
        told = rust_backend.run_solver(s, str(fake.path), max_iterations=30, target_exploitability=0).strategy
        assert told.exploitability is None  # run_solver itself reports only what the program said


def test_a_program_that_reads_the_target_in_another_unit_is_noticed(fake, caplog):
    # The target goes out in percent of the pot. A program that took the number for a
    # share would stop a hundred times too early and still say it converged.
    fake.mode("target-is-a-share")
    with caplog.at_level(logging.WARNING, logger=rust_backend.__name__):
        got = rust_backend.solve_river(spot(), None, target_exploitability=0.001)
    assert got.backend == "rust" and got.exploitability > 0.01
    (record,) = caplog.records
    assert "check the unit of --target-exploitability" in record.getMessage()
    caplog.clear()
    fake.mode("ok")
    with caplog.at_level(logging.WARNING, logger=rust_backend.__name__):
        got = rust_backend.solve_river(spot(), None, target_exploitability=0.001)
    assert got.exploitability <= 0.001 and not caplog.records


def test_a_real_bet_size_from_the_table_survives_the_trip(fake):
    # what the bridge builds facing a bet of 70 into 200: the bet is one of the sizes
    sizes = BetSizes((0.5, 1.0, 70 / 200), (1.0,), True)
    s = spot(pot=200.0, stack=1000.0, ip_sizes=sizes)
    got = rust_backend.solve_river(s, None, max_iterations=30, target_exploitability=0)
    assert got.backend == "rust" and "x b70" in got.probs
    assert same(got, solve_river(s, None, max_iterations=30, target_exploitability=0))


def test_run_solver_reports_where_the_time_went(fake):
    run = rust_backend.run_solver(spot(), rust_backend.find_binary(), max_iterations=20, target_exploitability=0.0)
    assert run.strategy.backend == "rust" and run.header["spot_id"] == "live"
    assert run.total_ms == pytest.approx(run.write_ms + run.run_ms + run.read_ms)
    assert run.result_bytes > 1000 and run.solver_ms is not None
    assert 0 < run.overhead_ms == pytest.approx(run.total_ms - run.solver_ms)
    assert run.strategy.elapsed_ms == pytest.approx(run.total_ms)


# ------------------------------------------------------------- falling back
def test_no_program_means_the_python_solver(no_program, caplog):
    s = spot()
    with caplog.at_level(logging.WARNING, logger=rust_backend.__name__):
        got = rust_backend.solve_river(s, None, max_iterations=40, target_exploitability=0)
    assert got.backend == "python" and got.iterations == 40
    want = solve_river(s, None, max_iterations=40, target_exploitability=0)
    assert all(np.array_equal(got.probs[k], want.probs[k]) for k in want.probs)
    assert not caplog.records  # not being built is normal, not a warning


FAILURES = {
    "crash": "exit code 101: thread 'main' panicked",
    "no-output": "wrote no result",
    "garbage": "not JSON Lines",
    "other-spot": "for spot 'r01'",
    "wrong-tree": "the spot's tree has",
    "missing-node": "nodes differ from the spot's tree",
    "missing-combo": "must list the",
    "bad-sum": "do not add up to 1",
}


@pytest.mark.parametrize("mode", sorted(FAILURES))
def test_a_failing_program_means_the_python_solver(fake, mode, caplog):
    fake.mode(mode)
    s = spot()
    with caplog.at_level(logging.WARNING, logger=rust_backend.__name__):
        got = rust_backend.solve_river(s, None, max_iterations=40, target_exploitability=0)
    assert len(fake.calls()) == 1  # it was tried, once
    assert got.backend == "python"
    want = solve_river(s, None, max_iterations=40, target_exploitability=0)
    assert all(np.array_equal(got.probs[k], want.probs[k]) for k in want.probs)
    (record,) = caplog.records
    assert "subgame-solve failed" in record.getMessage() and FAILURES[mode] in record.getMessage()
    # the same failure without the fallback is an error that says what was wrong
    with pytest.raises(RustSolverError, match=FAILURES[mode].replace("(", r"\(")):
        rust_backend.run_solver(s, str(fake.path), max_iterations=40, target_exploitability=0.0)


def test_a_program_that_cannot_be_started_means_the_python_solver(tmp_path, monkeypatch):
    broken = tmp_path / "subgame-solve"
    broken.write_bytes(b"\x00\x01 not a program")
    broken.chmod(0o755)
    monkeypatch.setenv(rust_backend.ENV_BINARY, str(broken))
    got = rust_backend.solve_river(spot(), None, max_iterations=10, target_exploitability=0)
    assert got.backend == "python" and got.iterations == 10


def test_a_slow_program_is_stopped_at_the_budget(fake, monkeypatch):
    fake.mode("slow")
    monkeypatch.setenv("FAKE_SUBGAME_SLEEP_S", "30")
    seen = {}

    def python_solver(s, budget_ms, **kw):
        seen["budget"] = budget_ms
        return solve_river(s, None, max_iterations=5, target_exploitability=0)

    monkeypatch.setattr(rust_backend, "python_solve_river", python_solver)
    got = rust_backend.solve_river(spot(), 300)
    assert got.backend == "python"
    assert 0 <= seen["budget"] < 50  # the budget went on waiting; the Python solver gets what is left
    assert 300 <= got.elapsed_ms < 3000  # stopped at the budget, not after the program's 30 seconds
    assert fake.calls()[0]["--time-ms"] == str(int(300 - rust_backend.OVERHEAD_RESERVE_MS))


def test_after_a_quick_failure_the_python_solver_gets_the_rest_of_the_budget(fake, monkeypatch):
    fake.mode("crash")
    seen = {}

    def python_solver(s, budget_ms, **kw):
        seen["budget"], seen["kw"] = budget_ms, kw
        return solve_river(s, None, max_iterations=5, target_exploitability=0)

    monkeypatch.setattr(rust_backend, "python_solve_river", python_solver)
    got = rust_backend.solve_river(spot(), 60_000, max_iterations=7, target_exploitability=0.004)
    assert 0 < seen["budget"] < 60_000 and got.elapsed_ms == pytest.approx(60_000 - seen["budget"], abs=2000)
    assert seen["kw"] == {"max_iterations": 7, "target_exploitability": 0.004}


# ------------------------------------------------------------ in the advice
BOARD_HU = ["Ac", "8d", "5c", "2h", "Js"]
HEADS_UP = dict(folded=["SB", "UTG", "HJ", "CO"])


def facing_bet():  # hero in the big blind checked, the button bet 100 into 200
    return table(["8h", "8s"], "BB", BOARD_HU, bets={"BTN": 100}, pot=200, to_call=100,
                 last={"BTN": Action("bet", 100)},
                 actions=[Action("fold"), Action("call", 100), Action("raise", 200)], **HEADS_UP)


def _never(*a, **kw):
    raise AssertionError("must not be called")


def test_the_switch_is_off_in_the_baseline():
    assert advice.TUNING["rust_solver"] is False and advice.TUNING["river_solver"] is False


def test_the_rust_switch_alone_changes_nothing(monkeypatch):
    before = go(facing_bet()).to_dict()
    monkeypatch.setattr(rust_backend, "solve_river", _never)
    monkeypatch.setattr(rust_backend, "run_solver", _never)
    monkeypatch.setitem(advice.TUNING, "rust_solver", True)  # river_solver is still off
    assert go(facing_bet()).to_dict() == before


def answers_call(name, calls):
    """A fake solver that calls wherever it can, and plays every action equally often
    elsewhere (so both players get to every node)."""
    def solve(s, **how):
        calls.append((name, how))
        return RiverStrategy.from_rule(s, lambda node, combo: (
            {"c": 1.0} if "c" in node.actions else [1 / len(node.actions)] * len(node.actions)))
    return solve


def test_with_the_river_solver_on_the_rust_switch_picks_who_solves(monkeypatch):
    calls = []
    monkeypatch.setattr(solver, "solve_river", answers_call("python", calls))
    monkeypatch.setattr(rust_backend, "solve_river", answers_call("rust", calls))
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    a = go(facing_bet())
    assert [name for name, _ in calls] == ["python"] and (a.action, a.basis) == ("call", "solver")
    # by the clock, stopping early at a hundredth of a big blind: the pot is 20 of them
    assert calls[0][1] == {"time_budget_ms": solver.DECISION_BUDGET_MS, "max_iterations": None,
                           "target_exploitability": pytest.approx(0.01 / 20)}
    monkeypatch.setitem(advice.TUNING, "rust_solver", True)
    a = go(facing_bet())
    assert [name for name, _ in calls] == ["python", "rust"] and (a.action, a.basis) == ("call", "solver")
    assert calls[1][1] == calls[0][1]  # asked in exactly the same way


def test_fixed_work_reaches_the_rust_backend_too(monkeypatch):
    # what the simulator turns on: no clock, a number of iterations
    calls = []
    monkeypatch.setattr(solver, "solve_river", _never)
    monkeypatch.setattr(rust_backend, "solve_river", answers_call("rust", calls))
    for name in ("river_solver", "rust_solver", "river_solver_fixed_work"):
        monkeypatch.setitem(advice.TUNING, name, True)
    assert go(facing_bet()).basis == "solver"
    ((_, how),) = calls
    assert how["time_budget_ms"] is None and how["max_iterations"] >= 16


def test_a_broken_backend_leaves_the_decision_to_the_rules(monkeypatch):
    before = go(facing_bet()).to_dict()

    def broken(s, **how):
        raise RuntimeError("bug")

    monkeypatch.setattr(rust_backend, "solve_river", broken)
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    monkeypatch.setitem(advice.TUNING, "rust_solver", True)
    assert go(facing_bet()).to_dict() == before


def test_the_advice_through_the_program(fake, monkeypatch):
    # A fixed amount of work in place of the clock, as the simulator runs it: the stand-in
    # takes a few hundred ms just to start Python, far more than the real program.
    for name in ("river_solver", "rust_solver", "river_solver_fixed_work"):
        monkeypatch.setitem(advice.TUNING, name, True)
    monkeypatch.setattr(rust_backend, "python_solve_river", _never)
    a = go(facing_bet())  # a set of eights facing a half-pot bet: never a fold
    assert a.basis == "solver" and a.action in ("call", "raise", "all-in")
    assert "river solver" in a.reason and "%" in a.detail
    (call,) = fake.calls()
    assert "--time-ms" not in call and int(call["--max-iterations"]) >= 16
    # the advice's target, a hundredth of a big blind in a pot of 20, goes out in percent
    assert float(call["--target-exploitability"]) == pytest.approx(100 * 0.01 / 20)
    # the spot went out with the three sizes the format has (their bet of 100 the only bet)
    assert go(facing_bet()).to_dict() == a.to_dict()  # and the same answer on every run


def test_the_advice_through_the_program_by_the_clock(fake, monkeypatch):
    # By the clock the program gets the budget less the reserve for the call itself. The
    # budget is made long here because of the stand-in's slow start, and its work is capped.
    monkeypatch.setattr(solver, "DECISION_BUDGET_MS", 60_000)  # what the advice checks
    monkeypatch.setattr(solver.solve, "DECISION_BUDGET_MS", 60_000)  # what decision_settings gives
    monkeypatch.setenv("FAKE_SUBGAME_MAX_ITERATIONS", "400")
    monkeypatch.setitem(advice.TUNING, "river_solver", True)
    monkeypatch.setitem(advice.TUNING, "rust_solver", True)
    monkeypatch.setattr(rust_backend, "python_solve_river", _never)
    a = go(facing_bet())
    assert a.basis == "solver" and a.action in ("call", "raise", "all-in")
    (call,) = fake.calls()
    assert int(call["--time-ms"]) == 60_000 - rust_backend.OVERHEAD_RESERVE_MS and "--max-iterations" not in call


def test_the_advice_without_the_program_uses_the_python_solver(no_program, monkeypatch):
    for name in ("river_solver", "rust_solver", "river_solver_fixed_work"):
        monkeypatch.setitem(advice.TUNING, name, True)
    a = go(facing_bet())
    assert a.basis == "solver" and a.action in ("call", "raise", "all-in")
    monkeypatch.setitem(advice.TUNING, "rust_solver", False)
    assert go(facing_bet()).to_dict() == a.to_dict()  # exactly what the switch being off gives


# ------------------------------------------------------- the real program
def test_the_real_program_when_it_is_built():
    """The contract, against the Rust crate itself. Skipped until `cargo build --release`
    has put subgame-solve in engine/target/release (or POKERSCRIBE_SUBGAME_SOLVE names it).

    Three spots: plain sizes; the advice's sizes ten pots deep, where all in is said as a
    size bigger than the stack (the program must turn that into all in, as the format
    says); and the same facing a bet of 70. run_solver refuses an answer for another tree."""
    binary = rust_backend.find_binary()
    if binary is None:
        pytest.skip("subgame-solve isn't built (cargo build --release in engine/)")
    with open(binary, "rb") as f:
        if f.read(2) == b"#!":
            pytest.skip("the program named is a script, not the Rust build")
    spots = [spot(), spot(stack=1000.0, oop_sizes=ADVICE, ip_sizes=ADVICE), decision(villain_bet=70.0, stack=2000.0)]
    if rust_backend.EXTENDED_SIZES:  # sizes only the three newer options can say
        spots.append(spot(stack=1600.0, oop_sizes=ADVICE, ip_sizes=ADVICE))
    for s in spots:
        run = rust_backend.run_solver(s, binary, time_ms=5000, target_exploitability=0.003, timeout_ms=60_000)
        assert run.strategy.backend == "rust"
        # within 1% of the pot of an equilibrium, by the Python checker (the solver's own
        # number is not trusted here)
        assert exploitability(run.strategy).pot_share < 0.01
        print(f"subgame-solve: {run.total_ms:.0f} ms in all, {run.run_ms:.0f} ms in the program, "
              f"{run.strategy.iterations} iterations")
