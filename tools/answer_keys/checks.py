"""Checks on a solved spot that don't trust the solver that made it.

- check_expected: the "expected" list of a spot (the trivial spots have one), e.g. "at
  every node facing a bet, nobody folds".
- river_exploitability: for a river spot, the exploitability of the answer worked out by
  app/solver/exploitability.py, our own exact best response. TexasSolver reports its own
  number; this one is independent of it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Mapping, Tuple

import numpy as np

from app.solver.exploitability import exploitability
from app.solver.spot import PLAYER_NAMES, combo_text
from app.solver.strategy import RiverStrategy
from app.solver.tree import GameTree

from .result import node_record
from .spots import river_spot


def kind_share(row: Mapping[str, float], kind: str) -> float:
    """How often a combo takes any action of this kind: x, c, f, b (any bet), r (any raise)."""
    return sum(p for a, p in row.items() if a[:1] == kind)


def check_expected(spot: Mapping, nodes: Mapping[str, Mapping]) -> List[str]:
    """Every way the result breaks the spot's expected checks (an empty list passes)."""
    failures = []
    for check in spot.get("expected", []):
        pattern = re.compile(check["nodes"])
        matched = [rec for key, rec in nodes.items()
                   if pattern.search(key) and check["actor"] in ("any", rec["actor"])]
        if not matched:
            failures.append(f"no {check['actor']} node matches {check['nodes']!r}")
            continue
        for rec in matched:
            for combo, row in rec["strategy"].items():
                share = kind_share(row, check["action"])
                if "min" in check and share < check["min"]:
                    failures.append(f"{rec['node']!r} {combo}: {check['action']} {share:.3f} < {check['min']}")
                if "max" in check and share > check["max"]:
                    failures.append(f"{rec['node']!r} {combo}: {check['action']} {share:.3f} > {check['max']}")
    return failures


def river_strategy(spot: Mapping, nodes: Mapping[str, Mapping]) -> Tuple[RiverStrategy, int]:
    """The answer as a RiverStrategy on app/solver's own tree of the spot. A combo the
    answer leaves out at a node gets a uniform row; the count of those rows comes back too."""
    rs = river_spot(spot)
    tree = GameTree(rs)
    probs, filled = {}, 0
    for node in tree.decision_nodes():
        rec = nodes[node.key]
        if tuple(rec["actions"]) != node.actions:
            raise ValueError(f"{node.key!r}: actions {rec['actions']} differ from {list(node.actions)}.")
        rows = []
        for combo in rs.combos(node.player):
            row = rec["strategy"].get(combo_text(combo))
            if row is None:
                filled += 1
                rows.append([1.0 / len(node.actions)] * len(node.actions))
            else:
                p = np.array([max(0.0, float(row[a])) for a in node.actions])
                rows.append(p / p.sum() if p.sum() > 0 else np.full(len(p), 1.0 / len(p)))
        probs[node.key] = np.array(rows, dtype=float)
    return RiverStrategy(rs, probs, tree), filled


def river_exploitability(spot: Mapping, nodes: Mapping[str, Mapping]) -> Tuple[float, int]:
    """(exploitability as a share of the pot, rows filled in uniformly)."""
    strategy, filled = river_strategy(spot, nodes)
    return exploitability(strategy).pot_share, filled


def nodes_from_river_strategy(strategy: RiverStrategy) -> Dict[str, dict]:
    """Result node records from one of app/solver's own river strategies (for tests, and
    to compare our solver with an answer key)."""
    out = {}
    spot = strategy.spot
    for node in strategy.tree.decision_nodes():
        rows = {combo_text(c): dict(zip(node.actions, strategy.probs[node.key][i]))
                for i, c in enumerate(spot.combos(node.player))}
        out[node.key] = node_record(node.key, PLAYER_NAMES[node.player], node.actions, rows)
    return out
