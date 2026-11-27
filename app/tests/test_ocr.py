"""OCR adapters. Apple Vision can only run on a Mac, so its adapter is checked against a
stand-in that returns exactly what ocrmac 1.0's recognize(px=True) returns."""
import sys
import types

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.tests.synthetic import TEXT_BOLD_FONTS, find_font
from app.vision import ocr
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


def _amount_crop(text="2,450"):
    """A small crop holding one amount, like the ones the second read of each amount gets."""
    img = Image.new("RGB", (70, 26), (20, 20, 20))
    font = ImageFont.truetype(find_font(*TEXT_BOLD_FONTS), 16)
    ImageDraw.Draw(img).text((6, 3), text, fill=(255, 255, 255), font=font)
    return np.array(img)[:, :, ::-1].copy()


def test_rapidocr_never_turns_text_upside_down(monkeypatch):
    """The angle classifier read "$999" as "666$", so it is switched off. This checks that a
    real read on the installed RapidOCR never calls it, not just that a switch is set: a
    switch RapidOCR doesn't read would pass that check and leave the classifier on."""
    if not RapidOcrEngine.available():
        pytest.skip("RapidOCR not installed")
    RapidOcrEngine().read(_text_image())  # makes the shared engine
    engine = RapidOcrEngine._engine
    classify, calls = engine.text_cls, []

    def watched(*args, **kwargs):
        calls.append(1)
        return classify(*args, **kwargs)

    monkeypatch.setattr(engine, "text_cls", watched)
    texts = " | ".join(b.text for b in RapidOcrEngine().read(_text_image()))
    assert "1,250" in texts and "60" in texts
    assert calls == [], "the angle classifier ran"


def test_rapidocr_reads_a_small_amount_with_the_line_reader(monkeypatch):
    """The second read of each amount uses the recognition-only reader. On 1.4 the old name
    for it was missing, read_line quietly fell back to the full reader, and that read a
    2,450 stack as 45."""
    if not RapidOcrEngine.available():
        pytest.skip("RapidOCR not installed")

    def full_reader(self, image):
        raise AssertionError("read_line used the full reader")

    monkeypatch.setattr(RapidOcrEngine, "read", full_reader)
    text, score = RapidOcrEngine().read_line(_amount_crop("2,450"))
    assert text == "2,450" and score >= 0.5


@pytest.mark.parametrize("version, present, missing", [
    ("1.4.4", ["use_angle_cls", "text_rec"], "use_cls"),  # the 1.2 switch on a 1.4 version
    ("1.2.3", ["use_angle_cls", "text_rec"], "text_recognizer"),
])
def test_rapidocr_missing_setting_fails_loudly(monkeypatch, version, present, missing):
    """If RapidOCR renames a setting again, reading raises an error naming it (the app shows
    it as "OCR engine skipped") instead of reading badly without a word."""
    class RenamedRapidOCR:
        def __init__(self):
            for attr in present:
                setattr(self, attr, True)

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=RenamedRapidOCR))
    monkeypatch.setattr(ocr, "_rapidocr_version", lambda: version)
    monkeypatch.setattr(RapidOcrEngine, "_engine", None)
    monkeypatch.setattr(RapidOcrEngine, "_recognize", None)
    with pytest.raises(RuntimeError, match=f"RapidOCR {version} has no '{missing}'"):
        RapidOcrEngine().read(_text_image())
    with pytest.raises(RuntimeError, match=f"RapidOCR {version} has no '{missing}'"):
        RapidOcrEngine().read_line(_amount_crop())


def test_rapidocr_setting_names_follow_the_version():
    assert ocr.rapidocr_names("1.2.3") == ("use_angle_cls", "text_recognizer")
    assert ocr.rapidocr_names("1.3.19") == ("use_cls", "text_rec")  # 1.3 renamed both
    assert ocr.rapidocr_names("1.4.4") == ("use_cls", "text_rec")
