"""Compare a solver's RESULTs with a reference (docs/research/PHASE4.md).

    python -m tools.answer_keys compare <results dir> [--against texassolver|python_solver]

For each spot:

- EV. Each player's EV when both follow the answer, worked out here from the strategies
  (values.py; a RESULT has no values), and its difference from the reference's EV, in
  percent of the pot. Gate: within 0.5.
- Exploitability, in percent of the pot. Recomputed: river spots by app/solver's checker
  (checks.river_exploitability), turn spots by values.py's exact best response. The
  solver's own number is shown next to it ("Reported"). Gate: under 0.5.
  turn_exploitability="reported" takes the solver's own number for turn spots instead.
- The spot's expected checks (the trivial spots have them).
- Action frequencies. At each decision node, how often the acting player takes each action
  over the combos that get there; the node's difference is the largest difference for one
  action, in percentage points. "Freq mean" is the mean over the nodes, each weighted by the
  chance that play reaches it (the smaller of the two answers' chances). "Freq max" is the
  largest over the nodes that both answers reach at least 5% of the time (for a river node
  of a turn spot: 5% of the time once its river card has come). Reported only: a spot can
  have more than one equilibrium, so a difference here isn't a mistake.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from app.solver.timing import percentile

from .checks import check_expected, river_exploitability
from .result import ResultError, read_result, result_path, validate_result
from .spots import ROOT, decision_nodes, spot_hash
from .values import Evaluation, Game

KEYS_DIR = os.path.join(ROOT, "data", "answer_keys")
GATE_EV_PCT = 0.5  # each player's EV within this of the reference, percent of the pot
GATE_EXPLOITABILITY_PCT = 0.5  # exploitability under this, percent of the pot
GATE_RIVER_P95_MS = 400.0  # river p95 time under this (measured by `run`)
MIN_REACH = 0.05  # "Freq max" looks only at nodes both answers reach at least this often
TURN_EXPLOITABILITY = ("checked", "reported")


@dataclass
class Row:
    """One spot of a comparison. Percentages are of the pot; frequencies are in points."""

    spot_id: str
    street: str
    status: str = "ok"  # "ok", "missing" (no result for the spot) or "invalid"
    problems: List[str] = field(default_factory=list)  # why it is invalid, or which gates fail
    notes: List[str] = field(default_factory=list)
    ev: Optional[Tuple[float, float]] = None  # the answer's EV for (oop, ip)
    ev_diff: Optional[Tuple[float, float]] = None  # the answer's EV minus the reference's
    exploitability: Optional[float] = None  # the number the gate uses
    exploitability_source: str = ""  # "checked" or "reported"
    reported: Optional[float] = None  # the solver's own exploitability
    expected: Optional[List[str]] = None  # failed expected checks; None when the spot has none
    freq_mean: Optional[float] = None
    freq_max: Optional[float] = None
    freq_max_node: Optional[str] = None
    freq_max_detail: str = ""
    solver_ms: Optional[float] = None  # the solve time in the RESULT's header
    iterations: Optional[int] = None

    @property
    def compared(self) -> bool:
        return self.status != "missing"

    @property
    def passed(self) -> bool:
        return self.status == "ok" and not self.problems


def resolve_dir(name_or_path: str) -> str:
    """A results folder: a path, or the name of a folder in data/answer_keys."""
    if os.path.isdir(name_or_path):
        return name_or_path
    named = os.path.join(KEYS_DIR, name_or_path)
    return named if os.path.isdir(named) else name_or_path


def solver_stats(header: Mapping) -> Tuple[Optional[float], Optional[int], Optional[float]]:
    """(solve time in ms, iterations, exploitability in percent of the pot) as the solver
    wrote them in the header; None for what it left out."""
    solver = header.get("solver") or {}
    ms = None
    if isinstance(solver.get("elapsed_s"), (int, float)):
        ms = 1000.0 * solver["elapsed_s"]
    elif isinstance(solver.get("elapsed_ms"), (int, float)):
        ms = float(solver["elapsed_ms"])
    its = solver.get("iterations")
    expl = solver.get("exploitability_pot")
    return (ms, int(its) if isinstance(its, (int, float)) else None,
            100.0 * expl if isinstance(expl, (int, float)) else None)


def load_valid(results_dir: str, spot: Mapping, tree: Optional[Mapping] = None):
    """(header, nodes) of the spot's result in the folder, checked against the spot; None
    when there is none. Raises ValueError when it doesn't fit the spot."""
    path = result_path(results_dir, spot["id"])
    if path is None:
        return None
    header, nodes = read_result(path)
    validate_result(header, nodes, spot, spot_hash(spot), tree if tree is not None else decision_nodes(spot))
    return header, nodes


def frequency_difference(game: Game, a: Evaluation, b: Evaluation,
                         min_reach: float = MIN_REACH) -> Tuple[float, float, Optional[str], str]:
    """(mean, max, the node of the max, that node's two frequency rows as text), in
    percentage points: see the module text."""
    weighted = weight = 0.0
    worst, worst_key = -1.0, None
    for key in game.nodes:
        fa, fb = a.freq[key], b.freq[key]
        if fa is None or fb is None:
            continue  # one answer never gets here: its frequencies there mean nothing
        d = float(np.max(np.abs(fa - fb)))
        w = min(a.reach[key], b.reach[key])
        weighted += w * d
        weight += w
        if min(a.line_reach[key], b.line_reach[key]) >= min_reach and d > worst:
            worst, worst_key = d, key
    detail = ""
    if worst < 1e-9:
        worst, worst_key = 0.0, None  # no difference to point at
    if worst_key is not None:
        node = game.nodes[worst_key]
        pairs = [f"{t} {100 * x:.1f}/{100 * y:.1f}"
                 for t, x, y in zip(node.actions, a.freq[worst_key], b.freq[worst_key])]
        detail = f"{node.actor} at {worst_key!r}: " + ", ".join(pairs)
    return 100.0 * weighted / weight, 100.0 * worst, worst_key, detail


def compare_spot(spot: Mapping, result, reference=None, turn_exploitability: str = "checked",
                 min_reach: float = MIN_REACH) -> Row:
    """One row. result and reference are (header, nodes), already checked against the spot;
    reference may be None (the spot has no reference answer)."""
    header, nodes = result
    row = Row(spot["id"], spot["street"])
    pot = float(spot["pot"])
    row.solver_ms, row.iterations, row.reported = solver_stats(header)
    game = Game(spot)
    mine = game.evaluate(nodes)
    row.ev = (100.0 * mine.value[0] / pot, 100.0 * mine.value[1] / pot)
    if mine.filled_rows:
        row.notes.append(f"{mine.filled_rows} rows the answer left out were played evenly")

    if spot["street"] == "river":
        row.exploitability, row.exploitability_source = 100.0 * river_exploitability(spot, nodes)[0], "checked"
    elif turn_exploitability == "reported":
        row.exploitability, row.exploitability_source = row.reported, "reported"
    else:
        row.exploitability, row.exploitability_source = 100.0 * game.exploitability(nodes)[0], "checked"
    if row.exploitability is None:
        row.problems.append("no exploitability in the result")
    elif not row.exploitability < GATE_EXPLOITABILITY_PCT:
        row.problems.append(f"exploitability {row.exploitability:.3f}% is not under {GATE_EXPLOITABILITY_PCT}%")
    if (row.exploitability_source == "checked" and row.reported is not None
            and abs(row.reported - row.exploitability) > max(0.02, 0.1 * row.exploitability)):
        row.notes.append(f"the solver reports {row.reported:.3f}%, our check finds {row.exploitability:.3f}%")

    if spot.get("expected"):
        row.expected = check_expected(spot, nodes)
        if row.expected:
            row.problems.append(f"{len(row.expected)} expected checks fail, e.g. {row.expected[0]}")

    if reference is None:
        row.notes.append("no reference answer")
    else:
        theirs = game.evaluate(reference[1])
        row.ev_diff = (100.0 * (mine.value[0] - theirs.value[0]) / pot, 100.0 * (mine.value[1] - theirs.value[1]) / pot)
        worst = max(abs(d) for d in row.ev_diff)
        if worst > GATE_EV_PCT:
            row.problems.append(f"EV differs by {worst:.3f}% of the pot, over {GATE_EV_PCT}%")
        row.freq_mean, row.freq_max, row.freq_max_node, row.freq_max_detail = frequency_difference(
            game, mine, theirs, min_reach)
    return row


def compare_dirs(results_dir: str, against_dir: Optional[str], spots: Sequence[Mapping],
                 turn_exploitability: str = "checked", min_reach: float = MIN_REACH, log=None) -> List[Row]:
    """A row for every spot: compared, "missing" (the folder has no result for it) or
    "invalid" (its result doesn't fit the spot)."""
    if turn_exploitability not in TURN_EXPLOITABILITY:
        raise ValueError(f"turn_exploitability is one of {TURN_EXPLOITABILITY}.")
    rows = []
    for spot in spots:
        tree = decision_nodes(spot)
        try:
            result = load_valid(results_dir, spot, tree)
        except (ValueError, KeyError, TypeError, OSError, EOFError) as e:  # ResultError is a ValueError
            rows.append(Row(spot["id"], spot["street"], "invalid", [f"invalid result: {e}"]))
            continue
        if result is None:
            rows.append(Row(spot["id"], spot["street"], "missing"))
            continue
        reference, bad_reference = None, ""
        if against_dir:
            try:
                reference = load_valid(against_dir, spot, tree)
            except (ValueError, KeyError, TypeError, OSError, EOFError) as e:
                bad_reference = f"the reference answer is invalid: {e}"
        try:
            row = compare_spot(spot, result, reference, turn_exploitability, min_reach)
        except (ValueError, KeyError) as e:
            row = Row(spot["id"], spot["street"], "invalid", [f"invalid result: {e}"])
        if bad_reference:
            row.notes.append(bad_reference)
        rows.append(row)
        if log:
            log(row)
    return rows


# ------------------------------------------------------------------ the report
def _num(x: Optional[float], spec: str, none: str = "-") -> str:
    return none if x is None else format(x, spec)


def _cells(row: Row) -> List[str]:
    if row.status == "missing":
        return [row.spot_id, row.street] + ["-"] * 10 + ["no result"]
    if row.status == "invalid":
        return [row.spot_id, row.street] + ["-"] * 10 + ["INVALID"]
    d = row.ev_diff or (None, None)
    expected = "-" if row.expected is None else ("ok" if not row.expected else f"{len(row.expected)} fail")
    source = {"reported": " r", "checked": ""}.get(row.exploitability_source, "")
    return [row.spot_id, row.street, _num(row.ev[0], ".2f"), _num(d[0], "+.3f"), _num(d[1], "+.3f"),
            _num(row.exploitability, ".3f") + (source if row.exploitability is not None else ""),
            _num(row.reported, ".3f"), expected, _num(row.freq_mean, ".1f"), _num(row.freq_max, ".1f"),
            _num(row.solver_ms, ".1f"), _num(row.iterations, "d"), "pass" if row.passed else "FAIL"]


HEADERS = ["Spot", "Street", "EV oop", "dEV oop", "dEV ip", "Exploit.", "Reported", "Expected", "Freq mean",
           "Freq max", "Solve ms", "Iter.", "Gates"]
LEFT = {0, 1, 7, 12}  # columns of words; the rest are numbers


def format_table(rows: Sequence[Row], markdown: bool = False) -> str:
    table = [HEADERS] + [_cells(r) for r in rows]
    if markdown:
        lines = ["| " + " | ".join(HEADERS) + " |",
                 "| " + " | ".join("---" if i in LEFT else "---:" for i in range(len(HEADERS))) + " |"]
        return "\n".join(lines + ["| " + " | ".join(c) + " |" for c in table[1:]])
    widths = [max(len(r[i]) for r in table) for i in range(len(HEADERS))]
    return "\n".join("  ".join(c.ljust(w) if i in LEFT else c.rjust(w)
                               for i, (c, w) in enumerate(zip(r, widths))).rstrip() for r in table)


def legend(against: Optional[str], turn_exploitability: str = "checked", min_reach: float = MIN_REACH) -> str:
    ref = against or "no reference"
    turn = ("turn spots as the solver reported it (r)" if turn_exploitability == "reported"
            else "turn spots by tools/answer_keys/values.py")
    return (f"EV oop: the answer's EV for the out of position player, % of the pot. dEV: each player's EV minus "
            f"the reference's ({ref}), % of the pot; gate {GATE_EV_PCT}.\n"
            f"Exploit.: % of the pot, recomputed (river spots by app/solver's checker, {turn}); gate under "
            f"{GATE_EXPLOITABILITY_PCT}. Reported: the solver's own number.\n"
            f"Freq: difference in action frequencies from the reference, in points. Mean over the nodes weighted by "
            f"reach; max over the nodes reached at least {100 * min_reach:g}% of the time. Reported only.\n"
            f"Solve ms, Iter.: as the solver wrote them in its RESULT.")


@dataclass
class Summary:
    passed: bool
    lines: List[str]
    n_compared: int
    n_ev: int
    worst_ev: Optional[float]
    worst_ev_spot: str
    worst_exploitability: Optional[float]
    worst_exploitability_spot: str
    expected_spots: int
    expected_failed: int
    freq_mean: Optional[float]  # mean over the spots of each spot's "Freq mean"
    freq_max: Optional[float]
    solver_ms: Dict[str, Tuple[float, float, int]]  # street -> (p50, p95, spots), the solver's own time
    wall_ms: Dict[str, Tuple[float, float, int]]  # street -> (p50, p95, runs), from `run`'s index.json


def _ranges(ids: Sequence[str]) -> str:
    return " ".join(ids) if len(ids) <= 12 else " ".join(ids[:12]) + f" ... ({len(ids)} spots)"


def summarize(rows: Sequence[Row], against: Optional[str], results_dir: Optional[str] = None) -> Summary:
    """The pass/fail lines for the Phase 4 gates, and the numbers behind them."""
    done = [r for r in rows if r.compared]
    valid = [r for r in done if r.status == "ok"]
    invalid = [r for r in done if r.status == "invalid"]
    missing = [r.spot_id for r in rows if not r.compared]
    lines: List[str] = []
    verdict = lambda ok: "PASS" if ok else "FAIL"  # noqa: E731

    with_ev = [r for r in valid if r.ev_diff is not None]
    worst_ev, worst_ev_spot = None, ""
    ev_ok = True
    if with_ev:
        top = max(with_ev, key=lambda r: max(abs(d) for d in r.ev_diff))
        worst_ev, worst_ev_spot = max(abs(d) for d in top.ev_diff), top.spot_id
        ev_ok = worst_ev <= GATE_EV_PCT
        over = [r.spot_id for r in with_ev if max(abs(d) for d in r.ev_diff) > GATE_EV_PCT]
        lines.append(f"EV within {GATE_EV_PCT}% of the pot of {against}: {verdict(ev_ok)}, largest difference "
                     f"{worst_ev:.3f}% ({worst_ev_spot}), {len(with_ev)} spots"
                     + (f"; over: {_ranges(over)}" if over else ""))
    elif against:
        lines.append(f"EV within {GATE_EV_PCT}% of the pot of {against}: not checked (no spot has a reference answer)")
    no_ref = [r.spot_id for r in valid if r.ev_diff is None]
    if against and with_ev and no_ref:
        lines.append(f"  No {against} answer to compare with: {_ranges(no_ref)}")

    with_expl = [r for r in valid if r.exploitability is not None]
    worst_expl, worst_expl_spot = None, ""
    expl_ok = len(with_expl) == len(valid)
    if with_expl:
        top = max(with_expl, key=lambda r: r.exploitability)
        worst_expl, worst_expl_spot = top.exploitability, top.spot_id
        over = [r.spot_id for r in with_expl if not r.exploitability < GATE_EXPLOITABILITY_PCT]
        expl_ok = expl_ok and not over
        none = [r.spot_id for r in valid if r.exploitability is None]
        lines.append(f"Exploitability under {GATE_EXPLOITABILITY_PCT}% of the pot: {verdict(expl_ok)}, largest "
                     f"{worst_expl:.3f}% ({worst_expl_spot}), {len(with_expl)} spots"
                     + (f"; not under: {_ranges(over)}" if over else "")
                     + (f"; not reported: {_ranges(none)}" if none else ""))
    elif valid:
        lines.append(f"Exploitability under {GATE_EXPLOITABILITY_PCT}% of the pot: FAIL, no result reports one")

    checked = [r for r in valid if r.expected is not None]
    failed = [r.spot_id for r in checked if r.expected]
    if checked:
        lines.append(f"Expected checks of the trivial spots: {verdict(not failed)}, {len(checked) - len(failed)} of "
                     f"{len(checked)} spots" + (f"; failing: {_ranges(failed)}" if failed else ""))
    if invalid:
        lines.append(f"Invalid results: {_ranges([r.spot_id for r in invalid])}")
        for r in invalid[:5]:
            lines.append(f"  {r.spot_id}: {r.problems[0]}")

    passed = bool(done) and ev_ok and expl_ok and not failed and not invalid
    caveat = "" if done else " (nothing to compare)"
    if done and against and no_ref:
        caveat = f" (EV not checked on {len(no_ref)} spots with no {against} answer)"
    lines.append(f"Phase 4 gates on {len(done)} of {len(rows)} spots: {verdict(passed)}{caveat}")
    if missing:
        lines.append(f"No result, not checked: {_ranges(missing)}")

    solver_ms: Dict[str, Tuple[float, float, int]] = {}
    for street in ("river", "turn"):
        times = [r.solver_ms for r in valid if r.street == street and r.solver_ms is not None]
        if times:
            solver_ms[street] = (percentile(times, 50), percentile(times, 95), len(times))
    wall_ms = wall_times(results_dir) if results_dir else {}
    for street, (p50, p95, n) in solver_ms.items():
        lines.append(f"Solve time the solver reported, {street}: p50 {p50:.1f} ms, p95 {p95:.1f} ms ({n} spots)")
    for street, (p50, p95, n) in wall_ms.items():
        lines.append(f"Wall time from the last `run`, {street}: p50 {p50:.1f} ms, p95 {p95:.1f} ms ({n} runs)")

    means = [r.freq_mean for r in valid if r.freq_mean is not None]
    maxes = [r.freq_max for r in valid if r.freq_max is not None]
    return Summary(passed, lines, len(done), len(with_ev), worst_ev, worst_ev_spot, worst_expl, worst_expl_spot,
                   len(checked), len(failed), sum(means) / len(means) if means else None,
                   max(maxes) if maxes else None, solver_ms, wall_ms)


def wall_times(results_dir: str) -> Dict[str, Tuple[float, float, int]]:
    """street -> (p50, p95, runs) of the wall times `run` saved in the folder's index.json."""
    try:
        with open(os.path.join(results_dir, "index.json")) as f:
            timing = json.load(f).get("timing", {})
    except (OSError, ValueError):
        return {}
    out = {}
    for street in ("river", "turn"):
        t = timing.get(street) or {}
        if "wall_ms_p50" in t and "wall_ms_p95" in t:
            out[street] = (float(t["wall_ms_p50"]), float(t["wall_ms_p95"]), int(t.get("runs", 0)))
    return out


def markdown_row(name: str, against: str, s: Summary) -> str:
    """One line for the results table of docs/research/PHASE4.md."""
    def times(d, street):
        return f"{d[street][0]:.0f} / {d[street][1]:.0f}" if street in d else "-"

    return ("| " + " | ".join([
        name, str(s.n_compared), against,
        f"{s.worst_ev:.3f}% ({s.worst_ev_spot})" if s.worst_ev is not None else "-",
        f"{s.worst_exploitability:.3f}% ({s.worst_exploitability_spot})" if s.worst_exploitability is not None else "-",
        f"{s.expected_spots - s.expected_failed} of {s.expected_spots}" if s.expected_spots else "-",
        f"{s.freq_mean:.1f} / {s.freq_max:.1f}" if s.freq_mean is not None else "-",
        times(s.solver_ms, "river"), times(s.wall_ms, "river"), times(s.solver_ms, "turn"), times(s.wall_ms, "turn"),
        "PASS" if s.passed else "FAIL"]) + " |")


MARKDOWN_ROW_HEADER = (
    "| Solver | Spots | Against | Largest EV difference | Largest exploitability | Expected checks | "
    "Freq mean / max (points) | River solve p50 / p95 (ms) | River wall p50 / p95 (ms) | "
    "Turn solve p50 / p95 (ms) | Turn wall p50 / p95 (ms) | Gates |\n"
    "| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |")

__all__ = ["GATE_EV_PCT", "GATE_EXPLOITABILITY_PCT", "GATE_RIVER_P95_MS", "MIN_REACH", "ResultError", "Row", "Summary",
           "compare_dirs", "compare_spot", "format_table", "frequency_difference", "legend", "load_valid",
           "markdown_row", "resolve_dir", "solver_stats", "summarize", "wall_times"]
