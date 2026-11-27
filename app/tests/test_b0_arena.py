"""B0 against Rust agents in the arena (tools/b0_arena.py).

Checked here: B0 sees each spot exactly as in tools/simulate.py (the same hand replayed in
the simulator gives the same GameState at every one of B0's decisions); each instruction
becomes the move the simulator would make, and every one that isn't legal as said is
counted and logged; B0 against B0 comes out at 0; B0 beats the arena's always-call and
always-fold bots; the same seed gives the same match; B0 itself is unchanged.
"""
import json
import os
import random
import sys

import pytest

pe = pytest.importorskip("pokerscribe_engine", reason="the Rust engine module isn't built (engine/crates/py/README.md)")

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")
DECK = [r + s for r in "23456789TJQKA" for s in "cdhs"]
# The hand-by-hand comparisons with the simulator play at blinds 32/64: one simulator chip
# (blinds 1/2) is 32 engine chips, so every amount is a binary fraction and the simulator's
# float sums are exact. At the arena's 50/100 they would differ in the last bits (12.42 as a
# sum of other decimals is not quite 621 / 50), and the simulator would sometimes offer a
# raise to a player whose stack exactly covers the call. The matches play at 50/100.
UNIT = 32
SB, BB = 32, 64
DEEP, SHORT = 100 * BB, 6 * BB


@pytest.fixture(scope="module")
def tools():
    sys.path.insert(0, TOOLS)
    try:
        import b0_arena
        import compare
        import simulate
    finally:
        sys.path.remove(TOOLS)
    return b0_arena, simulate, compare


class StateView:
    """A pokerscribe_engine State seen from one seat, under the arena View's names."""

    def __init__(self, state, seat):
        self._state, self.seat = state, seat

    def __getattr__(self, name):
        return getattr(self._state, name)

    @property
    def hole(self):
        return self._state.hole_cards(self.seat)

    @property
    def to_call(self):
        return self._state.legal_actions().call or 0


def _random_hand(seed, stack, b0, sim, me):
    """A heads-up hand in the engine (blinds 32/64, the button on seat 0) with random legal
    actions: its cards, its moves, and the GameState B0 gets at each of seat me's turns."""
    rng = random.Random(seed)
    deck = DECK[:]
    rng.shuffle(deck)
    hole, board = [deck[0:2], deck[2:4]], deck[4:9]
    h = pe.new_hand([stack, stack], SB, BB, hole=hole, board=board)
    moves, seen = [], []
    while not h.is_terminal:
        seat, legal = h.current_player, h.legal_actions()
        if seat == me:
            seen.append(sim.app_state(*b0.table(StateView(h, me))).to_json())
        options = [("fold", None)] * legal.fold + [("check", None)] * (3 * legal.check)
        options += [("call", None)] * (3 * (legal.call is not None))
        if legal.can_raise:
            lo, hi = legal.min_raise_to, legal.max_raise_to
            options += [("raise", lo), ("raise", hi), ("raise", rng.randint(lo, hi))]
        kind, amount = rng.choice(options)
        moves.append((seat, kind, amount))
        h.apply(kind, amount)
    return h, hole, board, moves, seen


def test_b0_sees_each_spot_exactly_as_in_the_simulator(tools, monkeypatch):
    """The same hand played in the simulator (the same cards, the same moves) gives B0 the same
    GameState at each of its decisions, to the last bit: stacks, bets, pot, blinds, the seat
    names "BTN/SB" and "BB", each player's last action, the cards and the buttons. The hands
    are random, 100 big blinds deep and 6 deep (all-ins), with B0 on the button and in the
    big blind. The simulator also pays the same result."""
    b0, sim, compare = tools
    script = []

    def scripted(h, i):
        seat, kind, amount = script.pop(0)
        assert seat == sim_to_engine[i], "the simulator and the engine disagree on who acts"
        return kind, (amount / UNIT if kind == "raise" else 0.0)

    def app_decide(h, i, budget_ms, stats):
        simulated.append(sim.app_state(h, i).to_json())
        return scripted(h, i)

    monkeypatch.setattr(sim, "app_decide", app_decide)
    monkeypatch.setattr(sim, "bot_decide", lambda h, i, rng: scripted(h, i))
    spots, streets, positions, all_ins = 0, set(), set(), 0
    for k in range(400):
        stack = DEEP if k % 2 else SHORT
        me = (k // 2) % 2
        final, hole, board, moves, seen = _random_hand(k, stack, b0, sim, me)
        # the simulator's seats: B0 is its seat 0, the other player its seat 1
        sim_to_engine = [me, 1 - me]
        script[:] = moves
        simulated = []
        stats = compare.new_stats()
        net = sim.play_hand(["app", "bot"], button=(0 - me) % 2, seed=k, budget_ms=0, depth_bb=stack / BB,
                            stats=stats, names=["You", "P1"], hole_override={0: tuple(hole[me]), 1: tuple(hole[1 - me])},
                            board_override=dict(enumerate(board)))
        assert script == [], k
        assert simulated == seen, k
        assert net[0] == final.payouts()[me] / UNIT, k
        spots += len(seen)
        for st in seen:
            streets.add(st["street"]["value"])
            positions.add(next(p["position"]["value"] for p in st["players"] if p["is_hero"]))
        all_ins += any(final.is_all_in(s) for s in range(2))
    assert spots > 600 and streets == {"preflop", "flop", "turn", "river"} and positions == {"BTN/SB", "BB"}
    assert all_ins > 50


def test_the_spot_reads_as_the_app_reads_a_table(tools):
    """One spot by hand: B0 in the big blind facing a raise to 3 big blinds, 100 deep."""
    b0, sim, _ = tools
    h = pe.new_hand([10000, 10000], 50, 100, hole=["AsKd", "7c2h"], board="2c3d4h5s6c")
    h.apply("raise", 300)
    st = sim.app_state(*b0.table(StateView(h, 1)))
    hero, other = st.players
    assert [c.value for c in st.hero_cards] == ["7c", "2h"] and st.board == []
    assert st.blinds.value == (1.0, 2.0) and st.street.value == "preflop"
    assert (hero.seat, hero.position.value, hero.stack.value, hero.bet.value) == (0, "BB", 198.0, 2.0)
    assert (other.seat, other.position.value, other.stack.value, other.bet.value) == (1, "BTN/SB", 194.0, 6.0)
    assert other.last_action.value.kind == "raise" and other.last_action.value.amount == 6.0
    assert hero.last_action.value is None and st.pot.value == 0.0 and not st.pot_includes_bets
    assert st.to_call.value == 4.0 and [a.kind for a in st.available_actions.value] == ["fold", "call", "raise"]
    with pytest.raises(ValueError, match="blinds 1/2"):
        b0.table(StateView(pe.new_hand([10000, 10000], 40, 100, seed=1), 0))
    with pytest.raises(ValueError, match="antes"):
        b0.table(StateView(pe.new_hand([10000, 10000], 50, 100, ante=10, seed=1), 0))


def _instructions(sim, h, me):
    """Every kind of instruction B0 can give, at sizes around the legal ones."""
    from app.poker.advice import Advice

    seat = h.seats[me]
    total, pot, current = seat.stack + seat.bet, h.pot, h.current
    out = [Advice("fold", "FOLD", ""), Advice("check", "CHECK", ""), Advice("call", "CALL", ""),
           Advice("raise", "RAISE", ""), Advice("all-in", f"ALL IN ({total:g})", "", amount=total),
           Advice("all-in", f"CALL ALL IN ({seat.stack:g})", "", amount=seat.stack),
           Advice("wait", "WAIT", ""), Advice("unknown", "CAN'T READ THE BOARD", "")]
    for size in (0.5, 1.5, 2.0, current + 1.0, 2.5 * current, current + h.min_raise, pot, total - 1, total, 2 * total):
        if size <= 0:
            continue
        word = "bet" if current == 0 else "raise"
        out.append(Advice(word, f"{word.upper()} {size:g}", "", amount=size))
    return out


def test_each_instruction_becomes_the_simulators_move(tools):
    """At random spots, every kind of instruction: the engine move puts in the same chips and
    folds the same as the simulator's own move for it (simulate.app_move, then simulate.act).
    One that is legal as said is played as said; one that isn't is named, never passed over."""
    b0, sim, _ = tools
    import copy

    checked = named = 0
    for k in range(120):
        stack = DEEP if k % 2 else SHORT
        me = k % 2
        final, hole, board, moves, _ = _random_hand(1000 + k, stack, b0, sim, me)
        h = pe.new_hand([stack, stack], SB, BB, hole=hole, board=board)
        for seat, kind, amount in moves:
            if seat == me:
                view = StateView(h, me)
                hand, i = b0.table(view)
                legal = h.legal_actions()
                for adv in _instructions(sim, hand, i):
                    action, problem = b0.engine_action(view, hand, i, adv)
                    played = h.copy()
                    played.apply(*([action] if isinstance(action, str) else action))
                    theirs = copy.deepcopy(hand)
                    sim.act(theirs, i, *sim.app_move(theirs, i, adv))
                    other = theirs.seats[1 - i]
                    at_risk = other.put_in + other.stack  # chips past this the other player can't match
                    assert played.is_folded(me) == theirs.seats[i].folded, (k, adv)
                    # the same chips, to the whole engine chip a size like 2/3 of the pot is rounded to
                    assert abs(min(played.committed[me] / UNIT, at_risk) - min(theirs.seats[i].put_in, at_risk)) <= (
                        0.5 / UNIT), (k, adv, action)
                    # legal as said, or named
                    said = {"fold": ("fold", None), "check": ("check", None), "call": ("call", None)}.get(adv.action)
                    if adv.action == "all-in" and adv.headline.startswith("CALL"):
                        said = ("call", None)
                    elif adv.action == "all-in":
                        said = ("raise", legal.max_raise_to) if legal.can_raise else None
                    elif adv.action in ("bet", "raise") and adv.amount is not None:
                        said = ("raise", int(round(adv.amount * UNIT)))
                    literal = said is not None and legal.allows(*said)
                    if adv.action == "all-in" and not literal and not adv.headline.startswith("CALL"):
                        literal = legal.call is not None and legal.call >= h.stacks[me]  # calling is all in
                    assert (problem is None) == literal, (k, adv, action, problem)
                    if problem is None:  # played exactly as said (ALL IN by calling, when a call is all in)
                        assert action == ("call" if said is None else said[0] if said[1] is None else said), (k, adv)
                    checked += 1
                    named += problem is not None
            h.apply(kind, amount)
    assert checked > 3000 and named > 1000


def test_what_is_wrong_with_an_instruction_is_named_as_the_simulator_names_it(tools):
    from app.poker.advice import Advice

    b0, sim, _ = tools

    def spot(*moves, stack=10000):
        h = pe.new_hand([stack, stack], 50, 100, hole=["AsKd", "7c2h"], board="2c3d4h5s6c")
        for m in moves:
            h.apply(*m)
        view = StateView(h, h.current_player)
        return view, *b0.table(view)

    # the turn, checked to B0 in a pot of two big blinds (4 of the simulator's chips)
    turn = spot(("call",), ("check",), ("check",), ("check",))
    assert turn[0].street == "turn" and turn[0].pot == 200
    cases = [
        (turn, Advice("bet", "BET 1.5", "", amount=1.5), ("raise", 100), "below the minimum bet or raise"),
        (turn, Advice("bet", "BET 3", "", amount=3.0), ("raise", 150), None),
        (turn, Advice("fold", "FOLD", ""), "check", "fold when checking is free"),
        (turn, Advice("call", "CALL", ""), "check", "call with nothing to call"),
        (turn, Advice("bet", "BET", ""), ("raise", 133), "bet or raise with no amount"),  # 2/3 of the pot of 4
        (turn, Advice("bet", "BET 500", "", amount=500.0), ("raise", 9900), "more than the stack"),
        (turn, Advice("wait", "WAIT", ""), "check", "WAIT on your turn"),
        (turn, Advice("all-in", "ALL IN (198)", "", amount=198.0), ("raise", 9900), None),
    ]
    facing = spot(("raise", 300))  # B0 in the big blind facing a raise to 3 big blinds
    cases += [
        (facing, Advice("check", "CHECK", ""), "fold", "check facing a bet"),
        (facing, Advice("raise", "RAISE TO 8", "", amount=8.0), ("raise", 500), "below the minimum bet or raise"),
        (facing, Advice("raise", "RAISE", ""), ("raise", 900), "bet or raise with no amount"),  # 3 times the bet
        (facing, Advice("call", "CALL 4", "", amount=4.0), "call", None),
    ]
    shove = spot(("raise", 10000))  # facing an all-in: no raise is possible, calling puts B0 all in
    cases += [
        (shove, Advice("all-in", "ALL IN (200)", "", amount=200.0), "call", None),
        (shove, Advice("all-in", "CALL ALL IN (198)", "", amount=198.0), "call", None),
        (shove, Advice("raise", "RAISE TO 150", "", amount=150.0), "call", "raise when only a call is allowed"),
    ]
    short = spot(("raise", 200), stack=200)  # 2 big blinds deep: the button jams, B0 can only call
    cases += [(short, Advice("raise", "RAISE TO 4", "", amount=4.0), "call", "raise when only a call is allowed")]
    for (view, h, me), adv, want, problem in cases:
        assert b0.engine_action(view, h, me, adv) == (want, problem), adv.headline


def test_illegal_instructions_are_counted_and_logged(tools, monkeypatch, tmp_path):
    """In a match, an instruction that isn't legal as said is played as the simulator plays it,
    counted, and written to the log with the spot."""
    from app.poker.advice import Advice

    b0, sim, _ = tools
    monkeypatch.setattr(sim, "decision", lambda h, me, overrides, st: Advice("bet", "BET 1.5", "", amount=1.5))
    log = tmp_path / "illegal.jsonl"
    report, player = b0.run("call", 20, seed=3, log=str(log))
    s = player.stats()
    assert s["instructions"] > 40 and s["illegal"] == {"below the minimum bet or raise": s["instructions"]}
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(lines) == s["instructions"] and len(s["illegal_examples"]) == b0.EXAMPLES
    first = lines[0]
    assert first["problem"] == "below the minimum bet or raise" and first["instruction"]["headline"] == "BET 1.5"
    assert first["played"][0] == "raise" and first["played"][1] == first["legal"]["min_raise_to"]
    assert first["hand"] == 0 and len(first["cards"]) == 4 and first["position"] in ("BTN/SB", "BB")
    assert report.result("b0")["illegal_actions"] == 0  # the arena got legal actions only


def test_always_wrong_instructions_are_counted_with_their_spots(tools, monkeypatch):
    """The simulator's always-wrong checks run on every instruction, and the first spots that
    fail one are kept, with what failed. Here B0 is made to go all in with every hand before
    the flop, 100 big blinds deep: legal, but always wrong outside the top 5% of hands."""
    from app.poker import hands
    from app.poker.advice import Advice

    b0, sim, _ = tools
    monkeypatch.setattr(sim, "decision", lambda h, me, overrides, st: Advice("all-in", "ALL IN (200)", "", amount=200))
    report, player = b0.run("fold", 40, seed=4)
    s = player.stats()
    wrong = sum(s["always_wrong"].values())
    assert s["illegal"] == {} and 0 < wrong < s["instructions"]
    assert all(k.startswith("all in 100bb deep preflop with ") for k in s["always_wrong"])
    assert len(s["always_wrong_examples"]) == min(wrong, b0.EXAMPLES)
    for ex in s["always_wrong_examples"]:
        cls = hands.preflop_class((ex["cards"][:2], ex["cards"][2:]))
        assert ex["always_wrong"] == [f"all in 100bb deep preflop with {cls}"]
        assert ex["problem"] is None and ex["played"] == ["raise", 10_000] and ex["street"] == "preflop"


# ------------------------------------------------------------- the matches
def test_b0_against_b0_is_zero(tools):
    """In duplicate play B0 meets itself on the same cards from both seats: exactly 0. In plain
    play the deals don't cancel, and the result is 0 within the standard error."""
    b0, _, _ = tools
    report, first = b0.run(b0.opponent("b0"), 20, seed=5)
    for r in report.to_dict()["results"]:
        assert r["bb_per_100"] == 0.0 and r["se"] == 0.0 and r["illegal_actions"] == 0
    assert first.instructions > 20 and first.stats()["illegal"] == {}
    plain = b0.run(b0.opponent("b0"), 60, seed=5, duplicate=False)[0].result("b0")
    assert plain["se"] > 0 and abs(plain["bb_per_100"]) < 3 * plain["se"]


def test_b0_beats_always_call_and_always_fold(tools):
    """By more than 2.5 SE each. Sized from the 1000-deal runs (docs/research/runs/phase6_b0_arena):
    against fold B0 wins 35 bb/100 with an sd per deal of 37, against call 240 with an sd of
    606. At 150 deals that is 4.9 SE expected against call, under 2.5 about 1 time in 100 (60
    deals, 3.1 SE expected, was too few). Every hand against call goes to the river, so this
    is the slow test (about a minute)."""
    b0, _, _ = tools
    for bot, deals in (("fold", 30), ("call", 150)):
        report, player = b0.run(bot, deals, seed=2)
        r = report.result("b0")
        assert r["bb_per_100"] > 2.5 * r["se"] > 0, (bot, r)
        assert player.stats()["illegal"] == {} and player.stats()["always_wrong"] == {}


def test_the_same_seed_gives_the_same_match_and_b0_is_unchanged(tools):
    from app.poker import advice

    b0, _, _ = tools
    before = dict(advice.TUNING)

    def match(seed):
        report, player = b0.run("tag", 25, seed=seed)
        d = report.to_dict()
        d.pop("timing")
        s = player.stats()
        s.pop("seconds")
        return d, s

    first = match(9)
    assert match(9) == first and match(10)[0] != first[0]
    assert advice.TUNING == before  # B0's settings are put back after every decision
