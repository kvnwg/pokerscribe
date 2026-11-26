1. r per comparison

| Comparison | Run 4 | Run 5 | Runs 4 and 5 pooled |
|---|---|---|---|
| ev_mixed | 0.39 | 0.58 | 0.50 |
| ev_fish | 0.35 | 0.43 | 0.41 |
| bet_half | 0.40 | 0.73 | 0.61 |
| semibluff_never | 0.80 | 0.57 | 0.66 |
| texture | 0.51 | 0.75 | 0.65 |
| push_chart | 0.17 | 0.15 | 0.16 |
| commit | 2.02 | 1.45 | 1.46 |
| no_stab | 0.12 | 0.38 | 0.28 |

Pooled, the five judged in runs 4 and 5: geometric mean 0.42; without push_chart 0.53

2. 2000 runs of run 5's size drawn from the pooled hands

| Comparison | Middle r | 95% of draws | Judged in | r above 0.75 in |
|---|---|---|---|---|
| ev_mixed | 0.50 | 0.33 to 0.72 | 100% | 2% |
| ev_fish | 0.41 | 0.30 to 0.56 | 100% | 0% |
| bet_half | 0.61 | 0.42 to 0.83 | 100% | 11% |
| semibluff_never | 0.65 | 0.31 to 1.15 | 4% | 33% |
| texture | 0.64 | 0.43 to 0.95 | 100% | 24% |
| push_chart | 0.16 | 0.12 to 0.20 | 95% | 0% |
| commit | 1.41 | 0.32 to 4.79 | 0% | 79% |
| no_stab | 0.25 | 0.10 to 0.68 | 0% | 1% |

Geometric mean at most 0.5 in 93% of draws, no judged r above 0.75 in 69%, both in 67%.

3. Run 5: CPU seconds for equal precision, new way over old way

| Comparison | r | CPU per hand, new / old | CPU for equal precision |
|---|---|---|---|
| ev_mixed | 0.58 | 1.46 | 0.50 |
| ev_fish | 0.43 | 1.42 | 0.27 |
| bet_half | 0.73 | 1.31 | 0.70 |
| semibluff_never | 0.57 | 1.04 | 0.34 |
| texture | 0.75 | 1.29 | 0.73 |
| push_chart | 0.15 | 1.06 | 0.02 |
| commit | 1.45 | 1.03 | 2.16 |
| no_stab | 0.38 | 1.10 | 0.16 |
