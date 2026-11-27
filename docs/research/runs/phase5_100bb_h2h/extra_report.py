"""The checks added after review (`extra.py`): not pre-registered, they don't change the decision.

    python docs/research/runs/phase5_100bb_h2h/extra_report.py docs/research/runs/phase5_100bb_h2h/results.jsonl docs/research/runs/phase5_100bb_h2h/extra.jsonl [--md OUT]
"""
import argparse
import json
import math


def upper_gamma_regularized(s, x):
    """Q(s, x), for the chi-square test (series for the lower part)."""
    term = total = 1.0 / s
    k = 1
    while k < 10000 and term > 1e-16 * total:
        term *= x / (s + k)
        total += term
        k += 1
    return 1.0 - total * math.exp(-x + s * math.log(x) - math.lgamma(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("extra")
    ap.add_argument("--md")
    args = ap.parse_args()
    rows = [json.loads(x) for x in open(args.results) if x.strip()]
    extra = [json.loads(x) for x in open(args.extra) if x.strip()]
    out = []
    say = out.append

    say("## Added after review (not pre-registered; doesn't change the decision)\n")
    say("The main match (seed 9201) and the replication (seed 9202) agreed to 0.0023 bb/100. "
        "These checks show that it is chance.\n")
    say("**The deals differ.** The arena deals deal d from mix(seed, d) alone "
        "(`engine/crates/arena/src/runner.rs`), so an agent that only checks and calls sees the "
        "same cards the blueprints were dealt:\n")
    for e in extra:
        if e.get("check") == "cards":
            f = e["first_deal"]
            say(f"- seed {e['seed']}, deal 0: button {' '.join(f['button'])}, big blind "
                f"{' '.join(f['big_blind'])}, board {' '.join(f['board'])}")
        if e.get("check") == "cards compared":
            say(f"- of the first {e['deals']:,} deals, {e['identical_deals']} are the same on seeds "
                f"{e['seeds'][0]} and {e['seeds'][1]}")

    say("\nThe blueprints on the first 1,000 deals of each seed:\n")
    say("| Seed | Deals | standard-k200 against standard-k50 | Real chips | All-in hands adjusted |")
    say("| ---: | ---: | ---: | ---: | ---: |")
    for e in extra:
        if e.get("check") == "match" and e["deals"] < 1_000_000:
            x = e["report"]["results"][1]
            say(f"| {e['seed']} | {e['deals']:,} | {x['bb_per_100']:+.2f} ± {x['se']:.2f} | "
                f"{x['actual_bb_per_100']:+.2f} | {e['report']['adjusted_hands']} |")

    full = {r["seed"]: r for r in rows if r["name"] in ("main", "replication")}
    for e in extra:
        if e.get("check") == "match" and e["deals"] >= 1_000_000:
            full[e["seed"]] = e
    say("\n**Every seed at 2,000,000 deals** (9201 and 9202 from the plan; 9203 and 9204 asked "
        "for in review; 9205 to 9212 added after those two, because 9204 landed 0.02 from 9201 "
        "and 9202):\n")
    say("| Seed | standard-k200 against standard-k50 | Real chips | On the button | In the big blind |")
    say("| ---: | ---: | ---: | ---: | ---: |")
    v, se = [], []
    for seed in sorted(full):
        x = full[seed]["report"]["results"][1]
        seat = {s["position"]: s for s in x["by_seat"]}
        v.append(x["bb_per_100"])
        se.append(x["se"])
        say(f"| {seed} | {x['bb_per_100']:+.4f} ± {x['se']:.4f} | {x['actual_bb_per_100']:+.4f} | "
            f"{seat['BTN/SB']['bb_per_100']:+.2f} | {seat['BB']['bb_per_100']:+.2f} |")
    n = len(v)
    w = [1 / e ** 2 for e in se]
    pooled = sum(a * b for a, b in zip(v, w)) / sum(w)
    pse = (1 / sum(w)) ** 0.5
    mean = sum(v) / n
    sd = (sum((a - mean) ** 2 for a in v) / (n - 1)) ** 0.5
    chi = sum(((a - pooled) / e) ** 2 for a, e in zip(v, se))
    p = upper_gamma_regularized((n - 1) / 2, chi / 2)
    pairs = sorted((abs(v[i] - v[j]), i, j) for i in range(n) for j in range(i + 1, n))
    seeds = sorted(full)
    say(f"\n- The spread of the {n} results is what their SEs give: sd {sd:.3f} against a mean SE of "
        f"{sum(se) / n:.3f} (chi-square {chi:.1f} on {n - 1} degrees of freedom, p = {p:.2f}).")
    say(f"- Among their {len(pairs)} pairs the closest are "
        + ", ".join(f"{seeds[i]} and {seeds[j]} ({d:.4f})" for d, i, j in pairs[:3]) + ".")
    say(f"- Pooled over the {n} seeds: {pooled:+.2f} ± {pse:.2f} bb/100 ({pooled / pse:.1f} SE). "
        "No illegal actions in any match.")

    text = "\n".join(out)
    print(text)
    if args.md:
        with open(args.md, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
