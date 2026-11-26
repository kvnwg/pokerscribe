"""Play sessions against GTO Wizard AI: the hand loop, the JSONL hand log, resuming, the caps,
and the luck-adjusted results the API returns.

GTO Wizard's terms, as this module keeps them
---------------------------------------------
- **Benchmarking only, and never training data.** Every line this module writes carries
  ``"source": "gtowizard_benchmark"`` and ``"use": "benchmark_only"``, and every session line
  carries the notice in full. Anything that builds a training, tuning or calibration set must
  drop such lines. ``run_session`` refuses to start until the caller has accepted the terms.
- **No human help during hands.** Nothing here reads the keyboard. Every decision comes from the
  bot. When the bot fails or picks an illegal action, or when a reply can't be read, the hand is
  finished by rule (check when it is free, fold otherwise), the session stops after that hand,
  and the fix happens between hands.
- **Results are public** from the first hand, hand histories included. There are no practice hands.
- **The caps** (``limits.py``) are checked before every new hand; a hand that would go over is
  never started. One hand is played at a time.

The log is one JSON object per line:

- ``session``: written when a session starts or resumes (bot, rules, caps, hands used so far).
- ``hand``: a finished hand. Our seat and cards, the server's action list and the same history as
  a Slumbot string and by street, our decisions, ``winnings`` (chips), ``aivat_score`` (the
  luck-adjusted result of this hand in chips, computed by GTO Wizard), our own recomputation of
  the result (``check``), and the final game state as the server sent it.
- ``lost``: a hand that ended on the server without its result reaching us (a reply lost on the
  way, or a crash between the reply and the log). It counts towards the caps and GTO Wizard's
  results, not towards the log's own statistics.
- ``results``: what ``GET /results`` returned, for everything under the key and for this log's
  time window. The latest one is also written to ``<log>.results.json``.
- ``note``: anything else worth knowing.

Resuming: the server keeps unfinished hands (``GET /hands/in-progress``). Every session starts by
finishing those, so a hand cut off by a crash is played to the end by the bot (``"resumed": true``),
not abandoned. ``<log>.state.json`` only remembers which hand was open; it holds no secret.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Callable, List, Optional

from ..slumbot.bots import Bot
from ..slumbot.protocol import BIG_BLIND, SEAT_NAMES, SMALL_BLIND, STACK
from ..slumbot.session import HandLog, check_result, hands_in, rate, read_log
from .client import GTOWizardClient, GTOWizardError, NotFound, RateLimited, Rejected, Unsure
from .limits import (WINDOWS, CapReached, HandBudget, Ledger, default_ledger_path,
                     use_server_counts, utcnow)
from .protocol import OPPONENT, USER, ProtocolError, Reader, request_for, safe_action

SOURCE = "gtowizard_benchmark"
USE = "benchmark_only"
NOTICE = ("GTO Wizard Benchmark data. Benchmarking only: under GTO Wizard's terms these hands and "
          "results must never be used to train, tune or calibrate any agent, solver or model.")
TERMS = """GTO Wizard's terms for the benchmark (https://benchmark.gtowizard.com/terms/), in short:
  1. Benchmarking only.
  2. The hands and results must NEVER be used to train, tune or calibrate anything.
  3. No human help during hands: the bot plays every decision alone.
  4. Results are public. GTO Wizard may publish the bot's name, rank, results and every hand.
Every hand counts from the first one; there are no practice hands."""

MAX_PROBLEMS_IN_A_ROW = 3  # lost hands or unanswered new-hand requests before the session stops
SEND_ATTEMPTS = 6  # times one action is offered to the server while it keeps not applying it
TURN_POLLS = 5  # looks at a hand that is waiting for GTO Wizard AI before giving up
Z95 = 1.96  # the leaderboard ranks by the lower end of the 95% interval


class HandLost(GTOWizardError):
    """The hand ended on the server and its result never reached us."""


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).isoformat(timespec="seconds")


def _find(hands: List[dict], hand_id: int) -> Optional[dict]:
    return next((h for h in hands if h.get("hand_id") == hand_id), None)


# --- one hand -------------------------------------------------------------------------------------

def _send(client: GTOWizardClient, hand_id: int, before: dict, action: str,
          amount: Optional[int]) -> dict:
    """Send one action and return the next state, without ever applying it twice.

    When no usable answer comes back, the server may or may not have applied the action. The
    hand's entry in ``/hands/in-progress`` tells: an unchanged action history means it did not
    (send again, after a pause), a longer one means it did (carry on from there), and no entry
    means the action ended the hand and the result is gone (``HandLost``).
    """
    sent_at = list(before["game_state"]["action_history"])
    problem: Optional[Exception] = None
    for attempt in range(SEND_ATTEMPTS):
        try:
            return client.act(hand_id, action, amount)
        except NotFound as e:
            raise HandLost(f"the server no longer knows hand {hand_id}: {e}") from e
        except Unsure as e:
            problem = e
        client.wait(attempt)
        now = _find(client.in_progress(), hand_id)
        if now is None:
            raise HandLost(f"hand {hand_id} ended on the server, but the reply with its result "
                           f"never arrived ({problem})")
        if list(now["game_state"]["action_history"]) != sent_at:
            return now
    raise problem


def _wait_for_turn(client: GTOWizardClient, hand_id: int) -> dict:
    """The server shows a hand that is waiting for GTO Wizard AI. Look again until it is our turn."""
    for attempt in range(TURN_POLLS):
        client.wait(attempt)
        now = _find(client.in_progress(), hand_id)
        if now is None:
            raise HandLost(f"hand {hand_id} was waiting for GTO Wizard AI and is no longer in progress")
        if now["game_state"].get("player_to_act") == USER:
            return now
    raise GTOWizardError(f"hand {hand_id} is still not ours to act on after {TURN_POLLS} looks; "
                         "it stays open on the server, resume later")


def play_hand(client: GTOWizardClient, bot: Bot, resp: dict, hand_number: int, reader: Reader, *,
              resumed: bool = False, now: Callable[[], _dt.datetime] = utcnow) -> dict:
    """Play the hand in ``resp`` to the end and return its log record (``hand`` or ``lost``).

    No human is asked anything, ever. If the bot can't play the hand (it fails, it picks an
    illegal action, the server refuses its action, or a reply can't be trusted), the rest of the
    hand is checked or folded and the record says why in ``fallback``.
    """
    hand_id = int(resp["hand_id"])
    me: Optional[int] = None
    decisions: List[dict] = []
    notes: List[str] = []
    fallback: Optional[str] = None
    state = view = sending = None
    started = False
    try:
        while True:
            gs = resp.get("game_state") or {}
            try:
                view = reader.read(resp, me)
            except ProtocolError as e:
                view = None
                fallback = fallback or f"a reply could not be read: {e}"
            if view is not None:
                me = view.me
                notes.extend(s for s in view.soft if s not in notes)
                if view.hard and fallback is None and not view.over:
                    fallback = "; ".join(view.hard)
            if gs.get("is_hand_over"):
                break
            if gs.get("player_to_act") != USER:
                resp = _wait_for_turn(client, hand_id)
                continue
            decision = None
            if fallback is None:
                state = view.bot_state(hand_number)
                try:
                    if not started:
                        started = True
                        bot.start_hand(state)
                    decision = bot.act(state)
                    if not state.is_legal(decision):
                        fallback = (f"{bot.name} chose {decision}, which is not legal here "
                                    f"(legal: {state.legal()})")
                except Exception as e:  # a bot bug must not leave the hand hanging
                    fallback = f"{bot.name} failed: {type(e).__name__}: {e}"
            if fallback is None:
                action, amount = request_for(decision)
            else:
                action, amount = safe_action(gs.get("legal_actions") or ())
            entry = {"street": gs.get("street"),
                     "facing": view.history.action if view is not None and view.history else None,
                     "incr": action + ("" if amount is None else str(amount))}
            if fallback is not None:
                entry["fallback"] = True
            sending, before = entry, list(gs.get("action_history") or [])
            try:
                resp = _send(client, hand_id, resp, action, amount)
            except Rejected as e:
                if fallback is not None:
                    raise  # even a check or a fold was refused: stop, the hand stays open
                fallback = f"the server refused {entry['incr']} from {bot.name}: {e}"
                continue
            after = resp.get("game_state") or {}
            if not after.get("is_hand_over") and list(after.get("action_history") or []) == before:
                raise GTOWizardError(f"hand {hand_id}: the server answered {entry['incr']!r} with an "
                                     "unchanged hand; stopping rather than sending it again")
            sending = None
            decisions.append(entry)
    except HandLost as e:
        # ``unanswered`` is the action whose reply never came; if the hand is gone, it was applied.
        return {"type": "lost", "source": SOURCE, "use": USE, "hand_id": hand_id, "time": _iso(now()),
                "bot": bot.name, "reason": client.scrub(e), "resumed": resumed,
                "decisions": decisions, "unanswered": sending["incr"] if sending else None,
                "action_history": list((resp.get("game_state") or {}).get("action_history") or [])}

    gs = resp.get("game_state") or {}
    if gs.get("winnings") is None:
        return {"type": "lost", "source": SOURCE, "use": USE, "hand_id": hand_id, "time": _iso(now()),
                "bot": bot.name, "reason": "the hand is over but the reply has no winnings",
                "resumed": resumed, "decisions": decisions, "game_state": gs}
    history = view.history if view is not None else None
    rec = {
        "type": "hand", "source": SOURCE, "use": USE, "hand": hand_number, "hand_id": hand_id,
        "time": _iso(now()), "bot": bot.name,
        "seat": me, "position": SEAT_NAMES.get(me),
        "hole_cards": view.hole_cards if view is not None else None,
        "gto_hole_cards": view.opponent_cards if view is not None else None,
        "board": view.board if view is not None else None,
        "action_history": list(gs.get("action_history") or []),
        "action": history.action if history else None,
        "streets": history.by_street(me, OPPONENT) if history else None,
        "history": history.to_dict() if history else None,
        "postflop_first": SEAT_NAMES[reader.postflop_first],
        "decisions": decisions,
        "showdown": history.showdown if history else None,
        "pot": history.pot if history else None,
        "winnings": float(gs["winnings"]),
        "aivat_score": None if gs.get("aivat_score") is None else float(gs["aivat_score"]),
        "gto_folded": bool(gs.get("has_gto_wizard_folded")),
        "resumed": resumed,
        "fallback": None if fallback is None else client.scrub(fallback),
        "notes": notes,
        "game_state": gs,
    }
    if resp.get("mock"):
        rec["mock"] = True
    if history is not None and history.over and not view.hard:
        rec.update(check_result(history, me, view.hole_cards, view.opponent_cards, view.board,
                                rec["winnings"]))
    else:
        rec.update({"computed_winnings": None, "check": "unreadable"})
        if view is not None:
            rec["notes"] = notes + [h for h in view.hard if h not in notes]
    if started and state is not None:
        try:
            bot.end_hand(state, rec)
        except Exception as e:
            rec["notes"] = rec["notes"] + [f"{bot.name}.end_hand failed: {type(e).__name__}: {e}"]
    return rec


# --- results and stats ----------------------------------------------------------------------------

def tidy_results(stats: Optional[dict]) -> Optional[dict]:
    """The API's statistics with honest names next to the raw object.

    The API field ``aivat_std_bb_per_100`` is the standard error of the AIVAT win rate (its own
    description says so, and the old name is kept for compatibility). It is saved here as
    ``aivat_standard_error_bb_per_100``.
    """
    if not stats:
        return None
    win, se = stats.get("aivat_score_bb_per_100"), stats.get("aivat_std_bb_per_100")
    interval = None if win is None or se is None else [win - Z95 * se, win + Z95 * se]
    return {"hands": stats.get("total_hands"), "aivat_bb_per_100": win,
            "aivat_standard_error_bb_per_100": se, "aivat_ci95_bb_per_100": interval,
            "raw_bb_per_100": stats.get("bb_per_100"), "api": stats}


def results_path(log_path: str) -> str:
    return log_path + ".results.json"


def save_results(client: GTOWizardClient, log_path: str,
                 now: Callable[[], _dt.datetime] = utcnow) -> dict:
    """Fetch ``GET /results``, append it to the log and write it to ``<log>.results.json``.

    Two answers are saved: everything played under the key (what the leaderboard shows), and the
    hands since this log's first session line (``this_log``), which is this log's own result as
    long as nothing else was played with the key in that time (``matches_log`` says whether the
    server's hand count for the window equals the log's).
    """
    records = read_log(log_path)
    n = len(hands_in(records))
    snap = {"type": "results", "source": SOURCE, "use": USE, "notice": NOTICE, "time": _iso(now()),
            "api": client.url, "game": client.game, "all_time": tidy_results(client.results())}
    sessions = [r for r in records if r.get("type") == "session" and r.get("time")]
    if sessions:
        start = _dt.datetime.fromisoformat(sessions[0]["time"])
        window = tidy_results(client.results(start=start)) or {}
        snap["this_log"] = {"start_date": _iso(start), "hands_in_log": n,
                            "matches_log": window.get("hands") == n, **window}
    if any(h.get("mock") for h in hands_in(records)):
        snap["mock"] = True
    HandLog(log_path).append(snap)
    tmp = results_path(log_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1)
        f.write("\n")
    os.replace(tmp, results_path(log_path))
    return snap


def summary(records: List[dict]) -> dict:
    """The log's own numbers: raw and luck-adjusted bb/100 from the per-hand values, by seat too."""
    hands = hands_in(records)

    def rates(hs: List[dict]) -> dict:
        scores = [h["aivat_score"] for h in hs if h.get("aivat_score") is not None]
        return {"raw": rate([h["winnings"] for h in hs]), "aivat": rate(scores) if scores else None}

    out = {"hands": len(hands), **rates(hands)}
    for seat, name in SEAT_NAMES.items():
        out[name] = rates([h for h in hands if h.get("seat") == seat])
    out["checks"] = {k: sum(1 for h in hands if h.get("check") == k)
                     for k in ("ok", "mismatch", "unchecked", "unreadable")}
    out["showdowns"] = sum(1 for h in hands if h.get("showdown"))
    out["fallbacks"] = sum(1 for h in hands if h.get("fallback"))
    out["resumed"] = sum(1 for h in hands if h.get("resumed"))
    out["lost"] = sum(1 for r in records if r.get("type") == "lost")
    out["mock"] = any(h.get("mock") for h in hands)
    out["results"] = next((r for r in reversed(records) if r.get("type") == "results"), None)
    out["stopped"] = None
    return out


def _api_line(label: str, t: Optional[dict]) -> str:
    if not t or t.get("aivat_bb_per_100") is None:
        return f"    {label}: nothing yet"
    lo, hi = t["aivat_ci95_bb_per_100"]
    return (f"    {label}: {t['hands']:,} hands, AIVAT {t['aivat_bb_per_100']:+.2f} bb/100, "
            f"standard error {t['aivat_standard_error_bb_per_100']:.2f}, 95% interval "
            f"{lo:+.2f} to {hi:+.2f}; raw {t['raw_bb_per_100']:+.2f} bb/100")


def format_summary(s: dict) -> str:
    lines = [f"{s['hands']:,} hands against GTO Wizard AI. Benchmark only: never train, tune or "
             "calibrate on them."]
    if s["mock"]:
        lines.append("  MOCK SERVER: a random opponent and made-up AIVAT numbers. These mean nothing.")
    lines += [f"  raw:      {s['raw']}",
              f"  AIVAT:    {s['aivat'] if s['aivat'] else 'n/a'}   (from this log's per-hand aivat_score)"]
    for name in ("BB", "SB"):
        lines.append(f"  as {name}:    raw {s[name]['raw']}; AIVAT {s[name]['aivat'] or 'n/a'}")
    lines.append(f"  showdowns: {s['showdowns']}; result checks: "
                 + ", ".join(f"{v} {k}" for k, v in s["checks"].items()))
    extras = [f"{s[k]} {text}" for k, text in (("fallbacks", "finished by check or fold"),
                                               ("resumed", "resumed after a stop"),
                                               ("lost", "lost (ended on the server, result not seen)"))
              if s[k]]
    if extras:
        lines.append("  hands " + "; ".join(extras))
    r = s["results"]
    if r:
        lines.append(f"  GTO Wizard's own figures (GET /results, {r['time']}):")
        lines.append(_api_line("all hands under this key", r.get("all_time")))
        w = r.get("this_log")
        if w:
            lines.append(_api_line(f"since {w['start_date']}", w))
            if not w["matches_log"]:
                lines.append(f"    that window holds {w.get('hands')} hands at the server and "
                             f"{w['hands_in_log']} in this log, so it is not this log's result alone")
    if s.get("stopped"):
        lines.append(f"  stopped early ({s['stopped']['reason']}): {s['stopped']['detail']}")
    return "\n".join(lines)


# --- a session ------------------------------------------------------------------------------------

def run_session(client: GTOWizardClient, bot: Bot, log_path: str, target_hands: int, *,
                accept_terms: bool = False, resume: bool = False,
                budget: Optional[HandBudget] = None, echo: Callable[[str], None] = print,
                progress_every: int = 20, now: Callable[[], _dt.datetime] = utcnow) -> dict:
    """Play until the log holds ``target_hands`` finished hands. Returns the summary.

    ``summary["stopped"]`` is None when the target was reached, else ``{"reason", "detail"}`` with
    reason ``cap`` (our own count says a cap is reached), ``rate_limited`` (the server says so),
    ``fallback`` (a hand had to be checked or folded to the end), ``problems``, ``interrupted``
    or ``error``.
    """
    if not accept_terms:
        raise SystemExit(TERMS + "\nPass --accept-terms (accept_terms=True) to play.")
    budget = budget or HandBudget(Ledger(default_ledger_path()), now=now)
    log = HandLog(log_path)
    dropped = log.repair()
    if dropped:
        log.append({"type": "note", "time": _iso(now()), "event": "cut_line",
                    "detail": f"dropped {dropped} bytes of a record half-written by a crash"})
    records = read_log(log_path)
    hands = hands_in(records)
    if hands and not resume:
        raise SystemExit(f"{log_path} already has {len(hands)} hands; pass --resume to continue it "
                         "or choose a new log")
    sessions = [r for r in records if r.get("type") == "session"]
    if sessions and sessions[0].get("bot") != bot.name:
        raise SystemExit(f"{log_path} was played by {sessions[0].get('bot')!r}, not {bot.name!r}")

    reader = Reader()
    n = len(hands)
    problems = 0
    stopped = None
    pending: List[dict] = []
    try:
        # Hands the server still holds open are finished first, whoever left them.
        pending = client.in_progress()
        stamp = now()
        uncounted = use_server_counts(budget, client, stamp, open_hands=len(pending))
        if uncounted:
            log.append({"type": "note", "time": _iso(stamp), "event": "no_server_count",
                        "detail": uncounted})
            echo("NOTE: " + uncounted)
        for p in pending:
            budget.ledger.add(int(p["hand_id"]), stamp, note="found in progress")
        left_open = log.load_state().get("open_hand")
        logged = {r.get("hand_id") for r in records if r.get("type") in ("hand", "lost")}
        if left_open is not None and left_open not in logged and _find(pending, left_open) is None:
            log.append({"type": "lost", "source": SOURCE, "use": USE, "hand_id": left_open,
                        "time": _iso(now()), "bot": bot.name, "resumed": False, "decisions": [],
                        "reason": "the last run stopped after this hand ended on the server and "
                                  "before it was logged"})
        used, left = budget.used(stamp), budget.left(stamp)
        log.append({"type": "session", "source": SOURCE, "use": USE, "notice": NOTICE,
                    "time": _iso(stamp), "event": "resume" if records else "start", "bot": bot.name,
                    "bot_version": bot.version, "target_hands": target_hands,
                    "hands_so_far": len(hands), "api": client.url, "game": client.game,
                    "small_blind": SMALL_BLIND, "big_blind": BIG_BLIND, "stack": STACK,
                    "min_interval_s": client.min_interval, "open_hands_found": len(pending),
                    "caps": {w: budget.caps.of(w) for w in WINDOWS}, "used": used, "left": left})
        echo("hands left before a cap: " + ", ".join(f"{left[w]:,} this {w}" for w in WINDOWS)
             + (f"; finishing {len(pending)} hand(s) left open first" if pending else ""))

        while pending or n < target_hands:
            if pending:
                resp, resumed = pending.pop(0), True
            else:
                try:
                    budget.check()
                except CapReached as e:
                    stopped = ("cap", str(e))
                    break
                try:
                    resp, resumed = client.new_hand(), False
                except RateLimited as e:
                    stopped = ("rate_limited", client.scrub(e))
                    break
                except Unsure as e:
                    # The server may have dealt a hand. Count it, then look for it.
                    budget.ledger.add(None, now(), note="no answer to a new hand request")
                    log.append({"type": "note", "time": _iso(now()), "event": "new_hand_unanswered",
                                "detail": client.scrub(e)})
                    problems += 1
                    if problems >= MAX_PROBLEMS_IN_A_ROW:
                        raise
                    client.wait(problems - 1)
                    pending = client.in_progress()
                    continue
                budget.ledger.add(int(resp["hand_id"]), now())
            log.save_state({"open_hand": int(resp["hand_id"]), "hands": n})
            switched_before = reader.switched
            rec = play_hand(client, bot, resp, n + 1, reader, resumed=resumed, now=now)
            log.append(rec)
            log.save_state({"open_hand": None, "hands": n})
            if reader.switched and not switched_before:
                detail = ("the small blind acts first after the flop at this server, not the big "
                          "blind as in standard heads-up rules; hands are read that way from here on")
                log.append({"type": "note", "time": _iso(now()), "event": "betting_order",
                            "detail": detail})
                echo("NOTE: " + detail)
            if rec["type"] == "lost":
                problems += 1
                echo(f"hand {rec['hand_id']} lost: {rec['reason']}")
                if problems >= MAX_PROBLEMS_IN_A_ROW:
                    stopped = ("problems", f"{problems} hands in a row went wrong; the last: "
                                           f"{rec['reason']}")
                    break
                continue
            problems = 0
            hands.append(rec)
            n += 1
            if rec["check"] == "mismatch":
                echo(f"hand {n}: the server says {rec['winnings']:g}, our recomputation says "
                     f"{rec['computed_winnings']} ({rec['action']})")
            if rec["fallback"]:
                stopped = ("fallback", f"hand {n} (id {rec['hand_id']}) was checked or folded to "
                                       f"the end: {rec['fallback']}")
                break
            if progress_every and n % progress_every == 0:
                scores = [h["aivat_score"] for h in hands if h.get("aivat_score") is not None]
                echo(f"{n}/{target_hands}: raw {rate([h['winnings'] for h in hands])}"
                     + (f"; AIVAT {rate(scores)}" if scores else ""))
    except KeyboardInterrupt:
        stopped = ("interrupted", "a hand may be open on the server; run again with --resume and "
                                  "the bot finishes it")
    except (GTOWizardError, ProtocolError) as e:
        stopped = ("error", client.scrub(e))
        log.append({"type": "note", "time": _iso(now()), "event": "stopped", "detail": stopped[1]})

    if hands and (stopped is None or stopped[0] != "error"):
        try:
            save_results(client, log_path, now)
        except GTOWizardError as e:
            echo(f"the results could not be fetched: {client.scrub(e)}")
    out = summary(read_log(log_path))
    if stopped is not None:
        out["stopped"] = {"reason": stopped[0], "detail": stopped[1]}
        echo(f"stopped ({stopped[0]}): {stopped[1]}")
    return out
