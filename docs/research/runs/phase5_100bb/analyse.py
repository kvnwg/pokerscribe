"""The 100bb bucket check's tables and verdict (README.md here has the plan and the rules).

    python docs/research/runs/phase5_100bb/analyse.py ~/bp/100bb [--md OUT]

From the copy in the repository (the logs, and the final deals in one archive):

    cd docs/research/runs/phase5_100bb/run && tar -xJf deals.tar.xz && cd -
    python docs/research/runs/phase5_100bb/analyse.py docs/research/runs/phase5_100bb/run

Uses the gate's reader (`../phase5_gate/analyse.py`) for the deals files; every difference is
paired deal by deal on the final deals (seed 778, 100,000 hands).
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "phase5_gate"))
from analyse import deals, fmt, lines, minus, result  # noqa: E402

SETTINGS = ["b56_14", "b56_34", "fcpa14", "fcpa34", "fc34", "fc14"]
GATE_FIVE = SETTINGS[:5]
NAMES = {"b56_14": "56 bets, 1-4", "b56_34": "56 bets, 3-4", "fcpa14": "fcpa, 1-4",
         "fcpa34": "fcpa, 3-4", "fc34": "fc, 3-4", "fc14": "fc, 1-4"}
RUNS = ["standard-k10", "standard-k50", "standard-k200"]


def load(rdir):
    run = {"name": os.path.basename(rdir)}
    run["stages"] = lines(os.path.join(rdir, "stages.jsonl"))
    run["lbr"] = lines(os.path.join(rdir, "lbr.jsonl"))
    run["final"] = lines(os.path.join(rdir, "final.jsonl"))
    done = os.path.join(rdir, "done.json")
    run["done"] = json.load(open(done)) if os.path.exists(done) else None
    run["deals"] = {}
    run["final"] = [l for l in run["final"] if l["extra"].get("small_bets", "smallest") == "smallest"]
    for line in run["final"]:
        path = line["deals_file"]
        if not os.path.exists(path):
            path = os.path.join(rdir, "deals", os.path.basename(path))
        run["deals"][line["setting"]] = deals(path)
    run["off_tree"] = {l["setting"]: l["extra"].get("off_tree_share") for l in run["final"]}
    return run


def best(run, settings):
    out = None
    for s in settings:
        d = run["deals"].get(s)
        if d is None:
            continue
        v, se = result(d)
        if out is None or v > out[1]:
            out = (s, v, se)
    return out


def compare(a, b, settings):
    """M(a) - M(b): paired when both maxima come from the same setting."""
    sa, va, ea = best(a, settings)
    sb, vb, eb = best(b, settings)
    if sa == sb:
        d, se = minus(a["deals"][sa], b["deals"][sb])
        return d, se, "paired"
    return va - vb, math.hypot(ea, eb), "unpaired"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--md")
    a = ap.parse_args()
    runs = {r: load(os.path.join(a.dir, r)) for r in RUNS if os.path.isdir(os.path.join(a.dir, r))}
    out = []
    say = out.append

    say("## Training and convergence\n")
    say("| Run | Information sets | Stopped at | Why | Change, last doubling | Train time | Iterations/s (4 threads) | LBR 56 bets 1-4 by stage (50k hands, seed 777) | fcpa 3-4 by stage |")
    say("| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |")
    for name, r in runs.items():
        if not r["stages"]:
            continue
        last = r["stages"][-1]
        done = r["done"] or {}
        curve = {}
        for setting in ["b56_14", "fcpa34"]:
            by = {l["extra"]["stage"]: l for l in r["lbr"] if l["setting"] == setting}
            curve[setting] = ", ".join(f"{s // 10**6}M {by[s]['bb_per_100']:.1f}" for s in sorted(by))
        spans = [(s["session"]["iterations_per_second"], s["session"]["to"] - s["session"]["from"]) for s in r["stages"]]
        ips = sum(v * n for v, n in spans) / max(1, sum(n for _, n in spans))
        stop = done.get("stage", last["stage"])
        change = next((s["change"] for s in r["stages"] if s["stage"] == stop), None)
        say(f"| {name} | {last['info_sets']:,} | {stop // 10**6}M | {done.get('reason', 'running')} | "
            f"{'' if change is None else round(change, 3)} | "
            f"{done.get('train_seconds', last['train_seconds']) / 3600:.2f} h | {ips:,.0f} | "
            f"{curve['b56_14']} | {curve['fcpa34']} |")

    say("\n## Final LBR (100,000 hands, seed 778, the same deals for every run), bb/100\n")
    say("| Run | " + " | ".join(NAMES[s] for s in SETTINGS) + " | M (of six) | M (the gate's five) |")
    say("| --- | " + " | ".join("---:" for _ in SETTINGS) + " | ---: | ---: |")
    for name, r in runs.items():
        if not r["final"]:
            continue
        cells = [fmt(*result(r["deals"][s])) if s in r["deals"] else "" for s in SETTINGS]
        b6, b5 = best(r, SETTINGS), best(r, GATE_FIVE)
        say(f"| {name} | " + " | ".join(cells) + f" | {fmt(b6[1], b6[2])} ({NAMES[b6[0]]}) | {fmt(b5[1], b5[2])} |")
    say("\nShare of the blueprint's decisions off the tree (it checks or calls there):\n")
    say("| Run | " + " | ".join(NAMES[s] for s in SETTINGS) + " |")
    say("| --- | " + " | ".join("---:" for _ in SETTINGS) + " |")
    for name, r in runs.items():
        if r["final"]:
            say(f"| {name} | " + " | ".join(
                "" if r["off_tree"].get(s) is None else f"{r['off_tree'][s]:.2%}" for s in SETTINGS) + " |")

    def have(*names):
        return all(n in runs and runs[n]["final"] for n in names)

    say("\n## Paired differences by setting (bb/100, the second run minus the first)\n")
    say("| From | To | " + " | ".join(NAMES[s] for s in SETTINGS) + " |")
    say("| --- | --- | " + " | ".join("---:" for _ in SETTINGS) + " |")
    for x, y in [("standard-k10", "standard-k50"), ("standard-k50", "standard-k200"), ("standard-k10", "standard-k200")]:
        if not have(x, y):
            continue
        cells = []
        for s in SETTINGS:
            if s not in runs[x]["deals"] or s not in runs[y]["deals"]:
                cells.append("")
                continue
            d, e = minus(runs[y]["deals"][s], runs[x]["deals"][s])
            cells.append(f"{fmt(d, e)} ({d / e:+.1f} SE)")
        say(f"| {x} | {y} | " + " | ".join(cells) + " |")

    if have(*RUNS):
        say("\n## The verdict (the gate's buckets rule)\n")
        for label, settings in [("M of six", SETTINGS), ("M of the gate's five", GATE_FIVE)]:
            d1, s1, h1 = compare(runs["standard-k50"], runs["standard-k10"], settings)
            d2, s2, h2 = compare(runs["standard-k200"], runs["standard-k50"], settings)
            falls = d1 < -2 * s1
            flattens = (-d2) < (-d1) and d2 <= 2 * s2
            again = d2 < -2 * s2
            say(f"- {label}: 10 to 50 {fmt(d1, s1)} ({h1}, {d1 / s1:+.1f} SE), 50 to 200 {fmt(d2, s2)} "
                f"({h2}, {d2 / s2:+.1f} SE): buckets {'help' if falls else 'do not help'} from 10 to 50; "
                f"{'then flattens' if falls and flattens else 'falls again from 50 to 200' if again else 'does not flatten' if falls else 'nothing fell, so nothing to flatten'}.")
        k200 = runs["standard-k200"]["done"] or {}
        if k200.get("reason") != "converged":
            say(f"\nstandard-k200 stopped without converging ({k200.get('reason')}): its comparison with "
                f"standard-k50 is at unequal convergence (README, \"What each outcome would mean\").")

    text = "\n".join(out)
    print(text)
    if a.md:
        with open(a.md, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
