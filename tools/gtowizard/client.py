"""An HTTPS client for the GTO Wizard Benchmark API ("Ruse AI Researcher API"), with polite pacing.

Endpoints used (spec: https://researcher.gtowizard.com/openapi.json, read 26 Nov 2026):

- ``POST /hands`` ``{"game_name": "HUNL 200BB"}`` -> a new hand's state.
- ``POST /hands/{hand_id}/act`` ``{"action": "f"|"k"|"c"|"b", "amount": int|null}`` -> the state
  after our action and GTO Wizard AI's reply. A bet's amount is the total for the betting round.
- ``GET /hands/in-progress?game_name=...`` -> our unfinished hands and their states.
- ``GET /results?game_name=...[&start_date=&end_date=&gto_wizard_version=]`` -> our statistics,
  with the AIVAT win rate and its standard error (which the API calls ``aivat_std_bb_per_100``).

The API key
-----------
The key is read from the environment variable ``GTOWIZARD_API_KEY`` and sent in the ``X-API-Key``
header, nowhere else. It is never written to a log, a state file, an error message or the
terminal: the client keeps it in a private attribute, cuts it out of any text that comes back
from the server before that text is shown, refuses plain http (except to this machine, for the
mock server) and does not follow redirects, so the header can't be sent to another host.

Failures
--------
- 401 and 403: ``AuthError``. Not retried.
- 429: the request was refused, so it is safe to send again. The client waits (``Retry-After``
  when given) and tries a few times, then raises ``RateLimited``. A long ``Retry-After`` raises
  at once: that is a hand cap, not a burst limit, and waiting it out in a loop would be rude.
- Other 4xx: ``Rejected`` (``NotFound`` for 404). Not retried.
- No answer, a timeout, or 5xx (the reference client treats 502, 503 and 504 as "engine busy"):
  ``Unsure``. A GET is retried with exponential backoff. A POST is **not** retried here, because
  the server may have applied it: sending "check" twice could check the next street too. The
  session looks at ``/hands/in-progress`` to find out what happened, then decides.

Only the standard library is used.
"""
from __future__ import annotations

import datetime as _dt
import http.client
import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional

from ..slumbot.client import _ssl_context
from .protocol import GAME_NAME

API_URL = "https://researcher.gtowizard.com"
KEY_ENV = "GTOWIZARD_API_KEY"
KEY_HEADER = "X-API-Key"
USER_AGENT = "PokerScribe-benchmark-client/1.0 (python urllib)"
TIMEOUT = 180.0  # seconds; the reference client's value. GTO Wizard AI computes its reply live.
MIN_INTERVAL_FLOOR = 0.1  # never faster than ten requests a second, whatever is asked
HIDDEN = "<api key>"


class GTOWizardError(RuntimeError):
    """The API answered with an error, or no usable answer came back."""


class MissingKey(GTOWizardError):
    """No API key in the environment."""


class AuthError(GTOWizardError):
    """The server refused the API key (401 or 403)."""


class Rejected(GTOWizardError):
    """The server understood the request and refused it (an illegal action, a bad field)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class NotFound(Rejected):
    """404: no such hand, or nothing to report."""


class RateLimited(GTOWizardError):
    """429, still, after waiting: a rate limit or a hand cap on the server's side."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class Unsure(GTOWizardError):
    """No usable answer (network error, timeout, 5xx). A POST may or may not have been applied."""


def load_api_key(env: Optional[Mapping[str, str]] = None) -> str:
    """The key from ``GTOWIZARD_API_KEY``. The value is never echoed, not even when it is wrong."""
    env = os.environ if env is None else env
    return check_key(env.get(KEY_ENV, ""))


def check_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        raise MissingKey(f"no API key: set the environment variable {KEY_ENV} "
                         "(see tools/gtowizard/README.md, \"Getting access\")")
    if any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise MissingKey(f"{KEY_ENV} holds spaces or characters that can't go in an HTTP header; "
                         "check how it was pasted")
    return key


def iso_utc(t: _dt.datetime) -> str:
    """A date-time for the query string, in UTC: ``2026-11-26T00:00:00Z``."""
    if t.tzinfo is None:
        raise ValueError("a date needs a time zone")
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the API key header to wherever it points. Don't follow any."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class Reply:
    status: int
    headers: Mapping[str, str]
    body: Any  # parsed JSON, or None when the body isn't JSON
    text: str  # the start of the raw body, for error messages


class Transport:
    """Sends one request and returns the reply, whatever its status. Swappable for tests."""

    def __init__(self, url: str = API_URL, timeout: float = TIMEOUT):
        parts = urllib.parse.urlsplit(url)
        local = _is_loopback(parts.hostname)
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise ValueError(f"refusing {url!r}: the API key only travels over https "
                             "(plain http is accepted for a mock server on this machine)")
        self.url = url.rstrip("/")
        self.timeout = timeout
        handlers: list = [_NoRedirect()]
        if parts.scheme == "https":
            handlers.append(urllib.request.HTTPSHandler(context=_ssl_context()))
        if local:
            handlers.append(urllib.request.ProxyHandler({}))  # never through a proxy to this machine
        self._opener = urllib.request.build_opener(*handlers)

    def send(self, method: str, path: str, *, params: Optional[dict] = None,
             body: Optional[dict] = None, headers: Optional[dict] = None) -> Reply:
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                status, hdrs, raw = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, hdrs, raw = e.code, e.headers, e.read()
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return Reply(status, {k.lower(): v for k, v in (hdrs.items() if hdrs else [])}, parsed,
                     raw[:300].decode("utf-8", "replace"))


class GTOWizardClient:
    """New hand, act, hands in progress and results: one request at a time, at most one per
    ``min_interval`` seconds. See the module docstring for what is retried and what is not."""

    def __init__(self, api_key: Optional[str] = None, *, url: str = API_URL,
                 transport: Optional[Transport] = None, game: str = GAME_NAME,
                 min_interval: float = 0.5, retries: int = 6, rate_limit_retries: int = 3,
                 backoff: float = 2.0, max_backoff: float = 32.0, max_retry_after: float = 120.0,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self._key = load_api_key() if api_key is None else check_key(api_key)
        self.transport = transport or Transport(url)
        self.url = getattr(self.transport, "url", url)
        self.game = game
        self.min_interval = max(MIN_INTERVAL_FLOOR, float(min_interval))
        self.retries = retries
        self.rate_limit_retries = rate_limit_retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.max_retry_after = max_retry_after
        self.sleep = sleep
        self._clock = clock
        self._last = None
        self.requests = 0

    def __repr__(self) -> str:
        return f"GTOWizardClient({self.url!r}, key=<hidden>)"

    # --- the four endpoints ---
    def new_hand(self) -> dict:
        return self._call("POST", "/hands", body={"game_name": self.game})

    def act(self, hand_id: int, action: str, amount: Optional[int] = None) -> dict:
        if action not in ("f", "k", "c", "b"):
            raise ValueError(f"unknown action {action!r}")
        if (action == "b") != (amount is not None):
            raise ValueError("a bet needs an amount, and only a bet takes one")
        return self._call("POST", f"/hands/{int(hand_id)}/act",
                          body={"action": action, "amount": None if amount is None else int(amount)})

    def in_progress(self) -> List[dict]:
        r = self._call("GET", "/hands/in-progress", params={"game_name": self.game})
        if not isinstance(r, list):
            raise GTOWizardError(f"/hands/in-progress returned {type(r).__name__}, not a list")
        return r

    def results(self, start: Optional[_dt.datetime] = None, end: Optional[_dt.datetime] = None,
                gto_wizard_version: Optional[int] = None) -> Optional[dict]:
        """Our statistics (``PlayerStatistics`` in the spec), or None when the server has none (404)."""
        params: dict = {"game_name": self.game}
        if start is not None:
            params["start_date"] = iso_utc(start)
        if end is not None:
            params["end_date"] = iso_utc(end)
        if gto_wizard_version is not None:
            params["gto_wizard_version"] = int(gto_wizard_version)
        try:
            r = self._call("GET", "/results", params=params)
        except NotFound:
            return None
        if not isinstance(r, dict):
            raise GTOWizardError(f"/results returned {type(r).__name__}, not an object")
        return r

    # --- plumbing ---
    def scrub(self, text: object) -> str:
        """``text`` with the API key cut out, in case a server or a library echoed it."""
        return str(text).replace(self._key, HIDDEN)

    def wait(self, attempt: int) -> None:
        """Sleep before retry number ``attempt`` (0-based): ``backoff`` doubling up to ``max_backoff``."""
        self.sleep(min(self.max_backoff, self.backoff * (2 ** attempt)))

    def _call(self, method: str, path: str, *, params: Optional[dict] = None,
              body: Optional[dict] = None):
        headers = {KEY_HEADER: self._key, "Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        what = f"{method} {path}"
        failures = refusals = 0
        while True:
            self._wait_turn()
            try:
                reply = self.transport.send(method, path, params=params, body=body, headers=headers)
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                    ConnectionError, OSError) as e:
                problem = Unsure(f"{what}: no answer ({type(e).__name__}: {self.scrub(e)})")
            else:
                status = reply.status
                if 200 <= status < 300:
                    if reply.body is None:
                        problem = Unsure(f"{what}: HTTP {status} without JSON: {self.scrub(reply.text)!r}")
                    else:
                        return reply.body
                elif status in (401, 403):
                    raise AuthError(f"{what}: HTTP {status}, the server refused the API key in "
                                    f"{KEY_ENV} ({self._detail(reply)})")
                elif status == 429:
                    after = _seconds(reply.headers.get("retry-after"))
                    message = f"{what}: HTTP 429 ({self._detail(reply)})"
                    if (after is not None and after > self.max_retry_after) \
                            or refusals >= self.rate_limit_retries:
                        raise RateLimited(message, after)
                    self.sleep(max(after or 0.0, min(self.max_backoff, self.backoff * 2 ** refusals)))
                    refusals += 1
                    continue
                elif status >= 500:
                    problem = Unsure(f"{what}: HTTP {status} ({self._detail(reply)})")
                elif status == 404:
                    raise NotFound(f"{what}: HTTP 404 ({self._detail(reply)})", 404)
                else:
                    raise Rejected(f"{what}: HTTP {status} ({self._detail(reply)})", status)
            if method != "GET" or failures >= self.retries:
                raise problem
            self.wait(failures)
            failures += 1

    def _detail(self, reply: Reply) -> str:
        """The server's error text, FastAPI style (``{"detail": ...}``), short and without the key."""
        d = reply.body.get("detail") if isinstance(reply.body, dict) else None
        if isinstance(d, list):
            parts = []
            for item in d:
                if isinstance(item, dict):
                    where = ".".join(str(x) for x in item.get("loc", ()))
                    parts.append(f"{where}: {item.get('msg')}" if where else str(item.get("msg")))
                else:
                    parts.append(str(item))
            d = "; ".join(parts)
        text = str(d) if d else reply.text
        return self.scrub(text)[:300] or "no details"

    def _wait_turn(self) -> None:
        now = self._clock()
        if self._last is not None:
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                self.sleep(gap)
                now = self._clock()
        self._last = now
        self.requests += 1


def _seconds(retry_after: Optional[str]) -> Optional[float]:
    """``Retry-After`` in seconds. The HTTP-date form is not handled: None."""
    try:
        return max(0.0, float(retry_after)) if retry_after is not None else None
    except ValueError:
        return None
