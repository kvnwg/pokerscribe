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
    assert all(s["max_raises"] == ts.TEXASSOLVER_MAX_RAISES == 3 for s in spots.values())


def test_every_spot_gives_texassolver_whole_classes(spots):
    for s in spots.values():
        for p in ("oop", "ip"):
            classes = class_weights(s["ranges"][p], s["board"])
            # the class text TexasSolver gets expands back to exactly the spot's combos
            assert expand_range_text(ts.range_text(s, p), s["board"]) == s["ranges"][p]
            assert classes


def test_texassolver_can_only_take_three_raises(spots):
    with pytest.raises(ValueError, match="3 raises"):
        ts.config_text(dict(spots["r04"], max_raises=1), "x.json")


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
    with pytest.raises(SpotError, match="not under the stack"):  # SPR 0.5: a 0.75 first bet is all in
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
    s = spots["r24"]  # three raises, so the readings differ
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
    dump = fake_dump(s, lambda node, c: [1.0 / len(node.actions)] * len(node.actions), "by", children_key="children")
    deal = dump["children"]["CHECK"]["children"]["CHECK"]["dealcards"]
    for card in s["board"]:  # TexasSolver lists the board's cards too
        deal[card] = deal["9c"]
    parsed = ts.parse_dump(dump, s)
    assert parsed.differences == []
    assert set(parsed.nodes) == set(decision_nodes(s))
    river_node = parsed.nodes["x b50 c 9c"]
    assert river_node["actor"] == "oop" and river_node["actions"] == ["x", "b100", "b450"]
    assert parsed.nodes["b50 r150 r350 c 9c"]["actions"] == ["x", "b150"]  # river bets capped to the all in
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
    assert "set_allin_threshold 1000" in lines and not any("raise_limit" in line for line in lines)
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


# ------------------------------------------------------ the committed answer keys
def _saved(spot_id):
    from tools.answer_keys.result import result_path
    from tools.answer_keys.spots import RESULTS_DIR
    return read_result(result_path(RESULTS_DIR, spot_id))


def test_every_saved_answer_key_is_valid_and_its_values_add_up(spots):
    for s in spots.values():
        header, nodes = _saved(s["id"])
        validate_result(header, nodes, s, spot_hash(s), decision_nodes(s))
        assert header["solver"]["converged"] and header["solver"]["exploitability_pot"] <= 0.003
        assert check_expected(s, nodes) == []
        if s["street"] != "river":
            continue
        c = header["checks"]
        assert c["values"]["oop"] + c["values"]["ip"] == pytest.approx(s["pot"], abs=1e-4)
        lo, hi = c["oop_value_bounds"]
        assert lo - 1e-6 <= c["values"]["oop"] <= hi + 1e-6
        assert hi - lo == pytest.approx(2 * c["exploitability_pot"] * s["pot"], abs=1e-4)
    assert _saved("r03")[0]["checks"]["values"]["oop"] == pytest.approx(50, abs=1e-6)  # the board plays


@pytest.mark.parametrize("spot_id", ["r04", "r13", "r24", "r28"])
def test_app_solver_agrees_with_texassolver(spots, spot_id):
    """The true value lies inside both answers' bounds, so the two intervals must meet."""
    s = spots[spot_id]
    e = exploitability(solve_river(river_spot(s), time_budget_ms=30000, target_exploitability=0.0005))
    lo, hi = _saved(spot_id)[0]["checks"]["oop_value_bounds"]
    assert max(lo, s["pot"] - e.best_response[1]) <= min(hi, e.best_response[0]) + 1e-6
    assert abs(e.value[0] - _saved(spot_id)[0]["checks"]["values"]["oop"]) < 0.005 * s["pot"]  # the Phase 4 bar


# ============================================================ Phase 4: the comparison harness
# values.py (EV, reach, frequencies, best response), compare.py, the Python reference answers
# (python_solver.py, data/answer_keys/python_solver/) and runner.py (docs/research/PHASE4.md).
import gzip  # noqa: E402
import subprocess  # noqa: E402

from app.solver.labels import SOLVER_NAME  # noqa: E402
from app.solver.ranking import hand_value  # noqa: E402
from tools.answer_keys import compare as cmp  # noqa: E402
from tools.answer_keys import python_solver, runner, standin_solver  # noqa: E402
from tools.answer_keys.result import make_header, node_record  # noqa: E402
from tools.answer_keys.spots import RESULTS_DIR as TEXASSOLVER_DIR  # noqa: E402
from tools.answer_keys.values import RIVER_CARDS, TEXASSOLVER_RIVER_CARDS, Game  # noqa: E402

PYTHON_DIR = python_solver.RESULTS_DIR
STANDIN = standin_solver.__file__


def _key(spots, spot_id):
    """TexasSolver's saved answer to a spot: (header, nodes)."""
    return cmp.load_valid(TEXASSOLVER_DIR, spots[spot_id])


def _rule_nodes(spot, rule):
    """Node records from rule(node, combo) -> probabilities in the node's action order.
    Combos that hold a node's river card are left out, as in a real result."""
    out = {}
    for key, node in decision_nodes(spot).items():
        dead = set(key.split()) if spot["street"] == "turn" else set()
        rows = {c: dict(zip(node.actions, rule(node, c))) for c in spot["ranges"][node.actor]
                if c[:2] not in dead and c[2:] not in dead}
        out[key] = node_record(key, node.actor, node.actions, rows)
    return out


def _uniform(node, combo):
    return [1.0 / len(node.actions)] * len(node.actions)


def _save(folder, spot, nodes, **solver):
    header = make_header(spot, spot_hash(spot), dict({"name": "test"}, **solver), len(nodes))
    return write_result(str(folder), header, [nodes[k] for k in decision_nodes(spot)])


# ------------------------------------------------------------------- values.py
@pytest.mark.parametrize("spot_id", ["r05", "r21", "r24"])
def test_river_values_are_app_solvers(spots, spot_id):
    s = spots[spot_id]
    _, nodes = _key(spots, spot_id)
    game = Game(s)
    ours = game.evaluate(nodes)
    theirs = exploitability(river_strategy(s, nodes)[0])
    assert ours.value == pytest.approx(theirs.value, abs=1e-9)
    assert sum(ours.value) == pytest.approx(s["pot"])
    assert game.exploitability(nodes)[0] == pytest.approx(theirs.pot_share, abs=1e-12)
    assert game.exploitability(nodes)[0] == pytest.approx(river_exploitability(s, nodes)[0], abs=1e-12)
    assert ours.reach[""] == pytest.approx(1.0) and ours.line_reach == ours.reach and ours.filled_rows == 0
    for key, node in game.nodes.items():
        if ours.freq[key] is not None:
            assert ours.freq[key].sum() == pytest.approx(1.0)
        # what goes into a node comes out of it: the reach of its children adds up to its own
        kids = [f"{key} {a}".strip() for a in node.actions]
        if all(k in game.nodes for k in kids):
            assert sum(ours.reach[k] for k in kids) == pytest.approx(ours.reach[key])


TINY_TURN = {
    "format": "pokerscribe-spot", "version": 1, "id": "tiny", "street": "turn",
    "board": ["Ks", "7d", "2c", "4h"], "pot": 100, "stacks": [150, 150], "max_raises": 1,
    "sizes": {"oop": {"bets": [0.5], "raises": [0.5], "allin": True},
              "ip": {"bets": [0.5], "raises": [0.5], "allin": True}},
    "river_sizes": {"oop": {"bets": [0.5], "raises": [], "allin": True},
                    "ip": {"bets": [0.5], "raises": [], "allin": True}},
    # the ranges share cards (Kh), and 9s8s and 6s5s make straights and flushes on some rivers
    "ranges": {"oop": {"KhKd": 1.0, "QsQh": 0.5, "9s8s": 1.0, "AsKh": 0.75},
               "ip": {"AhKc": 1.0, "7s7h": 0.5, "6s5s": 1.0, "KhQh": 1.0}},
}


def _deal_by_deal(spot, nodes):
    """EV, reach and action frequencies by playing every deal out one at a time: each pair
    of combos that share no card, with each river card neither holds. Slow and plain, with
    its own showdowns (ranking.hand_value) and its own walk of the tree."""
    tree = decision_nodes(spot)
    pot, stack, board = spot["pot"], min(spot["stacks"]), spot["board"]
    reach = {k: 0.0 for k in tree}
    taken = {k: {a: 0.0 for a in n.actions} for k, n in tree.items()}
    total = value = 0.0
    for oop, w_oop in spot["ranges"]["oop"].items():
        for ip, w_ip in spot["ranges"]["ip"].items():
            held = [oop[:2], oop[2:], ip[:2], ip[2:]]
            if len(set(held)) < 4:
                continue
            rivers = [c for c in deck_left(board) if c not in held]
            assert len(rivers) == RIVER_CARDS
            total += w_oop * w_ip
            for card in rivers:
                weight = w_oop * w_ip / len(rivers)
                a, b = hand_value(board + [card, *held[:2]]), hand_value(board + [card, *held[2:]])

                def play(key, before, prob):
                    node = tree[key]
                    reach[key] += weight * prob
                    out = 0.0
                    row = nodes[key]["strategy"][oop if node.actor == "oop" else ip]
                    for action, p in row.items():
                        p /= sum(row.values())  # saved rows are rounded to 6 places
                        taken[key][action] += weight * prob * p
                        child = f"{key} {action}".strip()
                        matched = max(node.put_in)
                        if child in tree:
                            v = play(child, before, prob * p)
                        elif action == "f":
                            v = -(before + node.put_in[0]) if node.actor == "oop" else pot + before + node.put_in[1]
                        elif node.street == "turn" and matched < stack:
                            v = play(f"{child} {card}", matched, prob * p)
                        else:
                            put = before + matched
                            v = pot + put if a > b else (-put if a < b else pot / 2)
                        out += p * v
                    return out

                value += weight * play("", 0.0, 1.0)
    return value / total, {k: v / total for k, v in reach.items()}, taken


def test_turn_values_match_dealing_every_card_by_hand():
    validate_spot(TINY_TURN)
    rng = np.random.default_rng(7)
    nodes = _rule_nodes(TINY_TURN, lambda node, combo: rng.dirichlet(np.ones(len(node.actions))))
    game = Game(TINY_TURN)
    ours = game.evaluate(nodes)
    value, reach, taken = _deal_by_deal(TINY_TURN, nodes)
    assert ours.value[0] == pytest.approx(value, abs=1e-9) and sum(ours.value) == pytest.approx(100)
    assert ours.filled_rows == 0  # combos that hold the river card aren't missing rows
    assert sum(game.card_share[c] for c in game.cards) == pytest.approx(1.0)
    assert any(" c " in k for k in reach) and any(k.startswith("x x ") for k in reach)
    for key, node in game.nodes.items():
        assert ours.reach[key] == pytest.approx(reach[key], abs=1e-12)
        if reach[key] > 0:
            assert ours.freq[key] == pytest.approx([taken[key][a] / sum(taken[key].values()) for a in node.actions])
        card = game.river_card(node)
        assert (card is None) == (node.street == "turn")
        assert ours.line_reach[key] == pytest.approx(reach[key] / game.card_share[card])
    # a best response can't do worse than following the answer, for either player
    sigma, _ = game.strategy_arrays(nodes)
    assert game.best_response(sigma, 0) >= ours.value[0] and game.best_response(sigma, 1) >= ours.value[1]
    assert game.exploitability(nodes)[0] > 0.01  # random play is far from an equilibrium


def test_texassolver_weighs_each_river_card_by_one_in_46(spots):
    """The finding in docs/research/PHASE4.md: TexasSolver's own exploitability of its turn
    answers is reproduced only when each river card weighs 1/46. By the exact rule (1/44)
    the same answers are further from an equilibrium than it reports."""
    s = spots["t05"]
    header, nodes = _key(spots, "t05")
    reported = header["solver"]["exploitability_pot"]
    assert (TEXASSOLVER_RIVER_CARDS, RIVER_CARDS) == (46, 44)
    assert Game(s, TEXASSOLVER_RIVER_CARDS).exploitability(nodes)[0] == pytest.approx(reported, abs=5e-7)
    exact = Game(s).exploitability(nodes)[0]
    assert reported == pytest.approx(0.0022, abs=1e-4) and exact == pytest.approx(0.0055, abs=1e-4)
    by_its_rule = Game(s, TEXASSOLVER_RIVER_CARDS).evaluate(nodes)
    assert sum(by_its_rule.value) == pytest.approx(s["pot"])  # still adds up to the pot


# -------------------------------------------- the Python reference answers
def test_the_python_reference_answers_every_river_spot(spots):
    rivers = [s for s in spots.values() if s["street"] == "river"]
    names = sorted(n for n in os.listdir(PYTHON_DIR) if n != "index.json")
    assert names == [s["id"] + ".jsonl" for s in rivers]  # 30 river spots, no turn spots
    target = python_solver.REFERENCE_TARGET_PCT / 100
    for s in rivers:
        header, nodes = cmp.load_valid(PYTHON_DIR, s)  # the same spot (sha256), the same tree, rows add up
        assert header["solver"]["name"] == SOLVER_NAME and header["solver"]["converged"]
        assert header["solver"]["settings"]["target_exploitability_pct"] == python_solver.REFERENCE_TARGET_PCT
        assert header["checks"]["expected_failures"] == [] and header["checks"]["filled_rows"] == 0
        checked = river_exploitability(s, nodes)[0]
        assert checked == pytest.approx(header["checks"]["exploitability_pot"], abs=1e-7)
        assert checked <= 1.05 * target  # the saved rows are rounded to 6 places
    index = json.loads(open(os.path.join(PYTHON_DIR, "index.json")).read())
    assert sorted(index["spots"]) == [s["id"] for s in rivers]
    assert all(e["status"] == "ok" for e in index["spots"].values())


def test_the_python_reference_passes_the_phase4_gates_against_texassolver(spots):
    rows = cmp.compare_dirs(PYTHON_DIR, TEXASSOLVER_DIR, list(spots.values()))
    done = [r for r in rows if r.compared]
    assert [r.spot_id for r in done] == [k for k, s in spots.items() if s["street"] == "river"]
    assert all(r.passed for r in done), [(r.spot_id, r.problems) for r in done if not r.passed]
    for r in done:
        assert max(abs(d) for d in r.ev_diff) <= cmp.GATE_EV_PCT
        assert r.ev_diff[0] == pytest.approx(-r.ev_diff[1], abs=1e-9)  # one player's gain is the other's loss
        assert r.exploitability < 0.011 and r.exploitability_source == "checked"
        assert r.reported == pytest.approx(r.exploitability, abs=1e-3)
        assert (r.expected == []) == ("trivial" in spots[r.spot_id]["tags"])
    summary = cmp.summarize(rows, "texassolver", PYTHON_DIR)
    assert summary.passed and summary.n_compared == 30 and summary.expected_spots == 3
    assert summary.worst_ev <= cmp.GATE_EV_PCT and summary.worst_exploitability < 0.011
    assert any("No result, not checked: t01" in line for line in summary.lines)
    assert summary.lines[-3].startswith("Phase 4 gates on 30 of 40 spots: PASS")
    text = cmp.format_table(rows)
    assert text.splitlines()[0].split() == ["Spot", "Street", "EV", "oop", "dEV", "oop", "dEV", "ip", "Exploit.",
                                            "Reported", "Expected", "Freq", "mean", "Freq", "max", "Solve", "ms",
                                            "Iter.", "Gates"]
    assert len(text.splitlines()) == 41 and text.splitlines()[-1].split()[-2:] == ["no", "result"]
    row = cmp.markdown_row("python_solver", "texassolver", summary)
    assert row.count("|") == cmp.MARKDOWN_ROW_HEADER.splitlines()[0].count("|") and row.endswith("| PASS |")


# ------------------------------------------------------------------ compare.py
def test_an_answer_compared_with_itself_differs_by_nothing(spots):
    for spot_id in ("r05", "t05"):
        result = _key(spots, spot_id)
        row = cmp.compare_spot(spots[spot_id], result, result)
        assert row.ev_diff == (0.0, 0.0) and row.freq_mean == 0.0 and row.freq_max == 0.0
        assert row.solver_ms > 5000 and row.iterations == result[0]["solver"]["iterations"]  # TexasSolver's 5 s


def test_turn_exploitability_is_checked_unless_asked_as_reported(spots):
    s, result = spots["t05"], _key(spots, "t05")
    checked = cmp.compare_spot(s, result, result)
    assert checked.exploitability == pytest.approx(0.552, abs=0.001) and checked.exploitability_source == "checked"
    assert checked.reported == pytest.approx(0.2205, abs=0.0001)
    assert not checked.passed and "not under 0.5%" in checked.problems[0]
    assert any("the solver reports 0.221%, our check finds 0.552%" in n for n in checked.notes)
    reported = cmp.compare_spot(s, result, result, turn_exploitability="reported")
    assert reported.exploitability == reported.reported and reported.exploitability_source == "reported"
    assert reported.passed
    header = dict(result[0], solver={"name": "silent"})  # a solver that reports nothing
    silent = cmp.compare_spot(s, (header, result[1]), result, turn_exploitability="reported")
    assert silent.exploitability is None and silent.problems == ["no exploitability in the result"]
    with pytest.raises(ValueError):
        cmp.compare_dirs(TEXASSOLVER_DIR, None, [s], turn_exploitability="guessed")


def test_frequency_differences_are_weighted_by_reach(spots):
    s = spots["r04"]  # root: x or b50 or b150; after x, IP: x, b75, b150
    first = lambda node, combo: [1.0] + [0.0] * (len(node.actions) - 1)  # noqa: E731 (always check, always fold)

    def bets_30(node, combo):
        return [0.7, 0.3, 0.0] if node.key == "" else first(node, combo)

    def differs_where_nobody_goes(node, combo):
        return _uniform(node, combo) if node.key == "x b75" else first(node, combo)

    game = Game(s)
    a, b, c = (game.evaluate(_rule_nodes(s, rule)) for rule in (first, bets_30, differs_where_nobody_goes))
    assert a.reach["x"] == pytest.approx(1.0) and b.reach["x"] == pytest.approx(0.7)
    assert b.reach["b50"] == pytest.approx(0.3)
    assert a.freq["b50"] is None and a.reach["b50"] == 0.0
    mean, largest, node, detail = cmp.frequency_difference(game, b, a)
    # the root differs by 30 points with reach 1; "x" is the same in both with reach 0.7;
    # "b50" is never reached by one of them, so it doesn't count
    assert mean == pytest.approx(30.0 / 1.7) and largest == pytest.approx(30.0) and node == ""
    assert detail == "oop at '': x 70.0/100.0, b50 30.0/0.0, b150 0.0/0.0"
    assert cmp.frequency_difference(game, c, a) == (pytest.approx(0.0), 0.0, None, "")
    # a node under the reach threshold counts in the mean and not in the max
    def rarely(node, combo):
        if node.key == "":
            return [0.96, 0.04, 0.0]
        return [0.0, 1.0] + [0.0] * (len(node.actions) - 2) if node.key == "b50" else first(node, combo)

    d = game.evaluate(_rule_nodes(s, rarely))
    e = game.evaluate(_rule_nodes(s, lambda node, combo: [0.96, 0.04, 0.0] if node.key == "" else first(node, combo)))
    mean, largest, node, _ = cmp.frequency_difference(game, d, e)
    assert d.reach["b50"] == pytest.approx(0.04) and largest == 0.0 and node is None
    assert mean == pytest.approx(0.04 * 100.0 / (1 + 0.96 + 0.04))
    assert cmp.frequency_difference(game, d, e, min_reach=0.01)[1:3] == (pytest.approx(100.0), "b50")


def test_compare_fails_bad_missing_and_invalid_results(tmp_path, spots, capsys):
    folder = tmp_path / "bad"
    _save(folder, spots["r04"], _rule_nodes(spots["r04"], _uniform), exploitability_pot=0.001, elapsed_ms=12.5)
    _save(folder, spots["r01"], _rule_nodes(spots["r01"], _uniform))
    header, nodes = _key(spots, "r05")
    write_result(str(folder), dict(header, spot_sha256="0" * 64), [nodes[k] for k in decision_nodes(spots["r05"])])
    four = [spots[i] for i in ("r01", "r04", "r05", "r06")]
    rows = {r.spot_id: r for r in cmp.compare_dirs(str(folder), TEXASSOLVER_DIR, four)}
    assert rows["r06"].status == "missing" and not rows["r06"].compared
    assert rows["r05"].status == "invalid" and "changed since it was solved" in rows["r05"].problems[0]
    bad = rows["r04"]  # even play: far from an equilibrium, whatever the solver says of itself
    assert bad.status == "ok" and not bad.passed and bad.exploitability > 5 and bad.reported == pytest.approx(0.1)
    assert bad.solver_ms == 12.5 and bad.iterations is None
    assert any("not under 0.5%" in p for p in bad.problems) and any("EV differs by" in p for p in bad.problems)
    assert rows["r01"].expected and any("expected checks fail" in p for p in rows["r01"].problems)
    summary = cmp.summarize(list(rows.values()), "texassolver")
    assert not summary.passed and summary.n_compared == 3 and summary.expected_failed == 1
    text = "\n".join(summary.lines)
    for part in ("EV within 0.5% of the pot of texassolver: FAIL", "Exploitability under 0.5% of the pot: FAIL",
                 "Expected checks of the trivial spots: FAIL", "Invalid results: r05",
                 "Phase 4 gates on 3 of 4 spots: FAIL", "No result, not checked: r06"):
        assert part in text
    # the command line: exit status 1, the table, the reasons, and a Markdown row when asked
    code = cli.main(["compare", str(folder), "r01", "r04", "r05", "r06", "--markdown", "-v"])
    out = capsys.readouterr().out
    assert code == 1 and "bad against texassolver" in out and "| r04 | river |" in out and "INVALID" in out
    assert "r04: EV differs by" in out and "largest frequency difference, oop at" in out
    assert out.rstrip().endswith("| FAIL |")
    assert cli.main(["compare", str(tmp_path / "nowhere")]) == 2
    assert cli.main(["compare", "texassolver", "r04", "r05", "--against", "python_solver"]) == 0  # names of folders
    assert "texassolver against python_solver" in capsys.readouterr().out


# -------------------------------------------------- export-python and the stand-in
def test_export_python_saves_results_and_an_index(tmp_path, spots, capsys):
    out = tmp_path / "py"
    assert cli.main(["export-python", "r01", "r06", "t01", "--out", str(out), "--target", "0.05"]) == 0
    assert sorted(os.listdir(out)) == ["index.json", "r01.jsonl", "r06.jsonl"]  # the turn spot is skipped
    printed = capsys.readouterr().out
    assert "Skipped 1 turn spots" in printed and "holds 2 river RESULTs" in printed
    index = json.loads((out / "index.json").read_text())
    assert index["settings"]["target_exploitability_pct"] == 0.05 and index["timing"]["river"]["spots"] == 2
    for spot_id in ("r01", "r06"):
        header, nodes = cmp.load_valid(str(out), spots[spot_id])
        assert header["solver"]["exploitability_pot"] <= 0.0005 and header["solver"]["iterations"] >= 8
        checked = river_exploitability(spots[spot_id], nodes)[0]
        assert header["checks"]["exploitability_pot"] == pytest.approx(checked, abs=1e-7)
        assert index["spots"][spot_id]["iterations"] == header["solver"]["iterations"]
    # solving one spot again keeps the other in the index; a turn spot alone changes nothing
    assert cli.main(["export-python", "r06", "--out", str(out), "--target", "0.05"]) == 0
    assert cli.main(["export-python", "t01", "--out", str(out)]) == 2
    assert sorted(json.loads((out / "index.json").read_text())["spots"]) == ["r01", "r06"]
    with pytest.raises(SpotError, match="river spots only"):
        python_solver.solve_spot(spots["t01"])


def test_the_stand_in_follows_the_command_line(tmp_path, spots):
    spot_path = os.path.join(SPOTS_DIR, "r06.json")
    out = tmp_path / "r06.result"
    assert standin_solver.main([spot_path, "--out", str(out), "--max-iterations", "16", "--target-exploitability", "0",
                                "--threads", "2"]) == 0
    header, nodes = runner.read_output(str(out))
    validate_result(header, nodes, spots["r06"], spot_hash(spots["r06"]), decision_nodes(spots["r06"]))
    assert header["solver"]["iterations"] == 16 and not header["solver"]["converged"]
    assert header["solver"]["elapsed_s"] > 0 and 0 < header["solver"]["exploitability_pot"] < 0.05
    # without --out the RESULT goes to standard output, as a real process
    done = subprocess.run([sys.executable, STANDIN, spot_path, "--time-ms", "50"], capture_output=True, timeout=120)
    assert done.returncode == 0
    lines = [json.loads(line) for line in done.stdout.decode().splitlines()]
    assert lines[0]["kind"] == "header" and lines[0]["spot_id"] == "r06" and len(lines) == 1 + lines[0]["nodes"]
    assert lines[0]["solver"]["settings"]["time_ms"] == 50
    assert standin_solver.main([os.path.join(SPOTS_DIR, "t01.json")]) == 2  # river spots only


# ------------------------------------------------------------------- runner.py
def test_the_command_line_of_the_contract():
    assert runner.command("/x/subgame-solve", "r01.json", "out.json") == [
        "/x/subgame-solve", "r01.json", "--out", "out.json", "--target-exploitability", "0.5"]
    assert runner.command("/x/subgame-solve", "r01.json", "o", 0.3, 200, 150.0, 4)[4:] == [
        "--target-exploitability", "0.3", "--max-iterations", "200", "--time-ms", "150", "--threads", "4"]
    assert runner.command("fake.py", "r01.json", "o", None)[:2] == [sys.executable, "fake.py"]  # .py: this Python
    assert runner.default_name("/a/b/target/release/subgame-solve") == "subgame-solve"
    assert runner.default_name("tools/answer_keys/standin_solver.py") == "standin_solver"
    assert runner.results_dir_for("rust_solver").endswith(os.path.join("data", "answer_keys", "rust_solver"))
    for name in ("texassolver", "python_solver", "spots", "../x", ".hidden"):
        with pytest.raises(ValueError):
            runner.results_dir_for(name)


def test_run_saves_results_and_times_a_solver(tmp_path, spots, capsys):
    out = tmp_path / "standin"
    code = cli.main(["run", "--solver", STANDIN, "--out", str(out), "--repeat", "2", "r01", "r04"])
    printed = capsys.readouterr().out
    assert code == 0
    assert sorted(os.listdir(out)) == ["index.json", "r01.jsonl", "r04.jsonl"]
    index = json.loads((out / "index.json").read_text())
    river = index["timing"]["river"]
    assert river["spots"] == 2 and river["runs"] == 4 and "turn" not in index["timing"]
    assert 0 < river["solver_ms_p50"] <= river["solver_ms_p95"] < river["wall_ms_p50"]
    assert river["wall_ms_p50"] <= river["wall_ms_p95"] <= river["wall_ms_max"]
    assert index["settings"] == {"target_exploitability_pct": 0.5, "repeat": 2, "max_iterations": None,
                                 "time_ms": None, "threads": None}
    assert index["solver"]["file"] == "standin_solver.py" and len(index["solver"]["binary_sha256"]) == 64
    for spot_id in ("r01", "r04"):
        e = index["spots"][spot_id]
        assert e["status"] == "ok" and len(e["wall_ms"]) == len(e["solver_ms"]) == 2
        assert e["exploitability_pot"] <= 0.005
        header, nodes = cmp.load_valid(str(out), spots[spot_id])
        assert header["solver"]["settings"]["target_exploitability_pct"] == 0.5
        # the "checks" block is ours: app/solver's checker on what the solver wrote
        checked = river_exploitability(spots[spot_id], nodes)[0]
        assert header["checks"]["exploitability_pot"] == pytest.approx(checked, abs=1e-7)
        assert header["checks"]["expected_failures"] == []
    assert "river: wall time p50" in printed and "River p95 under 400 ms (wall time):" in printed
    assert f"Saved 2 RESULTs to {out}" in printed
    # and what it saved passes the gates against the Python reference
    rows = cmp.compare_dirs(str(out), PYTHON_DIR, [spots["r01"], spots["r04"]])
    summary = cmp.summarize(rows, "python_solver", str(out))
    assert summary.passed and summary.wall_ms["river"][2] == 4 and summary.solver_ms["river"][2] == 2
    assert any(line.startswith("Wall time from the last `run`, river: p50") for line in summary.lines)


def test_run_reports_a_solver_that_fails(tmp_path, capsys):
    out = tmp_path / "standin"
    assert cli.main(["run", "--solver", STANDIN, "--out", str(out), "--spots", "turn", "t01"]) == 1
    printed = capsys.readouterr().out
    assert "t01  turn  FAIL  exit status 2" in printed and "river spots only" in printed
    assert "1 of 1 spots failed: t01" in printed and "Saved 0 RESULTs" in printed
    index = json.loads((out / "index.json").read_text())
    assert index["spots"]["t01"]["status"] == "fail" and index["timing"] == {}
    assert os.listdir(out) == ["index.json"]
    assert cli.main(["run", "--solver", str(tmp_path / "missing")]) == 2
    for reserved in (["--name", "python_solver"], ["--out", TEXASSOLVER_DIR]):  # never over the references
        assert cli.main(["run", "--solver", STANDIN, "r01"] + reserved) == 2


def _other_solver(tmp_path, body):
    """An executable that isn't the stand-in: `body` is Python run with `spot` (the spot),
    `nodes` (even play at every node, as records), `header` and `out` (the --out path)."""
    path = tmp_path / "other-solver"
    path.write_text(f"""#!{sys.executable}
import gzip, json, sys
sys.path.insert(0, {cli.ROOT!r})
from tools.answer_keys.result import make_header, node_record
from tools.answer_keys.spots import decision_nodes, load_spot, spot_hash
spot = load_spot(sys.argv[1])
out = sys.argv[sys.argv.index("--out") + 1]
nodes = []
for key, node in decision_nodes(spot).items():
    dead = set(key.split()) if spot["street"] == "turn" else set()
    rows = {{c: {{a: 1.0 / len(node.actions) for a in node.actions}} for c in spot["ranges"][node.actor]
            if c[:2] not in dead and c[2:] not in dead}}
    nodes.append(node_record(key, node.actor, node.actions, rows))
header = make_header(spot, spot_hash(spot), {{"name": "other", "elapsed_ms": 7.5, "iterations": 3,
                                             "exploitability_pot": 0.004}}, len(nodes))
{body}
""")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_run_reads_a_turn_result_in_another_layout(tmp_path, spots):
    """A turn spot from a binary that writes one gzipped JSON document. Even play is far
    from an equilibrium: only taking the solver's word for it lets it through."""
    one_document = 'json.dumps({"header": header, "nodes": nodes}).encode()'
    solver = _other_solver(tmp_path, f'open(out, "wb").write(gzip.compress({one_document}))')
    out = tmp_path / "other"
    index = runner.run_spots(solver, [spots["t05"]], str(out), "other", repeat=1, log=lambda line: None)
    e = index["spots"]["t05"]
    assert e["status"] == "ok" and e["solver_ms"] == [7.5] and e["iterations"] == 3 and e["exploitability_pot"] == 0.004
    assert e["checked_exploitability_pot"] is None  # the header's own check is for river spots (SPOT_FORMAT.md)
    assert e["file"] == "t05.jsonl.gz" and index["timing"]["turn"]["runs"] == 1
    assert index["solver"]["file"] == "other-solver" and runner.timing_lines(index)[0].startswith("turn: wall time p50")
    (row,) = cmp.compare_dirs(str(out), TEXASSOLVER_DIR, [spots["t05"]], turn_exploitability="reported")
    assert row.exploitability == pytest.approx(0.4) and row.solver_ms == 7.5
    assert all("exploitability" not in p for p in row.problems)
    (row,) = cmp.compare_dirs(str(out), TEXASSOLVER_DIR, [spots["t05"]])
    assert row.exploitability > 5 and any("not under 0.5%" in p for p in row.problems)
    assert any("the solver reports 0.400%" in n for n in row.notes)


def test_run_refuses_output_that_is_not_the_spots_result(tmp_path, spots):
    cases = {
        "a different tree": "json.dump([header] + nodes[:-1], open(out, 'w'))",
        "another spot": "json.dump([dict(header, spot_sha256='0' * 64)] + nodes, open(out, 'w'))",
        "rows that don't add up": ("rows = nodes[0]['strategy']\n"
                                   "nodes[0]['strategy'] = {c: {a: 0.9 for a in r} for c, r in rows.items()}\n"
                                   "json.dump([header] + nodes, open(out, 'w'))"),
        "not a number": ("rows = nodes[0]['strategy']\n"
                         "nodes[0]['strategy'] = {c: {a: float('nan') for a in r} for c, r in rows.items()}\n"
                         "json.dump([header] + nodes, open(out, 'w'))"),
        "not json": "open(out, 'w').write('solved!')",
        "nothing": "pass",
        "a crash": "sys.exit('out of memory')",
    }
    wanted = {"a different tree": "nodes differ", "another spot": "changed since it was solved",
              "rows that don't add up": "don't add up to 1", "not a number": "must be numbers",
              "not json": "isn't JSON Lines",
              "nothing": "no file at --out", "a crash": "exit status 1: out of memory"}
    for name, body in cases.items():
        index = runner.run_spots(_other_solver(tmp_path, body), [spots["r01"]], str(tmp_path / "out"), "other",
                                 repeat=2, log=lambda line: None)
        e = index["spots"]["r01"]
        assert e["status"] == "fail" and wanted[name] in e["problems"][0], (name, e["problems"])
        assert e["wall_ms"] == [] and len(e["problems"]) == 1  # not run again after a failure
    assert os.listdir(tmp_path / "out") == ["index.json"]


def test_read_output_takes_json_lines_an_array_or_gzip(tmp_path, spots):
    header, nodes = _key(spots, "r01")
    records = [header] + list(nodes.values())
    layouts = {"lines": "\n".join(json.dumps(r) for r in records).encode(),
               "array": json.dumps(records).encode(),
               "object": json.dumps({"header": header, "nodes": records[1:]}).encode()}
    layouts["gzip"] = gzip.compress(layouts["lines"])
    for name, data in layouts.items():
        path = tmp_path / name
        path.write_bytes(data)
        assert runner.read_output(str(path)) == (header, nodes), name
    (tmp_path / "empty").write_bytes(b"")
    (tmp_path / "headless").write_text(json.dumps(records[1]))
    for name in ("empty", "headless"):
        with pytest.raises(ValueError):
            runner.read_output(str(tmp_path / name))
