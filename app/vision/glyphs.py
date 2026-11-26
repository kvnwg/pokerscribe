"""Glyph normalisation and template matching for card ranks and suits.

A glyph is a binary mask (ink pixels of one character). It is cropped, padded
to a square keeping its aspect ratio, scaled to 32x32 and compared with
templates by correlation. Generic templates ship with the app (rendered from
many fonts by tools/build_templates.py); learned templates are saved locally
when the user corrects a card, which makes recognition near exact for the
deck that user plays with.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

GLYPH_SIZE = 32
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
RANK_LABELS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]
SUIT_LABELS = ["s", "h", "d", "c"]
MAX_LEARNED_PER_LABEL = 60  # per rank or suit, across every deck the user has taught


def normalize_mask(mask: np.ndarray) -> Optional[Tuple[np.ndarray, float]]:
    """Return (32x32 float image in [0, 1], aspect w/h) or None for empty masks."""
    m = mask.astype(bool)
    ys, xs = np.nonzero(m)
    if xs.size < 4:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = m[y0:y1, x0:x1].astype(np.float32)
    h, w = crop.shape
    side = max(h, w)
    canvas = np.zeros((side, side), np.float32)
    oy, ox = (side - h) // 2, (side - w) // 2
    canvas[oy : oy + h, ox : ox + w] = crop
    interp = cv2.INTER_AREA if side > GLYPH_SIZE else cv2.INTER_LINEAR
    small = cv2.resize(canvas, (GLYPH_SIZE, GLYPH_SIZE), interpolation=interp)
    return np.clip(small, 0.0, 1.0), w / float(h)


def _unit(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32) - float(v.mean())
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-6 else v


def feature(norm: np.ndarray) -> np.ndarray:
    """Blurred, mean-centred, unit-length vector: dot products are correlations."""
    return _unit(cv2.GaussianBlur(norm, (5, 5), 1.0).reshape(-1))


def shape_features(norm: np.ndarray) -> Tuple[np.ndarray, float]:
    """Row/column fill profiles of the tight glyph box (aspect independent) and solidity.

    These separate shapes that pixel correlation finds similar, e.g. a spade's
    pointed top versus a club's round lobes."""
    m = norm > 0.5
    ys, xs = np.nonzero(m)
    if xs.size < 4:
        return np.zeros(32, np.float32), 1.0
    crop = m[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].astype(np.float32)
    small = cv2.resize(crop, (16, 16), interpolation=cv2.INTER_AREA)
    prof = _unit(np.concatenate([small.mean(axis=1), small.mean(axis=0)]))
    # area and hull measured on the same outline polygon (pixel counts would bias small glyphs)
    contours, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    area = sum(float(cv2.contourArea(c)) for c in contours)
    hull_area = float(cv2.contourArea(cv2.convexHull(np.vstack(contours)))) if contours else 0.0
    solidity = float(min(1.0, area / hull_area)) if hull_area > 0 else 1.0
    return prof, solidity


@dataclass
class Match:
    label: str
    score: float
    learned: bool = False  # best evidence came from the user's own corrected cards


# weights: (pixel correlation, profile correlation, solidity penalty, aspect penalty)
SCORING = {"rank": (0.75, 0.25, 0.6, 0.6), "suit": (0.45, 0.55, 1.6, 0.25)}


class TemplateSet:
    """All templates of one kind (ranks or suits)."""

    def __init__(self, kind: str):
        self.kind = kind
        self.labels: List[str] = []
        self.aspects: List[float] = []
        self.learned: List[bool] = []
        self._features: List[np.ndarray] = []
        self._profiles: List[np.ndarray] = []
        self._solidity: List[float] = []
        self._matrix: Optional[np.ndarray] = None
        self._pmatrix: Optional[np.ndarray] = None

    def __len__(self) -> int:
        return len(self.labels)

    def add(self, label: str, norm: np.ndarray, aspect: float, learned: bool = False) -> None:
        self.labels.append(label)
        self.aspects.append(float(aspect))
        self.learned.append(learned)
        self._features.append(feature(norm))
        prof, solidity = shape_features(norm)
        self._profiles.append(prof)
        self._solidity.append(solidity)
        self._matrix = None
        self._pmatrix = None

    def load_dir(self, directory: Path, learned: bool = False) -> int:
        """Files are named <label>_<aspect>_<anything>.png"""
        count = 0
        if not directory.is_dir():
            return 0
        for path in sorted(directory.rglob("*.png")):
            parts = path.stem.split("_")
            if len(parts) < 2:
                continue
            label = parts[0]
            try:
                aspect = float(parts[1])
            except ValueError:
                continue
            img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None or img.shape != (GLYPH_SIZE, GLYPH_SIZE):
                continue
            self.add(label, img.astype(np.float32) / 255.0, aspect, learned)
            count += 1
        return count

    def _final(self, norm: np.ndarray, aspect: float) -> np.ndarray:
        """Similarity of the glyph to every template (about 1.0 for an identical shape)."""
        if self._matrix is None:
            self._matrix = np.stack(self._features)
            self._pmatrix = np.stack(self._profiles)
        w_pix, w_prof, w_sol, w_asp = SCORING.get(self.kind, SCORING["rank"])
        prof, solidity = shape_features(norm)
        raw = w_pix * (self._matrix @ feature(norm)) + w_prof * (self._pmatrix @ prof)
        asp = np.asarray(self.aspects, np.float32)
        penalty = np.maximum(0.0, np.abs(np.log(max(aspect, 1e-3) / asp)) - 0.18) * w_asp
        penalty = penalty + w_sol * np.abs(np.asarray(self._solidity, np.float32) - solidity)
        return raw - penalty

    def learned_labels(self) -> set:
        return {label for label, is_learned in zip(self.labels, self.learned) if is_learned}

    def label_scores(self, norm: np.ndarray, aspect: float) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Best single score per label: (from taught templates, from any template)."""
        if not self.labels:
            return {}, {}
        final = self._final(norm, aspect).tolist()
        best_l: Dict[str, float] = {}
        best_any: Dict[str, float] = {}
        for label, sc, is_learned in zip(self.labels, final, self.learned):
            best_any[label] = max(best_any.get(label, -9.0), sc)
            if is_learned:
                best_l[label] = max(best_l.get(label, -9.0), sc)
        return best_l, best_any

    def best_learned(self, norm: np.ndarray, aspect: float) -> Optional[Tuple[Match, float]]:
        """The closest template the user taught (a shape from their own deck), and the
        best score of any other label: (match, runner-up score)."""
        if not any(self.learned):
            return None
        best_l, best_any = self.label_scores(norm, aspect)
        label, score = max(best_l.items(), key=lambda kv: kv[1])
        runner = max((v for k, v in best_any.items() if k != label), default=-9.0)
        return Match(label, score, True), runner

    def scores(self, norm: np.ndarray, aspect: float, use_learned: bool = True) -> List[Match]:
        """Best score per label, highest first. use_learned=False: the general templates only."""
        if not self.labels:
            return []
        final = self._final(norm, aspect)
        # Generic templates: average of the 3 best per label, so one odd font cannot
        # win alone. Learned templates come from the user's own deck: best single match.
        generic: Dict[str, List[float]] = {}
        learned: Dict[str, float] = {}
        for label, sc, is_learned in zip(self.labels, final.tolist(), self.learned):
            if is_learned:
                if use_learned:
                    learned[label] = max(learned.get(label, -9.0), sc + 0.03)
            else:
                generic.setdefault(label, []).append(sc)
        best: Dict[str, float] = {}
        for label, values in generic.items():
            top = sorted(values, reverse=True)[:3]
            best[label] = sum(top) / len(top)
        from_learned = set()
        for label, sc in learned.items():
            if sc > best.get(label, -9.0):
                best[label] = sc
                from_learned.add(label)
        return sorted((Match(k, v, k in from_learned) for k, v in best.items()), key=lambda m: -m.score)


def save_template(directory: Path, label: str, norm: np.ndarray, aspect: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    img = (np.clip(norm, 0, 1) * 255).astype(np.uint8)
    digest = hashlib.sha1(img.tobytes()).hexdigest()[:10]
    path = directory / f"{label}_{aspect:.3f}_{int(time.time())}_{digest}.png"
    ok, enc = cv2.imencode(".png", img)
    if ok:
        enc.tofile(str(path))
    # keep the folder small: drop the oldest files for this label
    files = sorted(directory.glob(f"{label}_*.png"), key=os.path.getmtime)
    for old in files[:-MAX_LEARNED_PER_LABEL]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def load_generic(kind: str) -> TemplateSet:
    """Shipped templates: app/vision/templates/<kind>.npz (built by tools/build_templates.py)."""
    ts = TemplateSet(kind)
    path = TEMPLATE_DIR / f"{kind}.npz"
    if path.exists():
        data = np.load(path, allow_pickle=False)
        for norm, aspect, label in zip(data["norms"], data["aspects"], data["labels"]):
            ts.add(str(label), norm.astype(np.float32) / 255.0, float(aspect))
    return ts


def load_builtin_deck(ts: TemplateSet, kind: str) -> int:
    """Shapes of a deck the app already knows, cut from real screenshots of one client
    (templates/deck_<kind>.npz, built by tools/build_deck.py). They count like shapes the
    user taught: a card that matches them closely is read exactly from the first hand.
    Cards from other decks don't match them closely, so they don't affect other tables."""
    path = TEMPLATE_DIR / f"deck_{kind}.npz"
    if not path.exists():
        return 0
    data = np.load(path, allow_pickle=False)
    for norm, aspect, label in zip(data["norms"], data["aspects"], data["labels"]):
        ts.add(str(label), norm.astype(np.float32) / 255.0, float(aspect), learned=True)
    return len(data["labels"])


def pack_templates(directory: Path, out_path: Path) -> int:
    """Pack a folder of <label>_<aspect>_*.png templates into one .npz file."""
    ts_norms, aspects, labels = [], [], []
    for path in sorted(directory.glob("*.png")):
        parts = path.stem.split("_")
        img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None or len(parts) < 2:
            continue
        ts_norms.append(img)
        aspects.append(float(parts[1]))
        labels.append(parts[0])
    np.savez_compressed(out_path, norms=np.stack(ts_norms).astype(np.uint8),
                        aspects=np.asarray(aspects, np.float32), labels=np.asarray(labels))
    return len(labels)


def top_two(matches: Sequence[Match]) -> Tuple[Optional[Match], float]:
    if not matches:
        return None, -1.0
    second = matches[1].score if len(matches) > 1 else -1.0
    return matches[0], second
