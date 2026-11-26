"""Benchmark card recognition on synthetic cards drawn with held-out fonts.

    python tools/eval_cards.py [n_strips]

Prints accuracy, how many wrong reads would be shown as known (the number that
matters: it should be ~0), and score statistics used to calibrate confidence.
"""
import os
import random
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tests.synthetic import Theme, draw_card, find_font, held_out_rank_fonts  # noqa: E402
from app.vision.card_recognizer import CardRecognizer  # noqa: E402

DECK = [r + s for r in "23456789TJQKA" for s in "shdc"]
SUIT_FONTS = [None, None, find_font("NotoSerifCJK-Regular.ttc"), find_font("NotoSansCJK-Bold.ttc")]


def make_strip(rng: random.Random, fonts):
    h = rng.choice([36, 44, 56, 70, 90, 120])
    th = Theme(card_w=int(h * rng.uniform(0.68, 0.74)), card_h=h, rank_font=rng.choice(fonts),
               suit_font=rng.choice(SUIT_FONTS), four_color=rng.random() < 0.3,
               face=rng.choice([(250, 250, 248), (240, 238, 228), (255, 255, 255)]))
    cards = rng.sample(DECK, 5)
    felt = rng.choice([(29, 112, 66), (30, 60, 120), (110, 30, 35), (40, 40, 45)])
    W = 5 * (th.card_w + 10) + 20
    img = Image.new("RGB", (W, h + 30), felt)
    for i, c in enumerate(cards):
        draw_card(img, c, 10 + i * (th.card_w + 10), 15, th)
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    if rng.random() < 0.4:
        arr = cv2.GaussianBlur(arr, (3, 3), rng.uniform(0.3, 0.9))
    if rng.random() < 0.4:
        q = rng.choice([60, 75, 90])
        arr = cv2.imdecode(cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, q])[1], cv2.IMREAD_COLOR)
    return arr, cards


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = random.Random(42)
    fonts = held_out_rank_fonts()
    rec = CardRecognizer(threshold=0.70)
    total = found = correct = shown_wrong = shown = 0
    stats = []
    for _ in range(n):
        img, cards = make_strip(rng, fonts)
        reads = rec.read(img)
        total += len(cards)
        found += min(len(reads), len(cards))
        slot = th_w = (img.shape[1] - 20) / 5.0
        matched = {}
        for r in reads:
            k = int((r.center[0] - 10) // slot)
            if 0 <= k < 5 and k not in matched:
                matched[k] = r
        found -= min(len(reads), len(cards))
        found += len(matched)
        for k, r in matched.items():
            truth = cards[k]
            ok = r.guess == truth
            correct += ok
            if r.code is not None:
                shown += 1
                shown_wrong += not ok
            stats.append((ok, r.confidence, r.rank_confidence, r.suit_confidence, truth, r.guess, img.shape[0] - 30, r.code is not None))
    print(f"cards: {total}  detected: {found} ({found / total:.1%})")
    print(f"best guess correct: {correct}/{found} ({correct / max(1, found):.1%})")
    print(f"shown as known (conf>=0.70): {shown}/{found} ({shown / max(1, found):.1%}); wrong among shown: {shown_wrong}")
    for hb in sorted({s[6] for s in stats}):
        sub = [s for s in stats if s[6] == hb]
        acc = sum(s[0] for s in sub) / len(sub)
        shown_b = [s for s in sub if s[7]]
        wrong_b = sum(1 for s in shown_b if not s[0])
        print(f"  card h {hb:3d}: n={len(sub):3d} guess acc {acc:.1%}  shown {len(shown_b)/len(sub):.1%}  wrong shown {wrong_b}")
    wrong = [s for s in stats if not s[0]]
    print("sample wrong guesses (truth -> guess, conf):", [(s[4], s[5], s[1]) for s in wrong[:20]])
    oks = np.array([s[1] for s in stats if s[0]])
    bad = np.array([s[1] for s in stats if not s[0]]) if wrong else np.array([0.0])
    print(f"confidence correct: median {np.median(oks):.2f} p10 {np.percentile(oks, 10):.2f} | wrong: max {bad.max():.2f}")


if __name__ == "__main__":
    main()
