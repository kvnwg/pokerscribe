"""Replay one No-Limit Hold'em hand with PokerKit and cut it into decision points.

Each decision point holds only what the acting player could see at that moment: their own
hole cards (when the history has them), the board so far, every stack and bet on the
table, the pot, the actions so far and the legal options. It never holds anyone else's
cards, later board cards, later actions or the result of the hand. The action the player
then took is stored as `action`: what happened, not what was best."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from pokerkit import HandHistory
from pokerkit.notation import parse_action

from .reader import RawHand
from .sources import content_key, player_id, session_of, source_of, split_of, stakes_of

STREETS = ("preflop", "flop", "turn", "river")
PLAYER_ACTIONS = ("f", "cc", "cbr")
# the fields a decision is made from; everything else is bookkeeping or the label
FEATURES = ("n_players", "n_active", "street", "position", "seat", "actor_id", "actor_is_pluribus", "opponents",
            "hole_cards", "board", "bb", "pot_bb", "to_call_bb", "stack_bb", "bet_bb", "eff_stack_bb",
            "history", "can_fold", "can_check", "can_call", "can_raise", "min_raise_to_bb", "max_raise_to_bb")
LABEL = ("action", "amount_to_bb", "amount_added_bb", "size_of_pot", "all_in")


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    f = float(v)
    return None if math.isinf(f) or math.isnan(f) else f


def _bb(v: Optional[float], bb: float) -> Optional[float]:
    return None if v is None else round(v / bb, 4)


def _cards(cards) -> Optional[str]:
    s = "".join(repr(c) for c in cards)
    return s if s and "?" not in s else None


def position_names(n: int, posted: List[float]) -> List[str]:
    """Seat names in PHH order. With 3 or more players p1 is the small blind and the last
    player the button; heads-up the button posts the small blind."""
    if n == 2:
        names = ["BB", "BB"]
        names[0 if posted[0] < posted[1] else 1] = "BTN/SB"
        return names
    k = n - 3
    late = ["CO", "HJ", "LJ"]
    middle = []
    for i in range(k):
        from_end = k - 1 - i
        if k >= 3 and i == 0:
            middle.append("UTG")
        elif from_end < 3:
            middle.append(late[from_end])
        else:
            middle.append(f"UTG+{i}")
    return ["SB", "BB"] + middle + ["BTN"]


def _advance(state) -> None:
    """Dealer chores PokerKit leaves to the caller: antes, blinds, collecting bets, burning.
    Player actions are never made up here: a history with a missing action is rejected."""
    for _ in range(64):
        if state.can_post_ante():
            state.post_ante()
        elif state.can_collect_bets():
            state.collect_bets()
        elif state.can_post_blind_or_straddle():
            state.post_blind_or_straddle()
        elif state.can_burn_card():
            state.burn_card("??")
        else:
            return


def _known(cards: str) -> List[str]:
    return [cards[i:i + 2] for i in range(0, len(cards) - 1, 2) if "?" not in cards[i:i + 2]]


def hand_decisions(raw: RawHand) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(decision records, hand info). info["status"] is "ok", "not_nlhe", "corrupt" or
    "out_of_turn" (an action is missing, so later decisions would carry a wrong history)."""
    data = raw.data or {}
    src = source_of(raw.path)
    info: Dict[str, Any] = {"source": src, "status": "ok", "variant": data.get("variant"), "decisions": 0}
    if data.get("variant") != "NT":
        info["status"] = "not_nlhe"
        return [], info
    n = len(data["starting_stacks"])
    info["n_players"] = n
    try:
        hh = HandHistory(**HandHistory._filter_non_fields(**data))
        state = hh.create_state()
        _advance(state)
    except Exception as exc:  # PokerKit refuses the setup (bad stacks, blinds ...)
        info.update(status="corrupt", error=f"setup: {str(exc)[:140]}")
        return [], info
    posted = [float(b) for b in state.bets]
    names = position_names(n, posted)
    bb = _num(data.get("min_bet")) or max(posted[:2] or [0.0]) or None
    if not bb:
        info.update(status="corrupt", error="no big blind")
        return [], info
    players = data.get("players") or [f"p{i + 1}" for i in range(n)]
    ids = [player_id(src, p) for p in players]
    pluribus = [str(p) == "Pluribus" for p in players]
    session = session_of(src, raw.path, data)
    base = {"hand_uid": content_key(data, session), "source": src, "venue": data.get("venue"),
            "stakes": stakes_of(raw.path, data), "session": session, "split": split_of(session, src),
            "file": raw.path, "hand_index": raw.index}
    info.update(hand_uid=base["hand_uid"], session=session, split=base["split"], stakes=base["stakes"],
                players=ids, venue=data.get("venue"))

    seen_cards: set = set()
    history: List[str] = []
    records: List[Dict[str, Any]] = []
    known_hole = 0
    for action in data["actions"]:
        words = action.split("#")[0].split()
        if not words:
            continue
        if words[0] == "d" and len(words) >= 3 and words[1] in ("dh", "db"):
            cards = _known(words[-1])
            if words[1] == "dh":
                known_hole += len(cards)
            dup = seen_cards.intersection(cards)
            if dup or len(set(cards)) != len(cards):
                info.update(status="corrupt", error=f"card dealt twice: {sorted(dup) or cards}")
                return [], info
            seen_cards.update(cards)
        try:
            _advance(state)
        except Exception as exc:
            info.update(status="corrupt", error=f"dealer step before {action!r}: {str(exc)[:120]}")
            return [], info
        is_decision = len(words) >= 2 and words[0].startswith("p") and words[1] in PLAYER_ACTIONS
        rec = None
        if is_decision:
            try:
                a = int(words[0][1:]) - 1
            except ValueError:
                info.update(status="corrupt", error=f"bad player label in {action!r}")
                return [], info
            if state.actor_index != a:
                info.update(status="out_of_turn", error=f"{action!r} while p{(state.actor_index or -1) + 1} was to act")
                return [], info
            rec = dict(base)
            rec.update(_features(state, a, names, bb, history, ids, pluribus))
            rec.update(_label(state, a, words, bb))
        try:
            parse_action(state, action, hh.parse_value)
        except Exception as exc:
            if words[0] == "d" and state.actor_index is not None:
                # cards dealt while a player still had to act: an action is missing
                info.update(status="out_of_turn",
                            error=f"{action!r} while p{state.actor_index + 1} was still to act")
            else:
                info.update(status="corrupt", error=f"{action!r}: {str(exc)[:120]}")
            return [], info
        if rec is not None:
            records.append(rec)
            history.append(_token(rec, names[rec["seat"]]))
    info["decisions"] = len(records)
    info["known_hole_cards"] = known_hole
    return records, info


def _features(state, a: int, names: List[str], bb: float, history: List[str], ids: List[str],
              pluribus: List[bool]) -> Dict[str, Any]:
    si = state.street_index
    street = STREETS[si] if si is not None and 0 <= si < 4 else f"street{si}"
    stacks = [_num(s) for s in state.stacks]
    bets = [_num(b) or 0.0 for b in state.bets]
    active = [i for i, s in enumerate(state.statuses) if s]
    opp = [i for i in active if i != a]
    behind = stacks[a]
    eff = None
    if behind is not None and opp and all(stacks[i] is not None for i in opp):
        eff = min(behind + bets[a], max(stacks[i] + bets[i] for i in opp))
    to_call = _num(state.checking_or_calling_amount) or 0.0
    can_raise = bool(state.can_complete_bet_or_raise_to())
    mn = _num(state.min_completion_betting_or_raising_to_amount) if can_raise else None
    mx = _num(state.max_completion_betting_or_raising_to_amount) if can_raise else None
    return {
        "n_players": len(stacks), "n_active": len(active), "street": street, "position": names[a], "seat": a,
        "actor_id": ids[a], "actor_is_pluribus": pluribus[a],
        "opponents": [f"{names[i]}={ids[i]}" for i in opp],
        "hole_cards": _cards(state.hole_cards[a]),
        "board": "".join(repr(c) for c in state.get_board_cards(0)),
        "bb": bb, "pot_bb": _bb(_num(state.total_pot_amount), bb), "to_call_bb": _bb(to_call, bb),
        "stack_bb": _bb(behind, bb), "bet_bb": _bb(bets[a], bb), "eff_stack_bb": _bb(eff, bb),
        "history": list(history),
        "can_fold": bool(state.can_fold()) and to_call > 0, "can_check": to_call == 0,
        "can_call": to_call > 0, "can_raise": can_raise,
        "min_raise_to_bb": _bb(mn, bb), "max_raise_to_bb": _bb(mx, bb),
    }


def _label(state, a: int, words: List[str], bb: float) -> Dict[str, Any]:
    bets = [_num(b) or 0.0 for b in state.bets]
    behind = _num(state.stacks[a])
    pot = _num(state.total_pot_amount) or 0.0
    to_call = _num(state.checking_or_calling_amount) or 0.0
    kind = words[1]
    to = None
    if kind == "f":
        act = "fold"
    elif kind == "cc":
        act = "check" if to_call == 0 else "call"
        to = bets[a] + to_call
    else:
        to = float(words[2]) if len(words) > 2 else None
        act = "raise" if max(bets) > 0 else "bet"
    added = None if to is None else to - bets[a]
    if act in ("bet", "raise") and added is not None:
        call_part = max(bets) - bets[a]
        size = (to - max(bets)) / (pot + call_part) if pot + call_part > 0 else None
    else:
        size = None
    all_in = bool(added is not None and behind is not None and act != "check" and abs(added - behind) < 1e-6)
    return {"action": act, "amount_to_bb": _bb(to, bb), "amount_added_bb": _bb(added, bb),
            "size_of_pot": None if size is None else round(size, 4), "all_in": all_in,
            "label_source": "observed"}


def _token(rec: Dict[str, Any], pos: str) -> str:
    code = {"fold": "f", "check": "x", "call": "c", "bet": "b", "raise": "r"}[rec["action"]]
    amt = f"{rec['amount_to_bb']:g}" if code in ("b", "r") and rec["amount_to_bb"] is not None else ""
    return f"{rec['street'][0]}:{pos}:{code}{amt}"


def leak_check(raw: RawHand, records: List[Dict[str, Any]]) -> Tuple[int, int]:
    """Rebuild every decision from a copy of the hand that stops right at it, with the other
    players' cards hidden and the result removed. Identical features mean nothing from later
    in the hand or from hidden cards got in. Returns (checked, mismatches)."""
    data = raw.data or {}
    acts = data.get("actions", [])
    checked = bad = 0
    k = -1
    for pos, action in enumerate(acts):
        words = action.split("#")[0].split()
        if not (len(words) >= 2 and words[0].startswith("p") and words[1] in PLAYER_ACTIONS):
            continue
        k += 1
        if k >= len(records):
            break
        actor = words[0]
        cut = []
        for x in acts[:pos + 1]:
            w = x.split("#")[0].split()
            if len(w) >= 4 and w[0] == "d" and w[1] == "dh" and w[2] != actor:
                x = f"d dh {w[2]} " + "?" * len(w[3])
            cut.append(x)
        trimmed = {key: v for key, v in data.items() if key not in ("finishing_stacks", "winnings", "actions")}
        trimmed["actions"] = cut
        again, _ = hand_decisions(RawHand(raw.path, raw.index, "", trimmed))
        checked += 1
        if not again or any(again[-1][f] != records[k][f] for f in FEATURES):
            bad += 1
    return checked, bad
