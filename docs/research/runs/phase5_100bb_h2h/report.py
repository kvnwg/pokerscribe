"""The head-to-head results and the plan's decision (plan.md here has the rules).

    python docs/research/runs/phase5_100bb_h2h/report.py docs/research/runs/phase5_100bb_h2h/plan.json RESULTS.jsonl [--md OUT]

Written before the main run, with the plan.
"""
import argparse
import json


def category(bb, se, z_bar):
    z = bb / se
    if z >= z_bar:
        return "b ahead"
    if z <= -z_bar:
        return "a ahead"
    return "inconclusive"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("results")
    ap.add_argument("--md")
    args = ap.parse_args()
    plan = json.load(open(args.plan))
    rows = {}
    for line in open(args.results):
        if line.strip():
            d = json.loads(line)
            rows[d["name"]] = d
    z_bar = plan["decision"]["z"]
    small = plan["decision"]["small_edge_bb_per_100"]
    out = []
    say = out.append

    say("## Matches (100 big blinds, duplicate deals with the seats swapped, all-in equity), bb/100\n")
    say("Each result is the second run's against the first: positive means the second wins.\n")
    say("| Match | Role | Seed | Deals | Second against first | In SE | Real chips | "
        "Second on the button | Second in the big blind | All-in hands adjusted | Illegal actions | Wall time |")
    say("| --- | --- | ---: | ---: | --- | ---: | --- | --- | --- | ---: | ---: | ---: |")
    for m in plan["matches"]:
        d = rows.get(m["name"])
        if d is None:
            continue
        r = d["report"]
        b = r["results"][1]
        seat = {s["position"]: s for s in b["by_seat"]}
        btn, bbs = seat["BTN/SB"], seat["BB"]
        say(f"| {m['name']}: {m['b']} against {m['a']} | {m['role']} | {m['seed']} | {m['deals']:,} | "
            f"{b['bb_per_100']:+.2f} ± {b['se']:.2f} | {b['bb_per_100'] / b['se']:+.1f} | "
            f"{b['actual_bb_per_100']:+.2f} ± {b['actual_se']:.2f} | "
            f"{btn['bb_per_100']:+.2f} ± {btn['se']:.2f} | {bbs['bb_per_100']:+.2f} ± {bbs['se']:.2f} | "
            f"{r['adjusted_hands']:,} of {r['hands']:,} | "
            f"{', '.join(str(x['illegal_actions']) for x in r['results'])} | {d['wall_seconds']:.0f} s |")

    main_run = rows.get("main")
    if main_run is not None:
        b = main_run["report"]["results"][1]
        c = category(b["bb_per_100"], b["se"], z_bar)
        say("\n## The decision (the main match)\n")
        verdict = {"b ahead": "standard-k200 is ahead by 2.5 SE or more: the extra buckets pay off in play.",
                   "a ahead": "standard-k50 is ahead by 2.5 SE or more: flag it to the manager before "
                              "Phase 6's full run.",
                   "inconclusive": "Neither is ahead by 2.5 SE: inconclusive."}[c]
        say(f"- standard-k200 against standard-k50: {b['bb_per_100']:+.2f} ± {b['se']:.2f} bb/100 "
            f"({b['bb_per_100'] / b['se']:+.1f} SE). {verdict}")
        if c != "inconclusive" and abs(b["bb_per_100"]) < small:
            say(f"- The edge is under {small:g} bb/100: it passes the rule, and it is small.")
        rep = rows.get("replication")
        if rep is not None:
            rb = rep["report"]["results"][1]
            rc = category(rb["bb_per_100"], rb["se"], z_bar)
            gap = rb["bb_per_100"] - b["bb_per_100"]
            gse = (rb["se"] ** 2 + b["se"] ** 2) ** 0.5
            say(f"- The replication (seed {rep['seed']}): {rb['bb_per_100']:+.2f} ± {rb['se']:.2f} "
                f"({rb['bb_per_100'] / rb['se']:+.1f} SE), {rc.replace('b ahead', 'standard-k200 ahead').replace('a ahead', 'standard-k50 ahead')}; "
                f"{'the same call as the main match' if rc == c else 'not the same call as the main match'} "
                f"(gap {gap:+.2f} ± {gse:.2f}).")
    san = rows.get("sanity")
    if san is not None:
        b = san["report"]["results"][1]
        c = category(b["bb_per_100"], b["se"], z_bar)
        say("\n## The sanity check (optional)\n")
        say(f"- standard-k50 against standard-k10: {b['bb_per_100']:+.2f} ± {b['se']:.2f} "
            f"({b['bb_per_100'] / b['se']:+.1f} SE): "
            + {"b ahead": "the arena sees the 10 to 50 gain LBR saw.",
               "a ahead": "the arena sees the opposite of the 10 to 50 gain LBR saw.",
               "inconclusive": "the arena doesn't see the 10 to 50 gain by 2.5 SE."}[c])

    text = "\n".join(out)
    print(text)
    if args.md:
        with open(args.md, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
