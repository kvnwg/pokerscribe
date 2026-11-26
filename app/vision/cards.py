"""Find face-up playing cards and extract their corner-index glyphs.

Works on any layout: card faces are found as bright, low-saturation, roughly
rectangular blobs. Inside each blob the corner index (rank above suit) is
located from the ink components near the top edge, which also separates
overlapping hole cards. Classification happens in card_recognizer.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

Box = Tuple[int, int, int, int]  # x, y, w, h


@dataclass
class Glyph:
    mask: np.ndarray  # bool, cropped to `box`
    box: Box  # image coordinates
    pixels: np.ndarray  # N x 3 BGR ink pixels, for colour


@dataclass
class CardGlyphs:
    box: Box
    rank: Optional[Glyph]
    suit: Optional[Glyph]
    blob_box: Box
    pip: Optional[Glyph] = None  # large centre suit symbol, a second opinion on the suit
    notes: List[str] = field(default_factory=list)
    blob_fill: float = 1.0  # face area / bounding box area: ~1 for an upright card, lower when tilted or fanned
    variants: List["CardGlyphs"] = field(default_factory=list)  # the same card read at nearby angles

    @property
    def center(self) -> Tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2.0, y + h / 2.0


@dataclass
class _Comp:
    x: int
    y: int
    w: int
    h: int
    area: int
    ids: List[int]

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def merged(self, other: "_Comp") -> "_Comp":
        x0, y0 = min(self.x, other.x), min(self.y, other.y)
        x1, y1 = max(self.right, other.right), max(self.bottom, other.bottom)
        return _Comp(x0, y0, x1 - x0, y1 - y0, self.area + other.area, self.ids + other.ids)


LIGHT_V = 175
LIGHT_S = 60


def light_mask(hsv: np.ndarray) -> np.ndarray:
    return ((hsv[..., 2] >= LIGHT_V) & (hsv[..., 1] <= LIGHT_S)).astype(np.uint8) * 255


PipTest = Callable[[np.ndarray], bool]


def find_cards(img: np.ndarray, min_height: int = 22, is_pip: Optional[PipTest] = None,
               min_fill: float = 0.7) -> List[CardGlyphs]:
    """Return card candidates sorted left to right.

    `is_pip(mask)` says whether a glyph looks like a suit symbol; such glyphs are
    never taken as a rank (e.g. the corner pip of a neighbouring fanned card).
    `min_fill` is how much of its bounding box a face must cover: lower it for
    images rotated on purpose, where a fanned pair can sit at a steep angle."""
    if img is None or img.ndim != 3 or img.shape[0] < min_height:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # No morphological opening here: the light strip between a corner glyph and the
    # card edge can be 1-2 px wide and must stay connected to the rest of the face.
    contours, _ = cv2.findContours(light_mask(hsv), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = img.shape[:2]
    cards: List[CardGlyphs] = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if h < min_height or w < min_height * 0.45 or (h > 0.97 * H and w > 0.9 * W):
            continue
        # Corner glyphs sit close to the card edge, so morphology can cut notches into
        # the face outline. The convex hull restores the full card shape.
        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        if hull_area < min_fill * w * h:
            continue
        if not 0.42 <= w / float(h) <= 3.2:
            continue
        found = _cards_in_blob(img, hsv, hull, (x, y, w, h), is_pip, _outside_color(img, hull, (x, y, w, h)))
        for c in found:
            c.blob_fill = round(hull_area / float(w * h), 3)
        cards.extend(found)
    if cards:
        # Cards on one table are all about the same size. Much smaller light shapes (chips,
        # bits of text) only pass the size check when the capture is large; drop them.
        tallest = max(c.blob_box[3] for c in cards)
        cards = [c for c in cards if c.blob_box[3] >= 0.4 * tallest]
    return sorted(cards, key=lambda c: (c.box[0], c.box[1]))


def _outside_color(img: np.ndarray, hull: np.ndarray, rect: Box, pad: int = 4) -> Optional[np.ndarray]:
    """Median colour of a thin ring just outside the blob: the table felt around a card."""
    x, y, w, h = rect
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.drawContours(m, [hull - np.array([[x0, y0]])], -1, 255, thickness=-1)
    ring = (cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=3) > 0) & (m == 0)
    px = img[y0:y1, x0:x1][ring]
    return np.median(px, axis=0) if len(px) >= 8 else None


def _cards_in_blob(img: np.ndarray, hsv: np.ndarray, cnt: np.ndarray, rect: Box,
                   is_pip: Optional[PipTest] = None, outside: Optional[np.ndarray] = None) -> List[CardGlyphs]:
    x, y, w, h = rect
    sub = img[y : y + h, x : x + w]
    sub_hsv = hsv[y : y + h, x : x + w]
    blob = np.zeros((h, w), np.uint8)
    cv2.drawContours(blob, [cnt - np.array([[x, y]])], -1, 255, thickness=-1)
    inner = cv2.erode(blob, np.ones((3, 3), np.uint8), iterations=1) > 0
    sat, val = sub_hsv[..., 1].astype(np.int16), sub_hsv[..., 2].astype(np.int16)
    is_light = (val >= LIGHT_V) & (sat <= LIGHT_S) & inner
    if is_light.sum() < 0.35 * max(1, inner.sum()):
        return []
    band_px = max(2, int(round(min(w, h) / 30.0)))
    band = (blob > 0) & ~(cv2.erode(blob, np.ones((3, 3), np.uint8), iterations=band_px) > 0)
    if not _outline_is_light(band, (val >= LIGHT_V - 25) & (sat <= LIGHT_S + 25)):
        return []
    face_v = float(np.median(val[is_light]))
    face_s = float(np.median(sat[is_light]))
    # generous thresholds: thin anti-aliased strokes of small glyphs must stay connected
    ink = inner & ((val < face_v - 45) | ((sat > face_s + 45) & (val > 40)))
    # but faint ink hugging the card border is edge shading or JPEG ringing, not a glyph
    dist = cv2.distanceTransform(blob, cv2.DIST_L2, 3)
    strong = (val < face_v - 90) | ((sat > face_s + 80) & (val > 40))
    ink &= (dist > 2.5) | strong
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    stats = _split_touching_index(labels, stats, h)
    min_area = max(5, int(0.0006 * w * h))
    comps: List[_Comp] = []
    separators: List[int] = []
    # Ink touching the outline that has the colour of the felt outside is background
    # showing through (between the strokes of white text, or between fanned cards).
    # Glyphs printed close to the card edge also touch the outline, but are ink-coloured.
    # It meets the outline along a stretch: a glyph printed close to the edge on a dark felt
    # (a serif K on a near-black table) can touch it at a pixel or two and is still ink.
    touching = set()
    if band.any() and outside is not None:
        ids, contact = np.unique(labels[band], return_counts=True)
        for i, n in zip(ids.tolist(), contact.tolist()):
            if i == 0 or i >= len(stats) or n < 3:
                continue
            if np.linalg.norm(np.median(sub[labels == i], axis=0) - outside) < 30:
                touching.add(i)
    for i in range(1, len(stats)):
        cx, cy, cw, ch, area = (int(v) for v in stats[i])
        if ch >= 0.6 * h and cw <= max(4, 0.06 * h):
            separators.append(cx + cw // 2)  # edge line of an overlapping card
            continue
        if area < min_area or ch < max(4, 0.06 * h):
            continue
        if i in touching:
            continue  # background showing through the outline (text strokes, gaps between fanned cards)
        comps.append(_Comp(cx, cy, cw, ch, area, [i]))
    if not comps:
        return []

    # top edge of the face at each column (handles staggered cards)
    col_has = inner.any(axis=0)
    top_profile = np.where(col_has, inner.argmax(axis=0), h).astype(np.int32)

    def gap_to_top(c: _Comp) -> int:
        lo, hi = max(0, c.x), min(w, c.right)
        return c.y - int(top_profile[lo:hi].min()) if hi > lo else c.y

    # glyph-like: near the top, plausible height, not a 1-2 px line (card edges, JPEG ringing)
    near_top = [c for c in comps if gap_to_top(c) <= 0.33 * h and 0.10 * h <= c.h <= 0.48 * h and c.w <= 0.75 * h
                and c.w >= max(2, 0.14 * c.h) and c.area >= 0.12 * c.w * c.h]
    near_top.sort(key=lambda c: c.x)

    # merge "1" + "0" into a single "10" glyph (the suit can sit between them in x order)
    merged_away: set = set()
    ranks: List[_Comp] = []
    for a in near_top:
        if id(a) in merged_away:
            continue
        partner = None
        if a.w < 0.62 * a.h:
            for b in near_top:
                if b is a or id(b) in merged_away or b.x <= a.x:
                    continue
                gap = b.x - a.right
                if (abs(a.y - b.y) < 0.25 * a.h and 0.7 < b.h / float(a.h) < 1.35 and -1 <= gap < 0.35 * a.h
                        and (partner is None or b.x < partner.x)):
                    partner = b
        if partner is not None:
            merged_away.add(id(partner))
            ranks.append(a.merged(partner))
        else:
            ranks.append(a)
    # a glyph with another candidate directly above it is a suit, not a rank
    ranks = [r for r in ranks if not any(
        o is not r and o.bottom <= r.y + 0.3 * r.h and o.x < r.right and o.right > r.x for o in ranks)]
    if is_pip is not None:
        ranks = [r for r in ranks if not is_pip(np.isin(labels[r.y: r.bottom, r.x: r.right], r.ids))]
    ranks.sort(key=lambda c: c.x)

    # Two passes: the usual layout (suit directly under the rank) claims suits first,
    # so a neighbouring card's corner pip cannot steal a suit with the "beside" rule.
    used_suits: set = set()
    indexes: List[Tuple[_Comp, Optional[_Comp]]] = []
    paired = set()
    for finder in (_suit_below, _suit_beside):
        for r in ranks:
            if id(r) in paired or any(id_ in used_suits for id_ in r.ids):
                continue
            suit = finder(r, comps, used_suits)
            if suit is not None:
                used_suits.update(suit.ids)
                indexes.append((r, suit))
                paired.add(id(r))
    if not indexes:
        # single card whose suit is not under the rank: fall back to the biggest pip
        if 0.5 <= w / float(h) <= 0.9 and ranks:
            r = min(ranks, key=lambda c: (c.x + c.y))
            rest = [c for c in comps if c.ids != r.ids and c.y > r.bottom - 0.2 * r.h and c.h >= 0.3 * r.h]
            if rest:
                indexes.append((r, max(rest, key=lambda c: c.area)))
        if not indexes:
            return []

    indexes.sort(key=lambda p: p[0].x)
    out: List[CardGlyphs] = []
    for k, (r, s) in enumerate(indexes):
        left = max(0, int(r.x - 0.12 * h))
        seps_left = [sx for sx in separators if sx <= r.x]
        if seps_left:
            left = max(left, max(seps_left))
        if k + 1 < len(indexes):
            right = max(left + 4, int(indexes[k + 1][0].x - 0.12 * h))
        else:
            right = w
        right = min(right, left + int(0.8 * h)) if k + 1 < len(indexes) else right
        top = int(top_profile[min(w - 1, max(0, int(r.cx)))])
        box = (x + left, y + top, max(4, right - left), max(4, h - top))
        pip = _pip(comps, r, s, left, right, used_suits) if s is not None else None
        out.append(
            CardGlyphs(
                box=box,
                rank=_glyph(sub, labels, r, x, y),
                suit=_glyph(sub, labels, s, x, y) if s is not None else None,
                blob_box=rect,
                pip=_glyph(sub, labels, pip, x, y) if pip is not None else None,
            )
        )
    return out


def _outline_is_light(band: np.ndarray, light: np.ndarray) -> bool:
    """A card face is light along its outline, though one side may be hidden (a name
    plate or chips over the bottom of the hole cards). White text on the felt is light
    only in places, so it fails this."""
    if not band.any():
        return True
    h, w = band.shape
    yy, xx = np.mgrid[0:h, 0:w]
    top, bottom = band & (yy < 0.35 * h), band & (yy > 0.65 * h)
    middle = band & ~top & ~bottom
    sides = {}
    for name, m in (("top", top), ("bottom", bottom), ("left", middle & (xx < 0.5 * w)), ("right", middle & (xx >= 0.5 * w))):
        sides[name] = float(light[m].mean()) if m.any() else 1.0
    if sum(v >= 0.6 for v in sides.values()) >= 3:
        return True
    return sides["top"] >= 0.85 and max(sides["left"], sides["right"]) >= 0.85


def _pip(comps: List[_Comp], r: _Comp, s: _Comp, left: int, right: int, used: set) -> Optional[_Comp]:
    """Biggest suit-shaped component in the card body, below the corner index."""
    best = None
    for c in comps:
        if set(c.ids) & (set(r.ids) | set(s.ids)) or any(i in used for i in c.ids):
            continue
        right_of_index = c.cx > max(r.right, s.right)
        if (c.y < s.bottom - 0.2 * s.h and not right_of_index) or c.y < r.y or c.x < left or c.right > right + 2:
            continue
        if c.h < 1.2 * s.h or not 0.55 <= c.w / float(c.h) <= 1.5:
            continue
        if best is None or c.area > best.area:
            best = c
    return best


def _split_touching_index(labels: np.ndarray, stats: np.ndarray, h: int) -> np.ndarray:
    """At small sizes (or after JPEG) a rank can touch the suit below it and form one
    tall component. Cut such components at their narrowest row."""
    extra = []
    next_id = len(stats)
    for i in range(1, len(stats)):
        x, y, w, ch, area = (int(v) for v in stats[i])
        if not (0.48 * h < ch < 0.9 * h and y < 0.3 * h and w < 0.5 * h):
            continue
        region = labels[y: y + ch, x: x + w]
        rows = (region == i).sum(axis=1)
        lo, hi = int(0.3 * ch), int(0.75 * ch)
        if hi <= lo:
            continue
        cut = lo + int(np.argmin(rows[lo:hi]))
        if rows[cut] > max(2, 0.25 * rows.max()):
            continue
        bottom = region[cut:] == i
        region[cut:][bottom] = next_id
        top_rows = np.nonzero(rows[:cut])[0]
        bot_rows = np.nonzero((region[cut:] == next_id).sum(axis=1))[0]
        if not len(top_rows) or not len(bot_rows):
            region[cut:][bottom] = i
            continue
        cols_top = np.nonzero((region[:cut] == i).any(axis=0))[0]
        cols_bot = np.nonzero((region[cut:] == next_id).any(axis=0))[0]
        stats[i] = [x + cols_top.min(), y + top_rows.min(), cols_top.max() - cols_top.min() + 1,
                    top_rows.max() - top_rows.min() + 1, int((region[:cut] == i).sum())]
        extra.append([x + cols_bot.min(), y + cut + bot_rows.min(), cols_bot.max() - cols_bot.min() + 1,
                      bot_rows.max() - bot_rows.min() + 1, int(bottom.sum())])
        next_id += 1
    if extra:
        stats = np.vstack([stats, np.asarray(extra, dtype=stats.dtype)])
    return stats


def _suit_below(r: _Comp, comps: List[_Comp], used: set) -> Optional[_Comp]:
    best, best_gap = None, None
    for c in comps:
        if c.ids == r.ids or any(i in used for i in c.ids) or set(c.ids) & set(r.ids):
            continue
        if c.y < r.y + 0.6 * r.h:
            continue
        gap = c.y - r.bottom
        if gap > 0.9 * r.h:
            continue
        if not (c.x < r.right + 0.35 * r.h and c.right > r.x - 0.35 * r.h):
            continue
        if not 0.35 * r.h <= c.h <= 1.5 * r.h:
            continue
        if best is None or gap < best_gap:
            best, best_gap = c, gap
    return best


def _suit_beside(r: _Comp, comps: List[_Comp], used: set) -> Optional[_Comp]:
    best, best_gap = None, None
    for c in comps:
        if set(c.ids) & set(r.ids) or any(i in used for i in c.ids):
            continue
        gap = c.x - r.right
        if gap < 0 or gap > 0.6 * r.h:
            continue
        if abs(c.cy - r.cy) > 0.4 * r.h or not 0.4 * r.h <= c.h <= 1.3 * r.h:
            continue
        if best is None or gap < best_gap:
            best, best_gap = c, gap
    return best


def _glyph(sub: np.ndarray, labels: np.ndarray, c: _Comp, ox: int, oy: int) -> Glyph:
    region = labels[c.y : c.bottom, c.x : c.right]
    mask = np.isin(region, c.ids)
    pixels = sub[c.y : c.bottom, c.x : c.right][mask]
    return Glyph(mask=mask, box=(ox + c.x, oy + c.y, c.w, c.h), pixels=pixels.reshape(-1, 3))


def ink_color(pixels: np.ndarray) -> Tuple[str, float]:
    """Classify glyph ink as black / red / blue / green. Returns (name, strength 0..1)."""
    if pixels is None or len(pixels) < 3:
        return "unknown", 0.0
    px = pixels.reshape(-1, 1, 3).astype(np.uint8)
    hsv = cv2.cvtColor(px, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    # use the most saturated / darkest half: anti-aliased edges are washed out
    order = np.argsort(-(hsv[:, 1] - 0.5 * hsv[:, 2]))
    core = hsv[order[: max(3, len(order) // 2)]]
    s_med, v_med = float(np.median(core[:, 1])), float(np.median(core[:, 2]))
    if s_med < 80 or v_med < 60:
        strength = min(1.0, (110 - min(110.0, v_med)) / 80 + 0.3) if v_med < 110 else 0.5
        return "black", float(min(1.0, strength))
    hue = core[:, 0]
    ang = hue * (np.pi / 90.0)
    mean_h = (np.degrees(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) / 2.0) % 180
    strength = float(min(1.0, (s_med - 60) / 100.0 + 0.4))
    if mean_h < 12 or mean_h > 158:
        return "red", strength
    if 35 <= mean_h <= 88:
        return "green", strength
    if 92 <= mean_h <= 135:
        return "blue", strength
    return "unknown", 0.2
