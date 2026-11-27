# Pruning check

Settings scaled by 0.004 (CHECK 8,000,000 / NOMINAL 2,000,000,000).

| Arm | Stage | Iterations/s (session before) | States/s | States per iteration | Pruned traversals | Pruned actions | Export s | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pruning | 1,000,000 | 9,570 | 6.92M | 723 | 1,633,879 | 954,596 | 44 |  |
| pruning | 2,000,000 | 13,625 | 9.13M | 670 | 3,533,617 | 5,383,710 | 58 | 0.1117 |
| pruning | 4,000,000 | 13,107 | 9.41M | 718 | 7,333,920 | 25,634,633 | 60 | 0.1225 |
| pruning | 8,000,000 | 11,448 | 9.41M | 822 | 14,933,896 | 98,360,869 | 66 | 0.1345 |
| no-pruning | 1,000,000 | 9,211 | 6.67M | 724 | 0 | 0 | 44 |  |
| no-pruning | 2,000,000 | 13,716 | 9.31M | 679 | 0 | 0 | 48 | 0.1120 |
| no-pruning | 4,000,000 | 12,353 | 9.25M | 749 | 0 | 0 | 62 | 0.1245 |
| no-pruning | 8,000,000 | 10,718 | 9.46M | 883 | 0 | 0 | 68 | 0.1341 |

Regrets at 8M, share of slots below each level (big blinds):

| Arm | Street | below -1e3 | below -1e4 | below -1e5 | below -1e6 | below the threshold | lowest |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pruning | flop | 0.1470 | 0.01002 | 0.000036 | 0.000000 | 0.007719 | -492,207 |
| pruning | preflop | 0.3727 | 0.05171 | 0.000054 | 0.000000 | 0.039626 | -631,837 |
| pruning | river | 0.0553 | 0.00227 | 0.000005 | 0.000000 | 0.001630 | -251,328 |
| pruning | turn | 0.0805 | 0.00474 | 0.000034 | 0.000000 | 0.003528 | -513,099 |
| no-pruning | flop | 0.1527 | 0.01049 | 0.000141 | 0.000000 |  | -520,398 |
| no-pruning | preflop | 0.3846 | 0.05772 | 0.000513 | 0.000000 |  | -830,191 |
| no-pruning | river | 0.0556 | 0.00228 | 0.000006 | 0.000000 |  | -313,665 |
| no-pruning | turn | 0.0820 | 0.00477 | 0.000048 | 0.000000 |  | -584,167 |

| LBR | pruning | no pruning | difference | SE | z |
| --- | ---: | ---: | ---: | ---: | ---: |
| fcpa14 | +111.2 | +137.1 | -25.9 | 33.7 | -0.77 |
| b56_14 | +389.4 | +412.2 | -22.9 | 32.0 | -0.71 |

Head to head, pruning against no pruning: +2.15 ± 10.93 bb/100 over 40,000 hands.

Pruning trains: yes (worse on LBR by 2.5 SE: none; worse head to head by 2.5 SE: no; pruning skipped something: yes).
