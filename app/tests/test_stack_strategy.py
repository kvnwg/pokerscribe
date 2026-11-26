"""Stack-size strategy: push or fold when short, the big stack's pressure, getting the money
in when committed, and the never-break rule that one short opponent is no reason to go all
in while a big stack is still to act."""
import pytest

from app.poker import advice
from app.poker.advice import advise, push_share
from app.state.model import Action

from .test_advice import table

FOLD, CALL, RAISE, CHECK, BET = Action("fold"), Action("call", 10), Action("raise"), Action("check"), Action("bet")
ALL_ON = {"push_chart": True, "eff_push": True, "bully": True,
          "reshove": {"EP": 0.08, "HJ": 0.10, "CO": 0.13, "BTN": 0.17, "SB": 0.20}, "commit": 1.0}


@pytest.fixture
def tuned(monkeypatch):
    def apply(**kw):
        for k, v in kw.items():
            monkeypatch.setitem(advice.TUNING, k, v)
    return apply


def folded_to(pos, hero, stacks, positions=("BTN", "SB", "BB", "UTG", "HJ", "CO")):
    """Everyone before you folded; blinds 5/10 posted."""
    order = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
    before = [p for p in order[:order.index(pos)] if p not in ("SB", "BB")]
    bets = {"SB": 5.0, "BB": 10.0}
    to_call = 10.0 - bets.get(pos, 0.0)
    actions = [FOLD, Action("call", to_call), RAISE] if to_call > 0 else [CHECK, RAISE]
    return table(hero, pos, positions=positions, stacks=stacks, bets=bets, folded=before, pot=0.0,
                 to_call=to_call, actions=actions)


def test_push_share_follows_the_charts():
    assert push_share(1, 10) == pytest.approx(0.58)  # heads-up jam-or-fold at 10 big blinds
    assert push_share(1, 8) == pytest.approx(0.628, abs=0.01)  # about 62% at 8
    assert push_share(2, 10) == pytest.approx(0.436)  # the button
    assert push_share(5, 3) == push_share(5, 5)  # shorter than the chart: its widest row
    assert push_share(3, 12) < push_share(3, 10)  # deeper is tighter


def test_short_small_blind_jams_wide(tuned):
    tuned(push_chart=True)
    stacks = {"SB": 80.0}  # 8 big blinds
    adv = advise(folded_to("SB", ("Kc", "5d"), stacks))
    assert adv.action == "all-in"
    adv = advise(folded_to("SB", ("7c", "2d"), stacks))
    assert adv.action == "fold"


def test_one_short_stack_never_makes_a_big_stack_go_all_in(tuned):
    """The rule that matters most: the small blind is short but the big blind is deep."""
    tuned(**ALL_ON)
    for hand in [("Kc", "5d"), ("7c", "2d"), ("Jc", "8d"), ("Ah", "3c"), ("9s", "8s")]:
        adv = advise(folded_to("BTN", hand, {"BTN": 1000.0, "SB": 60.0, "BB": 1000.0}))
        assert adv.action != "all-in", (hand, adv.headline)
        if adv.amount is not None:
            assert adv.amount <= 40, (hand, adv.headline)  # a normal open, nothing bigger


def test_raise_only_their_stack_when_everyone_left_is_short(tuned):
    tuned(push_chart=True, eff_push=True)
    adv = advise(folded_to("BTN", ("Ah", "9c"), {"BTN": 1000.0, "SB": 60.0, "BB": 80.0}))
    assert adv.action == "raise"
    assert adv.amount == 90  # the big blind's 80 behind plus its blind: all anyone left can call
    assert "puts them all in" in adv.reason


def test_the_big_stack_opens_wider_against_short_stacks(tuned):
    tuned(bully=True)
    hand = ("Kc", "9d")  # a button open, not a cutoff open
    short = {"CO": 1500.0, "BTN": 250.0, "SB": 200.0, "BB": 280.0}  # 25, 20.5 and 29 big blinds
    adv = advise(folded_to("CO", hand, short))
    assert adv.action == "raise" and adv.amount == 25  # the normal size
    deep_button = dict(short, BTN=1500.0)  # a big stack is still to act: no bullying
    assert advise(folded_to("CO", hand, deep_button)).action == "fold"


def test_short_reshove_against_a_button_open(tuned):
    tuned(reshove={"EP": 0.08, "HJ": 0.10, "CO": 0.13, "BTN": 0.17, "SB": 0.20})
    def spot(hand):
        st = table(hand, "BB", stacks={"BB": 150.0, "BTN": 1000.0}, bets={"BTN": 25.0, "SB": 5.0, "BB": 10.0},
                   folded=["UTG", "HJ", "CO", "SB"], last={"BTN": Action("raise", 25)}, pot=0.0, to_call=15.0,
                   actions=[FOLD, Action("call", 15), RAISE])
        return advise(st)
    assert spot(("Ah", "7c")).action == "all-in"  # in the top 17%, wider at 15 big blinds
    assert spot(("Jc", "4d")).action == "fold"


def test_committed_top_pair_goes_all_in(tuned):
    tuned(commit=1.0)
    def spot(stack):
        st = table(("Ah", "Kd"), "BTN", board=("Ks", "7c", "2d"), stacks={"BTN": stack, "BB": 400.0},
                   bets={"BB": 60.0}, folded=["UTG", "HJ", "CO", "SB"], last={"BB": Action("bet", 60)},
                   pot=120.0, to_call=60.0, actions=[FOLD, Action("call", 60), RAISE])
        return advise(st)
    adv = spot(200.0)  # 140 left behind after calling into a pot of 240: committed
    assert adv.action == "all-in" and adv.amount == 200
    assert spot(2000.0).action == "call"  # deep: just call


def test_no_commit_shove_when_they_are_all_in(tuned):
    tuned(commit=1.0)
    st = table(("Ah", "Kd"), "BTN", board=("Ks", "7c", "2d"), stacks={"BTN": 200.0, "BB": 0.0},
               bets={"BB": 60.0}, folded=["UTG", "HJ", "CO", "SB"], last={"BB": Action("all-in", 60)},
               pot=120.0, to_call=60.0, actions=[FOLD, Action("call", 60)])
    assert advise(st).headline.startswith("CALL")


@pytest.mark.parametrize("hero,board,want", [
    (("Ah", "Kd"), ("Ks", "7c", "2d"), True),  # top pair
    (("Qh", "Qd"), ("Js", "7c", "2d"), True),  # overpair
    (("9h", "9d"), ("Js", "7c", "2d"), False),  # underpair
    (("Ah", "7d"), ("Ks", "7c", "2d"), False),  # middle pair
    (("Kh", "7d"), ("Ks", "7c", "2d"), True),  # two pair
    (("Ah", "Qd"), ("Ks", "Kc", "2d"), False),  # only the board's pair
    (("Qh", "Qd"), ("8s", "8c", "3d"), True),  # overpair on a paired board
])
def test_top_pair_plus(hero, board, want):
    assert advice._top_pair_plus(hero, board) is want


def test_geometric_sizing():
    # (1 + 2f) ** 3 = 1 + 2 * SPR: SPR 13 on the flop is a pot-size bet each street
    st = table(("Ah", "Ad"), "BTN", board=("Ks", "7c", "2d"), stacks={"BTN": 1300.0, "BB": 1300.0}, bets={},
               folded=["UTG", "HJ", "CO", "SB"], pot=100.0, to_call=0.0, actions=[CHECK, BET])
    s = advice._spot(st, {}, ("Ah", "Ad"), ("Ks", "7c", "2d"))
    assert advice._geometric(s) == pytest.approx(1.0)
    s.eff = 300.0  # SPR 3: about 46% of the pot
    assert advice._geometric(s) == pytest.approx(((1 + 2 * 3) ** (1 / 3) - 1) / 2)


# ------------------------------------------------------------------ semi-bluffs
def checked_to(hero, board, villain_style=None, pot=100.0):
    st = table(hero, "BTN", board=board, stacks={"BTN": 1000.0, "BB": 1000.0}, bets={},
               folded=["UTG", "HJ", "CO", "SB"], last={"BB": Action("check")}, pot=pot, to_call=0.0,
               actions=[CHECK, BET])
    if villain_style:
        for p in st.players:
            if p.position.value == "BB":
                p.style = villain_style
    return st


def test_no_turn_semibluff_with_one_draw(tuned):
    """The user's spot: the turn, no pair (the ace is on the board), a flush draw only."""
    tuned(semibluff_turn="combo")
    adv = advise(checked_to(("Qh", "9h"), ("Ah", "7h", "2c", "4s")))
    assert adv.action == "check", adv.headline


def test_turn_semibluff_with_a_combo_draw_names_the_draw_and_its_odds(tuned):
    tuned(semibluff_turn="combo")
    adv = advise(checked_to(("9h", "8h"), ("Th", "7h", "2c", "3s")))
    assert adv.action == "bet" and adv.amount
    assert "flush draw and a straight draw" in adv.reason
    assert "about 1 in 3 to hit on the river" in adv.reason


def test_flop_semibluff_says_the_chance_to_hit():
    adv = advise(checked_to(("Qh", "9h"), ("Ah", "7h", "2c")))
    assert adv.action == "bet"
    assert "flush draw (about 1 in 3 to hit by the river)" in adv.reason


def test_never_semibluff_a_calling_station():
    adv = advise(checked_to(("Qh", "9h"), ("Ah", "7h", "2c"), villain_style="station"))
    assert adv.action == "check"


# ------------------------------------------------------------------ sizes by expected value
def test_ev_sizing_gives_a_size_and_says_why(tuned):
    tuned(ev_sizing=True)
    for hero in [("Ah", "Ad"), ("As", "9c"), ("7s", "7c")]:
        adv = advise(checked_to(hero, ("Ac", "7d", "2s"), pot=100.0))
        if adv.action == "bet":
            assert adv.amount is not None and 30 <= adv.amount <= 100, adv.headline


# ------------------------------------------------------------------ the baseline
def test_defaults_are_the_frozen_baseline():
    """The defaults change only with credible paired evidence (docs/research/experiments.md).
    Whoever changes one records the new baseline in docs/research/baseline_tuning.json."""
    import json
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "research", "baseline_tuning.json")
    with open(path) as f:
        baseline = json.load(f)
    current = json.loads(json.dumps(advice.TUNING))  # tuples become lists, as in the file
    assert current == baseline
