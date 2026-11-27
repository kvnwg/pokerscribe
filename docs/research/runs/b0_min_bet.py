"""B0's always-wrong checks (simulate.check_advice) on the main tables, six-max and heads-up,
for the fix of bets under the minimum. Every instruction is kept, so the runs before and after
the fix can be compared hand by hand.

    python docs/research/runs/b0_min_bet.py run OUT_DIR [JOBS]    every setting below, JOBS at a time (4)
    python docs/research/runs/b0_min_bet.py compare BEFORE_DIR AFTER_DIR

Settings: six-max, 2000 hands, on every table (the tuning tables and the held-out ones), 100
and 500 big blinds deep; mixed and fish247 with tournament stacks, mixed with uneven stacks; and
fish247 500 big blinds deep on seed 43, the run where #21 found the bet under the minimum.
Heads-up: the 17 settings of phase1_heads_up_b0.sh, same seeds and hands.
"""
import json
import os
import sys
from collections import Counter
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import simulate as sim  # noqa: E402

TABLES = ("mixed", "stations", "nits", "tags", "lags", "maniacs", "fish247",
          "heldout", "regulars", "switchers", "wildcards")
# (players, table, stacks, hands, seed, deep, profiles)
SETTINGS = (
    [(6, t, "even", 2000, 51 + k, False, False) for k, t in enumerate(TABLES)]
    + [(6, t, "even", 2000, 62 + k, True, False) for k, t in enumerate(TABLES)]
    + [(6, "mixed", "tourney", 2000, 73, False, False), (6, "fish247", "tourney", 2000, 74, False, False),
       (6, "mixed", "uneven", 2000, 75, False, False), (6, "fish247", "even", 2000, 43, True, False)]
    # heads-up: phase1_heads_up_b0.sh
    + [(2, t, "even", 2000, 21 + k, False, False) for k, t in enumerate(
        ("mixed", "stations", "nits", "tags", "lags", "maniacs", "fish247", "heldout", "regulars", "switchers",
         "wildcards"))]
    + [(2, "mixed", "uneven", 2000, 32, False, False), (2, "mixed", "tourney", 2000, 33, False, False),
       (2, "fish247", "tourney", 2000, 34, False, False), (2, "mixed", "even", 2000, 35, True, False),
       (2, "fish247", "even", 2000, 36, True, False), (2, "mixed", "even", 1000, 37, False, True)]
)


def name(cfg) -> str:
    players, table, stacks, n, seed, deep, profiles = cfg
    return "_".join([str(players), table, stacks, str(n), str(seed)] + (["deep"] if deep else [])
                    + (["profiles"] if profiles else []))


def one(cfg) -> dict:
    players, table, stacks, n, seed, deep, profiles = cfg
    orig = sim.check_advice
    said = []  # every instruction: hand, cards on the board, action, amount, headline
    stats_ref = {}

    def check(h, me, adv, stats):
        stats_ref["s"] = stats
        before = sum(stats["problems"].values())
        orig(h, me, adv, stats)
        said.append((len(stats["hands"]), len(h.board), adv.action, adv.amount, adv.headline,
                     sum(stats["problems"].values()) > before))

    sim.check_advice = check
    try:
        st = sim.run(n, table, seed, quiet=True, stacks=stacks, depth_bb=500.0 if deep else 100.0,
                     profiles=profiles, players=players)
    finally:
        sim.check_advice = orig
    r = st["hands"]
    return {"config": list(cfg), "hands": len(r), "decisions": len(said), "bb100": 100 * sum(r) / len(r),
            "problems": dict(st["problems"]), "examples": st["examples"][:10],
            "nets": [round(x, 6) for x in r], "said": said}


def run(out: str, jobs: int) -> None:
    os.makedirs(out, exist_ok=True)
    with Pool(jobs) as pool:
        for cfg, res in zip(SETTINGS, pool.imap(one, SETTINGS)):
            with open(os.path.join(out, name(cfg) + ".json"), "w") as f:
                json.dump(res, f)
            print(f"done {name(cfg)}: {res['decisions']} instructions, problems {res['problems'] or 'none'}",
                  flush=True)


def label(cfg) -> str:
    players, table, stacks, n, seed, deep, profiles = cfg
    return f"{table}, {stacks}" + (", 500 bb deep" if deep else "") + (", profiles" if profiles else "")


def compare(before: str, after: str) -> None:
    print("| Players | Table, stacks | Seed | Hands | Instructions | Under the minimum, before / after "
          "| Other always-wrong, after | Instructions changed | Hands whose result changed |")
    print("|---|---|---|---|---|---|---|---|---|")
    totals = Counter()
    changes = []
    for cfg in SETTINGS:
        b = json.load(open(os.path.join(before, name(cfg) + ".json")))
        a = json.load(open(os.path.join(after, name(cfg) + ".json")))
        key = "below the minimum bet or raise"
        under_b, under_a = b["problems"].get(key, 0), a["problems"].get(key, 0)
        other = {k: v for k, v in a["problems"].items() if k != key}
        by_hand_b, by_hand_a = {}, {}
        for x in b["said"]:
            by_hand_b.setdefault(x[0], []).append(x[1:5])
        for x in a["said"]:
            by_hand_a.setdefault(x[0], []).append(x[1:5])
        changed_said = [k for k in sorted(set(by_hand_b) | set(by_hand_a)) if by_hand_b.get(k) != by_hand_a.get(k)]
        changed_net = [k for k, (x, y) in enumerate(zip(b["nets"], a["nets"])) if abs(x - y) > 1e-9]
        n_said = sum(1 for k in changed_said for u, v in zip(by_hand_b.get(k, []), by_hand_a.get(k, [])) if u != v)
        print(f"| {cfg[0]} | {label(cfg)} | {cfg[4]} | {a['hands']} | {a['decisions']} | {under_b} / {under_a} "
              f"| {sum(other.values()) or 'none'} | {n_said} | {len(changed_net)} |")
        totals.update({f"hands{cfg[0]}": a["hands"], f"decisions{cfg[0]}": a["decisions"],
                       f"under_before{cfg[0]}": under_b, f"under_after{cfg[0]}": under_a,
                       f"other{cfg[0]}": sum(other.values()), f"said{cfg[0]}": n_said,
                       f"net{cfg[0]}": len(changed_net)})
        for k in changed_said:
            for u, v in zip(by_hand_b.get(k, []), by_hand_a.get(k, [])):
                if u != v:
                    changes.append((label(cfg), cfg[0], cfg[4], k + 1, u, v,
                                    k in changed_net and round(a["nets"][k] - b["nets"][k], 3)))
    print()
    for p in (6, 2):
        print(f"- {'Six-max' if p == 6 else 'Heads-up'}: {totals[f'hands{p}']} hands, {totals[f'decisions{p}']} "
              f"instructions; under the minimum {totals[f'under_before{p}']} before, {totals[f'under_after{p}']} "
              f"after; other always-wrong after: {totals[f'other{p}'] or 'none'}; instructions changed "
              f"{totals[f'said{p}']}; hands whose result changed {totals[f'net{p}']}.")
    if changes:
        print("\nEvery instruction that changed (hand number in its run; street as cards on the board; "
              "before -> after; change in the hand's result in big blinds, or False if none):\n")
        for c in changes:
            lab, p, seed, k, u, v, dnet = c
            print(f"- {p} players, {lab}, seed {seed}, hand {k}, {u[0]} cards: {u[3]} -> {v[3]}"
                  f" (result {'unchanged' if dnet is False else f'{dnet:+g} bb'})")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
    elif sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
