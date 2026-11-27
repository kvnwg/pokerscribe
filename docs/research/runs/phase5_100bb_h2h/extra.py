"""Added after review, not pre-registered, doesn't change the decision.

The main match (seed 9201) and its replication (seed 9202) agreed to 0.0023 bb/100 (3.7409 and
3.7432, the difference's SE 0.69). This checks that it is chance:

1. The cards: the arena deals deal d of a match from mix(seed, d) alone, whatever the agents
   (engine/crates/arena/src/runner.rs, `Deal::from_seed`). A Python agent that only checks
   and calls, one in each seat, sees both seats' hole cards and the whole board of every deal.
   Seeds 9201 and 9202, the first 1,000 deals each: the first deal's cards, and how many of the
   1,000 deals are the same on both seeds.
2. The blueprints on seeds 9201 and 9202 at 1,000 deals, with their reports.
3. standard-k200 against standard-k50 on two more fresh seeds, 9203 and 9204, 2,000,000 deals
   each, the plan's settings.
4. With --more, run after 1 to 3: eight more fresh seeds, 9205 to 9212, the same way.

    python docs/research/runs/phase5_100bb_h2h/extra.py docs/research/runs/phase5_100bb_h2h/plan.json OUT.jsonl
    python docs/research/runs/phase5_100bb_h2h/extra.py docs/research/runs/phase5_100bb_h2h/plan.json OUT.jsonl --more
"""
import json
import sys
import time

import pokerscribe_engine as pe


class Recorder:
    """Checks or calls every time; keeps its seat's hole cards and the final board."""

    def __init__(self, name):
        self.name = name
        self.hands = []

    def begin_hand(self, view):
        self.hands.append({"seat": view.seat, "hole": view.hole, "board": []})

    def act(self, view):
        return "check" if view.to_call == 0 else "call"

    def end_hand(self, view):
        self.hands[-1]["board"] = view.board


def cards(seed, deals, g):
    a, b = Recorder("first"), Recorder("second")
    pe.run_match([a, b], deals, seed, stack=g["stack"], small_blind=g["small_blind"],
                 big_blind=g["big_blind"], all_in_equity=False, threads=1)
    out = []
    # Each deal is played twice (the seats swapped), one thread, in order.
    for d in range(deals):
        hands = [a.hands[2 * d], b.hands[2 * d]]
        hole = {h["seat"]: h["hole"] for h in hands}
        assert hands[0]["board"] == hands[1]["board"]
        out.append({"deal": d, "button": hole[0], "big_blind": hole[1], "board": hands[0]["board"]})
        # The replay with the seats swapped deals the same cards to the same seats.
        again = {h["seat"]: h["hole"] for h in (a.hands[2 * d + 1], b.hands[2 * d + 1])}
        assert again == hole and a.hands[2 * d + 1]["board"] == hands[0]["board"]
    return out


def match(plan, a, b, seed, deals):
    g, ar = plan["game"], plan["arena"]
    agents = ["blueprint:" + plan["files"][a]["path"], "blueprint:" + plan["files"][b]["path"]]
    start = time.time()
    report = pe.run_match(agents, deals, seed, players=g["players"], stack=g["stack"],
                          small_blind=g["small_blind"], big_blind=g["big_blind"],
                          duplicate=ar["duplicate"], all_in_equity=ar["all_in_equity"],
                          max_runouts=ar["max_runouts"], shared_randomness=ar["shared_randomness"],
                          threads=ar["threads"]).to_dict()
    return {"a": a, "b": b, "seed": seed, "deals": deals, "wall_seconds": time.time() - start,
            "report": report}


def main():
    plan = json.load(open(sys.argv[1]))
    out = open(sys.argv[2], "a")
    more = len(sys.argv) > 3 and sys.argv[3] == "--more"

    def write(obj):
        out.write(json.dumps(obj) + "\n")
        out.flush()

    if more:
        # 4. Run after 1 to 3: seeds 9203 and 9204 put three of four results within 0.021 of
        # each other, so eight more fresh seeds show the spread.
        for seed in range(9205, 9213):
            play(plan, write, seed, 2_000_000)
        return

    seen = {}
    for seed in (9201, 9202):
        seen[seed] = cards(seed, 1000, plan["game"])
        write({"check": "cards", "seed": seed, "deals": 1000, "first_deal": seen[seed][0]})
    same = sum(1 for x, y in zip(seen[9201], seen[9202])
               if (x["button"], x["big_blind"], x["board"]) == (y["button"], y["big_blind"], y["board"]))
    write({"check": "cards compared", "seeds": [9201, 9202], "deals": 1000, "identical_deals": same})
    print(f"cards: of the first 1,000 deals, {same} are the same on seeds 9201 and 9202", flush=True)
    for seed in (9201, 9202):
        print(f"  seed {seed}, deal 0: {seen[seed][0]}", flush=True)

    for seed, deals in [(9201, 1000), (9202, 1000), (9203, 2_000_000), (9204, 2_000_000)]:
        play(plan, write, seed, deals)


def play(plan, write, seed, deals):
    r = match(plan, "standard-k50", "standard-k200", seed, deals)
    write(dict(r, check="match"))
    x = r["report"]["results"][1]
    print(f"standard-k200 against standard-k50, seed {seed}, {deals:,} deals: "
          f"{x['bb_per_100']:+.4f} +- {x['se']:.4f} bb/100, real chips "
          f"{x['actual_bb_per_100']:+.4f}, illegal "
          f"{[y['illegal_actions'] for y in r['report']['results']]}", flush=True)


if __name__ == "__main__":
    main()
