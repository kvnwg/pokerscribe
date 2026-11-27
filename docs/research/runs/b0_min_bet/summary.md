# B0: bets under the minimum, before and after the fix

`simulate.check_advice` on the main tables, six-max and heads-up, on the commit before the fix
(cac3c4c) and on the fix. Run on 27 Nov 2026:

```
python docs/research/runs/b0_min_bet.py run BEFORE    # on cac3c4c
python docs/research/runs/b0_min_bet.py run AFTER     # on the fix
python docs/research/runs/b0_min_bet.py compare BEFORE AFTER
```

The heads-up settings are those of `phase1_heads_up_b0.sh` (same seeds and hands), and their
instruction counts match that run's. Six-max seed 43 (fish247, 500 big blinds deep) is the run
where #21 found the bet under the minimum, now 2000 hands instead of 1200.

| Players | Table, stacks | Seed | Hands | Instructions | Under the minimum, before / after | Other always-wrong, after | Instructions changed | Hands whose result changed |
|---|---|---|---|---|---|---|---|---|
| 6 | mixed, even | 51 | 2000 | 2759 | 1 / 0 | none | 1 | 0 |
| 6 | stations, even | 52 | 2000 | 3592 | 0 / 0 | none | 0 | 0 |
| 6 | nits, even | 53 | 2000 | 2285 | 0 / 0 | none | 0 | 0 |
| 6 | tags, even | 54 | 2000 | 2382 | 0 / 0 | none | 0 | 0 |
| 6 | lags, even | 55 | 2000 | 2552 | 1 / 0 | none | 1 | 0 |
| 6 | maniacs, even | 56 | 2000 | 2526 | 0 / 0 | none | 0 | 0 |
| 6 | fish247, even | 57 | 2000 | 3425 | 1 / 0 | none | 1 | 0 |
| 6 | heldout, even | 58 | 2000 | 2792 | 0 / 0 | none | 0 | 0 |
| 6 | regulars, even | 59 | 2000 | 2665 | 0 / 0 | none | 0 | 0 |
| 6 | switchers, even | 60 | 2000 | 2932 | 1 / 0 | none | 1 | 0 |
| 6 | wildcards, even | 61 | 2000 | 2887 | 0 / 0 | none | 0 | 0 |
| 6 | mixed, even, 500 bb deep | 62 | 2000 | 2746 | 0 / 0 | none | 0 | 0 |
| 6 | stations, even, 500 bb deep | 63 | 2000 | 3601 | 1 / 0 | none | 1 | 0 |
| 6 | nits, even, 500 bb deep | 64 | 2000 | 2245 | 2 / 0 | none | 2 | 0 |
| 6 | tags, even, 500 bb deep | 65 | 2000 | 2389 | 1 / 0 | none | 1 | 0 |
| 6 | lags, even, 500 bb deep | 66 | 2000 | 2633 | 0 / 0 | none | 0 | 0 |
| 6 | maniacs, even, 500 bb deep | 67 | 2000 | 2515 | 0 / 0 | none | 0 | 0 |
| 6 | fish247, even, 500 bb deep | 68 | 2000 | 3398 | 2 / 0 | none | 2 | 0 |
| 6 | heldout, even, 500 bb deep | 69 | 2000 | 2847 | 0 / 0 | none | 0 | 0 |
| 6 | regulars, even, 500 bb deep | 70 | 2000 | 2715 | 0 / 0 | none | 0 | 0 |
| 6 | switchers, even, 500 bb deep | 71 | 2000 | 2845 | 0 / 0 | none | 0 | 0 |
| 6 | wildcards, even, 500 bb deep | 72 | 2000 | 2884 | 0 / 0 | none | 0 | 0 |
| 6 | mixed, tourney | 73 | 2000 | 2477 | 1 / 0 | none | 1 | 0 |
| 6 | fish247, tourney | 74 | 2000 | 3234 | 1 / 0 | none | 1 | 0 |
| 6 | mixed, uneven | 75 | 2000 | 2582 | 0 / 0 | none | 0 | 0 |
| 6 | fish247, even, 500 bb deep | 43 | 2000 | 3430 | 2 / 0 | none | 2 | 0 |
| 2 | mixed, even | 21 | 2000 | 2250 | 0 / 0 | none | 0 | 0 |
| 2 | stations, even | 22 | 2000 | 3028 | 0 / 0 | none | 0 | 0 |
| 2 | nits, even | 23 | 2000 | 1401 | 0 / 0 | none | 0 | 0 |
| 2 | tags, even | 24 | 2000 | 1564 | 0 / 0 | none | 0 | 0 |
| 2 | lags, even | 25 | 2000 | 2065 | 0 / 0 | none | 0 | 0 |
| 2 | maniacs, even | 26 | 2000 | 2802 | 0 / 0 | none | 0 | 0 |
| 2 | fish247, even | 27 | 2000 | 2617 | 0 / 0 | none | 0 | 0 |
| 2 | heldout, even | 28 | 2000 | 2028 | 0 / 0 | none | 0 | 0 |
| 2 | regulars, even | 29 | 2000 | 1902 | 0 / 0 | none | 0 | 0 |
| 2 | switchers, even | 30 | 2000 | 2894 | 0 / 0 | none | 0 | 0 |
| 2 | wildcards, even | 31 | 2000 | 2505 | 0 / 0 | none | 0 | 0 |
| 2 | mixed, uneven | 32 | 2000 | 2155 | 0 / 0 | none | 0 | 0 |
| 2 | mixed, tourney | 33 | 2000 | 1871 | 0 / 0 | none | 0 | 0 |
| 2 | fish247, tourney | 34 | 2000 | 2538 | 0 / 0 | none | 0 | 0 |
| 2 | mixed, even, 500 bb deep | 35 | 2000 | 2308 | 0 / 0 | none | 0 | 0 |
| 2 | fish247, even, 500 bb deep | 36 | 2000 | 2652 | 0 / 0 | none | 0 | 0 |
| 2 | mixed, even, profiles | 37 | 1000 | 1049 | 0 / 0 | none | 0 | 0 |

- Six-max: 52000 hands, 73338 instructions; under the minimum 14 before, 0 after; other always-wrong after: none; instructions changed 14; hands whose result changed 0.
- Heads-up: 33000 hands, 37629 instructions; under the minimum 0 before, 0 after; other always-wrong after: none; instructions changed 0; hands whose result changed 0.

Every instruction that changed (hand number in its run, cards on the board, before -> after, and the change in the hand's result in big blinds):

- 6 players, mixed, even, seed 51, hand 5, 4 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, lags, even, seed 55, hand 1367, 4 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, fish247, even, seed 57, hand 1511, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, switchers, even, seed 60, hand 461, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, stations, even, 500 bb deep, seed 63, hand 1727, 4 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, nits, even, 500 bb deep, seed 64, hand 89, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, nits, even, 500 bb deep, seed 64, hand 1859, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, tags, even, 500 bb deep, seed 65, hand 1829, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, fish247, even, 500 bb deep, seed 68, hand 929, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, fish247, even, 500 bb deep, seed 68, hand 1133, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, mixed, tourney, seed 73, hand 947, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, fish247, tourney, seed 74, hand 1511, 3 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, fish247, even, 500 bb deep, seed 43, hand 665, 4 cards: BET 1.5 -> BET 2 (result unchanged)
- 6 players, fish247, even, 500 bb deep, seed 43, hand 1949, 4 cards: BET 1.5 -> BET 2 (result unchanged)

All 14 were one spot: B0 in the big blind, the small blind completed, checked to B0 on the flop
or turn, and the `stab` rule's third of the 4-chip pot (1.5) under the big blind of 2. The
simulator already played the minimum, so no result changed.
