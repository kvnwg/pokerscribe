"""Answer keys from TexasSolver (data/answer_keys/README.md), and checking solvers against
them (docs/research/PHASE4.md).

    python -m tools.answer_keys make-spots              # spot_defs.py -> data/answer_keys/spots/
    python -m tools.answer_keys validate                # every spot, and every saved result
    python -m tools.answer_keys config r04              # print the TexasSolver config of a spot
    python -m tools.answer_keys solve --solver ~/answer-keys/TexasSolver/console_solver [ids ...]
    python -m tools.answer_keys parse r04 --dump r04.json [--log r04.log]   # a dump you ran yourself
    python -m tools.answer_keys report                  # rewrite the solve table in the README

    python -m tools.answer_keys export-python           # river spots by app/solver -> data/answer_keys/python_solver/
    python -m tools.answer_keys compare <results dir> [--against texassolver|python_solver]
    python -m tools.answer_keys run --solver <path to subgame-solve> [--spots river|turn|all] [--target 0.5]
                                    [--repeat 3]

solve skips spots whose saved result is for the same spot (same sha256) unless --force.
Configs, raw dumps and logs go to --workdir (default ~/answer-keys/work), outside the repo;
only the parsed results are saved here, in data/answer_keys/texassolver/.

compare prints one row per spot and a pass/fail line for the Phase 4 gates (EV within 0.5%
of the pot of the reference, exploitability under 0.5% of the pot); it exits with 1 when
they fail. run times any binary that follows the subgame-solve command line (runner.py),
saves its RESULTs to data/answer_keys/<name>/ and reports p50 and p95 wall time per street.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.answer_keys import compare as cmp  # noqa: E402
from tools.answer_keys import python_solver, runner  # noqa: E402
from tools.answer_keys import texassolver as ts  # noqa: E402
from tools.answer_keys.build import write_spots  # noqa: E402
from tools.answer_keys.checks import check_expected, river_exploitability  # noqa: E402
from tools.answer_keys.result import (make_header, read_result, result_path, validate_result,  # noqa: E402
                                      write_result)
from tools.answer_keys.spot_defs import SPOTS  # noqa: E402
from tools.answer_keys.spots import (RESULTS_DIR, ROOT, SPOTS_DIR, decision_nodes, load_spots,  # noqa: E402
                                     spot_hash, streets_of)

README = os.path.join(ROOT, "data", "answer_keys", "README.md")
INDEX = "index.json"
TABLE_START, TABLE_END = "<!-- solve-table:start -->", "<!-- solve-table:end -->"
CHECK_SLACK = 2.0  # our own exploitability may be up to this many times the target before it warns


def save_parsed(spot: Mapping, parsed: ts.Parsed, solver_info: Mapping, results_dir: str,
                accuracy_pct: float) -> dict:
    """Check a parsed dump, save it as a RESULT, and return its index entry."""
    sha = spot_hash(spot)
    problems, warnings = [], []
    if parsed.differences:
        problems.append("TexasSolver's tree differs from the spot's: " + "; ".join(parsed.differences))
    checks = {"exploitability_pot": None, "filled_rows": 0, "expected_failures": []}
    if not problems:
        failures = check_expected(spot, parsed.nodes)
        checks["expected_failures"] = failures[:20]
        if failures:
            problems.append(f"{len(failures)} expected checks fail, e.g. {failures[0]}")
        if spot["street"] == "river":
            expl, filled = river_exploitability(spot, parsed.nodes)
            checks["exploitability_pot"], checks["filled_rows"] = round(expl, 8), filled
            if expl > CHECK_SLACK * accuracy_pct / 100:
                warnings.append(f"our own check finds {expl:.3%} of the pot")
    if not solver_info.get("converged"):
        warnings.append("TexasSolver stopped before reaching the target")
    solver = dict(solver_info, reading=parsed.reading, notes=parsed.notes[:20])
    status = "fail" if problems else ("warn" if warnings else "ok")
    entry = {"status": status, "problems": problems + warnings, "spot_sha256": sha, "street": spot["street"],
             "nodes": len(parsed.nodes), "elapsed_s": solver.get("elapsed_s"), "iterations": solver.get("iterations"),
             "exploitability_pot": solver.get("exploitability_pot"),
             "checked_exploitability_pot": checks["exploitability_pot"]}
    if problems:
        return entry
    expected = decision_nodes(spot)
    header = make_header(spot, sha, solver, len(parsed.nodes), checks)
    nodes = [parsed.nodes[k] for k in expected]  # the spot tree's order
    validate_result(header, {r["node"]: r for r in nodes}, spot, sha, expected)
    path = write_result(results_dir, header, nodes)
    entry["file"] = os.path.basename(path)
    entry["bytes"] = os.path.getsize(path)
    return entry


def solver_info_from_log(log: str, accuracy: float, settings: Mapping, version: str,
                         binary_sha256: Optional[str], elapsed_s: Optional[float]) -> dict:
    trace = ts.parse_log(log)
    last = trace[-1] if trace else (None, None)
    return {"name": "TexasSolver", "version": version, "binary_sha256": binary_sha256, "settings": dict(settings),
            "iterations": last[0], "elapsed_s": None if elapsed_s is None else round(elapsed_s, 2),
            "exploitability_pot": None if last[1] is None else round(last[1] / 100, 8),
            "exploitability_trace": [[i, v] for i, v in trace],
            "converged": last[1] is not None and last[1] <= accuracy}


def settings_of(args, spot: Mapping) -> dict:
    return {"accuracy_pct_of_pot": args.accuracy, "max_iterations": args.max_iterations,
            "print_interval": args.print_interval, "threads": args.threads or os.cpu_count(),
            "use_isomorphism": 0, "allin_threshold": ts.ALLIN_THRESHOLD,
            "raise_limit": ts.TEXASSOLVER_MAX_RAISES, "dump_rounds": len(streets_of(spot))}


def load_index(results_dir: str) -> dict:
    p = os.path.join(results_dir, INDEX)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {"spots": {}}


def save_index(results_dir: str, index: Mapping) -> None:
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, INDEX), "w") as f:
        json.dump(index, f, indent=1, sort_keys=True)
        f.write("\n")


def print_entry(spot_id: str, e: Mapping) -> None:
    ex = e.get("exploitability_pot")
    ck = e.get("checked_exploitability_pot")
    parts = [f"{spot_id:4} {e['status']:4}", f"{e.get('elapsed_s') or 0:8.1f} s", f"iter {e.get('iterations')}",
             f"TexasSolver {ex:.3%}" if ex is not None else "TexasSolver ?",
             f"ours {ck:.3%}" if ck is not None else ""]
    print("  ".join(p for p in parts if p))
    for problem in e.get("problems", []):
        print("       " + problem)


# ------------------------------------------------------------------ commands
def cmd_make_spots(args) -> int:
    paths = write_spots(SPOTS, args.spots_dir)
    print(f"Wrote {len(paths)} spots to {args.spots_dir}")
    return 0


def cmd_validate(args) -> int:
    spots = load_spots(args.spots_dir)
    bad = 0
    for spot in spots:
        path = result_path(args.results_dir, spot["id"])
        if path is None:
            continue
        try:
            header, nodes = read_result(path)
            validate_result(header, nodes, spot, spot_hash(spot), decision_nodes(spot))
            failures = check_expected(spot, nodes)
            if failures:
                raise ValueError(f"{len(failures)} expected checks fail, e.g. {failures[0]}")
        except ValueError as e:
            bad += 1
            print(f"{spot['id']}: {e}")
    solved = sum(result_path(args.results_dir, s["id"]) is not None for s in spots)
    print(f"{len(spots)} spots valid; {solved} solved, {bad} bad results")
    return 1 if bad else 0


def cmd_config(args) -> int:
    (spot,) = load_spots(args.spots_dir, [args.id])
    sys.stdout.write(ts.config_text(spot, args.dump or f"{spot['id']}.json", threads=args.threads,
                                    accuracy=args.accuracy, max_iterations=args.max_iterations,
                                    print_interval=args.print_interval))
    return 0


def cmd_solve(args) -> int:
    solver = os.path.expanduser(args.solver)
    if not os.path.isfile(solver):
        print(f"No solver at {solver}. Install TexasSolver as data/answer_keys/README.md describes.")
        return 2
    binary_sha = ts.file_sha256(solver)
    index = load_index(args.results_dir)
    failed = 0
    for spot in load_spots(args.spots_dir, args.ids or None):
        old = index["spots"].get(spot["id"])
        if (not args.force and old and old.get("status") != "fail" and old.get("spot_sha256") == spot_hash(spot)
                and result_path(args.results_dir, spot["id"])):
            print(f"{spot['id']:4} already solved (use --force to solve again)")
            continue
        print(f"{spot['id']:4} solving ...", flush=True)
        run = ts.run_solver(spot, solver, os.path.expanduser(args.workdir), cwd=args.solver_cwd,
                            timeout_s=args.timeout, threads=args.threads, accuracy=args.accuracy,
                            max_iterations=args.max_iterations, print_interval=args.print_interval)
        info = solver_info_from_log(run.log, args.accuracy, settings_of(args, spot), args.solver_version,
                                    binary_sha, run.elapsed_s)
        if run.returncode != 0 or not os.path.exists(run.dump_path):
            entry = {"status": "fail", "spot_sha256": spot_hash(spot), "elapsed_s": round(run.elapsed_s, 2),
                     "problems": [f"TexasSolver exited with {run.returncode} and no output; "
                                  f"see {os.path.join(args.workdir, spot['id'] + '.log')}"]}
        else:
            entry = save_parsed(spot, ts.parse_dump(ts.load_dump(run.dump_path), spot), info, args.results_dir,
                                args.accuracy)
            if not args.keep_dumps:
                os.remove(run.dump_path)
        index["spots"][spot["id"]] = entry
        index["solver"] = {"name": "TexasSolver", "version": args.solver_version, "binary_sha256": binary_sha}
        save_index(args.results_dir, index)
        print_entry(spot["id"], entry)
        failed += entry["status"] == "fail"
    if not args.no_report:
        write_report(args.results_dir)
    return 1 if failed else 0


def cmd_parse(args) -> int:
    (spot,) = load_spots(args.spots_dir, [args.id])
    log = open(args.log).read() if args.log else ""
    info = solver_info_from_log(log, args.accuracy, settings_of(args, spot), args.solver_version,
                                ts.file_sha256(os.path.expanduser(args.solver)) if args.solver else None, None)
    entry = save_parsed(spot, ts.parse_dump(ts.load_dump(args.dump), spot, args.reading), info,
                        args.results_dir, args.accuracy)
    index = load_index(args.results_dir)
    index["spots"][spot["id"]] = entry
    save_index(args.results_dir, index)
    print_entry(spot["id"], entry)
    return 1 if entry["status"] == "fail" else 0


def report_table(index: Mapping) -> str:
    rows = ["| Spot | Street | Status | Solve time (s) | Iterations | TexasSolver exploitability | Our check | Nodes | File |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    pct = lambda x: "" if x is None else f"{x:.3%}"  # noqa: E731
    for spot_id in sorted(index.get("spots", {})):
        e = index["spots"][spot_id]
        rows.append(f"| {spot_id} | {e.get('street', '')} | {e['status']} | {e.get('elapsed_s') or ''} | "
                    f"{e.get('iterations') or ''} | {pct(e.get('exploitability_pot'))} | "
                    f"{pct(e.get('checked_exploitability_pot'))} | {e.get('nodes', '')} | {e.get('file', '')} |")
    return "\n".join(rows)


def write_report(results_dir: str, readme: Optional[str] = None) -> None:
    readme = readme or README
    index = load_index(results_dir)
    with open(readme) as f:
        text = f.read()
    if TABLE_START not in text or TABLE_END not in text:
        print("The README has no solve table markers; not updated.")
        return
    head, rest = text.split(TABLE_START, 1)
    _, tail = rest.split(TABLE_END, 1)
    solver = index.get("solver", {})
    intro = f"TexasSolver {solver.get('version', '?')}, binary sha256 `{solver.get('binary_sha256', '?')}`.\n\n"
    with open(readme, "w") as f:
        f.write(head + TABLE_START + "\n" + intro + report_table(index) + "\n" + TABLE_END + tail)
    print(f"Updated the solve table in {readme}")


def cmd_report(args) -> int:
    write_report(args.results_dir)
    return 0


def select_spots(spots_dir: str, which: str = "all", ids: Optional[List[str]] = None) -> List[dict]:
    """The spots of a street ("river", "turn" or "all"), or just the ones named."""
    spots = load_spots(spots_dir, ids or None)
    return [s for s in spots if which == "all" or s["street"] == which]


def cmd_export_python(args) -> int:
    spots = select_spots(args.spots_dir, "all", args.ids)
    index = python_solver.export(spots, args.out, args.target, args.max_iterations)
    entries = index["spots"]
    if not entries:
        print("No river spot to solve.")
        return 2
    worst = max(entries, key=lambda k: entries[k]["checked_exploitability_pot"])
    t = index["timing"]["river"]
    print(f"{args.out} holds {len(entries)} river RESULTs: largest exploitability "
          f"{100 * entries[worst]['checked_exploitability_pot']:.4f}% of the pot ({worst}), "
          f"solve time p50 {t['solver_ms_p50']:.0f} ms, p95 {t['solver_ms_p95']:.0f} ms")
    return 0 if all(e["status"] == "ok" for e in entries.values()) else 1


def cmd_compare(args) -> int:
    results = cmp.resolve_dir(args.results)
    against = cmp.resolve_dir(args.against)
    for folder in (results, against):
        if not os.path.isdir(folder):
            print(f"No results folder at {folder}.")
            return 2
    name, against_name = (os.path.basename(os.path.normpath(d)) for d in (results, against))
    spots = select_spots(args.spots_dir, args.spots, args.ids)
    rows = cmp.compare_dirs(results, against, spots, args.turn_exploitability, args.min_reach)
    print(f"{name} against {against_name}")
    print(cmp.format_table(rows, markdown=args.markdown))
    print()
    print(cmp.legend(against_name, args.turn_exploitability, args.min_reach))
    remarks = []
    for row in rows:
        remarks += [f"{row.spot_id}: {p}" for p in row.problems]
        remarks += [f"{row.spot_id}: {n}" for n in row.notes if n != "no reference answer"]
        if args.verbose and row.freq_max_detail:
            remarks.append(f"{row.spot_id}: largest frequency difference, {row.freq_max_detail} "
                           f"(this answer/reference, %)")
    if remarks:
        print()
        print("\n".join(remarks))
    summary = cmp.summarize(rows, against_name, results)
    print()
    print("\n".join(summary.lines))
    if args.markdown:
        print()
        print(cmp.MARKDOWN_ROW_HEADER)
        print(cmp.markdown_row(name, against_name, summary))
    return 0 if summary.passed else 1


def cmd_run(args) -> int:
    solver = os.path.expanduser(args.solver)
    if not os.path.isfile(solver):
        print(f"No solver at {solver}.")
        return 2
    name = args.name or runner.default_name(solver)
    try:
        out_dir = args.out or runner.results_dir_for(name)
    except ValueError as e:
        print(e)
        return 2
    reserved = {os.path.realpath(os.path.join(cmp.KEYS_DIR, r)) for r in runner.RESERVED}
    if os.path.realpath(out_dir) in reserved:
        print(f"{out_dir} holds reference answers; run never writes there.")
        return 2
    spots = select_spots(args.spots_dir, args.spots, args.ids)
    print(f"{name}: {len(spots)} spots, {args.repeat} runs each, target {args.target:g}% of the pot")
    index = runner.run_spots(solver, spots, out_dir, name, spots_dir=args.spots_dir, target_pct=args.target,
                             repeat=args.repeat, max_iterations=args.max_iterations, time_ms=args.time_ms,
                             threads=args.threads, timeout_s=args.timeout)
    print()
    print("\n".join(runner.timing_lines(index)))
    saved = sum(e["status"] == "ok" for e in index["spots"].values())
    print(f"Saved {saved} RESULTs to {out_dir}. Check them: python -m tools.answer_keys compare {out_dir}")
    return 0 if saved == len(index["spots"]) and saved else 1


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.answer_keys", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--spots-dir", default=SPOTS_DIR)
    p.add_argument("--results-dir", default=RESULTS_DIR)
    sub = p.add_subparsers(dest="cmd", required=True)

    def solver_options(q, need_solver: bool):
        q.add_argument("--solver", required=need_solver, help="TexasSolver's console_solver binary")
        q.add_argument("--solver-version", default="console@02c8021", help="the build you installed (recorded in results)")
        q.add_argument("--accuracy", type=float, default=ts.DEFAULT_ACCURACY, help="target, percent of the pot")
        q.add_argument("--max-iterations", type=int, default=ts.DEFAULT_MAX_ITERATIONS)
        q.add_argument("--print-interval", type=int, default=ts.DEFAULT_PRINT_INTERVAL)
        q.add_argument("--threads", type=int, default=0, help="default: every core")

    sub.add_parser("make-spots").set_defaults(fn=cmd_make_spots)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    q = sub.add_parser("config")
    q.add_argument("id")
    q.add_argument("--dump", help="where the config tells TexasSolver to write its output")
    solver_options(q, False)
    q.set_defaults(fn=cmd_config)
    q = sub.add_parser("solve")
    q.add_argument("ids", nargs="*")
    solver_options(q, True)
    q.add_argument("--solver-cwd", help="folder to run it from (default: the binary's folder)")
    q.add_argument("--workdir", default="~/answer-keys/work")
    q.add_argument("--timeout", type=float, default=3600, help="seconds per spot")
    q.add_argument("--force", action="store_true")
    q.add_argument("--keep-dumps", action="store_true", help="keep TexasSolver's raw output in the workdir")
    q.add_argument("--no-report", action="store_true")
    q.set_defaults(fn=cmd_solve)
    q = sub.add_parser("parse")
    q.add_argument("id")
    q.add_argument("--dump", required=True)
    q.add_argument("--log")
    q.add_argument("--reading", choices=sorted(ts.READINGS))
    solver_options(q, False)
    q.set_defaults(fn=cmd_parse)
    sub.add_parser("report").set_defaults(fn=cmd_report)

    q = sub.add_parser("export-python", help="solve the river spots with app/solver: the Phase 2 reference answers")
    q.add_argument("ids", nargs="*", help="only these spots (default: every river spot)")
    q.add_argument("--out", default=python_solver.RESULTS_DIR)
    q.add_argument("--target", type=float, default=python_solver.REFERENCE_TARGET_PCT,
                   help="stop at this exploitability, percent of the pot")
    q.add_argument("--max-iterations", type=int, default=python_solver.MAX_ITERATIONS)
    q.set_defaults(fn=cmd_export_python)

    q = sub.add_parser("compare", help="compare a folder of RESULTs with a reference; pass/fail on the Phase 4 gates")
    q.add_argument("results", help="a folder of RESULTs, or its name in data/answer_keys")
    q.add_argument("ids", nargs="*", help="only these spots")
    q.add_argument("--against", default="texassolver",
                   help="texassolver (default), python_solver, or any folder of RESULTs")
    q.add_argument("--spots", choices=("river", "turn", "all"), default="all")
    q.add_argument("--turn-exploitability", choices=cmp.TURN_EXPLOITABILITY, default="checked",
                   help="turn spots: our own exact check (default), or the number the solver reported")
    q.add_argument("--min-reach", type=float, default=cmp.MIN_REACH,
                   help="Freq max only looks at nodes reached at least this often")
    q.add_argument("--markdown", action="store_true", help="the table in Markdown, and a row for PHASE4.md")
    q.add_argument("-v", "--verbose", action="store_true", help="also show where each spot's frequencies differ most")
    q.set_defaults(fn=cmd_compare)

    q = sub.add_parser("run", help="run a solver binary on the spots, save its RESULTs and time it")
    q.add_argument("ids", nargs="*", help="only these spots")
    q.add_argument("--solver", required=True, help="a binary that follows the subgame-solve command line")
    q.add_argument("--spots", choices=("river", "turn", "all"), default="all")
    q.add_argument("--target", type=float, default=runner.DEFAULT_TARGET_PCT,
                   help="--target-exploitability for the binary, percent of the pot")
    q.add_argument("--repeat", type=int, default=runner.DEFAULT_REPEAT, help="runs per spot")
    q.add_argument("--name", help="the results folder in data/answer_keys (default: the binary's file name)")
    q.add_argument("--out", help="save the RESULTs here instead of data/answer_keys/<name>/")
    q.add_argument("--max-iterations", type=int, help="passed on to the binary")
    q.add_argument("--time-ms", type=float, help="passed on to the binary")
    q.add_argument("--threads", type=int, help="passed on to the binary")
    q.add_argument("--timeout", type=float, default=runner.DEFAULT_TIMEOUT_S, help="seconds before a run is given up")
    q.set_defaults(fn=cmd_run)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
