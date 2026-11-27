## Work to the gate's convergence, per run

| Run | Information sets | Stopped at | Change reaches 0.08 | States visited then | Per information set | Iterations per information set | States per iteration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| small-k10 | 14,828 | 8M | 8.0M (at or before) | 1.47e+09 | 99,357 | 540 | 184 |
| small-k50 | 66,028 | 16M | 10.7M (interpolated) | 2e+09 | 30,263 | 161 | 187 |
| small-k50eq | 66,028 | 32M | 22.8M (interpolated) | 4.28e+09 | 64,870 | 345 | 188 |
| small-k200 | 258,028 | 64M | 35.8M (interpolated) | 6.85e+09 | 26,535 | 139 | 191 |
| standard-k10 | 64,580 | 32M | 10.4M (interpolated) | 3.72e+09 | 57,621 | 162 | 356 |
| standard-k50 | 282,340 | 64M | 34.9M (interpolated) | 1.32e+10 | 46,845 | 124 | 378 |
| standard-k50eq | 282,340 | 64M | 44.0M (interpolated) | 1.66e+10 | 58,893 | 156 | 378 |
| standard-k200 | 1,098,940 | 64M | 59.4M (interpolated) | 2.25e+10 | 20,474 | 54 | 379 |

Iterations to the bar against information sets: iterations ~ 4.39e+04 x info_sets^0.53 (residual sd 0.31 in log). At 97,158,404 information sets: 7.39e+08 iterations, 1-sd band 3.82e+08 to 1.43e+09.

States visited per information set at the bar: 20,474 to 99,357 (median 57,621).

## The Phase 6 game on this machine (200bb, rich menu, 200 buckets)

| Session | Threads | Iterations | Seconds | Iterations/s | States/s | States per iteration | Information sets met | Bytes per information set | Table | Resident |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 0.00M to 1.00M | 79 | 13,448 | 9.37M | 697 | 55,048,112 (56.7%) | 71.4 | 3.93 GB | 5.24 GB |
| 2 | 4 | 1.00M to 2.61M | 122 | 14,217 | 11.21M | 789 | 71,698,349 (73.8%) | 61.8 | 4.43 GB | 5.74 GB |
| 3 | 4 | 2.61M to 4.32M | 148 | 12,153 | 11.14M | 917 | 80,410,037 (82.8%) | 58.3 | 4.69 GB | 5.99 GB |
| 4 | 4 | 4.32M to 5.78M | 136 | 11,699 | 11.38M | 973 | 84,583,719 (87.1%) | 56.9 | 4.81 GB | 6.12 GB |
| 5 | 4 | 5.78M to 7.18M | 137 | 11,064 | 11.16M | 1,008 | 87,003,425 (89.5%) | 56.1 | 4.88 GB | 6.19 GB |
| 6 | 4 | 7.18M to 8.51M | 136 | 10,504 | 11.03M | 1,051 | 88,983,021 (91.6%) | 55.5 | 4.94 GB | 6.24 GB |
| 7 | 4 | 8.51M to 9.77M | 139 | 9,882 | 10.57M | 1,069 | 90,243,668 (92.9%) | 55.1 | 4.97 GB | 6.28 GB |
| 8 | 4 | 9.77M to 10.96M | 140 | 9,259 | 10.13M | 1,094 | 91,238,613 (93.9%) | 54.8 | 5.00 GB | 6.31 GB |
| 9 | 4 | 10.96M to 12.07M | 122 | 9,923 | 10.90M | 1,099 | 91,929,155 (94.6%) | 54.6 | 5.02 GB | 6.33 GB |
| 10 | 4 | 12.07M to 13.26M | 130 | 9,867 | 10.95M | 1,110 | 92,548,611 (95.3%) | 54.4 | 5.04 GB | 6.34 GB |
| 11 | 4 | 13.26M to 14.44M | 132 | 9,854 | 11.08M | 1,124 | 93,077,108 (95.8%) | 54.3 | 5.05 GB | 6.36 GB |
| 12 | 4 | 14.44M to 15.11M | 82 | 9,444 | 10.71M | 1,134 | 93,344,588 (96.1%) | 54.2 | 5.06 GB | 6.37 GB |
| 13 | 1 | 15.11M to 15.78M | 298 | 2,322 | 2.63M | 1,132 | 93,577,361 (96.3%) | 77.1 | 7.22 GB | 7.39 GB |

## Projection

- Information sets 97,158,404, slots 251,686,705 (2.59 a set).
- Memory: 3.02 GB of slots (12 bytes each) and the index: 2.15 GB measured with 96% of the sets met (23 bytes a set, room for the rest), 4.30 GB after a resume. So 5.2 GB for the tables in a fresh run and 7.3 GB after a resume (53 and 75 bytes a set). The whole process (with the bucket tables and the game) was 6.4 GB resident in the last 4-thread session and 7.4 GB after the resume, the index's unused cells not all touched. Checkpoint: 4.87 GB. Strategy file: 0.50 GB.
- Threads in this game: 4 threads gave 2.68M states/s each in the last 4-thread session, 1 thread 2.63M right after, so 4 threads ran at 1.02 of 4 times one thread.
- Speed measured here, last sessions: 2.63M states/s per thread (1 thread), 1,134 states per iteration, with 96% of the table met.
- 64-thread speed in states a second: 57M slow, 112M central, 227M fast (per core (0.8, 1.0, 1.5), 64-thread scaling (0.5, 0.7, 0.9), full table (0.85, 0.95, 1.0)).

| Work model | States to visit, low / central / high | Hours, low (fast speed) | Hours, central | Hours, high (slow speed) | Spot cost, central |
| --- | --- | ---: | ---: | ---: | ---: |
| Iterations from the power law, times states per iteration | 4.3e+11 / 1e+12 / 2.4e+12 | 0.5 | 2.5 | 11.8 | $5 |
| States per information set as at 20bb | 2e+12 / 5.6e+12 / 9.7e+12 | 2.4 | 13.9 | 46.9 | $28 |
