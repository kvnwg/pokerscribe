"""A river strategy: for every decision node, each combo of the player to act has a
probability for each action there."""
from __future__ import annotations

from typing import Callable, Dict, Mapping, Optional, Sequence, Union

import numpy as np

from .spot import Combo, RiverSpot
from .tree import GameTree, Node, describe_action

# rule(node, combo) -> {action token: probability} or a list in the node's action order
Rule = Callable[[Node, Combo], Union[Mapping[str, float], Sequence[float]]]


def describe_mix(probs: Mapping[str, float]) -> str:
    """'bet 75 60%, check 40%' from {action token: probability} (most likely first, under
    0.5% left out)."""
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{describe_action(a)} {int(round(100 * p))}%" for a, p in ranked if p >= 0.005)


class RiverStrategy:
    """probs[node key] is an array shaped (combos of the acting player, actions at the node).
    Rows are probabilities: non-negative, adding up to 1.

    iterations, elapsed_ms: filled in by the solver. exploitability: its own check, as a
    share of the pot, when it worked one out."""

    def __init__(self, spot: RiverSpot, probs: Mapping[str, np.ndarray], tree: Optional[GameTree] = None,
                 iterations: int = 0, elapsed_ms: float = 0.0, exploitability: Optional[float] = None):
        self.spot = spot
        self.tree = tree if tree is not None else GameTree(spot)
        self.probs: Dict[str, np.ndarray] = {k: np.asarray(v, dtype=float) for k, v in probs.items()}
        self.iterations = iterations
        self.elapsed_ms = elapsed_ms
        self.exploitability = exploitability
        self.validate()

    def validate(self, tol: float = 1e-6) -> None:
        for node in self.tree.decision_nodes():
            p = self.probs.get(node.key)
            n = len(self.spot.range(node.player))
            if p is None:
                raise ValueError(f"No strategy at node {node.key!r}.")
            if p.shape != (n, len(node.actions)):
                raise ValueError(f"Node {node.key!r}: expected shape {(n, len(node.actions))}, got {p.shape}.")
            if not np.all(np.isfinite(p)) or np.any(p < -tol):
                raise ValueError(f"Node {node.key!r}: probabilities must be finite and not negative.")
            if np.any(np.abs(p.sum(axis=1) - 1.0) > tol):
                raise ValueError(f"Node {node.key!r}: each combo's probabilities must add up to 1.")
        extra = set(self.probs) - {n.key for n in self.tree.decision_nodes()}
        if extra:
            raise ValueError(f"Strategy for nodes that aren't in the tree: {sorted(extra)[:3]}")

    # ---------------------------------------------------------------- build
    @classmethod
    def uniform(cls, spot: RiverSpot, tree: Optional[GameTree] = None) -> "RiverStrategy":
        tree = tree or GameTree(spot)
        probs = {n.key: np.full((len(spot.range(n.player)), len(n.actions)), 1.0 / len(n.actions))
                 for n in tree.decision_nodes()}
        return cls(spot, probs, tree)

    @classmethod
    def from_rule(cls, spot: RiverSpot, rule: Rule, tree: Optional[GameTree] = None, **kw) -> "RiverStrategy":
        """Build a strategy from a function of (node, combo). A mapping may leave actions
        out (they get 0); probabilities are used as given, so they must add up to 1."""
        tree = tree or GameTree(spot)
        probs = {}
        for node in tree.decision_nodes():
            rows = []
            for combo in spot.combos(node.player):
                got = rule(node, combo)
                if isinstance(got, Mapping):
                    unknown = set(got) - set(node.actions)
                    if unknown:
                        raise ValueError(f"Node {node.key!r} has no action {sorted(unknown)[0]!r}.")
                    rows.append([float(got.get(a, 0.0)) for a in node.actions])
                else:
                    rows.append([float(x) for x in got])
            probs[node.key] = np.array(rows, dtype=float).reshape(-1, len(node.actions))
        return cls(spot, probs, tree, **kw)

    # ---------------------------------------------------------------- read
    def action_probs(self, key: str, combo: Sequence[str]) -> Dict[str, float]:
        node = self.tree[key]
        row = self.probs[key][self.spot.index(node.player, combo)]
        return {a: float(p) for a, p in zip(node.actions, row)}

    def reach(self, player: int) -> Dict[str, np.ndarray]:
        """For every node: the chance that each of the player's combos gets there, counting
        only that player's own choices (the other player's are left out)."""
        n = len(self.spot.range(player))
        out = {"": np.ones(n)}
        stack = [""]
        while stack:
            key = stack.pop()
            node = self.tree[key]
            for i, child in enumerate(node.children):
                r = out[key]
                if node.player == player:
                    r = r * self.probs[key][:, i]
                out[child] = r
                if not self.tree[child].is_terminal:
                    stack.append(child)
        return out

    def frequencies(self, key: str) -> Dict[str, float]:
        """How often the player at this node takes each action, over the combos that get
        there (weighted by range weight and the player's own reach)."""
        node = self.tree[key]
        w = self.spot.weights(node.player) * self.reach(node.player)[key]
        total = w.sum()
        if total <= 0:
            return {a: 0.0 for a in node.actions}
        f = w @ self.probs[key] / total
        return {a: float(x) for a, x in zip(node.actions, f)}

    def describe(self, key: str, combo: Sequence[str]) -> str:
        """'bet 75 60%, check 40%' (most likely first, under 0.5% left out)."""
        return describe_mix(self.action_probs(key, combo))

    def __repr__(self) -> str:
        return (f"RiverStrategy({' '.join(self.spot.board)}, pot {self.spot.pot:g}, {len(self.tree)} nodes, "
                f"{self.iterations} iterations)")
