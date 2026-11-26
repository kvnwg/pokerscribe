"""One clear instruction for the hero: what to do now, and one sentence why.

Calling a bet is decided by maths: the chance of winning against the opponents'
likely hands versus the price (pot odds). Opening, raising and betting follow the
standard rules good players use: position-based opening ranges, re-raising strong
hands, value bets and raises with strong hands, semi-bluffs with big draws. That
is solid and close to how a pro plays, but it is not a game-theory solver.

Nothing here guesses: if a value the decision needs is UNKNOWN, the advice says
what is missing, or gives the rule that covers every possible value ("call if it
costs 12 or less").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.state.model import GameState, Player
from app.state.positions import label as position_label
from app.state.text_format import card_symbol, fmt_amount

from . import charts, exploits, hands
from .calculator import compute, opponents_in_hand, pot_for_odds
from .decision import call_or_fold
from .equity import equity
from . import ranges
from .ranges import RangeSpec, make_range, preflop_percentile

log = logging.getLogger(__name__)

BLINDS = {"SB", "BB", "BTN/SB"}

TONES = {"fold": "stop", "check": "neutral", "call": "go", "bet": "strong", "raise": "strong",
         "all-in": "strong", "wait": "idle", "unknown": "warn"}


@dataclass
class Advice:
    action: str  # fold | check | call | bet | raise | all-in | wait | unknown
    headline: str  # the big text, e.g. "CALL 60"
    reason: str  # one plain sentence
    amount: Optional[float] = None
    close: bool = False  # the two best choices are worth about the same
    basis: str = "rule"  # "math" (odds), "rule" (standard strategy), "solver" (river solver) or "none"
    detail: str = ""  # small print: backup plan, assumptions
    hand: str = ""  # "7♠ 4♠: Seven Four suited"
    missing: List[str] = field(default_factory=list)

    @property
    def tone(self) -> str:
        return TONES.get(self.action, "neutral")

    def to_dict(self) -> dict:
        return {"action": self.action, "headline": self.headline, "reason": self.reason, "amount": self.amount,
                "close": self.close, "basis": self.basis, "detail": self.detail, "hand": self.hand,
                "missing": list(self.missing)}


# ---------------------------------------------------------------- helpers
def _pct(p: float) -> str:
    return f"{int(round(100 * p))}%"


def _top(p: float) -> str:
    return f"top {max(1, int(round(100 * p)))}%"


def _chips(x: float) -> float:
    """Round a bet size the way people type it."""
    if x >= 10:
        return float(round(x))
    if x >= 1:
        return round(x * 2) / 2.0
    return round(x, 2)


def _amt(x: float) -> str:
    return fmt_amount(_chips(x))


def _last(p: Optional[Player]) -> Optional[str]:
    if p is None or not p.last_action.known or p.last_action.value is None:
        return None
    return p.last_action.value.kind


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def hand_text(hero: Tuple[str, ...], board: Tuple[str, ...]) -> str:
    cards = " ".join(card_symbol(c) for c in hero)
    if board:
        return f"{cards}: {hands.describe(tuple(hero) + tuple(board))}"
    return f"{cards}: {hands.describe_preflop(hero)}"


@dataclass
class _Spot:
    state: GameState
    computed: dict
    hero: Tuple[str, ...]
    board: Tuple[str, ...]
    pos: Optional[str]
    bb: Optional[float]
    to_call: Optional[float]
    hero_bet: Optional[float]
    stack: Optional[float]  # hero's chips behind
    pot: Optional[float]  # everything the hero can win right now (bets included)
    facing: Optional[bool]  # there is a bet to call (None = can't tell)
    can_check: Optional[bool]
    can_raise: bool
    n_opp: int
    eff: Optional[float]  # effective stack: the hero's or the biggest opponent's, whichever is smaller
    trusted: bool = True  # your stack (and, while watching, how the chips add up) was read reliably
    bb_guess: Optional[float] = None  # big blind worked out from the pot, only to put a number on a raise

    @property
    def total(self) -> Optional[float]:
        """The most the hero can have in front this street (stack + current bet)."""
        if self.stack is None:
            return None
        return self.stack + (self.hero_bet or 0.0)

    @property
    def hero_bb(self) -> Optional[float]:
        """Your own stack in big blinds, only when it was read reliably. Going all in
        because you're short is decided on this, never on an opponent's stack."""
        if not self.trusted or self.total is None or not self.bb:
            return None
        return self.total / self.bb


TRUSTED_STACK = 0.75  # confidence needed in your stack before an all-in can be suggested

# After-the-flop settings, chosen with the paired simulations in tools/compare.py
# (python tools/compare.py --help). Kept in one table so a variant can be tried without
# touching the code.
TUNING = {
    # bet for value when your chance of winning is at least this (heads-up / heads-up on
    # the river / against two or more players)
    "value_bet_hu": 0.62, "value_bet_river": 0.66, "value_bet_multi": 0.50,
    # raise a bet for value (only with two pair or better that uses your cards)
    "value_raise_hu": 0.72, "value_raise_river": 0.80, "value_raise_multi": 0.60,
    "bet_size": 2 / 3,  # share of the pot for a value bet
    "texture_sizing": False,  # smaller bets on dry boards, bigger on wet ones
    "sizes": {"dry": 0.33, "medium": 0.55, "wet": 0.75},
    "pot_control": 0.0,  # extra winning chance needed to bet one pair out of position or into 2+ players
    "stab": 0.40,  # heads-up, checked to you on a dry board: bet small from this winning chance (0 = off)
    "semibluff": True,  # bet big draws heads-up
    # facing a bet: the share of their range that bets this much, and the share of bluffs in it
    "facing": {"raise": (0.25, 0.03), "over": (0.30, 0.08), "pot": (0.45, 0.10), "half": (0.55, 0.12),
               "small": (0.70, 0.12)},
    "narrow": True,  # judge calls against the hands that bet (False: against their whole range)
    "facing_budget_s": 0.12,  # time for that maths on the flop (the turn and river are exact)
    "facing_iterations": 60000,  # (a cap on the same; the simulator uses it to stay repeatable)
    "allin_budget_s": 0.35,  # time for the maths when someone went all in before the flop
    # --- stack sizes (before the flop). Your own stack decides whether you're short; an
    # opponent's short stack never makes you go all in while a bigger stack is still to act.
    "push_bb": 12,  # with this many big blinds or fewer (your own stack), open all in or fold
    "push_chart": False,  # push-or-fold ranges that widen as the stack gets shorter (False: the opening chart)
    "push_scale": 1.0,  # times the shares in that chart
    "eff_push": False,  # every player left to act is that short: raise to the size of their stack, no more
    "reshove": None,  # short and facing one raise: share of hands that re-raise all in, by the raiser's seat
    "bully": False,  # big stack, only short or medium stacks left to act: open one seat wider, normal size
    "bully_bb": 30,  # "short or medium" means at most this many big blinds
    # --- after the flop
    "commit": 0.0,  # heads-up, top pair or better, calling leaves at most this share of the pot behind: all in
    "commit_draws": False,  # the same with a big draw on the flop (draws near 50% want the money in early)
    "river_ip_call_share": 0.0,  # river, checked to you last: bet if you beat over half the hands that call
    "geometric": False,  # strong hands bet the same share of the pot each street so the stacks go in by the river
    "balanced_river": False,  # facing a river bet: assume a balanced bettor's bluff share, s/(1+2s) of the bets
    # semi-bluffs on the turn (one card to come): "always", "combo" (12 or more outs, or a
    # player who folds a lot) or "never". On the flop big draws always semi-bluff heads-up,
    # and never against a calling station.
    "semibluff_turn": "always",
    # choose bet and raise sizes by expected value: the bigger the bet, the more of their
    # range folds (they keep 1/(1+s) of it for a bet of s times the pot, wider for callers)
    "ev_sizing": False,
    "sizing_budget_s": 0.03, "sizing_iterations": 4000,  # time for that maths, per size
    # equity buckets: good hands (below 75%) bet a third of the pot, strong ones the usual size;
    # small_bet_from: heads-up and last to act, bet a third of the pot from this chance (0 = off)
    "bucket_sizing": False, "small_bet_from": 0.0,
    # out of position heads-up on the flop, on boards that favour the preflop raiser (high
    # cards, paired, one suit or dry): lead only from this chance of winning (0 = off)
    "oop_lead": 0.0,
    # river, heads-up: play the river solver's strategy (app/solver) when it answers within
    # its time budget; otherwise, and on every other street, the rules above decide
    "river_solver": False,
    "river_solver_fixed_work": False,  # (no clock, a fixed amount of work: the simulator uses it to stay repeatable)
}
SIZES = (1 / 3, 1 / 2, 2 / 3, 1.0)  # bet sizes tried, as shares of the pot

# Push or fold (no antes): the share of hands to open all in by the number of players still
# to act after you and the stack in big blinds (5, 10, 15, 20). Heads-up (small blind
# against the big blind) follows the jam-or-fold equilibrium in The Mathematics of Poker
# (about 62% of hands at 8 big blinds, 58% at 10); the other rows are the published 9-max
# no-ante charts at pokerskill.com, by players left behind (2 = button, 3 = cutoff ...).
PUSH_DEPTHS = (5.0, 10.0, 15.0, 20.0)
PUSH_SHARE = {
    1: (0.70, 0.58, 0.48, 0.36),
    2: (0.544, 0.436, 0.357, 0.279),
    3: (0.451, 0.342, 0.270, 0.207),
    4: (0.400, 0.300, 0.237, 0.189),
    5: (0.348, 0.246, 0.192, 0.160),
    6: (0.318, 0.204, 0.164, 0.128),
    7: (0.285, 0.175, 0.142, 0.115),
    8: (0.243, 0.179, 0.146, 0.115),
}
# Short and facing one raise (nobody called it): re-raise all in with this share of hands,
# by the raiser's seat. Later seats raise wider, so they get re-raised wider.
RESHOVE = {"EP": 0.08, "HJ": 0.10, "CO": 0.13, "BTN": 0.17, "SB": 0.20}
# The bully opens one seat wider: the chart of the seat with one player fewer behind it.
WIDER_SEAT = {"UTG+1": "UTG", "UTG+2": "UTG", "MP": "UTG", "LJ": "HJ", "UTG": "HJ", "HJ": "CO", "CO": "BTN",
              "BTN": "SB"}
BULLY_SB = 0.60  # small blind against a short or medium big blind


def _spot(state: GameState, computed: dict, hero: Tuple[str, ...], board: Tuple[str, ...],
          numbers_checked: Optional[bool] = None) -> _Spot:
    me = state.hero
    pos = me.position.value if me is not None and me.position.known else None
    bb = None
    if state.blinds.known and state.blinds.value:
        try:
            bb = float(state.blinds.value[1]) or None
        except (TypeError, ValueError, IndexError):
            bb = None
    to_call = float(state.to_call.value) if state.to_call.known else None
    hero_bet = float(me.bet.value) if me is not None and me.bet.known else None
    stack = float(me.stack.value) if me is not None and me.stack.known else None
    pot = pot_for_odds(state)
    if pot is None and state.pot.known:
        # No bet amounts on screen at all: this client puts bets straight into the pot.
        if not any(p.bet.known and float(p.bet.value) > 0 for p in state.players):
            pot = float(state.pot.value)
    acts = state.available_actions.value if state.available_actions.known else None
    kinds = {a.kind for a in acts} if acts else set()
    facing: Optional[bool] = None
    can_check: Optional[bool] = None
    if to_call is not None:
        facing, can_check = to_call > 0, to_call <= 0
    if kinds and state.hero_to_act.known and state.hero_to_act.value:
        # The buttons on screen are the final word on whether there is a bet to call:
        # they win over an amount worked out from the chips.
        btn_check = "check" in kinds
        btn_facing = "call" in kinds or ("all-in" in kinds and not btn_check)
        if btn_check and not btn_facing:
            facing, can_check = False, True
            if to_call:
                to_call = 0.0
        elif btn_facing and not btn_check:
            facing, can_check = True, False
            if to_call is not None and to_call <= 0:
                to_call = None  # there is a bet, but its size wasn't worked out
    elif to_call is None and kinds:
        facing = "call" in kinds or ("all-in" in kinds and "check" not in kinds)
        can_check = "check" in kinds
    can_raise = not kinds or bool(kinds & {"raise", "bet", "all-in"})
    n_opp = opponents_in_hand(state)
    opp = [float(p.stack.value) + (float(p.bet.value) if p.bet.known else 0.0) for p in state.opponents
           if p.in_hand.known and p.in_hand.value and p.stack.known]
    eff = None
    if stack is not None:
        eff = stack + (hero_bet or 0.0)
        if opp:
            eff = min(eff, max(opp))
    trusted = (numbers_checked is not False and me is not None and me.stack.known
               and (me.stack.source == "manual" or me.stack.confidence >= TRUSTED_STACK))
    bb_guess = bb
    if bb_guess is None and not board and pot:
        # nobody raised yet: the pot is the two blinds (1.5 big blinds) plus one per caller
        lasts = [p.last_action.value.kind for p in state.opponents if p.last_action.known]
        if not any(k in ("raise", "bet", "all-in") for k in lasts):
            bb_guess = pot / (1.5 + sum(1 for k in lasts if k == "call"))
    return _Spot(state, computed, hero, board, pos, bb, to_call, hero_bet, stack, pot, facing, can_check,
                 can_raise, n_opp, eff, trusted, bb_guess)


# ------------------------------------------------------------------- entry
def advise(state: GameState, computed: Optional[dict] = None, range_spec: Optional[RangeSpec] = None,
           budget_ms: int = 400, numbers_checked: Optional[bool] = None) -> Advice:
    """numbers_checked: while watching, whether the chips that left the stacks added up to
    the pot on this read. When they didn't, no all-in is suggested: a misread stack must
    never turn into "ALL IN"."""
    me = state.hero
    cards = list(state.hero_cards)
    if me is None or len(cards) != 2 or not all(c.known for c in cards):
        sees_table = state.pot.known or any(p.stack.known for p in state.players)
        if any(c.guess for c in cards):
            return Advice("unknown", "CONFIRM YOUR CARDS",
                          "Make sure the cards below are right. Each card shape is checked with you once, "
                          "then read exactly.", basis="none", missing=["your cards"])
        if not sees_table:
            return Advice("unknown", "CAN'T SEE THE TABLE",
                          "Nothing in the box looks like a poker table. Draw the box around the table again.",
                          basis="none", missing=["table"])
        return Advice("wait", "WAITING", "You don't have cards right now. Waiting for the next hand.", basis="none")
    if any(not c.known for c in state.board):
        if any(c.guess for c in state.board):
            return Advice("unknown", "CONFIRM THE BOARD",
                          "Make sure the cards below are right. Each card shape is checked with you once, "
                          "then read exactly.", basis="none", missing=["board"])
        return Advice("unknown", "CAN'T READ THE BOARD",
                      "A card in the middle couldn't be read. Make sure the whole table is inside the box.",
                      basis="none", missing=["board"])
    problems = state.validate()
    if problems:
        return Advice("unknown", "CONFIRM THE CARDS", problems[0], basis="none")
    hero = tuple(c.value for c in cards)
    board = tuple(c.value for c in state.board)
    if len(board) not in (0, 3, 4, 5):
        return Advice("unknown", "CAN'T READ THE BOARD", "Some cards in the middle are missing or hidden.",
                      basis="none", missing=["board"])
    if computed is None or not computed:
        computed = compute(state, range_spec, budget_ms)
    text = hand_text(hero, board)
    if state.hero_to_act.known and state.hero_to_act.value is False:
        return Advice("wait", "WAIT", "It's not your turn yet.", basis="none", hand=text)
    s = _spot(state, computed, hero, board, numbers_checked)
    waiting = _waiting_on_others(s)
    if waiting:
        return Advice("wait", "WAIT", waiting, basis="none", hand=text)
    adv = _never_fold_a_free_check(s, _preflop(s) if not board else _postflop(s))
    adv.hand = text
    if not state.hero_to_act.known:
        adv.detail = _join(adv.detail, "(No action buttons visible: this is the plan for when it's your turn.)")
    return adv


# ---------------------------------------------------------------- shared
def _never_fold_a_free_check(s: _Spot, adv: Advice) -> Advice:
    """The last check on every instruction: folding when checking costs nothing is never
    right. When it can't tell whether there's a bet, say both."""
    if adv.action != "fold":
        return adv
    reason = adv.reason.replace(" Fold.", "").rstrip()
    if s.can_check:
        return Advice("check", "CHECK", _join(reason, "Check, it's free."), basis=adv.basis, detail=adv.detail,
                      hand=adv.hand)
    if s.can_check is None and s.to_call is None:
        return Advice("check", "CHECK OR FOLD", _join(reason, "Check if you can; if there's a bet to call, fold."),
                      basis=adv.basis, detail=adv.detail, hand=adv.hand)
    return adv


def _waiting_on_others(s: _Spot) -> str:
    """The biggest bet on the table is your own: nobody has raised you, so there's nothing
    to decide until someone acts. (Never mistake your own raise for someone raising you.)"""
    if s.to_call is None or s.to_call > 1e-9 or not s.hero_bet:
        return ""
    if s.state.hero_to_act.known and s.state.hero_to_act.value:
        return ""  # the action buttons are showing: it's your turn, whatever the chips say
    if s.board:
        return "You bet. Wait for the others to act."
    if s.pos == "BB" or s.pos is None:
        if s.bb and s.hero_bet > 1.01 * s.bb:
            return "You raised. Wait for the others to act."
        return ""  # the big blind's own blind: checking or raising is still yours to decide
    if s.bb and s.hero_bet > 1.01 * s.bb:
        return "You raised. Wait for the others to act."
    return "You're in. Wait for the others to act."


ALL_IN_SHARE = 0.5  # a bet or raise this big a share of your chips becomes all in


def _aggressive(s: _Spot, kind: str, to: Optional[float], reason: str, detail: str = "",
                basis: str = "rule", size_hint: str = "", relative: str = "", in_bb: Optional[float] = None) -> Advice:
    """BET / RAISE TO x, or ALL IN when the size would be most of the stack anyway (and
    the stack was read reliably). It always says how much: when the amount can't be worked
    out, the headline gives the size in words ("RAISE TO 3X THEIR BET", "BET 2/3 POT") or
    from a big blind estimated from the pot ("RAISE TO ABOUT 5")."""
    if to is None and in_bb is not None and s.bb_guess:
        est = _chips(in_bb * s.bb_guess)
        word = "BET ABOUT" if kind == "bet" else "RAISE TO ABOUT"
        return Advice(kind, f"{word} {_amt(est)}", reason, amount=est, basis=basis,
                      detail=_join(size_hint, detail))
    total = s.total
    if to is not None:
        to = _chips(to)
        if s.trusted and total is not None and (to >= ALL_IN_SHARE * total
                                                or s.stack is not None and to - (s.hero_bet or 0) >= s.stack):
            return Advice("all-in", f"ALL IN ({_amt(total)})", reason, amount=total, basis=basis, detail=detail)
        if total is not None and to > total:
            to = total  # can't bet more than you have
    word = "BET" if kind == "bet" else "RAISE TO"
    if to is None:
        head = f"{word} {relative}" if relative else ("BET" if kind == "bet" else "RAISE")
        return Advice(kind, head, reason, basis=basis, detail=_join(size_hint, detail))
    return Advice(kind, f"{word} {_amt(to)}", reason, amount=to, basis=basis, detail=detail)


def _fold_or_check(s: _Spot, reason: str, detail: str = "", basis: str = "rule") -> Advice:
    """`reason` without the verb: it ends with "Fold." or "Check, it's free." as the spot allows."""
    if s.can_check:
        return Advice("check", "CHECK", _join(reason, "Check, it's free."), basis=basis, detail=detail)
    return Advice("fold", "FOLD", _join(reason, "Fold."), basis=basis, detail=detail)


def _call(s: _Spot, reason: str, detail: str = "", basis: str = "rule", close: bool = False) -> Advice:
    amount = s.to_call
    if amount is not None and s.stack is not None and amount >= s.stack and s.trusted:
        return Advice("all-in", f"CALL ALL IN ({_amt(s.stack)})", reason, amount=s.stack, basis=basis,
                      detail=detail, close=close)
    if amount is None or amount <= 0:
        return Advice("call", "CALL", reason, basis=basis, detail=detail, close=close)
    return Advice("call", f"CALL {_amt(amount)}", reason, amount=amount, basis=basis, detail=detail, close=close)


def _vs(n_opp: int) -> str:
    return "their likely hands" if n_opp <= 1 else f"the likely hands of {n_opp} players"


def _bettor(s: _Spot) -> Optional[Player]:
    """The opponent who made the biggest bet this round (the one you're facing)."""
    bets = [(float(p.bet.value), p) for p in s.state.opponents if p.bet.known and float(p.bet.value) > 0]
    if bets:
        return max(bets, key=lambda t: t[0])[1]
    aggr = [p for p in s.state.opponents if _last(p) in ("bet", "raise", "all-in")]
    return aggr[0] if len(aggr) == 1 else None


def _vs_betting_range(s: _Spot, call: float) -> Optional[Tuple[float, float, str]]:
    """Equity against the hands that bet this much here (not their whole range): bigger
    bets and raises come from stronger hands. (equity, standard error, wording)."""
    if not s.board or s.pot is None or call <= 0:
        return None
    pot_before = max(1e-9, s.pot - call)  # what was there before their bet
    size = call / pot_before
    raised_me = bool(s.hero_bet and s.hero_bet > 0)
    if not TUNING["narrow"]:
        return None
    if raised_me:
        key, words = "raise", "hands that raise a bet"
    elif size > 1.1:
        key, words = "over", "hands that bet more than the pot"
    elif size > 0.75:
        key, words = "pot", "hands that bet about the pot"
    elif size > 0.40:
        key, words = "half", "hands that bet half the pot or so"
    else:
        key, words = "small", "hands that make a small bet"
    share, bluffs = TUNING["facing"][key]
    if TUNING["balanced_river"] and len(s.board) == 5 and not raised_me:
        b = size / (1 + 2 * size)  # a balanced river bettor bluffs this share of their bets
        bluffs = share * b / (1 - b)
    share, bluffs = exploits.betting_share(_bettor(s), share, bluffs)
    base = make_range("medium").combos
    dead = tuple(s.hero) + tuple(s.board)
    combos = ranges.betting_range(base, tuple(s.board), dead, share, bluffs)
    if len(combos) < 5:
        return None
    s.betting_combos = combos
    n = max(1, min(s.n_opp, 3))
    try:
        r = equity(s.hero, s.board, n, combos, budget_s=TUNING["facing_budget_s"],
                   max_iterations=TUNING["facing_iterations"])
    except ValueError:
        return None
    who = words if n == 1 else f"{n} players with {words}"
    return r.equity, r.stderr, who


def _math_call(s: _Spot, e: float, stderr: float, win_line: str) -> Optional[Advice]:
    """Call or fold on pure maths, when the price is known."""
    if s.to_call is None or s.pot is None or s.to_call <= 0:
        return None
    call = min(s.to_call, s.stack) if s.stack is not None else s.to_call
    need = call / (s.pot + call)
    v = s.computed.get("verdict")
    if not v or abs(float(v.get("call_amount", call)) - call) > 1e-6:
        v = call_or_fold(e, stderr, s.pot, call, False).to_dict()
    if v["action"] == "call":
        return _call(s, f"{win_line}, and you only need {_pct(need)} to make calling worth it.", basis="math")
    if v["action"] == "close":
        if v["ev_call"] >= 0:
            return _call(s, f"{win_line} and you need {_pct(need)}: calling and folding are worth about the same.",
                         basis="math", close=True)
        return Advice("fold", "FOLD", f"{win_line} and you need {_pct(need)}: folding and calling are worth "
                      "about the same.", basis="math", close=True)
    return None


# ---------------------------------------------------------------- preflop
POSTFLOP_ORDER = ["SB", "BB", "UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO", "BTN"]


def _in_position(me: Optional[str], other: Optional[str]) -> bool:
    """You act after them on the flop, turn and river."""
    if me in ("BTN", "BTN/SB"):
        return True
    if me not in POSTFLOP_ORDER or other not in POSTFLOP_ORDER:
        return me not in BLINDS
    return POSTFLOP_ORDER.index(me) > POSTFLOP_ORDER.index(other)


PREMIUM = {"AA", "KK", "QQ", "AKs", "AKo"}


def _too_big_to_bluff(s: _Spot, cls: str, to: Optional[float]) -> bool:
    """A re-raise that would put in a big share of your chips is only for the best hands:
    the suited aces and connectors in the charts re-raise as bluffs when it's cheap."""
    return (cls not in PREMIUM and to is not None and s.total is not None
            and to >= 0.4 * s.total)


def _shove(s: _Spot, reason: str) -> Advice:
    return Advice("all-in", f"ALL IN ({_amt(s.total)})" if s.total else "ALL IN", reason, amount=s.total)


PREFLOP_ORDER = ["UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB"]


def _behind(s: _Spot) -> Optional[List[Player]]:
    """The opponents still to act after you before the flop (later seats, not folded).
    None when a seat isn't known."""
    me = "SB" if s.pos == "BTN/SB" else s.pos
    if me not in PREFLOP_ORDER:
        return None
    out = []
    for p in s.state.opponents:
        if (p.in_hand.known and p.in_hand.value is False) or _last(p) == "fold":
            continue
        if not p.position.known:
            return None
        pos = "SB" if p.position.value == "BTN/SB" else p.position.value
        if pos not in PREFLOP_ORDER:
            return None
        if PREFLOP_ORDER.index(pos) > PREFLOP_ORDER.index(me):
            out.append(p)
    return out


def _stacks_bb(s: _Spot, players: Optional[List[Player]]) -> Optional[List[float]]:
    """Their chips (stack plus bet) in big blinds, only when every one was read reliably."""
    if not players or not s.bb or not s.trusted:
        return None
    out = []
    for p in players:
        if not p.stack.known or not (p.stack.source == "manual" or p.stack.confidence >= TRUSTED_STACK):
            return None
        out.append((float(p.stack.value) + (float(p.bet.value) if p.bet.known else 0.0)) / s.bb)
    return out


def push_share(behind: int, depth_bb: float) -> float:
    """Share of hands that open all in with this many players left to act and this stack."""
    row = PUSH_SHARE[min(max(behind, 1), 8)]
    d = min(max(depth_bb, PUSH_DEPTHS[0]), PUSH_DEPTHS[-1])
    for k in range(len(PUSH_DEPTHS) - 1):
        d0, d1 = PUSH_DEPTHS[k], PUSH_DEPTHS[k + 1]
        if d <= d1:
            return row[k] + (row[k + 1] - row[k]) * (d - d0) / (d1 - d0)
    return row[-1]


def _pushes(cls: str, pct: float, behind: int, depth_bb: float) -> bool:
    share = push_share(behind, depth_bb) * TUNING["push_scale"]
    if len(cls) == 2 and share >= 0.14:
        return True  # every pair goes all in at these depths: it's never far behind when called
    return pct <= share


def _bully_opens(pos: Optional[str], cls: str, pct: float) -> bool:
    """Open one seat wider than usual (the next seat's chart)."""
    if pos in ("SB", "BTN/SB"):
        return pct <= BULLY_SB
    wider = WIDER_SEAT.get(pos)
    return bool(wider and charts.opens(wider, cls))


def _top_pair_plus(hero: Tuple[str, ...], board: Tuple[str, ...]) -> bool:
    """Top pair, an overpair, or better that uses your cards."""
    cat, bcat = hands.category(hero, board), hands.board_category(board)
    if cat >= bcat:
        return False  # your cards add nothing to the board
    if cat <= 6:
        return True  # three of a kind or better with your cards
    if cat == 7 and bcat == 9:
        return True  # two pair with both your cards
    top = max(hands.RANKS.index(c[0]) for c in board)
    mine = [hands.RANKS.index(c[0]) for c in hero]
    if mine[0] == mine[1]:
        return mine[0] > top  # an overpair
    return top in mine


def _preflop(s: _Spot) -> Advice:
    cls = hands.preflop_class(s.hero)
    pct = preflop_percentile(cls)
    name = hands.describe_preflop(s.hero)
    top = _top(pct)
    seat = position_label(s.pos) if s.pos else ""
    where = f"from the {seat}" if s.pos else "from this seat"
    opp = s.state.opponents
    raisers = [p for p in opp if _last(p) in ("raise", "bet", "all-in")]
    callers = [p for p in opp if _last(p) == "call"]
    max_bet = None
    if s.to_call is not None and s.hero_bet is not None:
        max_bet = s.to_call + s.hero_bet
    else:
        bets = [float(p.bet.value) for p in opp if p.bet.known]
        if opp and len(bets) == len(opp):
            max_bet = max(bets)
    raised = max_bet > 1.01 * s.bb if (s.bb and max_bet is not None) else bool(raisers)
    hero_raised = bool(s.hero_bet and s.bb and s.hero_bet > 1.01 * s.bb) or _last(s.state.hero) in ("raise", "bet")
    my_bb = s.hero_bb  # your own stack, read reliably; None when unsure
    all_in_vs = any(_last(p) == "all-in" for p in raisers) or (
        s.to_call is not None and s.stack is not None and s.to_call >= 0.98 * s.stack and raised)

    # Calling an all-in is pure maths: chance to win versus the price. The deeper the
    # shove, the stronger the hands people shove with.
    if all_in_vs:
        depth = max_bet / s.bb if (max_bet is not None and s.bb) else None
        key = "medium" if depth is not None and depth <= 15 else "tight" if depth is not None and depth <= 30 else "very_tight"
        shover = next((p for p in raisers if _last(p) == "all-in"), None) or (raisers[0] if len(raisers) == 1 else None)
        key = exploits.all_in_range(shover, key)
        spec = make_range(key)
        try:
            r = equity(s.hero, (), max(1, s.n_opp), spec.combos, budget_s=TUNING["allin_budget_s"],
                       max_iterations=TUNING["facing_iterations"])
            eqs = [{"equity": r.equity, "stderr": r.stderr}]
            s.computed = dict(s.computed)
            s.computed.pop("verdict", None)  # it was worked out against a wider range
        except ValueError:
            eqs = s.computed.get("equity") or []
        if eqs:
            e = eqs[-1]["equity"]
            adv = _math_call(s, e, eqs[-1]["stderr"], f"{name} wins about {_pct(e)} against hands people "
                                                         "go all in with")
            if adv is not None:
                return adv
            if s.to_call is not None and s.pot is not None:
                call = min(s.to_call, s.stack or s.to_call)
                return Advice("fold", "FOLD", f"{name} wins about {_pct(e)} against hands people go all in with, "
                              f"but you'd need {_pct(call / (s.pot + call))} to call.", basis="math")
        if pct <= 0.03:
            return _call(s, f"{name} is a {top} hand: strong enough to call an all-in.")
        return Advice("fold", "FOLD", f"{name} ({top} of hands) is not strong enough to call an all-in.")

    short = my_bb is not None and my_bb <= 20  # your own stack is short: raise all in or fold

    # --- you raised and they raised again
    if hero_raised and raised and s.facing is not False:
        reraiser = max((p for p in raisers), key=lambda p: float(p.bet.value) if p.bet.known else 0.0, default=None)
        their_pos = reraiser.position.value if reraiser is not None and reraiser.position.known else None
        you_3bet = bool(s.hero_bet and s.bb and s.hero_bet >= 6 * s.bb)
        if you_3bet or len(raisers) >= 2:  # a 4-bet: they raised your re-raise, or two players raised your open
            move = charts.vs_4bet(cls)
            if move == "all-in" and s.can_raise:
                return _shove(s, f"{name} is one of the very best hands ({top}). Go all in.")
            if move == "call":
                return _call(s, f"{name} ({top}) is strong enough to call their raise.")
            return Advice("fold", "FOLD", f"They raised your re-raise. {name} ({top} of hands) isn't strong enough "
                                          "to continue.")
        ip = _in_position(s.pos, their_pos)
        move = charts.vs_3bet(cls, ip, s.pos)
        to = (2.2 if ip else 2.5) * max_bet if max_bet else None
        if move == "raise" and not short and _too_big_to_bluff(s, cls, to):
            move = "fold"  # a re-raise this big is all your chips: only the best hands make it
        if move == "raise" and s.can_raise:
            if short:
                return _shove(s, f"{name} is a {top} hand and you're short-stacked: go all in.")
            return _aggressive(s, "raise", to, f"{name} is strong enough ({top}) to raise their re-raise.",
                               size_hint="Make it a bit more than double their raise.",
                               relative=f"{2.2 if ip else 2.5:g}X THEIR RAISE")
        if move == "call" and not short:
            where_ip = "in position" if ip else "out of position"
            return _call(s, f"{name} ({top} of hands) is good enough to call their re-raise {where_ip}.")
        return Advice("fold", "FOLD", f"They re-raised you. {name} ({top} of hands) isn't strong enough to continue.")

    # --- someone else raised
    if raised:
        raiser = max(raisers, key=lambda p: float(p.bet.value) if p.bet.known else 0.0) if raisers else None
        if raiser is None and max_bet is not None:
            raiser = next((p for p in opp if p.bet.known and float(p.bet.value) >= max_bet - 1e-9), None)
        raiser_pos = raiser.position.value if raiser is not None and raiser.position.known else None
        size_bb = max_bet / s.bb if (max_bet is not None and s.bb) else None
        cold_3bet = size_bb is not None and size_bb >= 7 or len(raisers) >= 2
        others_in = [p for p in callers if p is not raiser]
        if cold_3bet:
            move, spot = charts.cold_vs_3bet(cls), "a raise and a re-raise"
        elif others_in:
            move, spot = charts.vs_squeeze_spot(cls), "a raise and a call"
        else:
            move, spot = charts.vs_open(s.pos, exploits.opener_seat(raiser, raiser_pos), cls), "a raise"
        if short:
            rs = TUNING["reshove"]
            if rs and not cold_3bet and not others_in:
                # one raise in front of you: re-raise all in wider against the late seats
                seat = exploits.opener_seat(raiser, raiser_pos)
                limit = rs.get(charts._group(seat), 0.10)
                if s.can_raise and pct <= limit * (1.0 + max(0.0, 20.0 - my_bb) / 20.0):
                    return _shove(s, f"You're short-stacked and {name} ({top}) is good enough to go all in over "
                                     f"{spot}.")
                return Advice("fold", "FOLD", f"You're short-stacked: wait for a better hand than {name} to go "
                                              "all in.")
            if s.can_raise and (move == "raise" or pct <= 0.10):
                return _shove(s, f"You're short-stacked and {name} ({top}) is good enough to go all in over {spot}.")
            return Advice("fold", "FOLD", f"You're short-stacked: wait for a better hand than {name} to go all in.")
        ip = _in_position(s.pos, raiser_pos)
        if cold_3bet:
            mult, rel = 2.3, "2.3X THEIR RAISE"
        else:
            mult = (3.0 if ip else 4.0) + len(others_in)
            rel = f"{mult:g}X THEIR RAISE"
        to = mult * max_bet if max_bet else None
        if move == "raise" and _too_big_to_bluff(s, cls, to):
            move = "fold"  # a re-raise this big is all your chips: only the best hands make it
        if move == "raise" and s.can_raise:
            return _aggressive(s, "raise", to, f"{name} is a {top} hand: re-raise for value against {spot}.",
                               size_hint=f"Make it about {mult:g} times their raise.", relative=rel)
        if move == "call":
            return _call(s, f"{name} ({top} of hands) is good enough to call {spot} {where}.",
                         detail="If someone re-raises after you, fold unless your hand is very strong.")
        return Advice("fold", "FOLD", f"Someone raised. {name} ({top} of hands) isn't strong enough to call {where}.")

    # --- nobody has raised yet
    limpers = len(callers)
    behind = _behind(s)
    push_bb = TUNING["push_bb"]
    if my_bb is not None and my_bb <= push_bb and s.pos != "BB" and s.can_raise:
        if TUNING["push_chart"] and not limpers and behind is not None:
            pushes = _pushes(cls, pct, len(behind), my_bb)
        else:
            pushes = charts.opens(s.pos, cls) or (s.pos is None and pct <= 0.20)
        if pushes:
            return _shove(s, f"You have about {int(my_bb)} big blinds left. With a {top} hand, going all in is the "
                             "standard play.")
        return _fold_or_check(s, f"You have about {int(my_bb)} big blinds left. Wait for a better hand than "
                                 f"{name}.")
    if s.pos == "BB" or (s.can_check and not limpers):
        if charts.vs_limpers("BB", cls) == "raise" and s.can_raise:
            to = (3.5 + limpers) * s.bb if s.bb else None
            return _aggressive(s, "raise", to, f"{name} is a {top} hand. Raise instead of checking.",
                               size_hint="Make it about 4 big blinds.", relative=f"{3.5 + limpers:g} BIG BLINDS",
                               in_bb=3.5 + limpers)
        return Advice("check", "CHECK", f"No one raised, so you see the flop for free with {name}.")
    if limpers == 0:
        opens = charts.opens(s.pos, cls)
        if opens is None:
            opens = pct <= 0.20  # seat unknown: a middle-position range
        theirs = _stacks_bb(s, behind)  # the stacks still to act, when all were read reliably
        if TUNING["eff_push"] and theirs and my_bb is not None and s.can_raise:
            most = max(theirs)
            if most <= push_bb < my_bb and _pushes(cls, pct, len(theirs), most):
                # Only the smaller stack needs to be short: nobody left can call more than this.
                return _aggressive(s, "raise", max(most, 2.0) * s.bb,
                                   f"Everyone left to act has {int(most)} big blinds or less. With a {top} hand, "
                                   "raise the size of their stack: it puts them all in, and you risk no more.")
        if (TUNING["bully"] and not opens and theirs and my_bb is not None and my_bb >= 40
                and max(theirs) <= TUNING["bully_bb"] and _bully_opens(s.pos, cls, pct)):
            # You cover everyone left: calling you risks their whole stack, so they fold a lot.
            return _aggressive(s, "raise", (3.0 if s.pos == "SB" else 2.5) * s.bb,
                               f"You have the big stack and everyone left has {int(max(theirs))} big blinds or "
                               f"less, so they can't play back without risking it all. Open {name} {where}.",
                               size_hint="Make it about 2.5 big blinds.",
                               relative=f"{3 if s.pos == 'SB' else 2.5:g} BIG BLINDS",
                               in_bb=3.0 if s.pos == "SB" else 2.5)
        if opens:
            to = (3.0 if s.pos == "SB" else 2.5) * s.bb if s.bb else None
            return _aggressive(s, "raise", to, f"{name} is strong enough to open {where}.",
                               size_hint="Make it about 2.5 big blinds.",
                               relative=f"{3 if s.pos == 'SB' else 2.5:g} BIG BLINDS",
                               in_bb=3.0 if s.pos == "SB" else 2.5)
        return Advice("fold", "FOLD", f"{name} ({top} of hands) is too weak to play {where}.")
    move = charts.vs_limpers(s.pos, cls)
    cheap = s.to_call is None or s.bb is None or s.to_call <= s.bb + 1e-9
    if move == "raise" and s.can_raise:
        to = (3.0 + limpers) * s.bb if s.bb else None
        who = "a player" if limpers == 1 else f"{limpers} players"
        return _aggressive(s, "raise", to, f"{name} is a {top} hand. {who.capitalize()} just called the blind: "
                                          "raise and take control.", size_hint="Make it about 3 big blinds plus "
                                                                              "1 for each caller.",
                           relative=f"{3 + limpers} BIG BLINDS", in_bb=3.0 + limpers)
    if move == "call" and cheap:
        return _call(s, f"{name} plays well in a cheap pot with several players. Just call.")
    if s.pos == "SB" and cheap and charts.opens("SB", cls):
        return _call(s, f"It's cheap to complete the small blind with {name}.")
    return Advice("fold", "FOLD", f"{name} ({top} of hands) is too weak to play {where}, even though "
                                  "nobody raised.")


# --------------------------------------------------------------- postflop
def _postflop(s: _Spot) -> Advice:
    eqs = s.computed.get("equity") or []
    if not eqs:
        return Advice("unknown", "NOT SURE", "The odds for this hand couldn't be worked out.", basis="none")
    eq = eqs[-1]
    e, stderr = float(eq["equity"]), float(eq.get("stderr", 0.0))
    made = s.computed.get("hand") or ""
    if s.computed.get("hand_note"):
        made = f"{made} ({s.computed['hand_note']})"
    draws = s.computed.get("draws") or []
    big_draw = next((d for d in draws if d in ("flush draw", "open-ended straight draw")), None)
    river = len(s.board) == 5
    win = f"You win about {_pct(e)} of the time against {_vs(s.n_opp)}"
    # Raising a bet needs a hand that is strong in itself: two pair or better that uses
    # your cards (trips or better on the river). One pair calls; their betting range
    # is stronger than their range overall.
    cat = hands.category(s.hero, s.board)
    strong_made = cat < hands.board_category(s.board) and cat <= (6 if river else 7)
    t = TUNING
    if s.n_opp == 1:
        value_raise = t["value_raise_river"] if river else t["value_raise_hu"]
        value_bet = t["value_bet_river"] if river else t["value_bet_hu"]
    else:
        value_raise, value_bet = t["value_raise_multi"], t["value_bet_multi"]
    still_in = [p for p in s.state.opponents if not (p.in_hand.known and p.in_hand.value is False)]
    value_bet += exploits.value_bet_shift(still_in)

    if river and t["river_solver"] and s.n_opp == 1:
        solved = _river_solver(s, made)
        if solved is not None:
            return solved

    if s.facing:
        if s.to_call is not None and s.pot is not None:
            call = min(s.to_call, s.stack) if s.stack is not None else s.to_call
            need = call / (s.pot + call)
            narrowed = _vs_betting_range(s, call)
            if narrowed is not None:
                e, stderr, who = narrowed
                win = f"You win about {_pct(e)} of the time against {who}"
                s.computed = dict(s.computed)
                s.computed.pop("verdict", None)  # that one was worked out against their whole range
            if strong_made and e >= value_raise and s.can_raise and (s.stack is None or s.stack > call):
                their = s.to_call + (s.hero_bet or 0.0)
                to, why = 3 * their, ""
                sized = _ev_raise(s, their, call) if t["ev_sizing"] else None
                if sized is not None:
                    to, why = sized
                return _aggressive(s, "raise", to, _join(f"{win} with {made}. Raise for value.", why),
                                   detail="If they re-raise big, just call.", relative="3X THEIR BET")
            adv = _math_call(s, e, stderr, win)
            if adv is not None and adv.action == "call" and _committed(s, call, e, big_draw):
                return _shove(s, f"{win} with {made}, and calling would leave you few chips behind. Put them "
                                 "all in now.")
            if adv is not None:
                if adv.action == "call" and e >= value_raise and not strong_made:
                    adv.detail = _join(adv.detail, "Don't raise: with one pair, mostly better hands would call.")
                return adv
            if (not river and big_draw and s.eff is not None and s.eff >= 3 * (s.pot + call)
                    and e + 0.07 >= need):
                return _call(s, f"You have a {big_draw}. The price is a bit high, but when you hit you can win "
                                "a lot more. Call.", basis="math")
            return Advice("fold", "FOLD", f"{win}, but you'd need {_pct(need)} to make calling worth it.",
                          basis="math")
        # a bet we can't measure
        if strong_made and e >= value_raise and s.can_raise:
            return Advice("raise", "RAISE TO 3X THEIR BET", f"{win} with {made}. Raise for value.",
                          detail="Make it about 3 times their bet.", missing=["amount to call"])
        if s.pot is not None and e < 1:
            limit = e / (1 - e) * s.pot
            return Advice("call", f"CALL UP TO {_amt(limit)}", f"{win}. Calling pays off if it costs {_amt(limit)} "
                          "or less. If it costs more, fold.", amount=_chips(limit), basis="math",
                          missing=["amount to call"])
        if e >= 0.5:
            return Advice("call", "CALL", f"{win}: you're ahead of their likely hands.", basis="math",
                          missing=["amount to call"])
        frac = e / (1 - 2 * e)
        return Advice("call", "CALL SMALL BETS ONLY", f"{win}. Call if the bet is at most {_pct(frac)} of the pot; "
                      "fold to anything bigger.", basis="math", missing=["amount to call"])

    # nobody has bet: check or bet
    pot_size = s.pot
    backup = ""
    if s.facing is None and s.pot is not None and e < 1:
        backup = f"If someone has already bet: call if it costs {_amt(e / (1 - e) * s.pot)} or less."
    texture = board_texture(s.board)
    share, words = t["bet_size"], "2/3 OF THE POT"
    if t["texture_sizing"]:
        share = t["sizes"][texture]
        words = {"dry": "1/3 OF THE POT", "medium": "HALF THE POT", "wet": "3/4 OF THE POT"}[texture]
    hint = f"Bet about {_share_words(share)} of the pot."
    need_bet = value_bet
    last = _acts_last(s)
    if t["oop_lead"] and s.n_opp == 1 and not last and len(s.board) == 3 and _raisers_board(s.board):
        need_bet = max(need_bet, t["oop_lead"])  # check to the raiser: these boards hit their range
    small_from = t["small_bet_from"] if (t["bucket_sizing"] and s.n_opp == 1 and last) else 0.0
    if t["pot_control"] and not strong_made and (s.n_opp >= 2 or not last):
        need_bet += t["pot_control"]  # one pair out of position or into several players: keep the pot small
    if e >= need_bet and s.can_raise:
        geo = _geometric(s) if (t["geometric"] and strong_made and pot_size) else None
        why = ""
        if geo is not None:
            share, hint = geo, f"Bet about {_share_words(geo)} of the pot."
        elif t["ev_sizing"] and s.n_opp == 1 and pot_size:
            sized = _ev_bet(s)
            if sized is not None:
                share, why = sized
                hint = f"Bet about {_share_words(share)} of the pot."
        elif t["bucket_sizing"] and e < 0.75:
            share, words = 1 / 3, "1/3 OF THE POT"  # good, not great: a small bet keeps worse hands calling
            hint, why = "Bet about a third of the pot.", "A small bet keeps their worse hands calling."
        return _aggressive(s, "bet", share * pot_size if pot_size else None,
                           _join(f"{win} with {made}. Bet: worse hands will pay you.", why), detail=backup,
                           size_hint=hint, relative=words)
    if small_from and e >= small_from and s.can_raise and pot_size:
        return _aggressive(s, "bet", pot_size / 3, f"{win} with {made}. Bet small: worse hands still call a small "
                           "bet.", detail=backup, size_hint="Bet about a third of the pot.", relative="1/3 OF THE POT")
    if (river and t["river_ip_call_share"] and s.n_opp == 1 and last and s.facing is False and s.can_raise
            and pot_size):
        vs_callers = _vs_calling_range(s, t["river_ip_call_share"])
        if vs_callers is not None and vs_callers > 0.5:
            return _aggressive(s, "bet", 0.5 * pot_size,
                               f"{win} with {made}. They checked and can't raise you back after this: you beat "
                               f"{_pct(vs_callers)} of the hands that would call, so a smaller bet wins more.",
                               detail=backup, size_hint="Bet about half the pot.", relative="HALF THE POT")
    if s.can_raise and _semibluffs(s, big_draw):
        outs = _outs(s.hero, s.board)
        hit = _hit_words(outs, len(s.board))
        share, why = 0.5, ""
        if t["ev_sizing"] and pot_size:
            sized = _ev_bet(s)
            if sized is not None:
                share, why = sized
        return _aggressive(s, "bet", share * pot_size if pot_size else None,
                           _join(f"You have a {_draw_name(draws, outs)} ({hit}). Bet: they may fold now, and if "
                                 "they call you can still hit.", why),
                           detail=backup, size_hint=f"Bet about {_share_words(share)} of the pot.",
                           relative="HALF THE POT")
    if (t["stab"] and s.n_opp == 1 and last and texture == "dry" and e >= t["stab"] and s.can_raise
            and s.facing is False):
        return _aggressive(s, "bet", 0.33 * pot_size if pot_size else None,
                           f"{win} with {made}. They checked on a dry board: a small bet often wins the pot "
                           "right away.", detail=backup, size_hint="Bet about a third of the pot.",
                           relative="1/3 OF THE POT")
    if e >= value_bet and s.can_raise:
        return Advice("check", "CHECK", f"{win} with {made}. Good, but not strong enough to bet into "
                      + ("several players" if s.n_opp >= 2 else "them from here") + ": check and keep the pot small.",
                      detail=backup)
    return Advice("check", "CHECK", f"{win} with {made}. Not strong enough to bet, so check.", detail=backup)


def _river_solver(s: _Spot, made: str) -> Optional[Advice]:
    """TUNING["river_solver"]: the river solver's action for your hand, heads-up. None
    (the rules decide) when the spot isn't one it handles, the numbers it needs aren't
    known or reliable, it fails, it doesn't answer in time, its answer is too rough, or
    it has no answer for a bet it didn't expect."""
    import time

    from app import solver
    from app.solver import bridge
    from app.solver.strategy import describe_mix
    from app.solver.timing import QUALITY_BAR
    from app.solver.tree import action_amount, describe_action

    opp = _only_opponent(s)
    if (opp is None or not s.trusted or s.pot is None or s.stack is None or not opp.stack.known
            or s.facing is None or (s.facing and not s.to_call)):
        return None
    villain_bet = (s.hero_bet or 0.0) + s.to_call if s.facing else 0.0
    decision = bridge.river_decision(s.hero, s.board, pot_now=s.pot, hero_bet=s.hero_bet or 0.0,
                                     villain_bet=villain_bet, hero_stack=s.stack,
                                     villain_stack=float(opp.stack.value), hero_in_position=_acts_last(s),
                                     # what the ranges are worked out from: the betting so far
                                     line=getattr(s.state, "betting", None), big_blind=s.bb, hero_seat=s.pos,
                                     villain_seat=opp.position.value if opp.position.known else None,
                                     villain_style=exploits.style(opp), villain_rates=getattr(opp, "played", None))
    if decision is None:
        return None
    budget = solver.DECISION_BUDGET_MS
    fixed = bool(TUNING["river_solver_fixed_work"])  # the simulator: the same answer on every run
    start = time.perf_counter()
    try:
        strategy = solver.solve_river(decision.spot, **solver.decision_settings(decision.spot, s.bb, fixed))
        elapsed_ms = 1000.0 * (time.perf_counter() - start)
        if strategy is None or (elapsed_ms > budget and not fixed):
            return None
        if (strategy.exploitability or 0.0) > QUALITY_BAR:  # too far from an equilibrium to act on
            return None
        answer = bridge.recommend(strategy, decision)
        if answer is None:  # a bet the solution has no hands for: it has no answer here
            return None
        token, mix = answer[0], describe_mix(answer[1])
    except NotImplementedError:
        return None
    except Exception:  # a solver failure must never cost the instruction: the rules decide
        log.exception("River solver failed; using the rules")
        return None
    reason = f"With {made}, the river solver's play here is to {describe_action(token)}."
    detail = f"Its mix for your hand: {mix}."
    story = decision.line.describe() if decision.line is not None else ""
    if story:  # what it took their hands and yours to be, from the betting
        detail += (" Hands guessed from the size of the pot: " if decision.guessed else " Hands judged from: ") + story + "."
    kind, amount = token[:1], action_amount(token)
    if kind == "x":
        return Advice("check", "CHECK", reason, basis="solver", detail=detail)
    if kind == "f":
        return Advice("fold", "FOLD", reason, basis="solver", detail=detail)
    if kind == "c":
        return _call(s, reason, detail=detail, basis="solver")
    return _aggressive(s, "bet" if kind == "b" else "raise", amount, reason, detail=detail, basis="solver")


def _raisers_board(board: Tuple[str, ...]) -> bool:
    """Flops that favour the preflop raiser: an ace, king or queen, a pair, one suit, or dry.
    Low connected flops hit the caller's range."""
    top = max(hands.RANKS.index(c[0]) for c in board)
    paired = len({c[0] for c in board}) < len(board)
    mono = len({c[1] for c in board}) == 1
    return top >= hands.RANKS.index("Q") or paired or mono or board_texture(board) == "dry"


def _only_opponent(s: _Spot) -> Optional[Player]:
    left = [p for p in s.state.opponents if not (p.in_hand.known and p.in_hand.value is False)]
    return left[0] if len(left) == 1 else None


def _outs(hero: Tuple[str, ...], board: Tuple[str, ...]) -> int:
    """Cards that give you a straight or better with your own cards on the next card."""
    dead = set(hero) | set(board)
    n = 0
    for c in hands.DECK:
        if c in dead:
            continue
        nb = tuple(board) + (c,)
        cat = hands.category(hero, nb)
        if cat <= 5 and cat < hands.board_category(nb):
            n += 1
    return n


def _hit_words(outs: int, board_len: int) -> str:
    """The chance to hit, in words: 'about 1 in 5 to hit on the river'."""
    if board_len == 3:
        p = 1 - (47 - outs) * (46 - outs) / (47 * 46)
        when = "by the river"
    else:
        p = outs / 46
        when = "on the river"
    if p >= 0.45:
        return f"about an even chance to hit {when}"
    return f"about 1 in {max(2, int(round(1 / max(p, 1e-9))))} to hit {when}"


def _draw_name(draws: List[str], outs: int) -> str:
    big = [d for d in draws if d in ("flush draw", "open-ended straight draw")]
    if outs >= 12 and ("flush draw" in draws and any("straight" in d for d in draws)):
        return "flush draw and a straight draw"
    return big[0] if big else "draw"


def _semibluffs(s: _Spot, big_draw: Optional[str]) -> bool:
    """Bet a big draw heads-up: always on the flop (two cards to come), on the turn only as
    the setting says (one card to come hits about 1 time in 5). Never into a calling station."""
    t = TUNING
    if not t["semibluff"] or s.n_opp != 1 or not big_draw or len(s.board) >= 5:
        return False
    opp = _only_opponent(s)
    if exploits.calls_a_lot(opp):
        return False
    if len(s.board) == 3:
        return True
    mode = t["semibluff_turn"]
    if mode == "always":
        return True
    if mode == "combo":
        return _outs(s.hero, s.board) >= 12 or exploits.folds_a_lot(opp)
    return False


def _continuing(s: _Spot, base, frac: float, opp: Optional[Player], cache: dict) -> Tuple[float, float]:
    """(share of their range that continues against a bet of frac times the pot, your chance
    of winning against those hands)."""
    c = exploits.continue_share(opp, 1.0 / (1.0 + frac))
    key = round(c, 3)
    if key not in cache:
        dead = tuple(s.hero) + tuple(s.board)
        combos = ranges.betting_range(base, tuple(s.board), dead, c, 0.0)
        eq = None
        if len(combos) >= 5:
            try:
                eq = equity(s.hero, s.board, 1, combos, budget_s=TUNING["sizing_budget_s"],
                            max_iterations=TUNING["sizing_iterations"]).equity
            except ValueError:
                eq = None
        cache[key] = eq
    return c, cache[key]


def _ev_bet(s: _Spot) -> Optional[Tuple[float, str]]:
    """The bet size (share of the pot) with the best expected value when they fold the
    bottom of their range to bigger bets: P(fold) x pot + P(call) x (win x (pot + 2 bet) - bet)."""
    pot = s.pot
    if not pot or pot <= 0:
        return None
    opp = _only_opponent(s)
    base = make_range("medium").combos
    fracs = list(SIZES)
    if s.stack is not None and s.trusted and s.stack <= 1.5 * pot:
        fracs.append(s.stack / pot)  # all in when the stack is short
    if s.stack is not None:
        fracs = sorted({min(f, s.stack / pot) for f in fracs})
    cache: dict = {}
    best = None
    for f in fracs:
        c, eq = _continuing(s, base, f, opp, cache)
        if eq is None:
            continue
        bet = f * pot
        ev = (1 - c) * pot + c * (eq * (pot + 2 * bet) - bet)
        if best is None or ev > best[0] + 1e-9:
            best = (ev, f)
    if best is None:
        return None
    f = best[1]
    if f < 0.6:
        why = "A smaller bet keeps their worse hands calling."
    elif f > 0.75:
        why = "Their calling hands are worse than yours even against a big bet, so bet big."
    else:
        why = ""
    return f, why


def _ev_raise(s: _Spot, their: float, call: float) -> Optional[Tuple[float, str]]:
    """The raise size with the best expected value against the hands that bet
    (s.betting_combos): bigger raises make more of them fold."""
    combos = getattr(s, "betting_combos", None)
    if not combos or s.pot is None or s.total is None:
        return None
    opp = _bettor(s)
    mine = s.hero_bet or 0.0
    tos = [m * their for m in (2.5, 3.0, 4.0)]
    if s.trusted and s.total <= 1.5 * (s.pot + call):
        tos.append(s.total)  # all in when the stack is short
    tos = sorted({min(x, s.total) for x in tos if x > their})
    cache: dict = {}
    best = None
    for to in tos:
        extra = to - their  # what they must add to call
        ours = to - mine
        frac = extra / max(1e-9, s.pot + call)
        c, eq = _continuing(s, combos, frac, opp, cache)
        if eq is None:
            continue
        ev = (1 - c) * s.pot + c * (eq * (s.pot + ours + extra) - ours)
        if best is None or ev > best[0] + 1e-9:
            best = (ev, to)
    if best is None:
        return None
    to = best[1]
    why = "A smaller raise keeps their worse hands calling." if to < 2.9 * their else ""
    return to, why


def _committed(s: _Spot, call: float, e: float, big_draw: Optional[str]) -> bool:
    """Heads-up before the river, calling would leave only a little behind compared with the
    pot, and you're ahead of their betting hands (or have a big draw on the flop): put the rest
    in now rather than call and face another bet with what's left."""
    t = TUNING
    if not t["commit"] or s.n_opp != 1 or len(s.board) == 5 or not s.trusted or not s.can_raise:
        return False
    if s.stack is None or s.pot is None or s.stack <= call or s.stack - call > t["commit"] * (s.pot + call):
        return False
    bettor = _bettor(s)
    if bettor is None or not bettor.stack.known or float(bettor.stack.value) <= 0:
        return False  # they're all in already (or it can't be told): just call
    if _top_pair_plus(s.hero, s.board) and e >= 0.5:
        return True
    return bool(t["commit_draws"] and big_draw and len(s.board) == 3 and e >= 0.38)


def _geometric(s: _Spot) -> Optional[float]:
    """The share of the pot to bet each street so the stacks go in by the river:
    (1 + 2f) ** streets_left = 1 + 2 * stack_to_pot."""
    if s.eff is None or not s.pot:
        return None
    n = {3: 3, 4: 2, 5: 1}[len(s.board)]
    spr = s.eff / s.pot
    f = ((1 + 2 * spr) ** (1.0 / n) - 1) / 2
    return min(1.0, max(0.33, f))


def _vs_calling_range(s: _Spot, share: float) -> Optional[float]:
    """Your chance of winning against the hands that would call a bet (their strongest
    `share` on this board)."""
    base = make_range("medium").combos
    dead = tuple(s.hero) + tuple(s.board)
    combos = ranges.betting_range(base, tuple(s.board), dead, share, 0.0)
    if len(combos) < 5:
        return None
    try:
        r = equity(s.hero, s.board, 1, combos, budget_s=TUNING["facing_budget_s"],
                   max_iterations=TUNING["facing_iterations"])
    except ValueError:
        return None
    return r.equity


def _share_words(share: float) -> str:
    if share >= 0.9:
        return "the whole"
    if share <= 0.36:
        return "a third"
    if share <= 0.56:
        return "half"
    if share <= 0.70:
        return "two thirds"
    return "three quarters"


def board_texture(board: Tuple[str, ...]) -> str:
    """'dry' (unconnected, one suit at most twice), 'wet' (flush or straight cards
    everywhere) or 'medium'. Bets are sized to it: small where few hands can catch up."""
    if not board:
        return "medium"
    from collections import Counter

    suits = Counter(c[1] for c in board)
    ranks = {hands.RANKS.index(c[0]) for c in board}
    if 12 in ranks:
        ranks = ranks | {-1}  # the ace also plays low
    conn = max(sum(1 for r in ranks if w <= r <= w + 4) for w in range(-1, 9))
    flushy = max(suits.values())
    if flushy >= 3 or conn >= 4 or (conn >= 3 and flushy >= 2):
        return "wet"
    rainbow = flushy <= 1 or (len(board) > 3 and flushy <= 2)
    if rainbow and conn <= 2:
        return "dry"
    return "medium"


def _acts_last(s: _Spot) -> bool:
    """You act after everyone still in the hand (in position)."""
    if s.pos is None:
        return False
    others = [p.position.value for p in s.state.opponents
              if p.position.known and (not p.in_hand.known or p.in_hand.value)]
    return all(_in_position(s.pos, o) for o in others)
