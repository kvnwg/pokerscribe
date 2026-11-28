# The Phase 6 calibration run: what happened (27 Nov 2026)

Raw material for the experiments.md entry, gathered by the manager session from the calibration
session's reports from Kevin's Mac. Times UTC, from `watch` ages (about ±2 minutes).

## The run

- Launched about 19:32 (second attempt; the first, after the stale Cargo.lock, billed an
  unreported boot of 52 min, $1.29, counted in the run's cost). BUDGET_USD=5 (Kevin), inside his
  $10 calibration approval. c4a-highcpu-64 Spot, us-central1-a, 80 GB Hyperdisk Balanced at
  3,000 IOPS and 400 MiB/s; $1.4714 an hour (machine $1.4459, IP $0.0025, disk $0.0230).
  GCE's hard stop at 2h31m20s.
- 16M at 7 min (watch: 47,036 a second, a reading diluted by the stage pauses, the supervisor's
  rate being taken between the trainer's session lines); 128M at about 21 min (141,821); 256M at
  about 34 min (153,705); 1,024M at about 1h47m (176,662).
- The budget stop: requested 21:51, status written 21:51:56; the trainer exited 75 (STOPPED,
  saved on SIGTERM) at 1,330,975,013 iterations, last speed 183,096 a second (the trainer's own:
  182,020). Cost $4.67 (machine $4.56, IP $0.01, disk $0.10, incl. the $1.29 boot). recover
  logged one "wait" line a minute and exited at 21:52 with "finished: the run is budget". No
  preemption, 0 restarts, 0 crashes. Trainer memory 7.5 GB (peak 9.8 GB) of 134.8 GB.
- Artifacts: 13 files, 5.5 GB, each strategy file 503.4 MB; checkpoint 4.9 GB (3 kept in the
  bucket). After `cleanup`, leftovers: the bucket only, 20.28 GB, about $0.41 a month.

## The tables and the build on Kevin's Mac

`abstraction-build check ~/abstraction/k200`: 19 checks, 0 failed; checksums flop
7e143f5b92504f9b, turn e8f2df9a3d04e8b8, river e7ff8e349b9587b6 (the runbook's). blueprint
(cargo --locked) and pokerscribe_engine rebuilt from main.

## The evaluations

1. All 11 files (summary-1.02G.md, verbatim). The stop rule first says stop at it512M.
2. The manager's reading of the pre-registration (README "The gate", Checkpoints row): the gate's
   last file is it512M; it1.02G is reported only; no full run (the stop rule ended the run).
3. Files 1M to 512M, `--out ~/phase6/eval512 --b0 last --b0-deals 4000 --b0-seed 6201`: every
   LBR figure (both settings, 10 files), every pairwise LBR difference and every consecutive head
   to head repeated summary-1.02G.md exactly (only Hands/s differ). New: it512M against it1M
   +147.68 ± 3.89 (z +37.99). LBR last minus first: fcpa14 -235.3 ± 39.6 (z -5.95), b56_14
   +54.2 ± 41.4 (z +1.31). B0 sizing (not judged): +12.9 ± 12.7 bb/100, z +1.02, 8,000 hands,
   sd 801 a deal, 64.7 hands/s; saved as summary-sizing.md on Kevin's Mac.
4. The gate's B0 match: N = (2.5 × 801 / 10)² = 40,100, rounded up to 41,000 deals, seeds 7201
   on, same `--out`: "B0 against it512M: blueprint +16.3 +- 4.1 bb/100 over 82000 hands; sd 825
   a deal". The match's sd (825) would have sized N at 43,000; N is fixed from the sizing sd as
   registered. Not pooled with the sizing match.

The gate's summary section (verbatim):

    ## B0 heads-up

    | File | Blueprint wins, bb/100 | SE | z | Hands | sd a deal | Hands for 2.5 SE at 5 / 10 / 20 bb/100 | At the edge measured | Hands/s, all processes |
    | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
    | it512M | +16.3 | 4.1 | +4.00 | 82,000 | 825 | 340,646 / 85,162 / 21,292 | 32,066 | 67.3 |

    ## The gate

    - Head to head, the last file against the first: it512M against it1M, +147.68 +- 3.89 bb/100, z +37.99: passes
    - B0 heads-up: it512M +16.3 +- 4.1 bb/100, z +4.00: passes
    - The gate: passes
    - Reported: LBR fcpa14 from +391.0 to +155.7 bb/100, last minus first -235.3 +- 39.6 (z -5.95); from one file to the next, 9 steps: it fell at 5, by 2.5 SE at 1, and rose by 2.5 SE at 0
    - Reported: LBR b56_14 from +436.1 to +490.3 bb/100, last minus first +54.2 +- 41.4 (z +1.31); from one file to the next, 9 steps: it fell at 4, by 2.5 SE at 0, and rose by 2.5 SE at 0

## The incident: a false "no report"

At 78 minutes one `watch` printed no status lines and "WARNING no report from the machine for 78
min"; a minute later `gcloud storage ls -l` showed status.json written at 21:30:01Z and the next
watch was normal. Cause: GcsStore.get_bytes returned None (a failed `gcloud storage cat` matching
_NOT_FOUND, or bad JSON), and the tools took a missing status as "never reported this boot".
recover's stop-silent (PR #45) used the same reading, so one bad read could have stopped a healthy
machine; it didn't in about 140 polls. Fixed in PR #46 (a17b879): a failed read is "unknown",
stop-silent needs 3 agreeing looks a poll apart, stop() waits for the save when the report is
unknown, and leftovers prices each disk's provisioned IOPS and throughput (it showed the stopped
disk at $6.40 a month; Google bills $16.80 at 400 MiB/s).

## Side test: huge pages (huge-pages.md)

The trainer 1.145 times as fast with GLIBC_TUNABLES=glibc.malloc.hugetlb=1 (ABBA, 4 threads, to
4M, in a cloud container). Not used for the heads-up run; kept for six-max.
