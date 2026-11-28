# Blueprint evaluation

Seeds: LBR 6001, head to head 6101, B0 6201 and up. Stacks 200 big blinds.

(The first evaluation, on Kevin's Mac, 27 Nov 2026: `tools/blueprint_eval.py
~/phase6/run1/strategy-*.bps --tables ~/abstraction/k200 --out ~/phase6/eval --b0 none`, all 11
stage files. Relayed verbatim by the calibration session. Not the gate's reading: the gate's last
file is it512M, see summary-512M.md.)

## Files

| File | Iterations | Change from the stage before | Compared with |
| --- | ---: | ---: | --- |
| it1M | 1,000,000 | ? |  |
| it2M | 2,000,000 | 0.1174 | strategy-1000000.bps |
| it4M | 4,000,000 | 0.1883 | strategy-2000000.bps |
| it8M | 8,000,000 | 0.2055 | strategy-4000000.bps |
| it16M | 16,000,000 | 0.1883 | strategy-8000000.bps |
| it32M | 32,000,000 | 0.1691 | strategy-16000000.bps |
| it64M | 64,000,000 | 0.1488 | strategy-32000000.bps |
| it128M | 128,000,000 | 0.1187 | strategy-64000000.bps |
| it256M | 256,000,000 | 0.0887 | strategy-128000000.bps |
| it512M | 512,000,000 | 0.0745 | strategy-256000000.bps |
| it1.02G | 1,024,000,000 | 0.0655 | strategy-512000000.bps |

## LBR (20,000 hands, the same deals for every file)

| Setting | File | LBR wins, bb/100 | SE | Hands/s | Off the menu |
| --- | --- | ---: | ---: | ---: | ---: |
| b56_14 | it1M | +436.1 | 35.0 | 2196 | 3.9% |
| b56_14 | it2M | +436.4 | 31.6 | 2343 | 5.2% |
| b56_14 | it4M | +410.2 | 30.0 | 2301 | 7.6% |
| b56_14 | it8M | +481.5 | 29.4 | 1943 | 9.3% |
| b56_14 | it16M | +471.6 | 28.8 | 2635 | 10.1% |
| b56_14 | it32M | +480.2 | 28.1 | 2993 | 11.3% |
| b56_14 | it64M | +523.0 | 25.4 | 3183 | 9.0% |
| b56_14 | it128M | +510.5 | 24.4 | 3192 | 8.8% |
| b56_14 | it256M | +479.5 | 23.9 | 3232 | 8.6% |
| b56_14 | it512M | +490.3 | 23.9 | 3165 | 8.5% |
| b56_14 | it1.02G | +481.8 | 23.7 | 3180 | 8.4% |
| fcpa14 | it1M | +391.0 | 33.3 | 185 | 0.9% |
| fcpa14 | it2M | +234.2 | 28.3 | 7371 | 0.7% |
| fcpa14 | it4M | +186.6 | 28.3 | 5219 | 0.6% |
| fcpa14 | it8M | +111.5 | 28.4 | 4418 | 1.0% |
| fcpa14 | it16M | +107.5 | 27.6 | 4756 | 1.1% |
| fcpa14 | it32M | +94.0 | 26.8 | 4858 | 0.9% |
| fcpa14 | it64M | +120.3 | 26.2 | 5127 | 0.9% |
| fcpa14 | it128M | +126.9 | 25.3 | 5187 | 0.8% |
| fcpa14 | it256M | +131.1 | 25.2 | 5104 | 0.7% |
| fcpa14 | it512M | +155.7 | 24.5 | 5058 | 0.7% |
| fcpa14 | it1.02G | +151.1 | 24.4 | 5076 | 0.7% |

Later minus earlier, deal by deal (negative: LBR wins less, the later file is harder to exploit):

| Setting | Earlier | Later | Difference | SE | z |
| --- | --- | --- | ---: | ---: | ---: |
| fcpa14 | it1M | it2M | -156.8 | 35.0 | -4.48 |
| fcpa14 | it2M | it4M | -47.6 | 34.3 | -1.39 |
| fcpa14 | it4M | it8M | -75.1 | 33.2 | -2.26 |
| fcpa14 | it8M | it16M | -4.1 | 30.9 | -0.13 |
| fcpa14 | it16M | it32M | -13.5 | 29.6 | -0.46 |
| fcpa14 | it32M | it64M | +26.3 | 28.6 | +0.92 |
| fcpa14 | it64M | it128M | +6.6 | 26.4 | +0.25 |
| fcpa14 | it128M | it256M | +4.2 | 24.1 | +0.18 |
| fcpa14 | it256M | it512M | +24.6 | 22.4 | +1.10 |
| fcpa14 | it512M | it1.02G | -4.6 | 22.1 | -0.21 |
| fcpa14 | it1M | it1.02G | -239.9 | 39.5 | -6.08 |
| b56_14 | it1M | it2M | +0.3 | 38.3 | +0.01 |
| b56_14 | it2M | it4M | -26.2 | 35.5 | -0.74 |
| b56_14 | it4M | it8M | +71.3 | 31.4 | +2.27 |
| b56_14 | it8M | it16M | -9.9 | 26.5 | -0.37 |
| b56_14 | it16M | it32M | +8.5 | 23.9 | +0.36 |
| b56_14 | it32M | it64M | +42.8 | 23.3 | +1.83 |
| b56_14 | it64M | it128M | -12.5 | 17.4 | -0.72 |
| b56_14 | it128M | it256M | -31.0 | 13.6 | -2.27 |
| b56_14 | it256M | it512M | +10.9 | 12.2 | +0.89 |
| b56_14 | it512M | it1.02G | -8.5 | 10.5 | -0.81 |
| b56_14 | it1M | it1.02G | +45.7 | 41.3 | +1.11 |

## Head to head (200,000 deals, each twice with the seats swapped, all-in equity)

| Later | Earlier | Later wins, bb/100 | SE | z | Hands |
| --- | --- | ---: | ---: | ---: | ---: |
| it2M | it1M | +117.72 | 4.54 | +25.91 | 400,000 |
| it4M | it2M | +94.10 | 3.95 | +23.83 | 400,000 |
| it8M | it4M | +58.23 | 3.51 | +16.59 | 400,000 |
| it16M | it8M | +44.72 | 3.32 | +13.46 | 400,000 |
| it32M | it16M | +31.28 | 3.05 | +10.25 | 400,000 |
| it64M | it32M | +16.72 | 2.76 | +6.06 | 400,000 |
| it128M | it64M | +10.82 | 2.51 | +4.31 | 400,000 |
| it256M | it128M | +6.87 | 2.30 | +2.99 | 400,000 |
| it512M | it256M | +3.36 | 2.21 | +1.52 | 400,000 |
| it1.02G | it512M | +2.29 | 2.10 | +1.09 | 400,000 |
| it1.02G | it1M | +145.82 | 3.87 | +37.65 | 400,000 |

## The stop rule (change at most 0.08, and b56_14 moved by less than 3% or 2 SE)

| Stage | Change | LBR moved | z | Stop here |
| --- | ---: | ---: | ---: | --- |
| it2M | 0.1174 | +0.3 | +0.01 | no |
| it4M | 0.1883 | -26.2 | -0.74 | no |
| it8M | 0.2055 | +71.3 | +2.27 | no |
| it16M | 0.1883 | -9.9 | -0.37 | no |
| it32M | 0.1691 | +8.5 | +0.36 | no |
| it64M | 0.1488 | +42.8 | +1.83 | no |
| it128M | 0.1187 | -12.5 | -0.72 | no |
| it256M | 0.0887 | -31.0 | -2.27 | no |
| it512M | 0.0745 | +10.9 | +0.89 | yes |
| it1.02G | 0.0655 | -8.5 | -0.81 | yes |

## Projection

Over the stages it128M, it256M, it512M, it1.02G the change was multiplied by 0.82 at each
doubling; at that rate it reaches 0.08 at about 442,946,266 iterations, so the stop rule could
first say stop at the stage it512M. At the trainer's last speed (182,020 iterations a second)
that is 0.0 more hours of training, a little more as the states per iteration rise, plus the
pauses at each stage.

## The gate

(Not the gate's reading; see summary-512M.md.)

- Head to head, the last file against the first: it1.02G against it1M, +145.82 +- 3.87 bb/100, z +37.65: passes
- B0 heads-up: not measured
