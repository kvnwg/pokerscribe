"""Tests for tools/gtowizard against the local mock server (real HTTP on 127.0.0.1): reading the
game state, the client (key handling, errors, rate limits, retries), the session (any bot, the
log, resuming, replies lost on the way, the hand caps), the saved results and the CLI.

Nothing here may reach the real API: a fixture fails any test that opens a transport to a host
other than this machine. The key below is made up and only the mock knows it."""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse

import pytest

from tools.gtowizard import client as client_mod
from tools.gtowizard.__main__ import main
from tools.gtowizard.client import (KEY_ENV, AuthError, GTOWizardClient, MissingKey, NotFound,
                                    RateLimited, Rejected, Transport, Unsure, iso_utc)
from tools.gtowizard.limits import (PUBLISHED, Caps, CapReached, HandBudget, Ledger, next_resets,
                                    window_starts)
from tools.gtowizard.mock_server import MockBenchmark, MockServer
from tools.gtowizard.protocol import (ProtocolError, Reader, parse_history, read_state,
                                      slumbot_action, split_cards)
from tools.gtowizard.session import (NOTICE, format_summary, hands_in, read_log, results_path,
                                     run_session, save_results, summary, tidy_results)
from tools.slumbot.bots import Bot, CheckCallBot, Decision
from tools.slumbot.protocol import BB_SEAT, SB_SEAT

KEY = "made-up-key-for-the-mock-0123456789abcdefghij"
UTC = dt.timezone.utc
NEW_HAND = b'{"game_name": "HUNL 200BB"}'


def passive(h):  # an opponent that never bets and never folds
    return "k" if h.can_check() else "c"


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def __call__(self):
        return self.t


class Now:
    """A wall clock the test moves by hand."""

    def __init__(self, *when):
        self.t = dt.datetime(*when, tzinfo=UTC)

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch, tmp_path):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setenv("POKERSCRIBE_HOME", str(tmp_path / "home"))
    real_init = Transport.__init__

    def local_only(self, url=client_mod.API_URL, timeout=client_mod.TIMEOUT):
        real_init(self, url, timeout)
        host = urllib.parse.urlsplit(url).hostname
        assert host in ("127.0.0.1", "localhost"), f"a test tried to open {host}"

    monkeypatch.setattr(Transport, "__init__", local_only)


@pytest.fixture
def serve():
    """``serve(**mock_options)`` starts a mock server and returns ``(mock, url)``."""
    servers = []

    def start(**kw):
        kw.setdefault("keys", [KEY])
        server = MockServer(MockBenchmark(**kw)).start()
        servers.append(server)
        return server.mock, server.url

    yield start
    for s in servers:
        s.stop()


def make_client(url, clock=None, **kw):
    clock = clock or FakeClock()
    return GTOWizardClient(KEY, url=url, sleep=clock.sleep, clock=clock, **kw)


def budget_at(tmp_path, now=None, name="ledger.jsonl", **caps):
    kw = {} if now is None else {"now": now}
    return HandBudget(Ledger(str(tmp_path / name)), Caps(**caps), **kw)


def play(url, tmp_path, hands, *, bot=None, log="run.jsonl", clock=None, **kw):
    """One session with a fake clock. Returns (summary, client, echoed lines, log path)."""
    client = make_client(url, clock)
    lines = []
    path = str(tmp_path / log)
    kw.setdefault("budget", budget_at(tmp_path, kw.get("now")))
    out = run_session(client, bot or CheckCallBot(), path, hands, accept_terms=True,
                      echo=lines.append, **kw)
    return out, client, lines, path


def first_state(mock):
    """A new hand straight from the mock, without HTTP."""
    status, _, resp = mock.handle("POST", "/hands", {"X-API-Key": KEY}, NEW_HAND)
    assert status == 200
    return resp


def act(mock, resp, action, amount=None):
    body = json.dumps({"action": action, "amount": amount}).encode()
    status, _, out = mock.handle("POST", f"/hands/{resp['hand_id']}/act", {"X-API-Key": KEY}, body)
    assert status == 200, out
    return out


# --- test bots (the interface is tools.slumbot.bots.Bot, unchanged) -------------------------------

class Shover(Bot):
    name = "shover"

    def act(self, state):
        b = state.raise_bounds
        if b:
            return Decision("raise", b[1])
        return Decision("check") if state.legal()["check"] else Decision("call")


class MinRaiser(Bot):
    name = "minraiser"

    def act(self, state):
        b = state.raise_bounds
        if b and len(state.history.actions) < 6:
            return Decision("raise", b[0])
        return Decision("check") if state.legal()["check"] else Decision("call")


class Folder(Bot):
    name = "folder"

    def act(self, state):
        return Decision("fold") if state.legal()["fold"] else Decision("check")


class Killed(BaseException):
    """Stands in for the process dying: nothing in the session catches it."""


class Breaks(CheckCallBot):
    """Check/call that breaks at its n-th decision: raises ``error``, or returns ``instead``."""

    def __init__(self, at, error=None, instead=None):
        self.at, self.error, self.instead, self.n = at, error, instead, 0

    def act(self, state):
        self.n += 1
        if self.n == self.at:
            if self.error is not None:
                raise self.error
            return self.instead
        return super().act(state)


# --- reading the game state -----------------------------------------------------------------------

def test_cards():
    assert split_cards("AhKd3c") == ["Ah", "Kd", "3c"]
    assert split_cards("") == [] and split_cards(None) == []
    assert split_cards("10h9s") == ["Th", "9s"] and split_cards("ah kD") == ["Ah", "Kd"]
    assert split_cards(["Qd", "9s"]) == ["Qd", "9s"]
    for bad in ("Xx", "Ah9", "AhK"):
        with pytest.raises(ProtocolError):
            split_cards(bad)


def test_action_history_becomes_a_slumbot_string():
    # The example in the benchmark paper's prompt (arXiv 2603.23660, appendix).
    tokens = ["b200", "b800", "c", "_", "k", "b1600", "c", "_", "k", "k", "_", "k", "k"]
    assert slumbot_action(tokens) == "b200b800c/kb1600c/kk/kk"
    h = parse_history(tokens)
    assert h.over and h.showdown and h.contributed == [2400, 2400]
    assert [a.kind for a in h.streets[0]] == ["raise", "raise", "call"]
    assert slumbot_action(["b200.0", "c"]) == "b200c"  # chips may arrive as floats
    for bad in (["b200.5"], ["b"], ["x"], ["b-5"], ["bnan"]):
        with pytest.raises(ProtocolError):
            slumbot_action(bad)


def test_round_ends_after_the_hand_is_over_are_dropped():
    assert parse_history(["b200", "f", "_"]).folded == BB_SEAT
    assert parse_history(["b20000", "c"]).all_in
    assert parse_history(["b20000", "c", "_", "_", "_"]).all_in
    assert parse_history(["b20000", "c", "_"]).all_in
    assert parse_history(["c", "k", "_", "k", "k", "_", "k", "k", "_", "k", "k", "_"]).showdown
    assert parse_history(["c", "k", "_"]).street == 1  # a round end during the hand is kept
    with pytest.raises(ProtocolError):
        parse_history(["b200", "_"])  # a round can't end on an unanswered raise


def test_read_state_and_the_bot_state():
    mock = MockBenchmark(keys=[KEY], policy=passive)
    resp = first_state(mock)  # we are the big blind; the small blind limped
    v = read_state(resp)
    assert v.me == BB_SEAT and len(v.hole_cards) == 2 and v.opponent_cards is None
    assert v.our_turn and not v.over and not v.hard and not v.soft
    assert v.tokens == ["c"] and v.history.pot == 200 == v.total_pot
    s = v.bot_state(7)
    assert s.position == "BB" and s.street == "preflop" and s.hand_number == 7
    assert s.legal() == {"fold": False, "check": True, "call": False, "raise": (200, 20000)}
    assert s.is_legal(Decision("check")) and s.is_legal(Decision("raise", 200))
    assert not s.is_legal(Decision("fold")) and not s.is_legal(Decision("raise", 199))
    assert s.in_bb()["pot_bb"] == 2 and s.in_bb()["min_raise_to_bb"] == 2
    assert CheckCallBot().act(s) == Decision("check")

    resp = first_state(mock)  # seats alternate: now the small blind, first to act
    v = read_state(resp)
    assert v.me == SB_SEAT and v.tokens == [] and v.history.to_call() == 50
    assert set(v.legal) == {"f", "c", "b"}


def test_we_are_found_by_our_hole_cards_wherever_we_are_listed():
    mock = MockBenchmark(keys=[KEY], policy=passive, user_listed_first=False)
    resp = first_state(mock)
    assert resp["game_state"]["players"][0]["hole_cards"] is None
    v = read_state(resp)
    assert v.me == BB_SEAT and len(v.hole_cards) == 2
    resp["game_state"]["players"][0]["hole_cards"] = "AsAd"  # both shown: can't tell who we are
    with pytest.raises(ProtocolError):
        read_state(resp)
    assert read_state(resp, me=BB_SEAT).me == BB_SEAT  # unless an earlier state told us


def test_a_game_block_written_differently_is_noted_not_fatal():
    resp = first_state(MockBenchmark(keys=[KEY], policy=passive))
    assert read_state(resp).soft == []
    resp["game"].update(starting_stack=200, blinds=[0.5, 1])  # say, written in big blinds
    v = read_state(resp)
    assert len(v.soft) == 2 and not v.hard and v.bot_state().is_legal(Decision("check"))


def test_positions_and_masked_cards_are_read_leniently():
    resp = first_state(MockBenchmark(keys=[KEY], policy=passive))
    me, gto = resp["game_state"]["players"]
    me["position"], gto["position"], gto["hole_cards"] = "Big Blind", "btn", "????"
    v = read_state(resp)
    assert v.me == BB_SEAT and v.opponent_cards is None and not v.hard
    gto["position"] = "UTG"
    with pytest.raises(ProtocolError):
        read_state(resp)


def test_the_servers_word_on_legality_wins_and_differences_are_reported():
    resp = first_state(MockBenchmark(keys=[KEY], policy=passive))
    gs = resp["game_state"]
    gs["raise_range"] = {"min": 250.0, "max": 19000.5}
    gs["legal_actions"] = ["f", "k", "b"]
    v = read_state(resp)
    assert not v.hard and len(v.soft) == 2  # the fold rule and the raise range differ: noted
    s = v.bot_state()
    assert s.raise_bounds == (250, 19000)
    assert s.is_legal(Decision("fold")) and not s.is_legal(Decision("raise", 200))

    gs["total_pot"] = 201.0
    assert "total pot" in read_state(resp).hard[0]
    gs["total_pot"], gs["legal_actions"] = 200.0, ["f", "c", "b"]  # a call when we count a free check
    assert "legal actions" in read_state(resp).hard[0]
    gs["action_history"] = ["c", "?"]
    assert "unknown action" in read_state(resp).hard[0]


def test_reader_finds_out_who_acts_first_after_the_flop():
    for first, switched in ((BB_SEAT, False), (SB_SEAT, True)):
        mock = MockBenchmark(keys=[KEY], policy=passive, postflop_first=first)
        reader = Reader()
        resp = first_state(mock)  # we are the big blind
        assert not reader.read(resp).hard and not reader.confirmed  # before the flop: no way to tell
        resp = act(mock, resp, "k")
        v = reader.read(resp, BB_SEAT)
        assert v.tokens == (["c", "k", "_", "k"] if switched else ["c", "k", "_"])
        assert not v.hard and v.history.to_act == BB_SEAT
        assert reader.confirmed and reader.switched is switched and reader.postflop_first == first


# --- the client -----------------------------------------------------------------------------------

def test_key_comes_from_the_environment_and_is_never_shown(serve, monkeypatch):
    mock, url = serve()
    with pytest.raises(MissingKey) as e:
        GTOWizardClient(url=url)
    assert KEY_ENV in str(e.value)
    monkeypatch.setenv(KEY_ENV, "  " + KEY + "\n")  # stray whitespace from a paste is dropped
    c = GTOWizardClient(url=url, sleep=lambda s: None)
    assert c.new_hand()["hand_id"] == 1001  # the mock only answers the right key
    assert KEY not in repr(c) and KEY not in str(c)
    monkeypatch.setenv(KEY_ENV, "two words")
    with pytest.raises(MissingKey) as e:
        GTOWizardClient(url=url)
    assert "two words" not in str(e.value)


def test_a_refused_key_is_not_retried_and_not_echoed(serve):
    mock, url = serve()
    wrong = "wrong-key-0123456789-0123456789-0123456789"
    c = GTOWizardClient(wrong, url=url, sleep=lambda s: None)
    with pytest.raises(AuthError) as e:
        c.new_hand()
    assert wrong not in str(e.value) and KEY_ENV in str(e.value)
    assert len(mock.requests) == 1
    assert mock.handle("POST", "/hands", {}, NEW_HAND)[0] == 403  # no header at all


def test_key_only_travels_over_https_or_to_this_machine():
    with pytest.raises(ValueError):
        Transport("http://example.com")
    with pytest.raises(ValueError):
        Transport("ftp://127.0.0.1")
    Transport("http://127.0.0.1:1")
    Transport("http://localhost:1")


def test_redirects_are_not_followed(serve):
    mock, url = serve()
    mock.fail(status=307, headers={"Location": url + "/results?game_name=HUNL%20200BB"})
    with pytest.raises(Rejected) as e:
        make_client(url).results()
    assert e.value.status == 307 and len(mock.requests) == 1  # the key header went nowhere else


def test_the_four_endpoints(serve):
    mock, url = serve(policy=passive)
    c = make_client(url)
    hand = c.new_hand()
    assert hand["game"]["game_name"] == "HUNL 200BB"
    hid = hand["hand_id"]
    assert [h["hand_id"] for h in c.in_progress()] == [hid]
    after = c.act(hid, "b", 300)
    assert after["game_state"]["action_history"] == ["c", "b300", "c", "_"]
    assert mock.applied == [(hid, "b300")]
    with pytest.raises(ValueError):
        c.act(hid, "b")  # a bet without an amount never leaves this machine
    with pytest.raises(ValueError):
        c.act(hid, "k", 100)
    stats = c.results()
    assert stats["total_hands"] == 0 and "aivat_std_bb_per_100" in stats
    assert c.results(start=dt.datetime(2026, 1, 1, tzinfo=UTC), gto_wizard_version=2)["total_hands"] == 0
    assert iso_utc(dt.datetime(2026, 11, 26, 1, 2, 3, tzinfo=dt.timezone(dt.timedelta(hours=1)))) \
        == "2026-11-26T00:02:03Z"
    assert mock.requests == [("POST", "/hands"), ("GET", "/hands/in-progress"),
                             ("POST", f"/hands/{hid}/act"), ("GET", "/results"), ("GET", "/results")]


def test_errors_from_the_server(serve):
    mock, url = serve(policy=passive)
    c = make_client(url)
    hid = c.new_hand()["hand_id"]
    with pytest.raises(Rejected) as e:
        c.act(hid, "c")  # nothing to call
    assert e.value.status == 400 and "Illegal action" in str(e.value)
    with pytest.raises(Rejected):
        c.act(hid, "b", 150)  # below the minimum raise
    with pytest.raises(NotFound):
        c.act(999, "k")
    with pytest.raises(Rejected) as e:
        make_client(url, game="HUNL 100BB").new_hand()
    assert e.value.status == 422 and "body.game_name" in str(e.value)
    assert len(mock.requests) == 5 and mock.applied == []  # none of these was retried or applied
    mock.fail(status=404, method="GET", path="/results", detail="No results")
    assert c.results() is None


def test_text_from_the_server_is_scrubbed_of_the_key(serve):
    mock, url = serve()
    mock.fail(status=400, detail=f"bad request from key {KEY}")
    with pytest.raises(Rejected) as e:
        make_client(url).new_hand()
    assert KEY not in str(e.value) and "<api key>" in str(e.value)


def test_pacing_and_rate_limits(serve):
    clock = FakeClock()
    mock, url = serve(rate_limit=(3, 10.0), ticker=clock)
    c = make_client(url, clock, min_interval=0.5)
    for _ in range(3):
        c.results()
    assert clock.slept == [0.5, 0.5]  # our own pace: one request per min_interval
    c.results()  # the fourth in ten seconds: 429 with Retry-After, waited out, then served
    assert max(clock.slept) >= 9 and mock.count("GET", "/results") == 5
    assert make_client(url, min_interval=0).min_interval == client_mod.MIN_INTERVAL_FLOOR


def test_a_429_that_stays_is_given_up_on(serve):
    mock, url = serve()
    clock = FakeClock()
    mock.fail(status=429, times=99, detail="Rate limit exceeded")
    with pytest.raises(RateLimited):
        make_client(url, clock).new_hand()
    assert clock.slept == [2.0, 4.0, 8.0] and len(mock.requests) == 4  # three more tries, no more


def test_a_long_retry_after_is_a_cap_not_a_pause(serve):
    mock, url = serve()
    clock = FakeClock()
    mock.fail(status=429, retry_after=3600, detail="Daily hand limit reached")
    with pytest.raises(RateLimited) as e:
        make_client(url, clock).new_hand()
    assert e.value.retry_after == 3600 and "Daily hand limit" in str(e.value)
    assert clock.slept == [] and len(mock.requests) == 1


def test_gets_are_retried_with_backoff_posts_are_not(serve):
    mock, url = serve()
    clock = FakeClock()
    c = make_client(url, clock)
    mock.fail(status=503, times=2, method="GET")
    mock.fail(drop=True, method="GET")  # then a connection closed without a reply
    assert c.results()["total_hands"] == 0
    assert clock.slept[:3] == [2.0, 4.0, 8.0] and mock.count("GET", "/results") == 4

    mock.fail(status=502, method="POST")
    with pytest.raises(Unsure):
        c.new_hand()
    assert mock.requests.count(("POST", "/hands")) == 1  # the session decides what a silent POST means

    mock.fail(status=503, times=99, method="GET")
    with pytest.raises(Unsure):
        c.in_progress()
    assert mock.count("GET", "/hands/in-progress") == 1 + c.retries
    assert max(clock.slept) == c.max_backoff


# --- sessions -------------------------------------------------------------------------------------

def test_a_session_end_to_end(serve, tmp_path):
    mock, url = serve(seed=3)
    out, client, lines, log = play(url, tmp_path, 30)
    assert out["hands"] == 30 and out["stopped"] is None
    recs = read_log(log)
    assert [r["type"] for r in recs] == ["session"] + ["hand"] * 30 + ["results"]
    assert all(r["source"] == "gtowizard_benchmark" and r["use"] == "benchmark_only" for r in recs)
    assert recs[0]["notice"] == NOTICE and "never be used to train" in NOTICE
    hands = hands_in(recs)
    assert [h["hand_id"] for h in hands] == [m.hand_id for m in mock.hands()]
    assert all(m.finished is not None for m in mock.hands())
    assert sum(h["seat"] == BB_SEAT for h in hands) == 15  # seats alternate
    assert {h["check"] for h in hands} <= {"ok", "unchecked"} and out["checks"]["ok"] >= 25
    assert all(h["winnings"] == h["game_state"]["winnings"] for h in hands)
    assert [(h["hand_id"], d["incr"]) for h in hands for d in h["decisions"]] == mock.applied
    assert "gto_wizard" in json.dumps(hands[0]["streets"]) and "slumbot" not in json.dumps(hands)

    # The luck-adjusted results the API returned, saved in the log and next to it.
    saved = json.load(open(results_path(log)))
    assert saved == recs[-1] and saved["use"] == "benchmark_only"
    for part in (saved["all_time"], saved["this_log"]):
        api = part["api"]
        assert part["hands"] == 30 == api["total_hands"]
        assert part["aivat_bb_per_100"] == api["aivat_score_bb_per_100"]
        assert part["aivat_standard_error_bb_per_100"] == api["aivat_std_bb_per_100"] > 0
        lo, hi = part["aivat_ci95_bb_per_100"]
        assert lo == pytest.approx(api["aivat_score_bb_per_100"] - 1.96 * api["aivat_std_bb_per_100"])
        assert hi > lo
    assert saved["this_log"]["matches_log"] is True
    # The log's own numbers, from the per-hand aivat_score, agree with the server's.
    assert out["aivat"].bb100 == pytest.approx(saved["all_time"]["aivat_bb_per_100"])
    assert out["aivat"].se == pytest.approx(saved["all_time"]["aivat_standard_error_bb_per_100"])
    assert out["raw"].bb100 == pytest.approx(saved["all_time"]["raw_bb_per_100"])
    text = format_summary(out)
    assert "standard error" in text and "never train" in text and "MOCK SERVER" in text

    # The key is in no file and no line of output.
    for root, _, files in os.walk(tmp_path):
        for name in files:
            assert KEY not in open(os.path.join(root, name), encoding="utf-8").read(), name
    assert KEY not in "\n".join(lines) + text


def test_terms_must_be_accepted_before_anything_is_sent(serve, tmp_path):
    mock, url = serve()
    with pytest.raises(SystemExit) as e:
        run_session(make_client(url), CheckCallBot(), str(tmp_path / "x.jsonl"), 5,
                    budget=budget_at(tmp_path))
    assert "NEVER" in str(e.value) and "No human help" in str(e.value) and "public" in str(e.value)
    assert mock.requests == [] and not os.path.exists(tmp_path / "x.jsonl")


@pytest.mark.parametrize("bot", [Shover(), MinRaiser(), Folder()], ids=lambda b: b.name)
def test_any_bot_with_the_slumbot_interface_plays(serve, tmp_path, bot):
    mock, url = serve(seed=5, trailing_rounds=True, user_listed_first=False)
    out, _, _, log = play(url, tmp_path, 12, bot=bot)
    hands = hands_in(read_log(log))
    assert out["hands"] == 12 and out["stopped"] is None and out["fallbacks"] == 0
    assert out["checks"]["mismatch"] == 0 and out["checks"]["unreadable"] == 0
    assert [(h["hand_id"], d["incr"]) for h in hands for d in h["decisions"]] == mock.applied
    first = [h["decisions"][0]["incr"] if h["decisions"] else None for h in hands]
    if bot.name == "shover":
        assert "b20000" in first and any(h["history"]["preflop"][-1]["all_in"] for h in hands)
    if bot.name == "folder":
        assert all(h["winnings"] <= 0 or h["gto_folded"] or h["showdown"] for h in hands)
        assert "f" in first


def test_resume_after_a_crash_in_the_middle_of_a_hand(serve, tmp_path):
    mock, url = serve(policy=passive)
    ledger = str(tmp_path / "ledger.jsonl")
    with pytest.raises(Killed):  # dies at the 10th decision: hand 3, one action in
        play(url, tmp_path, 5, bot=Breaks(10, error=Killed()))
    log = str(tmp_path / "run.jsonl")
    with open(log, "a") as f:
        f.write('{"type":"hand","hand":3,"cut')  # and the crash cut a line in half
    assert len(hands_in(read_log(log))) == 2
    open_hand = [m.hand_id for m in mock.hands() if m.finished is None]
    assert open_hand == [1003] and json.load(open(log + ".state.json"))["open_hand"] == 1003

    with pytest.raises(SystemExit):  # an existing log needs --resume
        play(url, tmp_path, 5)
    with pytest.raises(SystemExit):  # and the same bot
        play(url, tmp_path, 5, bot=Shover(), resume=True)

    out, _, lines, _ = play(url, tmp_path, 5, resume=True)
    assert out["hands"] == 5 and out["stopped"] is None and out["resumed"] == 1
    assert "finishing 1 hand(s) left open first" in lines[0]
    recs = read_log(log)
    assert [r["type"] for r in recs] == ["session", "hand", "hand", "note", "session", "hand",
                                         "hand", "hand", "results"]
    hands = hands_in(recs)
    assert [h["hand_id"] for h in hands] == [1001, 1002, 1003, 1004, 1005]  # none twice, none skipped
    third = hands[2]
    assert third["resumed"] and [d["incr"] for d in third["decisions"]] == ["k", "k", "k"]  # after the crash
    assert third["action"] == "ck/kk/kk/kk" and third["check"] == "ok"  # the whole hand is in the record
    assert all(m.finished is not None for m in mock.hands()) and len(mock.hands()) == 5
    assert len(Ledger(ledger)) == 5  # the resumed hand was not counted twice
    assert recs[4]["event"] == "resume" and recs[4]["open_hands_found"] == 1


def test_a_hand_that_ended_between_the_reply_and_the_log_is_recorded_as_lost(serve, tmp_path):
    mock, url = serve(policy=passive)
    log = str(tmp_path / "run.jsonl")
    with open(log, "w") as f:
        f.write(json.dumps({"type": "session", "bot": "checkcall", "time": "2026-11-26T10:00:00+00:00"}) + "\n")
    with open(log + ".state.json", "w") as f:
        json.dump({"open_hand": 4242, "hands": 0}, f)
    out, _, _, _ = play(url, tmp_path, 2, resume=True)
    recs = read_log(log)
    assert [r["type"] for r in recs] == ["session", "lost", "session", "hand", "hand", "results"]
    assert recs[1]["hand_id"] == 4242 and out["lost"] == 1 and out["hands"] == 2
    assert "lost" in format_summary(out)


@pytest.mark.parametrize("applied,drop", [(True, False), (False, False), (True, True), (False, True)])
def test_an_action_whose_reply_is_lost_is_never_applied_twice(serve, tmp_path, applied, drop):
    mock, url = serve(policy=passive)
    mock.fail(status=503, after=applied, drop=drop, path="/act")  # the first action of the session
    out, client, _, log = play(url, tmp_path, 3)
    hands = hands_in(read_log(log))
    assert out["hands"] == 3 and out["stopped"] is None and out["checks"]["ok"] == 3
    sent = [(h["hand_id"], d["incr"]) for h in hands for d in h["decisions"]]
    assert sent == mock.applied and len(sent) == 12  # four checks or calls a hand, each applied once
    assert mock.count("POST", "/act") == 12 + (0 if applied else 1)  # sent again only if it wasn't applied
    assert mock.count("GET", "/hands/in-progress") == 2  # one at the start, one to find out


def test_a_hand_whose_final_reply_is_lost_is_logged_as_lost(serve, tmp_path):
    mock, url = serve(policy=passive)
    mock.fail(status=504, after=True, path="/act", skip=3)  # the action that ends hand 1
    out, _, lines, log = play(url, tmp_path, 3)
    recs = read_log(log)
    assert [r["type"] for r in recs] == ["session", "lost", "hand", "hand", "hand", "results"]
    assert recs[1]["hand_id"] == 1001 and [d["incr"] for d in recs[1]["decisions"]] == ["k", "k", "k"]
    assert recs[1]["unanswered"] == "k"  # the fourth check ended the hand; its reply never came
    assert out["hands"] == 3 and out["lost"] == 1 and out["stopped"] is None
    assert len(mock.hands()) == 4 and all(m.finished for m in mock.hands())
    assert len(Ledger(str(tmp_path / "ledger.jsonl"))) == 4  # the lost hand counts towards the caps
    # GTO Wizard's count includes the lost hand, and the saved results say the window isn't the log's.
    assert recs[-1]["this_log"]["hands"] == 4 and recs[-1]["this_log"]["matches_log"] is False
    assert "not this log's result alone" in format_summary(out)


@pytest.mark.parametrize("dealt", [True, False])
def test_an_unanswered_new_hand_request_never_leaves_a_hand_behind(serve, tmp_path, dealt):
    mock, url = serve(policy=passive)
    mock.fail(status=503, after=dealt, method="POST", path="/hands")
    out, _, _, log = play(url, tmp_path, 3)
    recs = read_log(log)
    assert out["hands"] == 3 and out["stopped"] is None
    assert len(mock.hands()) == 3 and all(m.finished for m in mock.hands())  # no orphan, no extra hand
    assert any(r.get("event") == "new_hand_unanswered" for r in recs)
    assert hands_in(recs)[0]["resumed"] is dealt  # the dealt hand was found in progress and played
    # The unanswered request is counted as a hand either way: exact if one was dealt, one too
    # many if not. Never one too few.
    assert len(Ledger(str(tmp_path / "ledger.jsonl"))) == (3 if dealt else 4)


def test_three_unanswered_new_hand_requests_stop_the_session(serve, tmp_path):
    mock, url = serve(policy=passive)
    mock.fail(status=503, times=99, method="POST", path="/hands")
    out, _, _, log = play(url, tmp_path, 3)
    assert out["stopped"]["reason"] == "error" and out["hands"] == 0
    assert mock.requests.count(("POST", "/hands")) == 3
    assert read_log(log)[-1]["event"] == "stopped"


def test_a_hand_waiting_for_the_opponent_is_polled_not_played_blind(serve, tmp_path):
    seen = []

    def thinking(state):  # the first reply shows GTO Wizard AI still to act
        seen.append(1)
        if len(seen) == 1:
            state.update(player_to_act="gto_wizard", legal_actions=[], raise_range=None)

    mock, url = serve(policy=passive, mutate=thinking)
    out, _, _, _ = play(url, tmp_path, 2)
    assert out["hands"] == 2 and out["stopped"] is None and out["fallbacks"] == 0
    assert mock.count("GET", "/hands/in-progress") == 2


def test_a_server_that_answers_without_applying_the_action_is_not_asked_forever(serve, tmp_path):
    mock, url = serve(policy=passive)
    first = {}

    def frozen(state):  # every reply shows the hand as it was at the start
        first.setdefault("state", dict(state))
        state.clear()
        state.update(first["state"])

    mock.mutate = frozen
    out, _, _, _ = play(url, tmp_path, 3)
    assert out["stopped"]["reason"] == "error" and "unchanged hand" in out["stopped"]["detail"]
    assert mock.count("POST", "/act") == 1


def test_betting_order_is_detected_and_noted(serve, tmp_path):
    mock, url = serve(seed=2, postflop_first=SB_SEAT)
    out, _, lines, log = play(url, tmp_path, 10)
    recs = read_log(log)
    assert out["hands"] == 10 and out["stopped"] is None and out["fallbacks"] == 0
    assert out["checks"]["mismatch"] == 0 and out["checks"]["unreadable"] == 0
    notes = [r for r in recs if r.get("event") == "betting_order"]
    assert len(notes) == 1 and "small blind acts first after the flop" in notes[0]["detail"]
    assert any(line.startswith("NOTE:") for line in lines)
    assert hands_in(recs)[-1]["postflop_first"] == "SB"


# --- no human help: a hand the bot can't play is finished by rule ---------------------------------

@pytest.mark.parametrize("bot,why", [
    (Breaks(2, error=RuntimeError("solver blew up")), "solver blew up"),
    (Breaks(2, instead=Decision("raise", 1)), "not legal"),
    (Breaks(2, instead=Decision("call")), "not legal"),
    (Breaks(2, instead=None), "failed"),
])
def test_a_failing_bot_gets_check_or_fold_and_the_session_stops(serve, tmp_path, monkeypatch, bot, why):
    def nobody(*a, **k):
        raise AssertionError("a human was asked")

    monkeypatch.setattr("builtins.input", nobody)
    mock, url = serve(policy=lambda h: "b200" if h.street == 1 and h.can_check() else passive(h))
    out, _, lines, log = play(url, tmp_path, 5, bot=bot)
    hand = hands_in(read_log(log))[0]
    assert out["hands"] == 1 and out["stopped"]["reason"] == "fallback" and out["fallbacks"] == 1
    assert why in hand["fallback"] and why in out["stopped"]["detail"]
    # Preflop check by the bot, then by rule: check the flop, fold to the bet.
    assert [(d["incr"], d.get("fallback", False)) for d in hand["decisions"]] == \
        [("k", False), ("k", True), ("f", True)]
    assert hand["winnings"] == -100 and hand["check"] == "ok"
    assert all(m.finished is not None for m in mock.hands())  # nothing left hanging


def test_an_action_the_server_refuses_falls_back_too(serve, tmp_path):
    def lower_minimum(state):  # the server advertises a smaller minimum raise than it enforces
        if state["raise_range"]:
            state["raise_range"]["min"] -= 50

    mock, url = serve(policy=passive, mutate=lower_minimum)
    out, _, _, log = play(url, tmp_path, 5, bot=MinRaiser())
    hand = hands_in(read_log(log))[0]
    assert out["stopped"]["reason"] == "fallback" and "the server refused b150" in hand["fallback"]
    assert any("raise range" in n for n in hand["notes"])  # the difference was noted before acting
    assert [d["incr"] for d in hand["decisions"]] == ["k", "k", "k", "k"] and mock.applied[0][1] == "k"


def test_a_state_that_disagrees_with_our_parse_is_not_shown_to_the_bot(serve, tmp_path):
    def wrong_pot(state):
        state["total_pot"] += 50

    mock, url = serve(policy=passive, mutate=wrong_pot)
    asked = []

    class Watching(CheckCallBot):
        def act(self, state):
            asked.append(state)
            return super().act(state)

    out, _, _, log = play(url, tmp_path, 5, bot=Watching())
    hand = hands_in(read_log(log))[0]
    assert asked == [] and out["stopped"]["reason"] == "fallback"
    assert "total pot" in hand["fallback"] and all(d["fallback"] for d in hand["decisions"])


# --- the hand caps --------------------------------------------------------------------------------

def test_windows_reset_at_midnight_utc_on_monday_and_on_the_first():
    now = dt.datetime(2026, 11, 26, 13, 45, tzinfo=UTC)  # a Thursday
    assert window_starts(now) == {"day": dt.datetime(2026, 11, 26, tzinfo=UTC),
                                  "week": dt.datetime(2026, 11, 23, tzinfo=UTC),
                                  "month": dt.datetime(2026, 11, 1, tzinfo=UTC)}
    assert next_resets(now) == {"day": dt.datetime(2026, 11, 27, tzinfo=UTC),
                                "week": dt.datetime(2026, 11, 30, tzinfo=UTC),
                                "month": dt.datetime(2026, 12, 1, tzinfo=UTC)}
    evening_in_la = dt.datetime(2026, 11, 26, 20, 0, tzinfo=dt.timezone(dt.timedelta(hours=-8)))
    assert window_starts(evening_in_la)["day"] == dt.datetime(2026, 11, 27, tzinfo=UTC)
    assert next_resets(dt.datetime(2026, 12, 31, 23, tzinfo=UTC))["month"] == dt.datetime(2027, 1, 1, tzinfo=UTC)
    monday = dt.datetime(2026, 11, 30, 0, 0, tzinfo=UTC)
    assert window_starts(monday)["week"] == monday


def test_caps_can_be_lowered_but_not_raised():
    assert Caps().day == 10_000 and Caps().week == 25_000 and Caps().month == 50_000
    assert Caps(day=100).day == 100
    for bad in ({"day": 10_001}, {"week": 25_001}, {"month": 50_001}, {"day": -1}):
        with pytest.raises(ValueError):
            Caps(**bad)
    with pytest.raises(SystemExit):
        main(["limits", "--offline", "--day-cap", "20000"])


def test_ledger_counts_hands_once_and_is_shared(tmp_path):
    now = Now(2026, 11, 26, 12)
    path = str(tmp_path / "ledger.jsonl")
    a, b = Ledger(path), Ledger(path)  # two sessions on one machine
    assert a.add(1, now()) and not a.add(1, now()) and a.add(None, now()) and a.add(None, now())
    assert b.add(2, now()) and not b.add(1, now())
    budget = HandBudget(a, Caps(day=5, week=5, month=6), now)
    assert budget.used() == {"day": 4, "week": 4, "month": 4} and budget.allowance() == 1
    budget.check()
    b.add(3, now())
    with pytest.raises(CapReached) as e:
        budget.check()
    assert e.value.window == "day" and "2026-11-27 00:00 UTC" in str(e.value)
    with open(path, "a") as f:
        f.write('{"time": "2026-11-26T12:0')  # a line cut by a crash is skipped, not fatal
    assert len(Ledger(path)) == 5
    assert KEY not in open(path).read()


def test_the_servers_count_is_used_when_it_is_larger(tmp_path):
    now = Now(2026, 11, 26, 12)
    budget = budget_at(tmp_path, now, day=100)
    budget.ledger.add(1, now() - dt.timedelta(minutes=1))
    budget.set_server_counts({"day": 40, "week": 60, "month": 90}, now(), open_hands=2)
    assert budget.used() == {"day": 42, "week": 62, "month": 92}
    now.t += dt.timedelta(minutes=5)
    budget.ledger.add(2, now())
    assert budget.used()["day"] == 43 and budget.left()["day"] == 57  # the server's count plus ours since
    now.t = dt.datetime(2026, 11, 27, 0, 1, tzinfo=UTC)  # a new day: yesterday's count no longer applies
    assert budget.used() == {"day": 0, "week": 63, "month": 93}


@pytest.mark.parametrize("window,still_closed,open_again", [
    ("day", (2026, 11, 26, 23, 59), (2026, 11, 27, 0, 0)),
    ("week", (2026, 11, 29, 23, 59), (2026, 11, 30, 0, 0)),  # Sunday night, then Monday
    ("month", (2026, 11, 30, 23, 59), (2026, 12, 1, 0, 0)),
])
def test_a_session_never_goes_over_a_cap(serve, tmp_path, window, still_closed, open_again):
    now = Now(2026, 11, 26, 12)  # Thursday noon UTC
    mock, url = serve(policy=passive, now=now)
    kw = dict(now=now, budget=budget_at(tmp_path, now, **{window: 4}))
    out, _, lines, log = play(url, tmp_path, 7, **kw)
    assert out["hands"] == 4 and out["stopped"]["reason"] == "cap"
    assert f"the {window} cap is reached: 4 of 4" in out["stopped"]["detail"]
    assert mock.requests.count(("POST", "/hands")) == 4  # the fifth hand was never asked for

    now.t = dt.datetime(*still_closed, tzinfo=UTC)
    out, _, _, _ = play(url, tmp_path, 7, resume=True, **kw)
    assert out["hands"] == 4 and out["stopped"]["reason"] == "cap" and mock.requests.count(("POST", "/hands")) == 4

    now.t = dt.datetime(*open_again, tzinfo=UTC)
    out, _, _, _ = play(url, tmp_path, 7, resume=True, **kw)
    assert out["hands"] == 7 and out["stopped"] is None and mock.requests.count(("POST", "/hands")) == 7
    session_lines = [r for r in read_log(log) if r["type"] == "session"]
    assert session_lines[0]["caps"][window] == 4 and session_lines[1]["left"][window] == 0
    assert session_lines[2]["left"][window] == 4


def test_hands_played_elsewhere_count_through_the_server(serve, tmp_path):
    now = Now(2026, 11, 26, 12)
    mock, url = serve(policy=passive, now=now)
    play(url, tmp_path, 4, now=now, log="laptop.jsonl",
         budget=budget_at(tmp_path, now, name="laptop_ledger.jsonl"))
    # Another machine: an empty ledger, the same key. The server knows about the four hands.
    out, _, lines, _ = play(url, tmp_path, 9, now=now, log="desktop.jsonl",
                            budget=budget_at(tmp_path, now, name="desktop_ledger.jsonl", day=6))
    assert "2 this day" in lines[0]
    assert out["hands"] == 2 and out["stopped"]["reason"] == "cap" and mock.requests.count(("POST", "/hands")) == 6


def test_without_the_servers_count_the_ledger_alone_is_used_and_it_says_so(serve, tmp_path):
    now = Now(2026, 11, 26, 12)
    mock, url = serve(policy=passive, now=now)
    mock.fail(status=422, method="GET", path="/results", detail="start_date: not understood")
    out, _, lines, log = play(url, tmp_path, 5, now=now, budget=budget_at(tmp_path, now, day=2))
    assert out["hands"] == 2 and out["stopped"]["reason"] == "cap"
    assert any(line.startswith("NOTE: the server's own hand count could not be read") for line in lines)
    assert any(r.get("event") == "no_server_count" for r in read_log(log))


def test_a_cap_enforced_by_the_server_stops_the_session_quietly(serve, tmp_path):
    now = Now(2026, 11, 26, 12)
    mock, url = serve(policy=passive, now=now, caps={"day": 3})  # their limit is lower than we think
    clock = FakeClock()
    out, _, _, log = play(url, tmp_path, 8, now=now, clock=clock)
    assert out["hands"] == 3 and out["stopped"]["reason"] == "rate_limited"
    assert "Day hand limit reached" in out["stopped"]["detail"]
    assert mock.requests.count(("POST", "/hands")) == 4 and max(clock.slept) < 60  # one refusal, no hammering
    assert read_log(log)[-1]["type"] == "results"  # what was played is still reported


# --- results and stats ----------------------------------------------------------------------------

def test_tidy_results_names_the_standard_error_honestly():
    api = {"total_hands": 50000, "aivat_score_bb_per_100": 2.0789067194, "bb_per_100": 4.17946,
           "aivat_std_bb_per_100": 0.9502605182158286}  # the leaderboard's top row on 26 Nov 2026
    t = tidy_results(api)
    assert t["aivat_standard_error_bb_per_100"] == api["aivat_std_bb_per_100"] and t["api"] is api
    assert t["aivat_ci95_bb_per_100"][0] == pytest.approx(0.2164, abs=1e-4)  # what the leaderboard ranks by
    assert tidy_results(None) is None and tidy_results({}) is None


def test_results_command_and_stats_without_a_network(serve, tmp_path, capsys, monkeypatch):
    mock, url = serve(seed=1)
    monkeypatch.setenv(KEY_ENV, KEY)
    log, ledger = str(tmp_path / "cli.jsonl"), str(tmp_path / "cli_ledger.jsonl")
    base = ["--url", url]
    assert main(["play", "--hands", "2", "--log", log, "--bot", "checkcall", "--ledger", ledger,
                 "--min-interval", "0.1"] + base) == 2  # no --accept-terms: nothing happens
    assert "NEVER" in capsys.readouterr().err and mock.requests == []

    assert main(["play", "--hands", "2", "--log", log, "--bot", "checkcall", "--ledger", ledger,
                 "--min-interval", "0.1", "--accept-terms"] + base) == 0
    played = capsys.readouterr().out
    assert "2 hands against GTO Wizard AI" in played and "requests" in played

    assert main(["results", log] + base) == 0
    assert [r["type"] for r in read_log(log)][-2:] == ["results", "results"]
    assert main(["limits", "--ledger", ledger] + base) == 0
    assert main(["limits", "--ledger", ledger, "--offline"]) == 0
    monkeypatch.delenv(KEY_ENV)
    before = len(mock.requests)
    assert main(["stats", log]) == 0  # no key, no request
    assert main(["play", "--hands", "4", "--log", log, "--bot", "checkcall", "--ledger", ledger,
                 "--accept-terms", "--resume"] + base) == 1
    out = capsys.readouterr()
    assert KEY_ENV in out.err and len(mock.requests) == before
    assert "this day:" in out.out and "2 used of 10,000" in out.out and "standard error" in out.out
    assert KEY not in out.out + out.err + played


def test_summary_of_an_empty_log(tmp_path):
    s = summary(read_log(str(tmp_path / "nothing.jsonl")))
    assert s["hands"] == 0 and s["aivat"] is None and s["results"] is None
    assert "0 hands" in format_summary(s)


def test_save_results_when_the_server_has_nothing(serve, tmp_path):
    mock, url = serve()
    log = str(tmp_path / "empty.jsonl")
    mock.fail(status=404, method="GET", path="/results")
    snap = save_results(make_client(url), log)
    assert snap["all_time"] is None and read_log(log)[-1]["type"] == "results"
