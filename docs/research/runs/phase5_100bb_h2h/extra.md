## Added after review (not pre-registered; doesn't change the decision)

The main match (seed 9201) and the replication (seed 9202) agreed to 0.0023 bb/100. These checks show that it is chance.

**The deals differ.** The arena deals deal d from mix(seed, d) alone (`engine/crates/arena/src/runner.rs`), so an agent that only checks and calls sees the same cards the blueprints were dealt:

- seed 9201, deal 0: button 9d 6h, big blind 8d 4c, board 6c Ts 3s 3c Kh
- seed 9202, deal 0: button 8d 2h, big blind Qc Jc, board 3d Ah Ts As 9s
- of the first 1,000 deals, 0 are the same on seeds 9201 and 9202

The blueprints on the first 1,000 deals of each seed:

| Seed | Deals | standard-k200 against standard-k50 | Real chips | All-in hands adjusted |
| ---: | ---: | ---: | ---: | ---: |
| 9201 | 1,000 | -7.34 ± 20.16 | -1.99 | 3 |
| 9202 | 1,000 | +10.41 ± 22.46 | +17.89 | 2 |

**Every seed at 2,000,000 deals** (9201 and 9202 from the plan; 9203 and 9204 asked for in review; 9205 to 9212 added after those two, because 9204 landed 0.02 from 9201 and 9202):

| Seed | standard-k200 against standard-k50 | Real chips | On the button | In the big blind |
| ---: | ---: | ---: | ---: | ---: |
| 9201 | +3.7409 ± 0.4850 | +3.3729 | +19.29 | -11.81 |
| 9202 | +3.7432 ± 0.4858 | +3.7150 | +18.21 | -10.72 |
| 9203 | +2.4107 ± 0.4864 | +2.4152 | +17.61 | -12.79 |
| 9204 | +3.7623 ± 0.4862 | +3.7463 | +17.48 | -9.95 |
| 9205 | +3.1913 ± 0.4870 | +3.1284 | +17.80 | -11.42 |
| 9206 | +3.4626 ± 0.4856 | +3.5909 | +18.22 | -11.30 |
| 9207 | +3.0736 ± 0.4846 | +3.0666 | +18.87 | -12.72 |
| 9208 | +3.5173 ± 0.4871 | +3.5333 | +17.77 | -10.74 |
| 9209 | +4.3348 ± 0.4873 | +4.0729 | +18.75 | -10.08 |
| 9210 | +3.7768 ± 0.4865 | +4.2616 | +18.98 | -11.42 |
| 9211 | +4.1035 ± 0.4866 | +4.0361 | +18.66 | -10.45 |
| 9212 | +3.7793 ± 0.4868 | +3.7627 | +18.63 | -11.08 |

- The spread of the 12 results is what their SEs give: sd 0.505 against a mean SE of 0.486 (chi-square 11.8 on 11 degrees of freedom, p = 0.38).
- Among their 66 pairs the closest are 9201 and 9202 (0.0023), 9210 and 9212 (0.0025), 9204 and 9210 (0.0145).
- Pooled over the 12 seeds: +3.57 ± 0.14 bb/100 (25.5 SE). No illegal actions in any match.
