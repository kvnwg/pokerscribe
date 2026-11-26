"""A small HTTPS client for the Slumbot API, with polite rate limiting.

Endpoints (POST, JSON body, ``Content-Type: application/json``):

- ``/slumbot/api/login`` ``{"username", "password"}`` -> ``{"token"}``. Only needed for the
  leaderboards; the account is registered on the website first.
- ``/slumbot/api/new_hand`` ``{"token"?}`` -> the hand state. The token may be missing on the
  very first request; the response then carries one.
- ``/slumbot/api/act`` ``{"token", "incr"}`` -> the hand state after our action and Slumbot's reply.

A hand state response has ``old_action``, ``action``, ``client_pos``, ``hole_cards``, ``board`` and,
sometimes, a new ``token``. At the end of the hand it also has ``winnings`` (our result in chips),
``won_pot``, ``baseline_winnings`` (our result minus what Slumbot made playing itself on the same
cards in our seat), ``session_num_hands``, ``session_total``, ``session_baseline_total`` and, after
a showdown, ``bot_hole_cards``. Errors come back as ``{"error_msg"}``, usually with status 200.

Only the standard library is used, so the client runs anywhere the app's Python does.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from .protocol import ActionHistory, parse_action

HOST = "https://slumbot.com"
USER_AGENT = "PokerScribe-research-client/1.0 (python urllib)"
MIN_INTERVAL_FLOOR = 0.2  # never faster than five requests a second, whatever is asked


class SlumbotError(RuntimeError):
    """Slumbot answered with an error, or no usable answer came back."""


class SlumbotRejected(SlumbotError):
    """Slumbot returned ``error_msg`` (an illegal action, a bad token, a failed login)."""


class Transport:
    """Sends one JSON POST and returns the parsed body. Swappable for tests."""

    def __init__(self, host: str = HOST, timeout: float = 30.0):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._ctx = _ssl_context()

    def post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.host + path, data=data, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and "error_msg" in parsed:
                return parsed
            raise _HTTPStatus(e.code, e.headers.get("Retry-After"), raw[:200]) from e
        try:
            parsed = json.loads(raw)
        except ValueError as e:
            raise SlumbotError(f"not JSON from {path}: {raw[:200]!r}") from e
        if not isinstance(parsed, dict):
            raise SlumbotError(f"unexpected reply from {path}: {parsed!r}")
        return parsed


class _HTTPStatus(Exception):
    def __init__(self, code: int, retry_after: Optional[str], body: bytes):
        super().__init__(f"HTTP {code}: {body!r}")
        self.code = code
        self.retry_after = retry_after


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:  # python.org builds on macOS ship without system certificates; certifi fills the gap
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


class SlumbotClient:
    """Login, new hand and act, one request at a time, at most one per ``min_interval`` seconds.

    Network errors, timeouts, HTTP 429 and 5xx are retried with exponential backoff
    (``retries`` times, starting at ``backoff`` seconds, honouring ``Retry-After``).
    ``new_hand`` is safe to retry. ``act`` is retried too, and the caller checks the reply's
    ``old_action`` against what it expected, which shows whether an earlier attempt already
    went through (see ``session.play_hand``).
    """

    def __init__(self, token: Optional[str] = None, *, transport: Optional[Transport] = None,
                 min_interval: float = 1.0, retries: int = 4, backoff: float = 2.0,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.token = token
        self.transport = transport or Transport()
        self.min_interval = max(MIN_INTERVAL_FLOOR, float(min_interval))
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.requests = 0

    # --- the three endpoints ---
    def login(self, username: str, password: str) -> str:
        r = self._call("/slumbot/api/login", {"username": username, "password": password})
        token = r.get("token")
        if not token:
            raise SlumbotError("login returned no token")
        self.token = token
        return token

    def new_hand(self) -> dict:
        return self._call("/slumbot/api/new_hand", {"token": self.token} if self.token else {})

    def act(self, incr: str) -> dict:
        if not self.token:
            raise SlumbotError("act needs a token; call new_hand first")
        return self._call("/slumbot/api/act", {"token": self.token, "incr": incr})

    # --- plumbing ---
    def _call(self, path: str, body: dict) -> dict:
        delay = self.backoff
        for attempt in range(self.retries + 1):
            self._wait_turn()
            try:
                r = self.transport.post(path, body)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, _HTTPStatus) as e:
                retryable = not isinstance(e, _HTTPStatus) or e.code == 429 or e.code >= 500
                if not retryable or attempt == self.retries:
                    raise SlumbotError(f"{path} failed: {e}") from e
                wait = delay
                if isinstance(e, _HTTPStatus) and e.retry_after:
                    try:
                        wait = max(wait, float(e.retry_after))
                    except ValueError:
                        pass
                self._sleep(wait)
                delay *= 2
                continue
            if "error_msg" in r:
                raise SlumbotRejected(f"{path}: {r['error_msg']}")
            if r.get("token"):
                self.token = r["token"]
            return r
        raise SlumbotError(f"{path} failed")  # not reached

    def _wait_turn(self) -> None:
        now = self._clock()
        if self._last is not None:
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                self._sleep(gap)
                now = self._clock()
        self._last = now
        self.requests += 1


def history_of(response: dict) -> ActionHistory:
    return parse_action(response.get("action", ""))
