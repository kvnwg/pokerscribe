"""The pre-registered AIVAT checks (docs/research/experiments.md, "Phase 7: AIVAT in the
arena"). Run from the repository root with the Rust module installed:

    python docs/research/runs/phase7_aivat/run.py 1a 1b 1c 2a 2b 3 4

Each run saves the arena's report as <id>.json next to this file and prints its summary.
The strategy files are the 20bb standard-k200 run of this container (B below).
"""
import json
import os
import sys
import time

import pokerscribe_engine as pe

HERE = os.path.dirname(os.path.abspath(__file__))
B = "/root/bp/standard-k200/strategy-%d.bps"
M4, M16, M64 = (f"blueprint:{B % n}" for n in (4_000_000, 16_000_000, 64_000_000))
# A second copy of the 64M file under another name: the arena needs two agents.
M64_COPY = f"blueprint:{B % 64_000_000}?tables=/root/abstraction/k200"
SEARCH = f"search:{B % 64_000_000}"

RUNS = {
    "1a": ([M64, M64_COPY], 1_000_000, 7501),
    "1b": ([M64, M64_COPY], 1_000_000, 7502),
    "1c": (["tag", "tag"], 1_000_000, 7503),
    "2a": ([M16, M64], 1_000_000, 7511),
    "2b": ([M4, M64], 1_000_000, 7512),
    "3": (["tag", M64], 200_000, 7531),
    "4": ([M64, SEARCH], 500, 7521),
}


def main(ids):
    for rid in ids:
        agents, deals, seed = RUNS[rid]
        t = time.time()
        report = pe.run_match(agents, deals, seed, stack=2000, small_blind=50, big_blind=100,
                              threads=4)
        d = report.to_dict()
        d["wall_seconds"] = time.time() - t
        with open(os.path.join(HERE, f"{rid}.json"), "w") as f:
            json.dump(d, f, indent=1)
        print(f"== {rid}: {agents[1]} against {agents[0]}, {deals} deals, seed {seed}, "
              f"{d['wall_seconds']:.0f} s")
        print(report.summary(), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
