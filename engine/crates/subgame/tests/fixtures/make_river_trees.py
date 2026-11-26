"""Writes river_trees.json: the tree app/solver/tree.py builds for every river answer-key spot.

The Rust test `river_trees_match_app_solver` (tests/answer_keys.rs) compares the subgame
crate's tree with it, node by node. Run from the repository root after tree.py or the spots
change:

    python engine/crates/subgame/tests/fixtures/make_river_trees.py

For each spot: every node in the order GameTree made it, as
[key, player (-1 at a terminal), actions, terminal ("", "fold" or "showdown"), folder, put_in].
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

from app.solver import GameTree, RiverSpot  # noqa: E402

SPOTS = os.path.join(ROOT, "data", "answer_keys", "spots")


def main() -> None:
    out = {}
    for name in sorted(os.listdir(SPOTS)):
        with open(os.path.join(SPOTS, name)) as f:
            d = json.load(f)
        if d["street"] != "river":
            continue
        tree = GameTree(RiverSpot.from_dict(d))
        out[d["id"]] = [[n.key, n.player, list(n.actions), n.terminal, n.folder, list(n.put_in)]
                        for n in tree.nodes.values()]
    path = os.path.join(HERE, "river_trees.json")
    with open(path, "w") as f:
        json.dump({"source": "app/solver/tree.py GameTree", "spots": out}, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    print(f"{len(out)} river trees, {sum(len(v) for v in out.values())} nodes -> {path}")


if __name__ == "__main__":
    main()
