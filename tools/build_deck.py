"""Build the built-in deck shapes (app/vision/templates/deck_rank.npz, deck_suit.npz)
from labelled screenshots of a poker client.

    python tools/build_deck.py labels.json

labels.json maps each screenshot to its scale (1.0 = the client's own size) and the
cards in it, in any order:

    {"shots/river.png": [1.58, "2h 6c Tc Js Kh Qd Th"], ...}

Every screenshot is read at many sizes with the general recognizer; each card it finds
and reads as one of the listed cards gives its rank and suit shapes. Near duplicates and
odd ones out (a glyph merged with a neighbour) are dropped, and up to 24 varied shapes
are kept per rank and suit. The screenshots themselves are not shipped.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.vision.card_recognizer import CardRecognizer  # noqa: E402
from app.vision.glyphs import TEMPLATE_DIR, feature, normalize_mask, pack_templates, save_template  # noqa: E402

SIZES = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8]
CAP = 24


def collect(labels: dict):
    rec = CardRecognizer(builtin_deck=False)
    out = []
    for path, (native, cards) in labels.items():
        img0 = cv2.imread(path)
        truth = cards.split()
        for size in SIZES:
            f = size / native
            img = cv2.resize(img0, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
            seen = set()
            for r in rec.read(img):
                code = r.code or r.guess
                if code not in truth or code in seen or r.glyphs is None:
                    continue
                if r.suit_confidence < 0.9 or r.rank_confidence < 0.45:
                    continue  # not sure enough that this glyph really is that card
                seen.add(code)
                for g in [r.glyphs] + list(r.glyphs.variants):
                    for kind, glyph, label in (("rank", g.rank, code[0]), ("suit", g.suit, code[1])):
                        res = normalize_mask(glyph.mask) if glyph is not None else None
                        if res is not None:
                            out.append((kind, label, res[0], res[1]))
    return out


def choose(samples, floor=0.88, dup=0.995):
    chosen = []
    for key in sorted({(k, lab) for k, lab, _, _ in samples}):
        group = [s for s in samples if s[:2] == key]
        feats = np.stack([feature(s[2]) for s in group])
        sim = feats @ feats.T
        medoid = int(np.argmax(sim.mean(axis=1)))
        idx = [i for i in range(len(group)) if sim[medoid, i] >= floor]  # drop odd ones out
        keep = []
        for i in idx:
            if all(sim[i, j] < dup for j in keep):
                keep.append(i)
        picked = keep[:1]
        while len(picked) < min(CAP, len(keep)):  # spread: farthest from those picked
            picked.append(max((i for i in keep if i not in picked), key=lambda i: min(1 - sim[i, j] for j in picked)))
        chosen += [group[i] for i in picked]
    return chosen


def main():
    labels = json.loads(Path(sys.argv[1]).read_text())
    shapes = choose(collect(labels))
    tmp = Path(tempfile.mkdtemp())
    for kind, label, norm, aspect in shapes:
        save_template(tmp / kind, label, norm, aspect)
    for kind in ("rank", "suit"):
        n = pack_templates(tmp / kind, TEMPLATE_DIR / f"deck_{kind}.npz")
        print(f"{kind}: {n} shapes")


if __name__ == "__main__":
    main()
