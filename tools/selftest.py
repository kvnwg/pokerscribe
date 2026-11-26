"""Phase 0 self-test: PokerScribe plays on a demo table of our own and every read is
checked against the truth.

    python tools/selftest.py [--layouts wireframe,green,...] [--hands 30] [--seed 1] [--drop 0.1]
                             [--out DIR]

The table is drawn by app/tests/demo_table.py from the simulator's game (tools/simulate.py:
same rules, same bots). After every action a picture of the table is drawn and goes through
exactly what watch mode does with a capture: the reader, the hand tracker, the hand memory
and the advice. When PokerScribe asks to confirm a card, the self-test answers as you would
(so each deck is learned once, as in the app). On your turn the instruction it gives is what
the hero plays. Nothing here touches a real poker client.

Checked on every picture: seats found, stacks, bets, who is still in, the button, your
cards, the board, the pot, whose turn it is. On your turn: the amount to call, and the
instruction against the one PokerScribe gives when it is handed the true table (same maths,
so any difference comes from reading), plus the never-wrong rules from tools/simulate.py
(no fold when checking is free, no WAIT on your turn, raises above the current bet ...).
Off your turn: whether it shows a move instead of WAIT.

--drop skips that share of the pictures between your turns (missed captures). Examples of
every kind of mistake are saved to --out with the picture, so they can be replayed.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import tempfile
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402

from app.poker.advice import advise  # noqa: E402
from app.poker.calculator import pot_for_odds  # noqa: E402
from app.recognition.hand import HandMemory  # noqa: E402
from app.recognition.recognizer import TableRecognizer  # noqa: E402
from app.recognition.tracker import HandTracker  # noqa: E402
from app.state.model import Action, Field, GameState, Player  # noqa: E402
from app.tests.demo_table import Layout, SeatView, TableView, layouts, money, render  # noqa: E402
from app.vision.card_recognizer import CardRecognizer  # noqa: E402
from app.vision.ocr import FallbackOcr  # noqa: E402
from tools.simulate import (BB, POSITIONS, SB, TABLES, Hand, Seat, act, bot_decide, check_advice,  # noqa: E402
                            showdown, sim_compute, variant)

NAMES = ["You", "Marlow", "Quinn", "Jasper", "Rhea", "Toby"]
TOP_UP_BB = 40  # a player below this many big blinds tops up to 100 between hands


# ---------------------------------------------------------------- PokerScribe
class Scribe:
    """What the app does with each capture while watching."""

    def __init__(self, learned_dir: str):
        cards = CardRecognizer(learned_dir, 0.70, require_learned=True)
        self.rec = TableRecognizer(cards, FallbackOcr("auto"), 0.70)
        self.tracker = HandTracker()
        self.hand = HandMemory()

    def read(self, img):
        res = self.rec.recognize(img)
        info = self.tracker.update(res.state)
        self.hand.update(res.state, [r.box for r in res.board_readings], info.new_hand, res.layout.hand_id)
        with variant(None):
            computed = sim_compute(res.state) if _cards_known(res.state) and not res.state.validate() else {}
            res.state.computed = computed
            adv = advise(res.state, computed, numbers_checked=info.valid)
        return res, info, adv

    def confirm(self, res, truth_hero: List[str], truth_board: List[str]) -> int:
        """Answer "Are these cards right?" the way the user would: teach each unclear card."""
        n = 0
        st = res.state
        for kind, fields, readings, truth in (("hero", st.hero_cards, res.hero_readings, truth_hero),
                                              ("board", st.board, res.board_readings, truth_board)):
            for i, f in enumerate(fields):
                if f.known:
                    continue
                # both are in table order (left to right), as the user sees them
                code = truth[i] if i < len(truth) else None
                if code is None:
                    continue
                r = self._reading(kind, i, readings)
                if r is not None and r.glyphs is not None:
                    self.rec.cards.learn(r.glyphs, code)
                self.hand.confirm(kind, i, code)
                n += 1
        return n

    def _reading(self, kind, i, readings):
        """The card read at that place (board indexes can shift when a card was remembered)."""
        if kind == "hero":
            return readings[i] if i < len(readings) else None
        x = self.hand.board_x(i)
        if x is None:
            return None
        near = [r for r in readings if r is not None and abs(r.center[0] - x) < 0.5 * r.box[2]]
        return near[0] if near else None


def _cards_known(st: GameState) -> bool:
    return len(st.hero_cards) == 2 and all(c.known for c in st.hero_cards) and all(c.known for c in st.board)


# ------------------------------------------------------------------ the game
class Table:
    def __init__(self, seed: int, table: str = "mixed", depth_bb: float = 100.0):
        self.rng = random.Random(seed)
        styles = ["app"] + self.rng.sample(TABLES[table], 5)
        self.seats = [Seat(st, stack=depth_bb * BB, name=NAMES[i]) for i, st in enumerate(styles)]
        self.button = self.rng.randrange(6)
        self.hand_no = 0
        self.depth = depth_bb

    def top_up(self) -> None:
        for s in self.seats:
            if s.stack < TOP_UP_BB * BB:
                s.stack = self.depth * BB


def view_of(h: Hand, acting: Optional[int], hand_no: int, lay: Layout, phase: str = "play",
            shown: bool = False) -> TableView:
    seats = []
    for i, s in enumerate(h.seats):
        has = phase != "between" and not s.folded
        tag = None
        if s.last is not None and phase == "play":
            tag = {"fold": "Fold", "check": "Check", "call": "Call", "raise": "Raise", "bet": "Bet",
                   "all-in": "All in"}[s.last.kind]
            if s.last.kind == "raise" and not h.board and h.current <= BB:
                tag = "Raise"
        seats.append(SeatView(s.name, round(s.stack, 2), round(s.bet, 2), has_cards=has, all_in=s.all_in,
                              shown=tuple(s.cards) if shown and has and i != 0 else None, tag=tag))
    hero = list(h.seats[0].cards) if phase != "between" and not h.seats[0].folded else []
    buttons: List[str] = []
    if acting == 0:
        buttons = hero_buttons(h, lay)
    return TableView(seats, hero, list(h.board) if phase != "between" else [], h.pot_before, h.button,
                     acting, buttons, hand_no, timer_left=0.3 + 0.6 * ((hand_no * 7 + len(h.log)) % 10) / 10)


def hero_buttons(h: Hand, lay: Layout) -> List[str]:
    s = h.seats[0]
    to_call = h.current - s.bet
    cur = lay.currency
    long = lay.button_labels == "long"
    total = s.stack + s.bet
    if to_call > 0:
        if to_call >= s.stack:
            return ["Fold", f"All in {money(s.stack, cur)}" if long else f"Call {money(s.stack, cur)}"]
        out = ["Fold", f"Call {money(to_call, cur)}"]
        min_to = min(total, h.current + h.min_raise)
        out.append(f"Raise to {money(min_to, cur)}" if long else "Raise")
        return out
    out = ["Check"]
    if h.current > 0:
        out.append(f"Raise to {money(min(total, h.current + h.min_raise), cur)}" if long else "Raise")
    else:
        out.append(f"Bet {money(min(total, BB), cur)}" if long else "Bet")
    return out


# --------------------------------------------------------------- the truth
def truth_state(h: Hand, tags: bool = False) -> GameState:
    """The table as it really is, in the shape the advice reads it (what is on screen only:
    no opponents' cards, and last actions only on a layout that shows them)."""
    players = []
    for i, s in enumerate(h.seats):
        p = Player(seat=i, is_hero=i == 0, position=Field.manual(h.position(i)),
                   stack=Field.manual(round(s.stack, 2)), bet=Field.manual(round(s.bet, 2)),
                   in_hand=Field.manual(not s.folded), name=s.name)
        if tags and s.last is not None:
            p.last_action = Field.manual(Action(s.last.kind))  # a tag shows the word, not the amount
        players.append(p)
    st = GameState(hero_cards=[Field.manual(c) for c in h.seats[0].cards], board=[Field.manual(c) for c in h.board],
                   players=players)
    st.street = Field.manual({0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(h.board)])
    st.pot = Field.manual(h.pot_before)
    st.blinds = Field.manual((SB, BB))
    me = h.seats[0]
    to_call = max(0.0, h.current - me.bet)
    st.to_call = Field.manual(min(to_call, me.stack))
    acts = [Action("fold"), Action("call", min(to_call, me.stack))] if to_call > 0 else [Action("check")]
    if me.stack > to_call:
        acts.append(Action("raise" if h.current > 0 else "bet"))
    st.available_actions = Field.manual(acts)
    st.hero_to_act = Field.manual(True)
    return st


def reference_advice(h: Hand, tags: bool = False):
    st = truth_state(h, tags)
    with variant(None):
        computed = sim_compute(st)
        st.computed = computed
        return advise(st, computed, numbers_checked=True)


# ----------------------------------------------------------------- checking
class Report:
    def __init__(self, name: str, out: Optional[str]):
        self.name = name
        self.out = out
        self.c: Counter = Counter()
        self.examples: Dict[str, List[dict]] = defaultdict(list)
        self.saved = 0
        self.log = None
        if out:
            os.makedirs(out, exist_ok=True)
            self.log = open(os.path.join(out, "frames.jsonl"), "a")

    def bad(self, kind: str, img, detail: str, extra: Optional[dict] = None) -> None:
        self.c[kind] += 1
        ex = self.examples[kind]
        if len(ex) >= 4:
            return
        item = {"detail": detail}
        if extra:
            item.update(extra)
        if self.out and img is not None:
            self.saved += 1
            path = os.path.join(self.out, f"{kind.replace(' ', '_')}_{len(ex)}.png")
            cv2.imwrite(path, img)
            item["image"] = path
        ex.append(item)


def match_seats(st: GameState, plates) -> Dict[int, int]:
    """Index in state.players -> screen seat, by where the seat was read."""
    out = {}
    for k, p in enumerate(st.players):
        if p.is_hero:
            out[k] = 0
            continue
        if not p.anchor:
            continue
        best = min(range(len(plates)), key=lambda i: (plates[i][0] - p.anchor[0]) ** 2 + (plates[i][1] - p.anchor[1]) ** 2)
        x, y, w, hgt = plates[best]
        if abs(plates[best][0] - p.anchor[0]) < w and abs(plates[best][1] - p.anchor[1]) < 1.5 * hgt:
            out[k] = best
    return out


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.51, 0.01 * abs(b))


def check_frame(rep: Report, img, meta, h: Hand, view: TableView, res, info, adv, hero_turn: bool) -> None:
    st: GameState = res.state
    rep.c["frames"] += 1
    plates = meta["plates"]
    seat_of = match_seats(st, plates)
    found = set(seat_of.values())
    missing = [i for i in range(6) if i not in found]
    if missing:
        rep.bad("seat not found", img, f"seats {missing} ({', '.join(h.seats[i].name for i in missing)})")
    if len(st.players) > 6 or len(seat_of) < len([p for p in st.players if p.is_hero or p.anchor]):
        rep.bad("extra seat", img, f"{len(st.players)} players read: {[p.name for p in st.players]}")
    for k, p in enumerate(st.players):
        i = seat_of.get(k)
        if i is None:
            continue
        s = h.seats[i]
        if p.stack.known and not close(float(p.stack.value), s.stack):
            rep.bad("stack wrong", img, f"{s.name}: read {p.stack.value} ({p.stack.source}), true {s.stack:g}")
        elif not p.stack.known:
            rep.c["stack unknown"] += 1
        if view.phase_play and p.bet.known and not close(float(p.bet.value), s.bet):
            rep.bad("bet wrong", img, f"{s.name}: read {p.bet.value} ({p.bet.source}), true {s.bet:g}")
        if view.phase_play and i != 0 and p.in_hand.known and bool(p.in_hand.value) == s.folded:
            rep.bad("in hand wrong", img, f"{s.name}: read in hand={p.in_hand.value}, folded={s.folded}")
        if view.phase_play and p.position.known and p.position.value != h.position(i):
            rep.bad("position wrong", img, f"{s.name}: read {p.position.value}, true {h.position(i)}")
    if view.phase_play and not h.seats[0].folded:
        for kind, fields, truth in (("hero card", st.hero_cards, view.hero_cards), ("board card", st.board, view.board)):
            got = [f.value for f in fields if f.known]
            wrong = [g for g in got if g not in truth]
            if wrong:
                rep.bad(f"{kind} wrong", img, f"read {[f.value for f in fields]}, true {truth}")
        if len(st.board) != len(view.board):
            rep.bad("board count wrong", img, f"read {len(st.board)} cards, true {len(view.board)}")
        pot = pot_for_odds(st)
        if pot is not None and not close(pot, h.pot):
            rep.bad("pot wrong", img, f"read {pot:g} (pot {st.pot.value}, includes bets {st.pot_includes_bets}), "
                    f"true {h.pot:g}")
    # whose turn: the seat with the timer bar or glow
    lay = res.layout
    if view.phase_play and view.acting is not None:
        rep.c["turns shown"] += 1
        if lay.acting_seat is None:
            rep.c["acting seat not read"] += 1
        else:
            cx, cy = lay.seats[lay.acting_seat].center
            seat = min(range(len(plates)), key=lambda i: (plates[i][0] - cx) ** 2 + (plates[i][1] - cy) ** 2)
            if seat != view.acting:
                rep.bad("acting seat wrong", img, f"read {h.seats[seat].name}, true {h.seats[view.acting].name}")
    elif lay.acting_seat is not None:
        rep.bad("acting seat when nobody acts", img, f"read seat {lay.acting_seat}")
    if hero_turn:
        rep.c["your turns"] += 1
        if not (st.hero_to_act.known and st.hero_to_act.value):
            rep.bad("your turn missed", img, f"hero_to_act={st.hero_to_act.value}")
        true_call = min(max(0.0, h.current - h.seats[0].bet), h.seats[0].stack)
        if st.to_call.known and not close(float(st.to_call.value), true_call):
            rep.bad("to call wrong", img, f"read {st.to_call.value} ({st.to_call.source}), true {true_call:g}")
        elif not st.to_call.known:
            rep.c["to call unknown"] += 1
    elif view.phase_play and view.acting is not None and h.seats[0].cards and not h.seats[0].folded:
        rep.c["their turns"] += 1
        if st.hero_to_act.known and st.hero_to_act.value:
            rep.bad("their turn read as yours", img, f"acting {h.seats[view.acting].name}")
        if adv.action not in ("wait", "unknown"):
            rep.c["move shown on their turn"] += 1
            if len(rep.examples["move shown on their turn"]) < 2:
                rep.bad("move shown on their turn (example)", img, f"{adv.headline}, acting {h.seats[view.acting].name}")
                rep.c["move shown on their turn (example)"] -= 1
    if rep.log:
        rep.log.write(json.dumps({"layout": rep.name, "hand": view.hand_no, "board": len(view.board),
                                  "acting": view.acting, "advice": adv.headline, "track": info.valid,
                                  "state": st.to_json()}, default=str) + "\n")


def judge_decision(rep: Report, img, h: Hand, adv, ref) -> None:
    stats = {"problems": Counter(), "examples": []}
    check_advice(h, 0, adv, stats)
    for p, n in stats["problems"].items():
        rep.bad(f"never-wrong rule: {p}", img, f"{adv.headline} ({adv.reason}); truth would say {ref.headline}")
    rep.c["decisions"] += 1
    if adv.action == ref.action and (adv.amount is None or ref.amount is None or close(adv.amount, ref.amount)):
        rep.c["same instruction"] += 1
        return
    kind = "different amount" if adv.action == ref.action else "different instruction"
    rep.bad(kind, img, f"read: {adv.headline} ({adv.reason}) | truth: {ref.headline} ({ref.reason})")


# ------------------------------------------------------------------- play
def hero_move(h: Hand, adv) -> Tuple[str, float]:
    """What the hero does when following the instruction (as tools/simulate.py)."""
    s = h.seats[0]
    to_call = h.current - s.bet
    total = s.stack + s.bet
    if adv.action in ("bet", "raise"):
        to = adv.amount
        if to is None:
            to = h.current * 3 if h.current > 0 else max(BB, 2 / 3 * h.pot)
        return "raise", min(total, to)
    if adv.action == "all-in":
        return ("call", 0.0) if adv.headline.startswith("CALL") else ("raise", total)
    if adv.action == "call":
        return ("call", 0.0) if to_call > 0 else ("check", 0.0)
    return ("check", 0.0) if to_call <= 0 else ("fold", 0.0)


class Run:
    def __init__(self, lay: Layout, seed: int, out: Optional[str], drop: float):
        self.lay = lay
        self.table = Table(seed)
        self.rep = Report(lay.name, out)
        self.learned = tempfile.mkdtemp(prefix="selftest-learned-")
        self.scribe = Scribe(self.learned)
        self.drop = drop
        self.rng = random.Random(seed * 13 + 5)

    def frame(self, h: Hand, acting: Optional[int], phase: str = "play", shown: bool = False, must: bool = False):
        view = view_of(h, acting, self.table.hand_no, self.lay, phase, shown)
        view.phase_play = phase == "play"
        if not must and acting != 0 and self.drop and self.rng.random() < self.drop:
            self.rep.c["pictures skipped"] += 1
            return None
        img, meta = render(view, self.lay)
        res, info, adv = self.scribe.read(img)
        hero_turn = acting == 0
        if hero_turn and adv.action == "unknown" and adv.headline.startswith("CONFIRM"):
            n = self.scribe.confirm(res, view.hero_cards, view.board)
            self.rep.c["cards confirmed"] += n
            res, info, adv = self.scribe.read(img)  # the app reads again after you confirm
        elif not hero_turn and any(not f.known and f.guess for f in res.state.hero_cards + res.state.board) \
                and phase == "play" and not h.seats[0].folded:
            # off your turn you'd confirm too (the yellow message is up): do it now
            self.rep.c["cards confirmed"] += self.scribe.confirm(res, view.hero_cards, view.board)
        check_frame(self.rep, img, meta, h, view, res, info, adv, hero_turn)
        return img, adv

    def betting_round(self, h: Hand, first: int) -> None:
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
                got = self.frame(h, i)
                if i == 0:
                    img, adv = got
                    ref = reference_advice(h, self.lay.action_tags)
                    if adv.action in ("wait", "unknown"):
                        self.rep.bad("no instruction on your turn", img, f"{adv.headline}: {adv.reason}")
                        adv = ref
                    else:
                        judge_decision(self.rep, img, h, adv, ref)
                    kind, to = hero_move(h, adv)
                else:
                    kind, to = bot_decide(h, i, self.rng)
                    to = float(round(to))  # play chips: whole amounts
                act(h, i, kind, to)
                moved = True
            if not moved:
                return

    def play_hand(self) -> None:
        t = self.table
        t.top_up()
        t.button = (t.button + 1) % 6
        t.hand_no += 1
        rng = random.Random(self.rng.random())
        deck = __import__("app.poker.hands", fromlist=["DECK"]).DECK[:]
        rng.shuffle(deck)
        for s in t.seats:
            s.bet = s.put_in = 0.0
            s.folded = s.all_in = s.acted = False
            s.last = None
        for k, s in enumerate(t.seats):
            s.cards = (deck[2 * k], deck[2 * k + 1])
        board = deck[12:17]
        h = Hand(t.seats, t.button)
        self.frame(h, None, phase="between")
        sb_i, bb_i = (t.button + 1) % 6, (t.button + 2) % 6
        for i, amt in ((sb_i, SB), (bb_i, BB)):
            t.seats[i].stack -= amt
            t.seats[i].bet = t.seats[i].put_in = amt
        h.current = BB
        self.betting_round(h, (t.button + 3) % 6)
        for n in (3, 4, 5):
            if len(h.active()) == 1:
                break
            h.pot_before = h.pot
            for s in t.seats:
                s.bet = 0.0
                s.acted = False
                if not s.folded:
                    s.last = None
            h.current = 0.0
            h.min_raise = BB
            h.board = board[:n]
            if sum(1 for i in h.active() if not t.seats[i].all_in) >= 2:
                first = next(((t.button + k) % 6 for k in range(1, 7)
                              if not t.seats[(t.button + k) % 6].folded and not t.seats[(t.button + k) % 6].all_in))
                self.betting_round(h, first)
            else:
                self.frame(h, None)  # all in: the cards are dealt with nobody to act
        if len(h.active()) > 1:
            h.board = board[:5]
            h.pot_before = h.pot
            for s in t.seats:
                s.bet = 0.0
            self.frame(h, None, shown=True)  # showdown: cards turned face up
        won = showdown(h)
        for i, w in won.items():
            t.seats[i].stack += w
        h.pot_before = 0.0
        for s in t.seats:
            s.bet = 0.0
        self.frame(h, None, shown=len(h.active()) > 1)  # the pot goes to the winner

    def go(self, hands: int) -> Report:
        for _ in range(hands):
            self.play_hand()
        return self.rep


# --------------------------------------------------------------- reporting
ORDER = ["seat not found", "extra seat", "stack wrong", "bet wrong", "in hand wrong", "position wrong",
         "hero card wrong", "board card wrong", "board count wrong", "pot wrong", "acting seat wrong",
         "acting seat when nobody acts", "your turn missed",
         "to call wrong", "their turn read as yours", "no instruction on your turn", "different instruction",
         "different amount"]


def summary(rep: Report) -> str:
    c = rep.c
    lines = [f"== {rep.name}: {c['frames']} pictures, {c['your turns']} of your turns, "
             f"{c['decisions']} instructions, {c['cards confirmed']} cards confirmed, "
             f"{c['pictures skipped']} pictures skipped"]
    if c["decisions"]:
        lines.append(f"   same instruction as from the true table: {c['same instruction']}/{c['decisions']} "
                     f"({100 * c['same instruction'] / c['decisions']:.0f}%)")
    if c["their turns"]:
        lines.append(f"   a move shown instead of WAIT on someone else's turn: {c['move shown on their turn']}/"
                     f"{c['their turns']}")
    lines.append(f"   stacks unknown: {c['stack unknown']}, to call unknown: {c['to call unknown']}, "
                 f"acting seat not read: {c['acting seat not read']}/{c['turns shown']}")
    kinds = [k for k in ORDER if c[k]] + sorted(k for k in c if k.startswith("never-wrong") and c[k])
    for k in kinds:
        lines.append(f"   {k}: {c[k]}")
        for ex in rep.examples[k][:3]:
            lines.append(f"      - {ex['detail']}" + (f"  [{os.path.basename(ex['image'])}]" if ex.get("image") else ""))
    if not kinds:
        lines.append("   no mistakes")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--layouts", default=",".join(layouts()))
    ap.add_argument("--hands", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--drop", type=float, default=0.0)
    ap.add_argument("--out", default=None, help="folder for examples of mistakes (pictures and a log)")
    args = ap.parse_args()
    lays = layouts()
    for name in args.layouts.split(","):
        t0 = time.time()
        out = os.path.join(args.out, name) if args.out else None
        rep = Run(lays[name], args.seed, out, args.drop).go(args.hands)
        print(summary(rep))
        print(f"   ({time.time() - t0:.0f} s)")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
