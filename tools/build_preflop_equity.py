"""Build the exact all-in equity of every starting hand against every other (169 x 169).

    python tools/build_preflop_equity.py [--workers 4] [--out app/solver/data/preflop_equity.npz]
                                         [--limit N] [--verify]

Exact means every one of the 1,712,304 boards for every pair of combos that don't share a
card, not a sample. Doing that pair by pair is far too slow, so the work goes board by
board instead:

1. Boards that differ only by swapping suits give the same counts once whole hand classes
   are added up, so one board stands for its whole family: 134,459 boards with a weight
   each, instead of 2,598,960.
2. On a board, every one of the 1,081 possible hole-card combos gets a value
   (app/solver/ranking.py). Counting, for every pair of classes, how many combo pairs win
   and tie is then a histogram and two matrix products.
3. Pairs of combos that share a card can't be dealt: they are counted separately and
   taken out.

The result (about 200 KB) is saved in the repo and loaded by app/solver/pushfold.py:
equity[i, j] = chance that class i beats class j all in before the flop, a split counting
half; pairs[i, j] = how many ways the two classes can be dealt together. Takes a few
minutes on four cores. --verify also works out AA against KK the slow way, combo by combo.
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys
import time
from multiprocessing import Pool

# One thread per worker for the matrix products: several workers each starting their own
# set of threads is many times slower than no threads at all. Must be set before numpy
# loads, so only when this runs as the script (or as one of its workers), not on import.
if __name__ in ("__main__", "__mp_main__"):
    for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver.pushfold import CLASSES, CLASS_INDEX, DATA_PATH, class_of  # noqa: E402
from app.solver.ranking import RANKS, SUITS, RiverRanker, hand_value  # noqa: E402

DECK = [r + s for r in RANKS for s in SUITS]  # card id = rank * 4 + suit
BOARDS_PER_MATCHUP = 1712304  # C(48, 5)


def canonical_boards():
    """One board per family of boards that are the same up to renaming suits, with the
    size of each family. Returns (boards as card ids, shape (n, 5); weights)."""
    boards = np.array(list(itertools.combinations(range(52), 5)), dtype=np.int64)
    rank, suit = boards // 4, boards % 4
    best = None
    for perm in itertools.permutations(range(4)):
        ids = np.sort(rank * 4 + np.array(perm)[suit], axis=1)
        key = ids[:, 0]
        for k in range(1, 5):
            key = key * 52 + ids[:, k]
        best = key if best is None else np.minimum(best, key)
    keys, counts = np.unique(best, return_counts=True)
    out = np.zeros((len(keys), 5), dtype=np.int64)
    rest = keys.copy()
    for k in range(4, -1, -1):
        out[:, k] = rest % 52
        rest //= 52
    return out, counts


# Combos as positions in the list of the 47 cards left: the same for every board.
_PAIRS = np.array(list(itertools.combinations(range(47), 2)), dtype=np.int64)  # (1081, 2)


def _sharing_pairs():
    """Every ordered pair of different combos that share a card (positions as above)."""
    by_card = [[] for _ in range(47)]
    for i, (a, b) in enumerate(_PAIRS):
        by_card[a].append(i)
        by_card[b].append(i)
    first, second = [], []
    for combos in by_card:
        for x in combos:
            for y in combos:
                if x != y:
                    first.append(x)
                    second.append(y)
    return np.array(first), np.array(second)


_SHARE_A, _SHARE_B = _sharing_pairs()
# class of the combo made of two card ids
_CLASS_OF = np.array([[CLASS_INDEX[class_of((DECK[a], DECK[b]))] if a != b else -1 for b in range(52)]
                      for a in range(52)])


def board_counts(board_ids):
    """(wins, ties) between classes on one board, shape (169, 169) each: the number of
    pairs (combo of class i, combo of class j) with no card in common where i's combo
    wins, or ties."""
    board = [DECK[c] for c in board_ids]
    on_board = set(int(c) for c in board_ids)
    left = [DECK[c] for c in range(52) if c not in on_board]
    combos = [(left[a], left[b]) for a, b in _PAIRS]
    values = RiverRanker(board).values(combos)
    left_ids = np.array([c for c in range(52) if c not in on_board])
    cls = _CLASS_OF[left_ids[_PAIRS[:, 0]], left_ids[_PAIRS[:, 1]]]
    _, level = np.unique(values, return_inverse=True)  # 0 = weakest hand on this board
    n_levels = int(level.max()) + 1
    hist = np.zeros((169, n_levels))
    np.add.at(hist, (cls, level), 1.0)
    below = np.cumsum(hist, axis=1) - hist  # combos of each class weaker than each level
    wins = hist @ below.T
    ties = hist @ hist.T
    # take out the pairs that share a card (and each combo against itself, a "tie")
    va, vb = values[_SHARE_A], values[_SHARE_B]
    idx = cls[_SHARE_A] * 169 + cls[_SHARE_B]
    wins -= np.bincount(idx[va > vb], minlength=169 * 169).reshape(169, 169)
    ties -= np.bincount(idx[va == vb], minlength=169 * 169).reshape(169, 169)
    ties[np.arange(169), np.arange(169)] -= np.bincount(cls, minlength=169)
    return wins, ties


def _chunk(args):
    boards, weights = args
    wins = np.zeros((169, 169))
    ties = np.zeros((169, 169))
    for b, w in zip(boards, weights):
        bw, bt = board_counts(b)
        wins += w * bw
        ties += w * bt
    return wins, ties


def class_pairs():
    """pairs[i, j]: how many (combo of class i, combo of class j) pairs share no card."""
    combos = list(itertools.combinations(DECK, 2))
    cls = np.array([CLASS_INDEX[class_of(c)] for c in combos])
    ids = np.array([[DECK.index(a), DECK.index(b)] for a, b in combos])
    clash = np.zeros((len(combos), len(combos)), dtype=bool)
    for i in range(2):
        for j in range(2):
            clash |= ids[:, i, None] == ids[None, :, j]
    onehot = np.zeros((len(combos), 169))
    onehot[np.arange(len(combos)), cls] = 1.0
    return (onehot.T @ (~clash).astype(float) @ onehot).round().astype(np.int64)


def enumerate_matchup(a, b):
    """Equity of combo a against combo b over every board, the slow and obvious way."""
    dead = set(a) | set(b)
    rest = [c for c in DECK if c not in dead]
    win = tie = n = 0
    for board in itertools.combinations(rest, 5):
        va, vb = hand_value(list(a) + list(board)), hand_value(list(b) + list(board))
        win += va > vb
        tie += va == vb
        n += 1
    return (win + tie / 2) / n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--out", default=DATA_PATH)
    ap.add_argument("--limit", type=int, default=0, help="only the first N boards (to time it; no file is written)")
    ap.add_argument("--verify", action="store_true", help="also work out AA against KK the slow way")
    args = ap.parse_args(argv)

    start = time.time()
    boards, weights = canonical_boards()
    print(f"{len(boards)} boards stand for {int(weights.sum())} ({time.time() - start:.0f} s)")
    assert int(weights.sum()) == 2598960
    if args.limit:
        boards, weights = boards[:args.limit], weights[:args.limit]
    step = 500
    chunks = [(boards[i:i + step], weights[i:i + step]) for i in range(0, len(boards), step)]
    wins = np.zeros((169, 169))
    ties = np.zeros((169, 169))
    with Pool(args.workers) as pool:
        for k, (w, t) in enumerate(pool.imap_unordered(_chunk, chunks), 1):
            wins += w
            ties += t
            if k % 20 == 0 or k == len(chunks):
                print(f"  {k * step} boards, {time.time() - start:.0f} s", flush=True)
    if args.limit:
        print("--limit given: nothing saved")
        return 0

    pairs = class_pairs()
    # Each class pair's count was added up over all 2,598,960 boards, but a given pair of
    # combos only sees the boards that avoid its four cards: C(48, 5) of them.
    total = pairs * float(BOARDS_PER_MATCHUP)
    assert np.allclose(wins + wins.T + ties, total), "wins, losses and ties must add up to every deal"
    equity = np.divide(wins + ties / 2, total, out=np.full((169, 169), 0.5), where=total > 0)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    np.savez_compressed(args.out, equity=equity, pairs=pairs.astype(np.int16), classes=np.array(CLASSES))
    print(f"saved {args.out} ({os.path.getsize(args.out) / 1024:.0f} KB, {time.time() - start:.0f} s)")
    i, j = CLASS_INDEX["AA"], CLASS_INDEX["KK"]
    print(f"AA v KK {equity[i, j]:.5f}   AKs v QQ {equity[CLASS_INDEX['AKs'], CLASS_INDEX['QQ']]:.5f}")

    if args.verify:
        # AA against KK the slow way. Against AsAh, the six KK combos are of three kinds:
        # both suits shared (KsKh), one shared (four combos like KsKd), none (KdKc).
        kinds = [(("As", "Ah"), ("Ks", "Kh")), (("As", "Ah"), ("Ks", "Kd")), (("As", "Ah"), ("Kd", "Kc"))]
        with Pool(min(args.workers, 3)) as pool:
            e2, e1, e0 = pool.starmap(enumerate_matchup, kinds)
        slow = (e2 + 4 * e1 + e0) / 6
        print(f"AA v KK by full enumeration {slow:.9f}, table {equity[i, j]:.9f}, "
              f"difference {abs(slow - equity[i, j]):.2e}")
        if abs(slow - equity[i, j]) > 1e-9:
            print("MISMATCH")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
