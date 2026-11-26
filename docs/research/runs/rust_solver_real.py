"""The Rust backend against the real program, on the advice's own river spots.

    .venv/bin/python docs/research/runs/rust_solver_real.py [--hands 6000] [--seed 77]
                                                             [--table mixed] [--spots 400]

Needs subgame-solve built (cd engine && cargo build --release --bin subgame-solve).

Nothing here compares a strategy with B0. As in phase2_budget.py, the simulator only deals
hands (the app's seat plays the frozen baseline with the switches off); every heads-up
river decision of the app becomes a spot. Then, by the clock, as the app asks:

1. Each spot solved by the Python solver and by subgame-solve through
   app/solver/rust_backend.py, with the advice's settings (solve.decision_settings). Who
   answered, the time of the call and where it went, how far each answer is from an
   equilibrium by the Python checker, whether the program's own number is the checker's,
   and whether the advice would act the same on both answers (bridge.recommend), with
   both mixes for the hero's hand where it would not.
2. The whole decision through advise(), switches on in this process only: its time with
   the Python solver and with the Rust program, and how often the instruction is the same.
"""
from __future__ import annotations

import argparse
import copy
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, HERE)

import app.solver as solver  # noqa: E402
from app.poker import advice  # noqa: E402
from app.solver import bridge, rust_backend  # noqa: E402
from app.solver.exploitability import exploitability  # noqa: E402
from app.solver.strategy import describe_mix  # noqa: E402
from app.solver.timing import QUALITY_BAR, TARGET_MS, percentile  # noqa: E402
from phase2_budget import decisions_of  # noqa: E402
from phase2_ranges import collect  # noqa: E402
from tools import simulate as sim  # noqa: E402


def stats(values, unit="ms", digits=0) -> str:
    return (f"p50 {percentile(values, 50):.{digits}f}, p95 {percentile(values, 95):.{digits}f}, "
            f"max {max(values):.{digits}f} {unit}")


def spot_by_spot(decisions, binary: str) -> None:
    python_ms, python_far, python_iterations = [], [], []
    calls, solving, overhead, rust_far, rust_iterations, own_gap = [], [], [], [], [], []
    unsaid = failed = late = both = same = 0
    apart = []
    for d, bb, _ in decisions:
        how = solver.decision_settings(d.spot, bb)
        by_python = solver.solve_river(d.spot, **how)
        python_ms.append(by_python.elapsed_ms)
        python_far.append(100 * exploitability(by_python).pot_share)
        python_iterations.append(by_python.iterations)
        budget = how["time_budget_ms"]
        try:  # the call rust_backend.solve_river makes, kept apart here to see inside it
            run = rust_backend.run_solver(d.spot, binary, time_ms=budget - rust_backend.OVERHEAD_RESERVE_MS,
                                          target_exploitability=how["target_exploitability"], timeout_ms=budget)
        except rust_backend.UnsupportedSpot:
            unsaid += 1
            continue
        except rust_backend.RustSolverError as e:
            failed += 1
            print(f"  failed: {e}")
            continue
        calls.append(run.total_ms)
        solving.append(run.solver_ms)
        overhead.append(run.overhead_ms)
        late += run.total_ms > budget
        checked = exploitability(run.strategy).pot_share
        rust_far.append(100 * checked)
        own_gap.append(abs(100 * (run.strategy.exploitability - checked)))
        rust_iterations.append(run.strategy.iterations)
        a, b = bridge.recommend(by_python, d), bridge.recommend(run.strategy, d)
        if a is not None and b is not None:
            both += 1
            same += a[0] == b[0]
            if a[0] != b[0]:
                apart.append(f"    at {d.node!r}, pot {d.spot.pot / bb:.1f} big blinds: Python {describe_mix(a[1])} "
                             f"| subgame-solve {describe_mix(b[1])}")
    n = len(decisions)
    print(f"  {n} spots: answered by subgame-solve {len(calls)}, can't be written as a SPOT {unsaid}, failed {failed}")
    print(f"  Python solver:  {stats(python_ms)}; iterations p50 {percentile(python_iterations, 50):.0f}; "
          f"from an equilibrium, % of the pot: {stats(python_far, '', 3)}")
    if not calls:
        return
    print(f"  subgame-solve:  {stats(calls)} for the whole call; iterations p50 {percentile(rust_iterations, 50):.0f}; "
          f"from an equilibrium, % of the pot: {stats(rust_far, '', 3)}")
    print(f"    of the call, solving (the program's own count): {stats(solving, 'ms', 1)}")
    print(f"    of the call, everything else (overhead):        {stats(overhead, 'ms', 1)}")
    print(f"    calls over the {budget:g} ms budget: {late}; answers over {100 * QUALITY_BAR:.0f}% of the pot: "
          f"{sum(x > 100 * QUALITY_BAR for x in rust_far)}")
    print(f"    the program's own exploitability against the Python checker's, % of the pot: "
          f"largest difference {max(own_gap):.6f}")
    print(f"  the advice would act the same on both answers in {same} of {both} spots where both have one")
    if apart:
        print("  where it would not, the mix for the hero's hand in each answer:")
        print("\n".join(apart))


def whole_decisions(decisions) -> None:
    """advise() on every state, with the Python solver and with the Rust program."""
    results = {}
    for name, rust in (("Python solver", False), ("subgame-solve", True)):
        times, said = [], []
        advice.TUNING["river_solver"] = True  # in this process only: timing, not a comparison
        advice.TUNING["rust_solver"] = rust
        try:
            for _, _, state in decisions:
                st = copy.deepcopy(state)
                computed = sim.sim_compute(st)
                start = time.perf_counter()
                adv = advice.advise(st, computed=computed, numbers_checked=True)
                times.append(1000 * (time.perf_counter() - start))
                said.append((adv.basis, adv.action, adv.amount))
        finally:
            advice.TUNING["river_solver"] = advice.TUNING["rust_solver"] = False
        results[name] = said
        print(f"  advise() with the {name}: {stats(times)} (target {TARGET_MS:.0f} ms); answered by the solver: "
              f"{sum(basis == 'solver' for basis, _, _ in said)} of {len(said)}")
    pairs = list(zip(results["Python solver"], results["subgame-solve"]))
    print(f"  the same instruction (action and amount) from both: {sum(a[1:] == b[1:] for a, b in pairs)} of {len(pairs)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hands", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=77)
    ap.add_argument("--table", default="mixed")
    ap.add_argument("--spots", type=int, default=400, help="river decisions used")
    args = ap.parse_args(argv)
    binary = rust_backend.find_binary()
    if binary is None:
        print(f"subgame-solve isn't built ({rust_backend.DEFAULT_BINARY}).")
        return 2
    samples = collect(args.table, args.hands, args.seed)
    decisions = decisions_of(samples, args.spots)
    print(f"table {args.table}: {args.hands} hands, seed {args.seed}: {len(samples)} heads-up river decisions, "
          f"the first {len(decisions)} used; program {os.path.relpath(binary)}")
    spot_by_spot(decisions, binary)
    whole_decisions(decisions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
