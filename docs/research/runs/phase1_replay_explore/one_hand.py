"""Play one hand of a paired comparison again and print the original pair and its replays."""
import os, sys, json
import os; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import simulate as sim, compare, hidden

captured = []
real_showdown = sim.showdown
def spy(h):
    captured.append(h)
    return real_showdown(h)
sim.showdown = spy

def fmt(h, me=0):
    out = []
    for i, kind, amt, street in h.log:
        who = "APP" if i == me else f"b{i}"
        out.append(f"{'PFTR'[[0,3,4,5].index(street)]}:{who} {kind}{'' if not amt else ' %.1f' % (amt / sim.BB)}")
    return " ".join(out)

def play(base, other, table, seed, k, resample=6, redeal=True):
    d, r = compare.deal(k, "duplicate")
    styles, names = sim.seating(table, seed, d)
    hand_seed = seed * 100003 + d
    sim.clear_advice_cache()
    sa, sb = compare.new_stats(base, other), compare.new_stats(other)
    captured.clear()
    sim.play_hand(styles, d % 6, hand_seed, 0, 100.0, sa, "even", names, None, k + 1, rotate=r, keyed=True)
    ha = captured[-1]; rec_a = sa["last"]
    print(f"hand {k}: deck {d} rotation {r} seats {styles} diverged {sa['diverged']} at {rec_a['diverge_at']}")
    print("cards", rec_a["cards"], "board", rec_a["board"])
    sim.play_hand(styles, d % 6, hand_seed, 0, 100.0, sb, "even", names, None, k + 1, rotate=r, keyed=True)
    hb = captured[-1]
    print(f"orig base  {rec_a['net']:+7.1f}: {fmt(ha)}  board {ha.board}")
    print(f"orig other {sb['last']['net']:+7.1f}: {fmt(hb)}  board {hb.board}")
    if not sa["diverged"]:
        return
    j = rec_a["diverge_at"]
    classes = hidden.live_classes(rec_a, j) if redeal else None
    if classes:
        print("live classes:", {i: len(c) for i, c in classes.items()}, "actual in class:",
              {i: (tuple(rec_a["cards"][i]) in c or tuple(reversed(rec_a["cards"][i])) in c) for i, c in classes.items()})
    draws = hidden.redeal(classes, resample - 1, (hand_seed, r, "redeal")) if classes else None
    for salt in range(1, resample):
        nets = []
        for v in (base, other):
            st = compare.new_stats(v)
            captured.clear()
            sim.play_hand(styles, d % 6, hand_seed, 0, 100.0, st, "even", names, None, k + 1, rotate=r, keyed=True,
                          split_at=j, resample=salt, hole_override=draws[salt - 1] if draws else None)
            nets.append((st["last"]["net"], captured[-1]))
        print(f"replay {salt} diff {nets[1][0] - nets[0][0]:+7.1f} hole {draws[salt-1] if draws else '-'}")
        print(f"   base  {nets[0][0]:+7.1f}: {fmt(nets[0][1])}  board {nets[0][1].board}")
        print(f"   other {nets[1][0]:+7.1f}: {fmt(nets[1][1])}  board {nets[1][1].board}")

if __name__ == "__main__":
    base = json.loads(sys.argv[1]); other = json.loads(sys.argv[2])
    table, seed, k = sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
    redeal = len(sys.argv) <= 6 or sys.argv[6] != "noredeal"
    play(base, other, table, seed, k, redeal=redeal)
