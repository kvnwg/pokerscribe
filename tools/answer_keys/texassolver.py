"""TexasSolver's console version as a black box: write its config, run it, read its output.

TexasSolver (github.com/bilibili/TexasSolver) is AGPL-3.0. It is installed outside the repo
(~/answer-keys) and only ever run as a separate program, given a config file. Nothing here
comes from its source: the config commands are the ones its README documents, and the
output is read as plain JSON.

What its output looks like, as this module reads it (data/answer_keys/README.md, "Quirks"):

- An action node: {"node_type": "action_node", "player": 0 or 1, "actions": ["CHECK",
  "BET 50.000000"], "childrens": {"CHECK": {...}, ...}, "strategy": {"actions": [...],
  "strategy": {"AhKd": [p, p], ...}}}. "children" is read as well as "childrens", and a
  bare {combo: [p, ...]} strategy as well as the nested one.
- A chance node (the river card of a turn spot): {"node_type": "chance_node",
  "dealcards": {"2c": {...}, ...}}.
- The end of the hand has no node, or one that is neither of those.

Which player TexasSolver calls 0 doesn't matter: the out of position player acts first on
each street and the players take turns, so the actor of every node is worked out here.

What a BET or RAISE amount means (chips put in on the street after the action, or added
by it, or added on top of the call, or put in since the start of the spot) isn't written
down anywhere, so every reading is tried and the one that rebuilds the spot's own tree
(spots.decision_nodes) is kept. If none does, the differences are reported and the spot
fails, because then TexasSolver solved a different game from the one in the spot.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from app.solver.spot import IP, OOP, PLAYER_NAMES, combo_text, parse_combo
from app.solver.tree import fmt_amount

from .result import node_record
from .spots import Decision, class_weights, decision_nodes, sizes, streets_of

DEFAULT_ACCURACY = 0.3  # stop at this exploitability, in percent of the pot
DEFAULT_MAX_ITERATIONS = 5000
DEFAULT_PRINT_INTERVAL = 10  # TexasSolver works out its exploitability every this many iterations


def _num(x: float) -> str:
    return f"{round(float(x), 6):g}"


def _pct(fractions) -> List[str]:
    return [_num(f * 100) for f in fractions]


def range_text(spot: Mapping, player: str) -> str:
    """The range as TexasSolver range text: 'AA,KK:0.5,AKs,...' (whole classes only)."""
    return ",".join(cls if w == 1 else f"{cls}:{_num(w)}" for cls, w in class_weights(spot["ranges"][player], spot["board"]))


def config_text(spot: Mapping, dump_path: str, threads: int = 0, accuracy: float = DEFAULT_ACCURACY,
                max_iterations: int = DEFAULT_MAX_ITERATIONS, print_interval: int = DEFAULT_PRINT_INTERVAL,
                raise_limit_extra: int = 0) -> str:
    """The TexasSolver console config for a spot.

    Sizes: the spot's sizes for the street it starts on are also given for the flop (never
    played, but some builds want every street set), and the out of position player's
    "donk" sizes are the same as its bets, so a lead is never sized differently from a bet.
    set_allin_threshold 1 makes only sizes at or over the stack all in, the app/solver rule.
    set_use_isomorphism 0 keeps every river card in the output of a turn spot."""
    threads = threads or os.cpu_count() or 1
    first = streets_of(spot)[0]
    lines = [
        f"set_pot {_num(spot['pot'])}",
        f"set_effective_stack {_num(min(spot['stacks']))}",
        "set_board " + ",".join(spot["board"]),
        "set_range_oop " + range_text(spot, "oop"),
        "set_range_ip " + range_text(spot, "ip"),
    ]
    for street in ("flop", "turn", "river"):
        source = first if street == "flop" or street not in streets_of(spot) else street
        for p in (OOP, IP):
            name = PLAYER_NAMES[p]
            sz = sizes(spot, p, source)
            if sz.bets:
                lines.append(f"set_bet_sizes {name},{street},bet," + ",".join(_pct(sz.bets)))
            if sz.raises:
                lines.append(f"set_bet_sizes {name},{street},raise," + ",".join(_pct(sz.raises)))
            if p == OOP and street != "flop" and sz.bets:
                lines.append(f"set_bet_sizes {name},{street},donk," + ",".join(_pct(sz.bets)))
            if sz.allin:
                lines.append(f"set_bet_sizes {name},{street},allin")
    lines += [
        "set_allin_threshold 1.0",
        f"set_raise_limit {spot['max_raises'] + raise_limit_extra}",
        "build_tree",
        f"set_thread_num {threads}",
        f"set_accuracy {_num(accuracy)}",
        f"set_max_iteration {int(max_iterations)}",
        f"set_print_interval {int(print_interval)}",
        "set_use_isomorphism 0",
        "start_solve",
        f"set_dump_rounds {len(streets_of(spot))}",
        f"dump_result {dump_path}",
    ]
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------- running
@dataclass
class Run:
    config_path: str
    dump_path: str
    log: str
    elapsed_s: float
    returncode: int


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_solver(spot: Mapping, solver: str, workdir: str, cwd: Optional[str] = None, timeout_s: float = 3600,
               extra_args: Tuple[str, ...] = (), **config_kw) -> Run:
    """Write the config under workdir and run `solver -i <config>` from cwd (default: the
    solver's own folder, where it looks for its resources folder)."""
    os.makedirs(workdir, exist_ok=True)
    config_path = os.path.abspath(os.path.join(workdir, spot["id"] + ".txt"))
    dump_path = os.path.abspath(os.path.join(workdir, spot["id"] + ".json"))
    if os.path.exists(dump_path):
        os.remove(dump_path)
    with open(config_path, "w") as f:
        f.write(config_text(spot, dump_path, **config_kw))
    solver = os.path.abspath(os.path.expanduser(solver))
    start = time.perf_counter()
    proc = subprocess.run([solver, "-i", config_path, *extra_args], cwd=cwd or os.path.dirname(solver),
                          capture_output=True, text=True, timeout=timeout_s)
    elapsed = time.perf_counter() - start
    log = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr.strip() else "")
    with open(os.path.join(workdir, spot["id"] + ".log"), "w") as f:
        f.write(log)
    return Run(config_path, dump_path, log, elapsed, proc.returncode)


_ITER = re.compile(r"iter(?:ation)?\s*:?\s*(\d+)", re.I)
_TOTAL = re.compile(r"total\s+exploitability\s*:?\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", re.I)
_ANY = re.compile(r"exploitability\s*:?\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", re.I)


def parse_log(text: str) -> List[Tuple[Optional[int], float]]:
    """[(iteration, exploitability in percent of the pot)] in the order printed. Uses the
    "Total exploitability" lines; if there are none, any line with "exploitability"."""
    out: List[Tuple[Optional[int], float]] = []
    loose: List[Tuple[Optional[int], float]] = []
    it: Optional[int] = None
    for line in text.splitlines():
        m = _ITER.search(line)
        if m:
            it = int(m.group(1))
        m = _TOTAL.search(line)
        if m:
            out.append((it, float(m.group(1))))
            continue
        m = _ANY.search(line)
        if m:
            loose.append((it, float(m.group(1))))
    return out or loose


# -------------------------------------------------------------------- output
class DumpError(ValueError):
    pass


_ACTION = re.compile(r"^\s*(CHECK|CALL|FOLD|BET|RAISE|ALLIN)\s*([-+]?\d+(?:\.\d+)?)?\s*$", re.I)

# street put-in after a BET or RAISE of `a`, given what the actor (mine) and the other
# player (theirs) have put in on the street, and what each put in on earlier streets (prev)
READINGS: Dict[str, Callable[[float, float, float, float], float]] = {
    "to": lambda a, mine, theirs, prev: a,
    "by": lambda a, mine, theirs, prev: mine + a,
    "over_call": lambda a, mine, theirs, prev: theirs + a,
    "to_since_start": lambda a, mine, theirs, prev: a - prev,
}


@dataclass
class Parsed:
    nodes: Dict[str, dict]
    reading: str
    differences: List[str]
    notes: List[str] = field(default_factory=list)


def _children(obj: Mapping) -> Mapping:
    return obj.get("childrens") or obj.get("children") or {}


def _is_action(obj) -> bool:
    return isinstance(obj, Mapping) and (obj.get("node_type") == "action_node" or "actions" in obj)


def _is_chance(obj) -> bool:
    return isinstance(obj, Mapping) and (obj.get("node_type") == "chance_node" or "dealcards" in obj)


def _card(text: str) -> str:
    t = text.strip()
    if len(t) != 2:
        raise DumpError(f"Not a card: {text!r}")
    return t[0].upper() + t[1].lower()


def _combo(text: str) -> str:
    t = re.sub(r"[^0-9A-Za-z]", "", text)
    return combo_text(parse_combo(_card(t[:2]) + _card(t[2:])))


def _strategy(obj: Mapping) -> Tuple[List[str], Mapping[str, List[float]]]:
    block = obj.get("strategy")
    if not isinstance(block, Mapping):
        return list(obj.get("actions", [])), {}
    if "strategy" in block and isinstance(block["strategy"], Mapping):
        return list(block.get("actions", obj.get("actions", []))), block["strategy"]
    return list(obj.get("actions", [])), block


class _Walker:
    def __init__(self, spot: Mapping, reading: str):
        self.spot = spot
        self.read = READINGS[reading]
        self.nodes: Dict[str, dict] = {}
        self.notes: List[str] = []
        self.player_ids: Dict[object, str] = {}

    def token(self, text: str, player: int, put: Tuple[float, float], stack: float, prev: float) -> str:
        m = _ACTION.match(str(text))
        if not m:
            raise DumpError(f"Unknown action {text!r}")
        kind, amount = m.group(1).upper(), m.group(2)
        mine, theirs = put[player], put[1 - player]
        facing = theirs > mine + 1e-9
        if kind == "CHECK":
            if facing:
                raise DumpError("CHECK while facing a bet")
            return "x"
        if kind == "CALL":
            return "c"
        if kind == "FOLD":
            return "f"
        new = stack if kind == "ALLIN" or amount is None else self.read(float(amount), mine, theirs, prev)
        new = round(new, 2)
        if new <= theirs + 1e-9 or new > stack + 0.01:
            raise DumpError(f"{text!r} reads as {new:g} put in, outside ({theirs:g}, {stack:g}]")
        return ("r" if facing else "b") + fmt_amount(min(new, stack))

    def street(self, obj: Mapping, street: str, prefix: str, pot: float, stack: float, prev: float) -> None:
        self.decision(obj, street, prefix, OOP, (0.0, 0.0), pot, stack, prev, checked=False)

    def decision(self, obj, street, key, player, put, pot, stack, prev, checked) -> None:
        if not _is_action(obj):
            return
        pid = obj.get("player")
        if pid is not None:
            seen = self.player_ids.setdefault(pid, PLAYER_NAMES[player])
            if seen != PLAYER_NAMES[player]:
                self.notes.append(f"{key!r}: TexasSolver player {pid} is {seen} elsewhere, {PLAYER_NAMES[player]} here")
        texts = list(obj.get("actions", []))
        tokens = [self.token(t, player, put, stack, prev) for t in texts]
        names, table = _strategy(obj)
        name_token = dict(zip(texts, tokens))
        order = [name_token.get(n) or self.token(n, player, put, stack, prev) for n in names]
        strategy = {}
        for combo, row in table.items():
            if len(row) != len(order):
                raise DumpError(f"{key!r} {combo}: {len(row)} probabilities for {len(order)} actions")
            strategy[_combo(combo)] = dict(zip(order, (float(p) for p in row)))
        if not strategy:
            self.notes.append(f"{key!r}: no strategy in the output")
        self.nodes[key] = node_record(key, PLAYER_NAMES[player], tokens, strategy)
        kids = _children(obj)
        other = 1 - player
        for text, tok in zip(texts, tokens):
            child = kids.get(text)
            k = f"{key} {tok}".strip()
            if tok == "f":
                continue
            if tok == "x":
                if checked or player == IP:
                    self.street_end(child, street, k, 0.0, pot, stack, prev)
                else:
                    self.decision(child, street, k, other, put, pot, stack, prev, True)
            elif tok == "c":
                self.street_end(child, street, k, put[other], pot, stack, prev)
            else:
                new = list(put)
                new[player] = float(tok[1:])
                self.decision(child, street, k, other, (new[0], new[1]), pot, stack, prev, checked)

    def street_end(self, child, street, key, called, pot, stack, prev) -> None:
        if street == "river" or called >= stack - 1e-9 or child is None:
            return
        if not _is_chance(child):
            self.notes.append(f"{key!r}: expected the river card here, found {str(child)[:60]}")
            return
        for card, sub in (child.get("dealcards") or {}).items():
            self.street(sub, "river", f"{key} {_card(card)}", pot + 2 * called, stack - called, prev + called)


def compare(expected: Mapping[str, Decision], nodes: Mapping[str, Mapping], limit: int = 12) -> List[str]:
    out = []
    for key in expected:
        if key not in nodes:
            out.append(f"missing {key!r}")
        elif set(nodes[key]["actions"]) != set(expected[key].actions):
            out.append(f"{key!r}: TexasSolver has {nodes[key]['actions']}, the spot has {list(expected[key].actions)}")
    out += [f"extra {k!r}" for k in nodes if k not in expected]
    return out[:limit] + ([f"... and {len(out) - limit} more"] if len(out) > limit else [])


def parse_dump(dump: Mapping, spot: Mapping, reading: Optional[str] = None) -> Parsed:
    """The dump as result node records, keyed as in data/SPOT_FORMAT.md, each node's
    actions in the spot tree's order. Tries each reading of the amounts (or just the one
    given) and keeps the first that rebuilds the spot's tree exactly, else the closest."""
    expected = decision_nodes(spot)
    best: Optional[Parsed] = None
    for name in ([reading] if reading else list(READINGS)):
        walker = _Walker(spot, name)
        try:
            walker.street(dump, spot["street"], "", float(spot["pot"]), float(min(spot["stacks"])), 0.0)
        except DumpError as e:
            parsed = Parsed({}, name, [f"can't read it this way: {e}"], walker.notes)
        else:
            parsed = Parsed(walker.nodes, name, compare(expected, walker.nodes), walker.notes)
        if not parsed.differences:
            break
        if best is None or (parsed.nodes and (not best.nodes or len(parsed.differences) < len(best.differences))):
            best = parsed
        parsed = None
    result = parsed or best
    for key, rec in result.nodes.items():  # the spot tree's action order
        want = expected.get(key)
        if want is not None and set(rec["actions"]) == set(want.actions):
            rec["actions"] = list(want.actions)
            rec["strategy"] = {c: {a: row[a] for a in want.actions} for c, row in rec["strategy"].items()}
    return result


def load_dump(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
