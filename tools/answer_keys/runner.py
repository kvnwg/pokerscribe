"""Run a solver binary on the spots, save its RESULTs and time it (docs/research/PHASE4.md).

    python -m tools.answer_keys run --solver <path to subgame-solve> [--spots river|turn|all]
                                    [--target 0.5] [--repeat 3]

The binary is a black box that follows this command line and nothing else:

    subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.3]
                  [--max-iterations N] [--time-ms N] [--threads N]

It must write the spot's RESULT (data/SPOT_FORMAT.md) to --out: the header with the solve
time (solver.elapsed_s), the iterations (solver.iterations) and the exploitability
(solver.exploitability_pot, a share of the pot), then one record per decision node. JSON
Lines is the format; one JSON array of the same records, or {"header": ..., "nodes": [...]},
is read as well, and gzip is recognised.

Each spot is run `repeat` times. The wall time is the whole process, from starting it to
its exit, so it includes start-up, reading the spot and writing the result; the solver's
own solve time is read from the header. p50 and p95 are nearest-rank percentiles over
every run of a street (app/solver/timing.percentile). The last run's RESULT is saved, with
the header's "checks" block filled in by us (python_solver.our_checks). index.json in the
results folder is rewritten by every `run` and describes that run only.

A path ending in .py is run with this Python (the stand-in, standin_solver.py).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from app.solver.timing import percentile

from .compare import GATE_RIVER_P95_MS, KEYS_DIR, solver_stats
from .python_solver import INDEX, machine, our_checks
from .result import ResultError, now, validate_result, write_result
from .spots import SPOTS_DIR, decision_nodes, spot_hash
from .texassolver import file_sha256

RESERVED = ("spots", "texassolver", "python_solver")  # folders `run` never writes to
DEFAULT_TARGET_PCT = 0.5  # the Phase 4 gate
DEFAULT_REPEAT = 3
DEFAULT_TIMEOUT_S = 600.0


def default_name(solver: str) -> str:
    """A folder name from the binary's file name: 'target/release/subgame-solve' -> 'subgame-solve'."""
    stem = os.path.splitext(os.path.basename(solver))[0]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "solver"


def results_dir_for(name: str) -> str:
    if name in RESERVED or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name.startswith("."):
        raise ValueError(f"{name!r} can't be used as a results folder (reserved: {', '.join(RESERVED)}); pick --name.")
    return os.path.join(KEYS_DIR, name)


def command(solver: str, spot_path: str, out_path: str, target_pct: Optional[float] = DEFAULT_TARGET_PCT,
            max_iterations: Optional[int] = None, time_ms: Optional[float] = None,
            threads: Optional[int] = None) -> List[str]:
    """The contract's command line for one spot."""
    cmd = ([sys.executable] if solver.endswith(".py") else []) + [solver, spot_path, "--out", out_path]
    if target_pct is not None:
        cmd += ["--target-exploitability", f"{target_pct:g}"]
    if max_iterations is not None:
        cmd += ["--max-iterations", str(int(max_iterations))]
    if time_ms is not None:
        cmd += ["--time-ms", f"{time_ms:g}"]
    if threads is not None:
        cmd += ["--threads", str(int(threads))]
    return cmd


def read_output(path: str) -> Tuple[dict, Dict[str, dict]]:
    """(header, {node key: record}) from what the binary wrote. See the module text for
    the layouts that are read."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8").strip()
    if not text:
        raise ResultError("the output file is empty.")
    records = None
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None  # more than one JSON value: JSON Lines
    if isinstance(whole, list):
        records = whole
    elif isinstance(whole, dict) and isinstance(whole.get("header"), dict) and isinstance(whole.get("nodes"), list):
        records = [whole["header"]] + whole["nodes"]
    elif isinstance(whole, dict):
        records = [whole]  # a header alone: reported below as a result with no nodes
    else:
        try:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        except ValueError as e:
            raise ResultError(f"the output isn't JSON Lines: {e}") from None
    if not records or not isinstance(records[0], dict) or records[0].get("kind") != "header":
        raise ResultError("the first record must be the header (kind: header).")
    header, nodes = records[0], {}
    for rec in records[1:]:
        if not isinstance(rec, dict) or rec.get("kind", "node") != "node" or "node" not in rec:
            raise ResultError("every record after the header is a node.")
        if rec["node"] in nodes:
            raise ResultError(f"node {rec['node']!r} is there twice.")
        nodes[rec["node"]] = dict(rec, kind="node")
    return header, nodes


def run_once(cmd: Sequence[str], out_path: str, timeout_s: float) -> Tuple[float, Optional[str]]:
    """(wall time in ms, None or what went wrong) for one run of the binary."""
    if os.path.exists(out_path):
        os.remove(out_path)
    start = time.perf_counter()
    try:
        done = subprocess.run(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return 1000.0 * (time.perf_counter() - start), f"no answer after {timeout_s:g} s"
    except OSError as e:
        return 1000.0 * (time.perf_counter() - start), f"couldn't be run: {e}"
    wall_ms = 1000.0 * (time.perf_counter() - start)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).decode("utf-8", "replace").strip().splitlines()[-3:]
        return wall_ms, f"exit status {done.returncode}" + (": " + " / ".join(tail) if tail else "")
    if not os.path.exists(out_path):
        return wall_ms, "exit status 0 but no file at --out"
    return wall_ms, None


def run_spot(solver: str, spot: Mapping, spot_path: str, out_dir: str, work_dir: str, repeat: int = DEFAULT_REPEAT,
             timeout_s: float = DEFAULT_TIMEOUT_S, **options) -> dict:
    """Run one spot `repeat` times; save the last run's RESULT; return its index entry."""
    sha, tree = spot_hash(spot), decision_nodes(spot)
    out_path = os.path.join(work_dir, spot["id"] + ".out")
    entry = {"status": "ok", "street": spot["street"], "spot_sha256": sha, "wall_ms": [], "solver_ms": [],
             "problems": []}
    last = None
    for _ in range(repeat):
        wall_ms, problem = run_once(command(solver, spot_path, out_path, **options), out_path, timeout_s)
        if problem is None:
            try:
                header, nodes = read_output(out_path)
                validate_result(header, nodes, spot, sha, tree)
            except (ValueError, KeyError, TypeError) as e:
                problem = f"its RESULT doesn't fit the spot: {e}"
        if problem is not None:
            entry["status"] = "fail"
            entry["problems"].append(problem)
            break  # a spot that fails once isn't timed further
        entry["wall_ms"].append(round(wall_ms, 3))
        ms = solver_stats(header)[0]
        if ms is not None:
            entry["solver_ms"].append(round(ms, 3))
        last = (header, nodes)
    if entry["status"] == "ok" and last is not None:
        header, nodes = last
        header = dict(header, checks=our_checks(spot, nodes))
        path = write_result(out_dir, header, [nodes[k] for k in tree])
        _, entry["iterations"], reported = solver_stats(header)
        entry["exploitability_pot"] = None if reported is None else round(reported / 100.0, 8)
        entry["checked_exploitability_pot"] = header["checks"]["exploitability_pot"]
        entry["expected_failures"] = len(header["checks"]["expected_failures"])
        entry["nodes"] = len(nodes)
        entry["file"], entry["bytes"] = os.path.basename(path), os.path.getsize(path)
    if os.path.exists(out_path):
        os.remove(out_path)
    return entry


def timing(entries: Mapping[str, Mapping]) -> Dict[str, dict]:
    """Per street: p50 and p95 of the wall time, and of the solver's own time, over every
    run that worked."""
    out = {}
    for street in ("river", "turn"):
        ok = [e for e in entries.values() if e["street"] == street and e["status"] == "ok"]
        wall = [t for e in ok for t in e["wall_ms"]]
        if not wall:
            continue
        own = [t for e in ok for t in e["solver_ms"]]
        out[street] = {"spots": len(ok), "runs": len(wall),
                       "wall_ms_p50": round(percentile(wall, 50), 3), "wall_ms_p95": round(percentile(wall, 95), 3),
                       "wall_ms_max": round(max(wall), 3)}
        if own:
            out[street].update(solver_ms_p50=round(percentile(own, 50), 3), solver_ms_p95=round(percentile(own, 95), 3))
    return out


def run_spots(solver: str, spots: Sequence[Mapping], out_dir: str, name: str, spots_dir: str = SPOTS_DIR,
              target_pct: Optional[float] = DEFAULT_TARGET_PCT, repeat: int = DEFAULT_REPEAT,
              max_iterations: Optional[int] = None, time_ms: Optional[float] = None, threads: Optional[int] = None,
              timeout_s: float = DEFAULT_TIMEOUT_S, log=print) -> dict:
    """Run the binary on every spot, save the RESULTs and index.json in out_dir, and
    return the index."""
    if repeat < 1:
        raise ValueError("repeat is at least 1.")
    entries: Dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="answer-keys-run-") as work_dir:
        for spot in spots:
            spot_path = os.path.join(spots_dir, spot["id"] + ".json")
            e = run_spot(solver, spot, spot_path, out_dir, work_dir, repeat, timeout_s, target_pct=target_pct,
                         max_iterations=max_iterations, time_ms=time_ms, threads=threads)
            entries[spot["id"]] = e
            log(entry_line(spot["id"], e))
    index = {"format": "pokerscribe-run-index", "version": 1,
             "solver": {"name": name, "file": os.path.basename(solver),
                        "binary_sha256": file_sha256(solver) if os.path.isfile(solver) else None,
                        "how": "run (one process per spot, the subgame-solve command line)"},
             "settings": {"target_exploitability_pct": target_pct, "repeat": repeat, "max_iterations": max_iterations,
                          "time_ms": time_ms, "threads": threads},
             "machine": machine(), "created": now(), "timing": timing(entries), "spots": entries}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, INDEX), "w") as f:
        json.dump(index, f, indent=1, sort_keys=True)
        f.write("\n")
    return index


def entry_line(spot_id: str, e: Mapping) -> str:
    if e["status"] != "ok":
        return f"{spot_id:4} {e['street']:5} FAIL  {e['problems'][0]}"
    wall = sorted(e["wall_ms"])
    own = sorted(e["solver_ms"])
    expl = e.get("exploitability_pot")
    parts = [f"{spot_id:4} {e['street']:5} ok  ", f"wall {percentile(wall, 50):9.1f} ms",
             f"solver {percentile(own, 50):9.1f} ms" if own else "solver         ? ms",
             f"iter {e.get('iterations') if e.get('iterations') is not None else '?':>6}",
             f"reported {100 * expl:.3f}%" if expl is not None else "reported ?"]
    if e.get("expected_failures"):
        parts.append(f"{e['expected_failures']} expected checks fail")
    return "  ".join(parts)


def timing_lines(index: Mapping) -> List[str]:
    """What `run` prints at the end: p50 and p95 per street, and the river time gate."""
    lines = []
    for street, t in index.get("timing", {}).items():
        own = (f"; the solver's own solve time: p50 {t['solver_ms_p50']:.1f} ms, p95 {t['solver_ms_p95']:.1f} ms"
               if "solver_ms_p50" in t else "")
        lines.append(f"{street}: wall time p50 {t['wall_ms_p50']:.1f} ms, p95 {t['wall_ms_p95']:.1f} ms, "
                     f"max {t['wall_ms_max']:.1f} ms over {t['runs']} runs of {t['spots']} spots{own}")
    river = index.get("timing", {}).get("river")
    if river:
        ok = river["wall_ms_p95"] < GATE_RIVER_P95_MS
        lines.append(f"River p95 under {GATE_RIVER_P95_MS:g} ms (wall time): {'PASS' if ok else 'FAIL'}")
    failed = [k for k, e in index["spots"].items() if e["status"] != "ok"]
    if failed:
        lines.append(f"{len(failed)} of {len(index['spots'])} spots failed: {' '.join(failed[:12])}"
                     + (" ..." if len(failed) > 12 else ""))
    return lines
