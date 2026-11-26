"""Where a hand comes from, which session it belongs to and which split it goes to.

Splits are decided per session group, never per hand, so hands from one sitting can't end
up on both sides of a train/test line."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Tuple

SPLITS = (("train", 0.8), ("validation", 0.1), ("test", 0.1))


def source_of(rel_path: str) -> str:
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) > 1 and parts[0] == "data":
        parts = parts[1:]
    head = parts[0]
    if head in ("pluribus", "handhq", "wsop"):
        return head
    return "historical"


def stakes_of(rel_path: str, data: Dict[str, Any]) -> str:
    m = re.search(r"_(\d+)NLH_", rel_path)
    if m:
        return f"{m.group(1)}NL"
    blinds = [b for b in data.get("blinds_or_straddles", []) if b]
    return "/".join(str(b) for b in sorted(blinds)[:2]) if blinds else "?"


def session_of(source: str, rel_path: str, data: Dict[str, Any]) -> str:
    """The group a hand is split with.
    pluribus: the day folder; '100' and '100b' were played on the same day by the same
      people, so they are one group.
    handhq: site, stakes and calendar day (the logs carry no real table ids, so a day at a
      stake is the tightest group that is sure to hold a whole sitting).
    wsop / historical: one group each (evaluation only)."""
    p = rel_path.replace("\\", "/")
    if source == "pluribus":
        m = re.search(r"pluribus/(\d+)", p)
        return f"pluribus/{m.group(1) if m else 'unknown'}"
    if source == "handhq":
        day = f"{data.get('year', '?')}-{data.get('month', '?'):>02}-{data.get('day', '?'):>02}"
        return f"handhq/{data.get('venue', '?')}/{stakes_of(p, data)}/{day}"
    if source == "wsop":
        m = re.search(r"wsop/(\d+)/(\d+)/(\d+)", p)
        return "wsop/" + ("/".join(m.groups()) if m else "unknown")
    return "historical"


def split_of(session: str, source: str) -> str:
    if source in ("wsop", "historical"):
        return "evaluation"  # too few hands to split; kept for spot checks
    h = int(hashlib.sha1(session.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    edge = 0.0
    for name, share in SPLITS:
        edge += share
        if h < edge:
            return name
    return SPLITS[-1][0]


def player_id(source: str, name: Any) -> str:
    """A stable pseudonym: the same player keeps the same id across hands of one source,
    and the raw name never leaves the pipeline."""
    return hashlib.sha1(f"phh:{source}:{name}".encode()).hexdigest()[:12]


IDENTITY = ("venue", "table", "hand", "year", "month", "day", "time", "event", "seats", "players")
GAME = ("variant", "antes", "blinds_or_straddles", "min_bet", "starting_stacks", "actions")


def content_key(data: Dict[str, Any], session: str = "") -> str:
    """Same hand, same record: everything that identifies the hand (site, hand number,
    time, players, session) plus everything that happened in it. Two different hands that
    happen to play out the same way (a walk between the same two players) differ here."""
    keep = {k: data.get(k) for k in IDENTITY + GAME}
    keep["_session"] = session
    return hashlib.sha1(repr(sorted(keep.items())).encode()).hexdigest()[:20]


def id_key(source: str, data: Dict[str, Any]) -> Tuple[str, ...] | None:
    """Site hand numbers are unique per site: two copies of one hand share it even when one
    copy shows more cards than the other."""
    if source == "handhq" and data.get("hand") is not None and data.get("venue"):
        return ("handhq", str(data["venue"]), str(data["hand"]))
    return None
