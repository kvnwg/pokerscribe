# Phase 5 check: buckets at 100 big blinds (the plan, written before the run)

A check added after the Phase 5 gate (`docs/research/experiments.md`, "Phase 5: the gate"), not a
gate run. This file and `plan.json` were committed before training started; the results are
added below them, and in `experiments.md` ("Phase 5 check: buckets at 100 big blinds").

## The question

At 20 big blinds more buckets did not lower LBR's win rate: from 10 to 50 buckets a street it
rose on both menus, and from 50 to 200 it was flat. Kevin needs to know whether that is the stack
depth (at 20 big blinds most of the game's value is decided before the flop, where every run uses
the same 169 exact classes, and the stack is at most 3.5 pots after the flop) or something that
will carry into Phase 6 at 200 big blinds.

So: at 100 big blinds, on the standard menu, does M fall from 10 to 50 buckets, then flatten
from 50 to 200?

## The runs

Heads-up, 100 big blinds (blinds 50/100, 10,000 chips each), the standard menu, OCHS on the
river, the gate's tables (`abstraction-build build --buckets 10, 50, 200`), the gate's training
settings unchanged (4 threads, seed 1, integer regrets at 100 a big blind, Pluribus's floor,
linear weighting every 200,000 iterations up to 20M, no pruning). `blueprint size --stack 100
--menu standard --buckets B`:

| Run | Information sets | Regret slots |
| --- | ---: | ---: |
| standard-k10 | 374,912 | 1,002,269 |
| standard-k50 | 1,815,072 | 4,834,909 |
| standard-k200 | 7,215,672 | 19,207,309 |

(At 20 big blinds the same three were 64,580, 282,340 and 1,098,940.)

## Stop rule and stages

The gate's, unchanged (`plan.json`, `stop`):

- Stages at 4M iterations, then doubling. After each: LBR `b56_14` and `fcpa34`, 50,000 hands,
  seed 777, the same deals at every stage and for every run.
- A run stops after the first doubling where both hold:
  1. LBR flat: `b56_14` moved, either way, by less than max(3% of its level, 2 paired SE);
  2. play settled: the average strategy changed by at most 8% over the doubling (the share of
     play that changed, each information set weighted by how often it is reached).
- **Cap: 256M iterations** (`max`). On this machine standard-k200 at 100bb trains at about 24,500
  iterations a second on 4 threads (`blueprint bench`, 120 seconds after 240 of warm-up, every
  information set met), so 256M takes about 3 to 3.5 hours and the next stage, 512M, about 7,
  more than the 6 hours allowed. A run that reaches 256M without meeting the rule stops there
  ("reached the largest stage") and is reported as not converged, with its trend; the bar is not
  moved.

## The final measurement

At each run's last stage: `b56_14`, `b56_34`, `fcpa14`, `fcpa34`, `fc34` (the gate's five) and
`fc14`, so the six cover both the gate's settings and the paper's (`blueprint lbr --settings
paper` is `fc14`, `fc34`, `fcpa34`, `b56_14`, `b56_34`). 100,000 hands, seed 778, the same deals
for all three runs, so every difference is paired deal by deal. M is the largest of the six; the
largest of the gate's five is reported too. Bets below the menu's smallest size are read as the
smallest (the default; the gate found the other reading worse everywhere).

`fc14` was left out of the gate because it ran 30 times slower than the others at 20bb (80 hands
a second). At 100bb it ran at 1,161 hands a second in the speed pilot (below), so it is cheap
here.

## What is reported

`analyse.py` here, written before the run, prints:

- training: information sets, stop, why, change at the stop, time, speed, `b56_14` by stage;
- the final LBR results, each with its SE, M, and the off-tree share;
- the paired differences k50 - k10 and k200 - k50 (and k200 - k10) for M and for every setting;
- the same verdict rule as the gate's buckets half: **buckets help** if M(k50) < M(k10) by more
  than 2 paired SE; **then flattens** if the drop from 50 to 200 is smaller than the drop from 10
  to 50 and M(k200) is not above M(k50) by more than 2 SE.

## What each outcome would mean

1. **Buckets help and then flatten** (M falls from 10 to 50 by more than 2 SE): the 20bb result
   was the stack depth. Deeper, the card abstraction matters as the paper found, and the Phase 6
   plan of 200 buckets a street stands.
2. **Buckets help and keep helping** (M falls from 10 to 50 and again from 50 to 200 by more
   than 2 SE): the same, and Phase 6 may gain from more than 200 buckets at 200bb.
3. **Buckets don't help** (no fall by 2 SE from 10 to 50, as at 20bb): it is not only the stack
   depth, so it will likely carry into Phase 6. Then either the buckets (imperfect recall, each
   street clustered on its own) don't separate what LBR exploits, or M measures mostly the bet
   translation, which buckets can't fix. The settings that stay close to the menu (`fcpa14`,
   `fcpa34`) and the off-tree share separate the two: if those fall with buckets while M does
   not, it is the translation. Phase 6 should then not count on LBR to show the value of 200
   buckets, and should check the card abstraction another way before paying for it.
4. **Buckets make it worse** (M rises by more than 2 SE, as on both menus at 20bb): as 3, more so.

If standard-k200 stops at the cap without converging, its comparison with standard-k50 is at
unequal convergence. At 20bb LBR rose as runs converged, so an unconverged k200 would likely look
better than it would converged: a fall from 50 to 200 would then be an upper bound on the gain,
and no fall would still mean no gain.

## The speed pilot

Only speed was measured before this plan; no LBR result was used to choose anything in it
(`/root/bp/pilot100`, not kept):

- standard-k10 at 100bb trained 4M iterations at 41,244 iterations a second on 4 threads;
- standard-k200 benched at 24,481 iterations a second, 590 states an iteration (above);
- LBR against standard-k10's 4M strategy, 2,000 hands each: `b56_14` about 220 hands a second
  once LBR's exact preflop table is built (265 seconds once per process on this machine),
  `b56_34` 998, `fcpa14` 2,030, `fcpa34` 4,584, `fc34` 7,766, `fc14` 1,161.

Expected time: about 1 hour for standard-k10, 2 for standard-k50 and 4 for standard-k200,
7 in all, in one process (`blueprint gate --plan plan.json`), as the gate ran.

## Results (27 Nov 2026)

Run from 09:17 to 12:13 UTC (`blueprint gate --plan plan.json`, one process, exit 0), from commit
350f9c4's plan. The tables are in `results.md` (`analyse.py`'s output); the checks after the
plan in `checks.md` (`checks.py`); the files are listed under "Files" below.

### Training

All three runs met the stop rule; none reached the cap.

| Run | Stopped at | Change, last doubling | Train time | Iterations/s (4 threads) | Peak memory | Iterations per information set |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard-k10 | 16M | 0.077 | 7 min | 38,518 | 0.23 GB | 43 |
| standard-k50 | 64M | 0.068 | 40 min | 26,870 | 0.58 GB | 35 |
| standard-k200 | 128M | 0.073 | 1.57 h | 22,786 | 1.62 GB | 18 |

The whole plan took 2 hours 56 minutes, not the 7 hours expected: standard-k10 converged at 16M
and standard-k200 at 128M, and LBR's `b56_14` ran at 1,189 to 1,314 hands a second on the final
deals, not the pilot's 220 (the pilot's figure was wrong).

### Final LBR (seed 778, 100,000 hands, the same deals for all three), bb/100

| Run | 56 bets, 1-4 | 56 bets, 3-4 | fcpa, 1-4 | fcpa, 3-4 | fc, 3-4 | fc, 1-4 | M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| standard-k10 | 592.6 ± 7.9 | 397.0 ± 5.8 | 74.9 ± 6.7 | 108.5 ± 5.0 | -24.7 ± 3.3 | 1.3 ± 2.5 | 592.6 |
| standard-k50 | 575.6 ± 7.7 | 431.8 ± 5.8 | 96.0 ± 6.8 | 132.8 ± 5.2 | -15.2 ± 3.0 | 0.2 ± 2.6 | 575.6 |
| standard-k200 | 592.9 ± 7.7 | 439.3 ± 6.0 | 111.4 ± 6.8 | 151.3 ± 5.4 | -11.2 ± 3.2 | 4.2 ± 2.7 | 592.9 |

M is `b56_14` for all three, so M of six and M of the gate's five are the same. With the 56
sizes, 9.1% to 10.1% of the blueprint's decisions are off the tree (about 18% at 20 big
blinds); with `fcpa14` 1.5% to 1.7%.

Paired differences, the second run minus the first:

| Buckets | 56 bets, 1-4 (M) | 56 bets, 3-4 | fcpa, 1-4 | fcpa, 3-4 | fc, 3-4 | fc, 1-4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 to 50 | -16.9 ± 7.8 (-2.2 SE) | +34.8 ± 6.8 (+5.1) | +21.1 ± 7.5 (+2.8) | +24.4 ± 6.2 (+3.9) | +9.5 ± 3.7 (+2.6) | -1.1 ± 2.9 (-0.4) |
| 50 to 200 | +17.3 ± 7.0 (+2.5 SE) | +7.5 ± 6.6 (+1.1) | +15.3 ± 7.2 (+2.1) | +18.5 ± 6.5 (+2.8) | +4.0 ± 3.5 (+1.1) | +4.0 ± 3.0 (+1.3) |
| 10 to 200 | +0.4 ± 7.7 (+0.0 SE) | +42.3 ± 7.0 (+6.1) | +36.5 ± 7.5 (+4.9) | +42.8 ± 6.5 (+6.6) | +13.5 ± 3.7 (+3.6) | +2.9 ± 3.0 (+1.0) |

### The verdict, by the plan's rule

- **Buckets help from 10 to 50**: M falls by 16.9 ± 7.8 bb/100, 2.2 paired SE (the bar is 2).
- **But M doesn't flatten from 50 to 200: it rises again**, by 17.3 ± 7.0 (2.5 SE), above the
  2 SE the rule allows. standard-k200's M is standard-k10's (+0.4 ± 7.7).

None of the four outcomes listed above fits: this is "help from 10 to 50, then worse from 50 to
200". (`analyse.py` prints it as "buckets help from 10 to 50; does not flatten".)

### Checks after the plan (not pre-registered)

Written after the k10 and k50 results, while standard-k200 trained (`after.sh`, `checks.py`):
the 10 to 50 fall was close to the bar, and at 20 big blinds one run's figure on seed 778 was
3 SE off its other two deal sets.

**A second deal set** (`b56_14`, seed 779, 100,000 hands, every run's final strategy):

| Buckets | Seed 778 | Seed 779 | Both (200,000 hands) |
| --- | ---: | ---: | ---: |
| 10 to 50 | -16.9 ± 7.8 (-2.2 SE) | -24.0 ± 7.7 (-3.1 SE) | -20.5 ± 5.5 (-3.7 SE) |
| 50 to 200 | +17.3 ± 7.0 (+2.5 SE) | +7.0 ± 7.0 (+1.0 SE) | +12.2 ± 5.0 (+2.5 SE) |
| 10 to 200 | +0.4 ± 7.7 (+0.0 SE) | -16.9 ± 7.6 (-2.2 SE) | -8.3 ± 5.4 (-1.5 SE) |

The fall from 10 to 50 repeats. The rise from 50 to 200 is smaller on seed 779 (1.0 SE), and
pooled it is 2.5 SE. From 10 to 200, pooled, M moves by -8.3 ± 5.4, which is not 2 SE.

**By seat** (`b56_14`; each deal is played twice, LBR once in each seat):

| Seed | LBR | k10 | k50 | k200 | 10 to 50 | 50 to 200 | 10 to 200 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 778 | on the button | 607.4 | 614.2 | 655.8 | +6.9 ± 11.4 | +41.5 ± 10.6 | +48.4 ± 11.5 |
| 778 | in the big blind | 577.8 | 537.1 | 530.1 | -40.8 ± 10.5 | -6.9 ± 9.2 | -47.7 ± 10.3 |
| 779 | on the button | 628.7 | 629.4 | 648.0 | +0.7 ± 11.4 | +18.6 ± 10.5 | +19.2 ± 11.3 |
| 779 | in the big blind | 582.4 | 533.8 | 529.3 | -48.6 ± 10.3 | -4.5 ± 9.1 | -53.1 ± 10.2 |

All of M's fall from 10 to 50 is with the blueprint on the button (LBR in the big blind): -41 and
-49 on the two seeds (3.9 and 4.7 SE), with nothing more from 50 to 200. With the blueprint in
the big blind, nothing changes from 10 to 50, and LBR wins more from 50 to 200 (+42 and +19).
This split isn't the same at 20 big blinds: there, from 10 to 200 buckets, LBR in the big blind
won more (+11.9 ± 2.1 on the standard menu, +12.9 ± 2.3 on the small one) and LBR on the button
about the same (+2.5 and +4.0) (the gate's final deals, seed 778).

**References** (`b56_14` on the final deals, seed 778, 100,000 hands): LBR wins 1,671.7 ± 10.9
bb/100 from always calling, 2,367.1 ± 18.9 from a random action and 1,719.7 ± 17.4 from a random
kind of action. The three blueprints give it 34% to 35% of what always calling gives it (33% to
40% at 20 big blinds).

### What it means

**Kevin's question: is the 20bb result the stack depth?** Partly. Deeper, the coarsest buckets
do show up in M, but the gain stops at 50 buckets, and the settings that stay near the menu get
more exploitable with every step, more than at 20 big blinds. That part is likely to carry into
Phase 6.

1. **What changed with the depth.** At 20 big blinds M rose from 10 to 50 buckets on the
   standard menu (+4.6 pooled over two deal sets, 4.5 SE). At 100 it falls (-20.5 ± 5.5
   pooled, 3.7 SE), all of it with the blueprint on the button. So 10 buckets a street are too
   coarse at 100 big blinds in a way LBR can see.
2. **What didn't.** From 50 to 200 buckets M doesn't fall (pooled +12.2 ± 5.0), and from 10 to
   200 it moves by -8.3 ± 5.4 (1.5 SE). LBR shows no gain from Phase 6's 200 buckets over 50.
3. **Near the menu, more buckets are more exploitable, at every step.** From 10 to 200 buckets
   (seed 778): `fcpa14` +36.5 (4.9 SE), `fcpa34` +42.8 (6.6 SE), `b56_34` +42.3 (6.1 SE),
   `fc34` +13.5 (3.6 SE); only `fc14`, which never bets, doesn't move (+2.9 ± 3.0). These
   exploiters stay close to the menu: with `fcpa14` 1.5% to 1.7% of the blueprint's decisions
   are off the tree. At 20 big blinds the same settings moved by -1.7 to +6.5 (at most 2.7 SE).
   So it isn't only the bet translation, which the plan's outcome 3 named as the other
   possibility: the finer strategies lose more even where LBR plays the menu's own bets.
4. **It isn't that standard-k200 trained less.** It met the same stop rule (change 0.073, LBR
   flat), and no run's LBR fell by more than the noise as it trained: `fcpa34` was already
   159.5 against standard-k200 at 4M iterations, against 101.7 for standard-k10 at 4M.
   Training on would not close the gap; at 20 big blinds it didn't (`experiments.md`, the
   gate, check 3).
   standard-k200 had 18 iterations per information set against 43 for standard-k10, and that
   remains a difference between them.

Why finer buckets are more exploitable here is not tested. The gate's three candidates stand:
abstraction pathologies (Waugh et al. 2009), imperfect recall (each street clustered on its
own), and finer strategies fitting the abstract betting more closely (Johanson et al. 2011).

**For Phase 6** (200 big blinds, 200 buckets a street): don't count on LBR, as measured here, to
show that 200 buckets are worth their cost (at 100 big blinds, 4 times the information sets
of 50, 2.8 times the memory and 2.4 times the training time). Check the card abstraction
another way first, for example standard-k50 against standard-k200 head to head at 100 big
blinds in the arena (both are `Strategy` agents; not done here).

## Files

| File | What |
| --- | --- |
| `README.md`, `plan.json` | The plan (committed before training), then the results |
| `analyse.py`, `results.md` | The plan's tables and verdict, and its output |
| `after.sh`, `checks.py`, `checks.md` | The checks after the plan (not pre-registered), and their output |
| `run/` | The plan's logs: `out.log`, `err.log`, and per run `spec.json`, `stages.jsonl`, `progress.jsonl` (each doubling's stop decision), `lbr.jsonl` (stage readings), `final.jsonl`, `log.jsonl` (training sessions), `done.json` |
| `run/deals.tar.xz` | The per-deal results of the final LBR (seed 778) |
| `after/` | `after.log`, `seed779.jsonl`, `references.jsonl`, and their per-deal results in `deals.tar.xz` |
| `pack.sh` | How these files were copied here and packed |

`plan.json` is ignored by `.gitignore` (`docs/research/runs/*/*.json`) and was added with
`git add -f`. The per-deal results are kept because training on 4 lock-free threads doesn't
repeat exactly, so they could not be rebuilt from the plan. To rebuild the tables:

```bash
cd docs/research/runs/phase5_100bb
(cd run && tar -xJf deals.tar.xz) && (cd after && tar -xJf deals.tar.xz)
python analyse.py run
python checks.py run after
```
