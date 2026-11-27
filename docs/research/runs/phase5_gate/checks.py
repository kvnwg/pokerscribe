"""The checks after the gate (experiments.md, Phase 5: the gate). Not pre-registered.

    python docs/research/runs/phase5_gate/checks.py ~/bp/gate ~/bp/after [--md OUT]

1. Fresh deals: every run's final strategy with `b56_14` on a third deal set (seed 779,
   100,000 hands, `after/seed779/`), and the gate's comparisons on it next to the same
   comparisons on the final deals (seed 778). M was `b56_14` for every run on seed 778.
2. The same measurement twice: standard-k10 and small-k10 were measured on seed 779 twice, by
   different processes (`after/check-deals/` and `after/seed779/`); the two must agree deal by
   deal.
3. Longer training: small-k10 trained on to 64M iterations (8 times its stop) and small-k200 to
   256M (4 times its stop), measured on the final deals (`after/longer/deals/`).

From the copy in the repository, unpack `gate/deals.tar.xz` in `gate/` and `after/deals.tar.xz`
in `after/` first.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import deals, fmt, minus, result  # noqa: E402

RUNS = ["small-k10", "small-k50", "small-k50eq", "small-k200",
        "standard-k10", "standard-k50", "standard-k50eq", "standard-k200"]


def stage(gate, run):
    return json.load(open(os.path.join(gate, run, "done.json")))["stage"]


def final(gate, run, setting="b56_14"):
    st = stage(gate, run)
    p = glob.glob(os.path.join(gate, run, "deals", f"{run}-final-{st}.{setting}.s778.h100000.deals"))
    return deals(p[0]) if p else None


def one(pattern):
    p = sorted(glob.glob(pattern))
    return deals(p[0]) if p else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gate")
    ap.add_argument("after")
    ap.add_argument("--md")
    a = ap.parse_args()
    out = []
    say = out.append

    s778 = {r: final(a.gate, r) for r in RUNS}
    s779 = {r: one(os.path.join(a.after, "seed779", f"{r}.b56_14.s779.deals")) for r in RUNS}

    say("## 1. Fresh deals: `b56_14`, seed 779 against seed 778 (100,000 hands each), bb/100\n")
    say("| Run | Seed 778 | Seed 779 | 779 - 778 (unpaired) |")
    say("| --- | ---: | ---: | ---: |")
    for r in RUNS:
        if s778[r] is None or s779[r] is None:
            continue
        v8, e8 = result(s778[r])
        v9, e9 = result(s779[r])
        se = (e8 ** 2 + e9 ** 2) ** 0.5
        say(f"| {r} | {fmt(v8, e8)} | {fmt(v9, e9)} | {fmt(v9 - v8, se)} ({(v9 - v8) / se:+.1f} SE) |")

    comps = [("Sizes, 10 buckets", "small-k10", "standard-k10"),
             ("Sizes, 50 buckets", "small-k50", "standard-k50"),
             ("Sizes, 200 buckets", "small-k200", "standard-k200"),
             ("Buckets, small, 10 to 50", "small-k10", "small-k50"),
             ("Buckets, small, 50 to 200", "small-k50", "small-k200"),
             ("Buckets, standard, 10 to 50", "standard-k10", "standard-k50"),
             ("Buckets, standard, 50 to 200", "standard-k50", "standard-k200"),
             ("Buckets, small, 10 to 200", "small-k10", "small-k200"),
             ("Buckets, standard, 10 to 200", "standard-k10", "standard-k200"),
             ("Equity - OCHS, small", "small-k50", "small-k50eq"),
             ("Equity - OCHS, standard", "standard-k50", "standard-k50eq")]
    say("\nThe gate's comparisons on `b56_14` (the second run minus the first, paired on each seed's deals):\n")
    say("| Comparison | Seed 778 | Seed 779 | Gap between the seeds |")
    say("| --- | ---: | ---: | ---: |")
    for name, x, y in comps:
        if any(d[r] is None for d in (s778, s779) for r in (x, y)):
            continue
        d8, e8 = minus(s778[y], s778[x])
        d9, e9 = minus(s779[y], s779[x])
        se = (e8 ** 2 + e9 ** 2) ** 0.5
        say(f"| {name} | {fmt(d8, e8)} ({d8 / e8:+.1f} SE) | {fmt(d9, e9)} ({d9 / e9:+.1f} SE) | "
            f"{d9 - d8:+.1f} ({(d9 - d8) / se:+.1f} SE) |")

    say("\n## 2. The same measurement twice (seed 779)\n")
    for r in ["standard-k10", "small-k10"]:
        # Step 5 gave no label, so its files are named after the strategy file's path.
        twice = one(os.path.join(a.after, "check-deals", f"*_{r}_strategy-{stage(a.gate, r)}_bps.b56_14.s779.deals"))
        if twice is None or s779[r] is None:
            continue
        n = len(twice["won"])
        differ = sum(1 for p, q in zip(twice["won"], s779[r]["won"]) if p != q)
        say(f"- {r}: {fmt(*result(twice))} and {fmt(*result(s779[r]))}; "
            f"{'identical deal by deal' if differ == 0 else f'{differ} of {n} deals differ'}")

    say("\n## 3. Longer training (seed 778, the final deals, 100,000 hands), bb/100\n")
    say("| Run | Setting | At its stop | Trained on | Difference (paired) |")
    say("| --- | --- | ---: | ---: | ---: |")
    longer = {}
    for r, until in [("small-k10", 64_000_000), ("small-k200", 256_000_000)]:
        for setting in ["b56_14", "fcpa34"]:
            d = one(os.path.join(a.after, "longer", "deals", f"longer-{r}-{until}.{setting}.s778.deals"))
            f = final(a.gate, r, setting)
            if d is None or f is None:
                continue
            longer[(r, setting)] = d
            x, e = minus(d, f)
            say(f"| {r}, {stage(a.gate, r) // 10**6}M to {until // 10**6}M | {setting} | {fmt(*result(f))} | "
                f"{fmt(*result(d))} | {fmt(x, e)} ({x / e:+.1f} SE) |")
    for setting in ["b56_14", "fcpa34"]:
        if ("small-k10", setting) in longer and ("small-k200", setting) in longer:
            x, e = minus(longer[("small-k200", setting)], longer[("small-k10", setting)])
            f10, f200 = final(a.gate, "small-k10", setting), final(a.gate, "small-k200", setting)
            y, g = minus(f200, f10)
            say(f"\n- {setting}, small-k200 - small-k10: {fmt(y, g)} ({y / g:+.1f} SE) at their stops; "
                f"{fmt(x, e)} ({x / e:+.1f} SE) after training on (k10 at 64M, k200 at 256M).")

    text = "\n".join(out)
    print(text)
    if a.md:
        with open(a.md, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
