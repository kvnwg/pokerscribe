"""Writes phase2_values.json: what the Phase 2 solver (app/solver) gets on every river
answer-key spot, solved to 0.1% of the pot.

The Rust test `river_values_match_the_phase_2_solver` (tests/answer_keys.rs) compares the
subgame crate's EVs with these. Run from the repository root after app/solver or the spots
change:

    python engine/crates/subgame/tests/fixtures/make_phase2_values.py

For each spot: iterations, exploitability (a share of the pot, by
app/solver/exploitability.py) and what OOP and IP win when both play the strategy.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

from app.solver import RiverSpot  # noqa: E402
from app.solver.cfr import solve  # noqa: E402
from app.solver.exploitability import exploitability  # noqa: E402

SPOTS = os.path.join(ROOT, "data", "answer_keys", "spots")
TARGET = 0.001


def main() -> None:
    out = {}
    for name in sorted(os.listdir(SPOTS)):
        with open(os.path.join(SPOTS, name)) as f:
            d = json.load(f)
        if d["street"] != "river":
            continue
        strategy = solve(RiverSpot.from_dict(d), None, max_iterations=100000, target_exploitability=TARGET)
        e = exploitability(strategy)
        assert e.pot_share <= TARGET, d["id"]
        out[d["id"]] = {"iterations": strategy.iterations, "exploitability_pot": round(e.pot_share, 8),
                        "value": [round(e.value[0], 6), round(e.value[1], 6)]}
    path = os.path.join(HERE, "phase2_values.json")
    with open(path, "w") as f:
        json.dump({"source": "app/solver solve (dcfr)", "target_exploitability": TARGET, "spots": out}, f,
                  indent=1, sort_keys=True)
        f.write("\n")
    print(f"{len(out)} river spots -> {path}")


if __name__ == "__main__":
    main()
