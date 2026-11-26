"""What calling the Rust solver as a separate program costs, apart from the solving.

    python tools/rust_solver_overhead.py [--spots 40] [--repeats 5] [--seed 1]
                                         [--ranges narrow|medium|wide|all] [--binary PATH]
                                         [--advice-hands 6000] [--advice-spots 200]
                                         [--table mixed] [--advice-seed 77]

app/solver/rust_backend.py runs the program `subgame-solve` once per river decision: it
writes the spot as a file, starts the program, and reads the answer back from another
file. All of that counts against the 400 ms decision budget, and none of it is solving.
This script measures it on the benchmark spots of app/solver/timing.py and, with
--advice-hands, on the spots the advice itself would send: every heads-up river decision
of the app's seat in that many simulated hands (collected as
docs/research/runs/phase2_budget.py collects them; the first --advice-spots are used).
It also counts the spots that can't be written as a SPOT (rust_backend.plain_sizes), which
go to the Python solver without a call.

Without --binary the program is a stand-in that does no solving (tools/replay_solve.rs,
compiled here with rustc): it reads the spot and writes back an answer that was solved
beforehand, so the whole call is overhead. What that leaves out is the real program's
own time to read and write JSON.

With --binary PATH the real program is timed, and the overhead of a call is its whole
time less the solving time the program reports in its answer (solver.elapsed_s).

Each call is split into: writing the spot, the program from start to exit, and reading
the answer (parsing it, checking it against the spot's tree, building the strategy).

Exits 0 when the p95 overhead of every range size fits in the time rust_backend keeps
back for it (OVERHEAD_RESERVE_MS), 1 otherwise, 2 when there is nothing to run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.solver import DECISION_BUDGET_MS, rust_backend  # noqa: E402
from app.solver.timing import RANGE_SHARES, TARGET_MS, benchmark_spots, percentile  # noqa: E402
from app.tests import fake_subgame_solve  # noqa: E402

STAND_IN_SOURCE = os.path.join(ROOT, "tools", "replay_solve.rs")
REPLAY_ENV = "POKERSCRIBE_REPLAY_RESULT"


def build_stand_in(folder: str) -> Optional[str]:
    """Compile tools/replay_solve.rs. None when rustc isn't installed."""
    rustc = shutil.which("rustc")
    if rustc is None:
        return None
    out = os.path.join(folder, "replay-solve")
    subprocess.run([rustc, "-O", "-o", out, STAND_IN_SOURCE], check=True, cwd=folder)
    return out


def prepare_answer(spot, folder: str, name: str, iterations: int) -> str:
    """Solve the spot beforehand (the Python solver, through the stand-in used by the
    tests) and save the RESULT, so that the timed program only has to hand it over."""
    spot_path = os.path.join(folder, f"{name}.spot.json")
    result_path = os.path.join(folder, f"{name}.result.jsonl")
    with open(spot_path, "w") as f:
        json.dump(rust_backend.spot_document(spot), f)
    code = fake_subgame_solve.main([spot_path, "--out", result_path, "--max-iterations", str(iterations),
                                    "--target-exploitability", "0"])
    if code != 0:
        raise RuntimeError(f"could not prepare an answer for {name}")
    return result_path


def start_up_ms(binary: str, repeats: int = 200) -> List[float]:
    """Starting the stand-in with no arguments and waiting for it to exit."""
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        subprocess.run([binary], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        times.append(1000.0 * (time.perf_counter() - t0))
    return times


def _stats(values: List[float]) -> str:
    return f"p50 {percentile(values, 50):5.1f}  p95 {percentile(values, 95):5.1f}  max {max(values):5.1f}"


def advice_spots(hands: int, table: str, seed: int, limit: int):
    """The spots the advice would hand the solver, from simulated hands: the first `limit`
    heads-up river decisions of the app's seat (the baseline plays; nothing is compared)."""
    sys.path.insert(0, os.path.join(ROOT, "docs", "research", "runs"))
    from phase2_budget import decisions_of  # noqa: E402
    from phase2_ranges import collect  # noqa: E402

    return [d.spot for d, _, _ in decisions_of(collect(table, hands, seed), limit)]


def measure(label: str, spots, args, binary: str, real: bool, folder: str) -> bool:
    overhead, write, run, read, sizes, solving, used, unsaid = [], [], [], [], [], [], [], []
    for i, spot in enumerate(spots):
        try:
            rust_backend.spot_document(spot)
        except rust_backend.UnsupportedSpot:
            unsaid.append(spot.effective_stack / spot.pot)  # the Python solver's: no call is made
            continue
        used.append(spot)
        if not real:
            os.environ[REPLAY_ENV] = prepare_answer(spot, folder, f"{abs(hash(label))}-{i}", args.iterations)
        for _ in range(args.repeats):
            got = rust_backend.run_solver(
                spot, binary, time_ms=args.budget_ms - rust_backend.OVERHEAD_RESERVE_MS,
                target_exploitability=rust_backend.TARGET_EXPLOITABILITY, timeout_ms=20 * args.budget_ms)
            if real and got.overhead_ms is None:
                raise SystemExit("The program's answer has no solver.elapsed_s, so its solving time can't be "
                                 "taken off. Nothing measured.")
            overhead.append(got.overhead_ms if real else got.total_ms)
            write.append(got.write_ms)
            run.append(got.run_ms)
            read.append(got.read_ms)
            sizes.append(got.result_bytes)
            solving.append(got.solver_ms or 0.0)
    print(f"{label}: {len(spots)} spots, {len(unsaid)} of them can't be written as a SPOT "
          f"(the Python solver's, no call)" +
          (f"; their stacks are {min(unsaid):.1f} to {max(unsaid):.1f} pots" if unsaid else ""))
    if not used:
        return True
    combos = sorted(len(s.oop_range) + len(s.ip_range) for s in used)
    nodes = sorted(sum(1 for _ in rust_backend.GameTree(s).decision_nodes()) for s in used)
    p95 = percentile(overhead, 95)
    print(f"  {len(used)} spots x {args.repeats} calls, {combos[0]} to {combos[-1]} combos (median "
          f"{combos[len(combos) // 2]}), {nodes[0]} to {nodes[-1]} decision nodes, "
          f"answers of {min(sizes) / 1000:.0f} to {max(sizes) / 1000:.0f} kB")
    print(f"  overhead per call, ms:   {_stats(overhead)}")
    print(f"    writing the spot:      {_stats(write)}")
    if real:
        print(f"    the program, in all:   {_stats(run)}   (of which solving: {_stats(solving)})")
    else:
        print(f"    the program:           {_stats(run)}")
    print(f"    reading the answer:    {_stats(read)}")
    print(f"  p95 is {100 * p95 / TARGET_MS:.1f}% of the {TARGET_MS:g} ms decision budget; "
          f"{'within' if p95 <= rust_backend.OVERHEAD_RESERVE_MS else 'OVER'} the "
          f"{rust_backend.OVERHEAD_RESERVE_MS:g} ms kept back for it")
    return p95 <= rust_backend.OVERHEAD_RESERVE_MS


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spots", type=int, default=40)
    ap.add_argument("--repeats", type=int, default=5, help="calls per spot")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ranges", choices=sorted(RANGE_SHARES) + ["all"], default="all")
    ap.add_argument("--budget-ms", type=float, default=DECISION_BUDGET_MS, help="the solver's time budget per decision")
    ap.add_argument("--iterations", type=int, default=60, help="iterations of the answers solved beforehand")
    ap.add_argument("--binary", help="time the real subgame-solve at this path (default: the stand-in)")
    ap.add_argument("--advice-hands", type=int, default=0,
                    help="also measure on the advice's own river spots from this many simulated hands")
    ap.add_argument("--advice-spots", type=int, default=200, help="how many of those spots are used")
    ap.add_argument("--table", default="mixed", help="the simulator table those hands are played at")
    ap.add_argument("--advice-seed", type=int, default=77)
    args = ap.parse_args(argv)
    kinds = ["narrow", "medium", "wide"] if args.ranges == "all" else [args.ranges]
    groups = [(f"{kind} ranges", benchmark_spots(args.spots, args.seed, kind)) for kind in kinds]
    if args.advice_hands:  # dealt before anything is timed
        groups.append((f"the advice's spots (table {args.table}, {args.advice_hands} hands, seed {args.advice_seed})",
                       advice_spots(args.advice_hands, args.table, args.advice_seed, args.advice_spots)))

    with tempfile.TemporaryDirectory(prefix="pokerscribe-overhead-") as folder:
        if args.binary:
            if not (os.path.isfile(args.binary) and os.access(args.binary, os.X_OK)):
                print(f"{args.binary} is not a program.")
                return 2
            binary, real = args.binary, True
            print(f"Timing {binary}: overhead = the whole call less the solving time it reports.")
        else:
            binary, real = build_stand_in(folder), False
            if binary is None:
                print("rustc isn't installed, so the stand-in can't be built. Install Rust, or give --binary.")
                return 2
            start = start_up_ms(binary)
            print("Stand-in program (no solving, no JSON work of its own): the whole call is overhead.")
            print(f"Starting a native program and waiting for it, ms: {_stats(start)}")
        print(f"Budget: {args.budget_ms:g} ms for the solver out of {TARGET_MS:g} ms per decision; "
              f"rust_backend keeps {rust_backend.OVERHEAD_RESERVE_MS:g} ms of it back for overhead.")
        results = [measure(label, spots, args, binary, real, folder) for label, spots in groups]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
