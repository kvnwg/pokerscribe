"""The RESULT format: one solved spot, as JSON Lines (data/SPOT_FORMAT.md, "RESULT").

Line 1 is the header; every other line is one decision node:

    {"format": "pokerscribe-answer-key", "version": 1, "kind": "header",
     "label_source": "solver", "spot_id": "r04", "spot_sha256": "...", "street": "river",
     "solver": {"name": "TexasSolver", "version": "0.2.0", "binary_sha256": "...",
                "settings": {...}, "iterations": 120, "elapsed_s": 3.2,
                "exploitability_pot": 0.0027, "converged": true},
     "checks": {"exploitability_pot": 0.0026, "expected_failures": []},
     "nodes": 8, "created": "2026-11-26T12:00:00Z"}
    {"kind": "node", "node": "x b75", "actor": "oop", "actions": ["f", "c", "r150"],
     "strategy": {"AhKd": {"f": 0.0, "c": 0.8, "r150": 0.2}, ...}}

The node and strategy fields are the ones app/solver/labels.py uses, so a river answer key
node reads the same as a solver label of that node.
"""
from __future__ import annotations

import datetime as _dt
import gzip
import io
import json
import os
from typing import Dict, Iterable, Mapping, Optional, Tuple

FORMAT = "pokerscribe-answer-key"
VERSION = 1
GZIP_OVER_BYTES = 1_000_000  # results bigger than this are saved as .jsonl.gz
DIGITS = 6  # probabilities are rounded to this many decimals


class ResultError(ValueError):
    pass


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_header(spot: Mapping, spot_sha256: str, solver: Mapping, n_nodes: int,
                checks: Optional[Mapping] = None, created: Optional[str] = None) -> dict:
    return {"format": FORMAT, "version": VERSION, "kind": "header", "label_source": "solver",
            "spot_id": spot["id"], "spot_sha256": spot_sha256, "street": spot["street"],
            "solver": dict(solver), "checks": dict(checks or {}), "nodes": n_nodes,
            "created": created or now()}


def node_record(key: str, actor: str, actions, strategy: Mapping[str, Mapping[str, float]]) -> dict:
    return {"kind": "node", "node": key, "actor": actor, "actions": list(actions),
            "strategy": {c: {a: round(float(p), DIGITS) for a, p in row.items()} for c, row in strategy.items()}}


def encode(header: Mapping, nodes: Iterable[Mapping]) -> bytes:
    buf = io.StringIO()
    buf.write(json.dumps(header, separators=(",", ":")) + "\n")
    for rec in nodes:
        buf.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return buf.getvalue().encode()


def write_result(results_dir: str, header: Mapping, nodes: Iterable[Mapping],
                 gzip_over: int = GZIP_OVER_BYTES) -> str:
    """Save as <spot_id>.jsonl, or <spot_id>.jsonl.gz when it is bigger than gzip_over
    bytes. The other spelling, if there is one from an earlier run, is removed."""
    os.makedirs(results_dir, exist_ok=True)
    data = encode(header, nodes)
    base = os.path.join(results_dir, header["spot_id"] + ".jsonl")
    path, other = (base + ".gz", base) if len(data) > gzip_over else (base, base + ".gz")
    if path.endswith(".gz"):
        with gzip.GzipFile(path, "wb", mtime=0) as f:  # mtime 0: the same answer gives the same bytes
            f.write(data)
    else:
        with open(path, "wb") as f:
            f.write(data)
    if os.path.exists(other):
        os.remove(other)
    return path


def result_path(results_dir: str, spot_id: str) -> Optional[str]:
    for name in (spot_id + ".jsonl", spot_id + ".jsonl.gz"):
        p = os.path.join(results_dir, name)
        if os.path.exists(p):
            return p
    return None


def read_result(path: str) -> Tuple[dict, Dict[str, dict]]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    if not lines or lines[0].get("kind") != "header":
        raise ResultError(f"{path}: the first line must be the header.")
    header = lines[0]
    nodes = {}
    for rec in lines[1:]:
        if rec.get("kind") != "node":
            raise ResultError(f"{path}: every line after the header is a node.")
        if rec["node"] in nodes:
            raise ResultError(f"{path}: node {rec['node']!r} is there twice.")
        nodes[rec["node"]] = rec
    return header, nodes


def validate_result(header: Mapping, nodes: Mapping[str, Mapping], spot: Mapping, spot_sha256: str,
                    expected_nodes: Mapping, tol: float = 1e-4) -> None:
    """Raise ResultError unless the result fits the spot: same hash, the same decision
    nodes with the same actions and actors, and every row of probabilities adding up to 1."""
    if header.get("format") != FORMAT or header.get("version") != VERSION:
        raise ResultError(f"Not a {FORMAT} version {VERSION} result.")
    if header.get("label_source") != "solver":
        raise ResultError("label_source must be 'solver'.")
    if header.get("spot_id") != spot["id"]:
        raise ResultError(f"The result is for {header.get('spot_id')!r}, not {spot['id']!r}.")
    if header.get("spot_sha256") != spot_sha256:
        raise ResultError(f"{spot['id']}: the spot changed since it was solved; solve it again.")
    if set(nodes) != set(expected_nodes):
        missing = sorted(set(expected_nodes) - set(nodes))[:3]
        extra = sorted(set(nodes) - set(expected_nodes))[:3]
        raise ResultError(f"{spot['id']}: nodes differ from the spot's tree (missing {missing}, extra {extra}).")
    for key, rec in nodes.items():
        want = expected_nodes[key]
        if tuple(rec["actions"]) != tuple(want.actions) or rec["actor"] != want.actor:
            raise ResultError(f"{spot['id']} {key!r}: actions or actor differ from the spot's tree.")
        for combo, row in rec["strategy"].items():
            if set(row) != set(rec["actions"]):
                raise ResultError(f"{spot['id']} {key!r} {combo}: not one probability per action.")
            if any(p < -tol for p in row.values()) or abs(sum(row.values()) - 1.0) > tol:
                raise ResultError(f"{spot['id']} {key!r} {combo}: probabilities don't add up to 1.")
