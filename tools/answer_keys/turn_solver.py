"""An exact solver for turn spots, in numpy: the reference answer for the turn.

app/solver solves river spots only, and TexasSolver's turn answers follow its own rule for
the river card (1/46 a card where the exact weight is 1/44: values.py and
docs/research/PHASE4.md). So until the Rust solver there was no exact answer to a turn
spot. This is one: Discounted CFR with app/solver's settings (alpha 1.5, beta 0, gamma 2,
players updated in turn) over values.Game, that is every combo, card removal, and each of
the 44 river cards dealt for every pair of combos. No abstraction and no sampling.

It is a reference, not a solver to play with: about 40 ms an iteration on a turn spot, so
seconds to minutes a spot. The speed-critical turn solver is the Rust one (engine/). This
one tells whether the Rust one is right.

    answer = solve(spot, target_exploitability=0.0002)
    nodes = node_records(answer)        # the RESULT's node records (data/SPOT_FORMAT.md)

It stops by work done, never by a clock unless time_ms is given, so a run repeats exactly:
the exploitability is worked out every `check_every` iterations (an exact best response,
values.Game.best_response) and the run ends at the first check at or under the target.

It takes river spots too. The tests use that to hold it against app/solver's checker,
which shares no code with it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Tuple

import numpy as np

from app.solver.cfr import DCFR_ALPHA, DCFR_BETA, DCFR_GAMMA
from app.solver.spot import IP, OOP

from .result import node_record
from .spots import Decision
from .values import RIVER_CARDS, Game

NAME = "pokerscribe turn reference (numpy DCFR)"
VERSION = "1"
METHOD = "dcfr"
CHECK_EVERY = 25  # iterations between two exploitability checks


@dataclass
class Answer:
    """probs[node]: the average strategy, shaped (combos of the actor, actions).
    exploitability: of that strategy, as a share of the pot (the last check).
    trace: (iteration, exploitability as a share of the pot) at every check."""

    game: Game
    probs: Dict[str, np.ndarray]
    iterations: int
    exploitability: float
    elapsed_ms: float
    trace: List[Tuple[int, float]] = field(default_factory=list)


def _match(regret: np.ndarray) -> np.ndarray:
    """Regret matching: in proportion to the positive regrets, even when there are none."""
    pos = np.maximum(regret, 0.0)
    total = pos.sum(axis=1)
    none = total <= 0
    pos[none] = 1.0
    total[none] = regret.shape[1]
    return pos / total[:, None]


def solve(spot: Mapping, target_exploitability: float = 0.0, max_iterations: Optional[int] = None,
          time_ms: Optional[float] = None, check_every: int = CHECK_EVERY, river_cards: int = RIVER_CARDS,
          log: Optional[Callable[[str], None]] = None) -> Answer:
    """Solve a turn (or river) spot. target_exploitability is a share of the pot (0 = never
    stop early); at least one of the three limits must be given. river_cards=46 solves the
    game by TexasSolver's rule (values.py), 44 the exact one."""
    if not (target_exploitability > 0 or max_iterations is not None or time_ms is not None):
        raise ValueError("Give a target exploitability, a number of iterations or a time.")
    if max_iterations is not None and max_iterations < 1:
        raise ValueError("max_iterations is at least 1.")
    start = time.perf_counter()
    g = Game(spot, river_cards)
    half = g.pot / 2
    shape = {key: (len(g.combos[g.actor[key]]), len(node.actions)) for key, node in g.nodes.items()}
    regret = {key: np.zeros(s) for key, s in shape.items()}
    strategy_sum = {key: np.zeros(s) for key, s in shape.items()}
    sigma = {key: np.full(s, 1.0 / s[1]) for key, s in shape.items()}

    def update(player: int, t: int) -> None:
        """One pass of the tree for one player: new regrets and a new strategy at each of
        the player's nodes, from the values of each action against the other's strategy."""
        weight = float(t) ** DCFR_GAMMA
        pos, neg = 1.0, 1.0
        if t > 1:
            pos = (t - 1) ** DCFR_ALPHA / ((t - 1) ** DCFR_ALPHA + 1)
            neg = (t - 1) ** DCFR_BETA / ((t - 1) ** DCFR_BETA + 1)

        def values(key: str, card: Optional[str], before: float, opp: np.ndarray, own: np.ndarray):
            """For each of the player's combos, its value from this node on, summed over
            the opponent's combos (opp: how often each gets here). own: how often each of
            the player's combos chooses to get here."""
            node = g.nodes[key]
            s = sigma[key]
            if g.actor[key] != player:
                total = 0.0
                for a, action in enumerate(node.actions):
                    total = total + after(node, action, card, before, opp * s[:, a], own)
                return total
            q = np.stack([after(node, action, card, before, opp, own * s[:, a])
                          for a, action in enumerate(node.actions)], axis=1)
            v = np.einsum("ij,ij->i", s, q)
            strategy_sum[key] += (weight * own)[:, None] * s
            r = regret[key]
            if t > 1:
                r *= np.where(r > 0, pos, neg)
            r += q - v[:, None]
            sigma[key] = _match(r)
            return v

        def after(node: Decision, action: str, card: Optional[str], before: float, opp: np.ndarray, own: np.ndarray):
            kind, child, chips = g.child(node, action, before)
            if kind == "node":
                return values(child, card, before, opp, own)
            if kind == "deal":
                total = 0.0
                for river in g.cards:
                    total = total + values(f"{child} {river}", river, chips, opp, own)
                return total
            meets, wins = g.tables[card]
            if kind == "fold":
                m = meets @ opp if player == OOP else opp @ meets
                return (-(half + chips) if g.actor[node.key] == player else half + chips) * m
            return (half + chips) * (wins @ opp if player == OOP else -(opp @ wins))

        values("", None, 0.0, g.weights[1 - player], np.ones(len(g.combos[player])))

    def average() -> Dict[str, np.ndarray]:
        """The average strategy; where a combo never got to a node, its last strategy."""
        out = {}
        for key, total in strategy_sum.items():
            n = total.sum(axis=1, keepdims=True)
            out[key] = np.where(n > 0, total / np.where(n > 0, n, 1.0), sigma[key])
        return out

    def exploitability(avg: Mapping[str, np.ndarray]) -> float:
        return (g.best_response(avg, OOP) + g.best_response(avg, IP) - g.pot) / 2 / g.pot

    t, trace = 0, []
    while True:
        t += 1
        update(OOP, t)
        update(IP, t)
        last = (max_iterations is not None and t >= max_iterations) or (
            time_ms is not None and 1000.0 * (time.perf_counter() - start) >= time_ms)
        if last or t % check_every == 0:
            avg = average()
            expl = exploitability(avg)
            trace.append((t, expl))
            if log:
                log(f"{spot.get('id', '')} iteration {t}: exploitability {100 * expl:.4f}% of the pot, "
                    f"{time.perf_counter() - start:.1f} s")
            if last or (target_exploitability > 0 and expl <= target_exploitability):
                return Answer(g, avg, t, expl, 1000.0 * (time.perf_counter() - start), trace)


def node_records(answer: Answer) -> Dict[str, dict]:
    """The answer as RESULT node records, in the order of the spot's tree. A combo that
    holds a node's river card can't be there and is left out (data/SPOT_FORMAT.md)."""
    g = answer.game
    out = {}
    for key, node in g.nodes.items():
        card = g.river_card(node)
        rows = {combo: dict(zip(node.actions, answer.probs[key][i]))
                for i, combo in enumerate(g.combos[g.actor[key]])
                if not (card and card in (combo[:2], combo[2:]))}
        out[key] = node_record(key, node.actor, node.actions, rows)
    return out
