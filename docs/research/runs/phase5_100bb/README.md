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
