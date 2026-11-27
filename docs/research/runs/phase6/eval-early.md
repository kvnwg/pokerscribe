# Blueprint evaluation

Seeds: LBR 6001, head to head 6101, B0 6201 and up. Stacks 200 big blinds.

## Files

| File | Iterations | Change from the stage before | Compared with |
| --- | ---: | ---: | --- |
| it1M | 1,000,000 | ? |  |
| it2M | 2,000,000 | 0.1196 | strategy-1000000.bps |

## LBR (20,000 hands, the same deals for every file)

| Setting | File | LBR wins, bb/100 | SE | Hands/s | Off the menu |
| --- | --- | ---: | ---: | ---: | ---: |
| b56_14 | it1M | +475.7 | 36.1 | 1026 | 3.8% |
| b56_14 | it2M | +394.3 | 32.3 | 1193 | 5.7% |
| fcpa14 | it1M | +311.4 | 34.3 | 88 | 0.9% |
| fcpa14 | it2M | +263.6 | 29.5 | 3241 | 0.6% |

Later minus earlier, deal by deal (negative: LBR wins less, the later file is harder to exploit):

| Setting | Earlier | Later | Difference | SE | z |
| --- | --- | --- | ---: | ---: | ---: |
| fcpa14 | it1M | it2M | -47.8 | 36.4 | -1.31 |
| b56_14 | it1M | it2M | -81.4 | 38.9 | -2.09 |

## Head to head (200,000 deals, each twice with the seats swapped, all-in equity)

| Later | Earlier | Later wins, bb/100 | SE | z | Hands |
| --- | --- | ---: | ---: | ---: | ---: |
| it2M | it1M | +120.94 | 4.51 | +26.84 | 400,000 |

## B0 heads-up

| File | Blueprint wins, bb/100 | SE | z | Hands | sd a deal | Hands for 2.5 SE at 5 / 10 / 20 bb/100 | At the edge measured | Hands/s, all processes |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| it2M | -96.2 | 20.4 | -4.71 | 8,000 | 1291 | 833,220 / 208,306 / 52,078 | 2,252 | 61.2 |

## The stop rule (change at most 0.08, and b56_14 moved by less than 3% or 2 SE)

| Stage | Change | LBR moved | z | Stop here |
| --- | ---: | ---: | ---: | --- |
| it2M | 0.1196 | -81.4 | -2.09 | no |

## Projection

Not made: fewer than 3 stages with a change.

## The gate

The last file beats the first head to head by 2.5 SE, and beats B0 heads-up by 2.5 SE (Kevin, 27 Nov 2026). LBR is reported, not pass or fail.

- Head to head, the last file against the first: it2M against it1M, +120.94 +- 4.51 bb/100, z +26.84: passes
- B0 heads-up: it2M -96.2 +- 20.4 bb/100, z -4.71: does not pass
- The gate: does not pass
- Reported: LBR fcpa14 from +311.4 to +263.6 bb/100, last minus first -47.8 +- 36.4 (z -1.31); from one file to the next, 1 step: it fell at 1, by 2.5 SE at 0, and rose by 2.5 SE at 0
- Reported: LBR b56_14 from +475.7 to +394.3 bb/100, last minus first -81.4 +- 38.9 (z -2.09); from one file to the next, 1 step: it fell at 1, by 2.5 SE at 0, and rose by 2.5 SE at 0
