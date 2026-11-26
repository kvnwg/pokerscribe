"""Solver-labelled river decisions, saved for later (training and testing data).

One JSON object per line (JSON Lines), so files can be appended to and streamed. A record
is one decision node of one solved spot, with the solver's strategy there for the combos
of the player to act:

    {
      "format": "pokerscribe-river-label", "version": 1, "label_source": "solver",
      "source": "synthetic:seed=1:spot=3",      where the spot came from (or "phh:<hand_uid>")
      "spot": {...},                            RiverSpot.to_dict(): board, pot, stacks, ranges, sizes
      "node": "x b75",                          the actions before this decision (tree.py)
      "actor": "oop",                           who decides: "oop" or "ip"
      "strategy": {"QhQd": {"f": 0.4, "c": 0.6}, ...},   every action of the node, adding up to 1
      "values": {"QhQd": 31.5, ...} or null,    optional: chips each combo expects from here
      "held": "QhQd" or null,                   the combo actually held, for a recorded hand
      "observed": {"action": "c", ...} or null, what the player actually did
      "solver": {"name": ..., "version": ..., "time_budget_ms": ..., "elapsed_ms": ...,
                 "iterations": ..., "exploitability_pot": ...},
      "created": "2026-11-26T12:00:00Z"
    }

The label is "strategy". "observed" is only an observation, never a label of correct play
(rule 3 in docs/research/README.md).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from typing import Iterable, Iterator, Mapping, Optional, Sequence

from .spot import PLAYER_NAMES, RiverSpot, combo_text, parse_combo
from .strategy import RiverStrategy
from .tree import GameTree

FORMAT = "pokerscribe-river-label"
VERSION = 1
SOLVER_NAME = "pokerscribe-river"
SOLVER_VERSION = "0"  # bump whenever the solver's answers can change


def make_label(strategy: RiverStrategy, node: str, source: str, combos: Optional[Sequence] = None,
               held=None, observed: Optional[Mapping] = None, values: Optional[Mapping] = None,
               time_budget_ms: Optional[float] = None, created: Optional[str] = None) -> dict:
    """A record for one node. combos: which of the actor's combos to include (default:
    every combo that can reach the node by its own choices)."""
    spot, tree = strategy.spot, strategy.tree
    n = tree[node]
    if n.is_terminal:
        raise ValueError(f"{node!r} is the end of the hand, not a decision.")
    if combos is None:
        reach = strategy.reach(n.player)[node]
        combos = [c for c, r in zip(spot.combos(n.player), reach) if r > 1e-9]
    out = {
        "format": FORMAT, "version": VERSION, "label_source": "solver",
        "source": source,
        "spot": spot.to_dict(),
        "node": node,
        "actor": PLAYER_NAMES[n.player],
        "strategy": {combo_text(parse_combo(c)): strategy.action_probs(node, c) for c in combos},
        "values": dict(values) if values is not None else None,
        "held": combo_text(parse_combo(held)) if held is not None else None,
        "observed": dict(observed) if observed is not None else None,
        "solver": {"name": SOLVER_NAME, "version": SOLVER_VERSION, "time_budget_ms": time_budget_ms,
                   "elapsed_ms": strategy.elapsed_ms, "iterations": strategy.iterations,
                   "exploitability_pot": strategy.exploitability},
        "created": created or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    validate_label(out)
    return out


def validate_label(rec: Mapping) -> None:
    """Raise ValueError when a record doesn't follow the format."""
    if rec.get("format") != FORMAT or rec.get("version") != VERSION:
        raise ValueError(f"Not a {FORMAT} version {VERSION} record.")
    if rec.get("label_source") != "solver":
        raise ValueError("label_source must be 'solver': recorded actions are never labels.")
    for key in ("source", "spot", "node", "actor", "strategy", "solver", "created"):
        if key not in rec:
            raise ValueError(f"Missing {key!r}.")
    spot = RiverSpot.from_dict(rec["spot"])
    tree = GameTree(spot)
    if rec["node"] not in tree or tree[rec["node"]].is_terminal:
        raise ValueError(f"{rec['node']!r} isn't a decision in this spot's tree.")
    node = tree[rec["node"]]
    if rec["actor"] != PLAYER_NAMES[node.player]:
        raise ValueError(f"At {rec['node']!r} the {PLAYER_NAMES[node.player]} player acts, not {rec['actor']!r}.")
    in_range = {combo_text(c) for c in spot.combos(node.player)}
    if not rec["strategy"]:
        raise ValueError("The strategy has no combos.")
    for combo, probs in rec["strategy"].items():
        if combo not in in_range:
            raise ValueError(f"{combo} isn't in the {rec['actor']} range.")
        if set(probs) != set(node.actions):
            raise ValueError(f"{combo}: the actions must be exactly {list(node.actions)}.")
        vals = [float(p) for p in probs.values()]
        if any(not math.isfinite(p) or p < -1e-9 for p in vals) or abs(sum(vals) - 1.0) > 1e-6:
            raise ValueError(f"{combo}: probabilities must be 0 or more and add up to 1.")
    if rec.get("values") is not None and set(rec["values"]) - set(rec["strategy"]):
        raise ValueError("values has combos that aren't in the strategy.")
    if rec.get("held") is not None and rec["held"] not in in_range:
        raise ValueError(f"The held combo {rec['held']} isn't in the {rec['actor']} range.")


def write_labels(path: str, records: Iterable[Mapping], append: bool = True) -> int:
    """Write records as JSON Lines; returns how many were written. The file is opened at
    the first record, so nothing is created when there is none."""
    n = 0
    f = None
    try:
        for rec in records:
            validate_label(rec)
            if f is None:
                f = open(path, "a" if append else "w", encoding="utf-8")
            f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
            n += 1
    finally:
        if f is not None:
            f.close()
    return n


def read_labels(path: str) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            try:
                validate_label(rec)
            except ValueError as e:
                raise ValueError(f"{path} line {i}: {e}") from None
            yield rec
