"""Build the generic rank and suit templates shipped in app/vision/templates/.

Ranks are rendered from many common sans and serif fonts at several sizes (small
sizes reproduce the blocky look of screen-resolution card indices). Suits come
from fonts that contain the card suit symbols plus parametric drawings.

The fonts used here deliberately differ from the held-out fonts used by the
synthetic test tables (see app/tests/synthetic.py).

    python tools/build_templates.py
"""
import math
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tests.synthetic import find_font  # noqa: E402
from app.vision.glyphs import GLYPH_SIZE, TEMPLATE_DIR, normalize_mask, pack_templates, save_template  # noqa: E402

RANK_FONTS = [
    "DejaVuSans-Bold.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSans.ttf", "LiberationSans-Bold.ttf",
    "LiberationSerif-Bold.ttf", "LiberationSans-Regular.ttf", "FreeSansBold.ttf", "FreeSerifBold.ttf",
    "FiraSans-Black.ttf", "FiraSans-Bold.ttf", "Inter-Black.otf", "Inter-Bold.otf", "Poppins-Bold.ttf",
    "texgyreheros-bold.otf", "texgyretermes-bold.otf", "texgyrepagella-bold.otf", "ArchivoBlack-Regular.ttf",
    "Carlito-Bold.ttf", "Caladea-Bold.ttf", "Arial Bold.ttf", "Verdana Bold.ttf", "Georgia Bold.ttf",
]
SUIT_FONTS = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf",
              "ipag.ttf", "NotoSansCJK-Regular.ttc", "Apple Symbols.ttf", "Arial Unicode.ttf"]
RANK_CHARS = {"A": "A", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
              "T": "10", "J": "J", "Q": "Q", "K": "K"}
SUIT_CHARS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
SIZES = [110, 30, 20]


def render_text(text: str, font_path: str, size: int) -> np.ndarray:
    font = ImageFont.truetype(font_path, size)
    canvas = Image.new("L", (size * 4, size * 3), 255)
    d = ImageDraw.Draw(canvas)
    d.text((size, size // 2), text, font=font, fill=0)
    arr = np.array(canvas)
    return arr < 128


def heart_polygon(cx, cy, s, flip=False, squash=1.0):
    pts = []
    for k in range(120):
        t = 2 * math.pi * k / 120
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        y = -y if not flip else y
        pts.append((cx + x * s / 32 * squash, cy + y * s / 32))
    return pts


def drawn_suits(size: int):
    """Parametric suit drawings, a few proportions each."""
    out = []
    for squash in (0.9, 1.05):
        for suit in "shdc":
            img = Image.new("L", (size * 2, size * 2), 255)
            d = ImageDraw.Draw(img)
            c = size
            s = size * 0.8
            if suit == "h":
                d.polygon(heart_polygon(c, c, s, squash=squash), fill=0)
            elif suit == "s":
                d.polygon(heart_polygon(c, c - s * 0.08, s * 0.92, flip=True, squash=squash), fill=0)
                d.polygon([(c, c + s * 0.05), (c - s * 0.22, c + s * 0.5), (c + s * 0.22, c + s * 0.5)], fill=0)
            elif suit == "d":
                w = s * (0.36 if squash < 1 else 0.44)
                d.polygon([(c, c - s / 2), (c + w, c), (c, c + s / 2), (c - w, c)], fill=0)
            elif suit == "c":
                r = s * 0.23 * squash
                d.ellipse([c - r, c - s * 0.48, c + r, c - s * 0.48 + 2 * r], fill=0)
                d.ellipse([c - s * 0.46, c - s * 0.1, c - s * 0.46 + 2 * r, c - s * 0.1 + 2 * r], fill=0)
                d.ellipse([c + s * 0.46 - 2 * r, c - s * 0.1, c + s * 0.46, c - s * 0.1 + 2 * r], fill=0)
                d.polygon([(c, c - s * 0.05), (c - s * 0.2, c + s * 0.48), (c + s * 0.2, c + s * 0.48)], fill=0)
            out.append((suit, np.array(img) < 128))
    return out


def downsample_threshold(mask: np.ndarray, target_h: int) -> np.ndarray:
    """Mimic a small on-screen glyph: render, shrink with antialiasing, re-threshold."""
    import cv2

    ys, xs = np.nonzero(mask)
    crop = mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].astype(np.float32)
    scale = target_h / crop.shape[0]
    small = cv2.resize(crop, (max(2, int(crop.shape[1] * scale)), target_h), interpolation=cv2.INTER_AREA)
    return small > 0.5


def main():
    for kind in ("rank", "suit"):
        shutil.rmtree(TEMPLATE_DIR / kind, ignore_errors=True)
    counts = {"rank": 0, "suit": 0}
    used = []
    for name in RANK_FONTS:
        path = find_font(name)
        if not path:
            continue
        used.append(name)
        for label, text in RANK_CHARS.items():
            for size in SIZES:
                mask = render_text(text, path, 110)
                if size != 110:
                    mask = downsample_threshold(mask, size)
                res = normalize_mask(mask)
                if res is None:
                    continue
                norm, aspect = res
                save_template(TEMPLATE_DIR / "rank", label, norm, aspect)
                counts["rank"] += 1
    for name in SUIT_FONTS:
        path = find_font(name)
        if not path:
            continue
        used.append(name)
        for label, ch in SUIT_CHARS.items():
            for size in SIZES:
                mask = render_text(ch, path, 110)
                if size != 110:
                    mask = downsample_threshold(mask, max(12, size - 6))
                res = normalize_mask(mask)
                if res is None:
                    continue
                save_template(TEMPLATE_DIR / "suit", label, *res)
                counts["suit"] += 1
    for size in SIZES:
        for label, mask in drawn_suits(120):
            m = mask if size == 110 else downsample_threshold(mask, max(12, size - 6))
            res = normalize_mask(m)
            if res:
                save_template(TEMPLATE_DIR / "suit", label, *res)
                counts["suit"] += 1
    for kind in ("rank", "suit"):
        n = pack_templates(TEMPLATE_DIR / kind, TEMPLATE_DIR / f"{kind}.npz")
        shutil.rmtree(TEMPLATE_DIR / kind, ignore_errors=True)
        print(f"{kind}: {n} unique templates packed")
    print(f"fonts used: {len(used)}; size {GLYPH_SIZE}px")


if __name__ == "__main__":
    import app.vision.glyphs as g

    g.MAX_LEARNED_PER_LABEL = 10**6  # no pruning for shipped templates
    main()
