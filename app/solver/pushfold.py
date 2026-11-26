"""Heads-up push-or-fold (jam-or-fold): the small blind goes all in or folds, the big blind
calls or folds. The Mathematics of Poker (Chen and Ankenman) solves this game and finds
it close to optimal play up to about 10 big blinds (KNOWLEDGE.md).

solve_push_fold(stack_bb) returns the equilibrium: for each of the 169 starting hands, how
often the small blind jams and how often the big blind calls. It is solved with the same
regret minimisation as the river (Discounted CFR or CFR+), on exact all-in equities with
card removal (app/solver/data/preflop_equity.npz, built by tools/build_preflop_equity.py),
and checked the same way: exploitability is what a perfect counter-strategy gains.

Units: big blinds. stack_bb is the smaller stack before the blinds are posted, as in the
published charts. Results are per hand for the small blind, blinds included:
fold = -0.5, jam and they fold = +1, jam and called = stack x (2 x equity - 1).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Sequence, Tuple

import numpy as np

RANKS_HIGH = "AKQJT98765432"
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "preflop_equity.npz")


def _grid_classes() -> List[str]:
    """The 169 starting hands in chart order: rows and columns A to 2, pairs on the
    diagonal, suited hands above it, offsuit hands below."""
    out = []
    for i, a in enumerate(RANKS_HIGH):
        for j, b in enumerate(RANKS_HIGH):
            out.append(a + b if i == j else (a + b + "s" if i < j else b + a + "o"))
    return out


CLASSES: List[str] = _grid_classes()
CLASS_INDEX: Dict[str, int] = {c: i for i, c in enumerate(CLASSES)}
COMBOS = np.array([6 if len(c) == 2 else 4 if c[2] == "s" else 12 for c in CLASSES], dtype=float)


def class_of(combo: Sequence[str]) -> str:
    """('Kd', 'Ah') -> 'AKo'."""
    a, b = sorted(combo, key=lambda c: RANKS_HIGH.index(c[0]))
    if a[0] == b[0]:
        return a[0] + b[0]
    return a[0] + b[0] + ("s" if a[1] == b[1] else "o")


@lru_cache(maxsize=1)
def load_equity() -> Tuple[np.ndarray, np.ndarray]:
    """(equity, pairs), both 169 x 169 in CLASSES order: equity[i, j] is the chance class i
    beats class j all in before the flop (a split counts half); pairs[i, j] is the number
    of ways the two can be dealt together."""
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"{DATA_PATH} is missing: run tools/build_preflop_equity.py")
    with np.load(DATA_PATH) as data:
        if [str(c) for c in data["classes"]] != CLASSES:
            raise ValueError("The equity table's hands are in a different order: rebuild it.")
        return data["equity"].astype(float), data["pairs"].astype(float)


@dataclass(frozen=True)
class PushFoldSolution:
    stack_bb: float
    jam: np.ndarray  # per class, how often the small blind goes all in
    call: np.ndarray  # per class, how often the big blind calls
    value_sb: float  # the small blind's result per hand in big blinds (the big blind's is the opposite)
    exploitability: float  # big blinds per hand a perfect counter gains, averaged over the two seats
    iterations: int

    @property
    def jam_share(self) -> float:
        """Share of all 1,326 hands the small blind jams."""
        return float(COMBOS @ self.jam / COMBOS.sum())

    @property
    def call_share(self) -> float:
        return float(COMBOS @ self.call / COMBOS.sum())

    def jams(self, hand: str) -> float:
        return float(self.jam[CLASS_INDEX[hand]])

    def calls(self, hand: str) -> float:
        return float(self.call[CLASS_INDEX[hand]])

    def mixed(self, tol: float = 0.01) -> Dict[str, List[str]]:
        """The hands that are neither always nor never played, per seat."""
        pick = lambda p: [c for c, x in zip(CLASSES, p) if tol < x < 1 - tol]  # noqa: E731
        return {"jam": pick(self.jam), "call": pick(self.call)}

    def grid(self, seat: str = "jam") -> str:
        """A 13 x 13 chart: # always, + mixed, . never (suited above the diagonal)."""
        p = self.jam if seat == "jam" else self.call
        mark = lambda x: "#" if x >= 0.99 else "." if x <= 0.01 else "+"  # noqa: E731
        rows = ["  " + " ".join(RANKS_HIGH)]
        for i, r in enumerate(RANKS_HIGH):
            rows.append(r + " " + " ".join(mark(p[i * 13 + j]) for j in range(13)))
        return "\n".join(rows)


def _match(regret: np.ndarray) -> np.ndarray:
    """Regret matching for two actions per hand; returns the chance of the second action."""
    pos = np.maximum(regret, 0.0)
    total = pos.sum(axis=1)
    return np.where(total > 0, pos[:, 1] / np.where(total > 0, total, 1.0), 0.5)


class _Game:
    def __init__(self, stack_bb: float, sb: float, bb: float):
        if stack_bb < bb or not 0 < sb <= bb:
            raise ValueError("Need 0 < small blind <= big blind <= stack.")
        equity, pairs = load_equity()
        self.sb, self.bb = sb, bb
        self.n = pairs  # weight of each (small blind class, big blind class) deal
        self.showdown = pairs * stack_bb * (2 * equity - 1)  # the small blind's result when called, weighted
        self.total = float(pairs.sum())
        self.dealt = pairs.sum(axis=1)  # weight of each class against everything

    def sb_values(self, call: np.ndarray) -> np.ndarray:
        """Per small blind class: (folding, jamming) against this calling strategy, weighted."""
        jam = self.bb * (self.n @ (1 - call)) + self.showdown @ call
        return np.stack([-self.sb * self.dealt, jam], axis=1)

    def bb_values(self, jam: np.ndarray) -> np.ndarray:
        """Per big blind class, facing a jam from this jamming strategy: (folding, calling)."""
        return np.stack([-self.bb * (self.n.T @ jam), -(self.showdown.T @ jam)], axis=1)

    def value_sb(self, jam: np.ndarray, call: np.ndarray) -> float:
        v = self.sb_values(call)
        return float((1 - jam) @ v[:, 0] + jam @ v[:, 1]) / self.total

    def exploitability(self, jam: np.ndarray, call: np.ndarray) -> float:
        best_sb = float(self.sb_values(call).max(axis=1).sum()) / self.total
        # the big blind wins the small blind when they fold, plus the better of fold or call
        best_bb = (self.sb * float((1 - jam) @ self.dealt) + float(self.bb_values(jam).max(axis=1).sum())) / self.total
        return (best_sb + best_bb) / 2


def solve_push_fold(stack_bb: float, sb: float = 0.5, bb: float = 1.0, max_iterations: int = 50000,
                    target_exploitability: float = 1e-6, method: str = "dcfr") -> PushFoldSolution:
    """The jam-or-fold equilibrium for this stack. Stops when exploitability is at or
    under the target (big blinds per hand) or at max_iterations."""
    if method not in ("dcfr", "cfr+"):
        raise ValueError(f"Unknown method {method!r}.")
    game = _Game(stack_bb, sb, bb)
    regret = [np.zeros((169, 2)), np.zeros((169, 2))]  # small blind (fold, jam), big blind (fold, call)
    total = [np.zeros(169), np.zeros(169)]
    sigma = [np.full(169, 0.5), np.full(169, 0.5)]
    weight_sum = 0.0
    avg = (sigma[0], sigma[1])
    expl = game.exploitability(*avg)
    t = 0
    for t in range(1, max_iterations + 1):
        weight = float(t) ** 2 if method == "dcfr" else float(t)
        for p in (0, 1):
            values = game.sb_values(sigma[1]) if p == 0 else game.bb_values(sigma[0])
            played = (1 - sigma[p]) * values[:, 0] + sigma[p] * values[:, 1]
            total[p] += weight * sigma[p]
            r = regret[p]
            if method == "dcfr":
                if t > 1:
                    r *= np.where(r > 0, (t - 1) ** 1.5 / ((t - 1) ** 1.5 + 1), 0.5)
                r += values - played[:, None]
            else:
                r += values - played[:, None]
                np.maximum(r, 0.0, out=r)
            sigma[p] = _match(r)
        weight_sum += weight
        if t % 50 == 0 or t == max_iterations:
            avg = (total[0] / weight_sum, total[1] / weight_sum)
            expl = game.exploitability(*avg)
            if expl <= target_exploitability:
                break
    return PushFoldSolution(float(stack_bb), avg[0], avg[1], game.value_sb(*avg), expl, t)
