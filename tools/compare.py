"""Compare two strategy variants on exactly the same hands (paired simulation).

    python tools/compare.py '{"pot_control": 0.08}' [hands] [--tables mixed,stations,maniacs,fish247]
    python tools/compare.py '{}' 2000 --base '{"texture_sizing": true}'
    python tools/compare.py '{"bully": true}' 1000 --stacks uneven
    python tools/compare.py '{"ev_sizing": true}' 3000 --method classic   # as before 26 Nov 2026
    python tools/compare.py '{"bet_size": 0.5}' 2000 --players 2           # heads-up

Each hand is dealt from a seed, and the bots' choices come from a seed too, so both
variants see the same cards and the same opponents. The hand is played with the base
variant; at each of the app's decisions the other variant is asked as well. If they
never disagree the result is the same and the hand counts as a difference of zero; if
they do, the hand is replayed with the other variant from the start. The win-rate
difference and its standard error come from these per-hand differences, which removes
most of the luck of the cards from the comparison.

Two ways to deal (--method):
  duplicate (default)  each deck is played six times with the players rotated one seat
                       each time, so the app and every bot hold each seat's cards from
                       that seat's position once; each bot decision has its own seed, so
                       when the variants part ways the bots still draw the same numbers.
                       Heads-up (--players 2) each deal is played twice with the seats
                       swapped: the app holds the button's cards once and the big blind's
                       once, against the same bot
  classic              one hand per deck and one random stream for the bots (every result
                       in experiments.md before Phase 1 was made this way)
  keyed                one hand per deck, a seed per bot decision (to measure the two parts
                       of duplicate separately)

Each hand where the variants differ is also played five more times from the first decision
where they part (--resample, 6 plays in all by default), with fresh bot random numbers and
board cards, and the bots still in dealt fresh hands they could have held given what they
did before (tools/hidden.live_classes; --no-redeal keeps their cards). The luck of board
cards after which nobody can bet again is taken out (tools/luck.py; --full-luck corrects
every board card after the split). The "replayed 6 times" figure is the estimate to use: in
Phase 1 gate run 4 its standard error was 0.42 of the classic one (geometric mean over 8
comparisons) for 1.17 times the CPU (docs/research/experiments.md). Standard errors count
the six hands of a deck (two heads-up) as one unit. Variants are overrides of
app.poker.advice.TUNING, given as JSON. --jobs 4 splits the hands over four processes with
identical results. --players 2 plays heads-up (tools/simulate.py): the app against one bot
of each table at a time.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hidden  # noqa: E402
import luck  # noqa: E402
import simulate as sim  # noqa: E402

METHODS = ("duplicate", "classic", "keyed")


def new_stats(variant=None, shadow=None) -> dict:
    return {"hands": [], "by_pos": defaultdict(list), "by_street": defaultdict(list), "all_in": [],
            "preflop_first": defaultdict(int), "advice": defaultdict(int), "problems": defaultdict(int),
            "examples": [], "variant": variant, "shadow": shadow}


def deal(k: int, method: str, players: int = 6) -> tuple:
    """Hand k's deck number and rotation (duplicate: one hand per seat of each deck)."""
    return divmod(k, players) if method == "duplicate" else (k, 0)


def paired(base: dict, other: dict, n: int, table: str, seed: int, depth_bb: float = 100.0, stacks: str = "even",
           profiles: bool = False, method: str = "classic", adjust: bool = True, adjust_all: bool = False,
           start: int = 0, resample: int = 1, use_hidden: bool = False, lean: bool = False,
           redeal: bool = False, exact_luck: bool = False, players: int = 6):
    """With profiles, the app learns the bots' styles from the hands as in watch mode. They are
    learned from the base variant's hands; a replayed hand starts from the same profiles.
    players: 6 (six-max) or 2 (heads-up, tools/simulate.py); with duplicate, each deck is
    played once per seat.

    Returns (base stats, other stats, per-hand differences, hands replayed, extra). extra has
    "decks" (each hand's deck, the unit for standard errors), and if adjust "adjusted" (the
    luck-adjusted differences, tools/luck.py), "checked_down" (the same with the checked-down
    value only), "x" (each hand's all-in features, other minus base) and "weights"
    (luck.WEIGHTS, fixed). With adjust_all, "base_adjusted" and "other_adjusted": each hand's
    luck-adjusted result for each variant. start: play hands start .. start + n - 1 (a shard
    of a longer run; see run_paired).

    resample K > 1 (duplicate or keyed, no profiles): each hand where the variants part ways
    is also played K - 1 more times from the first decision where they differ, with fresh
    bot random numbers and fresh board cards still to come (the same for both variants in
    each replay), and extra["resampled"] is the average luck-adjusted difference over the K
    plays (extra["resampled_raw"] the same without the luck adjustment). Which hands get
    replayed depends only on what happened before they part, so the average has the same
    expected value as one play.

    use_hidden (keyed or duplicate, no profiles): for hands where the variants part heads-up
    after the flop, extra["hidden"] also takes the opponent's hidden cards and random choices
    out (tools/hidden.py), averaged over the same plays; other hands that differ use the
    resampled luck-adjusted difference. extra["eligible"] marks the hands that used it.

    lean (with use_hidden): compute only what extra["hidden"] needs, so its time can be
    measured; the luck-adjusted columns are then NaN for the hands that use hidden cards.

    redeal (with resample): each replay also deals the bots still in at the split a fresh draw
    from the hands they could hold given what they did before it (tools/hidden.live_classes),
    so the replays average over the opponents' cards too. Given the split each replay is a
    fresh draw of the rest of the hand, so the average keeps the expected value.

    exact_luck: the luck adjustment only corrects board cards after which nobody can bet
    again, where the checked-down value is exact (tools/luck.no_more_betting)."""
    assert method in METHODS, method
    assert players in sim.PLAYERS, players
    assert resample <= 1 or (method != "classic" and not profiles), "resample needs keyed bots and no profiles"
    assert not use_hidden or (method != "classic" and not profiles), "hidden needs keyed bots and no profiles"
    sa, sb = new_stats(base, other), new_stats(other)
    diffs, replayed = [], 0
    zero = [0.0] * (1 + luck.N_FEATURES)
    extra = {"decks": [], "adjusted": [], "checked_down": [], "x": [], "weights": [],
             "base_adjusted": [], "other_adjusted": [], "resampled": [], "resampled_raw": [], "hidden": [],
             "eligible": [], "hidden_seconds": 0.0}
    base_y, base_x = [], []
    prof = sim.new_profiles() if profiles else None
    sa["profiles"] = prof
    for k in range(start, start + n):
        sim.clear_advice_cache()
        d, r = deal(k, method, players)
        styles, names = sim.seating(table, seed, d, players)
        hand_seed = seed * 100003 + d
        keyed = method in ("duplicate", "keyed")
        before = copy.deepcopy(prof) if prof is not None else None
        net_a = sim.play_hand(styles, d % players, hand_seed, 0, depth_bb, sa, stacks, names, prof, k + 1,
                              rotate=r, keyed=keyed)[0] / sim.BB
        rec_a = sa["last"]
        fa = luck.features(rec_a) if adjust_all else None
        fd = zero
        # board cards dealt before the split are the same for both variants: their luck
        # cancels in the difference, so only the later ones are worked out
        after = rec_a["spots"][rec_a["diverge_at"]]["board_len"] if sa["diverged"] else -1
        b_seat = hidden.opponent(rec_a, rec_a["diverge_at"]) if (use_hidden and sa["diverged"]) else None
        need_luck = adjust and not (lean and b_seat is not None)
        if sa["diverged"]:
            replayed += 1
            net_b = sim.play_hand(styles, d % players, hand_seed, 0, depth_bb, sb, stacks, names, before, k + 1,
                                  rotate=r, keyed=keyed)[0] / sim.BB
            if need_luck:
                fd = [b - a for a, b in zip(luck.features(rec_a, after=after, exact_only=exact_luck),
                                            luck.features(sb["last"], after=after, exact_only=exact_luck))]
        else:
            net_b = net_a
            sb["hands"].append(net_b)
        if resample > 1 or use_hidden:
            raw_s, adj_s = [net_b - net_a], [luck.adjust(net_b - net_a, fd)] if need_luck else None
            hid_s, eligible = None, False
            if sa["diverged"]:
                j = rec_a["diverge_at"]
                pairs = [(rec_a, sb["last"])]
                classes = hidden.live_classes(rec_a, j) if (redeal and resample > 1) else None
                draws = hidden.redeal(classes, resample - 1, (hand_seed, r, "redeal")) if classes else None
                for salt in range(1, resample):
                    recs = []
                    for v in (base, other):
                        st = new_stats(v)
                        sim.play_hand(styles, d % players, hand_seed, 0, depth_bb, st, stacks, names, None, k + 1,
                                      rotate=r, keyed=keyed, split_at=j, resample=salt,
                                      hole_override=draws[salt - 1] if draws else None)
                        recs.append(st["last"])
                    pairs.append(tuple(recs))
                    raw_s.append(recs[1]["net"] - recs[0]["net"])
                    if need_luck:
                        f0 = luck.features(recs[0], after=after, exact_only=exact_luck)
                        f1 = luck.features(recs[1], after=after, exact_only=exact_luck)
                        adj_s.append(luck.adjust(raw_s[-1], [b - a for a, b in zip(f0, f1)]))
                if b_seat is not None:
                    t_h = time.process_time()
                    sp = hidden.Split(rec_a, j, b_seat, cls=classes[b_seat] if classes else None)
                    hid_s = [hidden.estimate(pb, sp) - hidden.estimate(pa, sp) for pa, pb in pairs]
                    eligible = True
                    extra["hidden_seconds"] += time.process_time() - t_h
            extra["resampled_raw"].append(sum(raw_s) / len(raw_s))
            extra["resampled"].append(sum(adj_s) / len(adj_s) if adj_s else float("nan"))
            if use_hidden:
                extra["hidden"].append(sum(hid_s) / len(hid_s) if hid_s else extra["resampled"][-1])
                extra["eligible"].append(eligible)
        diffs.append(net_b - net_a)
        extra["decks"].append(d)
        if adjust:
            nan = not need_luck
            extra["checked_down"].append(float("nan") if nan else net_b - net_a - fd[0])
            extra["x"].append(fd[1:])
        if adjust_all:
            base_y.append(net_a - fa[0])
            base_x.append(fa[1:])
    if adjust:
        extra["weights"] = list(luck.WEIGHTS)
        extra["adjusted"] = [luck.adjust(y, [0.0] + x) for y, x in zip(extra["checked_down"], extra["x"])]
    if adjust_all:
        extra["base_adjusted"] = [luck.adjust(y, [0.0] + x) for y, x in zip(base_y, base_x)]
        extra["other_adjusted"] = [a + (dd if adjust else raw) for a, dd, raw in
                                   zip(extra["base_adjusted"], extra["adjusted"] or diffs, diffs)]
    return sa, sb, diffs, replayed, extra


def _paired_star(args):
    *rest, start, resample, use_hidden, lean, redeal, exact_luck, players = args
    return paired(*rest, start=start, resample=resample, use_hidden=use_hidden, lean=lean, redeal=redeal,
                  exact_luck=exact_luck, players=players)


def run_paired(base: dict, other: dict, n: int, table: str, seed: int, depth_bb: float = 100.0,
               stacks: str = "even", profiles: bool = False, method: str = "classic", adjust: bool = True,
               adjust_all: bool = False, jobs: int = 1, resample: int = 1, use_hidden: bool = False,
               lean: bool = False, redeal: bool = False, exact_luck: bool = False, players: int = 6):
    """paired() split over `jobs` processes by whole decks and merged; the result is the same
    hand for hand. With profiles the hands depend on the ones before, so it runs in one."""
    if jobs <= 1 or profiles or n < 2 * players:
        return paired(base, other, n, table, seed, depth_bb, stacks, profiles, method, adjust, adjust_all,
                      resample=resample, use_hidden=use_hidden, lean=lean, redeal=redeal, exact_luck=exact_luck,
                      players=players)
    from concurrent.futures import ProcessPoolExecutor

    chunk = -(-n // jobs)
    chunk += (-chunk) % players  # whole decks
    starts = list(range(0, n, chunk))
    args = [(base, other, min(chunk, n - st), table, seed, depth_bb, stacks, profiles, method, adjust, adjust_all, st,
             resample, use_hidden, lean, redeal, exact_luck, players) for st in starts]
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        parts = list(ex.map(_paired_star, args))
    sa, sb, diffs, replayed, extra = parts[0]
    for pa, pb, d, rep_, ex_ in parts[1:]:
        for mine, theirs in ((sa, pa), (sb, pb)):
            for key, val in theirs.items():
                if isinstance(val, list) and isinstance(mine.get(key), list):
                    mine[key] += val
                elif isinstance(val, dict) and isinstance(mine.get(key), dict) and key not in ("variant", "shadow",
                                                                                               "last"):
                    for kk, vv in val.items():
                        mine[key][kk] = mine[key][kk] + vv if kk in mine[key] else vv
        diffs += d
        replayed += rep_
        for key, val in ex_.items():
            if key == "weights":
                continue
            extra[key] += val  # lists are joined, seconds added
    sa["examples"] = sa["examples"][:25]
    return sa, sb, diffs, replayed, extra


def summary(values, units=None):
    """Mean and standard error in bb/100. With units (one label per value, e.g. the deck),
    values that share a unit count as one draw (a cluster-robust standard error)."""
    n = len(values)
    mean = sum(values) / n
    if units is None:
        sd = math.sqrt(sum((x - mean) ** 2 for x in values) / max(1, n - 1))
        return 100 * mean, 100 * sd / math.sqrt(n)
    sums, sizes = defaultdict(float), defaultdict(int)
    for x, u in zip(values, units):
        sums[u] += x
        sizes[u] += 1
    g = len(sums)
    ss = sum((sums[u] - sizes[u] * mean) ** 2 for u in sums)
    return 100 * mean, 100 * math.sqrt(ss * g / max(1, g - 1)) / n


def adjust_ok(a) -> bool:
    return not a.no_luck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("other", help="JSON overrides of advice.TUNING to compare against the base")
    ap.add_argument("hands", nargs="?", type=int, default=1000)
    ap.add_argument("--base", default="{}", help="JSON overrides for the base variant")
    ap.add_argument("--tables", default="mixed,stations,maniacs,fish247")
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--stacks", default="even", choices=["even"] + sorted(sim.STACKS))
    ap.add_argument("--profiles", action="store_true", help="the app learns the bots' styles as it plays")
    ap.add_argument("--method", default="duplicate", choices=METHODS,
                    help="duplicate: a seat rotation per player for each deck, a seed per bot decision; classic: "
                         "as before Phase 1")
    ap.add_argument("--no-luck", action="store_true", help="skip the luck-adjusted difference")
    ap.add_argument("--adjust-all", action="store_true",
                    help="also luck-adjust every hand, for luck-adjusted win rates of each variant")
    ap.add_argument("--save", help="write every hand's differences to this JSON file (for later analysis)")
    ap.add_argument("--resample", type=int, default=None,
                    help="play each hand where the variants differ this many times from where they part "
                         "(default 6; 1 with --method classic or --profiles)")
    ap.add_argument("--jobs", type=int, default=1,
                    help="processes to split the hands over (same results; not with --profiles)")
    ap.add_argument("--redeal", action="store_true", help=argparse.SUPPRESS)  # the default now
    ap.add_argument("--exact-luck", action="store_true", help=argparse.SUPPRESS)  # the default now
    ap.add_argument("--lean", action="store_true",
                    help="compute only the headline estimate (raw and hidden cards), to time it")
    ap.add_argument("--hidden", action="store_true",
                    help="also report the hidden-cards estimate (tools/hidden.py; keyed methods without profiles)")
    ap.add_argument("--no-hidden", action="store_true", help=argparse.SUPPRESS)  # the default now
    ap.add_argument("--no-redeal", action="store_true",
                    help="replays keep the opponents' cards (run 3); by default they deal them fresh hands")
    ap.add_argument("--full-luck", action="store_true",
                    help="luck-adjust every board card after the split; by default only those after which nobody "
                         "can bet again")
    ap.add_argument("--players", type=int, default=6, choices=sim.PLAYERS,
                    help="6: six-max; 2: heads-up against one of the table's bots at a time (each deal played twice "
                         "with the seats swapped)")
    a = ap.parse_args()
    if a.resample is None:
        a.resample = 1 if (a.method == "classic" or a.profiles) else 6
    keyed = a.method != "classic" and not a.profiles
    use_hidden = a.hidden and keyed and adjust_ok(a)
    a.redeal = keyed and a.resample > 1 and not a.no_redeal
    a.exact_luck = not a.full_luck
    if a.method == "duplicate" and a.hands % a.players:
        a.hands += a.players - a.hands % a.players  # whole decks
        print(f"(rounded up to {a.hands} hands: {'six' if a.players == 6 else 'two'} per deck)")
    base, other = json.loads(a.base), json.loads(a.other)
    adjust = not a.no_luck
    total, total_adj, total_units, total_res, total_hid = [], [], [], [], []
    saved = {"args": vars(a), "tables": {}}
    t0 = time.time()
    for table in a.tables.split(","):
        t_table, c_table = time.time(), time.process_time()
        sa, sb, diffs, replayed, extra = run_paired(base, other, a.hands, table, a.seed, 500.0 if a.deep else 100.0,
                                                    a.stacks, a.profiles, a.method, adjust, a.adjust_all, a.jobs,
                                                    a.resample, use_hidden, a.lean and use_hidden, a.redeal,
                                                    a.exact_luck, a.players)
        units = extra["decks"] if a.method == "duplicate" else None
        wa, ea = summary(sa["hands"], units)
        wb, eb = summary(sb["hands"], units)
        d, de = summary(diffs, units)
        total += diffs
        total_units += [(table, u) for u in extra["decks"]]
        line = (f"{table:9s} base {wa:+7.1f} (±{ea:5.1f})  other {wb:+7.1f} (±{eb:5.1f})  "
                f"difference {d:+6.1f} ± {de:4.1f}")
        lean = a.lean and use_hidden
        if adjust and not lean:
            ad, ade = summary(extra["adjusted"], units)
            cd, cde = summary(extra["checked_down"], units)
            total_adj += extra["adjusted"]
            line += f"  luck-adjusted {ad:+6.1f} ± {ade:4.1f} (checked down only {cd:+6.1f} ± {cde:4.1f})"
        probs = dict(sa["problems"]) or "none"
        print(f"{line} bb/100  [{replayed}/{a.hands} hands differ, problems {probs}]", flush=True)
        if a.resample > 1 and not lean:
            rs, rse = summary(extra["resampled"], units)
            rr, rre = summary(extra["resampled_raw"], units)
            total_res += extra["resampled"]
            print(f"          replayed {a.resample} times from where they part: luck-adjusted {rs:+6.1f} ± {rse:4.1f} "
                  f"(raw {rr:+6.1f} ± {rre:4.1f})", flush=True)
        if use_hidden:
            hs, hse = summary(extra["hidden"], units)
            total_hid += extra["hidden"]
            print(f"          with the opponent's hidden cards: {hs:+6.1f} ± {hse:4.1f} "
                  f"({sum(extra['eligible'])} hands heads-up after the flop, {extra['hidden_seconds']:.0f}s)", flush=True)
        if a.adjust_all:
            xa, xea = summary(extra["base_adjusted"], units)
            xb, xeb = summary(extra["other_adjusted"], units)
            print(f"          luck-adjusted win rates: base {xa:+7.1f} (±{xea:5.1f})  other {xb:+7.1f} (±{xeb:5.1f})",
                  flush=True)
        if sa.get("profiles") is not None:
            print("          styles learned: " + sim.profile_report(sa["profiles"], table), flush=True)
        saved["tables"][table] = {"diffs": diffs, "adjusted": extra["adjusted"], "decks": extra["decks"],
                                  "checked_down": extra["checked_down"], "x": extra["x"], "weights": extra["weights"],
                                  "resampled": extra["resampled"], "resampled_raw": extra["resampled_raw"],
                                  "base": sa["hands"], "other": sb["hands"], "replayed": replayed,
                                  "base_adjusted": extra["base_adjusted"], "other_adjusted": extra["other_adjusted"],
                                  "hidden": extra["hidden"], "eligible": extra["eligible"],
                                  "hidden_seconds": extra["hidden_seconds"],
                                  "seconds": time.time() - t_table,
                                  "cpu_seconds": time.process_time() - c_table if a.jobs <= 1 else None}
    if a.save:
        with open(a.save, "w") as f:
            json.dump(saved, f)
    units = total_units if a.method == "duplicate" else None
    d, de = summary(total, units)
    line = f"ALL       difference {d:+6.1f} ± {de:4.1f}"
    if adjust and total_adj:
        ad, ade = summary(total_adj, units)
        line += f"  luck-adjusted {ad:+6.1f} ± {ade:4.1f}"
    if total_res:
        rs, rse = summary(total_res, units)
        line += f"  replayed {a.resample} times {rs:+6.1f} ± {rse:4.1f}"
    if total_hid:
        hs, hse = summary(total_hid, units)
        line += f"  hidden cards {hs:+6.1f} ± {hse:4.1f}"
    print(f"{line} bb/100 over {len(total)} hands, {a.method} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
