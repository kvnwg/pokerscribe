"""Monte Carlo equity against random hands or a range, using the treys evaluator.

Runs for a fixed time budget and reports the standard error, so the caller (and
the AI) can see how precise the estimate is. Results are cached and reproducible:
the random seed is derived from the inputs.
"""
from __future__ import annotations

import hashlib
import math
import random
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Sequence, Tuple

from treys import Evaluator

from .hands import DECK, to_int
from .ranges import Combo

_EVAL = Evaluator()


@dataclass(frozen=True)
class EquityResult:
    equity: float
    stderr: float
    iterations: int
    exact: bool = False


def _seed(*parts) -> int:
    return int(hashlib.sha1(repr(parts).encode()).hexdigest()[:12], 16)


def equity(hero: Sequence[str], board: Sequence[str], opponents: int = 1,
           villain_range: Optional[Tuple[Combo, ...]] = None, budget_s: float = 0.3,
           max_iterations: int = 60000) -> EquityResult:
    hero_t, board_t = tuple(hero), tuple(board)
    return _equity_cached(hero_t, board_t, int(opponents), villain_range, round(budget_s, 3), max_iterations)


@lru_cache(maxsize=256)
def _equity_cached(hero, board, opponents, villain_range, budget_s, max_iterations) -> EquityResult:
    if len(hero) != 2 or len(set(hero) | set(board)) != len(hero) + len(board):
        raise ValueError("Hero cards and board must be distinct known cards.")
    if not 1 <= opponents <= 9:
        raise ValueError("Opponents must be between 1 and 9.")
    dead = set(hero) | set(board)
    deck = [to_int(c) for c in DECK if c not in dead]
    hero_i = [to_int(c) for c in hero]
    board_i = [to_int(c) for c in board]
    need = 5 - len(board)
    combos = None
    if villain_range is not None:
        combos = [(to_int(a), to_int(b)) for a, b in villain_range if a not in dead and b not in dead]
        if not combos:
            raise ValueError("Every hand in the range conflicts with the known cards.")
    if opponents == 1 and need == 0:
        return _exact_river(hero_i, board_i, deck, combos)
    if opponents == 1 and need == 1 and combos is not None:
        return _exact_turn(hero_i, board_i, deck, combos)  # <= ~48k evaluations

    rng = random.Random(_seed(hero, board, opponents, len(combos or []), budget_s))
    evaluate = _EVAL.evaluate
    total = total_sq = 0.0
    n = 0
    deadline = time.perf_counter() + budget_s
    while n < max_iterations:
        if n % 256 == 0 and n >= 512 and time.perf_counter() > deadline:
            break
        used = set()
        villains = []
        ok = True
        for _ in range(opponents):
            if combos is None:
                continue
            for _try in range(30):
                c = combos[rng.randrange(len(combos))]
                if c[0] not in used and c[1] not in used:
                    used.update(c)
                    villains.append(c)
                    break
            else:
                ok = False
                break
        if not ok:
            continue
        pool = [c for c in deck if c not in used] if used else deck
        k = need + (2 * opponents if combos is None else 0)
        draw = rng.sample(pool, k)
        full_board = board_i + draw[:need]
        if combos is None:
            rest = draw[need:]
            villains = [(rest[2 * i], rest[2 * i + 1]) for i in range(opponents)]
        mine = evaluate(full_board, hero_i)
        best_villain = min(evaluate(full_board, list(v)) for v in villains)
        if mine < best_villain:
            share = 1.0
        elif mine > best_villain:
            share = 0.0
        else:
            ties = sum(1 for v in villains if evaluate(full_board, list(v)) == mine)
            share = 1.0 / (ties + 1)
        total += share
        total_sq += share * share
        n += 1
    mean = total / n
    var = max(0.0, total_sq / n - mean * mean)
    return EquityResult(round(mean, 4), round(math.sqrt(var / n), 4), n)


def _exact_river(hero_i, board_i, deck, combos) -> EquityResult:
    """Heads-up on the river: enumerate every opponent hand exactly."""
    if combos is None:
        combos = [(deck[i], deck[j]) for i in range(len(deck)) for j in range(i + 1, len(deck))]
    mine = _EVAL.evaluate(board_i, hero_i)
    total = 0.0
    for v in combos:
        theirs = _EVAL.evaluate(board_i, list(v))
        total += 1.0 if mine < theirs else 0.5 if mine == theirs else 0.0
    return EquityResult(round(total / len(combos), 4), 0.0, len(combos), exact=True)


def _exact_turn(hero_i, board_i, deck, combos) -> EquityResult:
    """Heads-up on the turn: every opponent hand times every river card, exactly."""
    if combos is None:
        combos = [(deck[i], deck[j]) for i in range(len(deck)) for j in range(i + 1, len(deck))]
    total = 0.0
    count = 0
    evaluate = _EVAL.evaluate
    for v in combos:
        for river in deck:
            if river == v[0] or river == v[1]:
                continue
            full = board_i + [river]
            mine, theirs = evaluate(full, hero_i), evaluate(full, list(v))
            total += 1.0 if mine < theirs else 0.5 if mine == theirs else 0.0
            count += 1
    return EquityResult(round(total / count, 4), 0.0, count, exact=True)
