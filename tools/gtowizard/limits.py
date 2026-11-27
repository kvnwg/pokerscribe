"""GTO Wizard's hand caps, and a count of the hands we have started.

The limits (benchmark.gtowizard.com FAQ, read 26 Nov 2026), per user and per game:

- 10,000 hands a day, 25,000 a week, 50,000 a month;
- they reset at midnight UTC: every day, on Monday for the week, on the 1st for the month;
- they "may change at any time".

The session asks ``HandBudget.check()`` before every new hand and never starts one that would go
over. Two counts feed it, and the larger one is used:

- the **ledger**, a local file with one line per hand started (the time and the hand id), used
  by every session on this machine whatever log it writes to, one session at a time
  (``LedgerLock``);
- the **server's own count**, ``total_hands`` from ``GET /results`` with ``start_date`` set to the
  start of the day, the week and the month, fetched when a session starts. It covers hands played
  from another machine or with another tool.

Caps can be lowered (``Caps(day=500)``), never raised above the published numbers: if GTO Wizard
raises its limits, change ``PUBLISHED`` here, with the date.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import json
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .client import Rejected

UTC = _dt.timezone.utc
WINDOWS = ("day", "week", "month")
PUBLISHED = {"day": 10_000, "week": 25_000, "month": 50_000}
PUBLISHED_READ = "26 Nov 2026"
LEDGER_ENV = "GTOWIZARD_LEDGER"


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(UTC)


def window_starts(now: _dt.datetime) -> Dict[str, _dt.datetime]:
    """When the current day, week (Monday) and month began, in UTC."""
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"day": day, "week": day - _dt.timedelta(days=day.weekday()), "month": day.replace(day=1)}


def next_resets(now: _dt.datetime) -> Dict[str, _dt.datetime]:
    """When each cap next resets, in UTC."""
    s = window_starts(now)
    month = s["month"]
    after = month.replace(year=month.year + 1, month=1) if month.month == 12 \
        else month.replace(month=month.month + 1)
    return {"day": s["day"] + _dt.timedelta(days=1), "week": s["week"] + _dt.timedelta(days=7),
            "month": after}


@dataclass(frozen=True)
class Caps:
    day: int = PUBLISHED["day"]
    week: int = PUBLISHED["week"]
    month: int = PUBLISHED["month"]

    def __post_init__(self):
        for w in WINDOWS:
            n = getattr(self, w)
            if n < 0 or n > PUBLISHED[w]:
                raise ValueError(
                    f"the {w} cap must be between 0 and {PUBLISHED[w]:,} (GTO Wizard's limit, read "
                    f"{PUBLISHED_READ}); it can be lowered here, not raised")

    def of(self, window: str) -> int:
        return getattr(self, window)


class CapReached(Exception):
    """Starting another hand would go over a cap."""

    def __init__(self, window: str, used: int, cap: int, resets: _dt.datetime):
        super().__init__(f"the {window} cap is reached: {used:,} of {cap:,} hands; it resets at "
                         f"{resets:%Y-%m-%d %H:%M} UTC")
        self.window, self.used, self.cap, self.resets = window, used, cap, resets


def default_ledger_path() -> str:
    """``$GTOWIZARD_LEDGER``, or ``gtowizard_ledger.jsonl`` in PokerScribe's per-user data folder."""
    override = os.environ.get(LEDGER_ENV)
    if override:
        return os.path.expanduser(override)
    from app.config.settings import app_data_dir
    return str(app_data_dir() / "gtowizard_ledger.jsonl")


class Ledger:
    """One line per hand started: ``{"time": ..., "hand_id": ...}``. No key, no cards.

    A hand whose id never reached us (the request for a new hand got no answer, so the server may
    or may not have dealt one) is written with ``hand_id`` null and still counts: over-counting by
    one is harmless, under-counting is not.
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._times: List[_dt.datetime] = []
        self._ids: set = set()
        self._size = -1
        self.refresh()

    def refresh(self) -> None:
        """Read the file again if another session has written to it."""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        if size == self._size:
            return
        times, ids = [], set()
        if size:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        t = _dt.datetime.fromisoformat(rec["time"])
                    except (ValueError, KeyError, TypeError):
                        continue  # a line cut off by a crash
                    times.append(t)
                    if rec.get("hand_id") is not None:
                        ids.add(rec["hand_id"])
        self._times, self._ids, self._size = sorted(times), ids, size

    def __contains__(self, hand_id: int) -> bool:
        return hand_id in self._ids

    def __len__(self) -> int:
        return len(self._times)

    def add(self, hand_id: Optional[int], when: _dt.datetime, note: Optional[str] = None) -> bool:
        """Record a hand as started. Returns False if this hand id is already there."""
        self.refresh()
        if hand_id is not None and hand_id in self._ids:
            return False
        rec = {"time": when.astimezone(UTC).isoformat(timespec="seconds"), "hand_id": hand_id}
        if note:
            rec["note"] = note
        line = json.dumps(rec, separators=(",", ":")) + "\n"
        if self._cut_off():
            line = "\n" + line  # a crash left half a line: don't glue this record onto it
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        self._size = os.path.getsize(self.path)
        bisect.insort(self._times, _dt.datetime.fromisoformat(rec["time"]))
        if hand_id is not None:
            self._ids.add(hand_id)
        return True

    def _cut_off(self) -> bool:
        """Whether the file ends in the middle of a line."""
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    return False
                f.seek(-1, os.SEEK_END)
                return f.read(1) != b"\n"
        except OSError:
            return False

    def count_since(self, t: _dt.datetime) -> int:
        return len(self._times) - bisect.bisect_left(self._times, t)


class LedgerLock:
    """One session at a time per ledger, on this machine.

    Two sessions at once would each finish the other's open hand (both start by playing whatever
    the server holds in progress) and could both pass the cap check for the same last hand. The
    lock is a file next to the ledger, held with ``flock`` while a session runs and released by
    the system if the process dies. It can't see a session on another machine: that is on us.
    """

    def __init__(self, ledger_path: str):
        self.path = ledger_path + ".lock"
        self._file = None

    def acquire(self) -> bool:
        try:
            import fcntl
        except ImportError:  # no flock on this system (Windows): nothing to hold
            return True
        f = open(self.path, "a")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._file = f
        return True

    def release(self) -> None:
        if self._file is not None:
            self._file.close()  # closing the file drops the lock
            self._file = None


class HandBudget:
    """How many more hands may be started today, this week and this month."""

    def __init__(self, ledger: Ledger, caps: Optional[Caps] = None,
                 now: Callable[[], _dt.datetime] = utcnow):
        self.ledger = ledger
        self.caps = caps or Caps()
        self.now = now
        self._server: Optional[Dict[str, int]] = None
        self._server_time: Optional[_dt.datetime] = None

    def set_server_counts(self, counts: Dict[str, int], when: _dt.datetime, open_hands: int = 0) -> None:
        """The server's ``total_hands`` for each window as of ``when``, plus hands still open then."""
        self._server = {w: int(counts.get(w, 0)) + int(open_hands) for w in WINDOWS}
        # The ledger keeps whole seconds; round down so a hand started in this second still counts.
        self._server_time = when.replace(microsecond=0)

    def used(self, now: Optional[_dt.datetime] = None) -> Dict[str, int]:
        now = now or self.now()
        self.ledger.refresh()
        starts = window_starts(now)
        out = {}
        for w in WINDOWS:
            n = self.ledger.count_since(starts[w])
            # The server's count only describes this window if it was taken inside it.
            if self._server is not None and self._server_time >= starts[w]:
                n = max(n, self._server[w] + self.ledger.count_since(self._server_time))
            out[w] = n
        return out

    def left(self, now: Optional[_dt.datetime] = None) -> Dict[str, int]:
        used = self.used(now)
        return {w: max(0, self.caps.of(w) - used[w]) for w in WINDOWS}

    def allowance(self, now: Optional[_dt.datetime] = None) -> int:
        return min(self.left(now).values())

    def check(self, now: Optional[_dt.datetime] = None) -> None:
        """Raise ``CapReached`` if one more hand would go over a cap."""
        now = now or self.now()
        used = self.used(now)
        for w in WINDOWS:
            if used[w] >= self.caps.of(w):
                raise CapReached(w, used[w], self.caps.of(w), next_resets(now)[w])


def server_counts(client, now: _dt.datetime) -> Dict[str, int]:
    """``total_hands`` from ``GET /results`` since the start of the day, the week and the month."""
    out = {}
    for w, start in window_starts(now).items():
        stats = client.results(start=start)
        out[w] = int(stats.get("total_hands", 0)) if stats else 0
    return out


def use_server_counts(budget: HandBudget, client, now: _dt.datetime, open_hands: int = 0) -> Optional[str]:
    """Give ``budget`` the server's counts. Returns None, or why they could not be had.

    If the server refuses the question itself (a 4xx: say it reads ``start_date`` differently
    than the spec suggests), the ledger alone is used and the reason is returned, to be shown.
    Other failures (no answer, a refused key) are raised: nothing should be played then anyway.
    """
    try:
        budget.set_server_counts(server_counts(client, now), now, open_hands=open_hands)
    except Rejected as e:
        return (f"the server's own hand count could not be read ({client.scrub(e)}); "
                "counting from the local ledger only")
    return None
