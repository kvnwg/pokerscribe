"""Pilot for the 100bb head to head: speed and the sd of a deal. Its seeds are not used again."""
import json, math, sys, time
import pokerscribe_engine as pe
F = {"k10": "/root/bp/100bb/standard-k10/strategy-16000000.bps",
     "k50": "/root/bp/100bb/standard-k50/strategy-64000000.bps",
     "k200": "/root/bp/100bb/standard-k200/strategy-128000000.bps"}
for a, b, seed in [("k50", "k200", 9101), ("k10", "k50", 9102)]:
    deals = 20000
    t = time.time()
    r = pe.run_match(["blueprint:" + F[a], "blueprint:" + F[b]], deals, seed, stack=10000,
                     small_blind=50, big_blind=100).to_dict()
    wall = time.time() - t
    x = r["results"][1]
    sd = x["se"] * math.sqrt(deals)
    out = {"pilot": f"{b} against {a}", "seed": seed, "deals": deals, "wall_seconds": wall,
           "bb_per_100": x["bb_per_100"], "se": x["se"], "sd_per_deal": sd,
           "actual_bb_per_100": x["actual_bb_per_100"], "actual_se": x["actual_se"],
           "by_seat": x["by_seat"], "illegal": [y["illegal_actions"] for y in r["results"]],
           "adjusted_hands": r["adjusted_hands"], "hands": r["hands"], "timing": r["timing"],
           "scoring": r["scoring"]}
    print(json.dumps(out), flush=True)
