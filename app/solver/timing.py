"""Decision time on the river: p50 and p95 against the 400 ms target (Phase 2 gate).

time_decisions(spots, decide) runs `decide` on every spot and measures each call.
benchmark_spots(n, seed) makes a repeatable set of river spots for it.

The solver stops on the clock, so time alone says little: QualityReport adds how close to
an equilibrium each answer was when it stopped (its exploitability), and which spots are
still over the bar.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable, List, Sequence

from .spot import BetSizes, RiverSpot

TARGET_MS = 400.0  # p95 decision time must stay under this (docs/research/README.md, Phase 2)
# An answer misses when a perfect counter-strategy could still win more than this share of the pot.
QUALITY_BAR = 0.01


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value with at least q% of the values at or
    below it (p50 of 1..10 is 5, p95 is 10)."""
    if not values:
        raise ValueError("No values.")
    if not 0 < q <= 100:
        raise ValueError("q is between 0 (excluded) and 100.")
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q / 100.0 * len(ordered))) - 1]


@dataclass(frozen=True)
class TimingReport:
    times_ms: tuple
    target_ms: float = TARGET_MS

    @property
    def n(self) -> int:
        return len(self.times_ms)

    @property
    def p50(self) -> float:
        return percentile(self.times_ms, 50)

    @property
    def p95(self) -> float:
        return percentile(self.times_ms, 95)

    @property
    def max(self) -> float:
        return max(self.times_ms)

    @property
    def mean(self) -> float:
        return sum(self.times_ms) / len(self.times_ms)

    @property
    def over_target(self) -> int:
        return sum(1 for t in self.times_ms if t > self.target_ms)

    @property
    def passed(self) -> bool:
        return self.p95 < self.target_ms

    def __str__(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (f"{self.n} decisions: p50 {self.p50:.1f} ms, p95 {self.p95:.1f} ms, max {self.max:.1f} ms, "
                f"mean {self.mean:.1f} ms; {self.over_target} over {self.target_ms:g} ms. "
                f"p95 under {self.target_ms:g} ms: {verdict}")


def time_decisions(spots: Sequence[RiverSpot], decide: Callable[[RiverSpot], object],
                   target_ms: float = TARGET_MS, clock: Callable[[], float] = time.perf_counter) -> TimingReport:
    """Time one call of decide(spot) per spot. Errors are not caught: a decision that
    fails isn't a decision."""
    if not spots:
        raise ValueError("No spots to time.")
    times: List[float] = []
    for spot in spots:
        start = clock()
        decide(spot)
        times.append(1000.0 * (clock() - start))
    return TimingReport(tuple(times), target_ms)


@dataclass(frozen=True)
class QualityReport:
    """Exploitability (share of the pot) of each answer, in the order of the spots."""

    exploitability: tuple
    bar: float = QUALITY_BAR

    @property
    def p50(self) -> float:
        return percentile(self.exploitability, 50)

    @property
    def p95(self) -> float:
        return percentile(self.exploitability, 95)

    @property
    def max(self) -> float:
        return max(self.exploitability)

    @property
    def misses(self) -> List[int]:
        """Positions of the spots whose answer is still over the bar."""
        return [i for i, e in enumerate(self.exploitability) if e > self.bar]

    @property
    def passed(self) -> bool:
        return not self.misses

    def __str__(self) -> str:
        pct = lambda x: f"{100 * x:.3f}%"  # noqa: E731
        return (f"exploitability when it stopped: p50 {pct(self.p50)}, p95 {pct(self.p95)}, max {pct(self.max)} "
                f"of the pot; {len(self.misses)} of {len(self.exploitability)} over {100 * self.bar:g}%")


# Stack-to-pot ratios of the benchmark spots: from nearly all in to deep.
SPRS = (0.5, 1.0, 2.0, 4.0, 8.0)
RANGE_SHARES = {"narrow": (0.10, 0.15), "medium": (0.25, 0.30), "wide": (0.45, 0.50)}


def benchmark_spots(n: int, seed: int = 1, ranges: str = "medium",
                    sizes: BetSizes = BetSizes(), max_raises: int = 1) -> List[RiverSpot]:
    """n repeatable river spots: a random board, a pot of 20 to 200, a stack-to-pot ratio
    from SPRS, and both ranges the top share of preflop hands from RANGE_SHARES (the out
    of position player's range first). Preflop ranges are wider than real river ranges,
    so these are on the slow side."""
    from app.poker.hands import DECK
    from app.poker.ranges import top_fraction

    oop_share, ip_share = RANGE_SHARES[ranges]
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        board = tuple(rng.sample(DECK, 5))
        pot = float(rng.randrange(20, 201))
        stack = pot * rng.choice(SPRS)
        out.append(RiverSpot(board, pot, (stack, stack), top_fraction(oop_share), top_fraction(ip_share),
                             sizes, sizes, max_raises))
    return out
