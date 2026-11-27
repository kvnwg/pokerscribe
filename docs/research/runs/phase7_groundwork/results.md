# Phase 7 groundwork: results

The runs of `README.md` (committed before they started, in 2d9a22a), on 27 Nov 2026, on this
machine (4 cores, Intel Xeon at 2.1 GHz). Groundwork, not the Phase 7 gate: nothing here passes
or fails. Raw outputs: the JSON files and `log.txt` next to this file (the `.deals` files of the
LBR runs are not kept in the repository; `search compare` read them).

What changed after the plan was committed, none of it in how any agent plays:

- After the timing runs (4) the binary was rebuilt with two additions to what it reports: the
  LBR command counts the search agent's solves and re-solves, and the trees command counts the
  abstract game's turn starts and decision points by street. The rebuilt binary repeats the
  `b56_14` pilot (seed 9105) exactly, deals file for deals file.
- The tree sizes were also counted for the `rich` menu at 200 big blinds (the Phase 6 game),
  since the plan's `trees` runs use the standard menu. After the flop the two menus are the
  same, so the street trees are too; the abstract game, and so the leaf tables, are not.
- The Python test `test_solver_keeps_to_its_time_budget` (a wall-clock budget of 80 ms for the
  Python river solver) was run with the runs below paused for a few seconds (`kill -STOP`): it
  fails while the four cores are busy. Pausing changes no result here: no solve has a time
  limit.

H2H

LBR

## Timing (4)

`search bench`, 150 hands against the blueprint (seed 7104), 4 threads, an idle machine. A
decision is the whole call (ranges, solves, the answer); a later decision on a street that
reuses the street's solve takes well under a millisecond. Exploitability is the solve's own
(on the flop, against the leaf values), as a share of the pot.

| Street | Decisions | Decision p50 | p95 | Max | Solves | Solve p50 | p95 | Iterations (mean) | Exploitability (mean) | Combos a player (mean) | Solver nodes (mean) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Preflop | 161 | 0 ms | 0 ms | 0 ms | 0 | | | | | | |
| Flop | 126 | 480 ms | 752 ms | 1,044 ms | 101 | 552 ms | 780 ms | 46.1 | 0.88% | 960 | 76 |
| Turn | 61 | 2,228 ms | 6,021 ms | 6,677 ms | 56 | 2,400 ms | 6,020 ms | 54.7 | 1.76% | 828 | 8,980 |
| River | 42 | 39 ms | 158 ms | 206 ms | 37 | 64 ms | 158 ms | 71.4 | 0.45% | 693 | 56 |

Before the flop the search agent plays the blueprint. 220 s for the 150 hands: 1.5 s a hand for
the search agent's decisions. No re-solve happened: the blueprint only bets sizes of its own
menu, which are always in the search's tree. Re-solves come from LBR and B0 (below).

### Threads (`search scale`, seed 7105)

The same solves (6 flops and 6 turns from 40 hands) again from scratch on 1, 2 and 4 threads.

| Street | Solver nodes | Iterations | 1 thread | 2 threads | 4 threads | Speed-up on 4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Flop | 69 | 32 | 846 ms | 489 ms | 363 ms | 2.33 |
| Flop | 69 | 45 | 962 ms | 635 ms | 407 ms | 2.37 |
| Flop | 69 | 45 | 1,065 ms | 652 ms | 391 ms | 2.72 |
| Flop | 81 | 50 | 1,634 ms | 962 ms | 591 ms | 2.77 |
| Flop | 81 | 56 | 1,628 ms | 1,014 ms | 633 ms | 2.57 |
| Flop | 81 | 56 | 1,774 ms | 954 ms | 594 ms | 2.99 |
| Turn | 8,277 | 50 | 6,771 ms | 3,754 ms | 2,027 ms | 3.34 |
| Turn | 12,705 | 63 | 14,772 ms | 8,580 ms | 4,553 ms | 3.24 |
| Turn | 12,705 | 78 | 17,334 ms | 9,590 ms | 5,255 ms | 3.30 |
| Turn | 8,277 | 56 | 7,358 ms | 4,607 ms | 2,631 ms | 2.80 |
| Turn | 8,277 | 50 | 6,484 ms | 3,473 ms | 2,017 ms | 3.21 |
| Turn | 12,705 | 87 | 20,169 ms | 11,478 ms | 6,798 ms | 2.97 |

On one thread a turn solve costs 0.0100 to 0.0110 microseconds per solver node, iteration and
combo (both players' combos added), on all six: time is that product. A flop solve costs about
0.19 microseconds for the same product (the leaves, not the 69 to 81 nodes, are the work).
Amdahl's law fitted to the 4 thread speed-ups (median): 8% of a turn solve and 17% of a flop
solve run on one thread.

### Tree sizes (`search trees`)

The flop's street tree, the turn's subgame (every river card, with the turn solve's river menu)
and the river's subgame, from three preflop lines, after the flop checks through and after a bet
of three quarters of the pot is called:

| Stack | Line | Flop nodes (decisions, leaves) | Turn subgame nodes | River subgame nodes |
| --- | --- | --- | --- | --- |
| 20bb | limped | 81 (28, 13) | 12,705; 8,277 | 81; 69 |
| 20bb | raised to 2.5 | 69 (24, 11) | 8,277; 3,057 | 69; 33 |
| 20bb | 3-bet to 7.5 | 33 (12, 5) | 3,057; 537 | 33; 9 |
| 200bb | all three | 81 (28, 13) | 13,857 (11,553 after the 3-bet and a bet) | 81 |

At 20 big blinds the stacks cut the menu short in most pots; at 200 every line has the full
menu. The abstract game (the blueprint's tree, which the leaf tables follow):

| Game | Abstract nodes | Preflop, flop, turn, river | Turn starts (leaf tables) | Leaf tables at 200 buckets |
| --- | ---: | --- | ---: | ---: |
| 20bb, standard | 5,504 | 60, 324, 1,260, 3,860 | 133 | 0.15 GB |
| 200bb, standard | 63,956 | 88, 1,140, 9,204, 53,524 | 527 | 0.59 GB |
| 200bb, rich (Phase 6) | 486,120 | 2,116, 19,452, 97,356, 367,196 | 8,669 | 9.7 GB |

### 200 big blinds on a 64 core machine (an estimate)

The method of the plan: time scales with solver nodes times combos times iterations (the
turn's constant above shows it does), the speed-up on 64 cores is Amdahl's law with the serial
shares above (a turn solve splits over its 48 river cards, so 48 threads at most), and an Axion
core is taken to be as fast as one here (not measured: no Arm machine here).

- **Turn**: 13,857 nodes against 8,980 here on average (1.5 times), both players' combos about
  2,000 against 1,656, iterations as here (55 at the mean, 87 at the slowest of the six) or
  twice that if deeper stacks converge slower: one thread 15 to 31 s at the mean; Amdahl's
  speed-up on 48 threads with 8% serial is 10; so **about 1.5 to 3 s a turn solve, 2.5 to 5 s
  at the slow end**.
- **Flop**: the same 81 node tree; 2,000 combos, 56 to 110 iterations: one thread 1.7 to 3.4 s;
  the speed-up stops near 5.4 (17% serial); so **about 0.3 to 0.6 s**, no faster than 4 threads
  here by much. The flop's serial share (the leaf lookups by bucket, the equity table) is the
  first thing to parallelize.
- **River**: 81 nodes, under 0.3 s.
- **Leaf tables**: 8,669 turn starts and 53.6 turn and river nodes under each (38.5 at 20bb):
  per deal 91 times the walk of the 20bb build, which took 1,332 s on 4 cores (1.5 core-hours)
  for 16M deals. At 16M deals: about 134 core-hours, **about 2 hours on 64 cores**, and 9.7 GB
  of tables to hold in memory. Fewer deals or fewer flop buckets for the tables would cut both.

Decisions after the flop at 200bb would take about 0.5 s on the flop, 2 to 5 s on the turn and
well under a second on the river. For scale: Pluribus's searches took 1 to 33 s each on 28
cores (about 20 s a hand in six-max, Brown and Sandholm 2019).

## Range check (5)

`search ranges`, 300 hands against the blueprint (seed 7106). At every decision of the search
agent after the flop, for each player: whether the real hand has weight in the range the search
worked out, whether it is in the solve (not left out as under 0.1% of the largest weight), and
the share of the range's weight on combos lighter than the real hand (about 0.5 for a hand that
is a typical member of its range, near 0 for one the range barely holds).

| Street | Decisions | Opponent's hand in range | In the solve | Weight below it | Own hand in range | In the solve | Weight below it |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Flop | 210 | 100% | 100% | 0.55 | 100% | 100% | 0.48 |
| Turn | 120 | 100% | 100% | 0.53 | 100% | 100% | 0.47 |
| River | 85 | 100% | 100% | 0.53 | 100% | 100% | 0.49 |

Against the blueprint this is what the method promises: the opponent's range is updated with the
blueprint's own probabilities, so its real hand can't drop out, and the search agent's own range
with the strategy it played. Against an opponent that is not the blueprint (LBR, B0, a human)
its hand can get weight 0; that was not measured here.

## B0 (6)

`python tools/b0_arena.py <agent> --stack-bb 20 --deals 100 --seed 7107`: B0 from Python,
through `pokerscribe_engine.run_match`, each deal twice with the seats swapped, all-in hands
scored by equity. The same 100 deals for both.

| B0 against | B0's bb/100 | SE | The agent's bb/100 | B0's instructions | Not legal as said | Always wrong | Time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `search:<file>` | -4.70 | 22.08 | +4.70 | 403 | 0 | 0 | 532 s (2.7 s a hand) |
| `blueprint:<file>` | +11.78 | 18.25 | -11.78 | 397 | 0 | 0 | 14 s |

The search agent plays end to end from Python: 200 hands, every action legal. B0 sizes its bets
its own way, and a size off the search's menu is added to the street's tree (how often was not
counted in this run). 200 hands say nothing about who is better (the report has
no per-deal results, so no paired SE; unpaired, the two differ by 16.5 ± 28.6). In a match the
search agent's turn solves run on one thread (`turn_threads` 1), so here each hand cost more
than in the bench.
