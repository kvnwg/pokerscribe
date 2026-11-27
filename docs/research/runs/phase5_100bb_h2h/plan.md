# Phase 5 check: standard-k50 against standard-k200 head to head at 100 big blinds (the plan)

Informational, not a gate run. A follow-up to the 100bb bucket check
(`../phase5_100bb/README.md`; `experiments.md`, "Phase 5 check: buckets at 100 big blinds"):
there, LBR went against 200 buckets over 50 (M +12.2 ± 5.0 bb/100 pooled over two deal sets,
`fcpa34` +18.5 ± 6.5). LBR measures the worst case. This measures play: the two blueprints
against each other. Phase 6's gate doesn't change whatever this shows; it only tells Kevin
whether 200 buckets over 50 are worth checking before Phase 6's full run.

This file, `plan.json`, `run.py` and `report.py` were committed and pushed before the main
run. Only the pilot below was run before them.

## The question

At 100 big blinds, does standard-k200 beat standard-k50 head to head?

## The setup

- **The strategy files** are the 100bb check's final ones, unchanged (sha256 in `plan.json`):
  standard-k50 at 64M iterations and standard-k200 at 128M (and standard-k10 at 16M for the
  optional checks). Heads-up, 100 big blinds (blinds 50/100, 10,000 chips), the standard menu,
  OCHS on the river, trained to the gate's stop rule.
- **The arena** (`pokerscribe_engine.run_match`, built from main 4f40e1f), with the settings the
  arena uses by default: duplicate deals, each played twice with the seats swapped; the all-in
  equity adjustment (a hand all in before the river is scored by its equity, over at most
  10,000 boards); no shared randomness; 4 threads. Both blueprints have the standard menu, so
  every bet one makes is on the other's tree.
- **The SE** is the arena's: one sample per deal, the average of its two hands.

## The pilot (run before this plan, its seeds not used again)

20,000 deals each (`pilot.py`, `pilot.jsonl`): standard-k200 against standard-k50 on seed 9101,
standard-k50 against standard-k10 on seed 9102. Only the speed and the sd of a deal were used to
size the run: an sd of 688 and 702 bb/100 a deal, and 320,000 to 400,000 hands a second. (For
the record, the pilot's results were +0.8 ± 4.9 and +14.9 ± 5.0; they are not part of any
result below.)

## The matches and their size

| Match | Second against first | Seed | Deals | Role |
| --- | --- | ---: | ---: | --- |
| main | standard-k200 against standard-k50 | 9201 | 2,000,000 | the decision |
| replication | standard-k200 against standard-k50 | 9202 | 2,000,000 | the same match on fresh deals, reported next to it |
| sanity | standard-k50 against standard-k10 | 9301 | 2,000,000 | optional sanity check: does the arena see the 10 to 50 gain LBR saw? |
| k10-k200 | standard-k200 against standard-k10 | 9401 | 2,000,000 | information, no decision |

At the pilot's sd, 2,000,000 deals give an SE of about 0.5 bb/100 (the brief asked for about 3
or less in about 3 hours), and at its speed each match takes under a minute. The optional
matches cost under 30 minutes in all.

## The decision rule (the manager's, on the main match)

- **standard-k200 ahead by 2.5 SE or more**: the extra buckets pay off in play.
- **standard-k50 ahead by 2.5 SE or more**: flag it to the manager before Phase 6's full run.
- **Anything else**: inconclusive.

With an SE of about 0.5, an edge of about 1.3 bb/100 passes. An edge under 2 bb/100 that passes
is reported as passing and small. The replication is reported next to the main match; if it
doesn't give the same call, that is said. The sanity check reads the same way: standard-k50
ahead of standard-k10 by 2.5 SE means the arena sees the 10 to 50 gain.

## What is reported

`report.py` here, written with this plan, prints for every match: the second run's result
against the first in bb/100 with its SE and z, the same in real chips (before the all-in
adjustment), each seat separately (the second run on the button, and in the big blind), the
hands the all-in adjustment changed, illegal actions (there should be none) and the wall time;
then the decision, the replication's call, and the sanity check's.

## How to run it

```bash
python -m pip install ./engine/crates/py
python docs/research/runs/phase5_100bb_h2h/run.py docs/research/runs/phase5_100bb_h2h/plan.json results.jsonl
python docs/research/runs/phase5_100bb_h2h/report.py docs/research/runs/phase5_100bb_h2h/plan.json results.jsonl --md results.md
```

`plan.json` is ignored by `.gitignore` (`docs/research/runs/*/*.json`) and was added with
`git add -f`. The engine module was built from main 4f40e1f; main e1e34a5, this plan's base, has
the same engine code.

The strategy files are not in the repository (2 to 38 MB each, and the bucket tables they need
are rebuilt by `abstraction-build`); `run.py` checks their sha256 before it plays.
