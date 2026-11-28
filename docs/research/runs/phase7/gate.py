"""The Phase 7 run read on the Mac, by the rules pre-registered in experiments.md ("Phase 7: the
plan at 200 big blinds") and set in phase7.json, next to this file.

    python docs/research/runs/phase7/gate.py OUT

OUT holds the run's results, downloaded from the bucket (README.md, "Read the results"). The
plan job decided N, the bound check and the gate's reading on the machine; this works each of
them out again from the raw results and the plan's rules, and says where they differ:

- the bound: `bench.json`'s slowest decision per street against `bench.bound_ms`;
- the measure (`gate.measure`, AIVAT as registered): the AIVAT figure, unless it is missing or
  an agent has an unexplained decision in the result read, and then the plain figure (duplicate
  deals, all-in equity); both are reported;
- N: (z x sd / edge)^2 deals from the pilot's sd on the measure (`pilot.json`), rounded up to a
  multiple of `size.step`, within `size.min` and `size.max`, as `size.json` has it;
- the gate: the chunks `match-NN.json` pooled (weighted by deals), z on the measure against
  `gate.pass_z`, as `gate.json` has it. It passes on that match alone; the pilot is not pooled
  with it;
- for promotion: the repeat (`repeat-NN.json`, after a pass), read the same way;
- reported, not judged: the variants (`variant-NAME-NN.json`), LBR against both agents
  (`lbr-*.json`, `compare-*.json`).

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
    """The search agent's result over chunks: the mean weighted by deals, its SE, z; and the
    same for AIVAT (None unless every chunk has it), with the decisions it corrected."""
    total = sum(r["deals"] for r in reports)

    def pooled(field, se_field=None, of=lambda r: agent(r, "search")):
        mean = sum(of(r)[field] * r["deals"] for r in reports) / total
        se = math.sqrt(sum((of(r)[se_field or "se"] * r["deals"]) ** 2 for r in reports)) / total
        return mean, se

    mean, se = pooled("bb_per_100")
    illegal = sum(agent(r, a)["illegal_actions"] for r in reports for a in ("search", "blueprint"))
    hours = sum(r["timing"]["seconds"] for r in reports) / 3600
    aivat = None
    if all(agent(r, "search").get("aivat") for r in reports):
        a_of = lambda r: agent(r, "search")["aivat"]  # noqa: E731
        am, ase = pooled("bb_per_100", of=a_of)
        dm, dse = pooled("minus_main", "minus_main_se", of=a_of)
        decisions = {who: {k: sum((agent(r, who).get("aivat") or {}).get(f"{k}_decisions", 0)
                                  for r in reports)
                           for k in ("corrected", "unknown", "unexplained")}
                     for who in ("search", "blueprint")}
        aivat = {"bb_per_100": am, "se": ase, "z": am / ase if ase > 0 else 0.0,
                 "minus_plain": dm, "minus_plain_se": dse, "se_ratio": ase / se if se > 0 else 0.0,
                 "decisions": decisions,
                 "unexplained_decisions": sum(d["unexplained"] for d in decisions.values())}
    return {"deals": total, "hands": 2 * total, "bb_per_100": mean, "se": se,
            "z": mean / se if se > 0 else 0.0, "illegal_actions": illegal, "hours": hours,
            "seeds": [r["config"]["seed"] for r in reports], "aivat": aivat}


def decides(pooled, measure):
    """The figure the measure asks for: AIVAT when it is there and no decision is unexplained,
    the plain figure otherwise (with the reason)."""
    def plain(why):
        return {"measure": "plain", "bb_per_100": pooled["bb_per_100"], "se": pooled["se"],
                "z": pooled["z"], "why": why}
    if measure == "plain":
        return plain(None)
    a = pooled.get("aivat")
    if not a:
        return plain("no AIVAT figure")
    if a["unexplained_decisions"] != 0:
        return plain("AIVAT has unexplained decisions")
    return {"measure": "aivat", "bb_per_100": a["bb_per_100"], "se": a["se"], "z": a["z"],
            "why": None}


def judge(pooled, gate):
    d = decides(pooled, gate["measure"])
    pooled["decides"] = d
    pooled["passes"] = d["z"] >= gate["pass_z"]
    return pooled["passes"]


def minus(variant, gate, measure):
    """A variant minus the gate agent, unpaired, on the measure when both can use it."""
    def diff(a, b):
        se = math.sqrt(a["se"] ** 2 + b["se"] ** 2)
        d = a["bb_per_100"] - b["bb_per_100"]
        return {"bb_per_100": d, "se": se, "z": d / se if se > 0 else 0.0}
    v, g = decides(variant, measure), decides(gate, measure)
    if v["measure"] != g["measure"]:
        v, g = decides(variant, "plain"), decides(gate, "plain")
    return {**diff(v, g), "measure": v["measure"], "plain": diff(variant, gate)}


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
        p = pool([pilot])
        d = decides(p, plan["gate"]["measure"])
        root = math.sqrt(pilot["deals"])
        sd = d["se"] * root
        n = deals_for(sd, plan["size"])
        r["size"] = {"pilot_deals": pilot["deals"], "pilot_seed": pilot["config"]["seed"],
                     "measure": d["measure"], "measure_why": d["why"],
                     "pilot_bb_per_100": d["bb_per_100"], "pilot_se": d["se"], "sd_per_deal": sd,
                     "plain": {"bb_per_100": p["bb_per_100"], "se": p["se"],
                               "sd_per_deal": p["se"] * root,
                               "deals": deals_for(p["se"] * root, plan["size"])},
                     "aivat": p["aivat"],
                     "deals": n, "chunks": n // plan["gate"]["chunk"],
                     "edge_seen": plan["size"]["z"] * sd / math.sqrt(n),
                     "seconds_per_deal": pilot["timing"]["seconds"] / pilot["deals"]}
        job = os.path.join(out, "size.json")
        if os.path.exists(job):
            j = load(job)
            if j["deals"] != n:
                diff(f"size.json: {j['deals']} deals, the rule gives {n}")
            if j.get("measure") != d["measure"]:
                diff(f"size.json: sized on {j.get('measure')}, the rule says {d['measure']}")
    # The gate.
    if "size" in r:
        g = chunks(out, "match", r["size"]["chunks"])
        r["gate_match"] = g
        if "missing" in g:
            r["gate"] = f"not read yet: {len(g['missing'])} chunk(s) missing"
        else:
            passes = judge(g, plan["gate"])
            r["gate"] = "passes" if passes else "does not pass"
            job = os.path.join(out, "gate.json")
            if os.path.exists(job):
                j = load(job)
                jd = j.get("decides") or {}
                if (j["passes"] != passes or jd.get("measure") != g["decides"]["measure"]
                        or not close(jd.get("z", float("nan")), g["decides"]["z"])):
                    diff("gate.json: the job's reading differs")
            if glob.glob(os.path.join(out, "repeat-*.json")):
                rp = chunks(out, "repeat", r["size"]["chunks"])
                if "missing" not in rp:
                    judge(rp, plan["gate"])
                r["repeat"] = rp
    # The variants.
    r["variants"] = {}
    for v in plan["variants"]:
        m = chunks(out, f"variant-{v['name']}", v["chunks"])
        if "missing" not in m and "gate_match" in r and "missing" not in r["gate_match"]:
            m["minus_gate_agent"] = minus(m, r["gate_match"], plan["gate"]["measure"])
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
        pl = sz["plain"]
        why = f" ({sz['measure_why']})" if sz.get("measure_why") else ""
        lines.append(f"Pilot: {sz['pilot_deals']:,} deals (seed {sz['pilot_seed']}), "
                     f"{sz['seconds_per_deal']:.2f} s a deal. Search, on {sz['measure']}{why}: "
                     f"{sz['pilot_bb_per_100']:+.2f} ± {sz['pilot_se']:.2f} bb/100, sd "
                     f"{sz['sd_per_deal']:.0f} a deal; plain: {pl['bb_per_100']:+.2f} ± "
                     f"{pl['se']:.2f}, sd {pl['sd_per_deal']:.0f} (it would give N = "
                     f"{pl['deals']:,}). N = {sz['deals']:,} deals ({sz['chunks']} chunks of "
                     f"{plan['gate']['chunk']:,}); at {plan['size']['z']} SE it sees an edge of "
                     f"{sz['edge_seen']:.1f} bb/100.")
        lines.append("")
    g = r.get("gate_match")
    if g:
        if "missing" in g:
            lines.append(f"Gate match: not finished; missing {', '.join(g['missing'])}.")
        else:
            lines.append("| Match | Deals | Search, AIVAT bb/100 | z | Plain bb/100 | z | "
                         "AIVAT minus plain | SE ratio | Unexplained decisions | Illegal actions "
                         "| Hours |")
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
                         "| ---: |")
            rows = [(f"Gate (seeds {plan['gate']['seed'] + 1} on)", g),
                    (f"Repeat (seeds {plan['repeat']['seed'] + 1} on)", r.get("repeat"))]
            rows += [(f"Variant `{n}` (reported)", v) for n, v in r["variants"].items()]
            for name, m in rows:
                if m and "missing" not in m:
                    a = m.get("aivat")
                    cells = ([f"{a['bb_per_100']:+.2f} ± {a['se']:.2f}", f"{a['z']:+.2f}"]
                             if a else ["", ""])
                    cells += [f"{m['bb_per_100']:+.2f} ± {m['se']:.2f}", f"{m['z']:+.2f}"]
                    cells += ([f"{a['minus_plain']:+.2f} ± {a['minus_plain_se']:.2f}",
                               f"{a['se_ratio']:.3f}", str(a["unexplained_decisions"])]
                              if a else ["", "", ""])
                    cells += [str(m["illegal_actions"]), f"{m['hours']:.1f}"]
                    lines.append(f"| {name} | {m['deals']:,} | " + " | ".join(cells) + " |")
            d = g["decides"]
            why = f" ({d['why']})" if d.get("why") else ""
            lines += ["", f"**The gate's head-to-head condition (beats the blueprint by "
                          f"{plan['gate']['pass_z']} SE), read on {d['measure']}{why}: "
                          f"{d['bb_per_100']:+.2f} ± {d['se']:.2f} bb/100, z {d['z']:+.2f}, "
                          f"{r['gate']}.**", ""]
            rp = r.get("repeat")
            if rp and "decides" in rp:
                d = rp["decides"]
                lines += [f"The repeat, read the same way (for promotion): {d['measure']}, "
                          f"z {d['z']:+.2f}, " + ("passes." if rp["passes"] else "does not pass."),
                          ""]
            for n, v in r["variants"].items():
                d = v.get("minus_gate_agent")
                if d:
                    lines.append(f"- `{n}` minus the gate agent, on {d['measure']}: "
                                 f"{d['bb_per_100']:+.2f} ± {d['se']:.2f} bb/100 (z "
                                 f"{d['z']:+.2f}, not paired); plain {d['plain']['bb_per_100']:+.2f}"
                                 f" ± {d['plain']['se']:.2f}.")
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
