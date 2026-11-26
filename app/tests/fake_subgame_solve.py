#!/usr/bin/env python3
"""A stand-in for the Rust program `subgame-solve`, for the tests of
app/solver/rust_backend.py. It is not a test file itself.

It follows the program's command line and its two file formats (data/SPOT_FORMAT.md):

    subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.3]
                  [--max-iterations N] [--time-ms N] [--threads N]

--target-exploitability is in percent of the pot. The answer is the Python river solver's,
so the RESULT is a real solution of the spot, written as the format says (JSON Lines, a
header and one line per decision node, probabilities rounded to 6 decimals). Without --out
the RESULT goes to standard output.

Three environment variables are for the tests only:

- FAKE_SUBGAME_MODE: misbehave on purpose, one of MODES below ("ok" when not set);
- FAKE_SUBGAME_LOG: a file to which each call appends its arguments, one JSON line a call;
- FAKE_SUBGAME_MAX_ITERATIONS: never run more iterations than this, whatever was asked.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MODES = (
    "ok",
    "crash",  # exit with an error code and a message, write nothing
    "no-output",  # exit 0 without writing a result
    "garbage",  # write something that is not JSON
    "slow",  # sleep FAKE_SUBGAME_SLEEP_S seconds (5) before doing anything
    "other-spot",  # the header names another spot
    "wrong-tree",  # one action of the first node has another amount
    "missing-node",  # the last node is left out
    "missing-combo",  # one combo is left out of the first node
    "bad-sum",  # one combo's probabilities add up to more than 1
    "gzip",  # the result is gzipped (the format allows it for big results)
    "sorted-keys",  # every JSON object has its keys in alphabetical order
    "no-solver-numbers",  # the header says nothing about iterations or exploitability
    "target-is-a-share",  # --target-exploitability read as a share of the pot, not percent
)
DIGITS = 6


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="subgame-solve", description="Stand-in for the Rust subgame solver.")
    ap.add_argument("spot", help="a SPOT file (data/SPOT_FORMAT.md)")
    ap.add_argument("--out", help="where to write the RESULT (standard output when left out)")
    ap.add_argument("--target-exploitability", type=float, default=0.3, help="percent of the pot")
    ap.add_argument("--max-iterations", type=int)
    ap.add_argument("--time-ms", type=int)
    ap.add_argument("--threads", type=int)
    args = ap.parse_args(argv)

    mode = os.environ.get("FAKE_SUBGAME_MODE", "ok")
    if mode not in MODES:
        print(f"unknown FAKE_SUBGAME_MODE {mode!r}", file=sys.stderr)
        return 2
    if os.environ.get("FAKE_SUBGAME_LOG"):
        with open(os.environ["FAKE_SUBGAME_LOG"], "a") as f:
            f.write(json.dumps({"argv": list(sys.argv[1:] if argv is None else argv), "mode": mode}) + "\n")
    if mode == "crash":
        print("warming up\nthread 'main' panicked: made to fail by FAKE_SUBGAME_MODE", file=sys.stderr)
        return 101
    if mode == "no-output":
        return 0
    if mode == "slow":
        time.sleep(float(os.environ.get("FAKE_SUBGAME_SLEEP_S", "5")))

    with open(args.spot) as f:
        spot_doc = json.load(f)
    if spot_doc.get("format") != "pokerscribe-spot" or spot_doc.get("version") != 1:
        print("not a pokerscribe-spot version 1 file", file=sys.stderr)
        return 2
    if spot_doc.get("street") != "river":
        print("this stand-in only solves river spots", file=sys.stderr)
        return 2

    from app.solver import GameTree, RiverSpot, solve_river
    from app.solver.spot import PLAYER_NAMES, combo_text

    spot = RiverSpot.from_dict(spot_doc)
    max_iterations = args.max_iterations
    cap = os.environ.get("FAKE_SUBGAME_MAX_ITERATIONS")
    if cap:
        max_iterations = min(int(cap), max_iterations or int(cap))
    target = args.target_exploitability if mode == "target-is-a-share" else args.target_exploitability / 100.0
    strategy = solve_river(spot, args.time_ms, max_iterations=max_iterations, target_exploitability=target)

    canonical = json.dumps(spot_doc, sort_keys=True, separators=(",", ":"))
    solver = {"name": "fake-subgame-solve", "version": "python",
              "settings": {"target_exploitability_pct": args.target_exploitability,
                           "max_iterations": args.max_iterations, "time_ms": args.time_ms, "threads": args.threads},
              "iterations": strategy.iterations, "elapsed_s": round(strategy.elapsed_ms / 1000.0, 6),
              "exploitability_pot": strategy.exploitability,
              "converged": strategy.exploitability <= target}
    if mode == "no-solver-numbers":
        solver = {"name": "fake-subgame-solve"}
    tree = GameTree(spot)
    nodes = []
    for node in tree.decision_nodes():
        rows = strategy.probs[node.key]
        nodes.append({"kind": "node", "node": node.key, "actor": PLAYER_NAMES[node.player],
                      "actions": list(node.actions),
                      "strategy": {combo_text(c): {a: round(float(p), DIGITS) for a, p in zip(node.actions, rows[i])}
                                   for i, c in enumerate(spot.combos(node.player))}})
    header = {"format": "pokerscribe-answer-key", "version": 1, "kind": "header", "label_source": "solver",
              "spot_id": spot_doc["id"], "spot_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
              "street": "river", "solver": solver, "checks": {}, "nodes": len(nodes),
              "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    first = nodes[0]
    if mode == "other-spot":
        header["spot_id"] = "r01"
    elif mode == "wrong-tree":
        old = first["actions"][-1]
        new = old + "9"
        first["actions"][-1] = new
        first["strategy"] = {c: {(new if a == old else a): p for a, p in row.items()}
                             for c, row in first["strategy"].items()}
    elif mode == "missing-node":
        nodes.pop()
    elif mode == "missing-combo":
        first["strategy"].pop(next(iter(first["strategy"])))
    elif mode == "bad-sum":
        row = first["strategy"][next(iter(first["strategy"]))]
        for a in row:
            row[a] = 0.9

    sort = mode == "sorted-keys"
    text = "".join(json.dumps(rec, separators=(",", ":"), sort_keys=sort) + "\n" for rec in [header] + nodes)
    data = b"this is not a result\n" if mode == "garbage" else text.encode()
    if mode == "gzip":
        data = gzip.compress(data)
    if args.out:
        with open(args.out, "wb") as f:
            f.write(data)
    else:
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
