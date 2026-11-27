"""B0 against Rust agents in the arena: results, speed, and the hands a 2.5 SE test needs.

    python docs/research/runs/phase6_b0_arena.py [--jobs 4]      # from the repo root

Plays the matches below (tools/b0_arena.py, heads-up, duplicate, all-in equity, 100 big
blinds), four at a time, and a profile of B0 against tag. Writes one JSON per match to
docs/research/runs/phase6_b0_arena/ and the tables to summary.md there.

The hands a test needs: with one sample per deal, SE = sd / sqrt(deals), so an edge of D
bb/100 is 2.5 SE after deals = (2.5 sd / D)^2, which is twice that in hands.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import math
import os
import pstats
import sys
import time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "research", "runs", "phase6_b0_arena")

# (label, opponent, variant, deals, seed, duplicate)
MATCHES = [
    ("b0", "b0", None, 400, 601, True),
    ("b0, plain", "b0", None, 1000, 602, False),
    ("b0 bet_size 0.5", "b0", {"bet_size": 0.5}, 1500, 603, True),
    ("fold", "fold", None, 1000, 604, True),
    ("call", "call", None, 1000, 605, True),
    ("tag", "tag", None, 3000, 606, True),
    ("tag-loose", "tag-loose", None, 3000, 607, True),
    ("lbr-random", "lbr-random", None, 1000, 608, True),
    ("lbr-call-or-raise", "lbr-call-or-raise", None, 1000, 609, True),
    ("jam", "jam", None, 1000, 610, True),
]
EDGES = (5.0, 10.0, 20.0)


def play(match):
    import b0_arena

    label, name, variant, deals, seed, duplicate = match
    other = b0_arena.opponent(name, variant)
    t0, c0 = time.time(), time.process_time()
    report, b0 = b0_arena.run(other, deals, seed, duplicate=duplicate)
    d = report.to_dict()
    d["label"] = label
    d["cpu_seconds"] = time.process_time() - c0
    d["b0"] = [p.stats() for p in [b0] + ([other] if isinstance(other, b0_arena.B0Player) else [])]
    path = os.path.join(OUT, label.replace(" ", "_").replace(",", "") + ".json")
    with open(path, "w") as f:
        json.dump(d, f, indent=1)
    return label, time.time() - t0


def profile(deals=150, seed=699):
    """Where B0's time goes against tag: cumulative seconds in the main calls."""
    import b0_arena

    prof = cProfile.Profile(time.process_time)  # CPU time, as the total
    t0 = time.process_time()
    prof.enable()
    report, b0 = b0_arena.run("tag", deals, seed)
    prof.disable()
    total = time.process_time() - t0
    st = pstats.Stats(prof)
    want = {
        "B0Player.act (everything B0 does)": ("b0_arena.py", "act"),
        "advise, with its own equity runs": ("advice.py", "advise"),
        "sim_compute (the equity the advice is given)": ("simulate.py", "sim_compute"),
        "equity (all Monte Carlo equity runs)": ("equity.py", "equity"),
        "app_state (the GameState)": ("simulate.py", "app_state"),
        "table (the simulator's Hand from the view)": ("b0_arena.py", "table"),
        "check_advice (the always-wrong checks)": ("simulate.py", "check_advice"),
        "engine_action (instruction to nlhe action)": ("b0_arena.py", "engine_action"),
        "treys evaluations (hands.evaluate)": ("hands.py", "evaluate"),
    }
    rows = []
    for label, (file, func) in want.items():
        cum = sum(v[3] for k, v in st.stats.items() if k[0].endswith(file) and k[2] == func)
        calls = sum(v[1] for k, v in st.stats.items() if k[0].endswith(file) and k[2] == func)
        rows.append((label, cum, calls))
    act = rows[0][1]
    return {"deals": deals, "hands": report.to_dict()["hands"], "cpu_seconds": total, "rows": rows,
            "outside_b0": total - act, "instructions": b0.instructions}


def summary():
    rows = []
    for match in MATCHES:
        label = match[0]
        with open(os.path.join(OUT, label.replace(" ", "_").replace(",", "") + ".json")) as f:
            d = json.load(f)
        r = d["results"][0]
        deals = d["deals"]
        # B0 against itself in duplicate play: every deal's two hands cancel, up to float noise
        exact = abs(r["se"]) < 1e-9 and abs(r["bb_per_100"]) < 1e-9
        se = 0.0 if exact else r["se"]
        sd = se * math.sqrt(deals)
        b0_seconds = sum(sum(x["seconds"].values()) for x in d["b0"])
        s = d["b0"][0]
        instructions = sum(x["instructions"] for x in d["b0"])
        illegal = {}
        wrong = {}
        for x in d["b0"]:
            for k, v in x["illegal"].items():
                illegal[k] = illegal.get(k, 0) + v
            for k, v in x["always_wrong"].items():
                wrong[k] = wrong.get(k, 0) + v
        need = [2 * math.ceil((2.5 * sd / e) ** 2) for e in EDGES] if sd > 0 else [0] * len(EDGES)
        rows.append({"label": label, "deals": deals, "hands": d["hands"], "bb": 0.0 if exact else r["bb_per_100"],
                     "se": se, "plain_se": r["plain_se"], "sd": sd, "z": r["bb_per_100"] / se if se else None,
                     "outside": 1 - b0_seconds / d["timing"]["seconds"],
                     "examples": [e for x in d["b0"] for e in x.get("always_wrong_examples", [])],
                     "hands_s": d["hands"] / d["cpu_seconds"], "ms": 1000 * d["cpu_seconds"] / max(1, instructions),
                     "per_hand": instructions / d["hands"], "illegal": illegal, "wrong": wrong, "need": need,
                     "adjusted": d["adjusted_hands"], "duplicate": d["config"]["duplicate"], "b0_hands": s["hands"]})
    lines = ["# B0 against Rust agents in the arena", "",
             "Made by `docs/research/runs/phase6_b0_arena.py`. Heads-up, 100 big blinds, blinds 50/100, B0 as",
             "agent 0. Duplicate (each deal twice, seats swapped) and all-in equity unless the row says plain.",
             "Speed is per CPU second of one process.", "",
             "| Opponent | Deals | Hands | B0 bb/100 | SE | z | Plain SE | sd per deal | All-in hands adjusted |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for x in rows:
        z = "" if x["z"] is None else f"{x['z']:+.1f}"
        lines.append(f"| {x['label']} | {x['deals']} | {x['hands']} | {x['bb']:+.2f} | {x['se']:.2f} | {z} | "
                     f"{x['plain_se']:.2f} | {x['sd']:.0f} | {x['adjusted']} |")
    lines += ["", "B0 against itself in duplicate play is exactly 0: B0 is deterministic, so each deal's two hands",
              "cancel (the report's 1e-15 is float noise).",
              "", "| Opponent | Hands/s | ms per B0 instruction | B0 instructions per hand | Time outside B0 | "
                  "Not legal as said | Always-wrong (simulate.check_advice) |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for x in rows:
        ill = ", ".join(f"{k} x{v}" for k, v in sorted(x["illegal"].items())) or "none"
        wr = ", ".join(f"{k} x{v}" for k, v in sorted(x["wrong"].items())) or "none"
        lines.append(f"| {x['label']} | {x['hands_s']:.1f} | {x['ms']:.1f} | {x['per_hand']:.2f} | "
                     f"{100 * x['outside']:.1f}% | {ill} | {wr} |")
    lines += ["", "Time outside B0: the match's time less the time in `B0Player.act` (the arena, the other agent,",
              "and crossing between Rust and Python)."]
    examples = [(x["label"], e) for x in rows for e in x["examples"]]
    if examples:
        lines += ["", "The always-wrong instructions (the first of each match, up to 25), with the betting so far:", ""]
        for label, e in examples:
            moves = " ".join(f"{'B0' if seat == e['seat'] else 'opp'} {a}{'' if amt is None else ' ' + str(amt)}"
                             for seat, a, amt in e["history"])
            lines.append(f"- {label}: {e['cards']} on the {e['position']}, {'; '.join(e['always_wrong'])}: "
                         f"{e['instruction']['headline']} after {moves} (played {e['played']})")
    lines += ["", "Hands for an edge to be 2.5 SE at this sd per deal (hands = 2 x (2.5 sd / edge)^2):", "",
              "| Opponent | sd per deal | " + " | ".join(f"Edge {e:g} bb/100" for e in EDGES) + " |",
              "| --- | --- | " + " | ".join("---" for _ in EDGES) + " |"]
    for x in rows:
        if x["duplicate"] and x["sd"] > 0:  # not B0 against itself, which is exactly 0
            lines.append(f"| {x['label']} | {x['sd']:.0f} | " + " | ".join(f"{n:,}" for n in x["need"]) + " |")
    prof_path = os.path.join(OUT, "profile.json")
    if os.path.exists(prof_path):
        with open(prof_path) as f:
            p = json.load(f)
        lines += ["", f"Profile, B0 against tag, {p['hands']} hands, {p['instructions']} B0 instructions, "
                      f"{p['cpu_seconds']:.1f} CPU seconds (cProfile slows Python down, so these are shares, not speeds):",
                  "", "| Part | Seconds | Share | Calls |", "| --- | --- | --- | --- |"]
        for label, cum, calls in p["rows"]:
            lines.append(f"| {label} | {cum:.2f} | {100 * cum / p['cpu_seconds']:.0f}% | {calls} |")
        lines.append(f"| Outside B0 (the arena, tag, crossing into Python) | {p['outside_b0']:.2f} | "
                     f"{100 * p['outside_b0'] / p['cpu_seconds']:.0f}% | |")
    with open(os.path.join(OUT, "summary.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--summary", action="store_true", help="only rebuild summary.md from the JSON")
    ap.add_argument("--only", nargs="*", metavar="LABEL", help="play only these matches (and no profile), then the summary")
    ap.add_argument("--profile", action="store_true", help="only the profile, then the summary")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if not a.summary and not a.profile:
        matches = [m for m in MATCHES if a.only is None or m[0] in a.only]
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            # the longest first, so the pool ends together
            order = sorted(matches, key=lambda m: -m[3] * (3 if m[1] in ("call", "b0") else 1))
            for label, seconds in ex.map(play, order):
                print(f"{label}: {seconds:.0f} s", flush=True)
    if a.profile or (not a.summary and a.only is None):
        p = profile()
        with open(os.path.join(OUT, "profile.json"), "w") as f:
            json.dump(p, f, indent=1)
    summary()


if __name__ == "__main__":
    main()
