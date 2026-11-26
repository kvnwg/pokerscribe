"""OCR adapters. Apple Vision can only run on a Mac, so its adapter is checked against a
stand-in that returns exactly what ocrmac 1.0's recognize(px=True) returns."""
import sys
import types

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.tests.synthetic import TEXT_BOLD_FONTS, find_font
from app.vision.ocr import AppleVisionOcr, FallbackOcr, RapidOcrEngine, TesseractOcr, create_engine


def _text_image():
    img = Image.new("RGB", (640, 120), (20, 90, 50))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(find_font(*TEXT_BOLD_FONTS), 24)
    d.text((20, 20), "Pot: 1,250", fill=(255, 255, 255), font=f)
    d.text((340, 20), "Call 60", fill=(255, 255, 255), font=f)
    return np.array(img)[:, :, ::-1].copy()


def test_apple_vision_adapter_maps_coordinates(monkeypatch):
    calls = {}

    class FakeOCR:
        def __init__(self, image, recognition_level="accurate", **kw):
            calls["size"] = image.size
            calls["level"] = recognition_level

        def recognize(self, px=False):
            assert px is True
            w, h = calls["size"]
            # (text, confidence, (x1, y1, x2, y2)) in pixels of the image it was given
            return [("Pot: 1,250", 0.98, (0.03 * w, 0.15 * h, 0.25 * w, 0.45 * h))]

    fake = types.ModuleType("ocrmac")
    fake.ocrmac = types.SimpleNamespace(OCR=FakeOCR)
    monkeypatch.setitem(sys.modules, "ocrmac", fake)
    boxes = AppleVisionOcr().read(_text_image())
    assert calls["level"] == "accurate"
    assert len(boxes) == 1 and boxes[0].text == "Pot: 1,250"
    b = boxes[0]
    # mapped back to the original 640 x 120 image even though it was upscaled for OCR
    assert abs(b.x - 19) <= 2 and abs(b.y - 18) <= 2 and abs(b.w - 141) <= 3 and abs(b.h - 36) <= 3


def test_fallback_moves_on_when_an_engine_breaks(monkeypatch):
    if not RapidOcrEngine.available():
        pytest.skip("RapidOCR not installed")
    fb = FallbackOcr("rapidocr")

    class Broken:
        name, label = "broken", "Broken engine"

        def read(self, image):
            raise RuntimeError("model file missing")

    fb._engines.insert(0, Broken())
    boxes = fb.read(_text_image())
    assert any("1,250" in b.text for b in boxes)
    assert fb.failures and "Broken engine" in fb.failures[0]


@pytest.mark.parametrize("engine", ["rapidocr", "tesseract"])
def test_local_engines_read_amounts(engine):
    cls = {"rapidocr": RapidOcrEngine, "tesseract": TesseractOcr}[engine]
    if not cls.available():
        pytest.skip(f"{engine} not installed")
    texts = " | ".join(b.text for b in cls().read(_text_image()))
    assert "1,250" in texts and "60" in texts


def test_create_engine_respects_none():
    assert create_engine("none") is None


def test_amounts_are_double_checked():
    """Every amount is read a second time from just that spot; only agreeing reads count."""
    import numpy as np

    from app.recognition.recognizer import TableRecognizer
    from app.vision.card_recognizer import CardRecognizer
    from app.vision.ocr import OcrEngine, TextBox

    answers = {50: ["$1,000"], 100: ["$999"], 150: ["$998"], 200: ["$450"], 250: ["$710", "$720"]}

    class SpotReader(OcrEngine):
        name = "spot"
        calls = {}

        def read(self, image):
            return []

        def read_line(self, image):
            key = int(image.max())
            seq = answers.get(key, [])
            i = self.calls.get(key, 0)
            self.calls[key] = i + 1
            return (seq[min(i, len(seq) - 1)], 0.9) if seq else None

    img = np.zeros((220, 200, 3), np.uint8)
    first_reads = [("$1,000", 50), ("$999", 100), ("5998", 150), ("$460", 200), ("$700", 250)]
    boxes = []
    for k, (text, level) in enumerate(first_reads):
        y = 10 + 42 * k
        img[y:y + 20, 20:80] = level
        boxes.append(TextBox(text, 0.8, 20, y, 60, 20))
    out = TableRecognizer(CardRecognizer(), SpotReader())._verify_amounts(img, boxes)
    assert [b.text for b in out[:4]] == ["$1,000", "$999", "$998", "$450"]  # "5998" was "$998"
    assert all(b.confidence >= 0.8 for b in out[:4])
    assert out[4].confidence <= 0.2  # three different reads: left UNKNOWN


def test_rapidocr_never_turns_text_upside_down():
    from app.vision.ocr import RapidOcrEngine

    if not RapidOcrEngine.available():
        pytest.skip("RapidOCR not installed")
    import numpy as np

    RapidOcrEngine().read(np.full((60, 200, 3), 255, np.uint8))
    assert RapidOcrEngine._engine.use_angle_cls is False  # it read "$999" as "666$"
