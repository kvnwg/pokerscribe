"""Phase 2, river ranges: how well do the ranges built from the betting predict real cards,
and what do they cost the solver?

    .venv/bin/python docs/research/runs/phase2_ranges.py [--hands 4000] [--seed 31] [--decisions 200]

Nothing here compares strategies. The app's seat plays the frozen baseline with the switch
off, as always; the simulator is only used to deal hands and to see which cards the bots
really hold when a hand reaches the river heads-up. Then:

1. Ranges. At the app's first river decision of each such hand, the opponent's real combo
   is looked up in four guesses of their range: the old placeholder (the "medium" preset,
   the top 25% of starting hands), the pot-size guess (no record of the betting), the
   recorded betting, and the recorded betting with what the app has learned about that
   opponent (their style and how many hands they play and raise). For each:
   how often the real combo is in the range at all, how big the range is, and the score in
   bits: log2 of (probability given to the real combo / probability with no information),
   with 5% of the weight spread evenly so a miss costs a lot, not everything. 0 bits =
   knowing nothing; every bit halves the field.
2. Cost. The first river decisions of those hands (also the later ones of a hand, such as
   facing a raise) through advise() with the switch on in this process only: time for the
   whole decision, how many the solver answered and why not the others, and how far its
   answers were from an equilibrium. Then the same for the decisions facing a raise alone.
3. Facing a raise. The bots next to never raise a river bet, so each river bet the app
   made is answered by a made-up raise the size of the pot and given to the solver: time,
   distance from an equilibrium, and whether it has an answer.
"""
from __future__ import annotations

import argparse
import copy
import math
import os
import sys
import time
from collections import defaultdict
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import app.solver as solver  # noqa: E402
from app.poker import advice, exploits  # noqa: E402
from app.poker.ranges import make_range  # noqa: E402
from app.solver import bridge  # noqa: E402
from app.solver.ranges import river_ranges  # noqa: E402
from app.solver.spot import canonical, normalize_range  # noqa: E402
from app.solver.timing import QUALITY_BAR, TARGET_MS, percentile  # noqa: E402
from tools import simulate as sim  # noqa: E402

SMOOTH = 0.05


def collect(table: str, hands: int, seed: int):
    """Every decision of the app on the river against one opponent, with the cards both
    really hold. "first" marks the first one of each hand."""
    samples, seen = [], set()
    original = sim.decision

    def spy(h, me, overrides, st=None):
        if st is not None and len(h.board) == 5:
            left = [i for i in h.active() if i != me]
            if len(left) == 1:
                v = left[0]
                samples.append({"state": copy.deepcopy(st), "villain": canonical(h.seats[v].cards),
                                "hero": canonical(h.seats[me].cards), "style": h.seats[v].style,
                                "first": h.number not in seen})
                seen.add(h.number)
                adv = original(h, me, overrides, st)
                samples[-1]["did"] = (adv.action, adv.amount)  # what the baseline did (an observation)
                return adv
        return original(h, me, overrides, st)

    sim.decision = spy
    try:
        sim.run(hands, table, seed, quiet=True, profiles=True)
    finally:
        sim.decision = original
    return samples


def spot_of(st):
    """What the advice would hand to the bridge for this state."""
    hero = tuple(c.value for c in st.hero_cards)
    board = tuple(c.value for c in st.board)
    s = advice._spot(st, {}, hero, board, True)
    opp = advice._only_opponent(s)
    river_pot = s.pot - sum(float(p.bet.value) for p in st.players if p.bet.known)
    return dict(board=board, line=st.betting, hero_in_position=advice._acts_last(s), pot_bb=river_pot / s.bb,
                hero_seat=s.pos, villain_seat=opp.position.value, villain_style=exploits.style(opp),
                villain_rates=getattr(opp, "played", None))


def bits(rng, combo, n_live: int) -> float:
    total = sum(w for _, w in rng)
    p = next((w for c, w in rng if c == combo), 0.0) / total if total else 0.0
    return math.log2(((1 - SMOOTH) * p + SMOOTH / n_live) * n_live)


def range_report(samples) -> None:
    rows = defaultdict(lambda: defaultdict(list))
    for x in samples:
        a = spot_of(x["state"])
        board = a["board"]
        medium = normalize_range(make_range("medium").combos, board)
        guesses = {
            "placeholder (top 25%)": (medium, medium),
            "pot size only": river_ranges(board, None, hero_in_position=a["hero_in_position"], pot_bb=a["pot_bb"],
                                          hero_seat=a["hero_seat"], villain_seat=a["villain_seat"]),
            "recorded betting": river_ranges(**{**a, "villain_style": None, "villain_rates": None}),
            "recorded betting + profile": river_ranges(**a),
        }
        n_live = 1081  # combos that don't use a board card
        for name, g in guesses.items():
            hero_r, villain_r = (g.hero, g.villain) if hasattr(g, "hero") else g
            for who, rng, combo in (("villain", villain_r, x["villain"]), ("hero", hero_r, x["hero"])):
                r = rows[who][name]
                r.append((any(c == combo for c, _ in rng), len(rng), bits(rng, combo, n_live)))
    for who in ("villain", "hero"):
        print(f"  {'the opponent' if who == 'villain' else 'the app (as the opponent should see it)'}:")
        print(f"    {'guess':28s} {'real hand in range':>19s} {'combos':>7s} {'bits':>6s}")
        for name, r in rows[who].items():
            n = len(r)
            print(f"    {name:28s} {100 * sum(a for a, _, _ in r) / n:18.1f}% {sum(b for _, b, _ in r) / n:7.0f} "
                  f"{sum(c for _, _, c in r) / n:6.2f}")


def faces_raise(st) -> bool:
    """The app has chips in front on the river and must act again: its bet was raised."""
    return bool(st.hero and st.hero.bet.known and st.hero.bet.value > 0)


def cost_report(samples, limit: int) -> None:
    """The decisions through advise() with the switch on: time, and who answered."""
    times, solves, counts = [], [], defaultdict(int)
    real_solve, real_recommend = solver.solve_river, bridge.recommend

    def solve(spot, **how):
        st = real_solve(spot, **how)
        solves.append((st.elapsed_ms, st.exploitability, len(spot.combos(0)), len(spot.combos(1))))
        return st

    def recommend(strategy, decision):
        got = real_recommend(strategy, decision)
        counts["no answer (a bet the solution has no hands for)"] += got is None
        if got is not None:
            mine = strategy.spot.index(decision.hero, decision.combo)
            unreached = float(strategy.reach(decision.hero)[decision.node][mine]) < bridge.OWN_REACH
            counts["best action for a hand the solution never brings here"] += unreached
        return got

    solver.solve_river, bridge.recommend = solve, recommend
    advice.TUNING["river_solver"] = True  # in this process only: timing, not a comparison
    try:
        for x in samples[:limit]:
            st = copy.deepcopy(x["state"])
            computed = sim.sim_compute(st)
            raised = faces_raise(st)
            start = time.perf_counter()
            adv = advice.advise(st, computed=computed, numbers_checked=True)
            times.append(1000 * (time.perf_counter() - start))
            counts["answered by the solver"] += adv.basis == "solver"
            counts["facing a raise"] += raised
            counts["facing a raise, answered by the solver"] += raised and adv.basis == "solver"
    finally:
        advice.TUNING["river_solver"] = False
        solver.solve_river, bridge.recommend = real_solve, real_recommend
    n = len(times)
    print(f"  {n} decisions through advise(): p50 {percentile(times, 50):.0f} ms, p95 {percentile(times, 95):.0f} ms, "
          f"max {max(times):.0f} ms (target {TARGET_MS:.0f} ms)")
    late = sum(1 for ms, _, _, _ in solves if ms > solver.DECISION_BUDGET_MS)
    rough = sum(1 for _, e, _, _ in solves if e > QUALITY_BAR)
    print(f"  solver called {len(solves)} times: late {late}, too rough (over {100 * QUALITY_BAR:.0f}% of the pot) {rough}")
    for name, k in counts.items():
        print(f"  {name}: {k}")
    if solves:
        e = [100 * v for _, v, _, _ in solves]
        size = [a + b for _, _, a, b in solves]
        print(f"  distance from an equilibrium, % of the pot: p50 {percentile(e, 50):.2f}, p95 {percentile(e, 95):.2f}, "
              f"max {max(e):.2f}; combos in the two ranges together: p50 {percentile(size, 50):.0f}, "
              f"max {max(size)}")


def raise_report(samples, limit: int) -> None:
    """The bots next to never raise a river bet, so there are no real raises to measure.
    Instead each river bet the app really made is answered here by a made-up raise the
    size of the pot, and the solver is asked what to do about it: is its answer in time,
    close enough to an equilibrium, and there at all? Nothing is played out."""
    rows, counts, answers = [], defaultdict(int), defaultdict(int)
    bets = [x for x in samples if x["did"][0] == "bet" and x["did"][1]]
    for x in bets[:limit]:
        st = x["state"]
        a = spot_of(st)
        hero = tuple(c.value for c in st.hero_cards)
        s = advice._spot(st, {}, hero, a["board"], True)
        opp = advice._only_opponent(s)
        bet = float(x["did"][1])
        raise_to = min(bet + (s.pot + 2 * bet), float(opp.stack.value))  # the pot after calling, or all in
        if raise_to <= bet or bet > s.stack:
            counts["they can't raise (too few chips)"] += 1
            continue
        d = bridge.river_decision(hero, a["board"], pot_now=s.pot + bet + raise_to, hero_bet=bet,
                                  villain_bet=raise_to, hero_stack=s.stack - bet,
                                  villain_stack=float(opp.stack.value) - raise_to,
                                  hero_in_position=a["hero_in_position"], line=a["line"], big_blind=s.bb,
                                  hero_seat=a["hero_seat"], villain_seat=a["villain_seat"],
                                  villain_style=a["villain_style"], villain_rates=a["villain_rates"])
        if d is None:
            counts["not a spot the bridge takes"] += 1
            continue
        start = time.perf_counter()
        strategy = solver.solve_river(d.spot, solver.DECISION_BUDGET_MS)
        ms = 1000 * (time.perf_counter() - start)
        rows.append((ms, strategy.exploitability))
        if ms > solver.DECISION_BUDGET_MS:
            counts["late"] += 1
        elif strategy.exploitability > QUALITY_BAR:
            counts[f"too rough (over {100 * QUALITY_BAR:.0f}% of the pot)"] += 1
        else:
            got = bridge.recommend(strategy, d)
            if got is None:
                counts["no answer (a raise the solution has no hands for)"] += 1
            else:
                answers[{"f": "fold", "c": "call", "r": "all in"}[got[0][:1]]] += 1
    print(f"  the app bet the river {len(bets)} times; a made-up raise the size of the pot after each of "
          f"the first {min(limit, len(bets))}:")
    if rows:
        t, e = [r[0] for r in rows], [100 * r[1] for r in rows]
        print(f"    solver: p50 {percentile(t, 50):.0f} ms, p95 {percentile(t, 95):.0f} ms, max {max(t):.0f} ms; "
              f"distance from an equilibrium, % of the pot: p50 {percentile(e, 50):.2f}, "
              f"p95 {percentile(e, 95):.2f}, max {max(e):.2f}")
    print(f"    answered {sum(answers.values())}: " + ", ".join(f"{k} {v}" for k, v in sorted(answers.items())))
    for name, k in counts.items():
        print(f"    {name}: {k}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hands", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--decisions", type=int, default=200, help="decisions timed per table")
    ap.add_argument("--tables", default="mixed,fish247")
    args = ap.parse_args(argv)
    tables = args.tables.split(",")
    with Pool(len(tables)) as pool:  # the hands are dealt side by side; everything timed runs alone afterwards
        dealt = pool.starmap(collect, [(t, args.hands, args.seed) for t in tables])
    for table, decisions in zip(tables, dealt):
        samples = [x for x in decisions if x["first"]]
        recorded = sum(1 for x in samples if x["state"].betting is not None
                       and all(s.known for s in x["state"].betting.streets))
        print(f"table {table}: {args.hands} hands, seed {args.seed}: {len(samples)} reached the river heads-up "
              f"with the app to act; betting fully recorded in {recorded}")
        range_report(samples)
        if args.decisions:
            cost_report(decisions, args.decisions)
            raised = [x for x in decisions if faces_raise(x["state"])]
            print(f"  decisions where the app's river bet was really raised: {len(raised)}")
            if raised:
                cost_report(raised, args.decisions)
            raise_report(decisions, args.decisions)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
