## 1. Fresh deals: `b56_14`, seed 779 against seed 778 (100,000 hands each), bb/100

| Run | Seed 778 | Seed 779 | 779 - 778 (unpaired) |
| --- | ---: | ---: | ---: |
| small-k10 | +120.4 ± 1.8 | +126.2 ± 1.8 | +5.8 ± 2.6 (+2.3 SE) |
| small-k50 | +125.3 ± 1.8 | +131.2 ± 1.8 | +5.9 ± 2.6 (+2.3 SE) |
| small-k50eq | +127.9 ± 1.8 | +129.0 ± 1.8 | +1.1 ± 2.6 (+0.4 SE) |
| small-k200 | +128.9 ± 1.9 | +132.2 ± 1.9 | +3.3 ± 2.6 (+1.3 SE) |
| standard-k10 | +105.1 ± 1.8 | +112.9 ± 1.8 | +7.8 ± 2.6 (+3.1 SE) |
| standard-k50 | +111.7 ± 1.9 | +115.5 ± 1.8 | +3.8 ± 2.6 (+1.5 SE) |
| standard-k50eq | +107.3 ± 1.8 | +109.6 ± 1.8 | +2.3 ± 2.6 (+0.9 SE) |
| standard-k200 | +112.3 ± 1.9 | +113.6 ± 1.8 | +1.3 ± 2.6 (+0.5 SE) |

The gate's comparisons on `b56_14` (the second run minus the first, paired on each seed's deals):

| Comparison | Seed 778 | Seed 779 | Gap between the seeds | Both (200,000 hands) |
| --- | ---: | ---: | ---: | ---: |
| Sizes, 10 buckets | -15.3 ± 1.6 (-9.5 SE) | -13.3 ± 1.6 (-8.2 SE) | +2.0 (+0.9 SE) | -14.3 ± 1.1 (-12.6 SE) |
| Sizes, 50 buckets | -13.6 ± 1.6 (-8.5 SE) | -15.6 ± 1.6 (-9.7 SE) | -2.1 (-0.9 SE) | -14.6 ± 1.1 (-12.8 SE) |
| Sizes, 200 buckets | -16.6 ± 1.6 (-10.5 SE) | -18.6 ± 1.6 (-11.7 SE) | -2.0 (-0.9 SE) | -17.6 ± 1.1 (-15.7 SE) |
| Buckets, small, 10 to 50 | +4.9 ± 1.5 (+3.2 SE) | +5.0 ± 1.5 (+3.2 SE) | +0.1 (+0.0 SE) | +4.9 ± 1.1 (+4.6 SE) |
| Buckets, small, 50 to 200 | +3.6 ± 1.4 (+2.5 SE) | +1.1 ± 1.4 (+0.7 SE) | -2.5 (-1.3 SE) | +2.3 ± 1.0 (+2.3 SE) |
| Buckets, standard, 10 to 50 | +6.6 ± 1.4 (+4.6 SE) | +2.6 ± 1.5 (+1.8 SE) | -4.0 (-2.0 SE) | +4.6 ± 1.0 (+4.5 SE) |
| Buckets, standard, 50 to 200 | +0.6 ± 1.4 (+0.4 SE) | -1.9 ± 1.4 (-1.4 SE) | -2.5 (-1.3 SE) | -0.6 ± 1.0 (-0.6 SE) |
| Buckets, small, 10 to 200 | +8.5 ± 1.6 (+5.4 SE) | +6.0 ± 1.6 (+3.7 SE) | -2.5 (-1.1 SE) | +7.2 ± 1.1 (+6.4 SE) |
| Buckets, standard, 10 to 200 | +7.2 ± 1.5 (+4.9 SE) | +0.7 ± 1.5 (+0.4 SE) | -6.5 (-3.1 SE) | +3.9 ± 1.0 (+3.8 SE) |
| Equity - OCHS, small | +2.6 ± 1.5 (+1.7 SE) | -2.2 ± 1.5 (-1.4 SE) | -4.8 (-2.3 SE) | +0.2 ± 1.1 (+0.2 SE) |
| Equity - OCHS, standard | -4.4 ± 1.5 (-3.0 SE) | -5.9 ± 1.5 (-4.0 SE) | -1.5 (-0.7 SE) | -5.2 ± 1.0 (-5.0 SE) |

## 2. The same measurement twice (seed 779)

- standard-k10: +112.9 ± 1.8 and +112.9 ± 1.8; identical deal by deal
- small-k10: +126.2 ± 1.8 and +126.2 ± 1.8; identical deal by deal
- standard-k10 on seed 778, measured again after the checks: +105.1 ± 1.8, identical deal by deal to the gate's final measurement

## 3. Longer training (seed 778, the final deals, 100,000 hands), bb/100

| Run | Setting | At its stop | Trained on | Difference (paired) |
| --- | --- | ---: | ---: | ---: |
| small-k10, 8M to 64M | b56_14 | +120.4 ± 1.8 | +125.0 ± 1.8 | +4.6 ± 1.3 (+3.6 SE) |
| small-k10, 8M to 64M | fcpa34 | -0.7 ± 2.4 | +1.5 ± 2.4 | +2.2 ± 2.0 (+1.1 SE) |
| small-k200, 64M to 256M | b56_14 | +128.9 ± 1.9 | +131.4 ± 1.9 | +2.5 ± 1.0 (+2.4 SE) |
| small-k200, 64M to 256M | fcpa34 | +4.2 ± 2.4 | +6.7 ± 2.4 | +2.5 ± 1.8 (+1.4 SE) |

- b56_14, small-k200 - small-k10: +8.5 ± 1.6 (+5.4 SE) at their stops; +6.4 ± 1.4 (+4.5 SE) after training on (k10 at 64M, k200 at 256M).

- fcpa34, small-k200 - small-k10: +4.9 ± 2.5 (+2.0 SE) at their stops; +5.3 ± 2.4 (+2.2 SE) after training on (k10 at 64M, k200 at 256M).
