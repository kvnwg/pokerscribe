"""Dump OpenSpiel's vanilla CFR numbers on Leduc hold'em to a JSON file.

The Rust CFR core (engine/crates/cfr) checks its own vanilla CFR against these
numbers in engine/crates/cfr/tests/leduc_openspiel.rs.

Setup (any Python OpenSpiel has wheels for):
    python3 -m venv /tmp/osenv
    /tmp/osenv/bin/pip install open_spiel
    /tmp/osenv/bin/python tools/reference/openspiel_leduc.py

What it records:
- OpenSpiel's Python CFRSolver (open_spiel.python.algorithms.cfr, vanilla:
  alternating updates, no linear averaging, no regret matching plus): NashConv
  and exploitability (NashConv / 2) of the average policy after iterations
  1, 10, 100 and 1000, plus the value of that average policy for player 0.
- The same from OpenSpiel's C++ CFRSolver, as a cross-check.
- The equilibrium game value for player 0, from a long C++ CFR+ run, with the
  exploitability of the policy it came from.
- The size of the game (information states per player), so a rules mismatch
  shows up before any solver numbers are compared.
"""

import argparse
import importlib.metadata
import json
import os
import time

import pyspiel
from open_spiel.python import policy as policy_lib
from open_spiel.python.algorithms import cfr, exploitability
from open_spiel.python.algorithms import expected_game_score

CHECKPOINTS = [1, 10, 100, 1000]
EQUILIBRIUM_ITERATIONS = 20000

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "engine", "crates", "cfr", "tests", "data", "openspiel_leduc.json")


def count_info_states(game):
    per_player = [set() for _ in range(game.num_players())]
    histories = 0
    terminals = 0

    def walk(state):
        nonlocal histories, terminals
        histories += 1
        if state.is_terminal():
            terminals += 1
            return
        if state.is_chance_node():
            for action, _ in state.chance_outcomes():
                walk(state.child(action))
            return
        player = state.current_player()
        per_player[player].add(state.information_state_string(player))
        for action in state.legal_actions():
            walk(state.child(action))

    walk(game.new_initial_state())
    return [len(s) for s in per_player], histories, terminals


def python_cfr(game):
    solver = cfr.CFRSolver(game)
    rows = []
    start = time.time()
    for it in range(1, CHECKPOINTS[-1] + 1):
        solver.evaluate_and_update_policy()
        if it in CHECKPOINTS:
            avg = solver.average_policy()
            nash_conv = exploitability.nash_conv(game, avg)
            value = expected_game_score.policy_value(
                game.new_initial_state(), [avg] * game.num_players())[0]
            rows.append({
                "iteration": it,
                "nash_conv": nash_conv,
                "exploitability": nash_conv / game.num_players(),
                "value_player0": value,
            })
            print(f"python CFR it {it}: exploitability {nash_conv / 2:.9f} "
                  f"value {value:.9f} ({time.time() - start:.0f} s)", flush=True)
    return rows


def cpp_cfr(game):
    solver = pyspiel.CFRSolver(game)
    rows = []
    for it in range(1, CHECKPOINTS[-1] + 1):
        solver.evaluate_and_update_policy()
        if it in CHECKPOINTS:
            avg = solver.average_policy()
            nash_conv = pyspiel.nash_conv(game, avg)
            value = pyspiel.expected_returns(
                game.new_initial_state(), avg, -1, True)[0]
            rows.append({
                "iteration": it,
                "nash_conv": nash_conv,
                "exploitability": nash_conv / game.num_players(),
                "value_player0": value,
            })
            print(f"C++ CFR it {it}: exploitability {nash_conv / 2:.9f}", flush=True)
    return rows


def equilibrium_value(game):
    solver = pyspiel.CFRPlusSolver(game)
    for _ in range(EQUILIBRIUM_ITERATIONS):
        solver.evaluate_and_update_policy()
    avg = solver.average_policy()
    value = pyspiel.expected_returns(game.new_initial_state(), avg, -1, True)[0]
    expl = pyspiel.exploitability(game, avg)
    print(f"CFR+ {EQUILIBRIUM_ITERATIONS} its: value {value:.9f} "
          f"exploitability {expl:.2e}", flush=True)
    return {
        "solver": "OpenSpiel C++ CFRPlusSolver",
        "iterations": EQUILIBRIUM_ITERATIONS,
        "value_player0": value,
        "exploitability": expl,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    game = pyspiel.load_game("leduc_poker")
    info_states, histories, terminals = count_info_states(game)
    uniform = policy_lib.UniformRandomPolicy(game)
    uniform_nash_conv = exploitability.nash_conv(game, uniform)

    result = {
        "game": "leduc_poker",
        "open_spiel_version": importlib.metadata.version("open_spiel"),
        "info_states_per_player": info_states,
        "histories": histories,
        "terminal_histories": terminals,
        "uniform_policy": {
            "nash_conv": uniform_nash_conv,
            "exploitability": uniform_nash_conv / game.num_players(),
        },
        "exploitability_definition": "NashConv / num_players, as in "
                                     "open_spiel.python.algorithms.exploitability",
        "vanilla_cfr_python": python_cfr(game),
        "vanilla_cfr_cpp": cpp_cfr(game),
        "equilibrium": equilibrium_value(game),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print("wrote", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
