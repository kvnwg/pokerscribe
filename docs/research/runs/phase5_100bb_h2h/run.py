"""Runs the head-to-head plan (plan.md here has the rules) and writes one line per match.

    python docs/research/runs/phase5_100bb_h2h/run.py docs/research/runs/phase5_100bb_h2h/plan.json OUT.jsonl

Needs `pokerscribe_engine` (`python -m pip install ./engine/crates/py`) and the strategy files
named in plan.json, which are checked against their sha256. A match already in OUT.jsonl is
not played again.
"""
import hashlib
import json
import os
import sys
import time

import pokerscribe_engine as pe


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    plan_path, out = sys.argv[1], sys.argv[2]
    plan = json.load(open(plan_path))
    for name, f in plan["files"].items():
        got = sha256(f["path"])
        if got != f["sha256"]:
            sys.exit(f"{name}: {f['path']} has sha256 {got}, not the plan's {f['sha256']}")
    done = set()
    if os.path.exists(out):
        done = {json.loads(line)["name"] for line in open(out) if line.strip()}
    g, ar = plan["game"], plan["arena"]
    for m in plan["matches"]:
        if m["name"] in done:
            continue
        agents = ["blueprint:" + plan["files"][m["a"]]["path"], "blueprint:" + plan["files"][m["b"]]["path"]]
        start = time.time()
        report = pe.run_match(agents, m["deals"], m["seed"], players=g["players"], stack=g["stack"],
                              small_blind=g["small_blind"], big_blind=g["big_blind"],
                              duplicate=ar["duplicate"], all_in_equity=ar["all_in_equity"],
                              max_runouts=ar["max_runouts"], shared_randomness=ar["shared_randomness"],
                              threads=ar["threads"]).to_dict()
        line = dict(m, wall_seconds=time.time() - start, report=report)
        with open(out, "a") as f:
            f.write(json.dumps(line) + "\n")
        b = report["results"][1]
        print(f"{m['name']}: {m['b']} against {m['a']}: {b['bb_per_100']:+.2f} +- {b['se']:.2f} bb/100 "
              f"({m['deals']:,} deals, {line['wall_seconds']:.0f} s, illegal actions "
              f"{[r['illegal_actions'] for r in report['results']]})", flush=True)


if __name__ == "__main__":
    main()
