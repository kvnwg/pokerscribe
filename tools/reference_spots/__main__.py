"""Reference river spots solved by the Python river solver.

    python -m tools.reference_spots make-spots [--lines]   # defs.py -> spots/*.json
    python -m tools.reference_spots solve [ids] [--force]  # spots -> results/*.jsonl, index.json, README table
    python -m tools.reference_spots validate               # every spot and result, and the known answers
    python -m tools.reference_spots report                 # the tables, as Markdown
    python -m tools.reference_spots check <folder>         # another solver's RESULT files against the reference
    python -m tools.reference_spots rust [--target 0.3]    # run the Rust solver on every spot and check it
    python -m tools.reference_spots texassolver            # app/solver against TexasSolver's 30 river keys

Everything is under data/reference_spots/python_solver/ (see its README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from typing import Dict, List, Mapping, Optional

from app.solver import DECISION_BUDGET_MS, solve_river
from app.solver.exploitability import exploitability
from app.solver.labels import SOLVER_NAME, SOLVER_VERSION
from tools.answer_keys import result as result_mod
from tools.answer_keys import spots as key_spots
from tools.answer_keys.checks import check_expected, river_checks
from tools.answer_keys.spots import decision_nodes, load_spots, river_spot, spot_hash

from . import build, compare, defs, known, solve

INDEX = "index.json"
RUST_BINARY = os.path.join(build.ROOT, "engine", "target", "release", "subgame-solve")
TABLE_START, TABLE_END = "<!-- reference-table:start -->", "<!-- reference-table:end -->"


def load_index(home: str = build.HOME) -> dict:
    path = os.path.join(home, INDEX)
    return build.load_json(path) if os.path.exists(path) else {"spots": {}}


def save_index(index: Mapping, home: str = build.HOME) -> None:
    with open(os.path.join(home, INDEX), "w") as f:
        json.dump(index, f, indent=1, sort_keys=True)
        f.write("\n")


def saved(spot_id: str, results_dir: str = build.RESULTS_DIR):
    path = result_mod.result_path(results_dir, spot_id)
    return result_mod.read_result(path) if path else None


def entry(spot: Mapping, header: Mapping, path: str, app_budget: Mapping) -> Dict:
    checks, info = header["checks"], header["solver"]
    out = {"title": spot["title"], "tags": spot["tags"], "spr": spot["spr"],
           "combos": [len(spot["ranges"]["oop"]), len(spot["ranges"]["ip"])], "nodes": header["nodes"],
           "spot_sha256": header["spot_sha256"], "file": os.path.basename(path),
           "iterations": info["iterations"], "elapsed_s": info["elapsed_s"], "converged": info["converged"],
           "exploitability_pot": checks["exploitability_pot"], "oop_value": checks["values"]["oop"],
           "oop_value_bounds": checks["oop_value_bounds"], "app_budget": dict(app_budget)}
    if spot["id"] in defs.KNOWN:
        out["known_oop_value"] = round(float(defs.KNOWN[spot["id"]]["oop_value"]), 6)
    return out


# ------------------------------------------------------------------ commands
def cmd_make_spots(args) -> int:
    paths = build.write_spots(lines=args.lines)
    print(f"wrote {len(paths)} spots to {build.SPOTS_DIR}")
    if not args.lines:
        print("(the spots with the app's ranges were left as they are; --lines makes them again)")
    return 0


def cmd_solve(args) -> int:
    index = load_index()
    index["solver"] = {"name": SOLVER_NAME, "version": SOLVER_VERSION, "module": "app.solver"}
    index["settings"] = {"target_exploitability_pot": solve.REFERENCE_TARGET,
                         "max_iterations": solve.REFERENCE_MAX_ITERATIONS, "app_budget_ms": DECISION_BUDGET_MS}
    index["machine"] = f"{platform.system()} {platform.machine()}, {os.cpu_count()} cores"
    failed = 0
    for spot in load_spots(build.SPOTS_DIR, args.ids or None):
        sid, old = spot["id"], index["spots"].get(spot["id"])
        if old and old.get("spot_sha256") == spot_hash(spot) and saved(sid) and not args.force:
            print(f"{sid}: already solved")
            continue
        strategy, info = solve.reference_solve(spot)
        header, nodes = solve.make_result(spot, strategy, info)
        checks = header["checks"]
        problems = list(checks["expected_failures"])
        if checks["exploitability_pot"] > solve.ACCEPT:
            problems.append(f"{100 * checks['exploitability_pot']:.4f}% of the pot from an equilibrium")
        if problems:
            failed += 1
            print(f"{sid}: NOT saved: " + "; ".join(problems[:3]))
            continue
        path = result_mod.write_result(build.RESULTS_DIR, header, nodes)
        index["spots"][sid] = entry(spot, header, path, solve.at_the_apps_budget(spot))
        e = index["spots"][sid]
        print(f"{sid}: {e['iterations']} iterations, {e['elapsed_s']} s, {100 * e['exploitability_pot']:.4f}% of the pot, "
              f"OOP value {e['oop_value']:.4f}; at 300 ms: {e['app_budget']['ms']:.0f} ms, "
              f"{100 * e['app_budget']['exploitability_pot']:.3f}%")
    save_index(index)
    write_readme_table(index)
    return 1 if failed else 0


def validate_all(home: str = build.HOME) -> List[str]:
    """Every problem with the saved spots and results (an empty list passes)."""
    problems = []
    spots = {s["id"]: s for s in load_spots(os.path.join(home, "spots"))}
    for d in defs.SPOTS:
        if spots.get(d["id"]) != build.build_spot(d):
            problems.append(f"{d['id']}: the spot file isn't what defs.py gives (run make-spots, then solve)")
    for d in defs.LINES:
        if d["id"] not in spots:
            problems.append(f"{d['id']}: missing (run make-spots --lines)")
    for sid, spot in spots.items():
        got = saved(sid, os.path.join(home, "results"))
        if got is None:
            problems.append(f"{sid}: no result")
            continue
        header, nodes = got
        try:
            result_mod.validate_result(header, nodes, spot, spot_hash(spot), decision_nodes(spot))
        except result_mod.ResultError as e:
            problems.append(str(e))
            continue
        checks = river_checks(spot, nodes)
        if checks != {k: header["checks"][k] for k in checks}:
            problems.append(f"{sid}: the saved checks aren't what the saved strategy gives")
        if checks["exploitability_pot"] > solve.ACCEPT:
            problems.append(f"{sid}: {100 * checks['exploitability_pot']:.4f}% of the pot from an equilibrium")
        problems += [f"{sid}: {f}" for f in check_expected(spot, nodes)]
        problems += [f"{sid}: {f}" for f in known.known_failures(spot, nodes, checks)]
    return problems


def cmd_validate(args) -> int:
    problems = validate_all()
    for p in problems:
        print("PROBLEM", p)
    n = len(load_spots(build.SPOTS_DIR))
    print(f"{n} spots, {len(problems)} problems")
    return 1 if problems else 0


def spot_table(index: Mapping) -> str:
    rows = ["| Spot | What | Combos (OOP, IP) | Nodes | Reference: iterations | Time | From an equilibrium | OOP value "
            "| Known value | At 300 ms: time | From an equilibrium |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for sid in sorted(index["spots"]):
        e = index["spots"][sid]
        knownv = f"{e['known_oop_value']:.4f}" if "known_oop_value" in e else ""
        a = e["app_budget"]
        rows.append(f"| {sid} | {e['title']} | {e['combos'][0]}, {e['combos'][1]} | {e['nodes']} | {e['iterations']} "
                    f"| {e['elapsed_s']:.2f} s | {100 * e['exploitability_pot']:.4f}% | {e['oop_value']:.4f} | {knownv} "
                    f"| {a['ms']:.0f} ms | {100 * a['exploitability_pot']:.3f}% |")
    return "\n".join(rows)


def known_table() -> str:
    rows = ["| Spot | Bet, pots | Bluff share: known | solver | Call share: known | solver | OOP value: known | solver |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for spot in load_spots(build.SPOTS_DIR):
        want = defs.KNOWN.get(spot["id"])
        got = saved(spot["id"])
        if not want or not got:
            continue
        header, nodes = got
        value = f"{float(want['oop_value']):.4f} | {header['checks']['values']['oop']:.4f}"
        if "bettor" in want:
            s = known.polar_shares(spot, nodes)
            rows.append(f"| {spot['id']} | {want['s']:g} | {float(want['bluffs']):.4f} | {s['bluffs']:.4f} "
                        f"| {float(want['calls']):.4f} | {s['calls']:.4f} | {value} |")
        else:
            rows.append(f"| {spot['id']} |  |  |  |  |  | {value} |")
    return "\n".join(rows)


def write_readme_table(index: Mapping, home: str = build.HOME) -> None:
    path = os.path.join(home, "README.md")
    if not os.path.exists(path):
        return
    text = open(path).read()
    if TABLE_START not in text or TABLE_END not in text:
        return
    head, rest = text.split(TABLE_START, 1)
    tail = rest.split(TABLE_END, 1)[1]
    block = (f"\nSolved on: {index.get('machine', '')}. Reference target: "
             f"{100 * index['settings']['target_exploitability_pot']:.3f}% of the pot.\n\n{spot_table(index)}\n")
    with open(path, "w") as f:
        f.write(head + TABLE_START + block + TABLE_END + tail)


def cmd_report(args) -> int:
    index = load_index()
    print(spot_table(index))
    print()
    print(known_table())
    return 0


def check_folder(folder: str, *, max_exploitability: float = compare.MAX_EXPLOITABILITY,
                 value_tol: float = compare.VALUE_TOL, share_tol: Optional[float] = None,
                 home: str = build.HOME) -> List[Dict]:
    """Another solver's answers (RESULT files named <spot id>.jsonl in `folder`) against the
    reference: one row a spot with its numbers and its problems."""
    rows = []
    for spot in load_spots(os.path.join(home, "spots")):
        sid = spot["id"]
        ref_header, _ = saved(sid, os.path.join(home, "results"))
        path = result_mod.result_path(folder, sid)
        if not path:
            rows.append({"id": sid, "problems": ["no answer"]})
            continue
        header, nodes = result_mod.read_result(path)
        try:
            result_mod.validate_result(header, nodes, spot, spot_hash(spot), decision_nodes(spot))
        except result_mod.ResultError as e:
            rows.append({"id": sid, "problems": [str(e)]})
            continue
        numbers, problems = compare.check_answer(spot, nodes, ref_header["checks"], max_exploitability=max_exploitability,
                                                 value_tol=value_tol, share_tol=share_tol)
        info = header.get("solver", {})
        rows.append({"id": sid, "problems": problems, "reference_value": ref_header["checks"]["values"]["oop"],
                     "iterations": info.get("iterations"), "elapsed_s": info.get("elapsed_s"), **numbers})
    return rows


def print_check(rows: List[Mapping]) -> int:
    print("| Spot | Iterations | Time | From an equilibrium (our measure) | OOP value | Reference | Difference "
          "| Bounds meet | Problems |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    bad = 0
    for r in rows:
        bad += bool(r["problems"])
        if "oop_value" not in r:
            print(f"| {r['id']} |  |  |  |  |  |  |  | {'; '.join(r['problems'])} |")
            continue
        ms = "" if r["elapsed_s"] is None else f"{1000 * r['elapsed_s']:.1f} ms"
        print(f"| {r['id']} | {r['iterations'] if r['iterations'] is not None else ''} | {ms} "
              f"| {100 * r['exploitability_pot']:.4f}% | {r['oop_value']:.4f} | {r['reference_value']:.4f} "
              f"| {r['difference']:+.4f} | {'yes' if r['bounds_meet'] else 'NO'} | {'; '.join(r['problems'])} |")
    done = [r for r in rows if "oop_value" in r]
    if done:
        print(f"\n{len(rows)} spots, {bad} with problems; largest difference from the reference value "
              f"{max(abs(r['difference']) for r in done):.4f} chips (the pot is 100), furthest from an equilibrium "
              f"{100 * max(r['exploitability_pot'] for r in done):.4f}% of the pot")
    return 1 if bad else 0


def _limits(args) -> Dict:
    return {"max_exploitability": args.max_exploitability / 100, "value_tol": args.value / 100, "share_tol": args.shares}


def cmd_check(args) -> int:
    return print_check(check_folder(args.folder, **_limits(args)))


def cmd_rust(args) -> int:
    """Run engine/crates/subgame's subgame-solve on every reference spot, then check it."""
    binary = os.path.normpath(args.binary)
    if not os.path.exists(binary):
        print(f"{binary} isn't built. From engine/: cargo build --release -p subgame")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        for spot in load_spots(build.SPOTS_DIR):
            src = os.path.join(build.SPOTS_DIR, f"{spot['id']}.json")
            cmd = [binary, src, "--out", os.path.join(tmp, f"{spot['id']}.jsonl"), "--target-exploitability",
                   f"{args.target:g}", "--max-iterations", str(args.max_iterations)]
            done = subprocess.run(cmd, capture_output=True, text=True)
            if done.returncode:
                print(f"{spot['id']}: subgame-solve failed: {done.stderr.strip()}")
        print(f"subgame-solve at a target of {args.target:g}% of the pot:\n")
        return print_check(check_folder(tmp, **_limits(args)))


def cmd_texassolver(args) -> int:
    """app/solver on TexasSolver's 30 river keys: as the app runs it (300 ms) and solved
    tight. The key's value has TexasSolver's own error in it (up to 0.3% of the pot)."""
    print("| Spot | Nodes | TexasSolver: OOP value | its exploitability | app/solver at 300 ms: value | difference "
          "| exploitability | ms | app/solver tight: value | difference | bounds meet |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    worst_quick = worst_tight = 0.0
    for spot in load_spots(key_spots.SPOTS_DIR):
        if spot["street"] != "river":
            continue
        path = result_mod.result_path(key_spots.RESULTS_DIR, spot["id"])
        header, _ = result_mod.read_result(path)
        key = header["checks"]
        rs = river_spot(spot)
        quick = solve_river(rs, DECISION_BUDGET_MS)
        eq = exploitability(quick)
        tight = solve_river(rs, None, max_iterations=solve.REFERENCE_MAX_ITERATIONS,
                            target_exploitability=solve.REFERENCE_TARGET)
        et = exploitability(tight)
        lo, hi = key["oop_value_bounds"]
        meet = max(lo, spot["pot"] - et.best_response[1]) <= min(hi, et.best_response[0]) + 1e-6
        dq, dt = eq.value[0] - key["values"]["oop"], et.value[0] - key["values"]["oop"]
        worst_quick, worst_tight = max(worst_quick, abs(dq)), max(worst_tight, abs(dt))
        print(f"| {spot['id']} | {header['nodes']} | {key['values']['oop']:.3f} | {100 * key['exploitability_pot']:.3f}% "
              f"| {eq.value[0]:.3f} | {dq:+.3f} | {100 * eq.pot_share:.3f}% | {quick.elapsed_ms:.0f} "
              f"| {et.value[0]:.3f} | {dt:+.3f} | {'yes' if meet else 'NO'} |", flush=True)
    print(f"\nlargest difference from TexasSolver's value: {worst_quick:.3f} chips at 300 ms, {worst_tight:.3f} solved tight "
          f"(the pot is 100, so chips are percent of the pot)")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.reference_spots", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("make-spots")
    q.add_argument("--lines", action="store_true", help="also make the spots with the app's ranges again")
    q.set_defaults(fn=cmd_make_spots)
    q = sub.add_parser("solve")
    q.add_argument("ids", nargs="*")
    q.add_argument("--force", action="store_true")
    q.set_defaults(fn=cmd_solve)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    for name, fn in (("check", cmd_check), ("rust", cmd_rust)):
        q = sub.add_parser(name)
        if name == "check":
            q.add_argument("folder", help="RESULT files named <spot id>.jsonl")
        else:
            q.add_argument("--binary", default=RUST_BINARY)
            q.add_argument("--target", type=float, default=0.3, help="percent of the pot (subgame-solve's default)")
            q.add_argument("--max-iterations", type=int, default=100000)
        q.add_argument("--max-exploitability", type=float, default=100 * compare.MAX_EXPLOITABILITY,
                       help="percent of the pot, by our own best response")
        q.add_argument("--value", type=float, default=100 * compare.VALUE_TOL, help="percent of the pot")
        q.add_argument("--shares", type=float, default=None,
                       help="also check the known bluff and call shares, within this much (for tight solves)")
        q.set_defaults(fn=fn)
    sub.add_parser("texassolver").set_defaults(fn=cmd_texassolver)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
