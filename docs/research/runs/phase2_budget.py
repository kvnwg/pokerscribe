"""Phase 2, the solver's time: where it goes by the size of the pot, and whether a run in
the simulator repeats exactly.

    .venv/bin/python docs/research/runs/phase2_budget.py [--hands 6000] [--seed 77] [--spots 200]

Nothing here compares strategies. As in phase2_ranges.py, the simulator only deals hands
(the app's seat plays the frozen baseline with the switch off); every heads-up river
decision of the app becomes a spot for the solver. Then, per table:

1. By pot size. Each spot solved twice inside the same 300 ms: stopping early at 0.1% of
   the pot (the old rule) and at a hundredth of a big blind (the new one, solve.target_for).
   Time, and how far the answer is from an equilibrium, as a share of the pot and in big
   blinds.
2. The whole decision through advise(), switch on in this process only: time, and how
   many the solver answered.
3. Fixed work (what the simulator uses in place of the clock): each spot solved twice
   must give exactly the same strategy, a fresh process must agree, and advise() twice
   must give the same instruction. Also how the iterations compare with what the clock
   gave on this machine, and how often the action is the same as by the clock.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import multiprocessing
import os
import sys
import time
from collections import defaultdict
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import app.solver as solver  # noqa: E402
from app.poker import advice  # noqa: E402
from app.solver import bridge  # noqa: E402
from app.solver.solve import TARGET_EXPLOITABILITY  # noqa: E402
from app.solver.timing import QUALITY_BAR, TARGET_MS, percentile  # noqa: E402
from phase2_ranges import collect  # noqa: E402
from tools import simulate as sim  # noqa: E402

BUCKETS = ((0, 3), (3, 8), (8, 20), (20, 50), (50, float("inf")))


def decisions_of(samples, limit: int):
    """(the bridge's decision, the big blind) for each state the solver would be asked about."""
    out, seen = [], {}
    real_decision, real_settings, real_solve = bridge.river_decision, solver.decision_settings, solver.solve_river

    def spy_decision(*args, **kw):
        seen["decision"] = real_decision(*args, **kw)
        return seen["decision"]

    def spy_settings(spot, big_blind=None, repeatable=False):
        seen["bb"] = big_blind
        return real_settings(spot, big_blind, repeatable)

    def no_solve(spot, **how):
        raise NotImplementedError

    bridge.river_decision, solver.decision_settings, solver.solve_river = spy_decision, spy_settings, no_solve
    advice.TUNING["river_solver"] = True  # in this process only: to see what the solver would be given
    try:
        for x in samples:
            seen.clear()
            st = copy.deepcopy(x["state"])
            advice.advise(st, computed=sim.sim_compute(st), numbers_checked=True)
            if seen.get("decision") is not None and seen.get("bb"):
                out.append((seen["decision"], float(seen["bb"]), x["state"]))
            if len(out) >= limit:
                break
    finally:
        advice.TUNING["river_solver"] = False
        bridge.river_decision, solver.decision_settings, solver.solve_river = real_decision, real_settings, real_solve
    return out


def digest(strategy) -> str:
    h = hashlib.sha256(str(strategy.iterations).encode())
    for key in sorted(strategy.probs):
        h.update(key.encode())
        h.update(np.ascontiguousarray(strategy.probs[key]).tobytes())
    return h.hexdigest()


def fixed_digests(args):
    """The fixed-work strategies of these spots, as digests (run in a fresh process too)."""
    return [digest(solver.solve_river(spot, **solver.decision_settings(spot, bb, True))) for spot, bb in args]


def by_pot(decisions) -> None:
    rows = defaultdict(list)
    for d, bb, _ in decisions:
        pot_bb = d.spot.pot / bb
        old = solver.solve_river(d.spot, solver.DECISION_BUDGET_MS, target_exploitability=TARGET_EXPLOITABILITY)
        new = solver.solve_river(d.spot, **solver.decision_settings(d.spot, bb))
        rows[next(b for b in BUCKETS if b[0] < pot_bb <= b[1])].append((pot_bb, old, new))
    print(f"  {'pot, big blinds':16s} {'spots':>5s} | {'stop at 0.1% of the pot':^36s} | {'stop at 0.01 big blinds':^36s}")
    print(f"  {'':16s} {'':>5s} | {'ms p50':>7s} {'ms p90':>7s} {'% of pot':>9s} {'bb':>8s} | "
          f"{'ms p50':>7s} {'ms p90':>7s} {'% of pot':>9s} {'bb':>8s}")
    everything = []
    for b in BUCKETS:
        r = rows.get(b, [])
        everything += r
        if not r:
            continue
        line = f"  {b[0]:>3.0f} to {b[1]:<9.0f} {len(r):5d} |"
        for k in (1, 2):
            ms = [x[k].elapsed_ms for x in r]
            share = [100 * x[k].exploitability for x in r]
            chips = [x[k].exploitability * x[0] for x in r]
            line += f" {percentile(ms, 50):7.0f} {percentile(ms, 90):7.0f} {percentile(share, 50):9.3f} {np.mean(chips):8.4f} |"
        print(line)
    for name, k in (("old", 1), ("new", 2)):
        ms = [x[k].elapsed_ms for x in everything]
        chips = [x[k].exploitability * x[0] for x in everything]
        rough = sum(1 for x in everything if x[k].exploitability > QUALITY_BAR)
        print(f"  {name}: time mean {np.mean(ms):.0f} ms, p50 {percentile(ms, 50):.0f}, p95 {percentile(ms, 95):.0f}; "
              f"from an equilibrium, big blinds: mean {np.mean(chips):.4f}, worst {max(chips):.4f}; "
              f"over {100 * QUALITY_BAR:.0f}% of the pot: {rough} of {len(everything)}")


def whole_decisions(decisions) -> None:
    times, answered = [], 0
    advice.TUNING["river_solver"] = True  # in this process only: timing, not a comparison
    try:
        for _, _, state in decisions:
            st = copy.deepcopy(state)
            computed = sim.sim_compute(st)
            start = time.perf_counter()
            adv = advice.advise(st, computed=computed, numbers_checked=True)
            times.append(1000 * (time.perf_counter() - start))
            answered += adv.basis == "solver"
    finally:
        advice.TUNING["river_solver"] = False
    print(f"  {len(times)} decisions through advise(): p50 {percentile(times, 50):.0f} ms, "
          f"p95 {percentile(times, 95):.0f} ms, max {max(times):.0f} ms (target {TARGET_MS:.0f} ms); "
          f"answered by the solver: {answered}")


def fixed_work(decisions) -> None:
    same_strategy = same_action = both = usable = 0
    ratios, shares = [], []
    for d, bb, _ in decisions:
        how = solver.decision_settings(d.spot, bb, True)
        first, again = solver.solve_river(d.spot, **how), solver.solve_river(d.spot, **how)
        same_strategy += digest(first) == digest(again)
        clock = solver.solve_river(d.spot, **solver.decision_settings(d.spot, bb))
        if first.iterations == how["max_iterations"] and clock.exploitability > how["target_exploitability"]:
            ratios.append(first.iterations / clock.iterations)  # both ran out of budget: comparable
        shares.append(100 * first.exploitability)
        usable += first.exploitability <= QUALITY_BAR
        a, b = bridge.recommend(first, d), bridge.recommend(clock, d)
        if a is not None and b is not None:
            both += 1
            same_action += a[0] == b[0]
    n = len(decisions)
    print(f"  fixed work, {n} spots: the same strategy twice in {same_strategy}; within {100 * QUALITY_BAR:.0f}% of the pot "
          f"in {usable}; from an equilibrium, % of the pot: p50 {percentile(shares, 50):.3f}, p95 {percentile(shares, 95):.3f}")
    if ratios:
        print(f"  iterations, fixed work / by the clock on this machine ({len(ratios)} spots where both used their "
              f"whole budget): p10 {percentile(ratios, 10):.2f}, p50 {percentile(ratios, 50):.2f}, p90 {percentile(ratios, 90):.2f}")
    print(f"  the same action as by the clock: {same_action} of {both}")
    args = [(d.spot, bb) for d, bb, _ in decisions[:60]]
    here = fixed_digests(args)
    with multiprocessing.get_context("spawn").Pool(1) as pool:
        there = pool.apply(fixed_digests, (args,))
    print(f"  a fresh process gives the same strategy in {sum(a == b for a, b in zip(here, there))} of {len(args)}")
    agree = 0
    with sim.variant({"river_solver": True}):  # as tools/compare.py would run it
        for _, _, state in decisions[:60]:
            runs = []
            for _ in range(2):
                st = copy.deepcopy(state)
                runs.append(advice.advise(st, computed=sim.sim_compute(st), numbers_checked=True).to_dict())
            agree += runs[0] == runs[1]
    print(f"  advise() twice in the simulator's mode gives the same instruction in {agree} of {len(args)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hands", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=77)
    ap.add_argument("--spots", type=int, default=200, help="river decisions used per table")
    ap.add_argument("--tables", default="mixed,fish247")
    args = ap.parse_args(argv)
    tables = args.tables.split(",")
    with Pool(len(tables)) as pool:  # the hands are dealt side by side; everything timed runs alone afterwards
        dealt = pool.starmap(collect, [(t, args.hands, args.seed) for t in tables])
    for table, samples in zip(tables, dealt):
        decisions = decisions_of(samples, args.spots)
        print(f"table {table}: {args.hands} hands, seed {args.seed}: {len(samples)} heads-up river decisions, "
              f"the first {len(decisions)} used")
        by_pot(decisions)
        whole_decisions(decisions)
        fixed_work(decisions)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
