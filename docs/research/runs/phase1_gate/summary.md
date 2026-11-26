| Comparison | Method | Hands | Differ | Raw difference | Checked down | Fitted | Resampled | Base win rate | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| bet_half | classic | 3000 | 121 | +3.5 ± 3.8 | +0.3 ± 4.1 | - | - | +14.0 ± 18.0 | 324 |
| bet_half | duplicate | 3000 | 128 | +4.8 ± 3.3 | +3.8 ± 3.0 | +3.5 ± 2.8 | - | +1.7 ± 18.6 | 283 |
| commit | classic | 3000 | 1 | -1.3 ± 1.3 | -1.0 ± 1.0 | - | - | +14.0 ± 18.0 | 253 |
| commit | duplicate | 3000 | 0 | +0.0 ± 0.0 | +0.0 ± 0.0 | +0.0 ± 0.0 | - | +1.7 ± 18.6 | 248 |
| ev_fish | classic | 3000 | 149 | +6.8 ± 7.6 | +6.1 ± 7.3 | - | - | +44.3 ± 19.0 | 475 |
| ev_fish | duplicate | 3000 | 132 | +1.9 ± 5.2 | +0.3 ± 4.4 | -0.1 ± 4.3 | - | +20.6 ± 8.9 | 407 |
| ev_mixed | classic | 3000 | 116 | +5.7 ± 3.2 | +3.5 ± 3.8 | - | - | +14.0 ± 18.0 | 384 |
| ev_mixed | duplicate | 3000 | 109 | +8.2 ± 3.3 | +6.8 ± 2.9 | +6.6 ± 2.5 | - | +1.7 ± 18.6 | 330 |
| no_stab | classic | 3000 | 21 | -6.7 ± 4.2 | -6.9 ± 4.0 | - | - | +14.0 ± 18.0 | 246 |
| no_stab | duplicate | 3000 | 23 | +0.7 ± 2.1 | -1.4 ± 1.6 | -1.9 ± 1.5 | - | +1.7 ± 18.6 | 253 |
| push_chart | classic | 3000 | 30 | +0.2 ± 1.5 | +0.2 ± 0.4 | - | - | +7.6 ± 8.3 | 232 |
| push_chart | duplicate | 3000 | 31 | +0.8 ± 1.8 | +0.3 ± 0.5 | +0.3 ± 0.5 | - | +3.3 ± 7.9 | 211 |
| semibluff_never | classic | 3000 | 21 | -2.8 ± 1.7 | +0.9 ± 3.2 | - | - | +14.0 ± 18.0 | 295 |
| semibluff_never | duplicate | 3000 | 14 | -4.2 ± 2.0 | -3.4 ± 1.8 | -3.1 ± 1.8 | - | +1.7 ± 18.6 | 250 |
| texture | classic | 3000 | 118 | -1.3 ± 2.9 | -4.8 ± 3.5 | - | - | +14.0 ± 18.0 | 302 |
| texture | duplicate | 3000 | 127 | -2.8 ± 1.4 | -3.6 ± 1.4 | -3.2 ± 1.3 | - | +1.7 ± 18.6 | 284 |

Standard error as a share of classic raw, luck adjustment = checked:

| Comparison | Classic, adjusted | Keyed | Keyed, adjusted | Duplicate | Duplicate, adjusted (r) | Time, duplicate / classic |
|---|---|---|---|---|---|---|
| bet_half | 1.08 | - | - | 0.87 | **0.80** | 0.87 |
| commit | - | - | - | - | (no hand differs: left out) | - |
| ev_fish | 0.96 | - | - | 0.69 | **0.58** | 0.86 |
| ev_mixed | 1.21 | - | - | 1.05 | **0.90** | 0.86 |
| no_stab | 0.95 | - | - | 0.50 | **0.38** | 1.03 |
| push_chart | 0.25 | - | - | 1.16 | **0.33** | 0.91 |
| semibluff_never | 1.86 | - | - | 1.19 | **1.09** | 0.85 |
| texture | 1.19 | - | - | 0.47 | **0.47** | 0.94 |

Geometric mean of r: 0.60; largest r: 1.09; mean time ratio: 0.90. Gate FAILS (needs at most 0.5, 0.75 and 1.25).

Standard error as a share of classic raw, luck adjustment = fitted:

| Comparison | Classic, adjusted | Keyed | Keyed, adjusted | Duplicate | Duplicate, adjusted (r) | Time, duplicate / classic |
|---|---|---|---|---|---|---|
| bet_half | nan | - | - | 0.87 | **0.73** | 0.87 |
| commit | - | - | - | - | (no hand differs: left out) | - |
| ev_fish | nan | - | - | 0.69 | **0.57** | 0.86 |
| ev_mixed | nan | - | - | 1.05 | **0.80** | 0.86 |
| no_stab | nan | - | - | 0.50 | **0.37** | 1.03 |
| push_chart | nan | - | - | 1.16 | **0.33** | 0.91 |
| semibluff_never | nan | - | - | 1.19 | **1.08** | 0.85 |
| texture | nan | - | - | 0.47 | **0.44** | 0.94 |

Geometric mean of r: 0.57; largest r: 1.08; mean time ratio: 0.90. Gate FAILS (needs at most 0.5, 0.75 and 1.25).
