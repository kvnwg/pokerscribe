# Phase 5 check: standard-k50 against standard-k200 head to head at 100 big blinds

Informational, not a gate run. The plan (`plan.md`, `plan.json`, `run.py`, `report.py`) was
committed and pushed in 171028d at 12:57:53 UTC on 27 Nov 2026, before the main run (12:58 to
12:59 UTC). The tables are in `results.md` (`report.py`'s output). The write-up is in
`experiments.md`, under "Phase 5 check: buckets at 100 big blinds".

## Results

Duplicate deals with the seats swapped, the all-in equity adjustment, 2,000,000 deals (4,000,000
hands) a match, bb/100 for the second run against the first:

| Match | Seed | Result | In SE | Real chips | Second on the button | Second in the big blind |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard-k200 against standard-k50 (the decision) | 9201 | +3.74 ± 0.48 | +7.7 | +3.37 ± 0.50 | +19.29 ± 0.91 | -11.81 ± 0.91 |
| the same, fresh deals (replication) | 9202 | +3.74 ± 0.49 | +7.7 | +3.71 ± 0.50 | +18.21 ± 0.91 | -10.72 ± 0.91 |
| standard-k50 against standard-k10 (sanity check) | 9301 | +13.28 ± 0.52 | +25.7 | +13.38 ± 0.53 | +28.68 ± 0.94 | -2.13 ± 0.96 |
| standard-k200 against standard-k10 (information) | 9401 | +15.03 ± 0.52 | +28.8 | +15.33 ± 0.54 | +30.54 ± 0.94 | -0.49 ± 0.96 |

No illegal actions in any match. The all-in adjustment changed 0.3% to 0.4% of the hands. Each
match took 10 or 11 seconds on 4 threads. The main match and its replication agree to 0.002
bb/100 by chance: their deals differ (their real-chip results, seat figures and adjusted hands
all do), and the gap between them is +0.00 ± 0.69.

**Each seat's figure includes the button's advantage**: the second run on the button plays the
first in the big blind, and the other way round. The result is the mean of the two, and half
their difference (14.5 to 15.6 bb/100 in the four matches) is about what the button wins here.
So a seat's figure on its own is not the second run's edge in that seat.

## The decision, by the plan's rule

**standard-k200 is ahead of standard-k50 by 2.5 SE or more (7.7 SE): the extra buckets pay off
in play.** The edge, 3.74 bb/100, is above the plan's 2 bb/100 line for a small edge, and the
replication gives the same call. Nothing to flag before Phase 6's full run.

The sanity check passes: standard-k50 beats standard-k10 by 13.28 ± 0.52 (25.7 SE), so the arena
sees the 10 to 50 gain LBR saw.

## What it means

- **Head to head, every step up in buckets wins**, by less each time: 10 to 50 buckets +13.3,
  50 to 200 +3.7, and 10 to 200 +15.0 bb/100.
- **From 50 to 200 buckets, play and LBR disagree.** LBR, the worst case, found standard-k200
  more exploitable than standard-k50 (M +12.2 ± 5.0 pooled over two deal sets; `fcpa34` +18.5 ±
  6.5). Against standard-k50, standard-k200 wins. Worst-case exploitability and strength against
  another strategy need not move together, and here they don't. From 10 to 50 the two agree.
- **For Phase 6** (200 buckets a street, the gate head to head and against B0): this supports
  keeping 200 buckets. It also says, again, that Phase 6's LBR readings shouldn't be read as the
  value of its card abstraction. The gate is unchanged.

What this doesn't show: both blueprints have the same menu and buckets of the same kind, so
every bet is on both trees. The match measures them against each other, not against an opponent
that plays off their menu, as LBR does, or as people and other programs would.

## Files

| File | What |
| --- | --- |
| `plan.md`, `plan.json` | The plan, committed before the main run (`plan.json` added with `git add -f`) |
| `pilot.py`, `pilot.jsonl` | The pilot (seeds 9101 and 9102, 20,000 deals each), run before the plan, used only for its speed and sd |
| `run.py`, `run.log`, `results.jsonl` | The matches: the script, its output, and every match's full arena report |
| `report.py`, `results.md` | The plan's tables and decision, and their output |

To rebuild `results.md` from `results.jsonl`:

```bash
python docs/research/runs/phase5_100bb_h2h/report.py docs/research/runs/phase5_100bb_h2h/plan.json docs/research/runs/phase5_100bb_h2h/results.jsonl
```

The arena deals from the seed and the deal's index and gives each seat its own random numbers,
so a match repeats: the main match played again after the run (not kept) gave a report identical
to the first apart from its timing.
