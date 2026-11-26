"""Counterfactual regret minimisation on a river spot (Zinkevich et al. 2007), in two
flavours that share one loop:

- "cfr+" (Tammelin 2014): regrets never go below zero, later iterations weigh more in the
  average (weight t);
- "dcfr" (Brown and Sandholm 2019, Discounted CFR with alpha 1.5, beta 0, gamma 2): old
  positive regrets are discounted by t^1.5 / (t^1.5 + 1), old negative regrets halved,
  and iteration t weighs t^2 in the average.

Both update the players in turn (alternating updates) and return the average strategy,
which is what converges to an equilibrium in a two-player zero-sum game.

Everything is vectorised over combos. One half-iteration for a player is:
1. walk down the tree, multiplying the opponent's reach by its current strategy;
2. value every end of the hand at once: the reaches of all terminal nodes are the rows of
   one matrix, multiplied by the showdown tables in two matrix products;
3. walk back up: at the player's own nodes, the value of each action against the current
   strategy gives the regrets and the new strategy.

Payoffs, card removal and the exploitability number are the same as in exploitability.py
(the tests check the two agree to rounding).
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import numpy as np

from .ranking import matchups
from .spot import IP, OOP, RiverSpot
from .strategy import RiverStrategy
from .tree import FOLD, GameTree

METHODS = ("dcfr", "cfr+")
DCFR_ALPHA, DCFR_BETA, DCFR_GAMMA = 1.5, 0.0, 2.0


class RiverCFR:
    """The solver's state for one spot. iterate() runs one iteration (both players);
    average_strategy() and exploitability() can be asked at any time."""

    def __init__(self, spot: RiverSpot, method: str = "dcfr", tree: Optional[GameTree] = None):
        if method not in METHODS:
            raise ValueError(f"Unknown method {method!r}: use one of {METHODS}.")
        self.spot = spot
        self.method = method
        self.tree = tree if tree is not None else GameTree(spot)
        self.iterations = 0

        outcome, possible = matchups(spot.board, spot.combos(OOP), spot.combos(IP))
        meets = possible.astype(np.float64)  # (oop combos, ip combos): 1 where the deal can happen
        wins = outcome.astype(np.float64) * meets  # +1 OOP wins, -1 IP wins
        self.weights = (spot.weights(OOP), spot.weights(IP))
        self.total = float(self.weights[OOP] @ meets @ self.weights[IP])
        if self.total <= 0:
            raise ValueError("Every deal clashes: the two ranges share a card in every pairing.")
        # For the player being valued, tables shaped (opponent combos, own combos), so that
        # (terminal reaches as rows) @ table gives one row of values per terminal node.
        self._meets = (np.ascontiguousarray(meets.T), np.ascontiguousarray(meets))
        self._wins = (np.ascontiguousarray(wins.T), np.ascontiguousarray(-wins))

        self._flatten()
        n = (len(spot.oop_range), len(spot.ip_range))
        self.regret = [np.zeros((n[p], k)) for p, k in zip(self.player, self.n_actions)]
        self.strategy_sum = [np.zeros((n[p], k)) for p, k in zip(self.player, self.n_actions)]
        self.sigma = [np.full((n[p], k), 1.0 / k) for p, k in zip(self.player, self.n_actions)]
        self._reach_rows = [np.zeros((len(self.term_keys), n[1 - p])) for p in (OOP, IP)]
        self._ones = (np.ones(n[OOP]), np.ones(n[IP]))

    # ------------------------------------------------------------- the tree
    def _flatten(self) -> None:
        """Decision nodes in an order where parents come before children, terminal nodes
        with the showdowns first, and each terminal's payoff as two numbers per player:
        value = a x (weight of the deals that can happen) + b x (wins minus losses)."""
        tree, pot = self.tree, self.spot.pot
        order = []
        stack = [""]
        while stack:
            key = stack.pop()
            node = tree[key]
            if node.is_terminal:
                continue
            order.append(key)
            stack.extend(reversed(node.children))
        terminals = sorted((n for n in tree.terminals()), key=lambda n: (n.terminal == FOLD, n.key))
        d_index = {k: i for i, k in enumerate(order)}
        t_index = {n.key: i for i, n in enumerate(terminals)}
        self.keys: List[str] = order
        self.term_keys: List[str] = [n.key for n in terminals]
        self.player: List[int] = [tree[k].player for k in order]
        self.n_actions: List[int] = [len(tree[k].actions) for k in order]
        # children: (True, terminal index) or (False, decision index)
        self.kids: List[List[Tuple[bool, int]]] = [
            [(True, t_index[c]) if tree[c].is_terminal else (False, d_index[c]) for c in tree[k].children]
            for k in order]
        self.n_showdowns = sum(1 for n in terminals if n.terminal != FOLD)
        a = np.zeros((2, len(terminals)))
        b = np.zeros((2, len(terminals)))
        for t, node in enumerate(terminals):
            for p in (OOP, IP):
                if node.terminal == FOLD:
                    a[p, t] = -node.put_in[p] if node.folder == p else pot + node.put_in[node.folder]
                else:
                    a[p, t] = 0.5 * pot
                    b[p, t] = 0.5 * pot + node.put_in[0]
        self._a = (a[OOP][:, None], a[IP][:, None])
        self._b = (b[OOP][:self.n_showdowns, None], b[IP][:self.n_showdowns, None])

    # ------------------------------------------------------- one iteration
    def _terminal_values(self, p: int, sigma: List[np.ndarray], own_reach: Optional[list] = None) -> np.ndarray:
        """Rows: terminal nodes. Columns: the player's combos. Each entry is the payoff
        summed over the opponent's combos, weighted by how often each gets there playing
        `sigma`. Fills own_reach (per decision node) when a list is given."""
        opp = 1 - p
        rows = self._reach_rows[p]
        reach = [None] * len(self.keys)
        reach[0] = self.weights[opp]
        if own_reach is not None:
            own_reach[0] = self._ones[p]
        for i, kids in enumerate(self.kids):
            s, r = sigma[i], reach[i]
            if self.player[i] == opp:
                for a, (is_term, j) in enumerate(kids):
                    child = r * s[:, a]
                    if is_term:
                        rows[j] = child
                    else:
                        reach[j] = child
                        if own_reach is not None:
                            own_reach[j] = own_reach[i]
            else:
                for a, (is_term, j) in enumerate(kids):
                    if is_term:
                        rows[j] = r
                    else:
                        reach[j] = r
                        if own_reach is not None:
                            own_reach[j] = own_reach[i] * s[:, a]
        values = rows @ self._meets[p]
        values *= self._a[p]
        k = self.n_showdowns
        if k:
            values[:k] += (rows[:k] @ self._wins[p]) * self._b[p]
        return values

    def _update(self, p: int, t: int) -> None:
        own_reach: list = [None] * len(self.keys)
        terminal = self._terminal_values(p, self.sigma, own_reach)
        node_value: list = [None] * len(self.keys)
        dcfr = self.method == "dcfr"
        if dcfr:
            weight = float(t) ** DCFR_GAMMA
            if t > 1:
                pos = (t - 1) ** DCFR_ALPHA / ((t - 1) ** DCFR_ALPHA + 1)
                neg = (t - 1) ** DCFR_BETA / ((t - 1) ** DCFR_BETA + 1)
        else:
            weight = float(t)
        for i in range(len(self.keys) - 1, -1, -1):
            vals = [terminal[j] if is_term else node_value[j] for is_term, j in self.kids[i]]
            if self.player[i] != p:
                v = vals[0]
                for x in vals[1:]:
                    v = v + x
                node_value[i] = v
                continue
            q = np.stack(vals, axis=1)  # value of each action, per combo
            s = self.sigma[i]
            v = np.einsum("ij,ij->i", s, q)
            node_value[i] = v
            self.strategy_sum[i] += (weight * own_reach[i])[:, None] * s
            q -= v[:, None]  # now the regret of each action this iteration
            r = self.regret[i]
            if dcfr:
                if t > 1:
                    r *= np.where(r > 0, pos, neg)
                r += q
            else:
                r += q
                np.maximum(r, 0.0, out=r)
            self.sigma[i] = _match(r)

    def iterate(self) -> None:
        self.iterations += 1
        for p in (OOP, IP):
            self._update(p, self.iterations)

    # ---------------------------------------------------------------- read
    def average(self) -> List[np.ndarray]:
        """The average strategy at every decision node. A combo that never reached a node
        by its own choices has no average there: it gets the current strategy."""
        out = []
        for i, s in enumerate(self.strategy_sum):
            total = s.sum(axis=1, keepdims=True)
            out.append(np.where(total > 0, s / np.where(total > 0, total, 1.0), self.sigma[i]))
        return out

    def _best_response(self, p: int, sigma: List[np.ndarray]) -> float:
        terminal = self._terminal_values(p, sigma)
        node_value: list = [None] * len(self.keys)
        for i in range(len(self.keys) - 1, -1, -1):
            vals = [terminal[j] if is_term else node_value[j] for is_term, j in self.kids[i]]
            v = vals[0]
            if self.player[i] == p:
                for x in vals[1:]:
                    v = np.maximum(v, x)
            else:
                for x in vals[1:]:
                    v = v + x
            node_value[i] = v
        return float(self.weights[p] @ node_value[0]) / self.total

    def exploitability(self, sigma: Optional[List[np.ndarray]] = None) -> float:
        """Exploitability of the average strategy (or of `sigma`), as a share of the pot."""
        sigma = self.average() if sigma is None else sigma
        pot = self.spot.pot
        return (self._best_response(OOP, sigma) + self._best_response(IP, sigma) - pot) / 2 / pot

    def average_strategy(self, **kw) -> RiverStrategy:
        return RiverStrategy(self.spot, dict(zip(self.keys, self.average())), self.tree, **kw)


def _match(regret: np.ndarray) -> np.ndarray:
    """Regret matching: play each action in proportion to its positive regret (evenly when
    none is positive)."""
    pos = np.maximum(regret, 0.0)
    total = pos.sum(axis=1)
    none = total <= 0.0
    if none.any():
        pos[none] = 1.0
        total[none] = regret.shape[1]
    pos /= total[:, None]
    return pos


def solve(spot: RiverSpot, time_budget_ms: Optional[float], max_iterations: Optional[int] = None,
          method: str = "dcfr", target_exploitability: float = 0.0) -> RiverStrategy:
    """Iterate until the time budget is nearly spent, max_iterations is reached, or the
    average strategy's exploitability is at or under the target (a share of the pot,
    checked at iterations 8, 16, 32, ...). Always runs at least one iteration."""
    start = time.perf_counter()
    if time_budget_ms is None and max_iterations is None and target_exploitability <= 0:
        raise ValueError("Give a time budget, max_iterations or a target exploitability.")
    solver = RiverCFR(spot, method)
    deadline = None
    if time_budget_ms is not None:
        # keep a little back for the return itself
        deadline = start + (time_budget_ms - max(3.0, 0.03 * time_budget_ms)) / 1000.0
    next_check, expl, spent = 8, None, 0.0
    while True:
        t0 = time.perf_counter()
        solver.iterate()
        now = time.perf_counter()
        spent += now - t0
        expl = None
        if max_iterations is not None and solver.iterations >= max_iterations:
            break
        if target_exploitability > 0 and solver.iterations >= next_check:
            next_check *= 2
            expl = solver.exploitability()
            if expl <= target_exploitability:
                break
            now = time.perf_counter()
        # Another iteration, then the final check (about one more), must still fit. The
        # average iteration time is the estimate: one slow iteration shouldn't end the run.
        if deadline is not None and now + 3.0 * spent / solver.iterations > deadline:
            break
    average = solver.average()
    if expl is None:
        expl = solver.exploitability(average)
    strategy = RiverStrategy(spot, dict(zip(solver.keys, average)), solver.tree, iterations=solver.iterations,
                             exploitability=expl)
    strategy.elapsed_ms = 1000.0 * (time.perf_counter() - start)
    return strategy
