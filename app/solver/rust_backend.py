"""The Rust subgame solver as a backend for the river solver.

    from app.solver import rust_backend
    strategy = rust_backend.solve_river(spot, time_budget_ms=300)

solve_river here takes what app.solver.solve_river takes and returns the same
RiverStrategy. It writes the spot as a SPOT file, runs the program `subgame-solve` on it
and reads its RESULT back (both formats are in data/SPOT_FORMAT.md):

    subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.3]
                  [--max-iterations N] [--time-ms N] [--threads N]

When the program isn't built, fails, runs out of time or answers something that doesn't
fit the spot's tree, the Python solver answers instead, in what is left of the time
budget. strategy.backend says who answered: "rust" or "python".

The program is looked for in the environment variable POKERSCRIBE_SUBGAME_SOLVE (the path
of the program), and otherwise in engine/target/release, where `cargo build --release`
puts it.

The advice uses this only when TUNING["rust_solver"] is on (it is off), and only where
TUNING["river_solver"] already sends a decision to the solver: app/poker/advice.py.

A SPOT's bet sizes are bets, raises and allin. BetSizes has three more options (reraises,
allin_within, exact), which the advice's spots use. plain_sizes says them with the three
the format has wherever that gives exactly the same tree. Where it can't, the spot goes
straight to the Python solver and the program isn't run: about a quarter of the advice's
river decisions in simulated hands, all with stacks of 12.5 to 19 pots, where all in
answers a pot-sized bet but not a half-pot bet (EXTENDED_SIZES is the way out).

Only the program's command line and its two file formats are used here, nothing from the
crate behind it (engine/crates/subgame). --target-exploitability is in percent of the pot,
while RiverStrategy and solve_river count in shares of the pot, so 0.001 here goes out as
0.1.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from operator import itemgetter
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np

from .exploitability import exploitability as python_exploitability
from .solve import DECISION_BUDGET_MS, TARGET_EXPLOITABILITY
from .solve import solve_river as python_solve_river
from .spot import IP, OOP, PLAYER_NAMES, BetSizes, RiverSpot, combo_text
from .strategy import RiverStrategy
from .tree import GameTree

log = logging.getLogger(__name__)

ENV_BINARY = "POKERSCRIBE_SUBGAME_SOLVE"
BINARY_NAME = "subgame-solve"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BINARY = os.path.join(REPO_ROOT, "engine", "target", "release", BINARY_NAME)

SPOT_FORMAT, SPOT_VERSION = "pokerscribe-spot", 1
RESULT_FORMAT, RESULT_VERSION = "pokerscribe-answer-key", 1
SPOT_ID = "live"  # the id of a spot made here (the answer keys use r01, t01, ...)

# --target-exploitability is in percent of the pot; this module counts in shares of it.
TARGET_PERCENT = 100.0
# Time kept back from the budget for everything around the solve itself: starting the
# program, writing the spot, reading the answer back. Measured with
# tools/rust_solver_overhead.py; the numbers are in docs/research/experiments.md.
OVERHEAD_RESERVE_MS = 40.0
# A RESULT rounds probabilities to 6 decimals, so a row may be this far from adding up to 1.
ROW_TOLERANCE = 1e-4
# A SPOT's bet sizes are written with the three keys data/SPOT_FORMAT.md describes (bets,
# raises, allin), and a spot they can't say goes to the Python solver (plain_sizes).
# subgame-solve refuses a spot with BetSizes' three newer options (reraises, allin_within,
# exact). Set this to True once it reads them the way app/solver/tree.py does: such a spot
# then goes out with its sizes as they are (BetSizes.to_dict()). An answer for another
# tree is refused either way.
EXTENDED_SIZES = False


class RustSolverError(RuntimeError):
    """The program could not be run, or its answer does not fit the spot."""


class UnsupportedSpot(RustSolverError):
    """The spot's betting tree can't be written as a SPOT, so the program isn't asked."""


# ------------------------------------------------------------- the program
def find_binary() -> Optional[str]:
    """The path of subgame-solve, or None when it isn't there.

    POKERSCRIBE_SUBGAME_SOLVE, when set, is the only place looked at: a wrong path there
    means "not found", never a silent switch to another build."""
    named = os.environ.get(ENV_BINARY)
    candidates = [named] if named else [DEFAULT_BINARY, DEFAULT_BINARY + ".exe"]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


# ---------------------------------------------------------------- the SPOT
def _number(x: float):
    """Whole amounts as ints (200, not 200.0), as the answer-key spots write them."""
    return int(x) if float(x).is_integer() else float(x)


def _shape(tree: GameTree) -> Dict[str, Tuple[str, ...]]:
    """Every node of a tree with its actions. Amounts are in the action tokens, so two
    trees with the same shape are the same tree."""
    return {key: node.actions for key, node in tree.nodes.items()}


def _tree_with(spot: RiverSpot, sizes: Tuple[BetSizes, BetSizes]) -> GameTree:
    """The spot's tree if the players had these sizes. A tree doesn't depend on the
    ranges, so one combo each is enough (and much quicker to check than the whole range)."""
    return GameTree(RiverSpot(spot.board, spot.pot, spot.stacks, spot.oop_range[:1], spot.ip_range[:1],
                              sizes[OOP], sizes[IP], spot.max_raises))


def _is_plain(sizes: BetSizes) -> bool:
    return sizes.reraises is None and sizes.allin_within is None and not sizes.exact


def plain_sizes(spot: RiverSpot, tree: Optional[GameTree] = None) -> Tuple[BetSizes, BetSizes]:
    """The spot's bet sizes for (OOP, IP), said with the three things the sizes of a SPOT
    have: bets, raises and allin (data/SPOT_FORMAT.md). They give exactly the spot's tree.

    BetSizes has three more options, which the format doesn't know: reraises, allin_within
    and exact. All they do is decide where going all in is a choice and which list a raise
    takes its sizes from. So they are said here with allin off and, in the lists where all
    in is a choice, one more size big enough to be all in wherever it is offered (the
    format: "sizes at or over the effective stack become all in"). Each try is checked by
    building its tree. UnsupportedSpot when no try gives the spot's tree: one list of raise
    sizes for a player can't say a spot where that player's raises differ from one place
    in the tree to another."""
    both = (spot.sizes(OOP), spot.sizes(IP))
    if all(_is_plain(s) for s in both):
        return both
    wanted = _shape(tree if tree is not None else GameTree(spot))
    stack, pot = spot.effective_stack, spot.pot
    everything = float(math.ceil(stack / pot) + 1)  # as a share of the pot: all in, wherever it is offered
    found = list(both)
    for player in (OOP, IP):
        sizes = both[player]
        if _is_plain(sizes):
            continue
        bets = sizes.bets + ((everything,) if sizes.adds_allin("bets", stack / pot) else ())
        lists = [sizes.raises] + ([sizes.reraises] if sizes.reraises not in (None, sizes.raises) else [])
        for raises in [given + more for given in lists for more in ((everything,), ())]:
            trial = list(both)
            trial[player] = BetSizes(bets, raises, allin=False)
            if _shape(_tree_with(spot, (trial[OOP], trial[IP]))) == wanted:
                found[player] = trial[player]
                break
        else:
            raise UnsupportedSpot(f"a SPOT can't say the {PLAYER_NAMES[player]} bet sizes of this spot "
                                  f"({sizes.to_dict()}, {spot.max_raises} raises)")
    if _shape(_tree_with(spot, (found[OOP], found[IP]))) != wanted:  # can't happen: each player's nodes were checked
        raise UnsupportedSpot("a SPOT can't say the bet sizes of this spot")
    return found[OOP], found[IP]


def spot_document(spot: RiverSpot, spot_id: str = SPOT_ID, tree: Optional[GameTree] = None) -> dict:
    """The spot as a SPOT (data/SPOT_FORMAT.md), ready for json.dump. UnsupportedSpot when
    its bet sizes can't be said in one (plain_sizes), unless EXTENDED_SIZES is on.

    A SPOT's weights are at most 1. A range with a bigger weight is scaled down as a whole,
    which changes nothing in the answer: a strategy depends only on how a player's combos
    compare with each other."""
    d = spot.to_dict()
    try:
        sizes = {name: {"bets": list(s.bets), "raises": list(s.raises), "allin": s.allin}
                 for name, s in zip(PLAYER_NAMES, plain_sizes(spot, tree))}
    except UnsupportedSpot:
        if not EXTENDED_SIZES:
            raise
        sizes = d["sizes"]
    ranges = {}
    for name in PLAYER_NAMES:
        weights = d["ranges"][name]
        scale = max(1.0, max(weights.values()))
        ranges[name] = {combo: w / scale for combo, w in weights.items()}
    return {
        "format": SPOT_FORMAT, "version": SPOT_VERSION, "id": spot_id, "street": "river",
        "title": "A river decision from the app", "tags": [],
        "board": d["board"], "pot": _number(d["pot"]), "stacks": [_number(s) for s in d["stacks"]],
        "spr": round(spot.effective_stack / spot.pot, 2), "max_raises": d["max_raises"],
        "sizes": sizes, "ranges": ranges,
    }


# -------------------------------------------------------------- the RESULT
def parse_result(data: bytes) -> Tuple[dict, Dict[str, dict]]:
    """(header, {node key: node record}) from a RESULT's bytes: JSON Lines, gzipped or not."""
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError) as e:
            raise RustSolverError(f"the result is not readable gzip: {e}") from None
    try:
        lines = [json.loads(line) for line in data.splitlines() if line.strip()]
    except ValueError as e:
        raise RustSolverError(f"the result is not JSON Lines: {e}") from None
    if not lines or not isinstance(lines[0], dict) or lines[0].get("kind") != "header":
        raise RustSolverError("the result does not start with a header line")
    header = lines[0]
    if header.get("format") != RESULT_FORMAT or header.get("version") != RESULT_VERSION:
        raise RustSolverError(f"not a {RESULT_FORMAT} version {RESULT_VERSION} result")
    nodes: Dict[str, dict] = {}
    for rec in lines[1:]:
        if not isinstance(rec, dict) or rec.get("kind") != "node" or not isinstance(rec.get("node"), str):
            raise RustSolverError("every line after the header must be a node")
        if rec["node"] in nodes:
            raise RustSolverError(f"node {rec['node']!r} is there twice")
        nodes[rec["node"]] = rec
    return header, nodes


def _node_probs(rec: Mapping, key: str, actor: str, actions: Tuple[str, ...], combos: List[str]) -> np.ndarray:
    """One node's strategy as an array (combos in the range's order, actions in the tree's)."""
    if rec.get("actor") != actor or list(rec.get("actions") or ()) != list(actions):
        raise RustSolverError(f"node {key!r}: the result has {rec.get('actor')} to act with "
                              f"{rec.get('actions')}, the spot's tree has {actor} with {list(actions)}")
    table = rec.get("strategy")
    if not isinstance(table, dict) or len(table) != len(combos):
        raise RustSolverError(f"node {key!r}: the strategy must list the {len(combos)} combos of the {actor} range")
    try:
        rows = [table[c] for c in combos]
        if set(map(len, rows)) != {len(actions)}:
            raise RustSolverError(f"node {key!r}: a combo does not have one probability per action")
        # Looked up by action name: the order of the keys in the file is not relied on.
        take = itemgetter(*actions)
        probs = np.array([take(row) for row in rows], dtype=float).reshape(len(rows), len(actions))
    except KeyError as e:
        raise RustSolverError(f"node {key!r}: nothing for {e.args[0]!r}") from None
    except (TypeError, ValueError):
        raise RustSolverError(f"node {key!r}: the strategy is not combo -> action -> probability") from None
    if not np.all(np.isfinite(probs)) or probs.min() < -ROW_TOLERANCE:
        raise RustSolverError(f"node {key!r}: probabilities must be finite and not negative")
    totals = probs.sum(axis=1)
    if np.abs(totals - 1.0).max() > ROW_TOLERANCE:
        raise RustSolverError(f"node {key!r}: a combo's probabilities do not add up to 1")
    np.clip(probs, 0.0, None, out=probs)
    probs /= probs.sum(axis=1, keepdims=True)  # undo the file's rounding to 6 decimals
    return probs


def strategy_from_result(spot: RiverSpot, header: Mapping, nodes: Mapping[str, Mapping],
                         tree: Optional[GameTree] = None, spot_id: str = SPOT_ID) -> RiverStrategy:
    """The RESULT as a RiverStrategy. RustSolverError unless it is for this spot and has
    exactly the decision nodes of the spot's tree, with the same actions and every combo."""
    tree = tree if tree is not None else GameTree(spot)
    if header.get("spot_id") != spot_id:
        raise RustSolverError(f"the result is for spot {header.get('spot_id')!r}, not {spot_id!r}")
    if header.get("street", "river") != "river":
        raise RustSolverError(f"the result is for the {header.get('street')}, not the river")
    wanted = {n.key: n for n in tree.decision_nodes()}
    if set(nodes) != set(wanted):
        missing, extra = sorted(set(wanted) - set(nodes))[:3], sorted(set(nodes) - set(wanted))[:3]
        raise RustSolverError(f"the result's nodes differ from the spot's tree (missing {missing}, extra {extra})")
    combos = tuple([combo_text(c) for c in spot.combos(p)] for p in (0, 1))
    probs = {key: _node_probs(nodes[key], key, PLAYER_NAMES[n.player], n.actions, combos[n.player])
             for key, n in wanted.items()}

    solver = header.get("solver") if isinstance(header.get("solver"), dict) else {}
    iterations = solver.get("iterations")
    expl = solver.get("exploitability_pot")
    known = isinstance(expl, (int, float)) and not isinstance(expl, bool) and math.isfinite(expl)
    try:
        return RiverStrategy(spot, probs, tree,
                             iterations=iterations if isinstance(iterations, int) and iterations > 0 else 0,
                             exploitability=float(expl) if known else None, backend="rust")
    except ValueError as e:
        raise RustSolverError(str(e)) from None


# ----------------------------------------------------------------- one run
@dataclass
class RustSolve:
    """One answer of the program: the strategy, the RESULT's header, and where the time
    of the call went (milliseconds). overhead_ms is everything but the solving itself, by
    the program's own count of its solving time (None when the header doesn't give one)."""

    strategy: RiverStrategy
    header: dict
    write_ms: float  # the spot written to a file
    run_ms: float  # the program, from start to exit
    read_ms: float  # the result read, checked and turned into a RiverStrategy
    total_ms: float
    result_bytes: int

    @property
    def solver_ms(self) -> Optional[float]:
        solver = self.header.get("solver")
        s = solver.get("elapsed_s") if isinstance(solver, dict) else None
        return 1000.0 * s if isinstance(s, (int, float)) and not isinstance(s, bool) else None

    @property
    def overhead_ms(self) -> Optional[float]:
        return None if self.solver_ms is None else self.total_ms - self.solver_ms


def run_solver(spot: RiverSpot, binary: str, *, time_ms: Optional[float] = None,
               max_iterations: Optional[int] = None, target_exploitability: Optional[float] = None,
               threads: Optional[int] = None, timeout_ms: Optional[float] = None) -> RustSolve:
    """Run subgame-solve on the spot once and read its answer. No fallback: anything wrong
    is a RustSolverError.

    time_ms: the program's own time limit (--time-ms). target_exploitability: a share of
    the pot, as everywhere in app.solver. timeout_ms: the program is stopped after this
    long, whatever it is doing."""
    start = time.perf_counter()
    tree = GameTree(spot)
    document = spot_document(spot, tree=tree)
    with tempfile.TemporaryDirectory(prefix="pokerscribe-solve-") as folder:
        spot_path = os.path.join(folder, document["id"] + ".json")
        result_path = os.path.join(folder, "result.jsonl")
        with open(spot_path, "w") as f:
            json.dump(document, f, separators=(",", ":"))
        command = [binary, spot_path, "--out", result_path]
        if target_exploitability is not None:
            command += ["--target-exploitability", repr(float(target_exploitability) * TARGET_PERCENT)]
        if max_iterations is not None:
            command += ["--max-iterations", str(int(max_iterations))]
        if time_ms is not None:
            command += ["--time-ms", str(max(1, int(time_ms)))]
        if threads is not None:
            command += ["--threads", str(int(threads))]
        written = time.perf_counter()
        try:
            done = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE,
                                  timeout=None if timeout_ms is None else max(timeout_ms, 1.0) / 1000.0)
        except subprocess.TimeoutExpired:
            raise RustSolverError(f"no answer after {timeout_ms:.0f} ms") from None
        except OSError as e:
            raise RustSolverError(f"could not be started: {e}") from None
        ran = time.perf_counter()
        if done.returncode != 0:
            said = done.stderr.decode(errors="replace").strip().splitlines()
            raise RustSolverError(f"exit code {done.returncode}" + (f": {said[-1][:300]}" if said else ""))
        try:
            with open(result_path, "rb") as f:
                data = f.read()
        except OSError:
            raise RustSolverError("it wrote no result") from None
    header, nodes = parse_result(data)
    strategy = strategy_from_result(spot, header, nodes, tree, spot_id=document["id"])
    _check_target_unit(header, strategy, target_exploitability)
    end = time.perf_counter()
    strategy.elapsed_ms = 1000.0 * (end - start)
    return RustSolve(strategy, header, 1000.0 * (written - start), 1000.0 * (ran - written),
                     1000.0 * (end - ran), 1000.0 * (end - start), len(data))


def _check_target_unit(header: Mapping, strategy: RiverStrategy, target: Optional[float]) -> None:
    """Warn when the program says it reached its target while its answer is more than ten
    times further from an equilibrium than the target asked for here: then it does not
    read --target-exploitability in percent of the pot, as TARGET_PERCENT assumes."""
    solver = header.get("solver")
    said_converged = isinstance(solver, dict) and solver.get("converged") is True
    if said_converged and target and strategy.exploitability is not None and strategy.exploitability > 10 * target:
        log.warning("%s says it converged at %.3g%% of the pot, but the target was %.3g%%: check the unit of "
                    "--target-exploitability (TARGET_PERCENT in %s).", BINARY_NAME,
                    100 * strategy.exploitability, 100 * target, __name__)


# ------------------------------------------------------------ the entry point
_said_missing = False


def solve_river(spot: RiverSpot, time_budget_ms: Optional[float] = DECISION_BUDGET_MS, *,
                max_iterations: Optional[int] = None, target_exploitability: float = TARGET_EXPLOITABILITY,
                threads: Optional[int] = None, binary: Optional[str] = None) -> RiverStrategy:
    """app.solver.solve_river, answered by subgame-solve when it can, by the Python solver
    otherwise. The limits mean the same: a time budget for the whole call (None = no
    limit), max_iterations, and a target exploitability as a share of the pot.

    The program gets the budget less OVERHEAD_RESERVE_MS and is stopped at the budget. If it
    fails, the Python solver gets what is left of the budget; with nothing left it still
    runs one iteration, so check elapsed_ms against the budget (the advice does). A spot
    that can't be written as a SPOT (plain_sizes) goes to the Python solver at once.

    The strategy always comes back with its exploitability, as the Python solver's does
    (the advice drops an answer that is too rough): the program's own number, or the
    Python checker's when the program gave none (a few ms on the advice's spots)."""
    global _said_missing
    if time_budget_ms is None and max_iterations is None and target_exploitability <= 0:
        raise ValueError("Give a time budget, max_iterations or a target exploitability.")
    start = time.perf_counter()
    path = binary or find_binary()
    if path is None:
        if not _said_missing:
            _said_missing = True
            log.info("%s isn't built (%s or %s); the Python solver answers.", BINARY_NAME, ENV_BINARY, DEFAULT_BINARY)
    else:
        try:
            strategy = run_solver(
                spot, path, max_iterations=max_iterations, target_exploitability=target_exploitability,
                threads=threads, timeout_ms=time_budget_ms,
                time_ms=None if time_budget_ms is None else time_budget_ms - OVERHEAD_RESERVE_MS).strategy
            if strategy.exploitability is None:
                strategy.exploitability = python_exploitability(strategy).pot_share
                strategy.elapsed_ms = 1000.0 * (time.perf_counter() - start)
            return strategy
        except UnsupportedSpot as e:
            log.debug("%s is not asked (%s); the Python solver answers.", BINARY_NAME, e)
        except RustSolverError as e:
            log.warning("%s failed (%s); the Python solver answers.", BINARY_NAME, e)
    left = None if time_budget_ms is None else max(0.0, time_budget_ms - 1000.0 * (time.perf_counter() - start))
    strategy = python_solve_river(spot, left, max_iterations=max_iterations,
                                  target_exploitability=target_exploitability)
    strategy.elapsed_ms = 1000.0 * (time.perf_counter() - start)
    return strategy
