"""Reference fixture for the Rust hand evaluator (engine/crates/eval).

Deals random heads-up showdowns (a 5-card board plus two 2-card hands) and scores both
7-card hands with PokerKit 0.7.8, the library tools/phh already uses. The Rust test
`engine/crates/eval/tests/pokerkit.rs` replays the same deals and checks that its
evaluator agrees on every hand: the exact rank, the category and so the showdown result.

To keep the file small the cards are not stored. Both sides deal them from the same
seeded SplitMix64 generator, and the header holds a checksum of every dealt card, so a
dealing mismatch is reported as such and never as an evaluator bug.

File layout: a text header ending with an empty line, then for each showdown 4 bytes:
rank of hand A and rank of hand B, each u16 little-endian. Rank is PokerKit's lookup
index + 1, so 1 to 7462 with higher better. PokerKit's category (label) of each hand is
not stored per hand: the header line `category_ranges` gives, for each category, the
lowest and highest rank seen with that label, and the script checks these ranges do not
overlap, so a rank says its category. Categories in order: high card, pair, two pair,
three of a kind, straight, flush, full house, four of a kind, straight flush.

Card encoding (shared with the Rust crates): card = rank * 4 + suit, rank 0 = 2 up to
12 = ace, suit 0..3 = c, d, h, s.

Run (about 2 minutes on 4 cores):
    pip install pokerkit==0.7.8
    python tools/reference/eval_fixtures.py
"""

from __future__ import annotations

import argparse
import multiprocessing
import struct
from importlib.metadata import version
from pathlib import Path

from pokerkit import Label, StandardHighHand

MASK64 = (1 << 64) - 1
DEFAULT_OUT = (
    Path(__file__).resolve().parents[2]
    / "engine/crates/eval/tests/fixtures/pokerkit_showdowns.bin"
)
DEFAULT_SEED = 0x5EED_2026_1126
DEFAULT_COUNT = 1_000_000
CARDS_PER_DEAL = 9  # board 0..5, hand A 5..7, hand B 7..9

RANKS = "23456789TJQKA"
SUITS = "cdhs"
LABELS = [
    Label.HIGH_CARD,
    Label.ONE_PAIR,
    Label.TWO_PAIR,
    Label.THREE_OF_A_KIND,
    Label.STRAIGHT,
    Label.FLUSH,
    Label.FULL_HOUSE,
    Label.FOUR_OF_A_KIND,
    Label.STRAIGHT_FLUSH,
]
CATEGORY = {label: i for i, label in enumerate(LABELS)}


class SplitMix64:
    """SplitMix64 (Steele, Lea, Flood 2014). The Rust test has the same generator."""

    def __init__(self, seed: int) -> None:
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)


def deal_all(seed: int, count: int) -> list[list[int]]:
    """Partial Fisher-Yates on a fresh sorted deck for every showdown."""
    rng = SplitMix64(seed)
    deals = []
    for _ in range(count):
        deck = list(range(52))
        for i in range(CARDS_PER_DEAL):
            j = i + rng.next() % (52 - i)
            deck[i], deck[j] = deck[j], deck[i]
        deals.append(deck[:CARDS_PER_DEAL])
    return deals


def fnv1a64(deals: list[list[int]]) -> int:
    h = 0xCBF29CE484222325
    for deal in deals:
        for card in deal:
            h ^= card
            h = (h * 0x100000001B3) & MASK64
    return h


def text(cards: list[int]) -> str:
    return "".join(RANKS[c >> 2] + SUITS[c & 3] for c in cards)


def score(deal: list[int]) -> tuple[int, int, int, int]:
    """(rank A, category A, rank B, category B)."""
    board = text(deal[0:5])
    a = StandardHighHand.from_game(text(deal[5:7]), board).entry
    b = StandardHighHand.from_game(text(deal[7:9]), board).entry
    return a.index + 1, CATEGORY[a.label], b.index + 1, CATEGORY[b.label]


def category_ranges(results: list[tuple[int, int, int, int]]) -> list[tuple[int, int]]:
    lo = [10_000] * 9
    hi = [0] * 9
    for rank_a, cat_a, rank_b, cat_b in results:
        for rank, cat in ((rank_a, cat_a), (rank_b, cat_b)):
            lo[cat] = min(lo[cat], rank)
            hi[cat] = max(hi[cat], rank)
    ranges = list(zip(lo, hi))
    for (_, hi_prev), (lo_next, _) in zip(ranges, ranges[1:]):
        assert hi_prev < lo_next, f"PokerKit categories overlap: {ranges}"
    return ranges


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--workers", type=int, default=multiprocessing.cpu_count())
    args = parser.parse_args()

    deals = deal_all(args.seed, args.count)
    with multiprocessing.Pool(args.workers) as pool:
        results = pool.map(score, deals, chunksize=2000)

    ranges = category_ranges(results)
    header = (
        "pokerscribe eval fixture v1\n"
        f"generator=tools/reference/eval_fixtures.py\n"
        f"pokerkit={version('pokerkit')}\n"
        f"seed={args.seed}\n"
        f"count={args.count}\n"
        f"deal_fnv1a64={fnv1a64(deals):016x}\n"
        f"category_ranges={','.join(f'{lo}-{hi}' for lo, hi in ranges)}\n"
        "record=rank_a:u16le rank_b:u16le\n"
        "\n"
    )
    body = bytearray()
    for rank_a, _, rank_b, _ in results:
        body += struct.pack("<HH", rank_a, rank_b)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(header.encode("ascii") + bytes(body))

    wins = sum(1 for a, _, b, _ in results if a > b)
    ties = sum(1 for a, _, b, _ in results if a == b)
    print(f"wrote {args.out} ({len(results)} showdowns: A wins {wins}, ties {ties})")


if __name__ == "__main__":
    main()
