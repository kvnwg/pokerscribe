"""The one-line instruction shown in the simple view."""
from typing import Dict, Optional, Sequence

from app.poker.advice import advise
from app.state.model import Action, Field, GameState, Player

SIX = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]


def table(hero: Sequence[str], pos: str, board: Sequence[str] = (), *, positions: Sequence[str] = SIX,
          stacks: Optional[Dict[str, float]] = None, bets: Optional[Dict[str, float]] = None,
          folded: Sequence[str] = (), last: Optional[Dict[str, Action]] = None, pot: Optional[float] = None,
          blinds=(5, 10), to_call: Optional[float] = None, actions: Optional[Sequence[Action]] = None,
          hero_to_act: Optional[bool] = True, includes_bets: bool = False) -> GameState:
    stacks = stacks or {}
    bets = {} if bets is None else bets
    last = last or {}
    players = []
    for i, p in enumerate(positions):
        pl = Player(seat=i, is_hero=p == pos, position=Field.manual(p), stack=Field.manual(stacks.get(p, 1000.0)),
                    in_hand=Field.manual(p not in folded))
        if bets is not None:
            pl.bet = Field.manual(float(bets.get(p, 0.0)))
        if p in last:
            pl.last_action = Field.manual(last[p])
        players.append(pl)
    street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)]
    st = GameState(street=Field.manual(street), hero_cards=[Field.manual(c) for c in hero],
                   board=[Field.manual(c) for c in board], players=players, pot_includes_bets=includes_bets)
    if pot is not None:
        st.pot = Field.manual(float(pot))
    if blinds is not None:
        st.blinds = Field.manual(tuple(blinds))
    if to_call is not None:
        st.to_call = Field.manual(float(to_call))
    if actions is not None:
        st.available_actions = Field.manual(list(actions))
    if hero_to_act is not None:
        st.hero_to_act = Field.manual(hero_to_act)
    return st


def go(st: GameState):
    return advise(st, budget_ms=250)


# ----------------------------------------------------------------- preflop
def test_open_raise_with_a_strong_hand():
    st = table(["As", "Ks"], "CO", bets={"SB": 5, "BB": 10}, pot=0, to_call=10,
               folded=["UTG", "HJ"], actions=[Action("fold"), Action("call", 10), Action("raise", 20)])
    a = go(st)
    assert (a.action, a.headline, a.amount) == ("raise", "RAISE TO 25", 25.0)
    assert "Cutoff" in a.reason and a.hand.startswith("A♠ K♠")


def test_fold_trash_under_the_gun():
    st = table(["7c", "2d"], "UTG", bets={"SB": 5, "BB": 10}, pot=0, to_call=10)
    a = go(st)
    assert a.action == "fold" and a.headline == "FOLD"
    assert "too weak" in a.reason


def test_button_opens_wider_than_under_the_gun():
    hand = ["Kh", "9d"]
    utg = go(table(hand, "UTG", bets={"SB": 5, "BB": 10}, pot=0, to_call=10))
    btn = go(table(hand, "BTN", bets={"SB": 5, "BB": 10}, pot=0, to_call=10, folded=["UTG", "HJ", "CO"]))
    assert utg.action == "fold" and btn.action == "raise"


def test_reraise_queens_against_a_raise():
    st = table(["Qd", "Qc"], "BTN", bets={"SB": 5, "BB": 10, "UTG": 30}, pot=0, to_call=30,
               last={"UTG": Action("raise", 30)}, folded=["HJ", "CO"])
    a = go(st)
    assert (a.action, a.amount) == ("raise", 90.0)


def test_fold_a_medium_hand_against_an_early_raise():
    st = table(["Kd", "Tc"], "HJ", bets={"SB": 5, "BB": 10, "UTG": 30}, pot=0, to_call=30,
               last={"UTG": Action("raise", 30)})
    assert go(st).action == "fold"


def test_big_blind_checks_its_option():
    st = table(["9h", "4c"], "BB", bets={"SB": 10, "BB": 10, "CO": 10}, pot=0, to_call=0,
               last={"CO": Action("call", 10)}, folded=["UTG", "HJ", "BTN"],
               actions=[Action("check"), Action("raise", 20)])
    a = go(st)
    assert a.action == "check" and a.headline == "CHECK"


def test_short_stack_goes_all_in_or_folds():
    st = table(["Ah", "9d"], "BTN", stacks={"BTN": 90}, bets={"SB": 5, "BB": 10}, pot=0, to_call=10,
               folded=["UTG", "HJ", "CO"])
    a = go(st)
    assert a.action == "all-in" and a.headline == "ALL IN (90)"
    st = table(["8h", "3d"], "UTG", stacks={"UTG": 90}, bets={"SB": 5, "BB": 10}, pot=0, to_call=10)
    assert go(st).action == "fold"


def test_limped_pot_without_amounts_like_247_free_poker():
    # Fold / Call / Raise buttons without amounts, no bet numbers on the table, pot shown as one number
    st = table(["7s", "4s"], "CO", positions=["BTN", "SB", "BB", "HJ", "CO"], bets=None, pot=5, blinds=None,
               last={"HJ": Action("call")}, actions=[Action("fold"), Action("call"), Action("raise")])
    for p in st.players:
        p.bet = Field()
    a = go(st)
    assert a.action == "fold"


# ---------------------------------------------------------------- postflop
def test_top_pair_calls_and_a_set_raises():
    st = table(["As", "Kh"], "BTN", ["Ah", "8d", "5c"], bets={"BB": 60}, pot=120, to_call=60,
               folded=["SB", "UTG", "HJ", "CO"])
    a = go(st)
    assert a.action == "call" and a.headline == "CALL 60" and a.basis == "math"
    st = table(["8s", "8h"], "BTN", ["Ah", "8d", "5c"], bets={"BB": 60}, pot=120, to_call=60,
               folded=["SB", "UTG", "HJ", "CO"])
    a = go(st)
    assert a.action == "raise" and a.amount == 180.0 and a.headline == "RAISE TO 180"


def test_deep_all_in_needs_a_strong_hand():
    st = table(["Ac", "Qd"], "BB", stacks={"BTN": 0, "BB": 990}, bets={"SB": 5, "BB": 10, "BTN": 600}, pot=0,
               to_call=590, last={"BTN": Action("all-in", 600)}, folded=["UTG", "HJ", "CO", "SB"])
    a = go(st)
    assert a.action == "fold" and a.basis == "math"
    st = table(["Ac", "Ad"], "BB", stacks={"BTN": 0, "BB": 990}, bets={"SB": 5, "BB": 10, "BTN": 600}, pot=0,
               to_call=590, last={"BTN": Action("all-in", 600)}, folded=["UTG", "HJ", "CO", "SB"])
    assert go(st).action == "call"


def test_fold_air_to_a_big_bet():
    st = table(["7c", "2d"], "BB", ["As", "Kd", "Qh"], bets={"UTG": 100}, pot=100, to_call=100,
               folded=["SB", "HJ", "CO", "BTN"])
    a = go(st)
    assert a.action == "fold" and a.basis == "math"
    assert "you'd need 33%" in a.reason


def test_call_a_small_bet_with_a_decent_hand():
    st = table(["Jc", "Td"], "BB", ["Jh", "8s", "3c"], bets={"BTN": 25}, pot=100, to_call=25,
               folded=["SB", "UTG", "HJ", "CO"])
    a = go(st)
    assert a.action in ("call", "raise")
    assert a.basis in ("math", "rule")


def test_check_weak_hand_and_bet_strong_hand():
    weak = table(["7c", "2d"], "BB", ["As", "Kd", "9h"], bets={}, pot=60, to_call=0,
                 folded=["SB", "UTG", "HJ", "CO"], actions=[Action("check"), Action("bet", 10)])
    assert go(weak).action == "check"
    strong = table(["Ac", "Ad"], "BB", ["As", "Kd", "9h"], bets={}, pot=60, to_call=0,
                   folded=["SB", "UTG", "HJ", "CO"], actions=[Action("check"), Action("bet", 10)])
    a = go(strong)
    assert a.action == "bet" and a.amount == 40.0


def test_unknown_bet_size_gives_a_call_limit():
    st = table(["Jc", "Td"], "BB", ["Jh", "8s", "3c"], bets=None, pot=150, folded=["SB", "UTG", "HJ", "CO"],
               actions=[Action("fold"), Action("call"), Action("raise")])
    for p in st.players:
        p.bet = Field()
    a = go(st)
    assert a.action in ("call", "raise")
    if a.action == "call":
        assert a.headline.startswith("CALL UP TO ") and a.amount > 0
        assert "amount to call" in a.missing


# --------------------------------------------------------- not actionable
def test_wait_when_not_hero_turn():
    st = table(["As", "Ah"], "CO", bets={"SB": 5, "BB": 10}, pot=0, hero_to_act=False)
    a = go(st)
    assert a.action == "wait" and a.headline == "WAIT" and "A♠ A♥" in a.hand


def test_unreadable_cards_never_guess():
    st = table(["As", "Ah"], "CO", bets={"SB": 5, "BB": 10}, pot=15, to_call=10)
    st.hero_cards[1] = Field(None, 0.4, "auto", guess="Ah")
    a = go(st)
    assert a.action == "unknown" and a.headline == "CONFIRM YOUR CARDS"


def test_empty_capture_asks_to_redraw_the_box():
    a = go(GameState())
    assert a.action == "unknown" and a.headline == "CAN'T SEE THE TABLE"


# ---------------------------------------------------------------- discipline
def test_a_short_opponent_never_makes_a_deep_stack_go_all_in():
    """You have 100 big blinds; the only other player still in has 8. That isn't you
    being short-stacked: open normally, never shove your whole stack."""
    st = table(["Ah", "9d"], "BTN", stacks={"BTN": 1000, "BB": 80}, bets={"SB": 5, "BB": 10}, pot=0, to_call=10,
               folded=["UTG", "HJ", "CO", "SB"])
    a = go(st)
    assert a.action == "raise" and a.headline == "RAISE TO 25"


def test_no_all_in_when_the_numbers_were_not_checked():
    """While watching, a stack that doesn't add up with the pot may be misread: a short
    stack read that way must not turn into ALL IN."""
    st = table(["Ah", "9d"], "BTN", stacks={"BTN": 90}, bets={"SB": 5, "BB": 10}, pot=0, to_call=10,
               folded=["UTG", "HJ", "CO"])
    assert advise(st, budget_ms=250, numbers_checked=True).action == "all-in"
    a = advise(st, budget_ms=250, numbers_checked=False)
    assert a.action != "all-in" and "ALL IN" not in a.headline


def test_unsure_stack_read_never_means_all_in():
    st = table(["Ah", "9d"], "BTN", stacks={"BTN": 90}, bets={"SB": 5, "BB": 10}, pot=0, to_call=10,
               folded=["UTG", "HJ", "CO"])
    st.hero.stack = Field(90.0, 0.6, "auto")  # read, but not reliably
    assert go(st).action != "all-in"


def test_a_raise_that_is_well_under_half_the_stack_stays_a_raise():
    # a set facing a big flop bet: raise to 3x (450 of 1100), not all in
    st = table(["8s", "8h"], "BTN", ["Ah", "8d", "5c"], stacks={"BTN": 1100}, bets={"BB": 150}, pot=300,
               to_call=150, folded=["SB", "UTG", "HJ", "CO"])
    a = go(st)
    assert a.action == "raise" and a.headline == "RAISE TO 450"


def test_a_raise_always_says_how_much():
    # no blinds on screen (like 247 before the first hand is tracked): the size comes from the pot
    st = table(["As", "Ks"], "CO", bets=None, pot=3, blinds=None, folded=["UTG", "HJ"],
               actions=[Action("fold"), Action("call"), Action("raise")])
    for p in st.players:
        p.bet = Field()
    a = go(st)
    assert a.action == "raise" and a.headline == "RAISE TO ABOUT 5"
    # facing a bet whose size couldn't be read: the size in words
    st = table(["8s", "8h"], "BTN", ["Ah", "8d", "5c"], bets=None, pot=120, folded=["SB", "UTG", "HJ", "CO"],
               actions=[Action("fold"), Action("call"), Action("raise")], includes_bets=True)
    for p in st.players:
        p.bet = Field()
    a = go(st)
    assert a.action == "raise" and a.headline == "RAISE TO 3X THEIR BET"
    for word in ("RAISE", "BET"):
        assert a.headline != word


def test_your_own_raise_is_not_someone_raising_you():
    """You opened to 25 and nobody has acted since: wait, don't fold to your own raise."""
    st = table(["Ah", "Td"], "CO", bets={"SB": 5, "BB": 10, "CO": 25}, pot=0, to_call=0, folded=["UTG", "HJ"],
               last={"CO": Action("raise", 25)}, hero_to_act=None)
    a = go(st)
    assert a.action == "wait" and "You raised" in a.reason
    # once someone raises you back, it's a decision again
    st = table(["Ah", "Td"], "CO", bets={"SB": 5, "BB": 10, "CO": 25, "BTN": 75}, pot=0, to_call=50,
               folded=["UTG", "HJ"], last={"CO": Action("raise", 25), "BTN": Action("raise", 75)})
    assert go(st).action in ("fold", "call", "raise", "all-in")
    # after the flop: you bet and nobody has answered yet
    st = table(["Ah", "Td"], "CO", ["As", "7d", "2c"], bets={"CO": 30}, pot=60, to_call=0,
               folded=["UTG", "HJ", "BTN", "SB"], hero_to_act=None)
    assert go(st).action == "wait"


def test_big_blind_option_is_still_a_decision():
    st = table(["Ah", "Kd"], "BB", bets={"SB": 10, "BB": 10, "CO": 10}, pot=0, to_call=0, folded=["UTG", "HJ", "BTN"],
               last={"CO": Action("call", 10), "SB": Action("call", 10)})
    a = go(st)
    assert a.action == "raise"


def test_never_fold_when_checking_is_free():
    weak = ["7c", "2d"]
    board = ["As", "Kd", "Qh"]
    # the buttons say Check; the chips weren't worked out
    st = table(weak, "BB", board, bets=None, pot=40, folded=["SB", "HJ", "CO", "BTN"],
               actions=[Action("fold"), Action("check"), Action("bet")], includes_bets=True)
    for p in st.players:
        p.bet = Field()
    a = go(st)
    assert a.action == "check" and a.headline == "CHECK"
    # nothing tells whether there's a bet: say both, never a bare FOLD
    st = table(weak, "BB", board, bets=None, pot=40, folded=["SB", "HJ", "CO", "BTN"], hero_to_act=None,
               includes_bets=True)
    for p in st.players:
        p.bet = Field()
    a = go(st)
    assert a.headline in ("CHECK", "CHECK OR FOLD") and a.action != "fold"
    # the chip maths says 4 to call, but the buttons on screen say Check: the buttons win
    st = table(weak, "BB", board, bets={"UTG": 0}, pot=40, to_call=4, folded=["SB", "HJ", "CO", "BTN"],
               actions=[Action("fold"), Action("check"), Action("bet")])
    a = go(st)
    assert a.action == "check"


def test_stale_raise_bubble_does_not_fold_the_big_blind_option():
    # everyone limped; an old "Raise" bubble is still on screen; the buttons offer Check
    st = table(["9h", "8h"], "BB", bets={"SB": 10, "BB": 10, "CO": 10}, pot=0, folded=["UTG", "HJ", "BTN"],
               last={"CO": Action("raise")}, actions=[Action("fold"), Action("check"), Action("raise")])
    st.to_call = Field()
    a = go(st)
    assert a.action != "fold"


# ------------------------------------------------------------- tuned rules
def test_board_texture():
    from app.poker.advice import board_texture

    assert board_texture(("Kh", "7d", "2c")) == "dry"
    assert board_texture(("Kc", "Kd", "4h")) == "dry"
    assert board_texture(("9h", "8h", "2c")) == "medium"
    assert board_texture(("Jh", "Th", "9h")) == "wet"
    assert board_texture(("7s", "6d", "5c")) == "medium"


def test_two_raises_after_your_open_is_a_four_bet():
    """You opened, one player re-raised and another raised again: only the very best
    hands go on (it used to be treated as a single re-raise)."""
    st = table(["Ah", "5h"], "UTG", bets={"UTG": 5, "CO": 15, "BTN": 45}, pot=3, to_call=40,
               stacks={"UTG": 195, "CO": 185, "BTN": 155}, folded=["HJ"], blinds=(1, 2),
               last={"UTG": Action("raise", 5), "CO": Action("raise", 15), "BTN": Action("raise", 45)})
    a = go(st)
    assert a.action == "fold"
    st = table(["Ah", "Ad"], "UTG", bets={"UTG": 5, "CO": 15, "BTN": 45}, pot=3, to_call=40,
               stacks={"UTG": 195, "CO": 185, "BTN": 155}, folded=["HJ"], blinds=(1, 2),
               last={"UTG": Action("raise", 5), "CO": Action("raise", 15), "BTN": Action("raise", 45)})
    assert go(st).action == "all-in"


def test_a_bluff_reraise_never_becomes_all_in():
    """Suited aces re-raise as a bluff when it's cheap; against a huge raise that would be
    all your chips, so they fold instead."""
    from app.poker import charts

    big = table(["As", "5s"], "BTN", bets={"SB": 1, "BB": 2, "CO": 60}, pot=0, to_call=60, blinds=(1, 2),
                stacks={"BTN": 200, "CO": 140}, folded=["UTG", "HJ"], last={"CO": Action("raise", 60)})
    a = go(big)
    assert a.action != "all-in"
    if charts.vs_open("BTN", "CO", "A5s") == "raise":
        small = table(["As", "5s"], "BTN", bets={"SB": 1, "BB": 2, "CO": 5}, pot=0, to_call=5, blinds=(1, 2),
                      stacks={"BTN": 200}, folded=["UTG", "HJ"], last={"CO": Action("raise", 5)})
        assert go(small).action == "raise"


def test_small_bet_when_checked_to_on_a_dry_board():
    from app.poker.advice import TUNING

    if not TUNING["stab"]:
        return
    # heads-up on the button, checked to you on K-7-2 rainbow with a middling hand
    st = table(["Qs", "Jd"], "BTN", ["Kh", "7d", "2c"], bets={"BB": 0, "BTN": 0}, pot=11, to_call=0,
               folded=["SB", "UTG", "HJ", "CO"], last={"BB": Action("check")},
               actions=[Action("check"), Action("bet")])
    a = advise(st, budget_ms=250)
    assert a.action in ("bet", "check")
    if a.action == "bet":
        assert a.amount is not None and a.amount <= 0.4 * 11 + 1e-6
