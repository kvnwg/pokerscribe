"""The Phase 7 gate's sizing and reading, by the rules pre-registered in experiments.md
("Phase 7: the plan at 200 big blinds") and README.md here, "The plan".

    python docs/research/runs/phase7/gate.py bounds OUT   # OUT/bench.json against the bounds
    python docs/research/runs/phase7/gate.py size OUT     # N from OUT/pilot.json -> OUT/size.json
    python docs/research/runs/phase7/gate.py read OUT     # OUT/summary.md and OUT/summary.json

`bounds`: the slowest decision of each street in `search bench` (200 hands, 4 threads) against
the bound worked out before the run (README.md, "Decision time"): flop 12 s, turn 65 s, river
2 s. A street over its bound is named, and the match is not started until it is understood.

`size`: N = (2.5 x sd / 10)^2 deals, the deals a 2.5 SE result needs at an edge of 10 bb/100
at the pilot's sd a deal, rounded up to a multiple of 1,000, at least 4,000 and at most
40,000; played as N / 1,000 chunks of 1,000 deals.

`read`: the gate match (`match-NN.json`, seeds 7601 on) pooled over its chunks, the gate's
reading (passes at z >= 2.5, on that match alone; the pilot is not pooled with it), the
repeat on fresh seeds (`repeat-NN.json`, seeds 7701 on) when it was run, LBR pooled over its
chunks for both agents with the paired difference (reported, not judged), and the decision
times (`bench.json`) with the bound check. Chunks of a match that are missing are named, and
the gate is not read until all are there.
"""
import glob
import json
import math
import os
import sys

EDGE = 10.0
Z = 2.5
CHUNK, FLOOR, CAP = 1_000, 4_000, 40_000
GATE_SEED, REPEAT_SEED = 7600, 7700
SETTINGS = ("fcpa14", "b56_14")
# The slowest decision allowed per street on 4 threads, in ms (README.md, "Decision time").
BOUND_MS = {"flop": 12_000, "turn": 65_000, "river": 2_000}


def deals_for(sd: float) -> int:
    n = (Z * sd / EDGE) ** 2
    n = math.ceil(n / CHUNK) * CHUNK
    return min(CAP, max(FLOOR, n))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def agent(report, name):
    return next(r for r in report["results"] if r["agent"] == name)


def size(out: str) -> dict:
    pilot = load(os.path.join(out, "pilot.json"))
    deals = pilot["deals"]
    s = agent(pilot, "search")
    sd = s["se"] * math.sqrt(deals)
    n = deals_for(sd)
    per_deal = pilot["timing"]["seconds"] / deals
    result = {
        "pilot_deals": deals, "pilot_seed": pilot["config"]["seed"],
        "pilot_bb_per_100": s["bb_per_100"], "pilot_se": s["se"],
        "sd_per_deal": sd, "illegal_actions": s["illegal_actions"],
        "deals": n, "chunks": n // CHUNK, "hands": 2 * n,
        "edge_seen_at_2_5_se": Z * sd / math.sqrt(n),
        "seconds_per_deal": per_deal, "hours": n * per_deal / 3600,
        "seeds": [GATE_SEED + k for k in range(1, n // CHUNK + 1)],
    }
    with open(os.path.join(out, "size.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    return result


def bounds(out: str) -> dict:
    bench = load(os.path.join(out, "bench.json"))
    rows = {}
    for street, limit in BOUND_MS.items():
        x = bench.get(street) or {}
        slowest = x.get("decision_ms_max") if x.get("decisions") else None
        rows[street] = {"decisions": x.get("decisions", 0), "max_ms": slowest, "bound_ms": limit,
                        "within": slowest is None or slowest <= limit}
    over = [s for s, r in rows.items() if not r["within"]]
    return {"streets": rows, "bounded": not over, "over": over}


def pool(parts):
    """Pooled mean and SE of independent results [(mean, se, n)], weighted by n."""
    total = sum(n for _, _, n in parts)
    mean = sum(m * n for m, _, n in parts) / total
    se = math.sqrt(sum((s * n) ** 2 for _, s, n in parts)) / total
    return mean, se, total


def read_match(out, prefix, chunks):
    files = [os.path.join(out, f"{prefix}-{k:02d}.json") for k in range(1, chunks + 1)]
    missing = [os.path.basename(f) for f in files if not os.path.exists(f)]
    if missing:
        return {"missing": missing}
    parts, illegal, seconds, seeds = [], 0, 0.0, []
    for f in files:
        r = load(f)
        s = agent(r, "search")
        parts.append((s["bb_per_100"], s["se"], r["deals"]))
        illegal += s["illegal_actions"] + agent(r, "blueprint")["illegal_actions"]
        seconds += r["timing"]["seconds"]
        seeds.append(r["config"]["seed"])
    mean, se, deals = pool(parts)
    return {"deals": deals, "hands": 2 * deals, "bb_per_100": mean, "se": se,
            "z": mean / se if se > 0 else 0.0, "illegal_actions": illegal,
            "hours": seconds / 3600, "seeds": seeds}


def read_lbr(out):
    rows = {}
    for setting in SETTINGS:
        row = {}
        for who in ("search", "blueprint"):
            files = sorted(glob.glob(os.path.join(out, f"lbr-{who}-{setting}-*.json")))
            if files:
                runs = [load(f) for f in files]
                mean, se, hands = pool([(r["lbr_bb_per_100"], r["se"], r["hands"]) for r in runs])
                row[who] = {"bb_per_100": mean, "se": se, "hands": hands,
                            "hours": sum(r["seconds"] for r in runs) / 3600}
                if who == "search":
                    row["search_solves"] = [r.get("solves") for r in runs]
                    row["search_slowest_solve_ms"] = {
                        s: max((r.get("solves") or {}).get(s, {}).get("solve_ms_max") or 0
                               for r in runs)
                        for s in ("flop", "turn", "river")}
        cmp_files = sorted(glob.glob(os.path.join(out, f"compare-{setting}-*.json")))
        if cmp_files:
            # The chunks have the same number of hands, so they weigh the same.
            cmps = [load(f) for f in cmp_files]
            mean, se, _ = pool([(c["a_minus_b"], c["se"], 1) for c in cmps])
            row["search_minus_blueprint"] = {"bb_per_100": mean, "se": se,
                                             "z": mean / se if se > 0 else 0.0}
        rows[setting] = row
    return rows


def read(out: str) -> dict:
    sz = load(os.path.join(out, "size.json"))
    chunks = sz["chunks"]
    result = {"size": sz, "gate_match": read_match(out, "match", chunks)}
    if glob.glob(os.path.join(out, "repeat-*.json")):
        result["repeat"] = read_match(out, "repeat", chunks)
    result["lbr"] = read_lbr(out)
    bench = os.path.join(out, "bench.json")
    if os.path.exists(bench):
        result["bench"] = load(bench)
        result["bounds"] = bounds(out)
    g = result["gate_match"]
    if "missing" in g:
        result["gate"] = f"not read yet: {len(g['missing'])} chunk(s) missing"
    else:
        result["gate"] = "passes" if g["z"] >= Z else "does not pass"
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(markdown(result))
    return result


def markdown(r) -> str:
    sz, g = r["size"], r["gate_match"]
    lines = ["# Phase 7 gate: search against the blueprint at 200 big blinds", ""]
    lines.append(f"Pilot: {sz['pilot_deals']:,} deals (seed {sz['pilot_seed']}), search "
                 f"{sz['pilot_bb_per_100']:+.2f} ± {sz['pilot_se']:.2f} bb/100, sd "
                 f"{sz['sd_per_deal']:.0f} a deal, {sz['seconds_per_deal']:.2f} s a deal. "
                 f"N = {sz['deals']:,} deals ({sz['chunks']} chunks of {CHUNK:,}); at 2.5 SE "
                 f"it sees an edge of {sz['edge_seen_at_2_5_se']:.1f} bb/100.")
    lines.append("")
    if "missing" in g:
        lines.append(f"Gate match: not finished; missing {', '.join(g['missing'])}.")
    else:
        lines.append("| Match | Deals | Search, bb/100 | SE | z | Illegal actions | Hours |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for name, m in (("Gate (seeds 7601 on)", g), ("Repeat (seeds 7701 on)", r.get("repeat"))):
            if m and "missing" not in m:
                lines.append(f"| {name} | {m['deals']:,} | {m['bb_per_100']:+.2f} | "
                             f"{m['se']:.2f} | {m['z']:+.2f} | {m['illegal_actions']} | "
                             f"{m['hours']:.1f} |")
    lines += ["", f"**The gate's head-to-head condition (beats the blueprint by 2.5 SE): "
                  f"{r['gate']}.**", ""]
    lbr = r["lbr"]
    if any(lbr.values()):
        lines.append("| LBR setting | Against the blueprint | Against search | Search minus blueprint (paired) | z |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for setting, row in lbr.items():
            def cell(x):
                return f"{x['bb_per_100']:+.1f} ± {x['se']:.1f} ({x['hands']:,})" if x else ""
            d = row.get("search_minus_blueprint")
            lines.append(f"| `{setting}` | {cell(row.get('blueprint'))} | {cell(row.get('search'))} | "
                         + (f"{d['bb_per_100']:+.1f} ± {d['se']:.1f} | {d['z']:+.2f} |" if d else " | |"))
        lines += ["", "LBR is reported, not judged.", ""]
    b = r.get("bench")
    if b:
        lines.append(f"Decision time, `search bench`, {b['hands']} hands, {b['threads']} threads:")
        lines.append("")
        lines.append("| Street | Decisions | p50 | p95 | Max | Iterations (mean) | Exploitability (mean) |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for s in ("flop", "turn", "river"):
            x = b.get(s) or {}
            if x.get("decisions"):
                lines.append(f"| {s} | {x['decisions']} | {x['decision_ms_p50']:,.0f} ms | "
                             f"{x['decision_ms_p95']:,.0f} ms | {x['decision_ms_max']:,.0f} ms | "
                             f"{x['mean_iterations']:.0f} | {100 * x['mean_exploitability']:.2f}% |")
        lines.append("")
        bd = r["bounds"]
        lines.append("Bounded (slowest decision per street within flop 12 s, turn 65 s, river 2 s): "
                     + ("yes" if bd["bounded"] else "no, over on " + ", ".join(bd["over"])) + ".")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) != 3 or argv[1] not in ("bounds", "size", "read"):
        print(__doc__)
        return 2
    out = os.path.expanduser(argv[2])
    if argv[1] == "bounds":
        r = bounds(out)
        print(json.dumps(r, indent=1))
        return 0 if r["bounded"] else 1
    r = size(out) if argv[1] == "size" else read(out)
    print(json.dumps(r if argv[1] == "size" else {"gate": r["gate"], "gate_match": r["gate_match"]},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
