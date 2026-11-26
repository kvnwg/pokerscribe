"""The timing harness, the label format and the two solver scripts."""
import json
import time

import pytest

from app.solver import RiverStrategy, solve_river
from app.solver.labels import make_label, read_labels, validate_label, write_labels
from app.solver.timing import SPRS, TimingReport, benchmark_spots, percentile, time_decisions
from tools import label_river, solver_timing

from .solver_games import half_street_equilibrium


# ------------------------------------------------------------------- timing
def test_percentiles_are_nearest_rank():
    ten = list(range(1, 11))
    assert percentile(ten, 50) == 5  # ceil(0.50 x 10) = 5th smallest
    assert percentile(ten, 95) == 10  # ceil(0.95 x 10) = 10th
    twenty = list(range(20, 0, -1))  # order doesn't matter
    assert percentile(twenty, 95) == 19  # ceil(0.95 x 20) = 19th
    assert percentile(twenty, 50) == 10
    assert percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1], 0)


def test_time_decisions_measures_each_call():
    # a clock that moves 100, 250, 450 and 50 ms across the four calls
    ticks = iter([0.0, 0.100, 1.0, 1.250, 2.0, 2.450, 3.0, 3.050])
    seen = []
    report = time_decisions(["a", "b", "c", "d"], seen.append, clock=lambda: next(ticks))
    assert seen == ["a", "b", "c", "d"]
    assert report.times_ms == pytest.approx((100, 250, 450, 50))
    assert report.p50 == pytest.approx(100)  # sorted 50 100 250 450: the 2nd
    assert report.p95 == pytest.approx(450)
    assert report.over_target == 1 and not report.passed
    assert "FAIL" in str(report)
    ok = TimingReport((10.0, 20.0, 399.0))
    assert ok.passed and "PASS" in str(ok)


def test_benchmark_spots_repeat_exactly():
    a, b = benchmark_spots(6, seed=3), benchmark_spots(6, seed=3)
    assert a == b and len(a) == 6
    assert benchmark_spots(6, seed=4) != a
    for spot in a:
        assert 20 <= spot.pot <= 200
        assert any(abs(spot.effective_stack - r * spot.pot) < 1e-6 for r in SPRS)
        assert len(spot.oop_range) > 200 and len(spot.ip_range) > 200


def test_timing_script(capsys):
    assert solver_timing.main(["--spots", "3"]) == 2  # the stub
    assert "isn't written yet" in capsys.readouterr().out
    fast = lambda spot, ms: RiverStrategy.uniform(spot)  # noqa: E731
    assert solver_timing.main(["--spots", "3"], solver=fast) == 0
    assert "p95" in capsys.readouterr().out

    def slow(spot, ms):
        time.sleep(0.01)
        return None

    assert solver_timing.main(["--spots", "3", "--target-ms", "5"], solver=slow) == 1


# ------------------------------------------------------------------- labels
def _label(**kw):
    st = half_street_equilibrium(1.0)
    return make_label(st, "x b100", source="test", created="2026-11-26T00:00:00Z", **kw)


def test_a_label_holds_the_strategy_of_every_combo_that_gets_there():
    rec = _label(held="QdQs", observed={"action": "c"})
    assert rec["actor"] == "oop" and rec["node"] == "x b100" and rec["label_source"] == "solver"
    assert len(rec["strategy"]) == 6
    assert rec["strategy"]["QsQd"] == pytest.approx({"f": 0.5, "c": 0.5})
    assert rec["held"] == "QsQd"  # written in the spot's own order
    bettor = make_label(half_street_equilibrium(1.0), "x", source="test")
    assert bettor["actor"] == "ip" and len(bettor["strategy"]) == 19


def test_labels_round_trip_through_json_lines(tmp_path):
    path = str(tmp_path / "labels.jsonl")
    assert write_labels(path, []) == 0 and not (tmp_path / "labels.jsonl").exists()
    assert write_labels(path, [_label(), _label()]) == 2
    assert write_labels(path, [_label()]) == 1  # appends
    back = list(read_labels(path))
    assert len(back) == 3 and back[0] == json.loads(json.dumps(_label()))
    with open(path, "a") as f:
        f.write(json.dumps(dict(back[0], actor="ip")) + "\n")
    with pytest.raises(ValueError, match="line 4"):
        list(read_labels(path))


@pytest.mark.parametrize("change, message", [
    (lambda r: r.update(label_source="observed"), "never labels"),
    (lambda r: r.update(node="x b100 c"), "isn't a decision"),
    (lambda r: r.update(node="x b55"), "isn't a decision"),
    (lambda r: r.update(actor="ip"), "acts, not"),
    (lambda r: r["strategy"].update(KsKd={"f": 0.5, "c": 0.5}), "isn't in the oop range"),
    (lambda r: r["strategy"].update(QsQd={"f": 0.7, "c": 0.7}), "add up to 1"),
    (lambda r: r["strategy"].update(QsQd={"c": 1.0}), "exactly"),
    (lambda r: r.update(strategy={}), "no combos"),
    (lambda r: r.update(held="KsKd"), "held combo"),
    (lambda r: r.pop("spot"), "Missing"),
    (lambda r: r.update(version=99), "version"),
])
def test_bad_labels_are_refused(change, message):
    rec = json.loads(json.dumps(_label()))
    change(rec)
    with pytest.raises(ValueError, match=message):
        validate_label(rec)


def test_terminal_nodes_cannot_be_labelled():
    with pytest.raises(ValueError, match="not a decision"):
        make_label(half_street_equilibrium(1.0), "x x", source="test")


def test_label_script(tmp_path, capsys):
    out = str(tmp_path / "labels.jsonl")
    assert label_river.main(["--synthetic", "2", "--out", out]) == 2  # the stub
    assert "isn't written yet" in capsys.readouterr().out
    assert not (tmp_path / "labels.jsonl").exists()
    assert label_river.main(["--phh", "x.parquet", "--out", out]) == 2
    capsys.readouterr()

    uniform = lambda spot, ms: RiverStrategy.uniform(spot)  # noqa: E731
    assert label_river.main(["--synthetic", "2", "--ranges", "narrow", "--out", out], solver=uniform) == 0
    assert "Wrote" in capsys.readouterr().out
    recs = list(read_labels(out))
    nodes = sum(1 for _ in uniform(benchmark_spots(2, 1, "narrow")[0], 0).tree.decision_nodes())
    assert {r["source"] for r in recs} == {"synthetic:seed=1:spot=0", "synthetic:seed=1:spot=1"}
    assert sum(r["source"].endswith("spot=0") for r in recs) == nodes


def test_the_solver_stub_says_it_is_not_written():
    with pytest.raises(NotImplementedError):
        solve_river(half_street_equilibrium(1.0).spot, 100)
