"""Read .phh (one hand) and .phhs (many hands) files one hand at a time.

A broken hand never stops the file: each hand is parsed on its own and comes back either
with its data or with the error that stopped it."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

from pokerkit.utilities import parse_value  # ints stay ints, decimals and inf exact

HEADER = re.compile(r"^\[(\d+)\][ \t]*$", re.M)
REQUIRED = ("variant", "antes", "blinds_or_straddles", "min_bet", "starting_stacks", "actions")


@dataclass
class RawHand:
    path: str  # relative to the dataset root
    index: int  # 1-based position inside the file
    text: str
    data: Optional[Dict[str, Any]]
    error: Optional[str] = None


def parse_block(path: str, index: int, block: str) -> RawHand:
    try:
        data = tomllib.loads(block, parse_float=parse_value)
    except (tomllib.TOMLDecodeError, ValueError, TypeError) as exc:
        return RawHand(path, index, block, None, f"toml: {str(exc)[:120]}")
    if "variant" not in data:
        return RawHand(path, index, block, None, "missing fields: variant")
    if data["variant"] != "NT":
        return RawHand(path, index, block, data)  # other games: counted, not replayed
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        return RawHand(path, index, block, None, f"missing fields: {', '.join(missing)}")
    if not isinstance(data["actions"], list) or not all(isinstance(a, str) for a in data["actions"]):
        return RawHand(path, index, block, None, "actions is not a list of strings")
    n = len(data["starting_stacks"])
    for key in ("antes", "blinds_or_straddles"):
        if isinstance(data[key], list) and len(data[key]) != n:
            return RawHand(path, index, block, None, f"{key} has {len(data[key])} entries for {n} players")
    if "players" in data and isinstance(data["players"], list) and len(data["players"]) != n:
        return RawHand(path, index, block, None, f"players has {len(data['players'])} entries for {n} players")
    return RawHand(path, index, block, data)


def iter_file(path: str, root: str) -> Iterator[RawHand]:
    rel = os.path.relpath(path, root)
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8", errors="replace")
    except OSError as exc:
        yield RawHand(rel, 0, "", None, f"unreadable file: {exc}")
        return
    if path.endswith(".phhs"):
        heads = list(HEADER.finditer(text))
        if not heads:
            yield RawHand(rel, 0, text[:200], None, "no [n] hand headers in a .phhs file")
            return
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            yield parse_block(rel, int(m.group(1)), text[m.end():end])
    else:
        yield parse_block(rel, 1, text)


def iter_paths(root: str) -> Iterator[str]:
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            if f.endswith((".phh", ".phhs")):
                yield os.path.join(dirpath, f)
