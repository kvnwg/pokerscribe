"""The numbers behind "Phase 2: river solver and push-or-fold" in ../experiments.md.

    .venv/bin/python docs/research/runs/phase2_solver.py > docs/research/runs/phase2_solver.log

Run from the repo root. Nothing here touches the advice or the simulator.
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.getcwd())

import numpy as np  # noqa: E402

from app.solver import IP, solve_river  # noqa: E402
from app.solver.cfr import RiverCFR  # noqa: E402
from app.solver.exploitability import exploitability  # noqa: E402
from app.solver.pushfold import CLASSES, _Game, solve_push_fold  # noqa: E402
from app.solver.timing import benchmark_spots  # noqa: E402
from app.tests import pushfold_chart as chart  # noqa: E402
from app.tests.solver_games import (HALF_STREET, bluff_share_of_bets, call_share, half_street_spot,  # noqa: E402
                                    value_bet_share)
from app.tests.test_solver_cfr import real_spot  # noqa: E402

print("== 1. Answer keys: the half-street game of The Mathematics of Poker (pot 100)")
print("   as the tests run it (budget 2000 ms, stops at 0.1% of the pot), and run long (20000 iterations)")
print("bet    quantity          book      solver(test)  solver(long)")
for s in sorted(HALF_STREET):
    bluffs, calls, value = (float(x) for x in HALF_STREET[s])
    a = solve_river(half_street_spot(s), 2000)
    b = solve_river(half_street_spot(s), None, max_iterations=20000, target_exploitability=0)
    ea, eb = exploitability(a), exploitability(b)
    rows = [("bluff share", bluffs, bluff_share_of_bets(a, s), bluff_share_of_bets(b, s)),
            ("call share", calls, call_share(a, s), call_share(b, s)),
            ("bettor's value", value, ea.value[IP], eb.value[IP]),
            ("value hands bet", 1.0, value_bet_share(a, s), value_bet_share(b, s))]
    for name, book, x, y in rows:
        print(f"{s:<5}  {name:<16}  {book:8.4f}  {x:12.4f}  {y:12.4f}")
    print(f"{s:<5}  exploitability    {0:8.4f}  {100 * ea.pot_share:11.4f}%  {100 * eb.pot_share:11.6f}%"
          f"   ({a.iterations} iterations in {a.elapsed_ms:.0f} ms / {b.iterations})")

print()
print("== 2. Exploitability (% of the pot) as iterations grow")
spots = [("half-street, pot bet", half_street_spot(1.0)), ("two ranges", real_spot()),
         ("benchmark spot", benchmark_spots(1, 3, "narrow")[0])]
marks = (10, 30, 100, 300, 1000, 3000)
print(f"{'spot':<22} {'method':<5} " + " ".join(f"{m:>9}" for m in marks))
for name, spot in spots:
    for method in ("dcfr", "cfr+"):
        solver = RiverCFR(spot, method)
        out = []
        for t in range(1, marks[-1] + 1):
            solver.iterate()
            if t in marks:
                out.append(100 * solver.exploitability())
        print(f"{name:<22} {method:<5} " + " ".join(f"{x:9.5f}" for x in out))

print()
print("== 2b. Discounted CFR against CFR+ at equal iterations, 12 benchmark spots per range size")
print("   median (worst) exploitability in % of the pot")
for ranges in ("narrow", "medium", "wide"):
    bench = benchmark_spots(12, 1, ranges)
    for method in ("dcfr", "cfr+"):
        res = {k: [] for k in (50, 100, 200, 400)}
        for spot in bench:
            solver = RiverCFR(spot, method)
            for t in range(1, 401):
                solver.iterate()
                if t in res:
                    res[t].append(100 * solver.exploitability())
        print(f"{ranges:<7} {method:<5} " + "  ".join(f"{k}: {statistics.median(v):.3f} ({max(v):.3f})" for k, v in res.items()))

print()
print("== 3. Push-or-fold, heads-up, blinds 0.5/1, no ante")
print("stack  jam: chart   solver   book   2nd source | call: chart   solver   2nd source | SB value  exploitability  hands that differ from the chart")
for stack in (5, 8, 10, 12, 15):
    t0 = time.perf_counter()
    sol = solve_push_fold(stack, target_exploitability=1e-6)
    ms = 1000 * (time.perf_counter() - t0)
    game = _Game(float(stack), 0.5, 1.0)
    sb, bb, faced = game.sb_values(sol.call), game.bb_values(sol.jam), game.n.T @ sol.jam
    differ = []
    for i, hand in enumerate(CLASSES):
        if (sol.jam[i] >= 0.5) != chart.chart_pushes(hand, stack):
            differ.append(f"jam {hand} (solver {sol.jam[i]:.2f}; jam minus fold {(sb[i, 1] - sb[i, 0]) / game.dealt[i]:+.4f} bb)")
        if (sol.call[i] >= 0.5) != chart.chart_calls(hand, stack):
            differ.append(f"call {hand} (solver {sol.call[i]:.2f}; call minus fold {(bb[i, 1] - bb[i, 0]) / faced[i]:+.4f} bb)")
    book = chart.BOOK_JAM_SHARES.get(stack)
    second = chart.PUBLISHED_SHARES[stack]
    print(f"{stack:>5}  {100 * chart.chart_share(stack, 'jam'):9.1f}%  {100 * sol.jam_share:5.1f}%  "
          f"{(str(round(100 * book)) + '%') if book else '-':>5}  {100 * second[0]:9.1f}% | "
          f"{100 * chart.chart_share(stack, 'call'):10.1f}%  {100 * sol.call_share:5.1f}%  {100 * second[1]:9.1f}% | "
          f"{sol.value_sb:+.4f}  {sol.exploitability:.1e} bb ({sol.iterations} it, {ms:.0f} ms)  {'; '.join(differ) or 'none'}")
    jam = np.array([1.0 if chart.chart_pushes(h, stack) else 0.0 for h in CLASSES])
    call = np.array([1.0 if chart.chart_calls(h, stack) else 0.0 for h in CLASSES])
    print(f"       the chart played in our game: exploitable for {game.exploitability(jam, call):.6f} bb a hand, "
          f"SB value {game.value_sb(jam, call):+.4f}; mixed hands in the solution: {sol.mixed()}")

print()
print("== 4. Decision time (budget 300 ms, target 400 ms) and the exploitability reached")
from tools import solver_timing  # noqa: E402

solver_timing.main(["--ranges", "all", "--spots", "200"])

print()
print("== 4b. The whole decision through advise(), with the switch turned on inside this script only")
import random  # noqa: E402

from app.poker import advice  # noqa: E402
from app.poker.hands import DECK  # noqa: E402
from app.solver.timing import percentile  # noqa: E402
from app.state.model import Action  # noqa: E402
from app.tests.test_advice import table  # noqa: E402

advice.TUNING["river_solver"] = True  # in this process only: the default in the code stays off
rng = random.Random(7)
times, used, kinds = [], 0, {}
for k in range(150):
    cards = rng.sample(DECK, 7)
    hero, board = cards[:2], cards[2:]
    pot = float(rng.randrange(40, 400))
    stack = pot * rng.choice((0.5, 1.0, 2.0, 4.0, 8.0))
    seat = rng.choice(("BB", "BTN"))
    other = "BTN" if seat == "BB" else "BB"
    common = dict(folded=["SB", "UTG", "HJ", "CO"], stacks={"BB": stack, "BTN": stack})
    if rng.random() < 0.5:  # facing a bet
        bet = float(round(pot * rng.choice((0.33, 0.5, 0.75, 1.0))))
        st = table(hero, seat, board, bets={other: bet}, pot=pot, to_call=bet, last={other: Action("bet", bet)},
                   actions=[Action("fold"), Action("call", bet), Action("raise", 2 * bet)], **common)
    else:
        last = {other: Action("check")} if seat == "BTN" else {}
        st = table(hero, seat, board, bets={}, pot=pot, to_call=0, last=last,
                   actions=[Action("check"), Action("bet", 10)], **common)
    t0 = time.perf_counter()
    a = advice.advise(st, budget_ms=250)
    times.append(1000 * (time.perf_counter() - t0))
    used += a.basis == "solver"
    kinds[a.action] = kinds.get(a.action, 0) + 1
advice.TUNING["river_solver"] = False
print(f"150 heads-up river decisions: p50 {percentile(times, 50):.0f} ms, p95 {percentile(times, 95):.0f} ms, "
      f"max {max(times):.0f} ms; {sum(t > 400 for t in times)} over 400 ms")
print(f"the solver's answer was used in {used} of 150 (the rest fell back to the rules); actions: {kinds}")
