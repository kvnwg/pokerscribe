"""Exact card reading: closed counters of 6/8/9 and the built-in deck shapes."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.tests.synthetic import find_font
from app.vision.card_recognizer import CardRecognizer, hole_signature, rank_holes
from app.vision.glyphs import RANK_LABELS, SUIT_LABELS


def glyph(ch: str, size: int = 60, font: str = "DejaVuSans-Bold.ttf") -> np.ndarray:
    path = find_font(font)
    f = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    img = Image.new("L", (size * 2, size * 2), 255)
    ImageDraw.Draw(img).text((size // 2, size // 4), ch, font=f, fill=0)
    return np.array(img) < 128


def test_counters_tell_6_8_9_apart():
    assert hole_signature(glyph("6")) == "6"
    assert hole_signature(glyph("8")) == "8"
    assert hole_signature(glyph("9")) == "9"
    for ch in "2357JK":  # no closed counter, or none that looks like a 6, 8 or 9
        assert hole_signature(glyph(ch)) is None, ch
    assert len(rank_holes(glyph("0"))) == 1


def test_counters_are_not_trusted_on_tiny_glyphs():
    tiny = glyph("6", size=14)
    assert hole_signature(tiny) is None


def test_built_in_deck_is_complete_and_only_used_for_exact_cards():
    exact = CardRecognizer(require_learned=True)
    plain = CardRecognizer()
    assert exact.ranks.learned_labels() == set(RANK_LABELS)
    assert exact.suits.learned_labels() == set(SUIT_LABELS)
    assert not plain.ranks.learned_labels() and not plain.suits.learned_labels()
    assert not CardRecognizer(require_learned=True, builtin_deck=False).ranks.learned_labels()
