"""Answer-key spots: read, check and hash them, and work out their betting trees.

The format is in data/SPOT_FORMAT.md. A river spot is RiverSpot.to_dict() (app/solver)
plus a few fields of its own, so RiverSpot.from_dict reads it as it is. A turn spot adds
the river's bet sizes and a fourth board card instead of a fifth.

The tree here follows app/solver/tree.py street by street (the same sizes, caps, min-raise
rule and amount rounding, through its own `_amounts`), and adds the river card between
the streets of a turn spot. For a river spot it gives exactly GameTree's decision nodes;
a test checks that.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.poker.ranges import class_combos, parse_range
from app.solver.ranking import RANK_INDEX
from app.solver.spot import IP, OOP, PLAYER_NAMES, BetSizes, RiverSpot, check_card, combo_text, parse_combo
from app.solver.tree import _amounts, fmt_amount

FORMAT = "pokerscribe-spot"
VERSION = 1
STREETS = ("turn", "river")
BOARD_LEN = {"turn": 4, "river": 5}
RANKS = "23456789TJQKA"
SUITS = "cdhs"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPOTS_DIR = os.path.join(ROOT, "data", "answer_keys", "spots")
RESULTS_DIR = os.path.join(ROOT, "data", "answer_keys", "texassolver")


class SpotError(ValueError):
    pass


# ------------------------------------------------------------------- ranges
def expand_range_text(text: str, board: Sequence[str]) -> Dict[str, float]:
    """'QQ+, AKs:0.5, 76s-54s:0.25' -> {combo: weight}. Items are separated by commas; an
    item is app/poker/ranges.py notation with an optional ':weight' (default 1). A combo
    listed twice keeps its first weight; combos that touch the board, and weight 0, are
    dropped (the RiverSpot rules)."""
    dead = set(board)
    out: Dict[str, float] = {}
    for raw in text.split(","):
        item = raw.strip()
        if not item:
            continue
        token, _, w = item.partition(":")
        weight = float(w) if w.strip() else 1.0
        if not math.isfinite(weight) or weight < 0 or weight > 1:
            raise SpotError(f"Weight must be between 0 and 1: {item!r}")
        for combo in parse_range(token.strip()):
            c = parse_combo(combo)
            key = combo_text(c)
            if weight == 0 or c[0] in dead or c[1] in dead or key in out:
                continue
            out[key] = weight
    return out


def hand_class(combo: str) -> str:
    """'AhKh' -> 'AKs', 'KdAc' -> 'AKo', 'QsQd' -> 'QQ'."""
    a, b = parse_combo(combo)
    if a[0] == b[0]:
        return a[0] + b[0]
    hi, lo = (a, b) if RANK_INDEX[a[0]] > RANK_INDEX[b[0]] else (b, a)
    return hi[0] + lo[0] + ("s" if a[1] == b[1] else "o")


def class_weights(combos: Mapping[str, float], board: Sequence[str]) -> List[Tuple[str, float]]:
    """The range as whole hand classes, [(class, weight)], strongest class first.

    Raises SpotError unless every class is whole: every combo of the class that misses
    the board is in the range, all with the same weight. TexasSolver reads ranges by
    class, so only such ranges can be given to it exactly."""
    dead = set(board)
    by_class: Dict[str, Dict[frozenset, float]] = {}
    for key, w in combos.items():
        by_class.setdefault(hand_class(key), {})[frozenset(parse_combo(key))] = float(w)
    out = []
    for cls, got in by_class.items():
        live = {frozenset(c) for c in class_combos(cls) if c[0] not in dead and c[1] not in dead}
        if set(got) != live:
            raise SpotError(f"{cls}: only {len(got)} of its {len(live)} combos are in the range.")
        weights = set(got.values())
        if len(weights) != 1:
            raise SpotError(f"{cls}: its combos have different weights {sorted(weights)}.")
        out.append((cls, weights.pop()))

    def strength(item):
        cls = item[0]
        pair = cls[0] == cls[1]
        return (pair, RANK_INDEX[cls[0]], RANK_INDEX[cls[1]], cls.endswith("s"))

    return sorted(out, key=strength, reverse=True)


# --------------------------------------------------------------- the spot
def validate_spot(d: Mapping) -> None:
    """Raise SpotError when a spot doesn't follow data/SPOT_FORMAT.md."""
    if d.get("format") != FORMAT or d.get("version") != VERSION:
        raise SpotError(f"Not a {FORMAT} version {VERSION} spot.")
    for key in ("id", "street", "board", "pot", "stacks", "ranges", "sizes", "max_raises"):
        if key not in d:
            raise SpotError(f"Missing {key!r}.")
    street = d["street"]
    if street not in STREETS:
        raise SpotError(f"street must be one of {STREETS}.")
    board = [check_card(c) for c in d["board"]]
    if len(board) != BOARD_LEN[street] or len(set(board)) != len(board):
        raise SpotError(f"A {street} spot needs {BOARD_LEN[street]} different board cards.")
    if not (isinstance(d["pot"], (int, float)) and d["pot"] > 0):
        raise SpotError("pot must be more than 0.")
    if len(d["stacks"]) != 2 or any(not isinstance(s, (int, float)) or s <= 0 for s in d["stacks"]):
        raise SpotError("stacks are two amounts over 0: [oop, ip].")
    if not isinstance(d["max_raises"], int) or d["max_raises"] < 0:
        raise SpotError("max_raises is a whole number, 0 or more.")
    for name in PLAYER_NAMES:
        rng = d["ranges"].get(name)
        if not rng:
            raise SpotError(f"The {name} range is empty.")
        for key, w in rng.items():
            c = parse_combo(key)
            if combo_text(c) != key:
                raise SpotError(f"{key!r} isn't written canonically ({combo_text(c)!r}).")
            if c[0] in board or c[1] in board:
                raise SpotError(f"{key} uses a board card.")
            if not (isinstance(w, (int, float)) and 0 < w <= 1):
                raise SpotError(f"{key}: weight must be over 0 and at most 1.")
        text = d.get("range_text", {}).get(name)
        if text is not None and expand_range_text(text, board) != dict(rng):
            raise SpotError(f"The {name} range doesn't match its range_text.")
    for street_name in streets_of(d):
        for p in (OOP, IP):
            sizes(d, p, street_name)
    if street == "river":
        RiverSpot.from_dict(d)
    elif "river_sizes" not in d:
        raise SpotError("A turn spot needs river_sizes.")
    for check in d.get("expected", []):
        for key in ("nodes", "actor", "action"):
            if key not in check:
                raise SpotError(f"An expected check is missing {key!r}.")
        if check["actor"] not in ("oop", "ip", "any") or check["action"] not in ("x", "c", "f", "b", "r"):
            raise SpotError(f"Bad expected check {check!r}.")
        if "min" not in check and "max" not in check:
            raise SpotError("An expected check needs min or max.")


def streets_of(d: Mapping) -> Tuple[str, ...]:
    return ("turn", "river") if d["street"] == "turn" else ("river",)


def sizes(d: Mapping, player: int, street: str) -> BetSizes:
    block = d["river_sizes"] if (d["street"] == "turn" and street == "river") else d["sizes"]
    s = BetSizes.from_dict(block[PLAYER_NAMES[player]])
    if any(f < 0.5 for f in s.raises):
        raise SpotError("Raise sizes under 0.5 of the pot after calling aren't allowed (see SPOT_FORMAT.md).")
    return s


def load_spot(path: str) -> dict:
    with open(path) as f:
        d = json.load(f)
    validate_spot(d)
    return d


def spot_paths(spots_dir: str = SPOTS_DIR) -> List[str]:
    return sorted(os.path.join(spots_dir, n) for n in os.listdir(spots_dir) if n.endswith(".json"))


def load_spots(spots_dir: str = SPOTS_DIR, ids: Optional[Iterable[str]] = None) -> List[dict]:
    spots = [load_spot(p) for p in spot_paths(spots_dir)]
    if ids:
        wanted = list(ids)
        known = {s["id"] for s in spots}
        missing = [i for i in wanted if i not in known]
        if missing:
            raise SpotError(f"No spot called {', '.join(missing)}.")
        spots = [s for s in spots if s["id"] in wanted]
    return spots


def canonical_json(d: Mapping) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def spot_hash(d: Mapping) -> str:
    """sha256 of the spot's canonical JSON: an answer key belongs to exactly this spot."""
    return hashlib.sha256(canonical_json(d).encode()).hexdigest()


def river_spot(d: Mapping) -> RiverSpot:
    if d["street"] != "river":
        raise SpotError(f"{d['id']} is a {d['street']} spot.")
    return RiverSpot.from_dict(d)


def deck_left(board: Sequence[str]) -> List[str]:
    """The cards that can still come, in a fixed order (2c 2d 2h 2s 3c ...)."""
    used = set(board)
    return [r + s for r in RANKS for s in SUITS if r + s not in used]


# -------------------------------------------------------------- the tree
@dataclass(frozen=True)
class Decision:
    key: str
    street: str
    actor: str  # "oop" or "ip"
    actions: Tuple[str, ...]
    pot: float  # pot at the start of this street
    stack: float  # effective stack left at the start of this street
    put_in: Tuple[float, float]  # chips put in on this street so far


@dataclass(frozen=True)
class StreetEnd:
    key: str
    called: float  # what each player put in on the street
    fold: bool


def _street(d: Mapping, street: str, prefix: str, pot: float, stack: float,
            out: Dict[str, Decision], ends: List[StreetEnd]) -> None:
    max_raises = d["max_raises"]

    def build(key: str, player: int, put: Tuple[float, float], raises: int, checked: bool) -> None:
        other = 1 - player
        mine, theirs = put[player], put[other]
        sz = sizes(d, player, street)
        actions: List[str] = []

        def join(token: str) -> str:
            actions.append(token)
            return f"{key} {token}".strip()

        if theirs <= mine + 1e-9:
            k = join("x")
            if checked or player == IP:
                ends.append(StreetEnd(k, put[0], False))
            else:
                build(k, other, put, raises, True)
            for amount in _amounts([f * pot for f in sz.bets], stack, sz.allin, floor=0.0):
                new = list(put)
                new[player] = amount
                build(join("b" + fmt_amount(amount)), other, (new[0], new[1]), raises, checked)
        else:
            ends.append(StreetEnd(join("f"), 0.0, True))
            ends.append(StreetEnd(join("c"), theirs, False))
            if raises < max_raises and theirs < stack - 1e-9:
                after_call = pot + 2 * theirs
                least = theirs + (theirs - mine)
                wanted = [max(least, theirs + f * after_call) for f in sz.raises]
                for amount in _amounts(wanted, stack, sz.allin, floor=theirs):
                    new = list(put)
                    new[player] = amount
                    build(join("r" + fmt_amount(amount)), other, (new[0], new[1]), raises + 1, checked)
        out[key] = Decision(key, street, PLAYER_NAMES[player], tuple(actions), pot, stack, put)

    build(prefix, OOP, (0.0, 0.0), 0, False)


def decision_nodes(d: Mapping) -> Dict[str, Decision]:
    """Every decision node of the spot, keyed as in data/SPOT_FORMAT.md."""
    out: Dict[str, Decision] = {}
    pot, stack = float(d["pot"]), float(min(d["stacks"]))
    if d["street"] == "river":
        _street(d, "river", "", pot, stack, out, [])
        return out
    ends: List[StreetEnd] = []
    _street(d, "turn", "", pot, stack, out, ends)
    for end in ends:
        if end.fold or end.called >= stack - 1e-9:
            continue  # the hand is over, or all in with no more betting
        for card in deck_left(d["board"]):
            _street(d, "river", f"{end.key} {card}".strip(), pot + 2 * end.called, stack - end.called, out, [])
    return out


def capped_sizes(d: Mapping) -> List[str]:
    """Places where a size would be cut down to the all-in, or the min-raise rule would
    change a raise. The spots in this repo have none, so that every solver builds the
    same tree from the same sizes (see SPOT_FORMAT.md, "Sizes")."""
    problems = []
    pot0, stack0 = float(d["pot"]), float(min(d["stacks"]))

    def street_problems(street, prefix, pot, stack):
        for node in _street_nodes(d, street, prefix, pot, stack):
            p = 0 if node.actor == "oop" else 1
            sz = sizes(d, p, street)
            mine, theirs = node.put_in[p], node.put_in[1 - p]
            if theirs <= mine + 1e-9:
                for f in sz.bets:
                    if f * pot >= stack - 1e-9:
                        problems.append(f"{node.key!r}: a bet of {f} pot is {f * pot:g}, not under the stack {stack:g}")
            elif any(t.startswith("r") for t in node.actions):
                after_call = pot + 2 * theirs
                for f in sz.raises:
                    want = theirs + f * after_call
                    if want >= stack - 1e-9:
                        problems.append(f"{node.key!r}: a raise of {f} is to {want:g}, not under the stack {stack:g}")
                    if want < theirs + (theirs - mine) - 1e-9:
                        problems.append(f"{node.key!r}: a raise of {f} is under the min-raise")

    if d["street"] == "river":
        street_problems("river", "", pot0, stack0)
    else:
        street_problems("turn", "", pot0, stack0)
        ends: List[StreetEnd] = []
        _street(d, "turn", "", pot0, stack0, {}, ends)
        for end in ends:
            if not end.fold and end.called < stack0 - 1e-9:
                street_problems("river", end.key + " ?", pot0 + 2 * end.called, stack0 - end.called)
    return problems


def _street_nodes(d, street, prefix, pot, stack) -> List[Decision]:
    out: Dict[str, Decision] = {}
    _street(d, street, prefix, pot, stack, out, [])
    return list(out.values())


def integer_amounts(d: Mapping) -> List[str]:
    """Bet and raise amounts that aren't whole chips (the spots in this repo have none)."""
    bad = []
    for node in decision_nodes(d).values():
        for t in node.actions:
            if t[0] in "br" and abs(float(t[1:]) - round(float(t[1:]))) > 1e-9:
                bad.append(f"{node.key!r} {t}")
    return bad
