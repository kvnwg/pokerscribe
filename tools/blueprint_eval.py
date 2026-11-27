"""Every measurement of a blueprint run's strategy files, in one command (Phase 6).

    python tools/blueprint_eval.py strategy-*.bps --tables ~/abstraction/k200 --out eval/

For the files given (sorted by the iterations in their headers):

1. LBR, local best response (`blueprint lbr`), at each setting of ``--lbr`` (default
   ``fcpa14,b56_14``: LBR betting the pot and all in only, and LBR with 56 bet sizes, both
   thinking from the preflop), on the same deals for every file (one seed), with every deal's
   result kept, so two files' LBR results are compared deal by deal (`blueprint compare`):
   each file against the one before it, and the last against the first.
2. Head to head in the arena (`pokerscribe_engine.run_match`), each file against the one
   before it and the last against the first: duplicate deals (each played twice, seats
   swapped), all-in equity, bb/100 with its standard error, at the blueprint's 200 big blinds.
3. B0 heads-up (``tools/b0_arena.py``) against the last file (``--b0 all``: every file), split
   over ``--b0-processes`` processes with seeds ``--b0-seed`` + 0, 1, ... and pooled: B0 is a
   Python agent and plays on one core per process. Its standard deviation per deal gives the
   hands a 2.5 SE result needs at 5, 10 and 20 bb/100 and at the edge measured.
4. The change of each stage from the one before (``stages.jsonl``, written by the trainer),
   the stop rule at each stage, and a projection: at the rate the change fell over the last
   stages, the stage where the stop rule could first say stop, and at the trainer's last speed
   (``log.jsonl``) the hours left.

Results go to ``--out``: ``lbr.jsonl``, ``deals/``, ``h2h.jsonl``, ``b0/``, and
``summary.json`` with ``summary.md``, which ends with the readings of the Phase 6 gate under
each wording (docs/research/runs/phase6/README.md, "The gate"). A measurement already in
``--out`` with the same settings is not run again, so the command can be stopped and run
again, and run again with more files.

The B0 match is at 200 big blinds, the blueprint's own depth: at any other depth the blueprint
plays a game it was not trained for (its stacks are part of every information set's history),
and 200bb is also Slumbot's depth, the next benchmark (Phase 7).

Needs the blueprint binary (``cargo build --release --bin blueprint`` in engine/) and the Rust
module for the arena (``python -m pip install ./engine/crates/py``).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from typing import Callable, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLUEPRINT = os.path.join(REPO, "engine", "target", "release", "blueprint")
B0_ARENA = os.path.join(REPO, "tools", "b0_arena.py")

# Pre-registered seeds (docs/research/runs/phase6/README.md): the same for every run.
LBR_SEED = 6001
H2H_SEED = 6101
B0_SEED = 6201
STACK_BB = 200
Z = 2.5
EDGES = (5.0, 10.0, 20.0)
# The full run's stop rule, Phase 5's (docs/research/runs/phase5_gate/plan.json): stop at the
# first stage where the strategy changed by at most MAX_CHANGE since the stage before and the
# stopping measure (LBR b56_14) moved by less than RELATIVE of its value or SIGMAS standard
# errors of the paired difference.
STOP_SETTING = "b56_14"
STOP_RELATIVE = 0.03
STOP_SIGMAS = 2.0
STOP_MAX_CHANGE = 0.08


# --- small pure pieces (tests: app/tests/test_blueprint_eval.py) ----------------------------------

def label(iterations: int) -> str:
    """A file's name in the results: its iterations, e.g. it16M or it1.5G."""
    for div, unit in ((10 ** 9, "G"), (10 ** 6, "M"), (10 ** 3, "k")):
        if iterations >= div:
            v = iterations / div
            return f"it{v:g}{unit}" if v == int(v) else f"it{v:.3g}{unit}"
    return f"it{iterations}"


def pairs(n: int) -> list[tuple[int, int]]:
    """Index pairs to compare: each file with the one before it, then the last with the
    first (when that is not already a consecutive pair)."""
    out = [(i - 1, i) for i in range(1, n)]
    if n >= 3:
        out.append((0, n - 1))
    return out


def pool(parts: list[dict]) -> dict:
    """Independent matches with the same lineup pooled: ``parts`` hold deals, bb_per_100 and
    se (one sample per deal). The mean is weighted by deals; the variance of the pooled mean
    is the sum of n_i^2 se_i^2 over N^2."""
    n = sum(p["deals"] for p in parts)
    if not n:
        return {"deals": 0, "bb_per_100": None, "se": None, "sd_per_deal": None}
    mean = sum(p["deals"] * p["bb_per_100"] for p in parts) / n
    var = sum((p["deals"] * p["se"]) ** 2 for p in parts if p.get("se") is not None) / n ** 2
    se = math.sqrt(var)
    return {"deals": n, "bb_per_100": mean, "se": se, "sd_per_deal": se * math.sqrt(n),
            "hands": sum(p.get("hands", 2 * p["deals"]) for p in parts)}


def hands_needed(sd_per_deal: float, edge: float, z: float = Z, replays: int = 2) -> int:
    """Hands for an edge of ``edge`` bb/100 to be ``z`` standard errors, with ``sd_per_deal``
    the standard deviation of one deal's result (bb/100 units, each deal ``replays`` hands)."""
    deals = (z * sd_per_deal / abs(edge)) ** 2
    return int(math.ceil(deals)) * replays


def z_of(d: Optional[float], se: Optional[float]) -> Optional[float]:
    if d is None or not se:
        return None
    return d / se


def stage_changes(path: Optional[str]) -> dict[int, dict]:
    """stages.jsonl by iterations: the change from the stage before and its file."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "iterations" in d:
                out[int(d["iterations"])] = d
    return out


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def append_jsonl(path: str, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def gate_readings(files: list[dict], lbr: dict, lbr_pairs: dict, h2h: dict, b0: dict,
                  settings: list[str]) -> dict:
    """What each wording of the Phase 6 gate would say about these measurements.

    (a) as written: LBR falls at every checkpoint (each file's LBR below the one before);
    (b) the last file beats the first head to head by 2.5 SE;
    (c) LBR with menu bets only (fcpa) falls from the first file to the last;
    and in every wording: the blueprint beats B0 heads-up by 2.5 SE.
    Each reading gives the numbers behind it, so a stricter or looser reading (falls by 2.5
    SE, falls at all) can be made from the same summary."""
    n = len(files)
    out = {}
    a = {}
    for s in settings:
        steps = [lbr_pairs.get((s, i, j)) for i, j in pairs(n) if j == i + 1]
        steps = [x for x in steps if x]
        a[s] = {"steps": len(steps),
                "fell": sum(1 for x in steps if x["difference"] < 0),
                "fell_by_2_5_se": sum(1 for x in steps if x["difference"] < 0
                                      and abs(x["z"]) >= Z),
                "rose_by_2_5_se": sum(1 for x in steps if x["difference"] > 0
                                      and abs(x["z"]) >= Z)}
        a[s]["every_step_fell"] = bool(steps) and a[s]["fell"] == len(steps)
    out["a_lbr_falls_at_every_checkpoint"] = a
    last_first = h2h.get((0, n - 1)) if n >= 2 else None
    out["b_last_beats_first_by_2_5_se"] = None if not last_first else {
        "bb_per_100": last_first["bb_per_100"], "se": last_first["se"],
        "z": z_of(last_first["bb_per_100"], last_first["se"]),
        "passes": (z_of(last_first["bb_per_100"], last_first["se"]) or 0) >= Z}
    menu = next((s for s in settings if s.startswith("fcpa")), None)
    c = lbr_pairs.get((menu, 0, n - 1)) if menu and n >= 2 else None
    out["c_lbr_menu_bets_falls_first_to_last"] = None if not c else {
        "setting": menu, "first": lbr.get((menu, 0)), "last": lbr.get((menu, n - 1)),
        "difference": c["difference"], "se": c["std_err"], "z": c["z"],
        "falls": c["difference"] < 0, "falls_by_2_5_se": c["difference"] < 0 and abs(c["z"]) >= Z}
    last_b0 = b0.get(n - 1)
    out["b0_beaten_by_2_5_se"] = None if not last_b0 else {
        "bb_per_100": last_b0["blueprint_bb_per_100"], "se": last_b0["se"],
        "z": z_of(last_b0["blueprint_bb_per_100"], last_b0["se"]),
        "passes": (z_of(last_b0["blueprint_bb_per_100"], last_b0["se"]) or 0) >= Z}
    return out


def stop_rule(files: list[dict], lbr: dict, lbr_pairs: dict, setting: str = STOP_SETTING,
              relative: float = STOP_RELATIVE, sigmas: float = STOP_SIGMAS,
              max_change: float = STOP_MAX_CHANGE) -> list[dict]:
    """The stop rule at each stage after the first: whether it says stop there."""
    out = []
    for j in range(1, len(files)):
        i = j - 1
        c = lbr_pairs.get((setting, i, j))
        before = lbr.get((setting, i))
        change = files[j].get("change")
        if c is None or before is None:
            continue
        flat = abs(c["difference"]) < relative * abs(before) or abs(c["z"]) < sigmas
        settled = change is not None and change <= max_change
        out.append({"stage": files[j]["label"], "change": change, "lbr_before": before,
                    "lbr_move": c["difference"], "lbr_move_z": c["z"], "lbr_flat": flat,
                    "change_small": settled, "stop": flat and settled})
    return out


def projection(files: list[dict], log: list[dict], max_change: float = STOP_MAX_CHANGE,
               last: int = 4, first_stage: int = 1_000_000) -> dict:
    """Where the change reaches the stop rule's bar, at the rate of the last stages.

    A straight line through log2(change) against log2(iterations) over the last ``last``
    stages with a change (least squares) gives the factor the change is multiplied by at
    each doubling, and the iterations where it reaches ``max_change``. The run can only stop
    at a stage (``first_stage`` times a power of 2), so the stage after that is given too.
    The speed is that of the trainer's last sessions of a minute or more (``log.jsonl``),
    which overstates what is left a little: the states per iteration still rise as it trains.
    """
    pts = [(f["iterations"], f["change"]) for f in files if f.get("change")][-last:]
    out = {"stages_used": [p[0] for p in pts]}
    if len(pts) < 3:
        out["reason"] = "fewer than 3 stages with a change"
        return out
    xs = [math.log2(i) for i, _ in pts]
    ys = [math.log2(c) for _, c in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    out["factor_per_doubling"] = 2 ** slope
    if slope >= 0:
        out["reason"] = "the change is not falling over these stages"
        return out
    x_star = mx + (math.log2(max_change) - my) / slope
    target = 2 ** x_star
    stage = first_stage
    while stage < target:
        stage *= 2
    out.update(iterations=target, stage=stage)
    lines = [x for x in log if x.get("seconds", 0) >= 60 and x.get("to") is not None
             and x.get("from") is not None][-3:]
    if lines:
        ips = sum(x["to"] - x["from"] for x in lines) / sum(x["seconds"] for x in lines)
        out["iterations_per_second"] = ips
        out["hours_left"] = max(0.0, stage - pts[-1][0]) / ips / 3600
    return out


# --- running things --------------------------------------------------------------------------------

class Runner:
    """The measurements themselves; tests replace these methods with fakes."""

    def __init__(self, blueprint: str = BLUEPRINT, tables: Optional[str] = None,
                 say: Callable[[str], None] = print):
        self.blueprint = blueprint
        self.tables = tables
        self.say = say

    def _json_lines(self, args: list[str]) -> list[dict]:
        p = subprocess.run(args, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed ({p.returncode}): {p.stderr[-2000:]}")
        return [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]

    def header(self, path: str) -> dict:
        p = subprocess.run([self.blueprint, "info", path], capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"blueprint info {path}: {p.stderr[-1000:]}")
        return json.loads(p.stdout)

    def lbr(self, paths: list[str], names: list[str], settings: list[str], hands: int,
            seed: int, deals_dir: str) -> list[dict]:
        """LBR at each setting against each file, in one process: LBR's exact preflop win
        probabilities take minutes the first time and are then shared. Each result gets
        ``setting_short``."""
        args = [self.blueprint, "lbr", "--strategy", ",".join(paths), "--label", ",".join(names),
                "--hands", str(hands), "--seed", str(seed), "--settings", ",".join(settings),
                "--deals", deals_dir]
        if self.tables:
            args += ["--tables", self.tables]
        out = []
        for r in self._json_lines(args):
            m = re.search(r"\.([a-z0-9_]+)\.s\d+\.deals$", r.get("deals_file") or "")
            r["setting_short"] = m.group(1) if m else None
            out.append(r)
        return out

    def compare(self, a: str, b: str) -> dict:
        return self._json_lines([self.blueprint, "compare", "--a", a, "--b", b])[-1]

    def h2h(self, a: str, b: str, deals: int, seed: int, stack_bb: int) -> dict:
        """File b against file a; b's result."""
        import pokerscribe_engine as pe

        def agent(path):
            return f"blueprint:{path}" + (f"?tables={self.tables}" if self.tables else "")
        report = pe.run_match([agent(a), agent(b)], deals, seed, stack=stack_bb * 100,
                              small_blind=50, big_blind=100).to_dict()
        r = next(x for x in report["results"] if x["index"] == 1)
        return {"bb_per_100": r["bb_per_100"], "se": r["se"], "hands": report["hands"],
                "deals": report["deals"], "seconds": report["timing"]["seconds"],
                "illegal_actions": [x["illegal_actions"] for x in report["results"]]}

    def b0(self, path: str, deals: int, seed: int, processes: int, stack_bb: int,
           out_dir: str, name: str) -> dict:
        """B0 against the file, split over processes; each part saved, then pooled."""
        os.makedirs(out_dir, exist_ok=True)
        opponent = f"blueprint:{path}" + (f"?tables={self.tables}" if self.tables else "")
        per = [deals // processes + (1 if i < deals % processes else 0) for i in range(processes)]
        procs = []
        for i, n in enumerate(per):
            if not n:
                continue
            out = os.path.join(out_dir, f"{name}.d{deals}.s{seed + i}.json")
            if os.path.exists(out):
                procs.append((out, None))
                continue
            log = open(out + ".log", "w")
            p = subprocess.Popen([sys.executable, B0_ARENA, opponent, "--deals", str(n),
                                  "--seed", str(seed + i), "--stack-bb", str(stack_bb),
                                  "--out", out + ".part"], stdout=log, stderr=subprocess.STDOUT,
                                 cwd=REPO)
            procs.append((out, p))
        for out, p in procs:
            if p is not None and p.wait() != 0:
                raise RuntimeError(f"B0 match failed: see {out}.log")
            if p is not None:
                os.replace(out + ".part", out)
        parts = []
        illegal = 0
        seconds = 0.0
        for out, _ in procs:
            with open(out, encoding="utf-8") as f:
                d = json.load(f)
            bp = next(r for r in d["results"] if r["index"] == 1)
            parts.append({"deals": d["deals"], "hands": d["hands"], "bb_per_100": bp["bb_per_100"],
                          "se": bp["se"]})
            illegal += sum(sum(s["illegal"].values()) for s in d.get("b0", []))
            seconds = max(seconds, d["timing"]["seconds"])
        pooled = pool(parts)
        return {"blueprint_bb_per_100": pooled["bb_per_100"], "se": pooled["se"],
                "sd_per_deal": pooled["sd_per_deal"], "deals": pooled["deals"],
                "hands": pooled["hands"], "processes": len(parts), "b0_not_legal_as_said": illegal,
                "wall_seconds": seconds,
                "hands_per_second": pooled["hands"] / seconds if seconds else None}


def evaluate(paths: list[str], out: str, runner: Runner, settings: list[str],
             lbr_hands: int, h2h_deals: int, b0_deals: int, b0_processes: int,
             b0_which: str = "last", stages: Optional[str] = None, log: Optional[str] = None,
             lbr_seed: int = LBR_SEED,
             h2h_seed: int = H2H_SEED, b0_seed: int = B0_SEED, stack_bb: int = STACK_BB,
             skip: tuple = ()) -> dict:
    say = runner.say
    os.makedirs(out, exist_ok=True)
    deals_dir = os.path.join(out, "deals", f"h{lbr_hands}")
    files = []
    for p in paths:
        h = runner.header(p)
        files.append({"path": os.path.abspath(p), "iterations": int(h["iterations"]),
                      "info_sets": h.get("info_sets"), "visited": h.get("visited"),
                      "train_seconds": h.get("train_seconds")})
    files.sort(key=lambda f: f["iterations"])
    if len({f["iterations"] for f in files}) != len(files):
        raise SystemExit("two files have the same iterations: give each stage once")
    for f in files:
        f["label"] = label(f["iterations"])
    st = stage_changes(stages or os.path.join(os.path.dirname(files[0]["path"]),
                                              "stages.jsonl") if files else None)
    for f in files:
        s = st.get(f["iterations"]) or {}
        f["change"], f["change_from"] = s.get("change"), s.get("change_from")
        f["regrets"], f["pruning"] = s.get("regrets"), s.get("pruning")
    n = len(files)
    say(f"{n} strategy files: {', '.join(f['label'] for f in files)}")

    # 1. LBR
    lbr, lbr_pairs = {}, {}
    lbr_log = os.path.join(out, "lbr.jsonl")
    done = {(d["strategy"], d["setting_short"], d["seed_asked"], d["hands_asked"]): d
            for d in read_jsonl(lbr_log) if "setting_short" in d}
    if "lbr" not in skip:
        todo = [f for f in files if any((f["label"], s, lbr_seed, lbr_hands) not in done
                                        for s in settings)]
        if todo:
            want = [s for s in settings if any((f["label"], s, lbr_seed, lbr_hands) not in done
                                               for f in todo)]
            say(f"LBR {', '.join(want)} against {', '.join(f['label'] for f in todo)}, "
                f"{lbr_hands:,} hands each (one process)")
            t = time.time()
            by_label = {f["label"]: f for f in todo}
            for r in runner.lbr([f["path"] for f in todo], [f["label"] for f in todo], want,
                                lbr_hands, lbr_seed, deals_dir):
                f = by_label[r["strategy"]]
                r.update(iterations=f["iterations"], seed_asked=lbr_seed, hands_asked=lbr_hands)
                key = (f["label"], r["setting_short"], lbr_seed, lbr_hands)
                if key not in done:
                    append_jsonl(lbr_log, r)
                    done[key] = r
                say(f"LBR {r['setting_short']} against {f['label']}: {r['bb_per_100']:+.1f} +- "
                    f"{r['std_err']:.1f} bb/100 ({r['hands']} hands, {r['seconds']:.0f} s)")
            say(f"LBR took {time.time() - t:.0f} s")
        for s in settings:
            for i, f in enumerate(files):
                lbr[(s, i)] = done[(f["label"], s, lbr_seed, lbr_hands)]
            for i, j in pairs(n):
                a, b = lbr[(s, j)]["deals_file"], lbr[(s, i)]["deals_file"]
                c = runner.compare(a, b)     # later minus earlier
                lbr_pairs[(s, i, j)] = c

    # 2. head to head
    h2h = {}
    h2h_log = os.path.join(out, "h2h.jsonl")
    hdone = {(d["a"], d["b"], d["deals_asked"], d["seed"], d["stack_bb"]): d
             for d in read_jsonl(h2h_log)}
    if "h2h" not in skip:
        for i, j in pairs(n):
            key = (files[i]["label"], files[j]["label"], h2h_deals, h2h_seed, stack_bb)
            if key not in hdone:
                r = runner.h2h(files[i]["path"], files[j]["path"], h2h_deals, h2h_seed, stack_bb)
                r.update(a=key[0], b=key[1], deals_asked=h2h_deals, seed=h2h_seed,
                         stack_bb=stack_bb)
                append_jsonl(h2h_log, r)
                hdone[key] = r
                say(f"head to head, {key[1]} against {key[0]}: {r['bb_per_100']:+.2f} +- "
                    f"{r['se']:.2f} bb/100 ({r['hands']} hands)")
            h2h[(i, j)] = hdone[key]

    # 3. B0
    b0 = {}
    if "b0" not in skip and b0_deals > 0 and n:
        which = range(n) if b0_which == "all" else [n - 1]
        for i in which:
            f = files[i]
            r = runner.b0(f["path"], b0_deals, b0_seed, b0_processes, stack_bb,
                          os.path.join(out, "b0"), f["label"])
            r["needed_hands"] = {f"{e:g}": hands_needed(r["sd_per_deal"], e) for e in EDGES}
            if r["blueprint_bb_per_100"]:
                r["needed_hands"]["measured"] = hands_needed(r["sd_per_deal"],
                                                             r["blueprint_bb_per_100"])
            b0[i] = r
            say(f"B0 against {f['label']}: blueprint {r['blueprint_bb_per_100']:+.1f} +- "
                f"{r['se']:.1f} bb/100 over {r['hands']} hands; sd {r['sd_per_deal']:.0f} a deal")

    summary = {"files": files, "settings": settings, "seeds": {"lbr": lbr_seed, "h2h": h2h_seed,
                                                               "b0": b0_seed},
               "lbr_hands": lbr_hands, "h2h_deals": h2h_deals, "b0_deals": b0_deals,
               "stack_bb": stack_bb,
               "lbr": [dict(setting=s, file=files[i]["label"], bb_per_100=v["bb_per_100"],
                            se=v["std_err"], hands=v["hands"],
                            hands_per_second=v.get("hands_per_second"),
                            off_tree_share=(v.get("extra") or {}).get("off_tree_share"))
                       for (s, i), v in sorted(lbr.items(), key=lambda kv: (kv[0][0], kv[0][1]))],
               "lbr_changes": [dict(setting=s, earlier=files[i]["label"], later=files[j]["label"],
                                    difference=v["difference"], se=v["std_err"], z=v["z"])
                               for (s, i, j), v in lbr_pairs.items()],
               "h2h": [dict(earlier=files[i]["label"], later=files[j]["label"], **v)
                       for (i, j), v in h2h.items()],
               "b0": [dict(file=files[i]["label"], **v) for i, v in b0.items()],
               "gate": gate_readings(files, {k: v["bb_per_100"] for k, v in lbr.items()},
                                     lbr_pairs, h2h, b0, settings),
               "stop_rule": stop_rule(files, {k: v["bb_per_100"] for k, v in lbr.items()},
                                      lbr_pairs),
               "projection": projection(files, read_jsonl(log or os.path.join(
                   os.path.dirname(files[0]["path"]), "log.jsonl")) if files else [])}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(summary))
    say(f"summary: {os.path.join(out, 'summary.md')}")
    return summary


def fmt(x, digits=1, sign=True):
    if x is None:
        return "?"
    return f"{x:+.{digits}f}" if sign else f"{x:.{digits}f}"


def markdown(s: dict) -> str:
    out = ["# Blueprint evaluation", ""]
    out.append(f"Seeds: LBR {s['seeds']['lbr']}, head to head {s['seeds']['h2h']}, B0 "
               f"{s['seeds']['b0']} and up. Stacks {s['stack_bb']} big blinds.")
    out += ["", "## Files", "", "| File | Iterations | Change from the stage before | Compared with |",
            "| --- | ---: | ---: | --- |"]
    for f in s["files"]:
        out.append(f"| {f['label']} | {f['iterations']:,} | "
                   f"{'?' if f['change'] is None else f'{f['change']:.4f}'} | "
                   f"{f['change_from'] or ''} |")
    if s["lbr"]:
        out += ["", f"## LBR ({s['lbr_hands']:,} hands, the same deals for every file)", "",
                "| Setting | File | LBR wins, bb/100 | SE | Hands/s | Off the menu |",
                "| --- | --- | ---: | ---: | ---: | ---: |"]
        for r in s["lbr"]:
            off = r.get("off_tree_share")
            out.append(f"| {r['setting']} | {r['file']} | {fmt(r['bb_per_100'])} | "
                       f"{fmt(r['se'], sign=False)} | {fmt(r.get('hands_per_second'), 0, False)} | "
                       f"{'' if off is None else f'{100 * off:.1f}%'} |")
        out += ["", "Later minus earlier, deal by deal (negative: LBR wins less, the later file "
                    "is harder to exploit):", "",
                "| Setting | Earlier | Later | Difference | SE | z |", "| --- | --- | --- | ---: | ---: | ---: |"]
        for r in s["lbr_changes"]:
            out.append(f"| {r['setting']} | {r['earlier']} | {r['later']} | {fmt(r['difference'])} | "
                       f"{fmt(r['se'], sign=False)} | {fmt(r['z'], 2)} |")
    if s["h2h"]:
        out += ["", f"## Head to head ({s['h2h_deals']:,} deals, each twice with the seats swapped, "
                    f"all-in equity)", "", "| Later | Earlier | Later wins, bb/100 | SE | z | Hands |",
                "| --- | --- | ---: | ---: | ---: | ---: |"]
        for r in s["h2h"]:
            out.append(f"| {r['later']} | {r['earlier']} | {fmt(r['bb_per_100'], 2)} | "
                       f"{fmt(r['se'], 2, False)} | {fmt(z_of(r['bb_per_100'], r['se']), 2)} | "
                       f"{r['hands']:,} |")
    if s["b0"]:
        out += ["", "## B0 heads-up", "", "| File | Blueprint wins, bb/100 | SE | z | Hands | sd a deal | "
                "Hands for 2.5 SE at 5 / 10 / 20 bb/100 | At the edge measured | Hands/s, all processes |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |"]
        for r in s["b0"]:
            nh = r["needed_hands"]
            out.append(f"| {r['file']} | {fmt(r['blueprint_bb_per_100'])} | {fmt(r['se'], sign=False)} | "
                       f"{fmt(z_of(r['blueprint_bb_per_100'], r['se']), 2)} | {r['hands']:,} | "
                       f"{fmt(r['sd_per_deal'], 0, False)} | {nh['5']:,} / {nh['10']:,} / {nh['20']:,} | "
                       f"{nh.get('measured', 0):,} | {fmt(r.get('hands_per_second'), 1, False)} |")
    if s.get("stop_rule"):
        out += ["", f"## The stop rule (change at most {STOP_MAX_CHANGE:g}, and {STOP_SETTING} moved by "
                    f"less than {100 * STOP_RELATIVE:g}% or {STOP_SIGMAS:g} SE)", "",
                "| Stage | Change | LBR moved | z | Stop here |", "| --- | ---: | ---: | ---: | --- |"]
        for r in s["stop_rule"]:
            out.append(f"| {r['stage']} | {'?' if r['change'] is None else f'{r['change']:.4f}'} | "
                       f"{fmt(r['lbr_move'])} | {fmt(r['lbr_move_z'], 2)} | "
                       f"{'yes' if r['stop'] else 'no'} |")
    p = s.get("projection") or {}
    if p:
        out += ["", "## Projection", ""]
        if "iterations" not in p:
            out.append(f"Not made: {p.get('reason')}.")
        else:
            used = ", ".join(label(i) for i in p["stages_used"])
            line = (f"Over the stages {used} the change was multiplied by "
                    f"{p['factor_per_doubling']:.2f} at each doubling; at that rate it reaches "
                    f"{STOP_MAX_CHANGE:g} at about {p['iterations']:,.0f} iterations, so the stop "
                    f"rule could first say stop at the stage {label(p['stage'])}.")
            if "hours_left" in p:
                line += (f" At the trainer's last speed ({p['iterations_per_second']:,.0f} "
                         f"iterations a second) that is {p['hours_left']:.1f} more hours of "
                         f"training, a little more as the states per iteration rise, plus the "
                         f"pauses at each stage.")
            out.append(line)
    g = s["gate"]
    out += ["", "## The gate under each wording", ""]
    for setting, a in g["a_lbr_falls_at_every_checkpoint"].items():
        out.append(f"- (a) as written, LBR falls at every checkpoint, {setting}: fell at "
                   f"{a['fell']} of {a['steps']} steps ({a['fell_by_2_5_se']} by 2.5 SE; it rose by "
                   f"2.5 SE at {a['rose_by_2_5_se']}): {'yes' if a['every_step_fell'] else 'no'}")
    b = g["b_last_beats_first_by_2_5_se"]
    out.append("- (b) the last file beats the first head to head by 2.5 SE: " + (
        "not measured" if not b else f"{fmt(b['bb_per_100'], 2)} +- {fmt(b['se'], 2, False)} bb/100, "
        f"z {fmt(b['z'], 2)}: {'yes' if b['passes'] else 'no'}"))
    c = g["c_lbr_menu_bets_falls_first_to_last"]
    out.append("- (c) LBR with menu bets only falls from the first file to the last: " + (
        "not measured" if not c else f"{c['setting']} {fmt(c['first'])} to {fmt(c['last'])}, "
        f"difference {fmt(c['difference'])} +- {fmt(c['se'], sign=False)} (z {fmt(c['z'], 2)}): "
        f"{'yes' if c['falls'] else 'no'}{', by 2.5 SE' if c['falls_by_2_5_se'] else ''}"))
    d = g["b0_beaten_by_2_5_se"]
    out.append("- in every wording, the blueprint beats B0 heads-up by 2.5 SE: " + (
        "not measured" if not d else f"{fmt(d['bb_per_100'])} +- {fmt(d['se'], sign=False)} bb/100, "
        f"z {fmt(d['z'], 2)}: {'yes' if d['passes'] else 'no'}"))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("strategies", nargs="+", help="strategy files (.bps), any order")
    ap.add_argument("--tables", help="the bucket tables (default: the folder each file names)")
    ap.add_argument("--out", required=True, help="results folder (reused: done work is kept)")
    ap.add_argument("--stages", help="the run's stages.jsonl (default: next to the files)")
    ap.add_argument("--log", help="the trainer's log.jsonl, for the speed (default: next to the "
                                  "files)")
    ap.add_argument("--lbr", default="fcpa14,b56_14", help="LBR settings (fcpa14, fcpa34, b56_14, "
                                                         "b56_34, fc14, fc34)")
    ap.add_argument("--lbr-hands", type=int, default=20000)
    ap.add_argument("--h2h-deals", type=int, default=200000,
                    help="deals; each played twice (200,000: about 2 s of play, plus 15 s "
                         "to load a pair of files)")
    ap.add_argument("--b0-deals", type=int, default=4000, help="deals; each played twice")
    ap.add_argument("--b0-processes", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--b0", choices=("last", "all", "none"), default="last")
    ap.add_argument("--blueprint", default=BLUEPRINT, help="the blueprint binary")
    ap.add_argument("--skip", default="", help="lbr, h2h or b0, comma-separated")
    a = ap.parse_args(argv)
    if not os.path.exists(a.blueprint):
        print(f"{a.blueprint} is missing: cargo build --release --bin blueprint (in engine/)",
              file=sys.stderr)
        return 2
    skip = tuple(x.strip() for x in a.skip.split(",") if x.strip())
    if a.b0 == "none":
        skip += ("b0",)
    runner = Runner(a.blueprint, os.path.expanduser(a.tables) if a.tables else None)
    evaluate(a.strategies, a.out, runner, [x for x in a.lbr.split(",") if x], a.lbr_hands,
             a.h2h_deals, a.b0_deals, a.b0_processes, a.b0, a.stages, a.log, skip=skip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
