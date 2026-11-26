| Comparison | Method | Hands | Differ | Raw difference | Checked down | Fitted | Resampled | Base win rate | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| bet_half | classic | 3000 | 118 | -7.3 ± 4.0 | -6.8 ± 3.5 | -6.7 ± 3.5 | - | +53.5 ± 22.2 | 356 |
| bet_half | duplicate | 3000 | 132 | -1.0 ± 4.0 | -0.1 ± 3.4 | -0.6 ± 3.6 | +0.1 ± 2.3 | +58.4 ± 22.0 | 517 |
| commit | classic | 3000 | 2 | +0.0 ± 0.0 | +2.9 ± 2.9 | +0.7 ± 0.6 | - | +53.5 ± 22.2 | 383 |
| commit | duplicate | 3000 | 1 | +0.0 ± 0.0 | +1.4 ± 1.4 | +1.7 ± 1.7 | +0.9 ± 0.9 | +58.4 ± 22.0 | 248 |
| ev_fish | classic | 3000 | 155 | +2.3 ± 4.2 | +1.1 ± 3.7 | -0.1 ± 3.4 | - | +32.7 ± 14.2 | 650 |
| ev_fish | duplicate | 3000 | 173 | +0.1 ± 4.6 | -0.0 ± 4.1 | +0.4 ± 4.0 | -0.4 ± 3.3 | +51.1 ± 13.7 | 846 |
| ev_mixed | classic | 3000 | 128 | -2.7 ± 6.5 | -2.6 ± 6.2 | -2.1 ± 6.3 | - | +53.5 ± 22.2 | 439 |
| ev_mixed | duplicate | 3000 | 122 | +10.2 ± 5.3 | +12.4 ± 4.5 | +14.2 ± 4.4 | +9.8 ± 3.2 | +58.4 ± 22.0 | 646 |
| no_stab | classic | 3000 | 20 | +0.0 ± 2.7 | -0.3 ± 2.6 | -0.1 ± 2.7 | - | +53.5 ± 22.2 | 313 |
| no_stab | duplicate | 3000 | 18 | -0.8 ± 3.1 | -1.0 ± 2.8 | -0.8 ± 2.8 | -3.7 ± 3.4 | +58.4 ± 22.0 | 359 |
| push_chart | classic | 3000 | 33 | -1.1 ± 1.4 | +0.1 ± 0.5 | +0.1 ± 0.5 | - | +18.7 ± 9.7 | 405 |
| push_chart | duplicate | 3000 | 43 | -0.4 ± 1.9 | -1.0 ± 0.6 | -1.0 ± 0.6 | -1.0 ± 0.6 | +7.2 ± 9.0 | 236 |
| semibluff_never | classic | 3000 | 25 | -4.5 ± 2.8 | -3.8 ± 2.1 | -3.8 ± 1.9 | - | +53.5 ± 22.2 | 392 |
| semibluff_never | duplicate | 3000 | 16 | -3.1 ± 2.1 | -3.0 ± 1.5 | -2.7 ± 1.2 | -2.4 ± 1.3 | +58.4 ± 22.0 | 278 |
| texture | classic | 3000 | 119 | -0.7 ± 3.2 | +0.3 ± 2.8 | +0.5 ± 2.7 | - | +53.5 ± 22.2 | 483 |
| texture | duplicate | 3000 | 132 | +0.1 ± 6.5 | -3.0 ± 5.0 | -3.0 ± 4.9 | -0.5 ± 3.3 | +58.4 ± 22.0 | 537 |

Standard error as a share of classic raw, luck adjustment = checked:

| Comparison | Classic, adjusted | Keyed | Keyed, adjusted | Duplicate | Duplicate, adjusted (r) | Time, duplicate / classic |
|---|---|---|---|---|---|---|
| bet_half | 0.88 | - | - | 1.00 | **0.86** | 1.45 |
| commit | nan | - | - | nan | **nan** | 0.65 |
| ev_fish | 0.88 | - | - | 1.08 | **0.96** | 1.30 |
| ev_mixed | 0.96 | - | - | 0.81 | **0.70** | 1.47 |
| no_stab | 0.98 | - | - | 1.18 | **1.06** | 1.14 |
| push_chart | 0.33 | - | - | 1.33 | **0.43** | 0.58 |
| semibluff_never | 0.75 | - | - | 0.75 | **0.53** | 0.71 |
| texture | 0.85 | - | - | 2.02 | **1.53** | 1.11 |

Geometric mean of r: 0.80; largest r: 1.53; mean time ratio: 1.05. Gate FAILS (needs at most 0.5, 0.75 and 1.25).

Standard error as a share of classic raw, luck adjustment = fitted:

| Comparison | Classic, adjusted | Keyed | Keyed, adjusted | Duplicate | Duplicate, adjusted (r) | Time, duplicate / classic |
|---|---|---|---|---|---|---|
| bet_half | 0.87 | - | - | 1.00 | **0.90** | 1.45 |
| commit | nan | - | - | nan | **nan** | 0.65 |
| ev_fish | 0.81 | - | - | 1.08 | **0.94** | 1.30 |
| ev_mixed | 0.96 | - | - | 0.81 | **0.68** | 1.47 |
| no_stab | 1.02 | - | - | 1.18 | **1.05** | 1.14 |
| push_chart | 0.33 | - | - | 1.33 | **0.43** | 0.58 |
| semibluff_never | 0.68 | - | - | 0.75 | **0.43** | 0.71 |
| texture | 0.83 | - | - | 2.02 | **1.51** | 1.11 |

Geometric mean of r: 0.77; largest r: 1.51; mean time ratio: 1.05. Gate FAILS (needs at most 0.5, 0.75 and 1.25).

Standard error as a share of classic raw, luck adjustment = resampled:

| Comparison | Classic, adjusted | Keyed | Keyed, adjusted | Duplicate | Duplicate, adjusted (r) | Time, duplicate / classic |
|---|---|---|---|---|---|---|
| bet_half | nan | - | - | 1.00 | **0.57** | 1.45 |
| commit | nan | - | - | nan | **nan** | 0.65 |
| ev_fish | nan | - | - | 1.08 | **0.78** | 1.30 |
| ev_mixed | nan | - | - | 0.81 | **0.49** | 1.47 |
| no_stab | nan | - | - | 1.18 | **1.29** | 1.14 |
| push_chart | nan | - | - | 1.33 | **0.42** | 0.58 |
| semibluff_never | nan | - | - | 0.75 | **0.48** | 0.71 |
| texture | nan | - | - | 2.02 | **1.01** | 1.11 |

Geometric mean of r: 0.66; largest r: 1.29; mean time ratio: 1.05. Gate FAILS (needs at most 0.5, 0.75 and 1.25).

Weights used (flop, turn, river; SPR up to 1.5, up to 4, above): +0.31 +0.15 +0.05 +0.79 +0.14 +0.02 +0.21 +0.05 +0.01

On the same hands (duplicate runs), standard error as a share of the raw one:

| Comparison | Checked down | Fitted | Resampled |
|---|---|---|---|
| bet_half | 0.85 | 0.90 | 0.56 |
| ev_fish | 0.89 | 0.87 | 0.72 |
| ev_mixed | 0.86 | 0.84 | 0.60 |
| no_stab | 0.90 | 0.89 | 1.09 |
| push_chart | 0.32 | 0.32 | 0.32 |
| semibluff_never | 0.72 | 0.58 | 0.64 |
| texture | 0.76 | 0.75 | 0.50 |
| geometric mean | 0.72 | 0.70 | 0.60 |
