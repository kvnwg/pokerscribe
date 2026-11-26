"""Play the app's instructions against simulated opponents and measure how much it wins.

    python tools/simulate.py [hands] [--table mixed|stations|nits|tags|lags|maniacs] [--seed N] [--deep]
                             [--stacks even|uneven|tourney] [--profiles]

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

SB, BB = 1.0, 2.0
POSITIONS = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]  # by seat offset from the button
PREFLOP_FIRST = 3  # UTG acts first preflop
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

TABLES = {
    "mixed": ["station", "nit", "tag", "lag", "maniac"],
    "stations": ["station"] * 5, "nits": ["nit"] * 5, "tags": ["tag"] * 5,
    "lags": ["lag"] * 5, "maniacs": ["maniac"] * 5,
    "fish247": ["fish247"] * 5,
}


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

    def position(self, i: int) -> str:
        return POSITIONS[(i - self.button) % 6]

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
        p = Player(seat=(i - me) % 6, is_hero=i == me, position=Field.manual(h.position(i)),
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
            i = (p.seat + me) % 6
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


def decision(h: Hand, me: int, overrides: Optional[dict], st: Optional[GameState] = None):
    import copy

    st = observe(h, me) if st is None else copy.deepcopy(st)
    with variant(overrides):
        return advise(st, computed=sim_compute(st), numbers_checked=True)


def app_decide(h: Hand, me: int, budget_ms: int, stats) -> Tuple[str, float]:
    st = observe(h, me)
    adv = decision(h, me, stats.get("variant"), st)
    shadow = stats.get("shadow")
    if shadow is not None and not h.diverged:
        other = decision(h, me, shadow, st)
        if (other.action, other.amount) != (adv.action, adv.amount):
            h.diverged = True  # the two variants part ways in this hand: replay it with the other one
    stats["advice"][(len(h.board), adv.action)] += 1
    check_advice(h, me, adv, stats)
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


def bot_decide(h: Hand, i: int, rng: random.Random) -> Tuple[str, float]:
    s = h.seats[i]
    vpip, pfr, three, bet_s, call_s, bluff, aggr = STYLES[s.style]
    to_call = h.current - s.bet
    total = s.stack + s.bet
    if not h.board:
        pct = preflop_percentile(hands.preflop_class(s.cards))
        raised = h.current > BB
        short = total <= SHORT_BOT * BB  # short stacks move all in rather than raise small
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
        if pct <= call_pct or (s.style == "station" and pct <= vpip * 0.7 and not big):
            return "call", 0.0
        return ("check", 0.0) if to_call <= 0 else ("fold", 0.0)
    st = strength(s.cards, h.board)
    pot = h.pot
    if to_call <= 0:
        if st >= bet_s or (rng.random() < bluff and st < 0.35):
            if rng.random() < aggr or st >= 0.9:
                return "raise", min(total, h.current + max(BB, (0.5 + 0.4 * rng.random()) * pot))
        return "check", 0.0
    price = to_call / (pot + to_call)
    if st >= max(bet_s + 0.15, 0.85) and rng.random() < aggr:
        return "raise", min(total, h.current * 3 + pot * 0.2)
    need = price * (0.6 if s.style == "station" else 1.0)
    if st >= max(call_s * (0.6 + price), need + 0.1) or (s.style == "station" and st >= 0.3):
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
    order = [(first + k) % 6 for k in range(6)]
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
            kind, to = app_decide(h, i, budget_ms, stats) if s.style == "app" else bot_decide(h, i, rng)
            act(h, i, kind, to)
            if h.profiles is not None:
                observe(h, next(j for j, o in enumerate(h.seats) if o.style == "app"))
            moved = True
        if not moved:
            return


def showdown(h: Hand) -> Dict[int, float]:
    """Chips won by each seat (side pots included)."""
    won: Dict[int, float] = defaultdict(float)
    live = h.active()
    if len(live) == 1:
        won[live[0]] += sum(s.put_in for s in h.seats)
        return won
    ranks = {i: hands.evaluate(h.seats[i].cards, h.board) for i in live}
    levels = sorted({h.seats[i].put_in for i in live})
    prev = 0.0
    for lv in levels:
        layer = sum(min(s.put_in, lv) - min(s.put_in, prev) for s in h.seats)
        eligible = [i for i in live if h.seats[i].put_in >= lv]
        best = min(ranks[i] for i in eligible)
        winners = [i for i in eligible if ranks[i] == best]
        for i in winners:
            won[i] += layer / len(winners)
        prev = lv
    return won


def stack_sizes(styles: List[str], seed: int, depth_bb: float, stacks: str = "even") -> List[float]:
    """Each seat's starting stack in big blinds (from the hand's seed, so it repeats)."""
    if stacks == "even":
        return [depth_bb] * len(styles)
    app_opts, bot_opts = STACKS[stacks]
    rng = random.Random(seed * 31 + 7)
    return [float(rng.choice(app_opts if st == "app" else bot_opts)) for st in styles]


def play_hand(styles: List[str], button: int, seed: int, budget_ms: int, depth_bb: float, stats,
              stacks: str = "even", names: Optional[List[str]] = None, profiles=None,
              number: int = 0) -> Dict[int, float]:
    rng = random.Random(seed)
    deck = list(hands.DECK)
    rng.shuffle(deck)
    seats = [Seat(st, stack=d * BB) for st, d in zip(styles, stack_sizes(styles, seed, depth_bb, stacks))]
    for k, s in enumerate(seats):
        s.cards = (deck[2 * k], deck[2 * k + 1])
        if names:
            s.name = names[k]
    board_cards = deck[12:17]
    h = Hand(seats, button, profiles=profiles, number=number)
    sb_i, bb_i = (button + 1) % 6, (button + 2) % 6
    for i, amt in ((sb_i, SB), (bb_i, BB)):
        seats[i].stack -= amt
        seats[i].bet = amt
        seats[i].put_in = amt
    h.current = BB
    if profiles is not None:
        observe(h, styles.index("app"))  # the blinds are in
    bot_rng = random.Random(seed * 7 + 1)
    betting_round(h, (button + 3) % 6, bot_rng, budget_ms, stats)
    for n in (3, 4, 5):
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
        h.board = board_cards[:n]
        if sum(1 for i in h.active() if not seats[i].all_in) >= 2:
            betting_round(h, (button + 1) % 6, bot_rng, budget_ms, stats)
    if len(h.active()) > 1:
        h.board = board_cards[:5]
    won = showdown(h)
    net = {i: won.get(i, 0.0) - seats[i].put_in for i in range(6)}
    stats["diverged"] = h.diverged
    me = styles.index("app")
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


def seating(table: str, seed: int, k: int) -> Tuple[List[str], List[str]]:
    """Hand k's seats: the app in seat 0 and the bots shuffled round the others (the same
    shuffle for styles and names, so a bot keeps its name wherever it sits)."""
    others = TABLES[table]
    order = list(range(len(others)))
    random.Random(seed + k).shuffle(order)
    styles = ["app"] + [others[j] for j in order]
    names = ["You"] + [f"{others[j]}{j}" for j in order]
    return styles, names


def new_profiles():
    from app.poker.profiles import Profiles

    return Profiles()


def run(n: int, table: str, seed: int, budget_ms: int = 25, depth_bb: float = 100.0, quiet: bool = False,
        stacks: str = "even", profiles: bool = False) -> dict:
    stats = {"hands": [], "by_pos": defaultdict(list), "by_street": defaultdict(list), "all_in": [],
             "preflop_first": defaultdict(int), "advice": defaultdict(int), "problems": defaultdict(int),
             "examples": []}
    prof = new_profiles() if profiles else None
    stats["profiles"] = prof
    t0 = time.time()
    for k in range(n):
        # the app sits in seat 0; the button goes round, so it plays every position
        styles, names = seating(table, seed, k)
        play_hand(styles, button=k % 6, seed=seed * 100003 + k, budget_ms=budget_ms, depth_bb=depth_bb,
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
    for pos in ["UTG", "HJ", "CO", "BTN", "SB", "BB"]:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hands", nargs="?", type=int, default=2000)
    ap.add_argument("--table", default="mixed", choices=sorted(TABLES))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--budget", type=int, default=25, help="ms of equity maths per decision")
    ap.add_argument("--deep", action="store_true", help="500 big blinds deep, like 247 Free Poker")
    ap.add_argument("--stacks", default="even", choices=["even"] + sorted(STACKS),
                    help="even: everyone the same; uneven: bots 15-250bb; tourney: everyone shallow")
    ap.add_argument("--profiles", action="store_true",
                    help="the app learns each bot's style from the hands, as in watch mode")
    a = ap.parse_args()
    stats = run(a.hands, a.table, a.seed, a.budget, 500.0 if a.deep else 100.0, stacks=a.stacks,
                profiles=a.profiles)
    print(report(stats))
    if stats.get("profiles") is not None:
        print("styles learned: " + profile_report(stats["profiles"], a.table))


if __name__ == "__main__":
    main()
