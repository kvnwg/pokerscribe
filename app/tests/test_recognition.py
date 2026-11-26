"""End-to-end recognition on synthetic tables (cards drawn with fonts the recognizer
has never seen). Rule checked everywhere: a value is either right or UNKNOWN."""
import pytest

from app.recognition.recognizer import TableRecognizer
from app.state.model import Action
from app.tests.synthetic import SynthPlayer, SynthTable, Theme, demo_table, find_font, held_out_rank_fonts, render_table
from app.vision.card_recognizer import CardRecognizer
from app.vision.ocr import RapidOcrEngine

pytestmark = pytest.mark.skipif(not RapidOcrEngine.available(), reason="RapidOCR not installed")
FONTS = held_out_rank_fonts()


@pytest.fixture(scope="module")
def recognizer():
    return TableRecognizer(CardRecognizer(), RapidOcrEngine(), threshold=0.70)


def known_or_unknown(field, expected):
    """A field must be either correct or UNKNOWN, never a wrong value."""
    return field.value is None or field.value == expected


def test_demo_table_matches_spec_example(recognizer):
    img, _ = render_table(demo_table())
    st = recognizer.recognize(img).state
    assert [c.value for c in st.hero_cards] == ["As", "Kh"]
    assert [c.value for c in st.board] == ["Ah", "8d", "5c"]
    assert st.street.value == "flop"
    assert st.pot.value == 120
    assert st.blinds.value == (5, 10)
    assert st.hero.position.value == "BTN" and st.hero.stack.value == 800
    assert st.to_call.value == 60
    assert st.hero_to_act.value is True
    assert [a.describe() for a in st.available_actions.value] == ["Fold", "Call 60", "Raise to 240"]
    in_hand = [p for p in st.opponents if p.in_hand.value]
    assert len(in_hand) == 1
    villain = in_hand[0]
    assert villain.position.value == "BB" and villain.stack.value == 950 and villain.bet.value == 60
    assert villain.last_action.value == Action("bet", 60)
    assert st.active_players().value == 2


def _nine_handed(theme):
    players = [SynthPlayer("Hero", "2,450", bet="30", action="Raise 30")] + [
        SynthPlayer(f"Player{i}", f"{1000 + 137 * i:,}", in_hand=i in (2, 7), bet={2: "10", 7: "30"}.get(i),
                    action={7: "Call"}.get(i)) for i in range(1, 9)]
    return SynthTable(players=players, hero_cards=["Qd", "Qc"], board=[], pot="Pot: 15", button=8,
                      action_buttons=[], pre_actions=["Check/Fold", "Call Any"], blinds_text="NL Hold'em 5/10",
                      theme=theme)


def test_nine_handed_preflop_not_hero_turn(recognizer):
    theme = Theme(rank_font=FONTS[1], felt=(32, 74, 140), felt_edge=(22, 50, 96), back=(40, 140, 60),
                  width=1400, height=900, text_size=16)
    img, _ = render_table(_nine_handed(theme))
    st = recognizer.recognize(img).state
    assert [c.value for c in st.hero_cards] == ["Qd", "Qc"]
    assert st.board == [] and st.street.value == "preflop"
    assert st.hero_to_act.value is False
    assert len(st.players) == 9
    # button on seat 8 -> hero (seat 0) is SB, seat 1 BB, seat 2 UTG ...
    assert known_or_unknown(st.hero.position, "SB")
    positions = [p.position.value for p in st.players]
    if all(positions):
        assert positions == ["SB", "BB", "UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN"]
    assert st.hero.stack.value == 2450
    assert known_or_unknown(st.pot, 15)


def test_turn_overlapping_hole_cards_four_colour(recognizer):
    theme = Theme(rank_font=FONTS[2], four_color=True, hero_overlap=0.4, card_w=70, card_h=98,
                  suit_font=find_font("NotoSerifCJK-Regular.ttc"))
    players = [SynthPlayer("Hero", "1,210", bet="200", action="Raise"), SynthPlayer("Ace", "455", bet="100", action="Bet 100"),
               SynthPlayer("Bob", "2,000", in_hand=False), SynthPlayer("Cat", "870", in_hand=False)]
    t = SynthTable(players=players, hero_cards=["Jc", "Td"], board=["9c", "8d", "2h", "Qs"], pot="Pot: 340", button=3,
                   action_buttons=[], theme=theme)
    img, _ = render_table(t)
    res = recognizer.recognize(img)
    st = res.state
    assert [c.value for c in st.hero_cards] == ["Jc", "Td"]
    assert [c.value for c in st.board] == ["9c", "8d", "2h", "Qs"]
    assert st.street.value == "turn"
    assert st.pot.value == 340
    assert known_or_unknown(st.hero.position, "SB")
    ace = st.players[1]
    assert ace.stack.value == 455 and ace.bet.value == 100
    assert st.to_call.value in (None, 0)  # hero already raised to 200 > 100


def test_river_scaled_and_jpeg(recognizer):
    theme = Theme(rank_font=FONTS[3], scale=0.8, jpeg_quality=80, felt=(120, 30, 36), felt_edge=(90, 20, 26), back=(30, 60, 160))
    players = [SynthPlayer("Hero", "640"), SynthPlayer("Zed", "1,990", bet="150", action="Bet 150"),
               SynthPlayer("Yan", "720", in_hand=False)]
    t = SynthTable(players=players, hero_cards=["7h", "6h"], board=["5h", "4c", "Kh", "2s", "9d"], pot="Pot: 410", button=1,
                   action_buttons=["Fold", "Call 150", "Raise to 600"], theme=theme)
    img, _ = render_table(t)
    st = recognizer.recognize(img).state
    for f, v in zip(st.hero_cards, ["7h", "6h"]):
        assert known_or_unknown(f, v)
    for f, v in zip(st.board, ["5h", "4c", "Kh", "2s", "9d"]):
        assert known_or_unknown(f, v)
    assert len(st.board) == 5 and st.street.value == "river"
    assert st.pot.value == 410
    assert st.to_call.value == 150
    assert [a.kind for a in st.available_actions.value] == ["fold", "call", "raise"]


def test_unreadable_things_become_unknown(recognizer):
    import cv2

    img, truth = render_table(demo_table())
    # smear the hero's second card and erase the pot label
    x, y, w, h = truth["card_boxes"]["hero1"]
    img[y:y + h, x:x + w] = cv2.GaussianBlur(img[y:y + h, x:x + w], (0, 0), 6)
    img[300:330, 560:720] = img[300, 300]
    st = recognizer.recognize(img).state
    assert st.hero_cards[0].value == "As"
    assert st.hero_cards[1].value is None  # unknown, not invented
    assert st.pot.value is None


def test_no_ocr_engine_leaves_amounts_unknown():
    img, _ = render_table(demo_table())
    res = TableRecognizer(CardRecognizer(), None).recognize(img)
    st = res.state
    assert [c.value for c in st.hero_cards] == ["As", "Kh"]
    assert st.pot.value is None and st.to_call.value is None
    assert any("No OCR" in w for w in res.warnings)


def test_learning_from_corrections(tmp_path):
    """A deck the generic templates read poorly becomes exact after teaching it."""
    import random

    import cv2
    import numpy as np
    from PIL import Image

    from app.tests.synthetic import draw_card

    th = Theme(card_w=40, card_h=56, rank_font=FONTS[4], jpeg_quality=70)
    deck = [r + s for r in "23456789TJQKA" for s in "shdc"]

    def strip(cards):
        img = Image.new("RGB", (len(cards) * 50 + 20, 90), (29, 112, 66))
        for i, c in enumerate(cards):
            draw_card(img, c, 10 + i * 50, 15, th)
        arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        return cv2.imdecode(cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 70])[1], cv2.IMREAD_COLOR)

    def by_slot(readings, n):
        """reading for each card slot (cards are drawn every 50 px from x=10)"""
        slots = {}
        for r in readings:
            k = int((r.center[0] - 10) // 50)
            if 0 <= k < n and (k not in slots or r.confidence > slots[k].confidence):
                slots[k] = r
        return [slots.get(k) for k in range(n)]

    rec = CardRecognizer(learned_dir=tmp_path)
    teach = ["As", "2h", "3d", "4c", "5s", "6h", "7d", "8c", "9s", "Th", "Jd", "Qc", "Ks"]
    for code, reading in zip(teach, by_slot(rec.read(strip(teach)), len(teach))):
        assert reading is not None
        rec.learn(reading.glyphs, code)  # what the correction screen does when the user fixes a card
    assert any((tmp_path / "rank").glob("*.png"))
    random.seed(3)
    test_cards = random.sample(deck, 20)
    reads = by_slot(rec.read(strip(test_cards)), 20)
    assert [r.guess for r in reads] == test_cards
    assert sum(r.code is not None for r in reads) >= 18
    # a fresh recognizer loads the saved templates
    again = CardRecognizer(learned_dir=tmp_path)
    assert [r.guess for r in by_slot(again.read(strip(test_cards)), 20)] == test_cards
