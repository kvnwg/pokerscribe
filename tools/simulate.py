"""Play the app's instructions against simulated opponents and measure how much it wins.

    python tools/simulate.py [hands] [--table mixed|stations|nits|tags|lags|maniacs] [--seed N] [--deep]
                             [--stacks even|uneven|tourney] [--profiles] [--players 2]

With --players 2 the game is heads-up: the app against one bot of the table at a time (a
different one of the table's five, drawn for each deal). Heads-up rules: the button posts
the small blind and the other player the big blind; the button acts first before the flop
and last after it. The seats are named as the app reads them ("BTN/SB" and "BB").

A 6-max no-limit hold'em table, blinds 1/2, everyone topped up to 100 big blinds at the
start of each hand (500 with --deep, like 247 Free Poker). With --stacks uneven the bots
sit with 15 to 250 big blinds and the app with 100, so it is sometimes the big stack with
short stacks behind it; with --stacks tourney everyone is shallow like a tournament (bots
8 to 70 big blinds, the app 8 to 150), so the app is sometimes short and sometimes the
big stack. Stacks are drawn from the hand's seed, so paired comparisons see the same
stacks. Short bots (15 big blinds or less) move all in instead of making small raises,
as real short stacks do. With --profiles the app learns each bot's style from the hands,
as in watch mode (profiles.update on every action it sees, profiles.annotate before
advise), so the advice's exploits for stations, nits and maniacs are measured. Seat 0
follows advise()
exactly as the app would show it; the other five seats are bots with a playing style:

    station  plays half its hands, calls with any pair or draw, rarely bets
    nit      plays 14% of hands, bets only strong hands, folds to pressure
    tag      a solid regular: about 22% of hands, raises most of them, bets for value
    lag      loose and aggressive: 35% of hands, c-bets and bluffs a lot
    maniac   plays 60% of hands and bets or raises most of the time

The button moves every hand, so the app plays every position equally. Each hand uses a
seed, so two versions of the app can be compared on exactly the same cards and the same
opponent decisions (much less luck in the comparison).

Prints the win rate in big blinds per 100 hands with its standard error, and where the
chips were won and lost (by street, by the app's action, preflop opening by position).
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.poker import hands  # noqa: E402
from app.poker.advice import advise  # noqa: E402
from app.poker.ranges import preflop_percentile  # noqa: E402
from app.state.model import Action, Field, GameState, Player  # noqa: E402
from app.state.positions import position_names  # noqa: E402

SB, BB = 1.0, 2.0
POSITIONS = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]  # by seat offset from the button
assert POSITIONS == position_names(6)  # the names the app reads off a six-seat table
PREFLOP_FIRST = 3  # UTG acts first preflop
PLAYERS = (2, 6)  # table sizes: heads-up and six-max


def blind_seats(button: int, n: int) -> Tuple[int, int]:
    """The small and big blind's seats. Heads-up the button posts the small blind."""
    return (button, (button + 1) % n) if n == 2 else ((button + 1) % n, (button + 2) % n)


def first_to_act(button: int, n: int, preflop: bool) -> int:
    """Who acts first: before the flop the seat after the big blind (heads-up the button, which
    is the small blind); after it the first seat after the button (heads-up the big blind)."""
    if preflop:
        return button if n == 2 else (button + PREFLOP_FIRST) % n
    return (button + 1) % n


STYLES = {
    #          vpip  pfr  3bet  postflop: bet_strength  call_strength  bluff  aggression
    "station": (0.50, 0.08, 0.02, 0.80, 0.30, 0.02, 0.15),
    "nit": (0.14, 0.11, 0.03, 0.80, 0.70, 0.03, 0.50),
    "tag": (0.22, 0.18, 0.06, 0.65, 0.55, 0.12, 0.65),
    "lag": (0.35, 0.28, 0.10, 0.55, 0.45, 0.30, 0.80),
    "maniac": (0.60, 0.45, 0.20, 0.40, 0.35, 0.50, 0.95),
    # like the 247 Free Poker bots as far as we can tell: plays many hands, rarely raises
    # before the flop, calls a lot after it, and bets only strong hands
    "fish247": (0.40, 0.06, 0.01, 0.85, 0.35, 0.02, 0.20),
}
# Starting stacks in big blinds when they are not all the same: (the app's, the bots'),
# one drawn for each seat every hand.
STACKS = {
    "uneven": ((100,), (15, 25, 40, 60, 100, 150, 250)),
    "tourney": ((8, 12, 15, 20, 30, 45, 70, 100, 150), (8, 12, 15, 20, 25, 35, 50, 70)),
}
SHORT_BOT = 15  # a bot with this many big blinds or fewer moves all in instead of raising small
# With --short-raise, short bots raise small instead (3 to 4 big blinds), committing part of
# their stack, as some 247 Free Poker bots do (a raise to 30 of 100 at 5/10)
SHORT_RAISE = False

TABLES = {
    "mixed": ["station", "nit", "tag", "lag", "maniac"],
    "stations": ["station"] * 5, "nits": ["nit"] * 5, "tags": ["tag"] * 5,
    "lags": ["lag"] * 5, "maniacs": ["maniac"] * 5,
    "fish247": ["fish247"] * 5,
}
TUNING_TABLES = tuple(TABLES)  # every strategy option so far was chosen or rejected on these

# Held-out opponents (Phase 1): never used to choose or tune a strategy option, so a result
# on them says whether a change generalises beyond the bots it was tuned on. Each is a base
# style (the seven numbers of STYLES) plus something the tuning bots never do.
HELD_OUT = {
    # bets 1.1 to 1.8 times the pot (the tuning bots bet half to 0.9)
    "overbettor": {"base": (0.30, 0.20, 0.07, 0.60, 0.50, 0.25, 0.75), "size": (1.1, 1.8)},
    # bets a quarter to a third of the pot, often
    "minbettor": {"base": (0.32, 0.14, 0.05, 0.50, 0.45, 0.25, 0.80), "size": (0.25, 0.35)},
    # checks its strong hands 70% of the time and raises when someone bets (slowplays)
    "trapper": {"base": (0.25, 0.12, 0.05, 0.85, 0.45, 0.05, 0.40), "trap": 0.7, "raise": 0.8},
    # plays like a nit before the flop, so it gets labelled one, and like a lag after it
    "mimic": {"base": (0.14, 0.11, 0.03, 0.45, 0.40, 0.45, 0.90)},
    # a calling station for 30 hands, then a maniac for 30, and so on (each bot out of step)
    "switcher": {"phases": ("station", "maniac"), "every": 30},
    # set to the action shares of the HandHQ population (DATASET.md, all table sizes): about
    # 14% of preflop decisions raise; checked to after the flop it bets about 36%; facing a
    # bet it folds about 53%, calls 37% and raises 10%. A population average, not a clone of
    # any player (that needs the built dataset, tools/phh)
    "regular": {"base": (0.30, 0.18, 0.06, 0.45, 0.35, 0.30, 0.75)},
    # each bot (by name) has its own random style, drawn once from a fixed seed
    "wildcard": {"random": True},
}
TABLES.update({
    "heldout": ["overbettor", "minbettor", "trapper", "mimic", "switcher"],
    "regulars": ["regular"] * 5,
    "switchers": ["switcher"] * 5,
    "wildcards": ["wildcard"] * 5,
})
HELD_OUT_TABLES = tuple(t for t in TABLES if t not in TUNING_TABLES)


@dataclass
class Seat:
    style: str  # "app" for the app
    stack: float = 0.0
    name: str = ""  # follows the bot from seat to seat, so profiles can learn it
    cards: Tuple[str, str] = ("", "")
    bet: float = 0.0  # this round
    put_in: float = 0.0  # this hand
    folded: bool = False
    all_in: bool = False
    last: Optional[Action] = None
    acted: bool = False


@dataclass
class Hand:
    seats: List[Seat]
    button: int
    board: List[str] = field(default_factory=list)
    pot_before: float = 0.0  # chips from earlier rounds
    current: float = 0.0  # highest bet this round
    min_raise: float = BB
    log: List[tuple] = field(default_factory=list)
    diverged: bool = False
    profiles: object = None  # the app's Profiles (app.poker.profiles), learned from what it sees
    number: int = 0  # hand number for the profiles
    # keyed bot randomness: with a key, each bot decision draws from its own seed (hand, seat,
    # street, how many times that seat has acted on that street), so two variants of the app
    # that part ways in a hand still give the bots the same random numbers decision by decision
    rng_key: Optional[int] = None
    # resampling after the variants part ways (docs/research/runs/phase1_variance_split.py):
    # once the app has made its decision number `split_at`, the bots draw from seeds salted
    # with `resample` and the board cards still to come are drawn afresh from the unseen cards
    split_at: Optional[int] = None
    resample: Optional[int] = None
    diverge_at: Optional[int] = None  # the app's decision where a shadow variant first disagreed
    last_spec: object = None  # the seed of the bot decision being made
    rng_counts: Dict[tuple, int] = field(default_factory=dict)
    chance: List[dict] = field(default_factory=list)  # board cards dealt while the app was in (tools/luck.py)
    spots: List[dict] = field(default_factory=list)  # the app's decisions, for tools/weakness.py
    # every bot decision with what it saw and its seed, and the order of all events (bot and app
    # moves, board cards), so tools/hidden.py can ask what a bot would have done with other cards
    bot_decisions: List[dict] = field(default_factory=list)
    events: List[tuple] = field(default_factory=list)

    def bot_rng(self, i: int, stream: random.Random) -> random.Random:
        if self.rng_key is None:
            self.last_spec = None
            return stream
        self.last_spec = self.bot_spec(i)
        return random.Random(self.last_spec)

    def bot_spec(self, i: int):
        """The seed of bot i's next decision (keyed randomness): an int, or a string after the
        split when resampling. random.Random(spec) gives the same numbers again."""
        k = (i, len(self.board))
        n = self.rng_counts.get(k, 0)
        self.rng_counts[k] = n + 1
        if self.resample is not None and self.split_at is not None and len(self.spots) > self.split_at:
            return f"{self.rng_key}/{self.resample}/{i}/{len(self.board)}/{n}"
        return ((self.rng_key * 8 + i) * 8 + len(self.board)) * 64 + n

    def position(self, i: int) -> str:
        n = len(self.seats)
        return (POSITIONS if n == 6 else position_names(n))[(i - self.button) % n]

    @property
    def pot(self) -> float:
        return self.pot_before + sum(s.bet for s in self.seats)

    def active(self) -> List[int]:
        return [i for i, s in enumerate(self.seats) if not s.folded]


# ----------------------------------------------------------------- the app
def app_state(h: Hand, me: int) -> GameState:
    """What the app would read off the screen: cards, positions, stacks, bets in front of
    players, the pot without this round's bets, the amount to call and the buttons."""
    players = []
    for i, s in enumerate(h.seats):
        p = Player(seat=(i - me) % len(h.seats), is_hero=i == me, position=Field.manual(h.position(i)),
                   stack=Field.manual(s.stack), bet=Field.manual(s.bet), in_hand=Field.manual(not s.folded),
                   name="You" if i == me else (s.name or f"P{i}"))
        if s.last is not None:
            p.last_action = Field.manual(s.last)
        players.append(p)
    players.sort(key=lambda p: p.seat)
    st = GameState(hero_cards=[Field.manual(c) for c in h.seats[me].cards], board=[Field.manual(c) for c in h.board],
                   players=players)
    st.street = Field.manual({0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(h.board)])
    st.pot = Field.manual(h.pot_before)
    st.pot_includes_bets = False
    st.blinds = Field.manual((SB, BB))
    to_call = max(0.0, h.current - h.seats[me].bet)
    st.to_call = Field.manual(min(to_call, h.seats[me].stack))
    acts = [Action("fold"), Action("call", to_call)] if to_call > 0 else [Action("check")]
    if h.seats[me].stack > to_call:
        acts.append(Action("raise" if h.current > 0 else "bet"))
    st.available_actions = Field.manual(acts)
    st.hero_to_act = Field.manual(True)
    return st


class _Track:
    """What the live app's hand tracker gives the profiles: chips each player put in this hand
    and this round (indexes into state.players), all adding up."""

    def __init__(self, h: Hand, st: GameState, me: int):
        self.valid = True
        self.blinds = (SB, BB)
        self.contributions, self.street_bets = {}, {}
        for k, p in enumerate(st.players):
            i = (p.seat + me) % len(h.seats)
            self.contributions[k] = h.seats[i].put_in
            self.street_bets[k] = h.seats[i].bet


def observe(h: Hand, me: int) -> Optional[GameState]:
    """The app's read of the table now: its profiles learn from it (as in watch mode), and its
    opponents get their styles."""
    st = app_state(h, me)
    if h.profiles is not None:
        h.profiles.update(st, _Track(h, st, me), h.number)
        h.profiles.annotate(st)
    return st


def check_advice(h: Hand, me: int, adv, stats) -> None:
    """Instructions that are wrong whatever the strategy: count and keep examples."""
    seat = h.seats[me]
    to_call = h.current - seat.bet
    cls = hands.preflop_class(seat.cards)
    problems = []
    if adv.action in ("wait", "unknown"):
        problems.append(f"{adv.headline} on your turn")
    if adv.action == "fold" and to_call <= 1e-9:
        problems.append("fold when checking is free")
    if adv.action in ("bet", "raise") and adv.amount is None:
        problems.append(f"{adv.headline}: no amount")
    if adv.action in ("bet", "raise") and adv.amount is not None and adv.amount <= h.current + 1e-9:
        problems.append(f"{adv.headline}: not more than the current bet {h.current:g}")
    if adv.action == "all-in" and not adv.headline.startswith("CALL"):
        depth = (seat.stack + seat.bet) / BB
        if depth >= 40 and not h.board and preflop_percentile(cls) > 0.05:
            problems.append(f"all in {depth:.0f}bb deep preflop with {cls}")
        elif depth >= 25 and not h.board and preflop_percentile(cls) > 0.10 and any(
                not o.folded and o.stack + o.bet >= 25 * BB for j, o in enumerate(h.seats) if j != me):
            # one short opponent is never a reason to go all in while a big stack is still in
            problems.append(f"all in {depth:.0f}bb with {cls} while a big stack is in")
    if adv.action == "fold" and h.board:
        rank = hands.evaluate(seat.cards, h.board)
        if len(h.board) == 5:
            # the nuts never folds: nothing beats you
            dead = set(seat.cards) | set(h.board)
            rest = [c for c in hands.DECK if c not in dead]
            best_other = min(hands.evaluate((a, b), h.board) for k, a in enumerate(rest) for b in rest[k + 1:])
            if rank <= best_other:
                problems.append("folded the best possible hand")
    if "Someone raised" in adv.reason and to_call <= 1e-9:
        problems.append("'someone raised' with nothing to call")
    # moves the table can't take as said (added with the heads-up mode)
    if adv.action == "call" and to_call <= 1e-9:
        problems.append("call with nothing to call")
    if adv.action == "check" and to_call > 1e-9:
        problems.append("check facing a bet")
    total = seat.stack + seat.bet
    if adv.action in ("bet", "raise") and adv.amount is not None:
        if adv.amount < min(total, h.current + h.min_raise) - 1e-9:
            problems.append(f"below the minimum bet or raise: {adv.headline}")
        if adv.amount > total + 1e-9:
            problems.append(f"more than the stack: {adv.headline}")
    if adv.action == "fold" and not h.board and cls == "AA":
        problems.append("folded AA before the flop")
    for p in problems:
        stats["problems"][p.split(":")[0] if ":" in p else p] += 1
        if len(stats["examples"]) < 25:
            stats["examples"].append((p, cls, " ".join(h.board), h.position(me), round(to_call, 1),
                                      round(h.pot, 1), adv.headline))


ITERATIONS = 400  # Monte Carlo samples per equity estimate: a fixed count keeps every run repeatable


def sim_compute(st: GameState) -> dict:
    """What app.poker.calculator.compute gives the advice, with a fixed number of samples
    instead of a time budget (same answer every run, so two variants can be compared)."""
    from app.poker.calculator import opponents_in_hand
    from app.poker.equity import equity
    from app.poker.ranges import make_range

    hero = tuple(c.value for c in st.hero_cards)
    board = tuple(c.value for c in st.board)
    out: dict = {}
    if board:
        out["hand"] = hands.describe(list(hero) + list(board))
        note = hands.shared_note(hero, board)
        if note:
            out["hand_note"] = note
        d = hands.draws(hero, board)
        if d:
            out["draws"] = d
    n = opponents_in_hand(st)
    eqs = []
    for spec in (make_range("any"), make_range("medium")):
        r = equity(hero, board, n, spec.combos, budget_s=60.0, max_iterations=ITERATIONS)
        eqs.append({"label": spec.label, "opponents": n, "equity": r.equity, "stderr": r.stderr,
                    "iterations": r.iterations, "exact": r.exact})
    out["equity"] = eqs
    return out


class variant:
    """Temporarily change advice.TUNING (a strategy variant)."""

    def __init__(self, overrides: Optional[dict]):
        self.overrides = overrides or {}

    def __enter__(self):
        from app.poker import advice as adv_mod

        self.saved = {k: adv_mod.TUNING[k] for k in self.overrides}
        adv_mod.TUNING.update(self.overrides)
        adv_mod.TUNING["facing_budget_s"], adv_mod.TUNING["facing_iterations"] = 60.0, ITERATIONS
        adv_mod.TUNING["allin_budget_s"] = 60.0
        adv_mod.TUNING["sizing_budget_s"], adv_mod.TUNING["sizing_iterations"] = 60.0, ITERATIONS
        adv_mod.TUNING["river_solver_fixed_work"] = True  # the river solver, when a variant turns it on
        return self

    def __exit__(self, *exc):
        from app.poker import advice as adv_mod

        adv_mod.TUNING.update(self.saved)
        adv_mod.TUNING["facing_budget_s"], adv_mod.TUNING["facing_iterations"] = 0.12, 60000
        adv_mod.TUNING["allin_budget_s"] = 0.35
        adv_mod.TUNING["sizing_budget_s"], adv_mod.TUNING["sizing_iterations"] = 0.03, 4000
        adv_mod.TUNING["river_solver_fixed_work"] = False


# Replays from the split (tools/compare.py --resample) play the same hand again and again: up
# to the split the app sees exactly the same table each time (the opponents' cards are not part
# of what it sees), so its advice there is kept for the hand and reused.
_PRE_SPLIT_ADVICE: Dict[tuple, object] = {}


def clear_advice_cache() -> None:
    _PRE_SPLIT_ADVICE.clear()


def decision(h: Hand, me: int, overrides: Optional[dict], st: Optional[GameState] = None):
    import copy

    key = None
    if h.split_at is not None and h.rng_key is not None and len(h.spots) <= h.split_at and h.profiles is None:
        key = (h.rng_key, len(h.spots), repr(sorted((overrides or {}).items())))
        if key in _PRE_SPLIT_ADVICE:
            return _PRE_SPLIT_ADVICE[key]
    st = observe(h, me) if st is None else copy.deepcopy(st)
    with variant(overrides):
        adv = advise(st, computed=sim_compute(st), numbers_checked=True)
    if key is not None:
        _PRE_SPLIT_ADVICE[key] = adv
    return adv


STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


def pot_type(h: Hand) -> str:
    """How the pot went before the flop so far: limped, raised once, 3-bet, 4-bet or more."""
    raises = sum(1 for a in h.log if a[3] == 0 and a[1] == "raise")
    return ["limped", "raised", "3-bet", "4-bet+"][min(raises, 3)]


def spot(h: Hand, me: int, action: str) -> dict:
    """What the weakness report groups by: street, position, pot type, players, facing a bet,
    the hand's strength and the action taken."""
    seat = h.seats[me]
    to_call = max(0.0, h.current - seat.bet)
    if h.board:
        made = hands.CATEGORY[hands.category(seat.cards, h.board)]
        draw = bool(len(h.board) < 5 and hands.draws(seat.cards, h.board))
    else:
        pct = preflop_percentile(hands.preflop_class(seat.cards))
        made = "top 5%" if pct <= 0.05 else "top 15%" if pct <= 0.15 else "top 35%" if pct <= 0.35 else "rest"
        draw = False
    return {"street": STREETS[len(h.board)], "pos": h.position(me), "pot_type": pot_type(h),
            "situation": situation(h, me), "players": len(h.active()), "facing": to_call > 0, "made": made,
            "draw": draw, "action": action, "pot_bb": h.pot / BB, "to_call_bb": to_call / BB,
            "put_in_bb": seat.put_in / BB, "board_len": len(h.board), "current_bb": h.current / BB,
            "live": tuple(h.active()),
            "stack_bb": (seat.stack + seat.bet) / BB}


def situation(h: Hand, me: int) -> str:
    """What the app faces: before the flop first in, limpers, a raise or a 3-bet or more;
    after it checked to (or first), a bet, or a raise."""
    raises = sum(1 for a in h.log if a[3] == len(h.board) and a[1] == "raise")
    facing = h.current > h.seats[me].bet
    if not h.board:
        if raises == 0:
            limps = sum(1 for a in h.log if a[3] == 0 and a[1] == "call")
            return "limpers" if limps else ("checked to" if not facing else "first in")
        return "facing a raise" if raises == 1 else "facing a 3-bet+"
    if not facing:
        return "checked to"
    return "facing a bet" if raises == 1 else "facing a raise"


def app_decide(h: Hand, me: int, budget_ms: int, stats) -> Tuple[str, float]:
    st = observe(h, me)
    adv = decision(h, me, stats.get("variant"), st)
    shadow = stats.get("shadow")
    if shadow is not None and not h.diverged:
        other = decision(h, me, shadow, st)
        if (other.action, other.amount) != (adv.action, adv.amount):
            h.diverged = True  # the two variants part ways in this hand: replay it with the other one
            h.diverge_at = len(h.spots)
    stats["advice"][(len(h.board), adv.action)] += 1
    check_advice(h, me, adv, stats)
    record = spot(h, me, adv.action)
    move = app_move(h, me, adv)
    hook = stats.get("hook")  # tools/weakness.py: a planted flaw, or another move at one decision
    if hook is not None:
        move = hook(h, me, adv, move)
    record["move"], record["to_bb"] = move[0], move[1] / BB
    h.spots.append(record)
    return move


def app_move(h: Hand, me: int, adv) -> Tuple[str, float]:
    """The table move for an instruction: fold, check, call, or raise to an amount."""
    seat = h.seats[me]
    to_call = h.current - seat.bet
    total = seat.stack + seat.bet
    if adv.action in ("bet", "raise"):
        to = adv.amount
        if to is None:  # a size in words only: two thirds of the pot, or 3x the bet
            to = h.current * 3 if h.current > 0 else max(BB, 2 / 3 * h.pot)
        return "raise", min(total, to)
    if adv.action == "all-in":
        if adv.headline.startswith("CALL"):
            return "call", 0.0
        return "raise", total
    if adv.action == "call":
        return ("call", 0.0) if to_call > 0 else ("check", 0.0)
    if adv.action == "check":
        return ("check", 0.0) if to_call <= 0 else ("fold", 0.0)
    return ("check", 0.0) if to_call <= 0 else ("fold", 0.0)


# ----------------------------------------------------------------- the bots
def strength(cards, board) -> float:
    """0..1: share of random hands this hand beats right now, plus something for draws."""
    if not board:
        return 1.0 - preflop_percentile(hands.preflop_class(cards))
    rank = hands.evaluate(cards, board)
    base = 1.0 - (rank - 1) / 7461.0
    base = base ** 2.2  # the evaluator's scale is generous to weak pairs
    d = hands.draws(cards, board) if len(board) < 5 else []
    if d:
        base = max(base, 0.45 if any("flush" in x or "open-ended" in x for x in d) else 0.3)
    return base


def _bot_number(s: Seat) -> int:
    """The bot's number in its table (names are style + number, see seating)."""
    tail = s.name[len(s.style):] if s.name.startswith(s.style) else ""
    return int(tail) if tail.isdigit() else 0


def bot_style(h: Hand, s: Seat) -> Tuple[str, tuple, dict]:
    """The style a bot plays this hand: its name, its seven numbers and any extras."""
    if s.style in STYLES:
        return s.style, STYLES[s.style], {}
    extra = HELD_OUT[s.style]
    if "phases" in extra:
        j = _bot_number(s)
        style = extra["phases"][((h.number + 7 * j) // extra["every"]) % len(extra["phases"])]
        return style, STYLES[style], {}
    if extra.get("random"):
        return s.style, wildcard(_bot_number(s)), {}
    return s.style, extra["base"], extra


def wildcard(j: int) -> tuple:
    """Wildcard bot j's style, the same every run."""
    r = random.Random(1000 + j)
    vpip = r.uniform(0.12, 0.65)
    pfr = vpip * r.uniform(0.2, 0.8)
    return (vpip, pfr, pfr * r.uniform(0.15, 0.5), r.uniform(0.4, 0.85), r.uniform(0.3, 0.7), r.uniform(0.02, 0.5),
            r.uniform(0.15, 0.95))


def bot_decide(h: Hand, i: int, rng: random.Random) -> Tuple[str, float]:
    s = h.seats[i]
    style, numbers, extra = bot_style(h, s)
    vpip, pfr, three, bet_s, call_s, bluff, aggr = numbers
    to_call = h.current - s.bet
    total = s.stack + s.bet
    if not h.board:
        pct = preflop_percentile(hands.preflop_class(s.cards))
        raised = h.current > BB
        short = total <= SHORT_BOT * BB and not SHORT_RAISE  # short stacks move all in rather than raise small
        if not raised:
            if pct <= pfr:
                return "raise", total if short else min(total, (3 + rng.random()) * BB)
            if pct <= vpip:
                return ("call", 0.0) if to_call > 0 else ("check", 0.0)
            return ("check", 0.0) if to_call <= 0 else ("fold", 0.0)
        big = h.current >= 25 * BB
        if pct <= three * (0.5 if big else 1.0):
            return "raise", total if total <= 20 * BB else min(total, h.current * 3)
        call_pct = (vpip - pfr) * 0.6 + pfr * 0.5
        if big:
            call_pct *= 0.4
        if pct <= call_pct or (style == "station" and pct <= vpip * 0.7 and not big):
            return "call", 0.0
        return ("check", 0.0) if to_call <= 0 else ("fold", 0.0)
    st = strength(s.cards, h.board)
    pot = h.pot
    if to_call <= 0:
        if st >= bet_s or (rng.random() < bluff and st < 0.35):
            if extra.get("trap") and st >= 0.9 and rng.random() < extra["trap"]:
                return "check", 0.0
            if rng.random() < aggr or st >= 0.9:
                size = extra.get("size")
                frac = 0.5 + 0.4 * rng.random() if size is None else size[0] + (size[1] - size[0]) * rng.random()
                return "raise", min(total, h.current + max(BB, frac * pot))
        return "check", 0.0
    price = to_call / (pot + to_call)
    if st >= max(bet_s + 0.15, 0.85) and rng.random() < extra.get("raise", aggr):
        return "raise", min(total, h.current * 3 + pot * 0.2)
    need = price * (0.6 if style == "station" else 1.0)
    if st >= max(call_s * (0.6 + price), need + 0.1) or (style == "station" and st >= 0.3):
        return "call", 0.0
    return "fold", 0.0


# ------------------------------------------------------------------ the game
def act(h: Hand, i: int, kind: str, to: float) -> None:
    s = h.seats[i]
    to_call = h.current - s.bet
    if kind == "fold" and to_call <= 0:
        kind = "check"
    if kind == "check" and to_call > 0:
        kind = "fold"
    if kind == "raise":
        total = s.stack + s.bet
        to = max(to, h.current + h.min_raise)
        to = min(to, total)
        if to <= h.current:  # can't raise: just call
            kind = "call"
        else:
            if to - h.current >= h.min_raise:
                h.min_raise = to - h.current
            add = to - s.bet
            s.stack -= add
            s.put_in += add
            s.bet = to
            h.current = to
            s.all_in = s.stack <= 1e-9
            s.last = Action("all-in" if s.all_in else ("raise" if h.board or h.current > BB else "raise"), to)
            for j, o in enumerate(h.seats):
                if j != i:
                    o.acted = False
            s.acted = True
            h.log.append((i, "raise", to, len(h.board)))
            return
    if kind == "call":
        add = min(to_call, s.stack)
        s.stack -= add
        s.put_in += add
        s.bet += add
        s.all_in = s.stack <= 1e-9
        s.last = Action("call", s.bet)
        h.log.append((i, "call", add, len(h.board)))
    elif kind == "check":
        s.last = Action("check")
        h.log.append((i, "check", 0, len(h.board)))
    else:
        s.folded = True
        s.last = Action("fold")
        h.log.append((i, "fold", 0, len(h.board)))
    s.acted = True


def betting_round(h: Hand, first: int, rng: random.Random, budget_ms: int, stats) -> None:
    n = len(h.seats)
    order = [(first + k) % n for k in range(n)]
    while True:
        moved = False
        for i in order:
            s = h.seats[i]
            if s.folded or s.all_in:
                continue
            if len(h.active()) == 1:
                return
            if s.acted and s.bet >= h.current:
                continue
            if all(o.folded or o.all_in for j, o in enumerate(h.seats) if j != i) and s.bet >= h.current:
                continue
            if s.style == "app":
                kind, to = app_decide(h, i, budget_ms, stats)
            else:
                snap = {"i": i, "current": h.current, "bet": s.bet, "stack": s.stack, "pot": h.pot,
                        "board": tuple(h.board), "min_raise": h.min_raise, "number": h.number,
                        "put_in": tuple(o.put_in for o in h.seats), "live": tuple(h.active()),
                        "behind": tuple(o.stack for o in h.seats)}
                kind, to = bot_decide(h, i, h.bot_rng(i, rng))
                snap["spec"] = h.last_spec
            facing = h.current > s.bet
            act(h, i, kind, to)
            if s.style == "app":
                h.events.append(("app", len(h.spots) - 1))
            else:
                snap["action"] = (h.log[-1][1], h.log[-1][2])
                h.bot_decisions.append(snap)
                h.events.append(("bot", len(h.bot_decisions) - 1))
                stats.setdefault("bot_actions", defaultdict(int))[
                    (s.style, len(h.board), facing, h.log[-1][1])] += 1
            if h.profiles is not None:
                observe(h, next(j for j, o in enumerate(h.seats) if o.style == "app"))
            moved = True
        if not moved:
            return


def split_pot(put_in, live, ranks) -> Dict[int, float]:
    """Chips won by each seat (side pots included), from what each seat put in, the seats
    still in, and their hand ranks (lower is better; not needed when one seat is left)."""
    won: Dict[int, float] = defaultdict(float)
    if len(live) == 1:
        won[live[0]] += sum(put_in)
        return won
    levels = sorted({put_in[i] for i in live})
    prev = 0.0
    for lv in levels:
        layer = sum(min(p, lv) - min(p, prev) for p in put_in)
        eligible = [i for i in live if put_in[i] >= lv]
        best = min(ranks[i] for i in eligible)
        winners = [i for i in eligible if ranks[i] == best]
        for i in winners:
            won[i] += layer / len(winners)
        prev = lv
    return won


def showdown(h: Hand) -> Dict[int, float]:
    """Chips won by each seat (side pots included)."""
    live = h.active()
    ranks = {i: hands.evaluate(h.seats[i].cards, h.board) for i in live} if len(live) > 1 else {}
    return split_pot([s.put_in for s in h.seats], live, ranks)


def stack_sizes(styles: List[str], seed: int, depth_bb: float, stacks: str = "even") -> List[float]:
    """Each seat's starting stack in big blinds (from the hand's seed, so it repeats)."""
    if stacks == "even":
        return [depth_bb] * len(styles)
    app_opts, bot_opts = STACKS[stacks]
    rng = random.Random(seed * 31 + 7)
    return [float(rng.choice(app_opts if st == "app" else bot_opts)) for st in styles]


def play_hand(styles: List[str], button: int, seed: int, budget_ms: int, depth_bb: float, stats,
              stacks: str = "even", names: Optional[List[str]] = None, profiles=None,
              number: int = 0, rotate: int = 0, keyed: bool = False, split_at: Optional[int] = None,
              resample: Optional[int] = None, hole_override: Optional[Dict[int, Tuple[str, str]]] = None,
              board_override: Optional[Dict[int, str]] = None) -> Dict[int, float]:
    """Play one hand; the app is styles.index("app"). The deck deals hole cards to one card
    slot per player (six, or two heads-up) and the button sits at slot `button`. With `rotate`
    r the players move r slots on (the app takes slot r's cards and position), so the six
    rotations of one deck give the app, and every bot, each slot's cards from that slot's
    position once (duplicate deals). Heads-up the two rotations swap the seats: each deal is
    played twice, the app holding each player's cards once. With `keyed` each bot decision
    gets its own seed (Hand.bot_rng)."""
    n = len(styles)
    assert 2 <= n <= 6, n
    rng = random.Random(seed)
    deck = list(hands.DECK)
    rng.shuffle(deck)
    # tests only (tools/hidden.py): deal these hole cards to a seat, or these board cards
    # (board position 0-4), by swapping cards within the deck so it stays a whole deck
    wanted = {}
    for k, cards in (hole_override or {}).items():
        slot = (k + rotate) % n
        wanted.update({2 * slot: cards[0], 2 * slot + 1: cards[1]})
    wanted.update({2 * n + pos: c for pos, c in (board_override or {}).items()})
    for pos, c in wanted.items():
        j = deck.index(c)
        deck[pos], deck[j] = deck[j], deck[pos]
    seats = [Seat(st, stack=d * BB) for st, d in zip(styles, stack_sizes(styles, seed, depth_bb, stacks))]
    for k, s in enumerate(seats):
        slot = (k + rotate) % n
        s.cards = (deck[2 * slot], deck[2 * slot + 1])
        if names:
            s.name = names[k]
    button = (button - rotate) % n
    board_cards = deck[2 * n:2 * n + 5]
    h = Hand(seats, button, profiles=profiles, number=number, rng_key=seed * 6 + rotate if keyed else None,
             split_at=split_at, resample=resample)
    me = styles.index("app")
    sb_i, bb_i = blind_seats(button, n)
    for i, amt in ((sb_i, SB), (bb_i, BB)):
        seats[i].stack -= amt
        seats[i].bet = amt
        seats[i].put_in = amt
    h.current = BB
    if profiles is not None:
        observe(h, styles.index("app"))  # the blinds are in
    bot_rng = random.Random(seed * 7 + 1)
    betting_round(h, first_to_act(button, n, preflop=True), bot_rng, budget_ms, stats)
    for cards_on_board in (3, 4, 5):
        if len(h.active()) == 1:
            break
        h.pot_before = h.pot
        for s in seats:
            s.bet = 0.0
            s.acted = False
            if not s.folded:
                s.last = None
        h.current = 0.0
        h.min_raise = BB
        if not seats[me].folded:
            h.chance.append({"board": tuple(h.board), "deal": tuple(board_cards[len(h.board):cards_on_board]),
                             "live": tuple(h.active()), "put_in": tuple(s.put_in for s in seats),
                             "behind": tuple(s.stack for s in seats)})
            h.events.append(("card", len(h.chance) - 1))
        if resample is not None and split_at is not None and len(h.spots) > split_at:
            dead = {c for st_ in seats for c in st_.cards} | set(h.board)
            fresh = [c for c in hands.DECK if c not in dead]
            random.Random(f"{seed}/{rotate}/{resample}/{len(h.board)}").shuffle(fresh)
            board_cards = list(h.board) + fresh[:5 - len(h.board)]
            if h.chance and h.chance[-1]["board"] == tuple(h.board):
                h.chance[-1]["deal"] = tuple(board_cards[len(h.board):cards_on_board])
        h.board = board_cards[:cards_on_board]
        if sum(1 for i in h.active() if not seats[i].all_in) >= 2:
            betting_round(h, first_to_act(button, n, preflop=False), bot_rng, budget_ms, stats)
    if len(h.active()) > 1:
        h.board = board_cards[:5]
    won = showdown(h)
    net = {i: won.get(i, 0.0) - seats[i].put_in for i in range(n)}
    stats["diverged"] = h.diverged
    # everything tools/luck.py and tools/weakness.py need about the hand just played
    stats["last"] = {"cards": tuple(s.cards for s in seats), "board": tuple(board_cards), "me": me,
                     "chance": h.chance, "spots": h.spots, "net": net[me] / BB, "key": seed * 6 + rotate,
                     "pos": h.position(me), "put_in": seats[me].put_in / BB, "pot_type": pot_type(h),
                     "diverge_at": h.diverge_at, "bot_decisions": h.bot_decisions, "events": h.events,
                     "final_put_in": tuple(s.put_in for s in seats), "final_live": tuple(h.active()),
                     "final_board": tuple(h.board), "seats": tuple((s.style, s.name) for s in seats),
                     "number": number}
    stats["hands"].append(net[me] / BB)
    pos = h.position(me)
    stats["by_pos"][pos].append(net[me] / BB)
    first_app = next((a for a in h.log if a[0] == me), None)
    if first_app is not None and first_app[3] == 0:
        stats["preflop_first"][(pos, first_app[1])] += 1
    last_street = max((a[3] for a in h.log if a[0] == me), default=0)
    stats["by_street"][last_street].append(net[me] / BB)
    went_all_in = seats[me].all_in
    if went_all_in:
        stats["all_in"].append(net[me] / BB)
    return net


def seating(table: str, seed: int, k: int, players: int = 6) -> Tuple[List[str], List[str]]:
    """Hand k's seats: the app in seat 0 and the bots shuffled round the others (the same
    shuffle for styles and names, so a bot keeps its name wherever it sits). Heads-up
    (players 2) the app plays the first bot of the shuffle: one of the table's five, a
    different one from deal to deal."""
    others = TABLES[table]
    order = list(range(len(others)))
    random.Random(seed + k).shuffle(order)
    order = order[:players - 1]
    styles = ["app"] + [others[j] for j in order]
    names = ["You"] + [f"{others[j]}{j}" for j in order]
    return styles, names


def new_profiles():
    from app.poker.profiles import Profiles

    return Profiles()


def run(n: int, table: str, seed: int, budget_ms: int = 25, depth_bb: float = 100.0, quiet: bool = False,
        stacks: str = "even", profiles: bool = False, players: int = 6) -> dict:
    assert players in PLAYERS, players
    stats = {"hands": [], "by_pos": defaultdict(list), "by_street": defaultdict(list), "all_in": [],
             "preflop_first": defaultdict(int), "advice": defaultdict(int), "problems": defaultdict(int),
             "examples": []}
    prof = new_profiles() if profiles else None
    stats["profiles"] = prof
    t0 = time.time()
    for k in range(n):
        # the app sits in seat 0; the button goes round, so it plays every position
        styles, names = seating(table, seed, k, players)
        play_hand(styles, button=k % players, seed=seed * 100003 + k, budget_ms=budget_ms, depth_bb=depth_bb,
                  stats=stats, stacks=stacks, names=names, profiles=prof, number=k + 1)
        if not quiet and (k + 1) % 500 == 0:
            r = stats["hands"]
            print(f"  {k + 1} hands, {100 * sum(r) / len(r):+.1f} bb/100, {time.time() - t0:.0f}s", flush=True)
    return stats


def profile_report(prof, table: str) -> str:
    """Each bot's real style against the style the app learned for it."""
    from app.state.model import Player as P

    out = []
    for j, style in enumerate(TABLES[table]):
        key = prof.key_for(P(seat=1, name=f"{style}{j}"))
        st = prof.stats_for(key)
        out.append(f"{style}{j} -> {prof.style_for(key)} ({st.hands} hands, vpip {100 * st.vpip_rate:.0f}%, "
                   f"pfr {100 * st.pfr_rate:.0f}%)")
    return "; ".join(out)


def report(stats: dict) -> str:
    r = stats["hands"]
    n = len(r)
    mean = sum(r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / max(1, n - 1))
    lines = [f"{n} hands: {100 * mean:+.1f} bb/100 (± {100 * sd / math.sqrt(n):.1f})"]
    lines.append("by position: " + ", ".join(f"{p} {100 * sum(v) / len(v):+.0f}" for p, v in sorted(stats["by_pos"].items())))
    lines.append("by last street the app acted on: " + ", ".join(
        f"{['pre', '', '', 'flop', 'turn', 'river'][k]} {sum(v):+.0f}bb/{len(v)}" for k, v in sorted(stats["by_street"].items())))
    if stats["all_in"]:
        lines.append(f"hands where the app was all in: {len(stats['all_in'])}, net {sum(stats['all_in']):+.0f} bb")
    first = stats["preflop_first"]
    for pos in ["UTG", "HJ", "CO", "BTN", "SB", "BTN/SB", "BB"]:
        tot = sum(v for (p, _), v in first.items() if p == pos)
        if tot:
            lines.append(f"  {pos:3s} first action: " + ", ".join(
                f"{k} {100 * v / tot:.0f}%" for (p, k), v in sorted(first.items()) if p == pos))
    decisions = sum(stats["advice"].values())
    if stats["problems"]:
        lines.append(f"PROBLEMS in {decisions} instructions: " + ", ".join(f"{k} x{v}" for k, v in stats["problems"].items()))
        for ex in stats["examples"][:12]:
            lines.append(f"   {ex}")
    else:
        lines.append(f"no problems in {decisions} instructions")
    return "\n".join(lines)


def bot_action_report(stats: dict) -> str:
    """Each bot style's actions by street: checked to (bet share) and facing a bet (fold,
    call, raise shares), comparable with the HandHQ shares in DATASET.md."""
    counts = stats.get("bot_actions", {})
    lines = []
    for style in sorted({k[0] for k in counts}):
        parts = []
        for street in (0, 3, 4, 5):
            free = {a: n for (st, sr, f, a), n in counts.items() if st == style and sr == street and not f}
            facing = {a: n for (st, sr, f, a), n in counts.items() if st == style and sr == street and f}
            nf, nb = sum(free.values()), sum(facing.values())
            name = STREETS[street]
            txt = f"{name}: "
            if nf:
                txt += f"bets {100 * free.get('raise', 0) / nf:.0f}% of {nf} when free; "
            if nb:
                txt += (f"facing {nb}: fold {100 * facing.get('fold', 0) / nb:.0f}% call "
                        f"{100 * facing.get('call', 0) / nb:.0f}% raise {100 * facing.get('raise', 0) / nb:.0f}%")
            parts.append(txt)
        lines.append(f"{style}: " + " | ".join(parts))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hands", nargs="?", type=int, default=2000)
    ap.add_argument("--table", default="mixed", choices=sorted(TABLES),
                    help="held-out tables (never used for tuning): " + ", ".join(HELD_OUT_TABLES))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--budget", type=int, default=25, help="ms of equity maths per decision")
    ap.add_argument("--deep", action="store_true", help="500 big blinds deep, like 247 Free Poker")
    ap.add_argument("--stacks", default="even", choices=["even"] + sorted(STACKS),
                    help="even: everyone the same; uneven: bots 15-250bb; tourney: everyone shallow")
    ap.add_argument("--profiles", action="store_true",
                    help="the app learns each bot's style from the hands, as in watch mode")
    ap.add_argument("--bot-actions", action="store_true", help="each bot style's action shares by street")
    ap.add_argument("--players", type=int, default=6, choices=PLAYERS,
                    help="6: six-max; 2: heads-up against one of the table's bots at a time")
    a = ap.parse_args()
    stats = run(a.hands, a.table, a.seed, a.budget, 500.0 if a.deep else 100.0, stacks=a.stacks,
                profiles=a.profiles, players=a.players)
    print(report(stats))
    if a.bot_actions:
        print(bot_action_report(stats))
    if stats.get("profiles") is not None:
        print("styles learned: " + profile_report(stats["profiles"], a.table))


if __name__ == "__main__":
    main()
