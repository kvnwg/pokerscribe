"""Hole cards drawn fanned at an angle, as many clients show them."""
import random

from app.tests.synthetic import held_out_rank_fonts, render_fanned
from app.vision.card_recognizer import CardRecognizer, index_tilt
from app.vision.cards import find_cards

DECK = [r + s for r in "23456789TJQKA" for s in "shdc"]


def test_index_tilt_measures_the_turn():
    img = render_fanned(["9s", "4s"], [16, -8], h=120)
    tilts = [t for t in (index_tilt(g) for g in find_cards(img)) if t is not None]
    assert any(-12 < t < -4 for t in tilts) and any(12 < t < 20 for t in tilts)


def test_fanned_cards_are_read_or_unknown_never_wrong():
    rec = CardRecognizer()
    fonts = held_out_rank_fonts()
    rng = random.Random(11)
    read = total = 0
    for _ in range(16):
        cards = rng.sample(DECK, 2)
        img = render_fanned(cards, [rng.choice([8, 12, 16]), rng.choice([-8, -12, -16, -20])],
                            h=rng.choice([110, 140]), font=rng.choice(fonts))
        known = [r.code for r in rec.read(img) if r.code]
        assert all(c in cards for c in known), (cards, known)
        read += sum(1 for c in cards if c in known)
        total += 2
    assert read >= 0.5 * total


def test_confirmed_fanned_cards_are_not_asked_again(tmp_path):
    """After the user confirms fanned hole cards once, the next reads of that table are
    exact (they used to come back unclear and ask again)."""
    import cv2

    fonts = held_out_rank_fonts()
    rng = random.Random(4)
    asked = 0
    for _ in range(6):
        cards = rng.sample(DECK, 2)
        angles = [rng.choice([10, 14, 18]), rng.choice([-10, -14, -18])]
        font, h = rng.choice(fonts), rng.choice([110, 140])
        learned = tmp_path / str(rng.random())
        rec = CardRecognizer(learned_dir=learned, require_learned=True)
        first = sorted(rec.read(render_fanned(cards, angles, h=h, font=font)), key=lambda r: r.box[0])
        # a new deck: a card is only shown before it's checked when it's certain, and then right
        assert all(r.code in (None, code) for r, code in zip(first, cards))
        for r, code in zip(first, cards):
            rec.learn(r.glyphs, code)
        for shift in (0, 1):
            img = render_fanned(cards, angles, h=h, font=font)
            if shift:
                img = cv2.copyMakeBorder(img, shift, 0, shift, 0, cv2.BORDER_REPLICATE)
            known = [r.code for r in rec.read(img) if r.code]
            assert all(c in cards for c in known)  # never wrong
            asked += sum(1 for c in cards if c not in known)
    assert asked <= 2  # out of 24 card reads
