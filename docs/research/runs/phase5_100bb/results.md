## Training and convergence

| Run | Information sets | Stopped at | Why | Change, last doubling | Train time | Iterations/s (4 threads) | LBR 56 bets 1-4 by stage (50k hands, seed 777) | fcpa 3-4 by stage |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |
| standard-k10 | 374,912 | 16M | converged | 0.077 | 0.12 h | 38,518 | 4M 593.0, 8M 585.1, 16M 584.6 | 4M 101.7, 8M 115.4, 16M 107.9 |
| standard-k50 | 1,815,072 | 64M | converged | 0.068 | 0.66 h | 26,870 | 4M 561.4, 8M 544.9, 16M 551.5, 32M 581.2, 64M 571.0 | 4M 126.8, 8M 126.4, 16M 136.7, 32M 140.0, 64M 147.4 |
| standard-k200 | 7,215,672 | 128M | converged | 0.073 | 1.57 h | 22,786 | 4M 496.6, 8M 569.9, 16M 559.8, 32M 565.9, 64M 588.9, 128M 583.4 | 4M 159.5, 8M 154.9, 16M 148.8, 32M 151.2, 64M 154.9, 128M 154.7 |

## Final LBR (100,000 hands, seed 778, the same deals for every run), bb/100

| Run | 56 bets, 1-4 | 56 bets, 3-4 | fcpa, 1-4 | fcpa, 3-4 | fc, 3-4 | fc, 1-4 | M (of six) | M (the gate's five) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| standard-k10 | +592.6 ± 7.9 | +397.0 ± 5.8 | +74.9 ± 6.7 | +108.5 ± 5.0 | -24.7 ± 3.3 | +1.3 ± 2.5 | +592.6 ± 7.9 (56 bets, 1-4) | +592.6 ± 7.9 |
| standard-k50 | +575.6 ± 7.7 | +431.8 ± 5.8 | +96.0 ± 6.8 | +132.8 ± 5.2 | -15.2 ± 3.0 | +0.2 ± 2.6 | +575.6 ± 7.7 (56 bets, 1-4) | +575.6 ± 7.7 |
| standard-k200 | +592.9 ± 7.7 | +439.3 ± 6.0 | +111.4 ± 6.8 | +151.3 ± 5.4 | -11.2 ± 3.2 | +4.2 ± 2.7 | +592.9 ± 7.7 (56 bets, 1-4) | +592.9 ± 7.7 |

Share of the blueprint's decisions off the tree (it checks or calls there):

| Run | 56 bets, 1-4 | 56 bets, 3-4 | fcpa, 1-4 | fcpa, 3-4 | fc, 3-4 | fc, 1-4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard-k10 | 10.09% | 1.37% | 1.54% | 0.16% | 0.00% | 0.00% |
| standard-k50 | 9.10% | 1.51% | 1.69% | 0.17% | 0.00% | 0.00% |
| standard-k200 | 9.77% | 1.58% | 1.63% | 0.20% | 0.00% | 0.00% |

## Paired differences by setting (bb/100, the second run minus the first)

| From | To | 56 bets, 1-4 | 56 bets, 3-4 | fcpa, 1-4 | fcpa, 3-4 | fc, 3-4 | fc, 1-4 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard-k10 | standard-k50 | -16.9 ± 7.8 (-2.2 SE) | +34.8 ± 6.8 (+5.1 SE) | +21.1 ± 7.5 (+2.8 SE) | +24.4 ± 6.2 (+3.9 SE) | +9.5 ± 3.7 (+2.6 SE) | -1.1 ± 2.9 (-0.4 SE) |
| standard-k50 | standard-k200 | +17.3 ± 7.0 (+2.5 SE) | +7.5 ± 6.6 (+1.1 SE) | +15.3 ± 7.2 (+2.1 SE) | +18.5 ± 6.5 (+2.8 SE) | +4.0 ± 3.5 (+1.1 SE) | +4.0 ± 3.0 (+1.3 SE) |
| standard-k10 | standard-k200 | +0.4 ± 7.7 (+0.0 SE) | +42.3 ± 7.0 (+6.1 SE) | +36.5 ± 7.5 (+4.9 SE) | +42.8 ± 6.5 (+6.6 SE) | +13.5 ± 3.7 (+3.6 SE) | +2.9 ± 3.0 (+1.0 SE) |

## The verdict (the gate's buckets rule)

- M of six: 10 to 50 -16.9 ± 7.8 (paired, -2.2 SE), 50 to 200 +17.3 ± 7.0 (paired, +2.5 SE): buckets help from 10 to 50; does not flatten.
- M of the gate's five: 10 to 50 -16.9 ± 7.8 (paired, -2.2 SE), 50 to 200 +17.3 ± 7.0 (paired, +2.5 SE): buckets help from 10 to 50; does not flatten.
