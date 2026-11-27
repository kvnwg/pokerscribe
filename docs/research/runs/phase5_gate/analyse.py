"""The Phase 5 gate's tables and verdict, from a gate directory (README.md here has the rules).

    python docs/research/runs/phase5_gate/analyse.py ~/bp/gate [--references DIR] [--md OUT]

Reads each run's stages.jsonl, lbr.jsonl, progress.jsonl, final.jsonl and done.json, and the
deals files, so that every difference between two runs is paired deal by deal (the same
deals for every run: final LBR seed 778, 100,000 hands). `--references DIR` adds the
reference strategies measured with `blueprint reference --deals DIR` on the same deals.
"""
import argparse
import glob
import json
import math
import os
import struct
import sys

SETTINGS = ["b56_14", "b56_34", "fcpa14", "fcpa34", "fc34"]
NAMES = {"b56_14": "56 bets, 1-4", "b56_34": "56 bets, 3-4", "fcpa14": "fcpa, 1-4",
         "fcpa34": "fcpa, 3-4", "fc34": "fc, 3-4"}


def deals(path):
    with open(path, "rb") as f:
        b = f.read()
    assert b[:8] == b"PSDEALS\n", path
    seed, bb, n = struct.unpack_from("<QIQ", b, 8)
    won = struct.unpack_from(f"<{2 * n}i", b, 28)
    return {"seed": seed, "bb": bb, "won": [(won[2 * i], won[2 * i + 1]) for i in range(n)]}


def result(d):
    n = len(d["won"])
    x = [(a + b) / 2 for a, b in d["won"]]
    m = sum(x) / n
    var = sum((v - m) ** 2 for v in x) / (n - 1)
    k = 100 / d["bb"]
    return m * k, math.sqrt(var / n) * k


def minus(a, b):
    assert a["seed"] == b["seed"] and len(a["won"]) == len(b["won"]) and a["bb"] == b["bb"]
    x = [((p + q) - (r + s)) / 2 for (p, q), (r, s) in zip(a["won"], b["won"])]
    n = len(x)
    m = sum(x) / n
    var = sum((v - m) ** 2 for v in x) / (n - 1)
    k = 100 / a["bb"]
    return m * k, math.sqrt(var / n) * k


def lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def load_run(rdir):
    run = {"name": os.path.basename(rdir), "dir": rdir}
    run["stages"] = lines(os.path.join(rdir, "stages.jsonl"))
    run["lbr"] = lines(os.path.join(rdir, "lbr.jsonl"))
    run["progress"] = lines(os.path.join(rdir, "progress.jsonl"))
    run["final"] = lines(os.path.join(rdir, "final.jsonl"))
    done = os.path.join(rdir, "done.json")
    run["done"] = json.load(open(done)) if os.path.exists(done) else None
    run["deals"] = {}
    for line in run["final"]:
        reading = line["extra"].get("small_bets", "smallest")
        run["deals"][(reading, line["setting"])] = deals(line["deals_file"])
    return run


def best(run, reading="smallest"):
    """The largest final LBR result: (setting, bb/100, se)."""
    out = None
    for s in SETTINGS:
        d = run["deals"].get((reading, s))
        if d is None:
            continue
        v, se = result(d)
        if out is None or v > out[1]:
            out = (s, v, se)
    return out


def compare(a, b, reading="smallest"):
    """M(a) - M(b): paired when both maxima come from the same setting."""
    sa, va, ea = best(a, reading)
    sb, vb, eb = best(b, reading)
    if sa == sb:
        d, se = minus(a["deals"][(reading, sa)], b["deals"][(reading, sb)])
        return d, se, "paired"
    return va - vb, math.hypot(ea, eb), "unpaired"


def fmt(v, se):
    return f"{v:+.1f} ± {se:.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gate")
    ap.add_argument("--references")
    ap.add_argument("--md")
    a = ap.parse_args()
    plan = json.load(open(os.path.join(a.gate, "plan.json")))
    runs = {}
    for planned in plan["runs"]:
        rdir = os.path.join(a.gate, planned["name"])
        if os.path.isdir(rdir):
            runs[planned["name"]] = load_run(rdir)
    out = []
    say = out.append

    say("## Training and convergence\n")
    say("| Run | Information sets | Stopped at | Why | Train time | Iterations/s (4 threads) | Change, last doubling | LBR 56 bets 1-4 by stage (50k hands) |")
    say("| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |")
    for name, r in runs.items():
        if not r["stages"]:
            continue
        last = r["stages"][-1]
        done = r["done"] or {}
        by_stage = {l["extra"]["stage"]: l for l in r["lbr"] if l["setting"] == "b56_14"}
        curve = ", ".join(f"{s // 10**6}M {by_stage[s]['bb_per_100']:.1f}" for s in sorted(by_stage))
        ips = sum(s["session"]["iterations_per_second"] * (s["session"]["to"] - s["session"]["from"]) for s in r["stages"]) / max(1, sum(s["session"]["to"] - s["session"]["from"] for s in r["stages"]))
        stop = done.get("stage", last["stage"])
        change = next((s["change"] for s in r["stages"] if s["stage"] == stop), None)
        say(f"| {name} | {last['info_sets']:,} | {stop // 10**6}M | {done.get('reason', 'running')} | "
            f"{done.get('train_seconds', last['train_seconds']) / 60:.1f} min | {ips:,.0f} | "
            f"{change if change is None else round(change, 3)} | {curve} |")

    say("\n## Final LBR (100,000 hands, seed 778), bb/100\n")
    say("| Run | " + " | ".join(NAMES[s] for s in SETTINGS) + " | M (max) | Off the tree |")
    say("| --- | " + " | ".join("---:" for _ in SETTINGS) + " | ---: | ---: |")
    for name, r in runs.items():
        if not r["final"]:
            continue
        cells = []
        for s in SETTINGS:
            d = r["deals"].get(("smallest", s))
            cells.append(fmt(*result(d)) if d else "")
        b = best(r)
        off = max((l["extra"].get("off_tree_share", 0) for l in r["final"] if "small_bets" not in l["extra"]), default=0)
        say(f"| {name} | " + " | ".join(cells) + f" | {fmt(b[1], b[2]) if b else ''} | {off:.3%} |")

    if a.references:
        say("\n## References on the same deals, bb/100\n")
        say("| Strategy | " + " | ".join(NAMES[s] for s in SETTINGS) + " |")
        say("| --- | " + " | ".join("---:" for _ in SETTINGS) + " |")
        for who in ["always_call", "random_action", "random_kind_of_action"]:
            cells = []
            for s in SETTINGS:
                p = glob.glob(os.path.join(a.references, f"{who}.{s}.s778.deals"))
                cells.append(fmt(*result(deals(p[0]))) if p else "")
            say(f"| {who.replace('_', ' ')} | " + " | ".join(cells) + " |")

    def have(*names):
        return all(n in runs and runs[n]["final"] for n in names)

    say("\n## The gate\n")
    verdict = []
    say("Sizes: M(standard) - M(small), at each bucket count (negative is better):\n")
    for k in ["k10", "k50", "k200"]:
        if have(f"small-{k}", f"standard-{k}"):
            d, se, how = compare(runs[f"standard-{k}"], runs[f"small-{k}"])
            ok = d < -2 * se
            verdict.append(ok)
            say(f"- {k}: {fmt(d, se)} ({how}, {d / se:+.1f} SE): {'falls' if ok else 'does not fall'}")
    say("\nBuckets: M(k50) - M(k10), and M(k200) - M(k50), for each menu:\n")
    for m in ["small", "standard"]:
        if have(f"{m}-k10", f"{m}-k50", f"{m}-k200"):
            d1, s1, h1 = compare(runs[f"{m}-k50"], runs[f"{m}-k10"])
            d2, s2, h2 = compare(runs[f"{m}-k200"], runs[f"{m}-k50"])
            falls = d1 < -2 * s1
            flattens = (-d2) < (-d1) and d2 <= 2 * s2
            verdict += [falls, flattens]
            say(f"- {m}: 10 to 50 {fmt(d1, s1)} ({h1}, {d1 / s1:+.1f} SE), 50 to 200 {fmt(d2, s2)} ({h2}, {d2 / s2:+.1f} SE): "
                f"{'falls' if falls else 'does not fall'}, {'then flattens' if flattens else 'does not flatten'}")
    if len(verdict) == 7:
        say(f"\n**Gate: {'passes' if all(verdict) else 'fails'}** ({sum(verdict)} of 7 conditions hold).")
    else:
        say(f"\nGate: {len(verdict)} of 7 conditions measured so far.")

    say("\n## OCHS against equity on the river (50 buckets)\n")
    for m in ["small", "standard"]:
        if have(f"{m}-k50", f"{m}-k50eq"):
            d, se, how = compare(runs[f"{m}-k50eq"], runs[f"{m}-k50"])
            say(f"- {m}: M(equity) - M(OCHS) = {fmt(d, se)} ({how}, {d / se:+.1f} SE)")
            for s in SETTINGS:
                x, e = minus(runs[f"{m}-k50eq"]["deals"][("smallest", s)], runs[f"{m}-k50"]["deals"][("smallest", s)])
                say(f"  - {NAMES[s]}: {fmt(x, e)} ({x / e:+.1f} SE)")

    say("\n## Small bets read as a check or call, against the default (check-or-call minus smallest)\n")
    say("| Run | " + " | ".join(NAMES[s] for s in SETTINGS) + " | M, check or call |")
    say("| --- | " + " | ".join("---:" for _ in SETTINGS) + " | ---: |")
    for name, r in runs.items():
        if ("check-or-call", "b56_14") not in r["deals"]:
            continue
        cells = []
        for s in SETTINGS:
            x, e = minus(r["deals"][("check-or-call", s)], r["deals"][("smallest", s)])
            cells.append(f"{fmt(x, e)}")
        b = best(r, "check-or-call")
        say(f"| {name} | " + " | ".join(cells) + f" | {fmt(b[1], b[2])} ({NAMES[b[0]]}) |")

    text = "\n".join(out)
    print(text)
    if a.md:
        with open(a.md, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
