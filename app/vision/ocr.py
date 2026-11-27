"""Local OCR engines behind one interface. All of them run on this machine.

Order for "auto": RapidOCR (ONNX models bundled with the pip package; the engine the
recognizer is tested with), Apple Vision (macOS, via ocrmac; fast, selectable in
Settings), Tesseract (if installed). Each returns line-level boxes in the pixel
coordinates of the image passed in.
"""
from __future__ import annotations

import logging
import re
import shutil
import sys
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class TextBox:
    text: str
    confidence: float
    x: int
    y: int
    w: int
    h: int

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


class OcrEngine:
    name = "none"
    label = "No OCR"

    @classmethod
    def available(cls) -> bool:
        return False

    def read(self, image: np.ndarray) -> List[TextBox]:
        raise NotImplementedError

    def read_line(self, image: np.ndarray) -> Optional[Tuple[str, float]]:
        """Read a small crop holding one line of text: (text, confidence)."""
        boxes = sorted(self.read(image), key=lambda b: b.x)
        if not boxes:
            return None
        return "".join(b.text for b in boxes), min(b.confidence for b in boxes)

    # helpers shared by engines --------------------------------------------
    @staticmethod
    def _prepare(image: np.ndarray, target_min_height: int = 900) -> tuple:
        """Upscale small captures so 10-12 px labels become readable."""
        h = image.shape[0]
        scale = 1.0
        if h < target_min_height:
            scale = min(2.5, target_min_height / float(h))
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return image, scale

    @staticmethod
    def _scaled(box: TextBox, scale: float) -> TextBox:
        if scale == 1.0:
            return box
        return TextBox(box.text, box.confidence, int(round(box.x / scale)), int(round(box.y / scale)),
                       max(1, int(round(box.w / scale))), max(1, int(round(box.h / scale))))


class AppleVisionOcr(OcrEngine):
    """Apple's Vision framework through the `ocrmac` package (macOS only)."""

    name = "apple_vision"
    label = "Apple Vision (faster, experimental)"

    @classmethod
    def available(cls) -> bool:
        if sys.platform != "darwin":
            return False
        try:
            import ocrmac.ocrmac  # noqa: F401
            return True
        except Exception:
            return False

    def read(self, image: np.ndarray) -> List[TextBox]:
        from ocrmac import ocrmac
        from PIL import Image

        prepared, scale = self._prepare(image, 700)
        pil = Image.fromarray(cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB))
        results = ocrmac.OCR(pil, recognition_level="accurate").recognize(px=True)
        boxes = []
        for text, conf, (x1, y1, x2, y2) in results:
            text = " ".join(str(text).split())
            if not text:
                continue
            # Vision reports coarse confidences (often 0.5 for clean text); rescale so they
            # are comparable with the other engines' scores.
            conf = 0.75 + 0.25 * float(conf)
            boxes.append(self._scaled(TextBox(text, conf, int(x1), int(y1), int(x2 - x1), int(y2 - y1)), scale))
        return boxes


def _rapidocr_version() -> str:
    from importlib.metadata import version

    return version("rapidocr_onnxruntime")


def rapidocr_names(version: str) -> Tuple[str, str]:
    """What this RapidOCR version calls (the angle classifier's on/off switch, the
    recognition-only reader). 1.3 renamed both. Tested with 1.2.3 and 1.4.4, the versions
    requirements.txt pins."""
    major_minor = tuple(int(p) for p in re.findall(r"\d+", version)[:2])
    if major_minor >= (1, 3):
        return "use_cls", "text_rec"
    return "use_angle_cls", "text_recognizer"


class RapidOcrEngine(OcrEngine):
    """PaddleOCR models running on ONNX Runtime (rapidocr_onnxruntime)."""

    name = "rapidocr"
    label = "RapidOCR"
    _engine = None
    _recognize = None  # the engine's recognition-only reader
    _lock = threading.Lock()
    _line_failure_logged = False

    @classmethod
    def available(cls) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except Exception:
            return False

    @classmethod
    def _shared_engine(cls):
        """The one RapidOCR every read uses, made on first use. Call it holding _lock.

        It raises if this RapidOCR lacks a setting PokerScribe relies on. Carrying on
        without it is how 1.4 kept the angle classifier on and misread small amounts: the
        old names weren't there, and the code quietly did without them."""
        if cls._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            version = _rapidocr_version()
            switch, reader = rapidocr_names(version)
            engine = RapidOCR()
            for attr in (switch, reader):
                if not hasattr(engine, attr):
                    raise RuntimeError(f"RapidOCR {version} has no '{attr}', so app/vision/ocr.py doesn't "
                                       "work with it. Install the version requirements.txt pins.")
            # Table text is always upright. The angle classifier sometimes decides a crop
            # is upside down and turns "$999" into "666$", so it is switched off.
            setattr(engine, switch, False)
            cls._recognize = getattr(engine, reader)
            cls._engine = engine
        return cls._engine

    def read(self, image: np.ndarray) -> List[TextBox]:
        with RapidOcrEngine._lock:
            engine = self._shared_engine()
            prepared, scale = self._prepare(image, 700)
            result, _ = engine(prepared)
        boxes = []
        for item in result or []:
            # 1.2.x returns [box, text, score]; 1.4.x adds word-level details after the score
            points, text, score = item[0], item[1], item[2]
            pts = np.asarray(points, dtype=np.float32)
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            text = " ".join(str(text).split())
            if text:
                boxes.append(self._scaled(TextBox(text, float(score), int(x0), int(y0), int(x1 - x0), int(y1 - y0)), scale))
        return boxes


    def read_line(self, image: np.ndarray) -> Optional[Tuple[str, float]]:
        """Recognition only (no text detection): the whole crop is one line, so "$1,000"
        can't be split into "$1" and "000", and it takes a few milliseconds."""
        with RapidOcrEngine._lock:
            self._shared_engine()  # outside the try below: a missing setting must raise
            recognize = RapidOcrEngine._recognize
        try:
            with RapidOcrEngine._lock:
                res = recognize([image])
            items = res[0] if isinstance(res, tuple) else res
            text, score = items[0][0], float(items[0][1])
        except Exception as exc:
            # The full reader is the fallback, and it misreads small crops (2,450 as 45).
            if not RapidOcrEngine._line_failure_logged:
                RapidOcrEngine._line_failure_logged = True
                log.warning("RapidOCR's line reader failed (%s); reading crops with the full reader instead", exc)
            return super().read_line(image)
        text = " ".join(str(text).split())
        return (text, score) if text else None


class TesseractOcr(OcrEngine):
    name = "tesseract"
    label = "Tesseract"

    @classmethod
    def available(cls) -> bool:
        try:
            import pytesseract  # noqa: F401
        except Exception:
            return False
        return shutil.which("tesseract") is not None

    def read(self, image: np.ndarray) -> List[TextBox]:
        import pytesseract

        prepared, scale = self._prepare(image, 1200)
        gray = cv2.cvtColor(prepared, cv2.COLOR_BGR2GRAY)
        # Tesseract reads dark text on light backgrounds best; poker tables mostly
        # use light text on dark panels, so read both polarities and merge.
        found: List[TextBox] = []
        for img in (gray, 255 - gray):
            for box in self._read_one(pytesseract, img):
                if not any(_iou(box, o) > 0.3 for o in found):
                    found.append(box)
                else:
                    for i, o in enumerate(found):
                        if _iou(box, o) > 0.3 and box.confidence > o.confidence:
                            found[i] = box
        return [self._scaled(b, scale) for b in found if b.confidence >= 0.3]

    @staticmethod
    def _read_one(pytesseract, gray: np.ndarray) -> List[TextBox]:
        data = pytesseract.image_to_data(gray, config="--psm 11", output_type=pytesseract.Output.DICT)
        lines = {}
        for i, word in enumerate(data["text"]):
            word = (word or "").strip()
            conf = float(data["conf"][i])
            if not word or conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append((data["left"][i], data["top"][i], data["width"][i], data["height"][i], word, conf))
        boxes = []
        for words in lines.values():
            words.sort()
            # split a "line" where words are far apart (psm 11 groups loosely)
            groups, cur = [], [words[0]]
            for wd in words[1:]:
                prev = cur[-1]
                if wd[0] - (prev[0] + prev[2]) > 1.5 * max(prev[3], wd[3]):
                    groups.append(cur)
                    cur = [wd]
                else:
                    cur.append(wd)
            groups.append(cur)
            for g in groups:
                x0 = min(w[0] for w in g)
                y0 = min(w[1] for w in g)
                x1 = max(w[0] + w[2] for w in g)
                y1 = max(w[1] + w[3] for w in g)
                text = " ".join(w[4] for w in g)
                conf = sum(w[5] for w in g) / len(g) / 100.0
                boxes.append(TextBox(text, conf, x0, y0, x1 - x0, y1 - y0))
        return boxes


ENGINES = {cls.name: cls for cls in (AppleVisionOcr, RapidOcrEngine, TesseractOcr)}
AUTO_ORDER = ["rapidocr", "apple_vision", "tesseract"]


def available_engines() -> List[str]:
    return [name for name in AUTO_ORDER if ENGINES[name].available()]


def create_engine(preference: str = "auto") -> Optional[OcrEngine]:
    """Return the preferred engine if it is installed, otherwise the first available one."""
    if preference == "none":
        return None
    order = AUTO_ORDER if preference == "auto" else [preference] + [n for n in AUTO_ORDER if n != preference]
    for name in order:
        cls = ENGINES.get(name)
        if cls is not None and cls.available():
            return cls()
    return None


class FallbackOcr(OcrEngine):
    """Tries engines in order; if one fails at runtime it moves on and remembers that."""

    def __init__(self, preference: str = "auto"):
        self.preference = preference
        order = AUTO_ORDER if preference == "auto" else [preference] + [n for n in AUTO_ORDER if n != preference]
        self._engines = [ENGINES[n]() for n in order if n in ENGINES and ENGINES[n].available()]
        self.failures: List[str] = []

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._engines[0].name if self._engines else "none"

    @property
    def label(self) -> str:  # type: ignore[override]
        return self._engines[0].label if self._engines else "No OCR engine"

    def read(self, image: np.ndarray) -> List[TextBox]:
        while self._engines:
            engine = self._engines[0]
            try:
                return engine.read(image)
            except Exception as exc:  # broken install, missing model, OS error...
                log.warning("OCR engine %s failed: %s", engine.name, exc)
                self.failures.append(f"{engine.label}: {exc}")
                self._engines.pop(0)
        return []

    def read_line(self, image: np.ndarray) -> Optional[Tuple[str, float]]:
        if not self._engines:
            return None
        try:
            return self._engines[0].read_line(image)
        except Exception as exc:
            log.warning("OCR engine %s failed on a crop: %s", self._engines[0].name, exc)
            return None


def _iou(a: TextBox, b: TextBox) -> float:
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.right, b.right), min(a.bottom, b.bottom)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


_SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()
