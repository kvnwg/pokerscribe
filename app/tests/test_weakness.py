"""Phase 1: the held-out opponents, the weakness report (tools/weakness.py), and that the
classic simulator still gives the numbers every earlier experiment was made with."""
import os
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")


@pytest.fixture(scope="module")
def tools():
    sys.path.insert(0, TOOLS)
    try:
        import simulate
        import weakness
    finally:
        sys.path.remove(TOOLS)
    return simulate, weakness


def test_classic_simulation_unchanged(tools):
    """The same results as before Phase 1 (values from the commit that imported the repo),
    so every row in experiments.md can still be rebuilt."""
    sim, _ = tools
    st = sim.run(12, "maniacs", 2, quiet=True, stacks="tourney")
    assert [round(x, 4) for x in st["hands"]] == [-10.0, 0.0, 13.8289, 0.0, -1.0, -0.5, 0.0, 0.0, 0.0, 0.0, -1.0, 48.0]
    st = sim.run(30, "lags", 4, quiet=True)
    assert round(sum(st["hands"]), 4) == 24.3683


def test_held_out_tables_play_without_problems(tools):
    """Every held-out table plays, the app makes no always-wrong move against it, and the
    held-out styles are never in a tuning table."""
    sim, _ = tools
    for table in sim.HELD_OUT_TABLES:
        st = sim.run(18, table, 3, quiet=True)
        assert len(st["hands"]) == 18 and not st["problems"], (table, dict(st["problems"]))
        assert not set(sim.TABLES[table]) & set(sim.STYLES)
    for table in sim.TUNING_TABLES:
        assert not set(sim.TABLES[table]) & set(sim.HELD_OUT)


def test_switcher_changes_style(tools):
    sim, _ = tools
    seat = sim.Seat("switcher", name="switcher2")
    styles = {sim.bot_style(sim.Hand(seats=[seat], button=0, number=n), seat)[0] for n in range(1, 61)}
    assert styles == {"station", "maniac"}
    w = sim.Seat("wildcard", name="wildcard3")
    h = sim.Hand(seats=[w], button=0)
    assert sim.bot_style(h, w)[1] == sim.bot_style(h, w)[1] != sim.bot_style(h, sim.Seat("wildcard", name="wildcard4"))[1]


def test_alternative_moves(tools):
    sim, wk = tools
    bb = sim.BB
    # first in before the flop, 100 big blinds: fold, limp, raise to 2.5 or 4 big blinds, no all in
    assert wk.alternative("fold", bb, 1.5 * bb, bb, 100 * bb, 0) == ("fold", 0.0)
    assert wk.alternative("passive", bb, 1.5 * bb, bb, 100 * bb, 0) == ("call", 0.0)
    assert wk.alternative("small", bb, 1.5 * bb, bb, 100 * bb, 0) == ("raise", 2.5 * bb)
    assert wk.alternative("big", bb, 1.5 * bb, bb, 100 * bb, 0) == ("raise", 4 * bb)
    assert wk.alternative("all-in", bb, 1.5 * bb, bb, 100 * bb, 0) is None
    assert wk.alternative("all-in", bb, 1.5 * bb, bb, 12 * bb, 0) == ("raise", 12 * bb)
    # checked to on the flop with a pot of 10: no fold; bets of 4 and 10
    assert wk.alternative("fold", 0, 10, 0, 200, 3) is None
    assert wk.alternative("passive", 0, 10, 0, 200, 3) == ("check", 0.0)
    assert wk.alternative("small", 0, 10, 0, 200, 3) == ("raise", 4.0)
    assert wk.alternative("big", 0, 10, 0, 200, 3) == ("raise", 10.0)
    assert wk.alternative("big", 0, 10, 0, 10.5, 3) is None  # that would be all in


def test_planted_flaws_change_the_move(tools):
    sim, wk = tools
    seats = [sim.Seat("app", stack=200, cards=("7c", "2d"))] + [sim.Seat("tag", stack=200) for _ in range(5)]
    h = sim.Hand(seats=seats, button=0, board=["2h", "5s", "9c", "Jd", "Kh"])
    assert wk.FLAWS["never_bets_river"][1](h, 0, None, ("raise", 20.0)) == ("check", 0.0)
    h.current = 10.0
    assert wk.FLAWS["calls_river_bets"][1](h, 0, None, ("fold", 0.0)) == ("call", 0.0)
    assert wk.FLAWS["never_bets_river"][1](h, 0, None, ("call", 0.0)) == ("call", 0.0)
    sig = wk.FLAWS["calls_river_bets"][2]
    assert wk.matches(("river", "facing a bet", "nothing", "call"), sig)
    assert not wk.matches(("turn", "facing a bet", "nothing", "call"), sig)
    assert wk.matches(("turn", "checked to", "pair", "bet"), wk.FLAWS["overbets"][2])


def test_weakness_report_runs(tools):
    """A short run: every replayed move has a gain or None, folding has an exact gain, and
    the report prints."""
    _, wk = tools
    res = wk.analyse(12, "maniacs", 2, quiet=True)
    assert len(res["hands"]) == 12 and res["decisions"]
    for dec in res["decisions"]:
        assert set(dec["gains"]) == set(wk.MOVES)
        if dec["spot"]["move"] == "fold":
            assert dec["gains"]["fold"] is None
    text = wk.summary(res, 5)
    assert "Luck-adjusted by position" in text


def test_weakness_split_over_processes(tools):
    """--jobs: the same decisions, gains and hands as one process."""
    _, wk = tools
    one = wk.analyse(24, "maniacs", 4, quiet=True)
    two = wk.analyse(24, "maniacs", 4, quiet=True, jobs=2)
    assert one["hands"] == two["hands"]
    assert [(d["key"], d["gains"]) for d in one["decisions"]] == [(d["key"], d["gains"]) for d in two["decisions"]]
    assert wk.flaw_cost(12, "maniacs", 4, "limps") == wk.flaw_cost(12, "maniacs", 4, "limps", jobs=2)
