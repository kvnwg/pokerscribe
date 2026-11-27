"""Markdown table of phase1_heads_up_b0.py outputs: python phase1_heads_up_b0_table.py <folder>"""
import glob
import json
import os
import sys

rows = []
tot_hands = tot_dec = 0
for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    try:
        d = json.load(open(path))
    except ValueError:
        continue
    players, table, stacks, n, seed, *rest = d["config"]
    extra = ", ".join(rest)
    label = f"{table}, {stacks}" + (f", {extra}" if extra else "")
    probs = sum(d["problems"].values()) + sum(d["extra"].values())
    first = d["preflop_first"]
    btn = first.get("BTN/SB", {})
    rows.append((int(players), label, seed, d["hands"], d["decisions"], d["bb100"], probs,
                 btn.get("raise", 0.0), d["problems"], d["extra"]))
    if players == "2":
        tot_hands += d["hands"]
        tot_dec += d["decisions"]
print("| Players | Table, stacks | Seed | Hands | Instructions | B0, bb/100 | Always-wrong | Button raises |")
print("|---|---|---|---|---|---|---|---|")
notes = []
for p, label, seed, hands, dec, bb, probs, btn, pr, ex in sorted(rows, key=lambda r: (r[0], r[1])):
    print(f"| {p} | {label} | {seed} | {hands} | {dec} | {bb:+.1f} | {probs or 'none'} | "
          + (f"{100 * btn:.0f}% |" if p == 2 else "- |"))
    if pr or ex:
        notes.append(f"- {p} players, {label}: {dict(pr, **ex)}")
print(f"\nHeads-up: {tot_hands} hands, {tot_dec} instructions. \"Button raises\": B0's share of raises as the"
      " button (BTN/SB), first in.")
if notes:
    print("\nAlways-wrong instructions found:\n" + "\n".join(notes))
