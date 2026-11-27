# Phase 5 gate: the plan, written before the run

The gate (`docs/research/README.md`, Phase 5): "LBR win rate falls as buckets and sizes are
added, then flattens". This file was written before the gate run started; `plan.json` is the
plan the run used, unchanged. (`plan.json` was written at 02:24:27 UTC on 27 Nov 2026, 12 seconds
before the gate started, but the repository's `.gitignore` leaves out `runs/*/*.json`, so it
missed the commit that registered this plan and was added with the results. `gate/plan.json` is
the copy the gate wrote when it started: the same plan.) The results are in `engine/crates/blueprint/README.md` and
`docs/research/experiments.md` (Phase 5: the gate).

## What was decided from the pilots, and why

Two pilots on small-k50 (the small menu, 50 buckets per street, OCHS on the river), on this
machine (4 cores, Intel Xeon at 2.1 GHz, 16 GB):

- **Stack: 20 big blinds.** The standard menu with 200 buckets has 1.1M information sets
  there, small enough to train to a flat LBR in about an hour on 4 cores, and after an open
  and a call the stack is still 3.5 times the pot, so postflop bet sizes matter. At 100 big
  blinds the same game has many times more decision points (`blueprint size`).
- **LBR setting for the stages: "56 bets, rounds 1-4" (`b56_14`).** It is the strongest in
  the first pilot (111.5 ± 4.2 bb/100 against 75.6 for `b56_34`, 7.7 for `fcpa14`, -4.6 for
  `fc14`, -46.1 for `fc34`), so it is the paper's "max over settings" in practice. `fcpa34`
  is measured with it at every stage as a second view.
- **LBR rises as the strategy converges.** On small-k50, `b56_14` went 122.4, 130.0, 131.1,
  131.6, 131.1, 132.3 bb/100 at 2M to 64M iterations (linear weighting), and 115.3, 121.0,
  126.6 at 2M, 4M, 8M without it; `fcpa34` drifted up too. The coarse abstraction's
  equilibrium is more exploitable in the real game than strategies on the way to it (as
  Johanson et al. 2011 found for abstract CFR strategies). So "lower LBR" at equal iterations
  can just mean "less converged", and the stop rule looks at movement both ways.
- **Linear weighting on** (discount every 200k iterations until 20M, then plain), as Pluribus
  did: without it the same strategy is reached more slowly (the plain run's LBR was still
  rising at 8M, where the linear run's had flattened at 4M to 8M).
- **Convergence, judged two ways.** A run stops after the first doubling that meets both:
  1. LBR flat: `b56_14` (50,000 hands, seed 777, the same deals at every stage) moved by
     less than max(3% of its level, 2 paired standard errors) over the doubling;
  2. play settled: the average strategy changed by at most 8% over the doubling (the
     share of play that changed, each information set weighted by how often it is reached,
     `StrategyFile::change_from`). On small-k50 this was 0.099, 0.085, 0.077, 0.065, 0.050
     at 4M to 64M, so 0.08 is met at 16M, where LBR is flat as well.

  Equal time or equal iterations would favour the small games; the change measure puts every
  setting at about the same distance from its own limit. Cap: 1,024M iterations.
- **Stages** start at 4M and double. Threads: 4. Training seed 1. No pruning.

## The runs

20 big blinds, blinds 50/100, in this order:

| Run | Menu | Tables (flop, turn, river buckets) | River feature |
| --- | --- | --- | --- |
| small-k10 | small | k10 (10, 10, 10) | OCHS, 8 clusters |
| small-k50 | small | k50 (50, 50, 50) | OCHS |
| small-k50eq | small | k50eq (50, 50, 50) | equity |
| small-k200 | small | k200 (200, 200, 200) | OCHS |
| standard-k10 | standard | k10 | OCHS |
| standard-k50 | standard | k50 | OCHS |
| standard-k50eq | standard | k50eq | equity |
| standard-k200 | standard | k200 | OCHS |

Menus (`abstract_game::Menus`): small has opens of 2.5 times and all in, 3-bets of 3 times
and all in, and after the flop bets of a half and a whole pot and all in, then a pot raise
or all in. Standard has three opens, two 3-bets and two 4-bets, and after the flop bets of a
third, three quarters and one and a half pots and all in, then three quarters or all in.

The tables were built with `abstraction-build build --out ~/abstraction/k<B> --buckets <B>`
(and `--river-feature equity` for k50eq).

## The final measurement

Each run's last stage: LBR with `b56_14`, `b56_34`, `fcpa14`, `fcpa34` and `fc34`, 100,000
hands, seed 778 (the same deals for every run, so differences are paired). `fc14` is left out:
it is 30 times slower than the others and was the weakest in the pilot. Then the same five
with bets under the smallest menu size read as a check or call (`SmallBets::CheckOrCall`)
instead of as the smallest size. References on the same deals: always call, random action,
random kind of action (`blueprint reference`).

## How the gate is judged

For each run, M is the largest of the five final LBR results (the paper's rule), with the
default reading of small bets. A difference between two runs has a paired standard error
when both maxima come from the same setting, else sqrt(se1² + se2²).

1. **Sizes help:** M(standard) < M(small) by more than 2 SE, at each of 10, 50 and 200
   buckets.
2. **Buckets help:** M(k50) < M(k10) by more than 2 SE, for each menu.
3. **Then it flattens:** for each menu, the drop from 50 to 200 buckets is smaller than the
   drop from 10 to 50, and M(k200) is not above M(k50) by more than 2 SE.

The gate passes if all three hold.

**OCHS against equity on the river** (k50 against k50eq, both menus): OCHS is picked for
Phase 6 if it is lower by more than 2 paired SE on both menus, equity if equity is; if
neither, the evidence does not separate them and Phase 6 keeps OCHS, the choice in the
literature (Johanson et al. 2013), since both cost the same to train.

**Reading of small bets:** reported for every run as a paired difference. Whether Phase 6
should read small bets as checks or calls is judged on the same 2 SE rule over the runs.

**B0:** one short match, the last run's blueprint against B0 in the arena at 20 big blinds,
to show the path works end to end. Its result is not evidence of anything.
