"""The table of the pre-registered AIVAT checks, from the reports run.py saved, read as the
plan says (docs/research/experiments.md, "Phase 7: AIVAT in the arena"):

    python docs/research/runs/phase7_aivat/summarize.py > docs/research/runs/phase7_aivat/results.md
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
WHAT = {
    "1a": ("64M against a copy of itself", "identical"),
    "1b": ("64M against a copy of itself", "identical"),
    "1c": ("tag against tag", "identical"),
    "2a": ("64M against 16M", "agreement"),
    "2b": ("64M against 4M", "agreement"),
    "3": ("64M against tag", "agreement"),
    "4": ("Search on 64M against 64M", "search"),
}


def row(rid):
    path = os.path.join(HERE, f"{rid}.json")
    if not os.path.exists(path):
        return None
    d = json.load(open(path))
    r = next(x for x in d["results"] if x["index"] == 1)  # the second agent: the one named first in WHAT
    a = r["aivat"]
    z = a["bb_per_100"] / a["se"]
    mz = a["minus_main"] / a["minus_main_se"]
    kind = WHAT[rid][1]
    if kind == "identical":
        verdict = "pass" if abs(z) < 3 and abs(mz) < 3 else "FAIL"
    elif kind == "agreement":
        verdict = "pass" if abs(mz) < 2.5 else "FAIL"
    else:
        verdict = "reported"
    return (f"| {rid} | {WHAT[rid][0]} | {d['deals']:,} | {d['config']['seed']} | "
            f"{r['bb_per_100']:+.2f} ± {r['se']:.2f} | {a['bb_per_100']:+.2f} ± {a['se']:.2f} | "
            f"{z:+.2f} | {a['minus_main']:+.2f} ± {a['minus_main_se']:.2f} | {mz:+.2f} | "
            f"{a['se_ratio']:.3f} | {a['se'] / r['plain_se']:.3f} | "
            f"{a['corrected_decisions']:,} of {a['corrected_decisions'] + a['unknown_decisions'] + a['unexplained_decisions']:,} | "
            f"{d['timing']['hands_per_second']:,.0f} | {verdict} |")


def main():
    print("| # | Match (the first named wins) | Deals | Seed | Main bb/100 | AIVAT bb/100 | AIVAT z | "
          "AIVAT minus main | Its z | SE ratio, AIVAT over main | Over plain | "
          "Its decisions corrected | Hands/s | Read as planned |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for rid in WHAT:
        line = row(rid)
        if line:
            print(line)


if __name__ == "__main__":
    main()
