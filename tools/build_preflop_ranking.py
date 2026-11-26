"""Rank the 169 starting hands by all-in equity against one random hand (treys, Monte Carlo).

    python tools/build_preflop_ranking.py   -> prints a Python list for app/poker/ranges.py
"""
import random

from treys import Card, Evaluator

RANKS = "23456789TJQKA"
SUITS = "shdc"


def classes():
    out = []
    for i in range(12, -1, -1):
        for j in range(i, -1, -1):
            a, b = RANKS[i], RANKS[j]
            if i == j:
                out.append(a + b)
            else:
                out.append(a + b + "s")
                out.append(a + b + "o")
    return out


def example(cls):
    a, b = cls[0], cls[1]
    if len(cls) == 2:
        return [a + "s", b + "h"]
    return [a + "s", b + ("s" if cls[2] == "s" else "h")]


def main(samples=6000):
    ev = Evaluator()
    deck = [r + s for r in RANKS for s in SUITS]
    rng = random.Random(1)
    scores = {}
    for cls in classes():
        hero = example(cls)
        rest = [Card.new(c) for c in deck if c not in hero]
        h = [Card.new(c) for c in hero]
        win = 0.0
        for _ in range(samples):
            s = rng.sample(rest, 7)
            v, board = s[:2], s[2:]
            a, b = ev.evaluate(board, h), ev.evaluate(board, v)
            win += 1.0 if a < b else 0.5 if a == b else 0.0
        scores[cls] = win / samples
    ranked = sorted(scores, key=lambda c: -scores[c])
    print("PREFLOP_RANKING = [")
    for i in range(0, len(ranked), 12):
        print("    " + ", ".join(f'"{c}"' for c in ranked[i:i + 12]) + ",")
    print("]")


if __name__ == "__main__":
    main()
