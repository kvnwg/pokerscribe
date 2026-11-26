"""Phase 2, the Python river solver as a reference: every table in
docs/research/RIVER_SOLVER.md.

    .venv/bin/python docs/research/runs/phase2_reference.py > docs/research/runs/phase2_reference.log

Nothing here compares strategies for strength, and nothing touches the app or B0. It reads
the reference spots and their saved answers (data/reference_spots/python_solver, made by
python -m tools.reference_spots solve) and measures:

1. The saved answers: iterations, time, how far each is from an equilibrium, its value,
   and the known answers next to what the solver found.
2. How long app/solver takes to get within 0.5%, 0.1% and 0.01% of the pot of an
   equilibrium on each spot (no clock; the median time of three runs).
3. Push-or-fold at 5 to 15 big blinds: time, exploitability, and the shares next to the
   published chart's.
4. The Rust solver (engine/crates/subgame) on the same spots, checked against the saved
   answers, if it is built.
5. app/solver against TexasSolver's 30 river answer keys.

Run it on an idle machine: the times are wall-clock.
"""
from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))

from app.solver import solve_river  # noqa: E402
from app.solver.pushfold import solve_push_fold  # noqa: E402
from app.tests.pushfold_chart import chart_share  # noqa: E402
from tools.answer_keys.spots import load_spots, river_spot  # noqa: E402
from tools.reference_spots import __main__ as cli  # noqa: E402
from tools.reference_spots import build, solve  # noqa: E402

TARGETS = (0.005, 0.001, 0.0001)  # shares of the pot: the Phase 4 gate, the app's early stop, ten times tighter


def reach(rs, target, runs=3):
    got = sorted((solve_river(rs, None, max_iterations=solve.REFERENCE_MAX_ITERATIONS, target_exploitability=target)
                  for _ in range(runs)), key=lambda s: s.elapsed_ms)
    return got[len(got) // 2]


def convergence():
    print("| Spot | Combos (OOP, IP) | Nodes | To 0.5% of the pot: iterations | ms | To 0.1%: iterations | ms "
          "| To 0.01%: iterations | ms | ms an iteration |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    index = cli.load_index()["spots"]
    per_target = {t: [] for t in TARGETS}
    for spot in load_spots(build.SPOTS_DIR):
        rs = river_spot(spot)
        e = index[spot["id"]]
        cells, last = [], None
        for t in TARGETS:
            last = reach(rs, t)
            per_target[t].append(last.elapsed_ms)
            cells.append(f"{last.iterations} | {last.elapsed_ms:.0f}")
        print(f"| {spot['id']} | {e['combos'][0]}, {e['combos'][1]} | {e['nodes']} | " + " | ".join(cells)
              + f" | {last.elapsed_ms / last.iterations:.2f} |", flush=True)
    for t in TARGETS:
        ms = sorted(per_target[t])
        print(f"to {100 * t:g}% of the pot: median {statistics.median(ms):.0f} ms, slowest {ms[-1]:.0f} ms")


def push_fold(runs=5):
    print("| Stack, big blinds | ms | Iterations | Exploitability, big blinds a hand | Jam share | chart | Call share | chart "
          "| Small blind's result, big blinds a hand |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for stack in (5, 8, 10, 12, 15):
        times = []
        for _ in range(runs):
            start = time.perf_counter()
            sol = solve_push_fold(stack)
            times.append(1000 * (time.perf_counter() - start))
        print(f"| {stack} | {statistics.median(times):.0f} | {sol.iterations} | {sol.exploitability:.7f} "
              f"| {100 * sol.jam_share:.1f}% | {100 * chart_share(stack, 'jam'):.1f}% | {100 * sol.call_share:.1f}% "
              f"| {100 * chart_share(stack, 'call'):.1f}% | {sol.value_sb:+.4f} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skip", nargs="*", default=[], choices=["convergence", "pushfold", "rust", "texassolver"])
    args = ap.parse_args()
    print(f"# docs/research/runs/phase2_reference.py, {time.strftime('%d %b %Y')}, {platform.system()} "
          f"{platform.machine()}, {os.cpu_count()} cores, Python {platform.python_version()}\n")
    print("## 1. The saved reference answers (data/reference_spots/python_solver)\n")
    cli.cmd_report(None)
    problems = cli.validate_all()
    print(f"\nvalidate: {len(problems)} problems" + "".join(f"\n  {p}" for p in problems))
    if "convergence" not in args.skip:
        print("\n## 2. Time to a given accuracy (no clock, the early stop is checked at iterations 8, 16, 32, ...)\n")
        convergence()
    if "pushfold" not in args.skip:
        print("\n## 3. Push-or-fold (solve_push_fold, default settings)\n")
        push_fold()
    if "rust" not in args.skip:
        print("\n## 4. The Rust solver on the reference spots\n")
        if not os.path.exists(cli.RUST_BINARY):
            print("not built (cd engine && cargo build --release -p subgame)")
        else:
            limits = dict(binary=cli.RUST_BINARY, max_iterations=100000)
            cli.cmd_rust(argparse.Namespace(target=0.3, max_exploitability=0.5, value=0.5, shares=None, **limits))
            print()
            cli.cmd_rust(argparse.Namespace(target=0.01, max_exploitability=0.02, value=0.05, shares=0.005, **limits))
    if "texassolver" not in args.skip:
        print("\n## 5. app/solver against TexasSolver's 30 river answer keys (data/answer_keys)\n")
        cli.cmd_texassolver(None)


if __name__ == "__main__":
    main()
