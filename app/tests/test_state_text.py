"""JSON model, structured text output and the privacy guard."""
import json
import socket

import pytest

from app.state.model import Action, Field, GameState, Player
from app.state.positions import assign_positions, position_names
from app.state.privacy import PrivacyError, assert_safe, check_outgoing_text
from app.state.text_format import card_name, facing_summary, parse_text, render_text


def spec_example_state() -> GameState:
    """The example from the brief: AsKh on the button, facing a 60 bet on Ah 8d 5c."""
    M = Field.manual
    st = GameState(
        street=M("flop"),
        hero_cards=[M("As"), M("Kh")],
        board=[M("Ah"), M("8d"), M("5c")],
        pot=M(120.0),
        blinds=M((5.0, 10.0)),
        hero_to_act=M(True),
        available_actions=M([Action("fold"), Action("call", 60), Action("raise", 240)]),
        to_call=M(60.0),
    )
    st.players = [
        Player(seat=0, is_hero=True, position=M("BTN"), stack=M(800.0), bet=M(0.0), in_hand=M(True), name="Hero"),
        Player(seat=1, position=M("SB"), stack=M(1140.0), bet=M(0.0), in_hand=M(False), name="RiverRat"),
        Player(seat=2, position=M("BB"), stack=M(950.0), bet=M(60.0), last_action=M(Action("bet", 60)), in_hand=M(True),
               name="Maverick"),
    ]
    return st


def test_text_matches_the_brief_example():
    text = render_text(spec_example_state())
    d = parse_text(text)
    assert d["GAME"] == "Texas Hold'em"
    assert d["HERO CARDS"] == "Ace of Spades, King of Hearts"
    assert d["HERO POSITION"] == "Button"
    assert d["STREET"] == "Flop"
    assert d["BOARD"] == "Ace of Hearts, 8 of Diamonds, 5 of Clubs"
    assert d["POT"] == "120"
    assert d["HERO STACK"] == "800"
    assert d["OPPONENT 1"] == {"Position": "Big Blind", "Stack": "950", "Bet": "60", "Last action": "Bet 60",
                               "Status": "In hand"}
    assert d["ACTION FACING HERO"] == "Call 60, raise, or fold"
    assert d["UNKNOWN FIELDS"] == "None"
    assert d["ACTIVE PLAYERS"] == "2"
    assert d["FOLDED OPPONENTS"] == "1 (Small Blind)"


def test_text_never_contains_ocr_free_text_or_guesses():
    st = spec_example_state()
    st.hero_cards[1] = Field(None, 0.4, "auto", guess="Kd")  # low-confidence read
    st.pot = Field(None, 0.3, "auto", guess=125.0)
    text = render_text(st)
    assert "Maverick" not in text and "RiverRat" not in text and "Hero CARDS" not in text
    assert "Kd" not in text and "King of Diamonds" not in text and "125" not in text
    d = parse_text(text)
    assert d["HERO CARDS"] == "Ace of Spades, UNKNOWN"
    assert d["POT"] == "UNKNOWN"
    assert "HERO CARD 2" in d["UNKNOWN FIELDS"] and "POT" in d["UNKNOWN FIELDS"]


def test_unknown_everything_is_still_well_formed():
    text = render_text(GameState())
    assert check_outgoing_text(text) == []
    d = parse_text(text)
    assert d["HERO CARDS"] == "UNKNOWN, UNKNOWN"
    assert d["STREET"] == "UNKNOWN"
    assert d["ACTION FACING HERO"] == "UNKNOWN"


def test_not_heros_turn():
    st = spec_example_state()
    st.hero_to_act = Field.manual(False)
    st.available_actions = Field.manual([])
    d = parse_text(render_text(st))
    assert d["HERO TO ACT"] == "No"
    assert d["AVAILABLE ACTIONS"] == "None (not hero's turn)"


def test_facing_summary_and_card_names():
    assert facing_summary([Action("check"), Action("bet")]) == "Check or bet"
    assert facing_summary([Action("fold"), Action("all-in", 800)]) == "All-in 800 or fold"
    assert card_name("Td") == "10 of Diamonds" and card_name("Qs") == "Queen of Spades"
    assert Action.parse("Raise to 1.5K") == Action("raise", 1500)
    assert Action.parse_list("Fold, Call 60, Raise to 240") == [Action("fold"), Action("call", 60), Action("raise", 240)]
    with pytest.raises(ValueError):
        Action.parse_list("Fold, Dance")


def test_json_round_trip():
    st = spec_example_state()
    st.hero_cards[1] = Field(None, 0.4, "auto", guess="Kd")
    data = json.loads(json.dumps(st.to_json()))
    back = GameState.from_json(data)
    assert render_text(back) == render_text(st)
    assert back.hero_cards[1].guess == "Kd"
    assert back.available_actions.value[1] == Action("call", 60)
    assert back.blinds.value == (5.0, 10.0)


def test_validation_catches_duplicates():
    st = spec_example_state()
    st.board[0] = Field.manual("As")
    assert any("twice" in p for p in st.validate())


def test_positions():
    assert position_names(2) == ["BTN/SB", "BB"]
    assert position_names(6) == ["BTN", "SB", "BB", "UTG", "HJ", "CO"]
    assert position_names(9) == ["BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO"]
    assert assign_positions([0, 1, 2, 3, 4, 5], 0) == {0: "BTN", 1: "SB", 2: "BB", 3: "UTG", 4: "HJ", 5: "CO"}
    assert assign_positions([0, 1, 2], 2) == {2: "BTN", 0: "SB", 1: "BB"}


# ----------------------------------------------------------------- privacy
@pytest.mark.parametrize("bad_line", [
    "POT: 120 PokerStars",
    "HERO CARDS: Ace of Spades, King of Hearts\nTABLE: Maverick's table",
    "BOARD: see https://example.com/table/123",
    "UNKNOWN FIELDS: None\nNOTE: /Users/kevin/Desktop/shot.png",
    "POT: 120\nCONTACT: kevin@example.com",
    "HERO STACK: 800 été",
    "  Position: Button",  # sub-line outside a block
])
def test_privacy_guard_blocks_anything_unexpected(bad_line):
    text = render_text(spec_example_state()) + "\n" + bad_line
    assert check_outgoing_text(text)
    with pytest.raises(PrivacyError):
        assert_safe(text)


def test_privacy_guard_accepts_real_output_including_math():
    from app.poker.calculator import compute

    st = spec_example_state()
    st.computed = compute(st, budget_ms=200)
    text = render_text(st)
    assert "LOCAL MATH" in text
    assert check_outgoing_text(text) == []


def test_recognition_and_text_need_no_network(monkeypatch):
    """Capture-from-file, recognition, maths and text all run with networking disabled."""
    from app.capture import ImageSource
    from app.poker.calculator import compute
    from app.recognition.recognizer import TableRecognizer
    from app.tests.synthetic import demo_table, render_table
    from app.vision.card_recognizer import CardRecognizer
    from app.vision.ocr import create_engine

    img, _ = render_table(demo_table())
    ocr = create_engine("auto")

    def no_network(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    src = ImageSource(img)
    crop = src.region_image((0, 0, *src.size))
    st = TableRecognizer(CardRecognizer(), ocr).recognize(crop).state
    st.computed = compute(st, budget_ms=200)
    text = render_text(st)
    assert check_outgoing_text(text) == []
    assert "Ace of Spades" in text
