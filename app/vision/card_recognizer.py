"""Classify detected cards (rank + suit) with confidence scores.

Low-confidence cards are returned with code=None and a best guess, so the rest of
the app can show them as UNKNOWN instead of inventing a card.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .cards import Box, CardGlyphs, Glyph, find_cards, ink_color
from .glyphs import Match, TemplateSet, load_builtin_deck, load_generic, normalize_mask, save_template

COLOR_SUITS = {"black": {"s", "c"}, "red": {"h", "d"}, "blue": {"d"}, "green": {"c"}}


def suit_structure(mask: np.ndarray) -> Tuple[float, float, int]:
    """(upper-half solidity, relative row of greatest width, glyph height in px).

    A spade's top half is convex while a club's lobes make it concave; a heart is
    widest about a third of the way down while a diamond is widest at the middle."""
    import cv2

    ys, xs = np.nonzero(mask)
    if xs.size < 6:
        return 0.9, 0.45, 0
    m = mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].astype(np.uint8)
    h = m.shape[0]
    top = np.pad(m[: max(2, int(round(h * 0.5)))], 1)
    contours, _ = cv2.findContours(top, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    upper = 1.0
    if contours:
        area = sum(float(cv2.contourArea(c)) for c in contours)
        hull = float(cv2.contourArea(cv2.convexHull(np.vstack(contours))))
        upper = area / hull if hull > 0 else 1.0
    widths = m.sum(axis=1).astype(np.float32)
    k = max(1, h // 10)
    smooth = np.convolve(widths, np.ones(k) / k, mode="same")
    rows = np.nonzero(smooth >= 0.92 * smooth.max())[0]
    widest = float(rows.mean() + 0.5) / h
    return float(upper), widest, int(h)


def _centroid(g: Glyph) -> Tuple[float, float]:
    ys, xs = np.nonzero(g.mask)
    x, y, w, h = g.box
    if xs.size == 0:
        return x + w / 2.0, y + h / 2.0
    return x + float(xs.mean()), y + float(ys.mean())


def index_tilt(g: Optional[CardGlyphs]) -> Optional[float]:
    """How far a card is turned, in degrees (positive = counter-clockwise), from its
    corner index: the suit sits straight below the rank on an upright card."""
    if g is None or g.rank is None or g.suit is None:
        return None
    rx, ry = _centroid(g.rank)
    sx, sy = _centroid(g.suit)
    dx, dy = sx - rx, sy - ry
    if dy < 0.4 * g.rank.box[3] or dy < 6:
        return None  # suit beside the rank, or too small to measure
    return math.degrees(math.atan2(dx, dy))


def lower_middle_center(mask: np.ndarray) -> Optional[float]:
    """Where the ink sits, left (0) to right (1), between 55% and 85% of the glyph's
    height. A "2" runs its diagonal down to the left there; a "3" curls back right."""
    ys, xs = np.nonzero(mask)
    if xs.size < 6:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0 + 1, x1 - x0 + 1
    band = (ys >= y0 + 0.55 * h) & (ys <= y0 + 0.85 * h)
    if not band.any() or w < 3:
        return None
    return float((xs[band].mean() - x0) / (w - 1))


def upper_band_center(mask: np.ndarray, lo: float = 0.18, hi: float = 0.42) -> Optional[float]:
    """Where the ink sits, left (0) to right (1), between 18% and 42% of the glyph's
    height. A "5" comes down its left side there; a "3" curves round on the right."""
    ys, xs = np.nonzero(mask)
    if xs.size < 6:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0 + 1, x1 - x0 + 1
    band = (ys >= y0 + lo * h) & (ys <= y0 + hi * h)
    if not band.any() or w < 3:
        return None
    return float((xs[band].mean() - x0) / (w - 1))


def rank_holes(mask: np.ndarray) -> List[Tuple[float, float, float]]:
    """Closed counters of a glyph: [(centre height 0 top .. 1 bottom, area share,
    centre 0 left .. 1 right), ...]."""
    m = mask.astype(bool)
    ys, xs = np.nonzero(m)
    if xs.size < 6:
        return []
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    box = m[y0:y1, x0:x1]
    h, w = box.shape
    inv = np.pad(~box, 1, constant_values=True).astype(np.uint8)  # the frame is outside
    n, _, stats, cent = cv2.connectedComponentsWithStats(inv, connectivity=4)
    out = []
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if x == 0 or y == 0 or x + ww >= inv.shape[1] or y + hh >= inv.shape[0]:
            continue  # open to the outside: not a counter
        share = area / float(h * w)
        if share >= 0.02:
            out.append((float((cent[i][1] - 1) / h), float(share), float((cent[i][0] - 1) / w)))
    return sorted(out)


HOLE_MIN_PX = 19  # below this height a 6 or 9 can close its open stroke and look like an 8


def hole_signature(mask: np.ndarray) -> Optional[str]:
    """6, 8 or 9 from the closed counters, when they leave no doubt: an 8 has two (top and
    bottom), a 6 one low down and a 9 one high up. These ranks are the ones template
    matching mixes up most, and the counters tell them apart in any font."""
    ys = np.nonzero(mask)[0]
    if ys.size == 0 or ys.max() - ys.min() + 1 < HOLE_MIN_PX:
        return None
    holes = [hh for hh in rank_holes(mask) if hh[1] >= 0.03]
    if len(holes) == 2 and holes[0][0] < 0.45 and holes[1][0] > 0.55:
        return "8"
    if len(holes) == 1 and holes[0][1] >= 0.04:
        if holes[0][0] >= 0.55:
            return "6"
        if holes[0][0] <= 0.45:
            return "9"
    return None


def _size_factor(height: float, low: float, span: float) -> float:
    return min(1.0, max(0.5, (height - low) / span))


def score_to_confidence(best: float, second: float, floor: float = 0.50, span: float = 0.30,
                        margin_span: float = 0.10) -> float:
    """Map a template score and its lead over the runner-up to 0..1."""
    absolute = min(1.0, max(0.0, (best - floor) / span))
    margin = min(1.0, max(0.0, (best - second) / margin_span))
    return round(math.sqrt(absolute * margin), 3)


@dataclass
class CardReading:
    code: Optional[str]  # e.g. "As" when confident, otherwise None
    guess: Optional[str]  # best guess, shown to the user but never treated as fact
    confidence: float
    rank_confidence: float
    suit_confidence: float
    box: Box
    color: str = "unknown"
    glyphs: Optional[CardGlyphs] = field(default=None, repr=False)
    exact: bool = False  # rank and suit both match shapes the user confirmed
    anchor: Optional[Tuple[float, float]] = None  # centre of the rank glyph, in image coordinates

    @property
    def center(self) -> Tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2.0, y + h / 2.0


RANK_LABELS = set("23456789TJQKA")
SUIT_LABELS = set("shdc")


class CardRecognizer:
    # Similarity to a taught shape that counts as the same glyph, and how far ahead of
    # every other label it must be. Suits are simple shapes that all look alike to some
    # degree (a spade scores high against clubs), so they need a closer match instead.
    EXACT = {"rank": (0.90, 0.12), "suit": (0.90, 0.05)}
    # With require_learned, a card that isn't a confirmed shape still counts as known when
    # the general recognizer is this sure: in testing, reads at 0.95 or more were never wrong.
    HOLE_GAP = 0.06  # lead needed over the next rank when the counters confirm a 6, 8 or 9
    HOLE_MIN_SCORE = 0.90
    HOLE_8_MIN_PX = 22  # a blurred 6 or 9 can close its gap and show two counters like an 8
    SURE = 0.95
    SURE_MIN_PX = 20  # ...and only for glyphs big enough to tell a 5 from a 6

    def __init__(self, learned_dir: Optional[Path] = None, threshold: float = 0.70,
                 require_learned: bool = False, builtin_deck: bool = True):
        self.threshold = threshold
        # With require_learned, a card is only reported as known when both its rank and
        # its suit match shapes the user confirmed for this deck, or the general
        # recognizer is very sure (SURE). Everything else comes back as a best guess for
        # the user to confirm once.
        self.require_learned = require_learned
        self.learned_dir = Path(learned_dir) if learned_dir else None
        self._lock = threading.Lock()
        self.ranks: TemplateSet = load_generic("rank")
        self.suits: TemplateSet = load_generic("suit")
        if builtin_deck and require_learned:
            # Only with exact cards on: in the plain mode, taught shapes from one deck
            # can pull another deck's cards towards a wrong rank.
            load_builtin_deck(self.ranks, "rank")
            load_builtin_deck(self.suits, "suit")
        if self.learned_dir:
            self.ranks.load_dir(self.learned_dir / "rank", learned=True)
            self.suits.load_dir(self.learned_dir / "suit", learned=True)

    # ------------------------------------------------------------------
    def is_pip(self, mask: np.ndarray) -> bool:
        """True when a glyph matches a suit symbol clearly better than any rank."""
        res = normalize_mask(mask)
        if res is None:
            return False
        with self._lock:
            ranks = self.ranks.scores(*res)
            suits = self.suits.scores(*res)
        if not ranks or not suits:
            return False
        return suits[0].score > 0.75 and suits[0].score > ranks[0].score + 0.1

    TILTS = (-24, -20, -16, -12, -8, -4, 4, 8, 12, 16, 20, 24)
    UPRIGHT_FILL = 0.93  # a lone upright card fills its bounding box; tilted or fanned cards don't
    MAX_TILT = 7.0  # degrees: a more turned index is not read as it is
    UPRIGHT_TILT = 5.0  # degrees: a rotated read counts only when the card ended up this straight

    def read(self, img: np.ndarray) -> List[CardReading]:
        out = []
        for g in find_cards(img, is_pip=self.is_pip):
            r = self.classify(g)
            if r is None:
                continue
            tilt = index_tilt(g)
            if not r.exact and g.blob_fill < self.UPRIGHT_FILL and tilt is not None and abs(tilt) > self.MAX_TILT:
                # A turned glyph can match the wrong template with high confidence (a tilted
                # spade looks like a club): only a read of the straightened card counts.
                r.confidence = min(r.confidence, round(self.threshold * 0.9, 3))
                r.code = None
            out.append(r)
        for r in out:
            if r.glyphs is not None and r.glyphs.rank is not None:
                gx, gy, gw, gh = r.glyphs.rank.box
                r.anchor = (gx + gw / 2.0, gy + gh / 2.0)
        if any(r.confidence < self.threshold for r in out):
            out = self._dedupe(self._retry_tilted(img, out))
        return out

    @staticmethod
    def _dedupe(readings: List[CardReading]) -> List[CardReading]:
        """Drop an uncertain read of a card that was also read with confidence (the same
        corner index seen before and after straightening). Two different cards always
        have their corner indexes well apart, even when fanned."""
        sure = [r for r in readings if r.code and r.anchor is not None]
        out = []
        for r in readings:
            if r.code is None and r.anchor is not None and r.glyphs is not None and r.glyphs.rank is not None:
                size = max(r.glyphs.rank.box[2], r.glyphs.rank.box[3])
                if any(math.hypot(r.anchor[0] - c.anchor[0], r.anchor[1] - c.anchor[1]) < 0.8 * size for c in sure):
                    continue
            out.append(r)
        return out

    @staticmethod
    def _rotate(patch: np.ndarray, angle: float, border) -> Tuple[np.ndarray, np.ndarray]:
        """Rotate counter-clockwise by `angle` degrees on an enlarged canvas; also return
        the transform from the rotated image back to the patch."""
        import cv2

        ph, pw = patch.shape[:2]
        if abs(angle) < 1e-6:
            return patch, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        m = cv2.getRotationMatrix2D((pw / 2.0, ph / 2.0), angle, 1.0)
        cos, sin = abs(m[0, 0]), abs(m[0, 1])
        nw, nh = int(ph * sin + pw * cos), int(ph * cos + pw * sin)
        m[0, 2] += nw / 2.0 - pw / 2.0
        m[1, 2] += nh / 2.0 - ph / 2.0
        rot = cv2.warpAffine(patch, m, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=border)
        return rot, cv2.invertAffineTransform(m)

    def _retry_tilted(self, img: np.ndarray, readings: List[CardReading]) -> List[CardReading]:
        """Many clients fan the hole cards at an angle. For uncertain cards in tilted or
        fanned blobs: measure how far each card is turned (from its corner index, at a
        few trial rotations), then read it straightened, three times at slightly
        different angles. A read counts only when at least two of them agree, and it
        gets the lower of their confidences: taking the best of many tries would
        inflate the confidence of cards that are simply hard to read."""
        result = list(readings)
        blobs = {r.glyphs.blob_box for r in readings
                 if r.glyphs and r.confidence < self.threshold and r.glyphs.blob_fill < self.UPRIGHT_FILL}
        for blob in blobs:
            bx, by, bw, bh = blob
            pad = int(0.25 * max(bw, bh))
            x0, y0 = max(0, bx - pad), max(0, by - pad)
            x1, y1 = min(img.shape[1], bx + bw + pad), min(img.shape[0], by + bh + pad)
            patch = img[y0:y1, x0:x1]
            border = tuple(int(v) for v in np.median(np.concatenate([patch[0], patch[-1]]), axis=0))

            # 1. where the cards are and how far each one is turned
            clusters: List[dict] = []
            for ang in (0,) + tuple(self.TILTS):
                rot, inv = self._rotate(patch, ang, border)
                for g in find_cards(rot, is_pip=self.is_pip, min_fill=0.45):
                    t = index_tilt(g)
                    if g.rank is None or t is None:
                        continue
                    gx, gy, gw, gh = g.rank.box
                    cx, cy = inv @ np.array([gx + gw / 2.0, gy + gh / 2.0, 1.0])
                    size = float(max(gw, gh))
                    for c in clusters:
                        if abs(c["x"] - cx) < 1.2 * size and abs(c["y"] - cy) < 1.2 * size:
                            c["tilts"].append(t - ang)
                            break
                    else:
                        clusters.append({"x": cx, "y": cy, "size": size, "tilts": [t - ang]})

            # 2. read each turned card straightened, three times
            for c in clusters:
                tilt = float(np.median(c["tilts"]))
                if abs(tilt) <= self.UPRIGHT_TILT:
                    continue  # upright: the normal read already had its chance
                reads = []
                for a in (-tilt - 2.5, -tilt, -tilt + 2.5):
                    rot, inv = self._rotate(patch, a, border)
                    for g in find_cards(rot, is_pip=self.is_pip, min_fill=0.45):
                        t = index_tilt(g)
                        if g.rank is None or t is None or abs(t) > self.UPRIGHT_TILT:
                            continue
                        gx, gy, gw, gh = g.rank.box
                        cx, cy = inv @ np.array([gx + gw / 2.0, gy + gh / 2.0, 1.0])
                        if abs(cx - c["x"]) > 1.2 * c["size"] or abs(cy - c["y"]) > 1.2 * c["size"]:
                            continue
                        r = self.classify(g)
                        if r is not None and r.guess:
                            reads.append(r)
                        break
                best = None
                exact = [r for r in reads if r.exact]
                if exact:
                    # one read matching shapes the user confirmed is enough
                    best = (exact[0], 1.0)
                else:
                    for guess in {r.guess for r in reads}:
                        same = sorted((r for r in reads if r.guess == guess), key=lambda r: -r.confidence)
                        if len(same) >= 2 and (best is None or same[1].confidence > best[1]):
                            best = (same[0], same[1].confidence)
                if best is None:
                    continue
                r, conf = best
                if r.glyphs is not None:
                    # if the user confirms this card, all three straightened reads are learned,
                    # so the next read matches whichever angle it lands on
                    r.glyphs.variants = [o.glyphs for o in reads if o is not r and o.glyphs is not None]
                cx, cy, size = x0 + c["x"], y0 + c["y"], c["size"]
                target = None
                for o in result:
                    if o.glyphs is None or o.glyphs.blob_box != blob or o.glyphs.rank is None:
                        continue
                    ox, oy, ow, oh = o.glyphs.rank.box
                    if abs(ox + ow / 2.0 - cx) < 1.5 * size and abs(oy + oh / 2.0 - cy) < 1.5 * size:
                        target = o
                        break
                if any(o.guess == r.guess and o.confidence >= self.threshold for o in result if o is not target):
                    continue  # that card is already read elsewhere
                if target is not None and target.confidence >= conf:
                    continue
                r.confidence = conf
                r.code = r.guess if conf >= self.threshold else None
                r.anchor = (cx, cy)
                r.box = target.box if target is not None else (int(cx - size), int(cy - size), int(3 * size),
                                                                 int(5 * size))
                if r.glyphs is not None:
                    r.glyphs.blob_box = blob
                if target is not None:
                    result[result.index(target)] = r
                else:
                    result.append(r)
        return sorted(result, key=lambda r: (r.box[0], r.box[1]))

    def _score(self, g: CardGlyphs, use_learned: bool = True):
        """(rank label, suit label, rank confidence, suit confidence, best rank match,
        best suit match, colour), or None when the glyphs aren't a card index."""
        with self._lock:
            rank_matches = self._match(self.ranks, g.rank, use_learned)
            suit_matches = self._match(self.suits, g.suit, use_learned)
            pip_matches = self._match(self.suits, g.pip, use_learned)
        if pip_matches and suit_matches and pip_matches[0].score > 0.6:
            # combine the small index suit with the big centre pip
            pip_scores = {m.label: m.score for m in pip_matches}
            suit_matches = sorted((Match(m.label, 0.5 * m.score + 0.5 * pip_scores.get(m.label, 0.0), m.learned)
                                   for m in suit_matches), key=lambda m: -m.score)
        pixels = [p.pixels for p in (g.rank, g.suit, g.pip) if p is not None and len(p.pixels)]
        color, strength = ink_color(np.concatenate(pixels) if pixels else np.zeros((0, 3), np.uint8))
        suit_matches = self._apply_color(suit_matches, color, strength)
        suit_matches = self._apply_structure(suit_matches, g)
        rank_matches = self._apply_rank_structure(rank_matches, g)
        if not rank_matches or not suit_matches:
            return None
        rb, rs = rank_matches[0], rank_matches[1].score if len(rank_matches) > 1 else -1.0
        sb, ss = suit_matches[0], suit_matches[1].score if len(suit_matches) > 1 else -1.0
        if rb.score < 0.35 and sb.score < 0.35:
            return None  # not a card index at all
        rank_conf = score_to_confidence(rb.score, rs)
        suit_conf = score_to_confidence(sb.score, ss)
        # Tiny glyphs are ambiguous (a 9 px "5" and "6" differ by a few pixels), unless
        # they match the user's own taught templates.
        if not rb.learned and g.rank is not None:
            rank_conf = round(rank_conf * _size_factor(g.rank.box[3], 5.0, 8.0), 3)
        if not sb.learned:
            suit_h = max([x.box[3] for x in (g.suit, g.pip) if x is not None] or [0])
            suit_conf = round(suit_conf * _size_factor(suit_h, 6.0, 10.0), 3)
        return rb.label, sb.label, rank_conf, suit_conf, rb, sb, color

    def _generic_agrees(self, g: CardGlyphs, rank: str, suit: str) -> bool:
        """The general recognizer alone, without any taught shapes, picks the same card.
        Taught shapes from one deck can pull another deck's card towards the wrong rank
        (a 6 towards a taught 9), and then the two disagree."""
        if g.rank is None or g.rank.box[3] < self.SURE_MIN_PX:
            return False
        scored = self._score(g, use_learned=False)
        if scored is None:
            return False
        r, s = scored[:2]
        return (r, s) == (rank, suit)

    def classify(self, g: CardGlyphs) -> Optional[CardReading]:
        if g.pip is not None and g.suit is not None and self._differ(g.pip, g.suit):
            g.pip = None  # a centre symbol in another colour belongs to an overlapping card
        scored = self._score(g)
        if scored is None:
            return None
        rank, suit, rank_conf, suit_conf, rb, sb, color = scored
        conf = round(min(rank_conf, suit_conf), 3)
        guess = rank + suit
        exact = self._exact(g)
        if exact is not None:
            # both glyphs are shapes the user confirmed for this deck
            guess = exact
            conf = rank_conf = suit_conf = 1.0
        elif self.require_learned and (conf < self.SURE or self._learned_disagrees(g, rank, suit)
                                       or not self._generic_agrees(g, rank, suit)):
            conf = min(conf, round(self.threshold * 0.9, 3))
        if self._colors_disagree(g):
            conf = 0.0  # a black rank over a red suit: the two glyphs belong to different cards
        return CardReading(
            code=guess if conf >= self.threshold else None,
            guess=guess,
            confidence=conf,
            rank_confidence=rank_conf,
            suit_confidence=suit_conf,
            box=g.box,
            color=color,
            glyphs=g,
            exact=exact is not None and conf >= 1.0,
        )

    def _exact(self, g: CardGlyphs) -> Optional[str]:
        """The card, if both its rank and its suit match taught shapes closely."""
        if g.rank is None or g.suit is None:
            return None
        rn, sn = normalize_mask(g.rank.mask), normalize_mask(g.suit.mask)
        if rn is None or sn is None:
            return None
        pn = normalize_mask(g.pip.mask) if g.pip is not None else None
        with self._lock:
            r_learned, r_any = self.ranks.label_scores(*rn)
            s_learned, s_any = self.suits.label_scores(*sn)
            p_learned, p_any = self.suits.label_scores(*pn) if pn is not None else ({}, {})
        if not r_learned or not s_learned:
            return None
        (r_min, r_gap), (s_min, s_gap) = self.EXACT["rank"], self.EXACT["suit"]

        rank = max(r_learned, key=r_learned.get)
        r_score = r_learned[rank]
        others = set(r_any) - {rank}
        sig = hole_signature(g.rank.mask) if rank in "689" else None
        if sig == rank and r_score >= self.HOLE_MIN_SCORE and (rank != "8" or g.rank.box[3] >= self.HOLE_8_MIN_PX):
            # a 6, 8 or 9 whose closed counters agree with its shape: a 6 can't be a 9
            # (its counter is low, a 9's is high) and the other way round
            r_gap = self.HOLE_GAP
            others -= {"6": {"9"}, "9": {"6"}}.get(rank, set())
        r_next = max((r_any[k] for k in others), default=-9.0)
        if r_score < r_min or r_score - r_next < r_gap:
            return None
        if rank in "35":
            cx = upper_band_center(g.rank.mask)
            if cx is not None and (rank == "3" and cx < 0.42 or rank == "5" and cx > 0.52):
                return None  # its shape says the other one of 3 and 5: ask instead

        suit = max(s_learned, key=s_learned.get)
        s_score = s_learned[suit]
        s_next = max((v for k, v in s_any.items() if k != suit), default=-9.0)
        if p_learned and max(p_learned, key=p_learned.get) == suit:
            # the big centre symbol agrees: judge the suit on both symbols together
            s_score = 0.5 * (s_score + p_learned[suit])
            s_next = max((0.5 * (s_any.get(k, -9.0) + p_any.get(k, -9.0)) for k in s_any if k != suit), default=-9.0)
        if s_score < s_min or s_score - s_next < s_gap:
            return None
        return rank + suit

    def _learned_disagrees(self, g: CardGlyphs, rank: str, suit: str) -> bool:
        """A shape the user confirmed for this deck is closer to another card than the
        general recognizer's answer: don't trust that answer."""
        for kind, glyph, label, ts, floor in (("rank", g.rank, rank, self.ranks, 0.75),
                                              ("suit", g.suit, suit, self.suits, 0.85)):
            if glyph is None:
                continue
            res = normalize_mask(glyph.mask)
            if res is None:
                continue
            with self._lock:
                best = ts.best_learned(*res)
            if best is not None and best[0].score >= floor and best[0].label != label:
                return True
        return False

    @staticmethod
    def _differ(a: Glyph, b: Glyph) -> bool:
        """Two glyphs clearly printed in different colours (black versus red, say)."""
        ac, as_ = ink_color(a.pixels)
        bc, bs = ink_color(b.pixels)
        return "unknown" not in (ac, bc) and ac != bc and min(as_, bs) >= 0.6

    @classmethod
    def _colors_disagree(cls, g: CardGlyphs) -> bool:
        return g.rank is not None and g.suit is not None and cls._differ(g.rank, g.suit)

    @staticmethod
    def _match(templates: TemplateSet, glyph: Optional[Glyph], use_learned: bool = True) -> List[Match]:
        if glyph is None:
            return []
        res = normalize_mask(glyph.mask)
        if res is None:
            return []
        return templates.scores(*res, use_learned=use_learned)

    @staticmethod
    def _apply_color(matches: List[Match], color: str, strength: float) -> List[Match]:
        allowed = COLOR_SUITS.get(color)
        if not allowed or not matches:
            return matches
        bonus, penalty = 0.08 * strength, 0.45 * strength
        adjusted = [Match(m.label, m.score + (bonus if m.label in allowed else -penalty)) for m in matches]
        return sorted(adjusted, key=lambda m: -m.score)

    @staticmethod
    def _apply_rank_structure(matches: List[Match], g: CardGlyphs) -> List[Match]:
        """Separate "2" from "3", which share their top half in many fonts, and "3" from
        "5", which share their bottom half."""
        if not matches or g.rank is None:
            return matches
        top = {m.label for m in matches[:2]}
        if top == {"3", "5"}:
            cx = upper_band_center(g.rank.mask)
            if cx is not None:
                d = float(np.clip((0.48 - cx) / 0.06, -1.5, 1.5)) * 0.06  # + looks like a 5, - like a 3
                matches = sorted((Match(m.label, m.score + (d if m.label == "5" else -d if m.label == "3" else 0.0),
                                        getattr(m, "learned", False)) for m in matches), key=lambda m: -m.score)
        if not {m.label for m in matches[:2]} & {"2", "3"}:
            return matches
        cx = lower_middle_center(g.rank.mask)
        if cx is None:
            return matches
        delta = float(np.clip((0.56 - cx) / 0.06, -1.5, 1.5)) * 0.06  # + looks like a 2, - like a 3
        adjusted = [Match(m.label, m.score + (delta if m.label == "2" else -delta if m.label == "3" else 0.0),
                          getattr(m, "learned", False)) for m in matches]
        return sorted(adjusted, key=lambda m: -m.score)

    @staticmethod
    def _apply_structure(matches: List[Match], g: CardGlyphs) -> List[Match]:
        if not matches:
            return matches
        candidates = [x for x in (g.pip, g.suit) if x is not None]
        if not candidates:
            return matches
        glyph = max(candidates, key=lambda x: x.box[3])  # the bigger symbol shows more detail
        upper, widest, height = suit_structure(glyph.mask)
        reliability = min(1.0, max(0.0, (height - 10) / 20.0))
        red = float(np.clip((widest - 0.42) / 0.06, -1.5, 1.5)) * 0.08  # + diamond, - heart
        black = float(np.clip((upper - 0.88) / 0.035, -1.5, 1.5)) * 0.08 * reliability  # + spade, - club
        delta = {"d": red, "h": -red, "s": black, "c": -black}
        return sorted((Match(m.label, m.score + delta.get(m.label, 0.0)) for m in matches), key=lambda m: -m.score)

    # ------------------------------------------------------------------
    def learn(self, glyphs: Optional[CardGlyphs], code: str) -> bool:
        """Remember the user's correction so this deck is recognised exactly next time."""
        if glyphs is None or len(code) != 2:
            return False
        rank, suit = code[0], code[1]
        learned_any = False
        with self._lock:
            for g in [glyphs] + list(glyphs.variants):
                for kind, glyph, label, ts in (("rank", g.rank, rank, self.ranks), ("suit", g.suit, suit, self.suits)):
                    if glyph is None:
                        continue
                    res = normalize_mask(glyph.mask)
                    if res is None:
                        continue
                    norm, aspect = res
                    ts.add(label, norm, aspect, learned=True)
                    if self.learned_dir:
                        save_template(self.learned_dir / kind, label, norm, aspect)
                    learned_any = True
        return learned_any
