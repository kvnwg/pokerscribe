# Phase 7 groundwork: the plan, written before the runs

Depth-limited search (`engine/crates/search`) on a 20 big blind Phase 5 blueprint, on this
machine (4 cores, Intel Xeon at 2.1 GHz, 16 GB). This is groundwork, not the Phase 7 gate: the
gate ("beats blueprint by 2.5 SE; luck-adjusted Slumbot match; GTO Wizard Benchmark",
`docs/research/README.md`) is for the Phase 6 blueprint at 200 big blinds. Nothing here passes
or fails; the numbers say whether the search works and what it costs. This file was written and
committed before any of the runs below started. Results go to `results.md` next to it, to
`engine/crates/search/README.md` and to `docs/research/experiments.md` ("Phase 7 groundwork").
Everything is offline, against our own agents (rule 4).

## What is measured with what

- **Blueprint**: standard-k200, retrained here with the Phase 5 gate's spec (standard menu,
  200 buckets a street, OCHS river, 20 big blinds, training seed 1, 4 threads, linear weighting
  to 20M, 64M iterations): `/root/bp/standard-k200/strategy-64000000.bps`, 1,267 s of
  training. Bucket tables built here with `abstraction-build build --out /root/abstraction/k200
  --buckets 200`.
- **Leaf tables**: `search leaf`, 16,000,000 deals, seed 7, bias 5, prior 3 deals
  (`strategy-64000000.bps.leaf`).
- **Search settings**: the crate's defaults (`search::Settings::default()`), fixed before the
  pilots below and not changed after:
  - flop: depth-limited, Discounted CFR to 1% of the pot or 400 iterations;
  - turn: subgame to 2% or 300 iterations, every river card, the river inside the turn solve
    with a bet of three quarters of the pot or all in, then all in;
  - river: subgame to 0.5% or 1,000 iterations, the blueprint's menu;
  - combos under 0.1% of the largest weight of their range left out of a solve (the blueprint
    plays a hand that is left out);
  - no time limits (a solve depends only on the public state, so every run repeats).
- **Blueprint agent**: the same strategy file through `blueprint::Blueprint` (translation seed
  0, small bets read as the smallest size).

## Pilots (before this file; their seeds are not used below)

On 27 Nov 2026, with the settings above, to size the runs (none of these seeds is used
below):

- Turn settings (`search bench`, 24 hands, seed 5, 4 threads, only 4 turn solves each, so
  rough): turn solve p50 and p95 with the river inside the turn solve at three quarters of the
  pot or all in, to 1% of the pot: 6.3 s and 16.5 s (8,322 solver nodes on average); with all
  in only on that river, to 1%: 4.3 s and 7.5 s (5,154 nodes); the same to 2%: 2.8 s and 4.2 s;
  three quarters of the pot or all in, to 2%, leaving out combos under 1%: 4.7 s and 10.6 s.
  Chosen: three quarters of the pot or all in, to 2%, leaving out combos under 0.1% (not timed
  as such before this file). The river is solved again with the full menu when it comes, so the
  river inside the turn solve only has to give the turn sensible values; a bet size keeps more
  of the river's play than all in only, and 1% would make the match below too slow for a day.
- Head-to-head, 128 deals (seed 9104): 559 s on 4 threads, 4.7 thread-seconds a hand
  (search -1.4 ± 21.6 bb/100: no information at this size). The SE per deal is about 244
  bb/100, so 3,000 deals give about 4.5 bb/100.
- LBR against search: `fcpa14`, 16 hands in 40 s (seed 9102); `b56_14`, 8 hands in 46 s and
  32 hands in 94 s (seeds 9103, 9105). Both about 3 s a hand on 4 cores, so 1,500 hands each
  fit in about 1.2 hours.

## The runs

All at 2,000 chips, blinds 50 and 100.

| # | What | Command (in `engine/`, `S=/root/bp/standard-k200/strategy-64000000.bps`) | Seed |
| --- | --- | --- | --- |
| 1 | Head-to-head, search against the blueprint, 3,000 deals (6,000 hands) | `search match --strategy $S --deals 3000 --seed 7101 --threads 4 --out h2h.json` | 7101 |
| 2 | LBR `fcpa14`, 1,500 hands, against each agent (same deals) | `search lbr --strategy $S --agent blueprint\|search --setting fcpa14 --hands 1500 --seed 7102 --out <agent>-fcpa14.deals` | 7102 |
| 3 | LBR `b56_14`, 1,500 hands, against each agent (same deals) | `search lbr ... --setting b56_14 --hands 1500 --seed 7103` | 7103 |
| 4 | Timing: 150 hands against the blueprint, 4 threads; the same solves on 1, 2, 4 threads (6 flops and 6 turns); tree sizes at 20 and 200 big blinds | `search bench --hands 150 --seed 7104`, `search scale --hands 40 --seed 7105 --spots 6`, `search trees --stack-bb 20\|200` | 7104, 7105 |
| 5 | Range check, 300 hands against the blueprint | `search ranges --hands 300 --seed 7106` | 7106 |
| 6 | B0 against search and against the blueprint, 100 deals each | `python tools/b0_arena.py search:$S --stack-bb 20 --deals 100 --seed 7107` (and `blueprint:$S`) | 7107 |

They run one after another in the order 4, 5, 6, 1, 2, 3 (the timing first, on an idle
machine), from `run.sh` in this directory. The samples are fixed: no run is stopped early or
extended on its result.

## How each is read

- **Head-to-head (1)**: search's bb/100 against the blueprint with its standard error per deal
  (each deal played twice, seats swapped, all-in hands scored by equity). Reported with its z.
  At the Phase 7 gate the bar is 2.5 SE; here it is reported, not judged.
- **LBR (2, 3)**: what LBR wins against each agent, and search minus blueprint deal by deal
  (`Deals::minus`, the paired SE). Lower is better for the agent. `b56_14` is the stronger
  exploiter (Phase 5: +112.3 ± 1.9 against standard-k200, `fcpa14` +3.5 ± 2.0) but costs one
  re-solve per LBR bet size, so it gets the smaller sample, as said in the brief.
- **Timing (4)**: decision time (the whole `action_probs` call, ranges and solves included) and
  solve time, p50 and p95 per street, on 4 threads. Then the same flop and turn solves on 1, 2
  and 4 threads (`search scale`) and the tree sizes at 20 and 200 big blinds (`search trees`)
  for the 200bb, 64-core estimate. The estimate's method: time scales with solver nodes times
  combos times iterations; the 64-core speed-up is extrapolated from the 1, 2 and 4 thread
  times (a turn solve parallelizes over its 48 river cards, so no more than 48 threads help
  it); per-core speed taken as this machine's.
- **Range check (5)**: at every decision of the search agent after the flop, against the
  blueprint, whether each player's real hand has weight in the range the search works out, and
  whether it is in the solve (not pruned). Also the share of the range's weight on combos
  lighter than the real hand (0.5 would mean the real hand is a typical member).
- **B0 (6)**: `tools/b0_arena.py`, B0 against search, and against the blueprint on the same
  deals, to show the search plays end to end from Python. Short: no conclusion is drawn.

## Added after runs 1 to 6: LBR again on fresh seeds (written before it ran)

Runs 2 and 3 took 10 and 13 minutes for the search agent, not the 75 the pilots suggested (the
pilots' few hands were mostly the slow first solves of each flop), and gave search minus
blueprint -27.9 ± 11.8 (`fcpa14`) and -42.5 ± 12.2 (`b56_14`). Following the project's rule that
a result must repeat on fresh seeds, LBR is run again, four times as many hands, on seeds not
used before:

| # | What | Command | Seed |
| --- | --- | --- | --- |
| 7 | LBR `fcpa14`, 6,000 hands, against each agent (same deals) | `search lbr --strategy $S --agent blueprint\|search --setting fcpa14 --hands 6000 --seed 7201` | 7201 |
| 8 | LBR `b56_14`, 6,000 hands, against each agent (same deals) | `search lbr ... --setting b56_14 --hands 6000 --seed 7202` | 7202 |

Read as runs 2 and 3. The result repeats if search minus blueprint is negative on the new seeds
for the same setting; the two seeds' results are also pooled (weighted by hands) for the
estimate. The samples are fixed; `run-repeat.sh` in this directory runs them.
