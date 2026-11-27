"""The checks after the 100bb plan (`after.sh`). Not pre-registered: written after the k10 and k50
results, while standard-k200 trained.

    python docs/research/runs/phase5_100bb/checks.py ~/bp/100bb ~/bp/100bb-after [--md OUT]

1. A second deal set: every run's final strategy with `b56_14` (M for all three on seed 778) on
   seed 779, 100,000 hands, and the plan's comparisons on it next to the same comparisons on the
   final deals (seed 778), and pooled over both.
2. By seat: the plan's `b56_14` results split into LBR on the button and in the big blind.
3. The references at 100bb on the final deals (seed 778, `b56_14`): always call, random action,
   random kind of action, for scale.

From the copy in the repository, unpack `run/deals.tar.xz` in `run/` and `after/deals.tar.xz`
in `after/` first, then pass `run` and `after`.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "phase5_gate"))
from analyse import deals, fmt, minus, result  # noqa: E402

RUNS = ["standard-k10", "standard-k50", "standard-k200"]
COMPS = [("10 to 50", "standard-k10", "standard-k50"),
         ("50 to 200", "standard-k50", "standard-k200"),
         ("10 to 200", "standard-k10", "standard-k200")]


def one(pattern):
    p = sorted(glob.glob(pattern))
    return deals(p[0]) if p else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("after")
    ap.add_argument("--md")
    a = ap.parse_args()
    out = []
    say = out.append

    stage = {r: json.load(open(os.path.join(a.run, r, "done.json")))["stage"] for r in RUNS}
    s778 = {r: one(os.path.join(a.run, r, "deals", f"{r}-final-{stage[r]}.b56_14.s778.h100000.deals"))
            for r in RUNS}
    s779 = {r: one(os.path.join(a.after, "seed779", f"{r}.b56_14.s779*.deals")) for r in RUNS}

    say("## 1. A second deal set: `b56_14`, seed 779 against seed 778 (100,000 hands each), bb/100\n")
    say("| Run | Seed 778 (the final deals) | Seed 779 | 779 - 778 (unpaired) | Both (200,000 hands) |")
    say("| --- | ---: | ---: | ---: | ---: |")
    for r in RUNS:
        if s778[r] is None or s779[r] is None:
            continue
        v8, e8 = result(s778[r])
        v9, e9 = result(s779[r])
        se = (e8 ** 2 + e9 ** 2) ** 0.5
        say(f"| {r} | {fmt(v8, e8)} | {fmt(v9, e9)} | {fmt(v9 - v8, se)} ({(v9 - v8) / se:+.1f} SE) | "
            f"{fmt((v8 + v9) / 2, se / 2)} |")

    say("\nThe plan's comparisons on `b56_14` (the second run minus the first, paired on each seed's deals):\n")
    say("| Buckets | Seed 778 | Seed 779 | Gap between the seeds | Both (200,000 hands) |")
    say("| --- | ---: | ---: | ---: | ---: |")
    for name, x, y in COMPS:
        if any(d[r] is None for d in (s778, s779) for r in (x, y)):
            continue
        d8, e8 = minus(s778[y], s778[x])
        d9, e9 = minus(s779[y], s779[x])
        se = (e8 ** 2 + e9 ** 2) ** 0.5
        both, eb = (d8 + d9) / 2, se / 2
        say(f"| {name} | {fmt(d8, e8)} ({d8 / e8:+.1f} SE) | {fmt(d9, e9)} ({d9 / e9:+.1f} SE) | "
            f"{d9 - d8:+.1f} ({(d9 - d8) / se:+.1f} SE) | {fmt(both, eb)} ({both / eb:+.1f} SE) |")

    say("\n## 2. By seat: `b56_14`, LBR on the button and in the big blind, bb/100\n")
    say("Each deal is played twice, LBR in each seat; the plan's figure is the mean of the two. "
        "The differences are paired deal by deal (the second run minus the first).\n")
    say("| Seed | LBR | " + " | ".join(RUNS) + " | 10 to 50 | 50 to 200 | 10 to 200 |")
    say("| --- | --- | " + " | ".join("---:" for _ in RUNS) + " | ---: | ---: | ---: |")

    def mean_se(x):
        m = sum(x) / len(x)
        return m, (sum((v - m) ** 2 for v in x) / (len(x) - 1) / len(x)) ** 0.5

    for label, sets in [("778", s778), ("779", s779)]:
        if any(sets[r] is None for r in RUNS):
            continue
        k = 100 / sets[RUNS[0]]["bb"]
        for seat, name in [(0, "on the button"), (1, "in the big blind")]:
            cells = []
            for r in RUNS:
                m, e = mean_se([w[seat] for w in sets[r]["won"]])
                cells.append(fmt(m * k, e * k))
            for _, p, q in COMPS:
                m, e = mean_se([b[seat] - c[seat] for c, b in zip(sets[p]["won"], sets[q]["won"])])
                cells.append(f"{fmt(m * k, e * k)} ({m / e:+.1f} SE)")
            say(f"| {label} | {name} | " + " | ".join(cells) + " |")

    refs = {}
    for name in ["always_call", "random_action", "random_kind_of_action"]:
        d = one(os.path.join(a.after, "references", f"{name}.b56_14.s778*.deals"))
        if d is not None:
            refs[name] = d
    if refs:
        say("\n## 3. References at 100bb (`b56_14`, seed 778, the final deals, 100,000 hands), bb/100\n")
        say("| Agent | LBR wins | A blueprint's share of it (k10, k50, k200) |")
        say("| --- | ---: | --- |")
        for name, d in refs.items():
            v, e = result(d)
            shares = ", ".join(f"{result(s778[r])[0] / v:.0%}" for r in RUNS if s778[r] is not None)
            say(f"| {name.replace('_', ' ')} | {fmt(v, e)} | {shares} |")

    text = "\n".join(out)
    print(text)
    if a.md:
        with open(a.md, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
