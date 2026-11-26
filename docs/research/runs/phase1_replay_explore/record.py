"""Like compare.paired (duplicate, 6 replays), but keeps every play of each hand that differs:
the original pair, 5 replays without the redeal and 5 with it (same salts), plus checks that
each replay repeats the betting before the split."""
import json, sys, time
import os; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import simulate as sim, compare, hidden

def pre_split(rec, j):
    e0 = hidden.split_event(rec, j)
    acts = []
    for kind, idx in rec["events"][:e0 + 1]:
        if kind == "bot":
            acts.append(("bot", rec["bot_decisions"][idx]["i"], tuple(rec["bot_decisions"][idx]["action"])))
        elif kind == "app":
            sp = rec["spots"][idx]
            acts.append(("app", sp["move"], round(sp["to_bb"], 6)))
        else:
            acts.append(("card",))
    return acts

def run(base, other, table, seed, n, out_path, resample=6):
    rows = []
    t0 = time.time()
    for k in range(n):
        sim.clear_advice_cache()
        d, r = compare.deal(k, "duplicate")
        styles, names = sim.seating(table, seed, d)
        hand_seed = seed * 100003 + d
        sa, sb = compare.new_stats(base, other), compare.new_stats(other)
        sim.play_hand(styles, d % 6, hand_seed, 0, 100.0, sa, "even", names, None, k + 1, rotate=r, keyed=True)
        rec_a = sa["last"]
        if not sa["diverged"]:
            continue
        sim.play_hand(styles, d % 6, hand_seed, 0, 100.0, sb, "even", names, None, k + 1, rotate=r, keyed=True)
        rec_b = sb["last"]
        j = rec_a["diverge_at"]
        ref = pre_split(rec_a, j)
        row = {"k": k, "deck": d, "j": j, "street": rec_a["spots"][j]["board_len"],
               "live": len(rec_a["spots"][j]["live"]), "move_a": rec_a["spots"][j]["move"],
               "to_a": rec_a["spots"][j]["to_bb"], "move_b": rec_b["spots"][j]["move"],
               "to_b": rec_b["spots"][j]["to_bb"], "orig": [rec_a["net"], rec_b["net"]],
               "same_pre_b": pre_split(rec_b, j)[:-1] == ref[:-1]}
        classes = hidden.live_classes(rec_a, j)
        row["in_class"] = all(tuple(rec_a["cards"][i]) in c or tuple(reversed(rec_a["cards"][i])) in c
                              for i, c in classes.items())
        row["class_sizes"] = [len(c) for c in classes.values()]
        draws = hidden.redeal(classes, resample - 1, (hand_seed, r, "redeal")) if classes else None
        for name, use in (("plain", None), ("redeal", draws)):
            plays, same = [], True
            for salt in range(1, resample):
                nets = []
                for v in (base, other):
                    st = compare.new_stats(v)
                    sim.play_hand(styles, d % 6, hand_seed, 0, 100.0, st, "even", names, None, k + 1, rotate=r,
                                  keyed=True, split_at=j, resample=salt,
                                  hole_override=use[salt - 1] if use else None)
                    nets.append(st["last"]["net"])
                    same = same and pre_split(st["last"], j)[:-1] == ref[:-1]
                plays.append(nets)
            row[name] = plays
            row["same_pre_" + name] = same
        rows.append(row)
    json.dump({"base": base, "other": other, "table": table, "seed": seed, "n": n, "rows": rows,
               "seconds": time.time() - t0}, open(out_path, "w"))

if __name__ == "__main__":
    run(json.loads(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6])
