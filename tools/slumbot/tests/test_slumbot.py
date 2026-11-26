"""Tests for tools/slumbot: the action-string parser on recorded examples, the client, the bots,
the session loop with a scripted fake server, the hand log and resuming, and bb/100."""
from __future__ import annotations

import json
import os
import urllib.error

import pytest

from tools.slumbot import protocol
from tools.slumbot.bots import B0Bot, BotState, CheckCallBot, Decision, make_bot
from tools.slumbot.client import SlumbotClient, SlumbotError, SlumbotRejected, _HTTPStatus
from tools.slumbot.protocol import ActionParseError, chips_won, parse_action
from tools.slumbot.session import (Desync, check_result, play_hand, rate, read_log, run_session,
                                   summary)

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDED = os.path.join(HERE, "recorded_hands.jsonl")


def recorded():
    with open(RECORDED, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --- the parser ---------------------------------------------------------------------------------

def test_documented_examples():
    # From Slumbot's API page and sample_api.py.
    h = parse_action("b200c/kk/kk/kb200")
    assert h.street == 3 and h.to_act == protocol.BB_SEAT and h.to_call() == 200
    assert h.contributed == [200, 400]
    assert [a.kind for a in h.streets[3]] == ["check", "bet"]

    h = parse_action("b20000c///")
    assert h.over and h.showdown and h.all_in and h.contributed == [20000, 20000]
    assert h.board_cards_needed() == 5

    h = parse_action("b200c/kb400")  # a pot-size bet on the flop
    assert h.streets[1][1].to == 400 and h.pot == 800
    h = parse_action("b200c/kb400c")
    assert h.contributed == [600, 600] and h.street == 2 and h.to_act == protocol.BB_SEAT


def test_empty_action_is_the_small_blind_to_act():
    h = parse_action("")
    assert h.to_act == protocol.SB_SEAT and h.to_call() == 50 and h.pot == 150
    assert h.raise_bounds() == (200, 20000)
    assert h.can_fold() and h.can_call() and not h.can_check()


def test_bet_amounts_are_street_totals_and_raise_kinds():
    h = parse_action("cb300c/b300b900")
    pre, flop = h.streets[0], h.streets[1]
    assert [(a.seat, a.kind, a.added) for a in pre] == [(1, "call", 50), (0, "raise", 200), (1, "call", 200)]
    assert [(a.seat, a.kind, a.to, a.added) for a in flop] == [(0, "bet", 300, 300), (1, "raise", 900, 900)]
    assert h.contributed == [600, 1200] and h.to_act == 0 and h.to_call() == 600
    assert h.raise_bounds() == (1500, 19700)  # min raise adds the last raise (600) again


def test_min_raise_rules():
    assert parse_action("b200").raise_bounds() == (300, 20000)
    with pytest.raises(ActionParseError):
        parse_action("b199")
    with pytest.raises(ActionParseError):
        parse_action("b200b299")
    with pytest.raises(ActionParseError):
        parse_action("b200c/b99")  # a flop bet is at least one big blind
    assert parse_action("b200c/b100").streets[1][0].kind == "bet"
    # All-in for less than a full raise is allowed.
    h = parse_action("b200c/b19000")
    assert h.raise_bounds() == (19800, 19800)
    h = parse_action("b200c/b19000b19800")
    assert h.streets[1][-1].all_in and not h.can_raise()
    with pytest.raises(ActionParseError):
        parse_action("b200c/b19000b19800b19900")
    with pytest.raises(ActionParseError):
        parse_action("b20001")


@pytest.mark.parametrize("bad", [
    "k",                     # check facing the small blind's call amount
    "b200k",                 # check facing a raise
    "ck/f",                  # fold when checking is free
    "b200cb400",             # missing slash
    "b200c//",               # empty street that is not after an all-in
    "b20000c/",              # some but not all slashes after an all-in call
    "b20000c//k",            # action after an all-in call
    "b200f/",                # anything after a fold
    "b200c/kk/kk/kkk",       # past the river
    "b",                     # bet without a size
    "x",
])
def test_rejects_what_the_reference_parser_rejects(bad):
    with pytest.raises(ActionParseError):
        parse_action(bad)


def test_fold_results():
    h = parse_action("b200f")
    assert h.folded == 0
    assert chips_won(h, me=0) == -100 and chips_won(h, me=1) == 100
    h = parse_action("f")
    assert chips_won(h, me=1) == -50 and chips_won(h, me=0) == 50
    h = parse_action("b300b900b20000f")
    assert chips_won(h, me=1) == 900


def test_recorded_hands_parse_and_match_slumbots_results():
    hands = recorded()
    assert len(hands) >= 20
    kinds = set()
    for r in hands:
        h = parse_action(r["action"])
        assert h.over, r["action"]
        res = check_result(h, r["seat"], r["hole_cards"], r.get("bot_hole_cards"), r["board"],
                           r["winnings"])
        assert res["check"] in ("ok", "unchecked"), r
        if h.folded is None:
            assert res["check"] == "ok", r  # every showdown in the sample shows Slumbot's cards
        kinds.add("fold" if h.folded is not None else ("all-in" if h.all_in else "showdown"))
        # Every prefix we acted on parses, with us to act.
        for d in r["decisions"]:
            p = parse_action(d["facing"])
            assert p.to_act == r["seat"] and p.legal_incr(d["incr"]), (r["action"], d)
    assert {"fold", "showdown"} <= kinds


def test_every_recorded_prefix_parses():
    for r in recorded():
        toks = protocol.tokenize(r["action"])
        whole = parse_action(r["action"])
        for i in range(len(toks) + 1):
            prefix = "".join(toks[:i])
            try:
                h = parse_action(prefix)
            except ActionParseError as e:  # only a cut-off run of slashes after an all-in call
                assert whole.all_in and "slash" in str(e), (prefix, e)
                continue
            assert h.over == (i == len(toks)) or whole.all_in, prefix


def test_postflop_order_and_opponent_name_can_be_set_for_other_servers():
    # tools/gtowizard reuses this parser. Slumbot's own order and name stay the defaults.
    h = parse_action("b200c/")
    assert h.to_act == protocol.BB_SEAT and h.postflop_first == protocol.BB_SEAT
    h = parse_action("b200c/kb400", postflop_first=protocol.SB_SEAT)
    assert [(a.seat, a.kind) for a in h.streets[1]] == [(1, "check"), (0, "bet")]
    assert h.to_act == protocol.SB_SEAT and h.contributed == [600, 200]
    assert h.legal_incr("c") and not h.legal_incr("k")
    nxt = parse_action("b200c/kb400c/", postflop_first=protocol.SB_SEAT)
    assert nxt.street == 2 and nxt.to_act == protocol.SB_SEAT
    assert h.by_street(me=0, opponent="gto_wizard")["flop"] == ["gto_wizard checks", "me bets to 400"]
    assert parse_action("b200c/kb400").by_street(me=0)["flop"] == ["me checks", "slumbot bets to 400"]


# --- the bots -----------------------------------------------------------------------------------

def state(action, me=0, hole=("Ah", "Kd"), board=()):
    return BotState(me=me, hole_cards=list(hole), board=list(board), history=parse_action(action))


def test_check_call_bot():
    bot = CheckCallBot()
    assert bot.act(state("b200")) == Decision("call")
    assert bot.act(state("b200c/")) == Decision("check")
    assert bot.act(state("", me=1)) == Decision("call")
    assert bot.act(state("c")) == Decision("check")
    assert Decision("raise", 600).incr() == "b600" and Decision("fold").incr() == "f"


def test_state_legality_and_big_blind_view():
    s = state("b200c/kb200", board=("8d", "6c", "2s"))
    assert s.is_legal(Decision("call")) and s.is_legal(Decision("fold"))
    assert not s.is_legal(Decision("check"))
    assert s.is_legal(Decision("raise", 400)) and not s.is_legal(Decision("raise", 399))
    v = s.in_bb()
    assert v["position"] == "BB" and v["street"] == "flop"
    assert v["pot_bb"] == 6 and v["to_call_bb"] == 2 and v["stack_bb"] == 198
    assert v["min_raise_to_bb"] == 4 and v["max_raise_to_bb"] == 198
    assert v["history"] == ["preflop:SB:raise 2", "preflop:BB:call", "flop:BB:check", "flop:SB:bet 2"]


def test_b0_is_a_stub_until_heads_up_simulation_exists():
    with pytest.raises(NotImplementedError):
        B0Bot()
    with pytest.raises(NotImplementedError):
        make_bot("b0")
    assert isinstance(make_bot("checkcall"), CheckCallBot)


# --- the client ---------------------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def __call__(self):
        return self.t


class ScriptTransport:
    """Replies from a list; each item is a dict or an exception to raise."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def post(self, path, body):
        self.sent.append((path, dict(body)))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_rate_limit_and_retries():
    clock = FakeClock()
    t = ScriptTransport([{"action": "", "client_pos": 1, "hole_cards": ["Ah", "Kd"], "token": "T1"},
                         urllib.error.URLError("down"), _HTTPStatus(503, "7", b""),
                         {"action": "cb300", "old_action": "c", "client_pos": 1, "hole_cards": []}])
    c = SlumbotClient(transport=t, min_interval=1.0, backoff=2.0, sleep=clock.sleep, clock=clock)
    c.new_hand()
    assert c.token == "T1" and t.sent[0][1] == {}
    c.act("c")
    assert t.sent[-1] == ("/slumbot/api/act", {"token": "T1", "incr": "c"})
    assert 2.0 in clock.slept and 7.0 in clock.slept  # backoff, then Retry-After
    assert c.requests == 4


def test_min_interval_is_enforced():
    clock = FakeClock()
    t = ScriptTransport([{"action": ""}] * 3)
    c = SlumbotClient(transport=t, min_interval=0.01, sleep=clock.sleep, clock=clock)
    assert c.min_interval == 0.2  # the floor
    for _ in range(3):
        c.new_hand()
    assert clock.slept == [0.2, 0.2]


def test_errors():
    t = ScriptTransport([{"error_msg": "Bet size too small"}, _HTTPStatus(400, None, b"bad")])
    c = SlumbotClient(token="T", transport=t, sleep=lambda s: None)
    with pytest.raises(SlumbotRejected):
        c.act("b1")
    with pytest.raises(SlumbotError):
        c.new_hand()  # 400 is not retried


# --- the session with a scripted server ---------------------------------------------------------

def hand_script(seat, hole, steps, final):
    """A hand as the server would play it: new_hand reply, then one reply per action we send."""
    first_action = steps[0][0] if steps else final["action"]
    replies = [{"old_action": "", "action": first_action, "client_pos": seat, "hole_cards": hole,
                "board": [], "token": "tok-secret-1"}]
    for i, (facing, incr) in enumerate(steps):
        nxt = steps[i + 1][0] if i + 1 < len(steps) else final["action"]
        rep = {"old_action": facing, "action": nxt, "client_pos": seat, "hole_cards": hole, "board": []}
        if i + 1 == len(steps):
            rep.update(final)
        replies.append(rep)
    return replies


HAND_A = hand_script(0, ["8s", "8c"], [("b200", "c"), ("b200c/", "k"), ("b200c/kb200", "c"),
                                       ("b200c/kb200c/", "k"), ("b200c/kb200c/kb800", "c"),
                                       ("b200c/kb200c/kb800c/", "k")],
                     {"action": "b200c/kb200c/kb800c/kk", "board": ["Js", "Th", "6c", "3c", "Ac"],
                      "bot_hole_cards": ["Qc", "Jd"], "winnings": -1200, "won_pot": 0,
                      "baseline_winnings": -200, "session_num_hands": 1})
HAND_B = hand_script(1, ["7h", "2c"], [("", "c"), ("ck/k", "k"), ("ck/kk/k", "k"),
                                       ("ck/kk/kk/k", "k")],
                     {"action": "ck/kk/kk/kk", "board": ["Qd", "9c", "5h", "4s", "3d"],
                      "bot_hole_cards": ["As", "Ks"], "winnings": -100, "baseline_winnings": 0,
                      "session_num_hands": 2})


def test_play_hand_records_everything():
    t = ScriptTransport(HAND_A)
    c = SlumbotClient(transport=t, sleep=lambda s: None)
    rec = play_hand(c, CheckCallBot(), 1)
    assert [b.get("incr") for _, b in t.sent[1:]] == ["c", "k", "c", "k", "c", "k"]
    assert rec["winnings"] == -1200 and rec["computed_winnings"] == -1200 and rec["check"] == "ok"
    assert rec["streets"]["turn"] == ["me checks", "slumbot bets to 800", "me calls 800"]
    assert rec["position"] == "BB" and rec["showdown"] and rec["pot"] == 2400


def test_play_hand_detects_a_double_applied_action():
    bad = [dict(r) for r in HAND_B]
    bad[1]["old_action"] = "c"  # the server says our call came after an earlier call
    c = SlumbotClient(transport=ScriptTransport(bad), sleep=lambda s: None)
    with pytest.raises(Desync):
        play_hand(c, CheckCallBot(), 1)


def test_session_log_resume_and_token(tmp_path):
    log = str(tmp_path / "s.jsonl")
    t = ScriptTransport(HAND_A + HAND_B)
    c = SlumbotClient(transport=t, sleep=lambda s: None)
    out = run_session(c, CheckCallBot(), log, 1, echo=lambda m: None)
    assert out["hands"] == 1
    st = json.load(open(log + ".state.json"))
    assert st["token"] == "tok-secret-1" and st["in_hand"] is False
    assert "tok-secret-1" not in open(log).read()  # the token stays out of the shareable log

    with pytest.raises(SystemExit):  # an existing log needs --resume
        run_session(SlumbotClient(transport=t, sleep=lambda s: None), CheckCallBot(), log, 2,
                    echo=lambda m: None)
    c2 = SlumbotClient(transport=t, sleep=lambda s: None)
    out = run_session(c2, CheckCallBot(), log, 2, resume=True, echo=lambda m: None)
    assert out["hands"] == 2 and t.sent[len(HAND_A)][1] == {"token": "tok-secret-1"}  # same server session
    recs = read_log(log)
    assert [r["type"] for r in recs] == ["session", "hand", "session", "hand"]
    assert recs[3]["streets"]["preflop"] == ["me calls 50", "slumbot checks"]
    assert recs[3]["check"] == "ok" and recs[3]["position"] == "SB"


def test_resume_after_a_crash_mid_hand(tmp_path):
    log = str(tmp_path / "s.jsonl")
    with open(log, "w") as f:
        f.write(json.dumps({"type": "session", "bot": "checkcall"}) + "\n")
        f.write('{"type":"hand","hand":1,"cut')  # half-written line
    with open(log + ".state.json", "w") as f:
        json.dump({"token": "T0", "in_hand": True}, f)
    t = ScriptTransport(HAND_B)
    c = SlumbotClient(transport=t, sleep=lambda s: None)
    out = run_session(c, CheckCallBot(), log, 1, resume=True, echo=lambda m: None)
    assert out["hands"] == 1
    types = [r["type"] for r in read_log(log)]
    assert types == ["session", "note", "note", "session", "hand"]  # cut line, cut hand


def test_refused_token_starts_a_new_server_session(tmp_path):
    log = str(tmp_path / "s.jsonl")
    with open(log + ".state.json", "w") as f:
        json.dump({"token": "OLD", "in_hand": False}, f)
    t = ScriptTransport([{"error_msg": "Invalid token"}] + HAND_B)
    c = SlumbotClient(transport=t, sleep=lambda s: None)
    run_session(c, CheckCallBot(), log, 1, echo=lambda m: None)
    assert t.sent[0][1] == {"token": "OLD"} and t.sent[1][1] == {}
    assert any(r.get("event") == "new_token" for r in read_log(log))


def test_aborted_hand_is_logged_and_skipped(tmp_path):
    log = str(tmp_path / "s.jsonl")
    bad = [dict(r) for r in HAND_B]
    bad[1] = {"error_msg": "Not your turn"}
    t = ScriptTransport(bad + HAND_B)
    c = SlumbotClient(token="T", transport=t, sleep=lambda s: None)
    out = run_session(c, CheckCallBot(), log, 1, echo=lambda m: None)
    assert out["hands"] == 1
    assert [r["type"] for r in read_log(log)] == ["session", "aborted", "hand"]


# --- stats --------------------------------------------------------------------------------------

def test_rate_is_bb_per_100_with_standard_error():
    r = rate([100, -100, 100, -100])  # +1, -1, +1, -1 big blinds
    assert r.n == 4 and r.bb100 == 0
    assert r.se == pytest.approx(100 * (4 / 3) ** 0.5 / 2)
    assert rate([250, 250]).bb100 == 250  # 2.5 bb a hand


def test_summary_splits_by_seat():
    hands = [{"seat": 0, "winnings": -100, "baseline_winnings": 0, "check": "ok"},
             {"seat": 1, "winnings": 300, "baseline_winnings": 100, "check": "ok", "showdown": True}]
    s = summary(hands)
    assert s["raw"].bb100 == 100 and s["baseline"].bb100 == 50
    assert s["BB"].bb100 == -100 and s["SB"].bb100 == 300
    assert s["checks"]["ok"] == 2 and s["showdowns"] == 1
