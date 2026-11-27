"""The small-scale check of the Phase 6 training settings (README.md, "The training settings").

    python docs/research/runs/phase6/pruning_check.py --tables ~/abstraction/k200 --work DIR

Two runs of the Phase 6 game (200bb, rich menu, 200 buckets) on this machine, through the cloud
trainer exactly as on the rented machine (`blueprint --config ... --checkpoint-dir ...`, with
strategy files and stages.jsonl at 1M, 2M, 4M and 8M iterations), with trainer.json's linear
weighting and pruning scaled to the check's length: the check is CHECK iterations where the
settings were chosen for a nominal run of NOMINAL, so every iteration count is multiplied by
CHECK / NOMINAL, and so is the pruning threshold (regrets grow in proportion to the
iterations). The two runs differ only in pruning: on in one, off in the other.

What it measures (``check.md`` in --work, and the JSON lines it prints):
- speed: iterations a second, states a second, states per iteration, each stage;
- what pruning skipped (the trainer's counters) and how far the regrets fell, by street;
- LBR (fcpa14 and b56_14, the same deals) against both 8M strategies, and the paired
  difference;
- the two 8M strategies head to head (duplicate, all-in equity, 200bb).

Pre-registered: seed 1 for training (as trainer.json), LBR seed 6001, 20,000 hands; head to
head seed 6101, 20,000 deals. Pruning "trains" if the pruned run is not worse by 2.5 SE on
either measure and pruning skipped something.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "tools"))
import blueprint_eval as be  # noqa: E402

BLUEPRINT = os.path.join(REPO, "engine", "target", "release", "blueprint")
NOMINAL = 2_000_000_000
CHECK = 8_000_000


def scaled(spec: dict, factor: float, pruning: bool) -> dict:
    t = dict(spec["training"])
    interval, until = t["linear"]
    t["linear"] = [max(1, round(interval * factor)), max(1, round(until * factor))]
    if pruning:
        p = t["pruning"]
        t["pruning"] = {"warmup": max(1, round(p["warmup"] * factor)),
                        "threshold": p["threshold"] * factor, "probability": p["probability"]}
    else:
        t["pruning"] = None
    return dict(spec, training=t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--lbr-hands", type=int, default=20000)
    ap.add_argument("--h2h-deals", type=int, default=20000)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    with open(os.path.join(HERE, "trainer.json")) as f:
        base = json.load(f)
    spec = dict(base["spec"], abstraction=os.path.abspath(os.path.expanduser(a.tables)))
    spec["training"] = dict(spec["training"], threads=a.threads)
    factor = CHECK / NOMINAL
    arms = {}
    for name, pruning in (("pruning", True), ("no-pruning", False)):
        cfg = {"spec": scaled(spec, factor, pruning), "until": CHECK, "every_minutes": 30,
               "strategies": {"first": 1_000_000, "factor": 2}}
        d = os.path.join(a.work, name)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(a.work, f"{name}.json")
        with open(path, "w") as f:
            json.dump(cfg, f, indent=1)
        print(json.dumps({"arm": name, "training": cfg["spec"]["training"]}), flush=True)
        if not os.path.exists(os.path.join(d, "strategy.bps")):
            t = time.time()
            resume = ["--resume"] if os.path.exists(os.path.join(d, "checkpoint.ckpt")) else []
            with open(os.path.join(a.work, f"{name}.log"), "a") as log:
                rc = subprocess.call([BLUEPRINT, "--config", path, "--checkpoint-dir", d] + resume,
                                     stdout=log, stderr=subprocess.STDOUT)
            if rc != 0:
                sys.exit(f"{name}: the trainer exited with {rc}")
            print(json.dumps({"arm": name, "seconds": round(time.time() - t, 1)}), flush=True)
        arms[name] = {"dir": d, "stages": be.read_jsonl(os.path.join(d, "stages.jsonl")),
                      "log": [x for x in be.read_jsonl(os.path.join(a.work, f"{name}.log"))
                              if "iterations_per_second" in x]}
        # The checkpoint is not needed any more: 5 GB.
        ck = os.path.join(d, "checkpoint.ckpt")
        if os.path.exists(ck):
            os.remove(ck)

    runner = be.Runner(BLUEPRINT, os.path.abspath(os.path.expanduser(a.tables)), say=print)
    deals = os.path.join(a.work, "deals")
    results = {}
    settings = ["fcpa14", "b56_14"]
    lbr_out = os.path.join(a.work, "lbr.json")
    if not os.path.exists(lbr_out):
        rs = runner.lbr([os.path.join(arms[n]["dir"], "strategy.bps") for n in arms], list(arms),
                        settings, a.lbr_hands, be.LBR_SEED, deals)
        with open(lbr_out, "w") as f:
            json.dump(rs, f)
    with open(lbr_out) as f:
        for r in json.load(f):
            results[(r["setting_short"], r["strategy"])] = r
    for s in settings:
        for name in arms:
            print(json.dumps({"lbr": s, "arm": name, "bb_per_100": results[(s, name)]["bb_per_100"],
                              "se": results[(s, name)]["std_err"]}), flush=True)
    for s in settings:
        c = runner.compare(results[(s, "pruning")]["deals_file"],
                           results[(s, "no-pruning")]["deals_file"])
        results[(s, "difference")] = c
        print(json.dumps({"lbr": s, "pruning_minus_no_pruning": c["difference"],
                          "se": c["std_err"], "z": c["z"]}), flush=True)
    h2h_out = os.path.join(a.work, "h2h.json")
    if not os.path.exists(h2h_out):
        r = runner.h2h(os.path.join(arms["no-pruning"]["dir"], "strategy.bps"),
                       os.path.join(arms["pruning"]["dir"], "strategy.bps"), a.h2h_deals,
                       be.H2H_SEED, be.STACK_BB)
        with open(h2h_out, "w") as f:
            json.dump(r, f)
    with open(h2h_out) as f:
        h2h = json.load(f)
    print(json.dumps({"h2h": "pruning against no-pruning", **h2h}), flush=True)
    write_md(a.work, arms, results, h2h, factor)


def write_md(work, arms, results, h2h, factor):
    lines = ["# Pruning check", "",
             f"Settings scaled by {factor:g} (CHECK {CHECK:,} / NOMINAL {NOMINAL:,}).", "",
             "| Arm | Stage | Iterations/s (session before) | States/s | States per iteration | "
             "Pruned traversals | Pruned actions | Export s | Change |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, arm in arms.items():
        for st in arm["stages"]:
            sess = [x for x in arm["log"] if x["iterations"] <= st["iterations"]]
            last = sess[-1] if sess else {}
            ips, nps = last.get("iterations_per_second"), last.get("nodes_per_second")
            pr = st.get("pruning") or {}
            lines.append(f"| {name} | {st['iterations']:,} | {ips or 0:,.0f} | {(nps or 0) / 1e6:.2f}M | "
                         f"{(nps / ips) if ips else 0:,.0f} | {pr.get('pruned_traversals', 0):,} | "
                         f"{pr.get('pruned_actions', 0):,} | {st.get('export_seconds', 0):.0f} | "
                         f"{'' if st.get('change') is None else f'{st['change']:.4f}'} |")
    lines += ["", "Regrets at 8M, share of slots below each level (big blinds):", "",
              "| Arm | Street | below -1e3 | below -1e4 | below -1e5 | below -1e6 | below the threshold | lowest |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, arm in arms.items():
        st = arm["stages"][-1] if arm["stages"] else {}
        for street, r in ((st.get("regrets") or {}).get("streets") or {}).items():
            lines.append(f"| {name} | {street} | {r['below_1e3']:.4f} | {r['below_1e4']:.5f} | "
                         f"{r['below_1e5']:.6f} | {r['below_1e6']:.6f} | "
                         f"{'' if r['below_threshold'] is None else f'{r['below_threshold']:.6f}'} | "
                         f"{r['lowest']:,.0f} |")
    lines += ["", "| LBR | pruning | no pruning | difference | SE | z |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for s in ("fcpa14", "b56_14"):
        p, n, d = results[(s, "pruning")], results[(s, "no-pruning")], results[(s, "difference")]
        lines.append(f"| {s} | {p['bb_per_100']:+.1f} | {n['bb_per_100']:+.1f} | {d['difference']:+.1f} | "
                     f"{d['std_err']:.1f} | {d['z']:+.2f} |")
    lines += ["", f"Head to head, pruning against no pruning: {h2h['bb_per_100']:+.2f} ± {h2h['se']:.2f} "
                  f"bb/100 over {h2h['hands']:,} hands."]
    # The pre-registered reading (the docstring): not worse by 2.5 SE on either measure, and
    # pruning skipped something.
    worse_lbr = [s for s in ("fcpa14", "b56_14") if results[(s, "difference")]["z"] > 2.5]
    worse_h2h = h2h["bb_per_100"] < -2.5 * h2h["se"]
    skipped = (arms["pruning"]["stages"][-1].get("pruning") or {}).get("pruned_traversals", 0) > 0
    trains = not worse_lbr and not worse_h2h and skipped
    lines += ["", f"Pruning trains: {'yes' if trains else 'no'} (worse on LBR by 2.5 SE: "
                  f"{', '.join(worse_lbr) or 'none'}; worse head to head by 2.5 SE: "
                  f"{'yes' if worse_h2h else 'no'}; pruning skipped something: "
                  f"{'yes' if skipped else 'no'})."]
    with open(os.path.join(work, "check.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
