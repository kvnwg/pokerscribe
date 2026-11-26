"""Local maths: hand descriptions, draws, ranges, equity, pot odds and call-or-fold verdicts."""
import pytest

from app.poker import hands
from app.poker.calculator import compute, pot_for_odds
from app.poker.decision import call_or_fold, ev_of_call
from app.poker.equity import equity
from app.poker.ranges import make_range, parse_range, preflop_percentile
from app.state.model import Action, Field, GameState, Player


def test_hand_descriptions():
    assert hands.describe(["As", "Kh", "Ah", "8d", "5c"]) == "Pair of Aces"
    assert hands.describe(["As", "8h", "Ah", "8d", "5c"]) == "Two Pair, Aces and Eights"
    assert hands.describe(["8s", "8h", "8d", "5c", "5h"]) == "Full House, Eights full of Fives"
    assert hands.describe(["As", "2s", "3h", "4d", "5c"]) == "Straight, Five high"
    assert hands.describe(["Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d"]) == "Royal Flush"
    assert hands.describe(["7h", "6h", "5h", "4c", "Kh", "2s", "9h"]) == "Flush, King high"
    assert hands.describe_preflop(["Qd", "Qc"]) == "Pocket Queens"
    assert hands.describe_preflop(["Kh", "As"]) == "Ace King offsuit"


def test_descriptions_agree_with_treys_categories():
    import random

    rng = random.Random(5)
    names = {1: ("Straight Flush", "Royal Flush"), 2: ("Four of a Kind",), 3: ("Full House",), 4: ("Flush",),
             5: ("Straight",), 6: ("Three of a Kind",), 7: ("Two Pair",), 8: ("Pair",), 9: ("High Card",)}
    for _ in range(2000):
        cards = rng.sample(hands.DECK, 7)
        text = hands.describe(cards)
        assert text.startswith(names[hands.category(cards[:2], cards[2:])]), (cards, text)


def test_draws_and_outs():
    assert hands.draws(["Ah", "Kh"], ["2h", "7h", "9c"]) == ["flush draw"]
    assert hands.draws(["9s", "8s"], ["7d", "6c", "2h"]) == ["open-ended straight draw"]
    assert hands.draws(["9s", "8s"], ["7d", "5c", "2h"]) == ["gutshot straight draw"]
    nxt, outs, river = hands.improvement(["9s", "8s"], ["7d", "6c", "2h"])
    assert outs >= 8 and 0.3 < river < 0.6


def test_board_pair_is_not_an_out():
    # 72 offsuit on A K Q: a third K or Q pairs the board, not the hero
    nxt, outs, _ = hands.improvement(["7c", "2d"], ["Ah", "Ks", "Qd"])
    assert outs == 6  # three 7s and three 2s


def test_range_parsing():
    assert len(parse_range("AA")) == 6
    assert len(parse_range("AKs")) == 4 and len(parse_range("AKo")) == 12 and len(parse_range("AK")) == 16
    assert len(parse_range("QQ+")) == 18
    assert len(parse_range("A2s+")) == 48
    assert len(parse_range("76s-54s")) == 12
    assert len(parse_range("22-55")) == 24
    assert len(parse_range("AhKh")) == 1
    assert len(parse_range("QQ+, QQ+")) == 18
    with pytest.raises(ValueError):
        parse_range("AK+x")
    assert make_range("any").combos is None
    assert 0.24 < make_range("medium").fraction < 0.27
    assert preflop_percentile("AA") < 0.01 and preflop_percentile("72o") > 0.9


def test_known_equities():
    assert abs(equity(["As", "Ah"], [], 1, None, budget_s=0.6).equity - 0.852) < 0.012
    assert abs(equity(["As", "Ah"], [], 1, parse_range("KK"), budget_s=0.6).equity - 0.82) < 0.012
    # river is exact: the nuts cannot lose
    r = equity(["Ah", "Kh"], ["Qh", "Jh", "Th", "2c", "3d"], 1, None)
    assert r.exact and r.equity == 1.0
    # turn against a range is exact too
    t = equity(["As", "Kh"], ["Ah", "8d", "5c", "2s"], 1, make_range("medium").combos)
    assert t.exact and t.stderr == 0.0


def test_pot_odds_and_verdicts():
    assert ev_of_call(0.25, 180, 60) == pytest.approx(0.0)
    assert call_or_fold(0.40, 0.0, 180, 60, exact=True).action == "call"
    assert call_or_fold(0.20, 0.0, 180, 60, exact=True).action == "fold"
    assert call_or_fold(0.251, 0.005, 180, 60, exact=True).action == "close"


def _river_spot(hero_cards, board, villain_bet, pot=100.0, hero_stack=1000.0, villain_stack=500.0):
    M = Field.manual
    st = GameState(street=M("river"), hero_cards=[M(c) for c in hero_cards], board=[M(c) for c in board],
                   pot=M(pot), to_call=M(villain_bet), hero_to_act=M(True),
                   available_actions=M([Action("fold"), Action("call", villain_bet)]))
    st.players = [Player(0, True, M("BB"), M(hero_stack), M(0.0), Field(), M(True)),
                  Player(1, False, M("BTN"), M(villain_stack), M(villain_bet), M(Action("bet", villain_bet)), M(True))]
    return st


def test_calculator_river_verdict_is_exact():
    st = _river_spot(["Ah", "Kh"], ["Qh", "Jh", "2h", "7c", "3d"], 100.0)  # nut flush
    out = compute(st, make_range("medium"), budget_ms=200)
    assert out["pot_odds"] == {"to_call": 100.0, "pot": 200.0, "required_equity": round(100 / 300, 4)}
    assert out["verdict"]["action"] == "call" and out["verdict"]["exact"]
    weak = _river_spot(["7d", "2c"], ["Ah", "Ks", "Qd", "Jc", "9h"], 100.0)
    assert compute(weak, make_range("tight"), budget_ms=200)["verdict"]["action"] == "fold"


def test_calling_more_than_stack_only_wins_matched_chips():
    st = _river_spot(["Ah", "Kh"], ["Qh", "Jh", "2h", "7c", "3d"], villain_bet=500.0, hero_stack=200.0)
    st.to_call = Field.manual(200.0)  # recogniser caps the call at the stack
    out = compute(st, make_range("medium"), budget_ms=200)
    # pot 100 + villain 500 bet, but 300 of it is returned: the hero can win 300
    assert out["pot_odds"]["to_call"] == 200.0 and out["pot_odds"]["pot"] == 300.0


def test_pot_for_odds_respects_included_bets():
    st = _river_spot(["Ah", "Kh"], ["Qh", "Jh", "2h", "7c", "3d"], 100.0)
    assert pot_for_odds(st) == 200.0
    st.pot_includes_bets = True
    assert pot_for_odds(st) == 100.0


def test_missing_values_mean_no_math():
    st = _river_spot(["Ah", "Kh"], ["Qh", "Jh", "2h", "7c", "3d"], 100.0)
    st.hero_cards[1] = Field()  # unknown card: nothing to compute
    assert compute(st) == {}
    st = _river_spot(["Ah", "Kh"], ["Qh", "Jh", "2h", "7c", "3d"], 100.0)
    st.pot = Field()
    out = compute(st, budget_ms=200)
    assert "pot_odds" not in out and "hand" in out


def test_decision_benchmark_river_and_turn():
    """Proper test of decision quality: where calling ends the betting the verdict
    must match the exact best decision, losing (almost) nothing to sampling noise."""
    from tools.eval_decisions import run

    totals, per = run(per_street=40, streets=("river", "turn"), seed=3, verbose=False)
    assert totals["wrong"] == 0
    assert totals["loss"] / totals["staked"] < 0.001  # under 0.1% of the chips at stake
    assert per["river"]["close"] == 0  # river equity is exact, never "too close"


def test_royal_flush_is_class_one():
    """Regression: treys calls a royal flush class 0, which made a royal flush lying on the
    board look like the player's own improvement over it (0 < 1) and broke the simulator's
    spot labels. Category is 1 for every straight flush, as board_category is."""
    from app.poker import advice

    assert hands.category(("As", "Ks"), ["Qs", "Js", "Ts"]) == 1
    board = ("As", "Ks", "Qs", "Js", "Ts")
    assert hands.category(("2c", "3d"), board) == hands.board_category(board) == 1
    assert not advice._top_pair_plus(("2c", "3d"), board)
    assert hands.CATEGORY[hands.category(("As", "Ks"), ["Qs", "Js", "Ts", "2d", "3c"])] == "Straight Flush"
