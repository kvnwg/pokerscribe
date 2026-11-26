"""Turn the definitions (defs.py) into SPOT files (data/SPOT_FORMAT.md)."""
from __future__ import annotations

import json
import os
from typing import Dict, List, Mapping

from app.poker.history import Line, StreetLine
from app.solver.ranges import river_ranges
from app.solver.spot import combo_text
from tools.answer_keys.build import KEY_ORDER, dumps_spot
from tools.answer_keys.spots import FORMAT, VERSION, SpotError, expand_range_text, validate_spot

from . import defs

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.path.join(ROOT, "data", "reference_spots", "python_solver")
SPOTS_DIR = os.path.join(HOME, "spots")
RESULTS_DIR = os.path.join(HOME, "results")
SIZE_KEYS = {"bets", "raises", "allin"}  # the only size fields SPOT_FORMAT.md describes


def _finish(d: Dict) -> Dict:
    d["format"], d["version"] = FORMAT, VERSION
    d["spr"] = round(min(d["stacks"]) / d["pot"], 2)
    if not d.get("expected"):
        d.pop("expected", None)
    out = {k: d[k] for k in KEY_ORDER if k in d}
    extra = set(d) - set(out)
    if extra:
        raise SpotError(f"{d['id']}: unknown fields {sorted(extra)}")
    for player, sizes in out["sizes"].items():
        if set(sizes) != SIZE_KEYS:
            raise SpotError(f"{d['id']}: {player} sizes must have exactly {sorted(SIZE_KEYS)}.")
    validate_spot(out)
    return out


def build_spot(defn: Mapping) -> Dict:
    """A hand-written definition (range text) as a SPOT."""
    d = dict(defn)
    d["ranges"] = {p: expand_range_text(d["range_text"][p], d["board"]) for p in ("oop", "ip")}
    return _finish(d)


def line_numbers(defn: Mapping) -> Dict:
    """The river pot in big blinds and the stack-to-pot ratio a betting line leaves: both
    players put in the same before the flop (a raise and a call), `dead_bb` comes from
    players who folded, and each bet after the flop is called."""
    put_in = defn["preflop"][0]
    pot = 2 * put_in + defn["dead_bb"]
    for street in ("flop", "turn"):
        bet = defn[street][0] * pot
        put_in += bet
        pot += 2 * bet
    return {"pot_bb": pot, "spr": (defs.STACK_BB - put_in) / pot}


def build_line_spot(defn: Mapping) -> Dict:
    """One of the spots with the app's own ranges: what app/solver/ranges.py makes of the
    betting line, at the stack-to-pot ratio the line leaves, with the app's bet sizes."""
    board = defn["board"].split()
    line = Line(*(StreetLine(float(size), who) for size, who in (defn["preflop"], defn["flop"], defn["turn"])),
                river=())
    numbers = line_numbers(defn)
    hero_ip = defs_position(defn)
    est = river_ranges(board, line, hero_in_position=hero_ip, pot_bb=numbers["pot_bb"],
                       hero_seat=defn["hero_seat"], villain_seat=defn["villain_seat"])
    ranges = {"ip" if hero_ip else "oop": est.hero, "oop" if hero_ip else "ip": est.villain}
    stack = round(numbers["spr"] * defs.POT)
    return _finish({"id": defn["id"], "street": "river", "title": defn["title"], "tags": list(defn["tags"]),
                    "board": board, "pot": defs.POT, "stacks": [stack, stack], "max_raises": 1,
                    "sizes": {"oop": dict(defs.APP_SIZES), "ip": dict(defs.APP_SIZES)},
                    "ranges": {p: {combo_text(c): float(w) for c, w in ranges[p]} for p in ("oop", "ip")}})


ORDER = ["SB", "BB", "UTG", "HJ", "CO", "BTN"]  # who acts first after the flop


def defs_position(defn: Mapping) -> bool:
    """Whether the app's seat acts last on the river."""
    return ORDER.index(defn["hero_seat"]) > ORDER.index(defn["villain_seat"])


def write_spot(spot: Mapping, spots_dir: str = SPOTS_DIR) -> str:
    os.makedirs(spots_dir, exist_ok=True)
    path = os.path.join(spots_dir, spot["id"] + ".json")
    with open(path, "w") as f:
        f.write(dumps_spot(spot))
    return path


def write_spots(spots_dir: str = SPOTS_DIR, lines: bool = False) -> List[str]:
    """The hand-written spots, always. The app-range spots only with lines=True: they are
    made once and then kept as they are (see defs.py)."""
    ids = [d["id"] for d in defs.SPOTS] + [d["id"] for d in defs.LINES]
    if len(set(ids)) != len(ids):
        raise SpotError("Two spots share an id.")
    paths = [write_spot(build_spot(d), spots_dir) for d in defs.SPOTS]
    if lines:
        paths += [write_spot(build_line_spot(d), spots_dir) for d in defs.LINES]
    return paths


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
