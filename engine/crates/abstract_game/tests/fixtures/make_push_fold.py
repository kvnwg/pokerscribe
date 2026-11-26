"""Reference data for the abstract_game crate, from the Python solver in app/solver.

Run from the repository root (needs numpy and treys, as the app does):

    python engine/crates/abstract_game/tests/fixtures/make_push_fold.py

It writes push_fold_10bb.txt next to this file: heads-up push-or-fold at 10 big blinds
solved by app.solver.solve_push_fold, one line per starting hand in chart order. The
Rust test tests/push_fold.rs trains the same game with the cfr crate and compares.

With --strength it prints, as a Rust array, each starting hand's chance of beating a random
hand all in before the flop, from the same exact equity table. That array is
PREFLOP_STRENGTH in src/bucket.rs.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 5)))

from app.solver.pushfold import CLASSES, COMBOS, load_equity, solve_push_fold  # noqa: E402

STACK = 10
SB, BB = 0.5, 1.0
HERE = os.path.dirname(os.path.abspath(__file__))


def strength() -> None:
    equity, pairs = load_equity()
    against_random = (pairs * equity).sum(axis=1) / pairs.sum(axis=1)
    print("// Made by tests/fixtures/make_push_fold.py --strength; chart order, AA first.")
    for row in range(13):
        print("    " + " ".join(f"{x:.5f}," for x in against_random[row * 13:row * 13 + 13]))


def push_fold() -> None:
    sol = solve_push_fold(STACK, sb=SB, bb=BB, max_iterations=200_000, target_exploitability=1e-9)
    equity, pairs = load_equity()
    total = pairs.sum()
    dealt = pairs.sum(axis=1)
    showdown = pairs * STACK * (2 * equity - 1)  # the small blind's result when called, per deal
    # The small blind holding each hand: jamming against the equilibrium caller, less folding.
    jam_value = (BB * (pairs @ (1 - sol.call)) + showdown @ sol.call) / dealt
    jam_margin = jam_value - (-SB)
    # The big blind holding each hand and facing the equilibrium jam: calling less folding.
    faced = pairs.T @ sol.jam
    call_margin = -(showdown.T @ sol.jam) / faced - (-BB)
    path = os.path.join(HERE, f"push_fold_{STACK}bb.txt")
    with open(path, "w") as f:
        f.write(f"# Heads-up push-or-fold, {STACK} big blinds each, blinds {SB} and {BB}.\n")
        f.write("# From app.solver.solve_push_fold by tests/fixtures/make_push_fold.py.\n")
        f.write(f"# exploitability {sol.exploitability:.3e} big blinds a hand after {sol.iterations} iterations\n")
        f.write(f"# value {sol.value_sb:.9f}\n")
        f.write(f"# jam_share {sol.jam_share:.9f}\n")
        f.write(f"# call_share {sol.call_share:.9f}\n")
        f.write("# Columns: hand; how often the small blind jams; how often the big blind calls;\n")
        f.write("# jam margin: big blinds the small blind gains by jamming over folding with the hand;\n")
        f.write("# call margin: big blinds the big blind gains by calling over folding, facing a jam;\n")
        f.write("# jam weight: the chance the small blind holds the hand;\n")
        f.write("# call weight: the chance the big blind holds the hand and faces a jam.\n")
        for i, hand in enumerate(CLASSES):
            f.write(f"{hand} {sol.jam[i]:.9f} {sol.call[i]:.9f} {jam_margin[i]:.9f} {call_margin[i]:.9f} "
                    f"{COMBOS[i] / 1326:.9f} {faced[i] / total:.9f}\n")
    print(f"wrote {path}: jam {sol.jam_share:.4f}, call {sol.call_share:.4f}, value {sol.value_sb:.6f}, "
          f"exploitability {sol.exploitability:.2e}")


if __name__ == "__main__":
    strength() if "--strength" in sys.argv[1:] else push_fold()
