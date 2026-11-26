"""The answer-key spots and the TexasSolver converter (tools/answer_keys).

TexasSolver itself isn't run here. Its output is imitated from our own trees and
strategies in the shape data/answer_keys/README.md describes, and a stand-in program
plays the solver for the end-to-end test.
"""
import json
import os
import re
import stat
import sys

import numpy as np
import pytest

from app.poker.ranges import class_combos
from app.solver import GameTree, solve_river
from app.solver.exploitability import exploitability
from app.solver.spot import PLAYER_NAMES
from tools.answer_keys import __main__ as cli
from tools.answer_keys import texassolver as ts
from tools.answer_keys.build import build_spot, dumps_spot
from tools.answer_keys.checks import (check_expected, nodes_from_river_strategy, river_exploitability,
                                      river_strategy)
from tools.answer_keys.result import read_result, validate_result, write_result
from tools.answer_keys.spot_defs import SPOTS
from tools.answer_keys.spots import (SPOTS_DIR, SpotError, class_weights, decision_nodes, deck_left,
                                     expand_range_text, load_spots, river_spot, spot_hash, validate_spot)


@pytest.fixture(scope="module")
def spots():
    return {s["id"]: s for s in load_spots()}


# ------------------------------------------------------------------ the spots
def test_spot_files_are_built_from_spot_defs(spots):
    assert len(SPOTS) == len(spots) == 40
    for defn in SPOTS:
        with open(os.path.join(SPOTS_DIR, defn["id"] + ".json")) as f:
            assert f.read() == dumps_spot(build_spot(defn)), f"{defn['id']}: run make-spots"


def test_the_set_covers_what_was_asked(spots):
    streets = [s["street"] for s in spots.values()]
    assert streets.count("river") == 30 and streets.count("turn") == 10
    tags = [set(s["tags"]) for s in spots.values()]
    assert sum("trivial" in t for t in tags) == 3
    for tag in ("dry", "wet", "polar", "condensed", "wide", "paired"):
        assert any(tag in t for t in tags), tag
    sprs = {s["spr"] for s in spots.values()}
    assert min(sprs) == 0.5 and max(sprs) == 5
    for street in ("river", "turn"):
        assert {0.5, 5} <= {s["spr"] for s in spots.values() if s["street"] == street}
    counts = {len(s["sizes"]["ip"]["bets"]) for s in spots.values()}
    assert counts == {1, 2, 3}
    assert all(s.get("expected") for s in spots.values() if "trivial" in s["tags"])
    assert any(s["max_raises"] == 2 for s in spots.values())


def test_every_spot_gives_texassolver_whole_classes(spots):
    for s in spots.values():
        for p in ("oop", "ip"):
            classes = class_weights(s["ranges"][p], s["board"])
            # the class text TexasSolver gets expands back to exactly the spot's combos
            assert expand_range_text(ts.range_text(s, p), s["board"]) == s["ranges"][p]
            assert classes


def test_bad_spots_are_refused(spots):
    s = json.loads(json.dumps(spots["r04"]))
    s["board"] = s["board"][:4]
    with pytest.raises(SpotError):
        validate_spot(s)
    s = json.loads(json.dumps(spots["r04"]))
    s["ranges"]["oop"]["AsAd"] = 1.0  # not in its range_text
    with pytest.raises(SpotError):
        validate_spot(s)
    with pytest.raises(SpotError):  # half of a class can't be written for TexasSolver
        class_weights({"AsKs": 1.0, "AhKh": 1.0}, ["2c", "3d", "4h", "5s", "7c"])
    with pytest.raises(SpotError):  # nor a class with two weights
        class_weights({c[0] + c[1]: (1.0 if i else 0.5) for i, c in enumerate(class_combos("QQ"))},
                      ["2c", "3d", "4h", "5s", "7c"])
    defn = dict(SPOTS[5], sizes={"oop": {"bets": [0.75], "raises": [], "allin": True},
                                 "ip": {"bets": [0.75], "raises": [], "allin": True}})
    with pytest.raises(SpotError, match="not under the stack"):  # SPR 0.5: a 0.75 bet is all in
        build_spot(defn)


def test_the_river_tree_is_app_solvers_tree(spots):
    for s in spots.values():
        if s["street"] != "river":
            continue
        tree = GameTree(river_spot(s))
        ours = {k: (v.actor, v.actions) for k, v in decision_nodes(s).items()}
        assert ours == {n.key: (PLAYER_NAMES[n.player], n.actions) for n in tree.decision_nodes()}


def test_the_turn_tree_deals_every_river_card(spots):
    s = spots["t01"]  # pot 100, stacks 300, half-pot bets, all in
    nodes = decision_nodes(s)
    cards = deck_left(s["board"])
    assert len(cards) == 48
    for ending in ("x x", "b50 c", "x b50 c"):
        for card in cards:
            key = f"{ending} {card}"
            assert nodes[key].actor == "oop" and nodes[key].street == "river"
    assert nodes["b50 c 2d"].pot == 200 and nodes["b50 c 2d"].stack == 250
    assert nodes["b50 c 2d"].actions == ("x", "b100", "b250")
    assert not any(k.startswith("b300 c ") for k in nodes)  # all in on the turn: no river betting
    assert not any(k.startswith("b50 r300 c ") for k in nodes)


def test_trivial_spots_have_the_obvious_answer_from_our_solver(spots):
    for spot_id in ("r01", "r02", "r03"):
        s = spots[spot_id]
        strategy = solve_river(river_spot(s), time_budget_ms=30000, target_exploitability=0.003)
        assert check_expected(s, nodes_from_river_strategy(strategy)) == []


def test_a_wrong_answer_fails_the_trivial_checks(spots):
    s = spots["r01"]
    always_call = {k: {**rec, "strategy": {c: {a: (1.0 if a == "c" else 0.0) for a in rec["actions"]}
                                           if "c" in rec["actions"] else row for c, row in rec["strategy"].items()}}
                   for k, rec in nodes_from_river_strategy(solve_river(river_spot(s), 2000)).items()}
    failures = check_expected(s, always_call)
    assert failures and all("f 0.000 < 0.98" in f for f in failures)


# ------------------------------------------------- imitating TexasSolver's output
def _amount_text(tok, node, reading):
    new = float(tok[1:])
    mine = node.put_in[0 if node.actor == "oop" else 1]
    theirs = node.put_in[1 if node.actor == "oop" else 0]
    a = {"to": new, "by": new - mine, "over_call": new - theirs}[reading]
    return f"{'BET' if tok[0] == 'b' else 'RAISE'} {a:.6f}"


def _action_text(tok, node, reading):
    return {"x": "CHECK", "c": "CALL", "f": "FOLD"}.get(tok) or _amount_text(tok, node, reading)


def fake_dump(spot, rows, reading="to", children_key="childrens", shuffle=False):
    """TexasSolver-shaped output for a spot: rows(node, combo) -> probabilities in the
    node's action order. Player 1 is out of position, as we believe TexasSolver numbers them."""
    nodes = decision_nodes(spot)

    def combos_at(node):
        dead = set(node.key.split()) if spot["street"] == "turn" else set()
        return [c for c in spot["ranges"][node.actor] if c[:2] not in dead and c[2:] not in dead]

    def build(key):
        node = nodes[key]
        order = list(node.actions)[::-1] if shuffle else list(node.actions)
        texts = [_action_text(t, node, reading) for t in order]
        kids = {}
        for tok, text in zip(order, texts):
            child = f"{key} {tok}".strip()
            if child in nodes:
                kids[text] = build(child)
            else:
                cards = {k.split()[-1]: build(k) for k in nodes
                         if k.startswith(child + " ") and len(k.split()) == len(child.split()) + 1
                         and re.fullmatch(r"[2-9TJQKA][cdhs]", k.split()[-1])}
                if cards:
                    kids[text] = {"node_type": "chance_node", "deal_number": len(cards), "dealcards": cards}
        strategy = {}
        for c in combos_at(node):
            p = dict(zip(node.actions, rows(node, c)))
            strategy[c[2:] + c[:2]] = [p[t] for t in order]  # cards in the other order
        return {"node_type": "action_node", "player": 1 if node.actor == "oop" else 0, "actions": texts,
                children_key: kids, "strategy": {"actions": texts, "strategy": strategy}}

    return build("")


@pytest.mark.parametrize("reading", ["to", "by", "over_call"])
def test_parsing_recovers_a_river_strategy_and_its_exploitability(spots, reading):
    s = spots["r24"]  # a raise and a reraise, so the readings differ
    strategy = solve_river(river_spot(s), time_budget_ms=2000, max_iterations=40)
    probs = strategy.probs
    combos = {p: [c[0] + c[1] for c in river_spot(s).combos(i)] for i, p in enumerate(PLAYER_NAMES)}
    dump = fake_dump(s, lambda node, c: list(probs[node.key][combos[node.actor].index(c)]), reading,
                     shuffle=True)
    parsed = ts.parse_dump(json.loads(json.dumps(dump)), s)
    assert parsed.differences == [] and parsed.reading == reading
    assert set(parsed.nodes) == set(decision_nodes(s))
    rebuilt, filled = river_strategy(s, parsed.nodes)
    assert filled == 0
    for key in probs:
        assert np.allclose(rebuilt.probs[key], probs[key], atol=1e-6)
    expl, _ = river_exploitability(s, parsed.nodes)
    assert expl == pytest.approx(exploitability(strategy).pot_share, abs=1e-6)


def test_parsing_a_turn_spot_reads_every_river_card(spots):
    s = spots["t10"]  # a turn raise size
    dump = fake_dump(s, lambda node, c: [1.0 / len(node.actions)] * len(node.actions), "to", children_key="children")
    parsed = ts.parse_dump(dump, s)
    assert parsed.differences == []
    assert set(parsed.nodes) == set(decision_nodes(s))
    river_node = parsed.nodes["x b50 c 9c"]
    assert river_node["actor"] == "oop" and river_node["actions"] == ["x", "b100", "b450"]
    assert not any("9c" in combo for combo in river_node["strategy"])


def test_a_dump_of_a_different_tree_is_reported(spots):
    s, other = spots["r04"], dict(spots["r04"], sizes=spots["r05"]["sizes"], stacks=spots["r05"]["stacks"])
    dump = fake_dump(other, lambda node, c: [1.0 / len(node.actions)] * len(node.actions))
    parsed = ts.parse_dump(dump, s)
    assert parsed.differences


def test_the_log_is_read():
    log = ("Iter: 0\nplayer 0 exploitability 40.1\nplayer 1 exploitability 22.0\nTotal exploitability 62.05 precent\n"
           "Iter: 10\nTotal exploitability 1.5 precent\nIter: 20\nTotal exploitability 0.29 precent\n")
    assert ts.parse_log(log) == [(0, 62.05), (10, 1.5), (20, 0.29)]
    assert ts.parse_log("Iteration 30: exploitability 0.2\n") == [(30, 0.2)]


def test_the_config_has_the_spot(spots):
    text = ts.config_text(spots["r05"], "/tmp/out.json", threads=4)
    lines = text.splitlines()
    assert lines[:3] == ["set_pot 100", "set_effective_stack 300", "set_board Ks,7d,2c,4h,9s"]
    assert "set_bet_sizes ip,river,bet,33,100" in lines and "set_bet_sizes ip,river,raise,50" in lines
    assert "set_bet_sizes oop,river,donk,50" in lines and "set_bet_sizes oop,river,allin" in lines
    assert "set_accuracy 0.3" in lines and "set_use_isomorphism 0" in lines and "set_dump_rounds 1" in lines
    assert lines.index("build_tree") < lines.index("start_solve") < lines.index("dump_result /tmp/out.json")
    turn = ts.config_text(spots["t03"], "x.json").splitlines()
    assert "set_bet_sizes oop,turn,bet,33" in turn and "set_bet_sizes oop,river,bet,50,100" in turn
    assert "set_dump_rounds 2" in turn


# --------------------------------------------------------------- the results
def test_results_round_trip_and_know_their_spot(tmp_path, spots):
    s = spots["r04"]
    nodes = nodes_from_river_strategy(solve_river(river_spot(s), 500))
    header = cli.make_header(s, spot_hash(s), {"name": "test"}, len(nodes))
    path = write_result(str(tmp_path), header, list(nodes.values()))
    assert path.endswith(".jsonl")
    h, got = read_result(path)
    validate_result(h, got, s, spot_hash(s), decision_nodes(s))
    small = write_result(str(tmp_path), header, list(nodes.values()), gzip_over=10)
    assert small.endswith(".jsonl.gz") and not os.path.exists(path)
    assert read_result(small)[1] == got
    changed = dict(s, pot=99)
    with pytest.raises(ValueError, match="changed"):
        validate_result(h, got, changed, spot_hash(changed), decision_nodes(s))


def test_solve_end_to_end_with_a_stand_in_solver(tmp_path, spots):
    """A stand-in for console_solver: reads -i <config>, writes a prepared dump where the
    config's dump_result says, and prints a log like TexasSolver's."""
    s = spots["r01"]
    strategy = solve_river(river_spot(s), time_budget_ms=5000, target_exploitability=0.001)
    combos = {p: [c[0] + c[1] for c in river_spot(s).combos(i)] for i, p in enumerate(PLAYER_NAMES)}
    dump = fake_dump(s, lambda node, c: list(strategy.probs[node.key][combos[node.actor].index(c)]))
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps(dump))
    fake = tmp_path / "console_solver"
    fake.write_text(f"""#!{sys.executable}
import shutil, sys
config = open(sys.argv[sys.argv.index("-i") + 1]).read()
out = [l.split(" ", 1)[1] for l in config.splitlines() if l.startswith("dump_result ")][0]
shutil.copy({str(prepared)!r}, out)
print("Iter: 0\\nTotal exploitability 30.0 precent\\nIter: 10\\nTotal exploitability 0.08 precent")
""")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    readme = tmp_path / "README.md"
    readme.write_text(f"x\n{cli.TABLE_START}\nold\n{cli.TABLE_END}\ny\n")
    results = tmp_path / "results"
    cli.README = str(readme)
    try:
        code = cli.main(["--results-dir", str(results), "solve", "r01", "--solver", str(fake),
                         "--workdir", str(tmp_path / "work")])
    finally:
        cli.README = os.path.join(cli.ROOT, "data", "answer_keys", "README.md")
    assert code == 0
    header, nodes = read_result(str(results / "r01.jsonl"))
    assert header["solver"]["iterations"] == 10 and header["solver"]["exploitability_pot"] == pytest.approx(0.0008)
    assert header["solver"]["converged"] and header["solver"]["reading"] == "to"
    assert header["checks"]["expected_failures"] == []
    assert header["checks"]["exploitability_pot"] < 0.002
    index = json.loads((results / "index.json").read_text())
    assert index["spots"]["r01"]["status"] == "ok"
    assert "| r01 | river | ok |" in readme.read_text() and "old" not in readme.read_text()
    assert not (tmp_path / "work" / "r01.json").exists()  # the raw dump isn't kept
    assert cli.main(["--results-dir", str(results), "validate"]) == 0
