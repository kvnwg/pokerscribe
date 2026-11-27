"""B0 against Rust agents, heads-up, in the Rust arena (engine/crates/arena).

    python tools/b0_arena.py tag [--deals 1000] [--seed 1]      # B0 against the arena's tag bot
    python tools/b0_arena.py b0 --deals 200                     # B0 against itself
    python tools/b0_arena.py b0 --variant '{"bet_size": 0.5}'   # B0 against a TUNING variant of itself
    python tools/b0_arena.py call --log illegal.jsonl --out report.json
    python tools/b0_arena.py blueprint:strategy.bps --stack-bb 20  # B0 against a blueprint, at its stack depth

The arena plays the match: each deal twice with the seats swapped (duplicate), hands that
end all in before the river scored by their equity, bb/100 with a standard error, all
exactly as in a match between Rust agents (`engine/crates/arena/README.md`). B0 plays its
seat from Python: the arena calls `B0Player.act(view)` whenever it is B0's turn, through
the pokerscribe_engine bindings (`engine/crates/py/README.md`, which also has the usage).

B0 sees each spot exactly as in tools/simulate.py: `table(view)` turns the arena's view
into the simulator's own `Hand` (stacks, bets and pot in the simulator's chips, blinds 1/2,
seats named "BTN/SB" and "BB", each player's last action this street), and B0 is asked
through the simulator's own functions (`app_state`, `decision`, `app_move`). Its
instruction becomes the nlhe action the simulator would play. An instruction that is not
legal as said (under the minimum bet, a check facing a bet, ...) is played the way the
simulator plays it, and counted and logged: see `engine_action`.

Needs the Rust module: `python -m pip install ./engine/crates/py`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulate as sim  # noqa: E402
from app.state.model import Action  # noqa: E402

EXAMPLES = 25  # illegal instructions kept in memory (all of them go to the log file)


# ------------------------------------------------------------------ the spot
def unit(view) -> float:
    """Arena chips per simulator chip: the simulator's big blind is 2."""
    return view.big_blind / sim.BB


def table(view) -> Tuple[sim.Hand, int]:
    """The simulator's Hand at this decision, and B0's seat in it: what simulate.app_state
    reads to build what B0 sees. Seats and the button are the arena's; amounts are in the
    simulator's chips (blinds 1/2)."""
    if view.ante:
        raise ValueError("B0 plays without antes, as in the simulator")
    if view.small_blind * sim.BB != view.big_blind * sim.SB:
        raise ValueError(f"B0 plays at blinds 1/2, as in the simulator, not {view.small_blind}/{view.big_blind}")
    u = unit(view)
    n, me = view.num_players, view.seat
    stacks, bets, committed = view.stacks, view.bets, view.committed
    seats = []
    for i in range(n):
        seats.append(sim.Seat("app" if i == me else "rust", stack=stacks[i] / u, bet=bets[i] / u,
                              put_in=committed[i] / u, folded=view.is_folded(i), all_in=view.is_all_in(i),
                              # the other seats by where they sit from B0, as GameState numbers them
                              name="You" if i == me else f"P{(i - me) % n}"))
    seats[me].cards = tuple(view.hole)
    # Each seat's last action this street, as simulate.act labels it. The simulator clears it
    # when a street starts, except for players who folded.
    street, last = view.street, {}
    for m in view.history():
        if m["street"] == street:
            last[m["seat"]] = m
    for i, s in enumerate(seats):
        m = last.get(i)
        if m is None:
            s.last = Action("fold") if s.folded else None
        elif m["action"] in ("fold", "check"):
            s.last = Action(m["action"])
        elif m["action"] == "call":
            s.last = Action("call", s.bet)
        else:
            s.last = Action("all-in" if stacks[i] == 0 else "raise", m["amount"] / u)
    h = sim.Hand(seats, view.button, board=list(view.board), pot_before=(view.pot - sum(bets)) / u,
                 current=view.max_bet / u, min_raise=view.full_raise / u)
    return h, me


def engine_action(view, h: sim.Hand, me: int, adv) -> Tuple[object, Optional[str]]:
    """B0's instruction `adv` as an nlhe action ("fold", "check", "call" or ("raise", chips)),
    and what was wrong with it, or None when it is legal as said.

    The action is always the one the simulator plays for the instruction (simulate.app_move,
    then simulate.act), so B0 plays as it does in the simulator. What is wrong is named as in
    simulate.check_advice:
      fold when checking is free      -> check
      check facing a bet              -> fold
      call with nothing to call       -> check
      bet or raise with no amount     -> the simulator's size (3 times the bet, or 2/3 of the pot)
      below the minimum bet or raise  -> the minimum
      more than the stack             -> all in
      raise when only a call is allowed (the other player is all in or covered) -> call
      WAIT or similar on your turn    -> check, or fold facing a bet
    """
    legal = view.legal_actions()
    what = adv.action
    if what == "fold":
        return ("fold", None) if legal.fold else ("check", "fold when checking is free")
    if what == "check":
        return ("check", None) if legal.check else ("fold", "check facing a bet")
    if what == "call" or (what == "all-in" and adv.headline.startswith("CALL")):
        return ("call", None) if legal.call is not None else ("check", "call with nothing to call")
    if what in ("bet", "raise", "all-in"):
        u = unit(view)
        _, to = sim.app_move(h, me, adv)  # the amount, at most the stack; the size in words when none is given
        problem = None
        if what != "all-in" and adv.amount is None:
            problem = "bet or raise with no amount"
        elif what != "all-in" and adv.amount * u > view.stacks[me] + view.bets[me] + 0.5:
            problem = "more than the stack"
        if not legal.can_raise:
            if legal.call is None:
                return "check", problem or "raise when only a check is allowed"
            if what == "all-in" and legal.call >= view.stacks[me]:
                return "call", problem  # calling puts B0 all in: what it said
            return "call", problem or "raise when only a call is allowed"
        chips = int(round(to * u))
        if chips < legal.min_raise_to:
            return ("raise", legal.min_raise_to), problem or "below the minimum bet or raise"
        return ("raise", min(chips, legal.max_raise_to)), problem
    # WAIT, UNKNOWN: no move at all
    return ("check" if legal.check else "fold"), f"{adv.headline} on your turn"


# ------------------------------------------------------------------ the player
class B0Player:
    """B0 in an arena seat. `variant`: overrides of advice.TUNING, as in tools/compare.py (None
    is B0 itself). `log`: a file name; every illegal instruction is written to it as a line of
    JSON. The counts and the time spent are kept on the player."""

    def __init__(self, name: str = "b0", variant: Optional[dict] = None, log: Optional[str] = None):
        self.name = name
        self.variant = variant or None
        self.log = log
        self.hands = 0  # hands begun; with one thread, hand k is deal k // 2 heads-up
        self.instructions = 0
        self.illegal = Counter()
        self.examples = []
        self.checks = {"problems": defaultdict(int), "examples": []}  # simulate.check_advice's
        self.wrong_examples = []  # the spots of the first always-wrong instructions
        self.seconds = defaultdict(float)
        if log:
            open(log, "w").close()

    def begin_hand(self, view) -> None:
        self.hands += 1

    def act(self, view):
        t0 = time.perf_counter()
        h, me = table(view)
        st = sim.app_state(h, me)
        t1 = time.perf_counter()
        adv = sim.decision(h, me, self.variant, st)
        t2 = time.perf_counter()
        before = dict(self.checks["problems"])
        sim.check_advice(h, me, adv, self.checks)
        action, problem = engine_action(view, h, me, adv)
        t3 = time.perf_counter()
        self.instructions += 1
        if problem is not None:
            self.record(view, h, me, adv, action, problem)
        wrong = [k for k, v in self.checks["problems"].items() if v > before.get(k, 0)]
        if wrong and len(self.wrong_examples) < EXAMPLES:
            self.wrong_examples.append({"always_wrong": wrong, **self.entry(view, h, me, adv, action, problem)})
        self.seconds["spot"] += t1 - t0
        self.seconds["advice"] += t2 - t1
        self.seconds["checks"] += t3 - t2
        return action

    def record(self, view, h, me, adv, action, problem) -> None:
        self.illegal[problem.split(":")[0]] += 1
        entry = self.entry(view, h, me, adv, action, problem)
        if len(self.examples) < EXAMPLES:
            self.examples.append(entry)
        if self.log:
            with open(self.log, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def entry(self, view, h, me, adv, action, problem) -> dict:
        """The spot, the instruction and what was played, as JSON."""
        legal = view.legal_actions()
        return {"problem": problem, "hand": self.hands - 1, "seat": view.seat, "position": h.position(me),
                "cards": "".join(view.hole), "board": "".join(view.board), "street": view.street,
                "pot": view.pot, "to_call": view.to_call, "stacks": view.stacks, "bets": view.bets,
                "history": [(m["seat"], m["action"], m["amount"]) for m in view.history()],
                "instruction": {"action": adv.action, "amount": adv.amount, "headline": adv.headline},
                "legal": {"fold": legal.fold, "check": legal.check, "call": legal.call,
                          "min_raise_to": legal.min_raise_to, "max_raise_to": legal.max_raise_to},
                "played": action if isinstance(action, str) else list(action)}

    def stats(self) -> dict:
        return {"name": self.name, "variant": self.variant, "hands": self.hands, "instructions": self.instructions,
                "illegal": dict(self.illegal), "illegal_examples": self.examples,
                "always_wrong": dict(self.checks["problems"]), "always_wrong_examples": self.wrong_examples,
                "seconds": dict(self.seconds)}


# ------------------------------------------------------------------ the match
def opponent(name: str, variant: Optional[dict] = None, log: Optional[str] = None):
    """A Rust agent's name stays a name; "b0" is a second B0 (with `variant`, a TUNING variant)."""
    if name == "b0":
        return B0Player("b0-variant" if variant else "b0-copy", variant, log)
    return name


def run(against, deals: int, seed: int = 1, stack_bb: float = 100.0, log: Optional[str] = None, **match):
    """B0 (agent 0) against `against` (a Rust agent's name or a Python agent) heads-up: the
    arena's MatchReport and B0's player. `match` goes to pokerscribe_engine's run_match
    (duplicate, all_in_equity, max_runouts, threads, ...)."""
    import pokerscribe_engine as pe

    b0 = B0Player(log=log)
    report = pe.run_match([b0, against], deals, seed, stack=int(round(stack_bb * 100)), small_blind=50,
                          big_blind=100, **match)
    return report, b0


def format_stats(players, report: dict) -> str:
    lines = []
    seconds = report["timing"]["seconds"]
    python = 0.0
    for p in players:
        s = p.stats()
        python += sum(s["seconds"].values())
        illegal = ", ".join(f"{k} x{v}" for k, v in sorted(s["illegal"].items())) or "none"
        wrong = ", ".join(f"{k} x{v}" for k, v in sorted(s["always_wrong"].items())) or "none"
        lines.append(f"{s['name']}: {s['instructions']} instructions in {s['hands']} hands; not legal as said: "
                     f"{illegal}; the simulator's always-wrong checks: {wrong}")
        for ex in s["illegal_examples"][:5]:
            lines.append(f"   {ex['problem']}: {ex['instruction']['headline']} with {ex['cards']} "
                         f"{ex['board'] or 'preflop'}, played {ex['played']}")
        for ex in s["always_wrong_examples"][:5]:
            lines.append(f"   always wrong, {'; '.join(ex['always_wrong'])}: {ex['instruction']['headline']} with "
                         f"{ex['cards']} {ex['board'] or 'preflop'}, played {ex['played']}")
    per = [p.stats() for p in players]
    instructions = sum(s["instructions"] for s in per)
    spent = defaultdict(float)
    for s in per:
        for k, v in s["seconds"].items():
            spent[k] += v
    if instructions:
        lines.append(f"time: {seconds:.1f} s, {report['hands'] / seconds:.1f} hands/s, "
                     f"{1000 * seconds / instructions:.1f} ms per B0 instruction. In B0: advice "
                     f"{spent['advice']:.1f} s, building the spot {spent['spot']:.1f} s, checks and mapping "
                     f"{spent['checks']:.1f} s; the rest (arena, Rust agent, crossing to Python) "
                     f"{seconds - python:.1f} s")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("opponent", help="a Rust agent (pokerscribe_engine.agents()) or b0")
    ap.add_argument("--deals", type=int, default=1000, help="deals; each is played twice, seats swapped")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--variant", default=None, help="with b0: JSON overrides of advice.TUNING for the opponent")
    ap.add_argument("--stack-bb", type=float, default=100.0, help="stacks in big blinds (default 100)")
    ap.add_argument("--plain", action="store_true", help="each deal once, seats alternating (no duplicate)")
    ap.add_argument("--no-equity", action="store_true", help="score real chips when all in before the river")
    ap.add_argument("--log", help="write every instruction that is not legal as said to this file (JSON lines)")
    ap.add_argument("--out", help="save the report, with B0's counts, as JSON")
    a = ap.parse_args()
    if a.variant and a.opponent != "b0":
        ap.error("--variant goes with the opponent b0")
    other = opponent(a.opponent, json.loads(a.variant) if a.variant else None)
    report, b0 = run(other, a.deals, a.seed, a.stack_bb, a.log, duplicate=not a.plain, all_in_equity=not a.no_equity)
    print(report.summary())
    d = report.to_dict()
    players = [b0] + ([other] if isinstance(other, B0Player) else [])
    print(format_stats(players, d))
    if a.out:
        d["b0"] = [p.stats() for p in players]
        with open(a.out, "w") as f:
            json.dump(d, f, indent=1)


if __name__ == "__main__":
    main()
