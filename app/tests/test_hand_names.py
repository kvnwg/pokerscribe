"""The hand is named from your side: a card on the board belongs to everyone."""
from app.poker import hands
from app.poker.calculator import compute
from app.tests.test_advice import table


def test_ace_on_the_board_is_not_your_ace():
    assert hands.describe_hand(["Qh", "9h"], ["Ad", "7c", "2s"]) == "No pair, Queen high"
    assert "ace is on the board" in hands.shared_note(["Qh", "9h"], ["Ad", "7c", "2s"])
    assert hands.describe_hand(["Ah", "9h"], ["Kd", "7c", "2s"]) == "Ace high, no pair"
    assert hands.shared_note(["Ah", "9h"], ["Kd", "7c", "2s"]) == ""
    assert hands.describe_hand(["Ah", "9h"], ["Ad", "7c", "2s"]) == "Pair of Aces"


def test_instruction_names_the_hand_from_your_side():
    st = table(["Qh", "9h"], "BTN", ["Ad", "7c", "2s", "Kh"], stacks={"BTN": 300.0, "BB": 400.0},
               bets={}, folded=["SB", "UTG", "HJ", "CO"], pot=40, blinds=(1, 2), to_call=0)
    out = compute(st, budget_ms=100)
    assert out["hand"] == "No pair, Queen high"
    assert "ace is on the board" in out["hand_note"]
