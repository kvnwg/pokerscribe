"""The Phase 7 run read on the Mac, by the rules pre-registered in experiments.md ("Phase 7: the
plan at 200 big blinds") and set in phase7.json, next to this file.

    python docs/research/runs/phase7/gate.py OUT

OUT holds the run's results, downloaded from the bucket (README.md, "Read the results"). The
plan job decided N, the bound check and the gate's reading on the machine; this works each of
them out again from the raw results and the plan's rules, and says where they differ:

- the bound: `bench.json`'s slowest decision per street against `bench.bound_ms`;
- N: (z x sd / edge)^2 deals from the pilot's sd (`pilot.json`), rounded up to a multiple of
  `size.step`, within `size.min` and `size.max`, as `size.json` has it;
- the gate: the chunks `match-NN.json` pooled (weighted by deals), z against `gate.pass_z`,
  as `gate.json` has it. It passes on that match alone; the pilot is not pooled with it;
- reported, not judged: the repeat (`repeat-NN.json`, after a pass), the variants
  (`variant-NAME-NN.json`), LBR against both agents (`lbr-*.json`, `compare-*.json`).

It writes OUT/summary.md and OUT/summary.json, and exits 1 if a decision of the job doesn't
match the rules.
"""
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def agent(report, name):
    return next(r for r in report["results"] if r["agent"] == name)


def deals_for(sd: float, rule) -> int:
    n = (rule["z"] * sd / rule["edge_bb_per_100"]) ** 2
    n = math.ceil(n / rule["step"]) * rule["step"]
    return min(rule["max"], max(rule["min"], n))


def pool(reports):
    """The search agent's result over chunks: the mean weighted by deals, its SE, z."""
    total = sum(r["deals"] for r in reports)
    mean = sum(agent(r, "search")["bb_per_100"] * r["deals"] for r in reports) / total
    se = math.sqrt(sum((agent(r, "search")["se"] * r["deals"]) ** 2 for r in reports)) / total
    illegal = sum(agent(r, a)["illegal_actions"] for r in reports for a in ("search", "blueprint"))
    hours = sum(r["timing"]["seconds"] for r in reports) / 3600
    return {"deals": total, "hands": 2 * total, "bb_per_100": mean, "se": se,
            "z": mean / se if se > 0 else 0.0, "illegal_actions": illegal, "hours": hours,
            "seeds": [r["config"]["seed"] for r in reports]}


def chunks(out, prefix, n):
    files = [os.path.join(out, f"{prefix}-{k:02d}.json") for k in range(1, n + 1)]
    missing = [os.path.basename(f) for f in files if not os.path.exists(f)]
    if missing:
        return {"missing": missing}
    return pool([load(f) for f in files])


def bounds(bench, limits):
    rows, over = {}, []
    for street in ("flop", "turn", "river"):
        x = bench.get(street) or {}
        slowest = x.get("decision_ms_max") if x.get("decisions") else None
        within = slowest is None or slowest <= limits[street]
        rows[street] = {"decisions": x.get("decisions", 0), "max_ms": slowest,
                        "bound_ms": limits[street], "within": within}
        if not within:
            over.append(street)
    return {"streets": rows, "bounded": not over, "over": over}


def close(a, b):
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def read(out: str, plan) -> dict:
    r = {"differences": []}
    diff = r["differences"].append
    # The bound.
    if os.path.exists(os.path.join(out, "bench.json")):
        r["bench"] = load(os.path.join(out, "bench.json"))
        r["bounds"] = bounds(r["bench"], plan["bench"]["bound_ms"])
        job = os.path.join(out, "bounds.json")
        if os.path.exists(job) and load(job)["bounded"] != r["bounds"]["bounded"]:
            diff("bounds.json: the bound check differs")
    # N.
    if os.path.exists(os.path.join(out, "pilot.json")):
        pilot = load(os.path.join(out, "pilot.json"))
        s = agent(pilot, "search")
        sd = s["se"] * math.sqrt(pilot["deals"])
        n = deals_for(sd, plan["size"])
        r["size"] = {"pilot_deals": pilot["deals"], "pilot_seed": pilot["config"]["seed"],
                     "pilot_bb_per_100": s["bb_per_100"], "pilot_se": s["se"], "sd_per_deal": sd,
                     "deals": n, "chunks": n // plan["gate"]["chunk"],
                     "edge_seen": plan["size"]["z"] * sd / math.sqrt(n),
                     "seconds_per_deal": pilot["timing"]["seconds"] / pilot["deals"]}
        job = os.path.join(out, "size.json")
        if os.path.exists(job) and load(job)["deals"] != n:
            diff(f"size.json: {load(job)['deals']} deals, the rule gives {n}")
    # The gate.
    if "size" in r:
        g = chunks(out, "match", r["size"]["chunks"])
        r["gate_match"] = g
        if "missing" in g:
            r["gate"] = f"not read yet: {len(g['missing'])} chunk(s) missing"
        else:
            passes = g["z"] >= plan["gate"]["pass_z"]
            r["gate"] = "passes" if passes else "does not pass"
            job = os.path.join(out, "gate.json")
            if os.path.exists(job):
                j = load(job)
                if j["passes"] != passes or not close(j["z"], g["z"]):
                    diff("gate.json: the job's reading differs")
            if glob.glob(os.path.join(out, "repeat-*.json")):
                r["repeat"] = chunks(out, "repeat", r["size"]["chunks"])
    # The variants.
    r["variants"] = {}
    for v in plan["variants"]:
        m = chunks(out, f"variant-{v['name']}", v["chunks"])
        if "missing" not in m and "gate_match" in r and "missing" not in r["gate_match"]:
            g = r["gate_match"]
            se = math.sqrt(m["se"] ** 2 + g["se"] ** 2)
            m["minus_gate_agent"] = {"bb_per_100": m["bb_per_100"] - g["bb_per_100"], "se": se,
                                     "z": (m["bb_per_100"] - g["bb_per_100"]) / se}
        m["agent"] = v["agent"]
        r["variants"][v["name"]] = m
    # LBR.
    r["lbr"] = {}
    for s in plan["lbr"]["settings"]:
        name, row = s["name"], {}
        for who in ("blueprint", "search"):
            runs = [load(f) for f in sorted(glob.glob(os.path.join(out, f"lbr-{who}-{name}-*.json")))]
            if runs:
                hands = sum(x["hands"] for x in runs)
                mean = sum(x["lbr_bb_per_100"] * x["hands"] for x in runs) / hands
                se = math.sqrt(sum((x["se"] * x["hands"]) ** 2 for x in runs)) / hands
                row[who] = {"bb_per_100": mean, "se": se, "hands": hands,
                            "hours": sum(x["seconds"] for x in runs) / 3600}
        cmps = [load(f) for f in sorted(glob.glob(os.path.join(out, f"compare-{name}-*.json")))]
        if cmps:
            # The runs have the same number of hands, so they weigh the same.
            mean = sum(c["a_minus_b"] for c in cmps) / len(cmps)
            se = math.sqrt(sum(c["se"] ** 2 for c in cmps)) / len(cmps)
            row["search_minus_blueprint"] = {"bb_per_100": mean, "se": se,
                                             "z": mean / se if se > 0 else 0.0}
        r["lbr"][name] = row
    if os.path.exists(os.path.join(out, "end.json")):
        r["end"] = load(os.path.join(out, "end.json"))["end"]
    return r


def markdown(r, plan) -> str:
    lines = ["# Phase 7 gate: search against the blueprint at 200 big blinds", ""]
    if r.get("end"):
        lines += [f"The job ended: {r['end']}.", ""]
    b = r.get("bench")
    if b:
        bd = r["bounds"]
        lim = plan["bench"]["bound_ms"]
        lines.append(f"Decision time, {b['hands']} hands on {b['threads']} threads:")
        lines.append("")
        lines.append("| Street | Decisions | p50 | p95 | Max | Bound | Iterations (mean) |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for s in ("flop", "turn", "river"):
            x = b.get(s) or {}
            if x.get("decisions"):
                lines.append(f"| {s} | {x['decisions']} | {x['decision_ms_p50']:,.0f} ms | "
                             f"{x['decision_ms_p95']:,.0f} ms | {x['decision_ms_max']:,.0f} ms | "
                             f"{lim[s] / 1000:g} s | {x['mean_iterations']:.0f} |")
        lines += ["", "Bounded: " + ("yes." if bd["bounded"]
                                     else "no, over on " + ", ".join(bd["over"]) + "."), ""]
    sz = r.get("size")
    if sz:
        lines.append(f"Pilot: {sz['pilot_deals']:,} deals (seed {sz['pilot_seed']}), search "
                     f"{sz['pilot_bb_per_100']:+.2f} ± {sz['pilot_se']:.2f} bb/100, sd "
                     f"{sz['sd_per_deal']:.0f} a deal, {sz['seconds_per_deal']:.2f} s a deal. "
                     f"N = {sz['deals']:,} deals ({sz['chunks']} chunks of "
                     f"{plan['gate']['chunk']:,}); at {plan['size']['z']} SE it sees an edge of "
                     f"{sz['edge_seen']:.1f} bb/100.")
        lines.append("")
    g = r.get("gate_match")
    if g:
        if "missing" in g:
            lines.append(f"Gate match: not finished; missing {', '.join(g['missing'])}.")
        else:
            lines.append("| Match | Deals | Search, bb/100 | SE | z | Illegal actions | Hours |")
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
            rows = [(f"Gate (seeds {plan['gate']['seed'] + 1} on)", g),
                    (f"Repeat (seeds {plan['repeat']['seed'] + 1} on)", r.get("repeat"))]
            rows += [(f"Variant `{n}` (reported)", v) for n, v in r["variants"].items()]
            for name, m in rows:
                if m and "missing" not in m:
                    lines.append(f"| {name} | {m['deals']:,} | {m['bb_per_100']:+.2f} | "
                                 f"{m['se']:.2f} | {m['z']:+.2f} | {m['illegal_actions']} | "
                                 f"{m['hours']:.1f} |")
            lines += ["", f"**The gate's head-to-head condition (beats the blueprint by "
                          f"{plan['gate']['pass_z']} SE): {r['gate']}.**", ""]
            for n, v in r["variants"].items():
                d = v.get("minus_gate_agent")
                if d:
                    lines.append(f"- `{n}` minus the gate agent: {d['bb_per_100']:+.2f} ± "
                                 f"{d['se']:.2f} bb/100 (z {d['z']:+.2f}, not paired).")
            lines.append("")
    if any(r["lbr"].values()):
        lines.append("| LBR setting | Against the blueprint | Against search | Search minus blueprint (paired) | z |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for setting, row in r["lbr"].items():
            def cell(x):
                return f"{x['bb_per_100']:+.1f} ± {x['se']:.1f} ({x['hands']:,})" if x else ""
            d = row.get("search_minus_blueprint")
            lines.append(f"| `{setting}` | {cell(row.get('blueprint'))} | {cell(row.get('search'))} | "
                         + (f"{d['bb_per_100']:+.1f} ± {d['se']:.1f} | {d['z']:+.2f} |" if d else " | |"))
        lines += ["", "LBR is reported, not judged.", ""]
    if r["differences"]:
        lines += ["**The job's decisions differ from the rules:**", ""]
        lines += [f"- {d}" for d in r["differences"]] + [""]
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = os.path.expanduser(argv[1])
    plan = load(os.path.join(HERE, "phase7.json"))
    r = read(out, plan)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(markdown(r, plan))
    print(json.dumps({"gate": r.get("gate"), "gate_match": r.get("gate_match"),
                      "differences": r["differences"]}, indent=1))
    print(f"summary: {os.path.join(out, 'summary.md')}")
    return 1 if r["differences"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
