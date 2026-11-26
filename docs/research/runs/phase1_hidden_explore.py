"""Phase 1: training and checking data for the hidden-cards estimate (tools/hidden.py).

    python docs/research/runs/phase1_hidden_explore.py '{"ev_sizing": true}' 1500 --table mixed --seed 303 --save out.json

Plays the paired comparison as tools/compare.py does (duplicate deals, 6 replays from where
the variants part) and saves, for every hand, the raw difference, the resampled luck-adjusted
difference, and for hands that part heads-up after the flop the hidden-cards estimate split
into its base (checked-down values) and one part per weight group (tools/hidden.estimate_parts),
averaged over the six plays. The weights are then fitted by least squares on such files from
training seeds (`python tools/hidden.py fit <files>`) and frozen; any fixed weights keep the
estimate unbiased (app/tests/test_hidden.py checks it exactly).
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
import compare  # noqa: E402
import hidden  # noqa: E402
import luck  # noqa: E402
import simulate as sim  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("other")
    ap.add_argument("hands", type=int, nargs="?", default=1500)
    ap.add_argument("--table", default="mixed")
    ap.add_argument("--stacks", default="even")
    ap.add_argument("--seed", type=int, default=303)
    ap.add_argument("--resample", type=int, default=6)
    ap.add_argument("--save", required=True)
    a = ap.parse_args()
    other = json.loads(a.other)
    rows, cpu, t_all = [], 0.0, time.process_time()
    for k in range(a.hands):
        d, r = divmod(k, 6)
        styles, names = sim.seating(a.table, a.seed, d)
        seed = a.seed * 100003 + d
        st = compare.new_stats({}, other)
        sim.play_hand(styles, d % 6, seed, 0, 100.0, st, a.stacks, names, None, k + 1, rotate=r, keyed=True)
        row = {"deck": d, "raw": 0.0, "resampled": 0.0, "base": 0.0, "parts": {}, "eligible": False}
        rows.append(row)
        if not st["diverged"]:
            continue
        rec_a = st["last"]
        j = rec_a["diverge_at"]
        pairs = []
        for salt in range(a.resample):
            recs = []
            for v in ({}, other):
                s2 = compare.new_stats(v)
                sim.play_hand(styles, d % 6, seed, 0, 100.0, s2, a.stacks, names, None, k + 1, rotate=r, keyed=True,
                              split_at=j if salt else None, resample=salt or None)
                recs.append(s2["last"])
            pairs.append(recs)
        row["raw"] = pairs[0][1]["net"] - pairs[0][0]["net"]
        row["resampled"] = sum(luck.adjusted(pb) - luck.adjusted(pa) for pa, pb in pairs) / len(pairs)
        row["base"] = row["resampled"]
        b = hidden.opponent(rec_a, j)
        if b is None:
            continue
        t0 = time.process_time()
        sp = hidden.Split(rec_a, j, b)
        base, parts = 0.0, {}
        for pa, pb in pairs:
            ba, qa = hidden.estimate_parts(pa, sp)
            bb, qb = hidden.estimate_parts(pb, sp)
            base += (bb - ba) / len(pairs)
            for g in set(qa) | set(qb):
                key = json.dumps(list(g))
                parts[key] = parts.get(key, 0.0) + (qb.get(g, 0.0) - qa.get(g, 0.0)) / len(pairs)
        cpu += time.process_time() - t0
        row.update(base=base, parts=parts, eligible=True)
    out = {"args": vars(a), "rows": rows, "hidden_cpu": cpu, "cpu": time.process_time() - t_all}
    with open(a.save, "w") as f:
        json.dump(out, f)
    decks = [r["deck"] for r in rows]
    print(f"{a.other} on {a.table} ({a.stacks}), seed {a.seed}: {a.hands} hands, "
          f"{sum(r['eligible'] for r in rows)} part heads-up after the flop; hidden {cpu:.0f} of {out['cpu']:.0f} CPU s")
    for name in ("raw", "resampled", "base"):
        m, se = compare.summary([r[name] for r in rows], decks)
        print(f"  {name:10s} {m:+7.2f} ± {se:5.2f} bb/100")


if __name__ == "__main__":
    main()
