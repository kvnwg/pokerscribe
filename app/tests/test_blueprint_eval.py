"""tools/blueprint_eval.py, the Phase 6 evaluation command: its arithmetic (pooling B0's
processes, the hands a 2.5 SE result needs), which pairs it compares, the gate's reading, and
the whole command on fake measurements (sorted by iterations, work already
done is not run again, the summary written)."""
import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
import blueprint_eval as be  # noqa: E402

sys.path.pop(0)


def test_labels_and_pairs():
    assert be.label(1_000_000) == "it1M" and be.label(512_000_000) == "it512M"
    assert be.label(2_048_000_000) == "it2.05G" and be.label(8_192_000_000) == "it8.19G"
    assert be.label(500) == "it500" and be.label(4_000) == "it4k"
    assert be.pairs(1) == [] and be.pairs(2) == [(0, 1)]
    assert be.pairs(4) == [(0, 1), (1, 2), (2, 3), (0, 3)]


def test_pool_weights_by_deals_and_adds_variances():
    a = {"deals": 1000, "bb_per_100": 10.0, "se": 10.0}
    b = {"deals": 3000, "bb_per_100": 2.0, "se": 10.0 / math.sqrt(3)}
    p = be.pool([a, b])
    assert p["deals"] == 4000 and p["bb_per_100"] == pytest.approx(4.0)
    # Both parts have sd 10 * sqrt(1000) a deal: the pooled sd is the same, the se halves.
    assert p["sd_per_deal"] == pytest.approx(10 * math.sqrt(1000))
    assert p["se"] == pytest.approx(5.0)
    assert be.pool([])["bb_per_100"] is None


def test_hands_needed():
    # sd 350 a deal, a 10 bb/100 edge at 2.5 SE: (2.5 * 350 / 10)^2 = 7656.25 deals.
    assert be.hands_needed(350, 10) == 7657 * 2
    assert be.hands_needed(350, -10) == be.hands_needed(350, 10)
    assert be.hands_needed(350, 5) > 3.9 * be.hands_needed(350, 10)


def test_stop_rule():
    files = [{"label": "a", "change": None}, {"label": "b", "change": 0.2},
             {"label": "c", "change": 0.07}, {"label": "d", "change": 0.05}]
    lbr = {("b56_14", 0): 500.0, ("b56_14", 1): 300.0, ("b56_14", 2): 200.0, ("b56_14", 3): 205.0}
    pairs = {("b56_14", 0, 1): step(-200, 10), ("b56_14", 1, 2): step(-100, 10),
             ("b56_14", 2, 3): step(5, 10)}
    r = be.stop_rule(files, lbr, pairs)
    assert [x["stop"] for x in r] == [False, False, True]
    assert r[1]["change_small"] and not r[1]["lbr_flat"]
    # 5 bb/100 on 200 is 2.5%, under 3%; and 0.5 SE: flat either way.
    assert r[2]["lbr_flat"]


def step(d, se):
    return {"difference": d, "std_err": se, "z": d / se}


def test_projection_of_the_stop():
    # The change halves at each doubling: 0.64 at 8M, 0.32 at 16M, 0.16 at 32M, so 0.08 at 64M.
    files = [{"iterations": 4_000_000, "change": None}] + [
        {"iterations": i, "change": c} for i, c in ((8_000_000, 0.64), (16_000_000, 0.32),
                                                    (32_000_000, 0.16))]
    log = [{"from": 0, "to": 1_000_000, "seconds": 30},              # too short: not used
           {"from": 1_000_000, "to": 31_000_000, "seconds": 300},
           {"from": 31_000_000, "to": 32_000_000, "seconds": 10}]   # too short
    p = be.projection(files, log)
    assert p["stages_used"] == [8_000_000, 16_000_000, 32_000_000]
    assert p["factor_per_doubling"] == pytest.approx(0.5)
    assert p["iterations"] == pytest.approx(64_000_000)
    assert p["stage"] == 64_000_000
    assert p["iterations_per_second"] == pytest.approx(100_000)
    assert p["hours_left"] == pytest.approx(32_000_000 / 100_000 / 3600)
    # Just past a stage, the run stops at the next one.
    p = be.projection(files, log, max_change=0.075)
    assert p["iterations"] > 64_000_000 and p["stage"] == 128_000_000
    # A change that isn't falling, or too few stages: no projection.
    rising = [dict(f, change=None if f["change"] is None else 1 - f["change"]) for f in files]
    assert "iterations" not in be.projection(rising, log)
    assert "reason" in be.projection(files[:3], log)
    assert "hours_left" not in be.projection(files, [])


def test_gate_readings():
    files = [{"label": f"f{i}"} for i in range(4)]
    lbr = {("fcpa14", 0): 300.0, ("fcpa14", 3): 250.0}
    pairs = {("fcpa14", 0, 1): step(-20, 5), ("fcpa14", 1, 2): step(5, 5),
             ("fcpa14", 2, 3): step(-35, 10), ("fcpa14", 0, 3): step(-50, 10),
             ("b56_14", 0, 1): step(30, 5), ("b56_14", 1, 2): step(30, 5),
             ("b56_14", 2, 3): step(30, 5), ("b56_14", 0, 3): step(90, 10)}
    h2h = {(0, 3): {"bb_per_100": 6.0, "se": 2.0}}
    b0 = {3: {"blueprint_bb_per_100": 20.0, "se": 10.0}}
    g = be.gate_readings(files, lbr, pairs, h2h, b0, ["fcpa14", "b56_14"])
    h = g["h2h_last_beats_first"]
    assert h["passes"] and h["z"] == 3 and (h["first"], h["last"]) == ("f0", "f3")
    assert not g["b0_beaten"]["passes"] and g["b0_beaten"]["z"] == 2
    assert g["passes"] is False                        # B0 is beaten by only 2 SE
    b0[3]["blueprint_bb_per_100"] = 25.0
    assert be.gate_readings(files, lbr, pairs, h2h, b0, ["fcpa14"])["passes"] is True
    # LBR is reported only: rising LBR doesn't fail the gate.
    r = g["lbr_reported"]
    assert r["fcpa14"] == {"first": 300.0, "last": 250.0, "difference": -50, "se": 10, "z": -5,
                           "steps": 3, "fell": 2, "fell_by_2_5_se": 2, "rose_by_2_5_se": 0}
    assert r["b56_14"]["fell"] == 0 and r["b56_14"]["rose_by_2_5_se"] == 3
    none = be.gate_readings(files[:1], {}, {}, {}, {}, ["fcpa14"])
    assert none["h2h_last_beats_first"] is None and none["passes"] is None
    no_b0 = be.gate_readings(files, lbr, pairs, h2h, {}, ["fcpa14"])
    assert no_b0["passes"] is None and no_b0["h2h_last_beats_first"]["passes"]


class FakeRunner(be.Runner):
    """LBR wins 400 - 50 a doubling; each file beats the one before by 3 bb/100."""

    def __init__(self, its):
        super().__init__(blueprint="blueprint", say=lambda _line: None)
        self.its = its
        self.calls = []

    def header(self, path):
        return {"iterations": self.its[os.path.basename(path)], "info_sets": 97, "visited": 90}

    def lbr(self, paths, names, settings, hands, seed, deals_dir):
        out = []
        for setting in settings:
            for path, name in zip(paths, names):
                self.calls.append(("lbr", name, setting))
                k = math.log2(self.its[os.path.basename(path)] / 1e6)
                out.append({"bb_per_100": 400 - 50 * k + (100 if setting.startswith("b56") else 0),
                            "std_err": 8.0, "hands": hands, "strategy": name, "seconds": 1.0,
                            "deals_file": f"{deals_dir}/{name}.{setting}.s{seed}.deals",
                            "setting_short": setting, "hands_per_second": 50.0,
                            "extra": {"off_tree_share": 0.18}})
        self.lbr_calls = getattr(self, "lbr_calls", 0) + 1
        return out

    def compare(self, a, b):
        self.calls.append(("compare", a, b))
        ka = math.log2(float(a.rsplit("/it", 1)[1].split("M.")[0]))
        kb = math.log2(float(b.rsplit("/it", 1)[1].split("M.")[0]))
        d = -50 * (ka - kb)
        return {"difference": d, "std_err": 6.0, "z": d / 6.0}

    def h2h(self, a, b, deals, seed, stack_bb):
        self.calls.append(("h2h", os.path.basename(a), os.path.basename(b)))
        assert stack_bb == 200
        return {"bb_per_100": 3.0, "se": 1.0, "hands": 2 * deals, "deals": deals}

    def b0(self, path, deals, seed, processes, stack_bb, out_dir, name):
        self.calls.append(("b0", name, processes))
        return {"blueprint_bb_per_100": 40.0, "se": 10.0, "sd_per_deal": 10.0 * math.sqrt(deals),
                "deals": deals, "hands": 2 * deals, "processes": processes,
                "b0_not_legal_as_said": 0, "wall_seconds": 100.0, "hands_per_second": 2 * deals / 100}


def test_evaluate_on_fake_measurements(tmp_path):
    names = {"strategy-4000000.bps": 4_000_000, "strategy-1000000.bps": 1_000_000,
             "strategy-2000000.bps": 2_000_000}
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    with open(tmp_path / "stages.jsonl", "w") as f:
        f.write(json.dumps({"iterations": 1_000_000, "change": None, "change_from": None}) + "\n")
        f.write(json.dumps({"iterations": 2_000_000, "change": 0.3,
                            "change_from": "strategy-1000000.bps"}) + "\n")
        f.write(json.dumps({"iterations": 4_000_000, "change": 0.2,
                            "change_from": "strategy-2000000.bps"}) + "\n")
    out = tmp_path / "eval"
    r = FakeRunner(names)
    paths = [str(tmp_path / n) for n in names]
    s = be.evaluate(paths, str(out), r, ["fcpa14", "b56_14"], lbr_hands=1000, h2h_deals=500,
                    b0_deals=400, b0_processes=4)
    assert [f["label"] for f in s["files"]] == ["it1M", "it2M", "it4M"]
    assert [f["change"] for f in s["files"]] == [None, 0.3, 0.2]
    assert sum(1 for c in r.calls if c[0] == "lbr") == 6 and r.lbr_calls == 1
    assert [c[1:] for c in r.calls if c[0] == "h2h"] == [
        ("strategy-1000000.bps", "strategy-2000000.bps"),
        ("strategy-2000000.bps", "strategy-4000000.bps"),
        ("strategy-1000000.bps", "strategy-4000000.bps")]
    assert [c for c in r.calls if c[0] == "b0"] == [("b0", "it4M", 4)]
    g = s["gate"]
    assert g["h2h_last_beats_first"]["passes"] and g["passes"] is True
    assert g["b0_beaten"]["passes"] and g["b0_beaten"]["z"] == 4
    assert g["lbr_reported"]["fcpa14"]["difference"] == -100
    assert g["lbr_reported"]["fcpa14"]["fell"] == 2
    b0 = s["b0"][0]
    assert b0["needed_hands"]["10"] == be.hands_needed(b0["sd_per_deal"], 10)
    md = (out / "summary.md").read_text()
    for want in ("| it4M | 4,000,000 | 0.2000 | strategy-2000000.bps |", "## The gate",
                 "- Head to head, the last file against the first: it4M against it1M, +3.00",
                 "- The gate: passes", "- Reported: LBR fcpa14 from +400.0 to +300.0", "18.0%"):
        assert want in md, want
    assert "\u2014" not in md  # no em dash
    assert json.loads((out / "summary.json").read_text())["seeds"]["lbr"] == be.LBR_SEED
    # Run again with one more file: only the new measurements are made.
    (tmp_path / "strategy-8000000.bps").write_bytes(b"x")
    names["strategy-8000000.bps"] = 8_000_000
    r2 = FakeRunner(names)
    be.evaluate(paths + [str(tmp_path / "strategy-8000000.bps")], str(out), r2,
                ["fcpa14", "b56_14"], lbr_hands=1000, h2h_deals=500, b0_deals=0, b0_processes=4)
    assert [c[1:] for c in r2.calls if c[0] == "lbr"] == [("it8M", "fcpa14"), ("it8M", "b56_14")]
    assert r2.lbr_calls == 1
    assert [c[1:] for c in r2.calls if c[0] == "h2h"] == [
        ("strategy-4000000.bps", "strategy-8000000.bps"),
        ("strategy-1000000.bps", "strategy-8000000.bps")]
