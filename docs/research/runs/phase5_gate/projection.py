"""The Phase 6 projection from the gate's runs and the benches (experiments.md, Phase 5: the gate).

    python docs/research/runs/phase5_gate/projection.py ~/bp/gate --rich ~/bp/after/rich \
        --bench ~/bp/after/bench.jsonl [--md OUT]

The Phase 6 game: heads-up, 200 big blinds, the `rich` menu, 200 buckets per postflop street
(`blueprint size --stack 200 --menu rich --buckets 200`). What it needs to reach the gate's level
of convergence is read off the gate's eight runs two ways:

- work per information set: the game states the run visited (cfr's `nodes_touched`) by the time
  its strategy changed by 8% over a doubling (the gate's "play settled" bar), divided by its
  information sets;
- iterations against information sets: a power law fitted to the eight runs, extrapolated.

Both are turned into hours with the speed measured in the Phase 6 game itself on this machine
(`--rich`: the `tools/cloud` trainer's session log, 4 threads then 1), scaled to 64 threads with
the stated ranges. The ranges are guesses where nothing was measured, and say so.
"""
import argparse
import json
import math
import os

# blueprint size --stack 200 --menu rich --buckets 200
PHASE6 = {"info_sets": 97_158_404, "slots": 251_686_705}
BAR = 0.08  # the gate's "play settled" bar: change per doubling
THREADS = 64
# Ranges for what was not measured, as (slow, central, fast) multipliers on the speed measured
# here. They are judgement, not measurement.
ARM_PER_CORE = (0.8, 1.0, 1.5)    # a c4a (Axion) core against one of this machine's 2.1 GHz Xeon cores
SCALING_64 = (0.5, 0.7, 0.9)      # 64 threads' speed over 64 times one thread's (4 gave 0.93 here)
FULL_TABLE = (0.85, 0.95, 1.0)    # speed with the whole table met, against the bench's last session
# States per iteration rose through the bench as the strategy left uniform play (at 20bb they
# rose about 12% more from 4M iterations to the stop): (low, central, high) growth to the end.
STATES_GROWTH = (1.0, 1.2, 1.5)
SPOT_PER_HOUR = 2.0461            # c4a-highmem-64, spot, us-central1, read 26 Nov 2026 (BENCHMARKS.md)


def lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def crossing(stages):
    """Iterations where the change per doubling first reaches BAR, interpolated in log2(iterations)."""
    prev = None
    for s in stages:
        c = s["change"]
        if c is None:
            prev = s
            continue
        if c <= BAR:
            if prev is None or prev["change"] is None:
                return s["stage"], "at or before"
            a, b = prev["change"], c
            f = (a - BAR) / (a - b)
            return prev["stage"] * 2 ** f, "interpolated"
        prev = s
    return None, "not reached"


def nodes_until(stages, iterations):
    """Game states visited by `iterations`, from the stage sessions (linear inside a session)."""
    total = 0.0
    for s in stages:
        x = s["session"]
        a, b = x["from"], x["to"]
        n = x["nodes_per_second"] * x["seconds"]
        if iterations >= b:
            total += n
        elif iterations > a:
            total += n * (iterations - a) / (b - a)
    return total


def fit(xs, ys):
    """Least squares of log y on log x: (slope, intercept, residual sd)."""
    lx = [math.log(x) for x in xs]
    ly = [math.log(y) for y in ys]
    n = len(lx)
    mx, my = sum(lx) / n, sum(ly) / n
    sxx = sum((a - mx) ** 2 for a in lx)
    b = sum((a - mx) * (c - my) for a, c in zip(lx, ly)) / sxx
    a = my - b * mx
    res = [c - (a + b * x) for x, c in zip(lx, ly)]
    sd = math.sqrt(sum(r * r for r in res) / max(1, n - 2))
    return b, a, sd, mx, sxx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gate")
    ap.add_argument("--rich", help="the Phase 6 game's trainer directory (its log.jsonl)")
    ap.add_argument("--bench", help="bench.jsonl with the thread scaling at 20bb")
    ap.add_argument("--md")
    a = ap.parse_args()
    out = []
    say = out.append
    plan = json.load(open(os.path.join(a.gate, "plan.json")))

    say("## Work to the gate's convergence, per run\n")
    say("| Run | Information sets | Stopped at | Change reaches 0.08 | States visited then | Per information set | Iterations per information set | States per iteration |")
    say("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    rows = []
    for planned in plan["runs"]:
        d = os.path.join(a.gate, planned["name"])
        st = lines(os.path.join(d, "stages.jsonl"))
        done = os.path.join(d, "done.json")
        if not st or not os.path.exists(done):
            continue
        stop = json.load(open(done))["stage"]
        it, how = crossing(st)
        if it is None:
            continue
        n = nodes_until(st, it)
        isets = st[-1]["info_sets"]
        per_it = n / it
        rows.append({"name": planned["name"], "info_sets": isets, "it": it, "nodes": n, "how": how})
        say(f"| {planned['name']} | {isets:,} | {stop / 1e6:.0f}M | {it / 1e6:.1f}M ({how}) | {n:.3g} | "
            f"{n / isets:,.0f} | {it / isets:,.0f} | {per_it:.0f} |")

    if len(rows) < 3:
        print("\n".join(out))
        return
    visits = [r["nodes"] / r["info_sets"] for r in rows]
    b, c, sd, mx, sxx = fit([r["info_sets"] for r in rows], [r["it"] for r in rows])
    x6 = math.log(PHASE6["info_sets"])
    it6 = math.exp(c + b * x6)
    # A rough 1-sd band for the extrapolation: residual sd and the slope's own uncertainty.
    se_pred = sd * math.sqrt(1 + 1 / len(rows) + (x6 - mx) ** 2 / sxx)
    say(f"\nIterations to the bar against information sets: iterations ~ {math.exp(c):.3g} x info_sets^{b:.2f} "
        f"(residual sd {sd:.2f} in log). At {PHASE6['info_sets']:,} information sets: {it6:.3g} iterations, "
        f"1-sd band {it6 * math.exp(-se_pred):.3g} to {it6 * math.exp(se_pred):.3g}.")
    say(f"\nStates visited per information set at the bar: {min(visits):,.0f} to {max(visits):,.0f} "
        f"(median {sorted(visits)[len(visits) // 2]:,.0f}).")

    if not a.rich:
        print("\n".join(out))
        return
    log = lines(os.path.join(a.rich, "log.jsonl"))
    four = [s for s in log if s["threads"] == 4]
    one = [s for s in log if s["threads"] == 1]
    say("\n## The Phase 6 game on this machine (200bb, rich menu, 200 buckets)\n")
    say("| Session | Threads | Iterations | Seconds | Iterations/s | States/s | States per iteration | Information sets met | Bytes per information set | Table | Resident |")
    say("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for i, s in enumerate(log):
        say(f"| {i + 1} | {s['threads']} | {s['from'] / 1e6:.2f}M to {s['to'] / 1e6:.2f}M | {s['seconds']:.0f} | "
            f"{s['iterations_per_second']:,.0f} | {s['nodes_per_second'] / 1e6:.2f}M | "
            f"{s['nodes_per_second'] / s['iterations_per_second']:,.0f} | {s['info_sets']:,} "
            f"({s['info_sets'] / PHASE6['info_sets']:.1%}) | {s['bytes_per_info_set']:.1f} | "
            f"{s['table_bytes'] / 1e9:.2f} GB | {(s['resident_bytes'] or 0) / 1e9:.2f} GB |")
    last4, last1 = four[-1], (one[-1] if one else None)
    per_thread = (last1 or last4)["nodes_per_second"] / (1 if last1 else 4)
    states_per_it = last4["nodes_per_second"] / last4["iterations_per_second"]
    slots_per_is = PHASE6["slots"] / PHASE6["info_sets"]
    # cfr: 12 bytes a slot with integer regrets, plus the index. The index share per
    # information set is what the measured bytes leave after the slots.
    index_now = last4["bytes_per_info_set"] - 12 * last4["slots"] / last4["info_sets"]
    say("\n## Projection\n")
    say(f"- Information sets {PHASE6['info_sets']:,}, slots {PHASE6['slots']:,} ({slots_per_is:.2f} a set).")
    # The index grows by doubling (cfr: a shard doubles past three quarters full), so with the
    # whole table met it is the index measured now, or at most twice that.
    index_total = last4["table_bytes"] - 12 * last4["slots"]
    slots_bytes = 12 * PHASE6["slots"]
    lo_b, hi_b = slots_bytes + index_total, slots_bytes + 2 * index_total
    say(f"- Memory: {slots_bytes / 1e9:.2f} GB of slots (12 bytes each) and the index, {index_total / 1e9:.2f} GB "
        f"measured with {last4['info_sets'] / PHASE6['info_sets']:.0%} of the sets met "
        f"({index_now:.0f} bytes a set), or twice that if it doubles once more: {lo_b / 1e9:.1f} to "
        f"{hi_b / 1e9:.1f} GB for the tables, {lo_b / PHASE6['info_sets']:.0f} to {hi_b / PHASE6['info_sets']:.0f} "
        f"bytes a set. The process held {((last4['resident_bytes'] or 0) - last4['table_bytes']) / 1e9:.1f} GB more "
        f"(bucket tables, the game). Checkpoint: {(19 * PHASE6['info_sets'] + 12 * PHASE6['slots']) / 1e9:.2f} GB. "
        f"Strategy file: {2 * PHASE6['slots'] / 1e9:.2f} GB.")
    say(f"- Speed measured here, last sessions: {per_thread / 1e6:.2f}M states/s per thread "
        f"({'1 thread' if last1 else '4 threads'}), {states_per_it:,.0f} states per iteration, "
        f"with {last4['info_sets'] / PHASE6['info_sets']:.0%} of the table met.")
    speeds = [THREADS * per_thread * ARM_PER_CORE[k] * SCALING_64[k] * FULL_TABLE[k] for k in range(3)]
    say(f"- 64-thread speed in states a second: {speeds[0] / 1e6:,.0f}M slow, {speeds[1] / 1e6:,.0f}M central, "
        f"{speeds[2] / 1e6:,.0f}M fast (per core {ARM_PER_CORE}, 64-thread scaling {SCALING_64}, "
        f"full table {FULL_TABLE}).")
    vmed = sorted(visits)[len(visits) // 2]
    lo_it, hi_it = it6 * math.exp(-se_pred), it6 * math.exp(se_pred)
    works = [
        ("Iterations from the power law, times states per iteration",
         [lo_it * states_per_it * STATES_GROWTH[0], it6 * states_per_it * STATES_GROWTH[1],
          hi_it * states_per_it * STATES_GROWTH[2]]),
        ("States per information set as at 20bb",
         [min(visits) * PHASE6["info_sets"], vmed * PHASE6["info_sets"], max(visits) * PHASE6["info_sets"]]),
    ]
    say("\n| Work model | States to visit, low / central / high | Hours, low (fast speed) | Hours, central | Hours, high (slow speed) | Spot cost, central |")
    say("| --- | --- | ---: | ---: | ---: | ---: |")
    for name, (lo, mid, hi) in works:
        h_lo, h_mid, h_hi = lo / speeds[2] / 3600, mid / speeds[1] / 3600, hi / speeds[0] / 3600
        say(f"| {name} | {lo:.2g} / {mid:.2g} / {hi:.2g} | {h_lo:.1f} | {h_mid:.1f} | {h_hi:.1f} | "
            f"${h_mid * SPOT_PER_HOUR:,.0f} |")
    text = "\n".join(out)
    print(text)
    if a.md:
        with open(a.md, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
