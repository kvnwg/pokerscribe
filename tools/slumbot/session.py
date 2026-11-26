"""Play sessions against Slumbot: the hand loop, the JSONL hand log, resuming, and bb/100.

The log is one JSON object per line:

- ``{"type": "session", ...}`` when a session starts or resumes (bot, rules, time).
- ``{"type": "hand", ...}`` for every finished hand: seat, cards, the action string, the parsed
  history by street, our decisions, Slumbot's ``winnings`` and ``baseline_winnings``, and our own
  recomputation of the result from the cards and the history (``check``).
- ``{"type": "aborted", ...}`` for a hand that could not be finished (the server rejected an
  action, or a retried request had already gone through). Aborted hands are not in the stats.
- ``{"type": "note", ...}`` for anything else worth knowing (a hand cut off by a restart, a new
  server token).

Next to the log, ``<log>.state.json`` keeps the API token and whether a hand was in progress, so
an interrupted session resumes with the same server session. It holds a credential: don't commit
or share it. The log itself has no token and no username.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

from .bots import Bot, BotState
from .client import SlumbotClient, SlumbotError, SlumbotRejected
from .protocol import (BIG_BLIND, SEAT_NAMES, SMALL_BLIND, STACK, STREETS, ActionHistory,
                       ActionParseError, chips_won, parse_action)

MAX_ABORTS_IN_A_ROW = 3


class TokenRefused(SlumbotError):
    """new_hand refused the saved token (it can expire after a long pause)."""


class Desync(SlumbotError):
    """The server's hand no longer matches ours (for example, a retried action went through twice)."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# --- one hand ---------------------------------------------------------------------------------

def _rank(hole: List[str], board: List[str]) -> Optional[int]:
    try:
        from treys import Card, Evaluator
    except ImportError:
        return None
    if len(board) != 5 or len(hole) != 2:
        return None
    return Evaluator().evaluate([Card.new(c) for c in board], [Card.new(c) for c in hole])


def check_result(history: ActionHistory, me: int, hole: List[str], bot_hole: Optional[List[str]],
                 board: List[str], winnings: int) -> dict:
    """Recompute our result from the history and cards and compare it with the server's."""
    if history.folded is not None:
        mine = chips_won(history, me)
    elif bot_hole:
        mine = chips_won(history, me, _rank(hole, board), _rank(bot_hole, board))
    else:
        mine = None
    status = "unchecked" if mine is None else ("ok" if mine == winnings else "mismatch")
    return {"computed_winnings": mine, "check": status}


def play_hand(client: SlumbotClient, bot: Bot, hand_number: int) -> dict:
    """Play one hand to the end and return its log record. Raises SlumbotError if it can't."""
    try:
        r = client.new_hand()
    except SlumbotRejected as e:
        if client.token:
            raise TokenRefused(str(e)) from e
        raise
    for key in ("client_pos", "hole_cards", "action"):
        if key not in r:
            raise SlumbotError(f"new_hand reply without {key}: {r!r}")
    me = int(r["client_pos"])
    hole = list(r["hole_cards"])
    decisions = []
    state = None
    while "winnings" not in r:
        history = parse_action(r["action"])
        if history.over:
            raise Desync(f"hand over at {r['action']!r} but no result")
        if history.to_act != me:
            raise Desync(f"not our turn at {r['action']!r}")
        state = BotState(me=me, hole_cards=hole, board=list(r.get("board", [])), history=history,
                         hand_number=hand_number)
        if not decisions:
            bot.start_hand(state)
        d = bot.act(state)
        if not state.is_legal(d):
            raise ValueError(f"{bot.name} chose an illegal action {d} at {r['action']!r} "
                             f"(legal: {state.legal()})")
        incr = d.incr()
        prior = r["action"]
        decisions.append({"street": STREETS[history.street], "facing": prior, "incr": incr})
        r = client.act(incr)
        if r.get("old_action", prior) != prior:
            raise Desync(f"sent {incr!r} after {prior!r} but the server applied it after "
                         f"{r.get('old_action')!r}")
    history = parse_action(r["action"])
    if not history.over:
        raise Desync(f"result given but the action {r['action']!r} is not finished")
    board = list(r.get("board", []))
    bot_hole = r.get("bot_hole_cards")
    winnings = int(r["winnings"])
    rec = {
        "type": "hand", "hand": hand_number, "time": _now(), "bot": bot.name,
        "seat": me, "position": SEAT_NAMES[me], "hole_cards": hole, "bot_hole_cards": bot_hole,
        "board": board, "action": r["action"],
        "streets": history.by_street(me), "history": history.to_dict(),
        "decisions": decisions, "showdown": history.showdown, "pot": history.pot,
        "winnings": winnings, "baseline_winnings": r.get("baseline_winnings"),
        "won_pot": r.get("won_pot"), "server_session_hands": r.get("session_num_hands"),
    }
    rec.update(check_result(history, me, hole, bot_hole, board, winnings))
    if state is not None:
        bot.end_hand(state, rec)
    return rec


# --- the log ----------------------------------------------------------------------------------

def read_log(path: str) -> List[dict]:
    """The log's records. A last line cut off by a crash is dropped; a bad line elsewhere is an error."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f.read().split("\n") if ln.strip()]
    out = []
    for i, line in enumerate(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            if i == len(lines) - 1:
                continue
            raise
    return out


def hands_in(records: Iterable[dict]) -> List[dict]:
    return [r for r in records if r.get("type") == "hand"]


class HandLog:
    def __init__(self, path: str):
        self.path = path
        self.state_path = path + ".state.json"
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)

    def append(self, rec: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def repair(self) -> int:
        """Cut off a last line left half-written by a crash. Returns how many bytes were dropped."""
        try:
            with open(self.path, "rb") as f:
                data = f.read()
        except OSError:
            return 0
        if not data or data.endswith(b"\n"):
            return 0
        keep = data.rfind(b"\n") + 1
        with open(self.path, "r+b") as f:
            f.truncate(keep)
        return len(data) - keep

    def load_state(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.state_path)


# --- stats ------------------------------------------------------------------------------------

@dataclass
class Rate:
    n: int
    bb100: float
    se: float

    def __str__(self) -> str:
        return f"{self.bb100:+.1f} bb/100 (± {self.se:.1f}, n={self.n})"


def rate(values_chips: List[float], big_blind: int = BIG_BLIND) -> Rate:
    """Mean result in big blinds per 100 hands, with its standard error."""
    n = len(values_chips)
    if n == 0:
        return Rate(0, 0.0, float("nan"))
    bb = [v / big_blind for v in values_chips]
    mean = sum(bb) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in bb) / (n - 1)) if n > 1 else float("nan")
    return Rate(n, 100 * mean, 100 * sd / math.sqrt(n))


def summary(hands: List[dict]) -> dict:
    out = {"hands": len(hands), "raw": rate([h["winnings"] for h in hands])}
    base = [h["baseline_winnings"] for h in hands if h.get("baseline_winnings") is not None]
    out["baseline"] = rate(base) if base else None
    for seat, name in SEAT_NAMES.items():
        out[name] = rate([h["winnings"] for h in hands if h["seat"] == seat])
    out["checks"] = {k: sum(1 for h in hands if h.get("check") == k)
                     for k in ("ok", "mismatch", "unchecked")}
    out["showdowns"] = sum(1 for h in hands if h.get("showdown"))
    return out


def format_summary(s: dict) -> str:
    lines = [f"{s['hands']} hands",
             f"  raw:      {s['raw']}",
             f"  baseline: {s['baseline'] if s['baseline'] else 'n/a'}"
             "   (our result minus Slumbot's own result with our cards in our seat)",
             f"  as BB:    {s['BB']}",
             f"  as SB:    {s['SB']}",
             f"  showdowns: {s['showdowns']}; result checks: " + ", ".join(
                 f"{v} {k}" for k, v in s["checks"].items())]
    if s["hands"] % 2:
        lines.append("  note: an odd number of hands, so one seat was played once more than the other")
    return "\n".join(lines)


# --- a session --------------------------------------------------------------------------------

def run_session(client: SlumbotClient, bot: Bot, log_path: str, target_hands: int, *,
                resume: bool = False, logged_in: bool = False,
                echo: Callable[[str], None] = print, progress_every: int = 20) -> dict:
    """Play until the log holds ``target_hands`` finished hands. Returns the summary."""
    log = HandLog(log_path)
    dropped = log.repair()
    if dropped:
        log.append({"type": "note", "time": _now(), "event": "cut_line",
                    "detail": f"dropped {dropped} bytes of a record half-written by a crash"})
    records = read_log(log_path)
    hands = hands_in(records)
    if hands and not resume:
        raise SystemExit(f"{log_path} already has {len(hands)} hands; pass --resume to continue it "
                         "or choose a new log")
    sessions = [r for r in records if r.get("type") == "session"]
    if sessions and sessions[0].get("bot") != bot.name:
        raise SystemExit(f"{log_path} was played by {sessions[0].get('bot')!r}, not {bot.name!r}")
    state = log.load_state()
    if state.get("token") and not client.token:
        client.token = state["token"]
    if state.get("in_hand"):
        log.append({"type": "note", "time": _now(), "event": "hand_cut_off",
                    "detail": "a hand was in progress when the last run stopped; it was abandoned"})
    log.append({"type": "session", "time": _now(), "event": "resume" if records else "start",
                "bot": bot.name, "bot_version": bot.version, "target_hands": target_hands,
                "hands_so_far": len(hands), "small_blind": SMALL_BLIND, "big_blind": BIG_BLIND,
                "stack": STACK, "logged_in": logged_in, "min_interval_s": client.min_interval})

    aborts_in_a_row = 0
    token_resets = 0
    n = len(hands)
    try:
        while n < target_hands:
            log.save_state({"token": client.token, "in_hand": True, "hands": n})
            try:
                rec = play_hand(client, bot, n + 1)
            except TokenRefused as e:
                if token_resets >= 1:
                    raise
                token_resets += 1
                log.append({"type": "note", "time": _now(), "event": "new_token",
                            "detail": f"the saved token was refused ({e}); starting a new server session"})
                client.token = None
                continue
            except SlumbotRejected as e:
                aborts_in_a_row += 1
                log.append({"type": "aborted", "time": _now(), "hand": n + 1, "reason": str(e)})
                echo(f"hand {n + 1} aborted: {e}")
            except (Desync, ActionParseError) as e:
                aborts_in_a_row += 1
                log.append({"type": "aborted", "time": _now(), "hand": n + 1, "reason": str(e)})
                echo(f"hand {n + 1} aborted: {e}")
            else:
                aborts_in_a_row = 0
                log.append(rec)
                hands.append(rec)
                n += 1
                if rec["check"] == "mismatch":
                    echo(f"hand {n}: server says {rec['winnings']}, our recomputation says "
                         f"{rec['computed_winnings']} ({rec['action']})")
                if progress_every and n % progress_every == 0:
                    echo(f"{n}/{target_hands}: {rate([h['winnings'] for h in hands])}")
            if aborts_in_a_row >= MAX_ABORTS_IN_A_ROW:
                raise SlumbotError(f"{aborts_in_a_row} hands in a row could not be finished; stopping")
            log.save_state({"token": client.token, "in_hand": False, "hands": n})
    except KeyboardInterrupt:
        echo("stopped; run again with --resume to continue")
    finally:
        st = log.load_state()
        st["token"] = client.token
        log.save_state(st)
    return summary(hands)

