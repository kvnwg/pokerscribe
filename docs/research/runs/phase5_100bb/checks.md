## 1. A second deal set: `b56_14`, seed 779 against seed 778 (100,000 hands each), bb/100

| Run | Seed 778 (the final deals) | Seed 779 | 779 - 778 (unpaired) | Both (200,000 hands) |
| --- | ---: | ---: | ---: | ---: |
| standard-k10 | +592.6 ± 7.9 | +605.6 ± 7.9 | +13.0 ± 11.2 (+1.2 SE) | +599.1 ± 5.6 |
| standard-k50 | +575.6 ± 7.7 | +581.6 ± 7.8 | +5.9 ± 10.9 (+0.5 SE) | +578.6 ± 5.5 |
| standard-k200 | +592.9 ± 7.7 | +588.6 ± 7.7 | -4.3 ± 10.9 (-0.4 SE) | +590.8 ± 5.4 |

The plan's comparisons on `b56_14` (the second run minus the first, paired on each seed's deals):

| Buckets | Seed 778 | Seed 779 | Gap between the seeds | Both (200,000 hands) |
| --- | ---: | ---: | ---: | ---: |
| 10 to 50 | -16.9 ± 7.8 (-2.2 SE) | -24.0 ± 7.7 (-3.1 SE) | -7.0 (-0.6 SE) | -20.5 ± 5.5 (-3.7 SE) |
| 50 to 200 | +17.3 ± 7.0 (+2.5 SE) | +7.0 ± 7.0 (+1.0 SE) | -10.3 (-1.0 SE) | +12.2 ± 5.0 (+2.5 SE) |
| 10 to 200 | +0.4 ± 7.7 (+0.0 SE) | -16.9 ± 7.6 (-2.2 SE) | -17.3 (-1.6 SE) | -8.3 ± 5.4 (-1.5 SE) |

## 2. By seat: `b56_14`, LBR on the button and in the big blind, bb/100

Each deal is played twice, LBR in each seat; the plan's figure is the mean of the two. The differences are paired deal by deal (the second run minus the first).

| Seed | LBR | standard-k10 | standard-k50 | standard-k200 | 10 to 50 | 50 to 200 | 10 to 200 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 778 | on the button | +607.4 ± 13.3 | +614.2 ± 12.8 | +655.8 ± 13.0 | +6.9 ± 11.4 (+0.6 SE) | +41.5 ± 10.6 (+3.9 SE) | +48.4 ± 11.5 (+4.2 SE) |
| 778 | in the big blind | +577.8 ± 12.1 | +537.1 ± 11.5 | +530.1 ± 11.0 | -40.8 ± 10.5 (-3.9 SE) | -6.9 ± 9.2 (-0.8 SE) | -47.7 ± 10.3 (-4.6 SE) |
| 779 | on the button | +628.7 ± 13.3 | +629.4 ± 12.8 | +648.0 ± 13.0 | +0.7 ± 11.4 (+0.1 SE) | +18.6 ± 10.5 (+1.8 SE) | +19.2 ± 11.3 (+1.7 SE) |
| 779 | in the big blind | +582.4 ± 12.1 | +533.8 ± 11.4 | +529.3 ± 11.0 | -48.6 ± 10.3 (-4.7 SE) | -4.5 ± 9.1 (-0.5 SE) | -53.1 ± 10.2 (-5.2 SE) |

## 3. References at 100bb (`b56_14`, seed 778, the final deals, 100,000 hands), bb/100

| Agent | LBR wins | A blueprint's share of it (k10, k50, k200) |
| --- | ---: | --- |
| always call | +1671.7 ± 10.9 | 35%, 34%, 35% |
| random action | +2367.1 ± 18.9 | 25%, 24%, 25% |
| random kind of action | +1719.7 ± 17.4 | 34%, 33%, 34% |
