"""A local stand-in for the GTO Wizard Benchmark API, for the tests and for dry runs without a key.

    python -m tools.gtowizard mock --port 8765

It copies the API's shapes from the public spec (https://researcher.gtowizard.com/openapi.json,
read 26 Nov 2026): the four endpoints the client uses, the ``X-API-Key`` header, the
``GameServiceResponse`` and ``PlayerStatistics`` objects, FastAPI-style errors
(``{"detail": ...}``, 422 for a badly formed request), the hand caps and their resets.

It is NOT GTO Wizard AI:

- the opponent picks actions at random (or follows the ``policy`` a test gives it);
- ``aivat_score`` is made up: a quarter of the raw result. Real AIVAT needs GTO Wizard AI's
  strategy and only their server can compute it;
- everything the spec doesn't say is a guess, marked "guess" below and listed in the README:
  the status codes for a bad key (401, 403), an illegal action (400), an unknown hand (404), a
  cap or rate limit (429 with ``Retry-After``); that seats alternate starting in the big blind;
  that the opponent's cards are shown after a showdown only.

Knobs let the tests bend it the way the real server might differ or fail: ``postflop_first``,
``trailing_rounds``, ``user_listed_first``, ``mutate`` (edit any outgoing state), ``rate_limit``,
``caps``, ``max_open_hands``, and ``fail()`` for errors before or after a request is applied.

Rules come from ``tools.slumbot.protocol`` (the same game), so the mock can't catch a rules
mistake that the client's parser shares. Only a real run can.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import random
import threading
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple

from ..slumbot.protocol import (BB_SEAT, BIG_BLIND, NUM_STREETS, SEAT_NAMES, SMALL_BLIND, STACK,
                                STREETS, ActionHistory, ActionParseError, chips_won, parse_action,
                                tokenize)
from .limits import PUBLISHED, WINDOWS, next_resets, utcnow, window_starts
from .protocol import GAME_NAME

DROP = "drop"  # a result that tells the HTTP layer to close the connection without answering
ENGINE_VERSION = 2
FAKE_AIVAT_SHARE = 0.25
DECK = [r + s for r in "23456789TJQKA" for s in "cdhs"]


def _rank(hole: List[str], board: List[str]) -> int:
    try:
        from treys import Card, Evaluator
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("the mock server needs treys to settle showdowns "
                           "(pip install -r requirements.txt)") from e
    return Evaluator().evaluate([Card.new(c) for c in board], [Card.new(c) for c in hole])


def random_policy(rng: random.Random) -> Callable[[ActionHistory], str]:
    """An opponent that checks, calls, bets, raises and folds at random. Nothing like GTO Wizard AI."""

    def size(h: ActionHistory, bounds: Tuple[int, int]) -> int:
        lo, hi = bounds
        if rng.random() < 0.05:
            return hi
        return min(hi, lo + rng.choice((0, 100, 300, h.pot)))

    def act(h: ActionHistory) -> str:
        bounds = h.raise_bounds()
        if h.can_check():
            return f"b{size(h, bounds)}" if bounds and rng.random() < 0.3 else "k"
        r = rng.random()
        if r < 0.2:
            return "f"
        if bounds and r > 0.85:
            return f"b{size(h, bounds)}"
        return "c"

    return act


@dataclass
class Fault:
    """An error to return for the next matching request(s)."""

    status: int = 503
    after: bool = False  # True: apply the request first, then fail (the reply is "lost")
    drop: bool = False  # close the connection without any reply
    method: Optional[str] = None
    path: Optional[str] = None  # a substring of the path
    times: int = 1
    skip: int = 0  # let this many matching requests through first
    retry_after: Optional[float] = None
    detail: str = "Service Unavailable"
    headers: Optional[Dict[str, str]] = None

    def matches(self, method: str, path: str) -> bool:
        if self.times <= 0 or (self.method is not None and self.method != method) \
                or (self.path is not None and self.path not in path):
            return False
        if self.skip > 0:
            self.skip -= 1
            return False
        return True


@dataclass
class _Hand:
    hand_id: int
    seat: int  # the user's seat
    user_cards: List[str]
    gto_cards: List[str]
    board: List[str]
    started: _dt.datetime
    action: str = ""
    finished: Optional[_dt.datetime] = None
    winnings: Optional[float] = None
    aivat: Optional[float] = None


class _User:
    def __init__(self, first_seat: int):
        self.hands: Dict[int, _Hand] = {}
        self.next_seat = first_seat


class MockBenchmark:
    """The benchmark's behaviour, in memory. ``handle`` answers one request."""

    def __init__(self, *, keys: Optional[List[str]] = None, seed: int = 0,
                 now: Callable[[], _dt.datetime] = utcnow,
                 caps: Optional[Dict[str, int]] = None,
                 policy: Optional[Callable[[ActionHistory], str]] = None,
                 first_seat: int = BB_SEAT, postflop_first: int = BB_SEAT,
                 max_open_hands: int = 20, rate_limit: Optional[Tuple[int, float]] = None,
                 ticker: Callable[[], float] = time.monotonic, trailing_rounds: bool = False,
                 user_listed_first: bool = True, mutate: Optional[Callable[[dict], None]] = None,
                 bot_name: str = "Mock bot", organization: str = "Mock"):
        self.keys = None if keys is None else set(keys)  # None: any key is accepted
        self.rng = random.Random(seed)
        self.now = now
        self.caps = dict(PUBLISHED, **(caps or {}))
        self.policy = policy or random_policy(self.rng)
        self.first_seat = first_seat
        self.postflop_first = postflop_first
        self.max_open_hands = max_open_hands
        self.rate_limit = rate_limit  # (requests, seconds), per key
        self.ticker = ticker
        self.trailing_rounds = trailing_rounds
        self.user_listed_first = user_listed_first
        self.mutate = mutate
        self.bot_name, self.organization = bot_name, organization
        self.faults: List[Fault] = []
        self.deals: List[Tuple[List[str], List[str], List[str]]] = []  # forced (user, gto, board)
        self.requests: List[Tuple[str, str]] = []  # (method, path) of every request, no headers
        self.applied: List[Tuple[int, str]] = []  # (hand id, action) of every action applied
        self._users: Dict[str, _User] = {}
        self._hits: Dict[str, List[float]] = {}
        self._next_id = 1001
        self._lock = threading.Lock()

    # --- for tests ---
    def fail(self, **kw) -> Fault:
        f = Fault(**kw)
        self.faults.append(f)
        return f

    def hands(self) -> List[_Hand]:
        return [h for u in self._users.values() for h in u.hands.values()]

    def count(self, method: str, path: str) -> int:
        return sum(1 for m, p in self.requests if m == method and path in p)

    # --- one request ---
    def handle(self, method: str, target: str, headers: Dict[str, str], body: bytes):
        """Returns ``(status, headers, json)`` or ``DROP``."""
        with self._lock:
            parts = urllib.parse.urlsplit(target)
            path = parts.path.rstrip("/") or "/"
            query = dict(urllib.parse.parse_qsl(parts.query))
            self.requests.append((method, path))
            fault = next((f for f in self.faults if f.matches(method, path)), None)
            if fault is not None:
                fault.times -= 1
                if not fault.after:
                    return self._fault(fault)
            result = self._route(method, path, query, {k.lower(): v for k, v in headers.items()}, body)
            return self._fault(fault) if fault is not None else result

    @staticmethod
    def _fault(f: Fault):
        if f.drop:
            return DROP
        hdrs = dict(f.headers or {})
        if f.retry_after is not None:
            hdrs["Retry-After"] = f"{f.retry_after:g}"
        return f.status, hdrs, {"detail": f.detail}

    def _route(self, method, path, query, headers, body):
        seg = [s for s in path.split("/") if s]
        routes = {("POST", "hands"): self._new_hand, ("GET", "hands/in-progress"): self._in_progress,
                  ("GET", "results"): self._results}
        handler = routes.get((method, "/".join(seg)))
        is_act = len(seg) == 3 and seg[0] == "hands" and seg[2] == "act"
        if handler is None and not is_act:
            known = {"hands", "hands/in-progress", "results"}
            return (405, {}, {"detail": "Method Not Allowed"}) if "/".join(seg) in known \
                else (404, {}, {"detail": "Not Found"})
        if is_act and method != "POST":
            return 405, {}, {"detail": "Method Not Allowed"}
        key = headers.get("x-api-key")
        if not key:
            return 403, {}, {"detail": "Not authenticated"}  # guess: FastAPI's reply without the header
        if self.keys is not None and key not in self.keys:
            return 401, {}, {"detail": "Invalid API key"}  # guess
        limited = self._rate_limited(key)
        if limited is not None:
            return limited
        user = self._users.setdefault(key, _User(self.first_seat))
        if is_act:
            return self._act(user, seg[1], body)
        return handler(user, query, body)

    def _rate_limited(self, key: str):
        if self.rate_limit is None:
            return None
        most, per = self.rate_limit
        t = self.ticker()
        hits = [x for x in self._hits.get(key, []) if x > t - per]
        if len(hits) >= most:
            self._hits[key] = hits
            wait = max(1, math.ceil(hits[0] + per - t))
            return 429, {"Retry-After": str(wait)}, {"detail": "Rate limit exceeded"}  # guess
        hits.append(t)
        self._hits[key] = hits
        return None

    # --- endpoints ---
    def _new_hand(self, user: _User, query, body):
        data, err = _json_object(body)
        if err:
            return err
        if "game_name" not in data:
            return _invalid(["body", "game_name"], "Field required", "missing")
        if data["game_name"] != GAME_NAME:
            return _invalid(["body", "game_name"], f"Input should be '{GAME_NAME}'", "literal_error")
        now = self.now()
        starts, resets = window_starts(now), next_resets(now)
        for w in WINDOWS:
            used = sum(1 for h in user.hands.values() if h.started >= starts[w])
            if used >= self.caps[w]:
                wait = max(1, math.ceil((resets[w] - now).total_seconds()))
                return 429, {"Retry-After": str(wait)}, {  # guess: status and wording
                    "detail": f"{w.capitalize()} hand limit reached ({self.caps[w]} hands)"}
        if sum(1 for h in user.hands.values() if h.finished is None) >= self.max_open_hands:
            return 429, {}, {"detail": "Too many hands in progress"}  # guess
        if self.deals:
            mine, theirs, board = (list(x) for x in self.deals.pop(0))
        else:
            deck = DECK[:]
            self.rng.shuffle(deck)
            mine, theirs, board = deck[:2], deck[2:4], deck[4:9]
        hand = _Hand(self._next_id, user.next_seat, mine, theirs, board, now)
        self._next_id += 1
        user.next_seat = 1 - user.next_seat  # positions alternate every hand
        user.hands[hand.hand_id] = hand
        self._advance(hand)
        return 200, {}, self._response(hand)

    def _act(self, user: _User, raw_id: str, body):
        try:
            hand_id = int(raw_id)
        except ValueError:
            return _invalid(["path", "hand_id"], "Input should be a valid integer", "int_parsing")
        data, err = _json_object(body)
        if err:
            return err
        action, amount = data.get("action"), data.get("amount")
        if action not in ("f", "k", "c", "b"):
            return _invalid(["body", "action"], "Input should be 'f', 'k', 'c' or 'b'", "literal_error")
        if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int)):
            return _invalid(["body", "amount"], "Input should be a valid integer", "int_type")
        if action == "b" and amount is None:
            return _invalid(["body"], "Value error, amount is required for a bet", "value_error")
        hand = user.hands.get(hand_id)
        if hand is None:
            return 404, {}, {"detail": "Hand not found"}  # guess
        if hand.finished is not None:
            return 400, {}, {"detail": "Hand is already over"}  # guess
        incr = f"b{amount}" if action == "b" else action
        try:
            hand.action = self._append(hand.action, incr)
        except ActionParseError as e:
            return 400, {}, {"detail": f"Illegal action: {e}"}  # guess
        self.applied.append((hand_id, incr))
        self._advance(hand)
        return 200, {}, self._response(hand)

    def _in_progress(self, user: _User, query, body):
        if "game_name" not in query:
            return _invalid(["query", "game_name"], "Field required", "missing")
        if query["game_name"] != GAME_NAME:
            return 200, {}, []
        return 200, {}, [self._response(h) for h in user.hands.values() if h.finished is None]

    def _results(self, user: _User, query, body):
        if "game_name" not in query:
            return _invalid(["query", "game_name"], "Field required", "missing")
        bounds = {}
        for name in ("start_date", "end_date"):
            if query.get(name):
                try:
                    t = _dt.datetime.fromisoformat(query[name].replace("Z", "+00:00"))
                except ValueError:
                    return _invalid(["query", name], "Input should be a valid datetime", "datetime_parsing")
                bounds[name] = t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)
        hands = [h for h in user.hands.values() if h.finished is not None
                 and query["game_name"] == GAME_NAME
                 and str(query.get("gto_wizard_version", ENGINE_VERSION)) == str(ENGINE_VERSION)
                 and ("start_date" not in bounds or h.finished >= bounds["start_date"])
                 and ("end_date" not in bounds or h.finished <= bounds["end_date"])]
        n = len(hands)
        chips = sum(h.winnings for h in hands)
        aivat = sum(h.aivat for h in hands)
        per100 = (lambda total: 100.0 * total / BIG_BLIND / n) if n else (lambda total: 0.0)
        se = 0.0
        if n > 1:
            mean = aivat / n
            sd = math.sqrt(sum((h.aivat - mean) ** 2 for h in hands) / (n - 1))
            se = 100.0 * sd / BIG_BLIND / math.sqrt(n)
        return 200, {}, {
            "bot_name": self.bot_name, "organization": self.organization,
            "gto_wizard_version": ENGINE_VERSION, "total_hands": n, "aivat_score": aivat,
            "bb_per_100": per100(chips), "chips_won_loss": chips,
            # In the real data, AIVAT = all hands chips - chance correction - action correction.
            "all_hands_chips_bb_per_100": per100(chips),
            "chance_correction_bb_per_100": per100(chips) - per100(aivat),
            "action_correction_bb_per_100": 0.0,
            "aivat_std_bb_per_100": se, "aivat_score_bb_per_100": per100(aivat)}

    # --- the game ---
    def _append(self, action: str, incr: str) -> str:
        new = action + incr
        h = parse_action(new, self.postflop_first)
        if not h.over and h.street > new.count("/"):
            new += "/"
        return new

    def _advance(self, hand: _Hand) -> None:
        """Let the opponent act until it is the user's turn or the hand is over, then settle."""
        while True:
            h = parse_action(hand.action, self.postflop_first)
            if h.over:
                if h.folded is not None:
                    won = chips_won(h, hand.seat)
                else:
                    won = chips_won(h, hand.seat, _rank(hand.user_cards, hand.board),
                                    _rank(hand.gto_cards, hand.board))
                hand.winnings = float(won)
                hand.aivat = FAKE_AIVAT_SHARE * won
                hand.finished = self.now()
                return
            if h.to_act == hand.seat:
                return
            hand.action = self._append(hand.action, self.policy(h))

    def _response(self, hand: _Hand) -> dict:
        h = parse_action(hand.action, self.postflop_first)
        user, gto = hand.seat, 1 - hand.seat
        our_turn = not h.over and h.to_act == user
        bounds = h.raise_bounds() if our_turn else None
        legal = []
        if our_turn:
            legal = [a for a, ok in (("f", h.can_fold()), ("c", h.can_call()), ("k", h.can_check()),
                                     ("b", bounds is not None)) if ok]
        tokens = ["_" if t == "/" else t for t in tokenize(hand.action)]
        if h.over and self.trailing_rounds:
            tokens += ["_"] * (NUM_STREETS - 1 - hand.action.count("/") if h.all_in else 1)
        players = [
            {"name": self.bot_name, "stack": float(STACK - h.contributed[user]),
             "position": SEAT_NAMES[user], "hole_cards": "".join(hand.user_cards)},
            {"name": "GTO Wizard AI", "stack": float(STACK - h.contributed[gto]),
             "position": SEAT_NAMES[gto],
             "hole_cards": "".join(hand.gto_cards) if h.over and h.folded is None else None}]
        if not self.user_listed_first:
            players.reverse()
        state = {
            "street": STREETS[h.street],
            "common_pot": float(h.pot if h.over else h.pot - sum(h.street_in)),
            "total_pot": float(h.pot),
            "board_cards": "".join(hand.board[:h.board_cards_needed()]),
            "is_hand_over": h.over,
            "player_to_act": "user" if our_turn else None,
            "players": players,
            "legal_actions": legal,
            "raise_range": None if bounds is None else {"min": float(bounds[0]), "max": float(bounds[1])},
            "action_history": tokens,
            "has_gto_wizard_folded": h.folded == gto,
            "winnings": hand.winnings,
            "aivat_score": hand.aivat,
        }
        if self.mutate is not None:
            self.mutate(state)
        return {"hand_id": hand.hand_id, "mock": True,
                "game": {"game_id": 1, "game_name": GAME_NAME, "game_format": "HUNL (mock)",
                         "starting_stack": float(STACK), "blinds": [float(SMALL_BLIND), float(BIG_BLIND)],
                         "stack_reset_per_hand": True},
                "game_state": state}


def _json_object(body: bytes):
    try:
        data = json.loads(body or b"null")
    except ValueError:
        return None, _invalid(["body"], "JSON decode error", "json_invalid")
    if not isinstance(data, dict):
        return None, _invalid(["body"], "Input should be a valid dictionary", "model_attributes_type")
    return data, None


def _invalid(loc: list, msg: str, kind: str):
    """A FastAPI validation error: HTTP 422 with a list under ``detail``."""
    return 422, {}, {"detail": [{"type": kind, "loc": loc, "msg": msg}]}


# --- over HTTP ------------------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    mock: MockBenchmark

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        result = self.mock.handle(self.command, self.path, dict(self.headers.items()), body)
        if result == DROP:
            self.close_connection = True
            return
        status, headers, payload = result
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = _serve

    def log_message(self, fmt, *args):  # quiet, and nothing from a request is ever printed
        pass


class MockServer:
    """``MockBenchmark`` behind a real HTTP server on this machine. Use as a context manager."""

    def __init__(self, mock: Optional[MockBenchmark] = None, host: str = "127.0.0.1", port: int = 0):
        self.mock = mock or MockBenchmark()
        handler = type("Handler", (_Handler,), {"mock": self.mock})
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._httpd.daemon_threads = True
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "MockServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> "MockServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
