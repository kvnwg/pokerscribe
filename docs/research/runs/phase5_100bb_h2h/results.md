## Matches (100 big blinds, duplicate deals with the seats swapped, all-in equity), bb/100

Each result is the second run's against the first: positive means the second wins.

| Match | Role | Seed | Deals | Second against first | In SE | Real chips | Second on the button | Second in the big blind | All-in hands adjusted | Illegal actions | Wall time |
| --- | --- | ---: | ---: | --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| main: standard-k200 against standard-k50 | decision | 9201 | 2,000,000 | +3.74 ± 0.48 | +7.7 | +3.37 ± 0.50 | +19.29 ± 0.91 | -11.81 ± 0.91 | 13,957 of 4,000,000 | 0, 0 | 11 s |
| replication: standard-k200 against standard-k50 | repeat, fresh deals | 9202 | 2,000,000 | +3.74 ± 0.49 | +7.7 | +3.71 ± 0.50 | +18.21 ± 0.91 | -10.72 ± 0.91 | 13,617 of 4,000,000 | 0, 0 | 11 s |
| sanity: standard-k50 against standard-k10 | sanity check (optional) | 9301 | 2,000,000 | +13.28 ± 0.52 | +25.7 | +13.38 ± 0.53 | +28.68 ± 0.94 | -2.13 ± 0.96 | 15,241 of 4,000,000 | 0, 0 | 10 s |
| k10-k200: standard-k200 against standard-k10 | information | 9401 | 2,000,000 | +15.03 ± 0.52 | +28.8 | +15.33 ± 0.54 | +30.54 ± 0.94 | -0.49 ± 0.96 | 16,566 of 4,000,000 | 0, 0 | 11 s |

## The decision (the main match)

- standard-k200 against standard-k50: +3.74 ± 0.48 bb/100 (+7.7 SE). standard-k200 is ahead by 2.5 SE or more: the extra buckets pay off in play.
- The replication (seed 9202): +3.74 ± 0.49 (+7.7 SE), standard-k200 ahead; the same call as the main match (gap +0.00 ± 0.69).

## The sanity check (optional)

- standard-k50 against standard-k10: +13.28 ± 0.52 (+25.7 SE): the arena sees the 10 to 50 gain LBR saw.

## Added after review (not pre-registered; doesn't change the decision)

The main match and the replication agreed to 0.0023 bb/100. `extra.md` (`extra.py`,
`extra_report.py`) shows that it is chance:

- The deals differ: seed 9201's first deal is 9d 6h against 8d 4c on 6c Ts 3s 3c Kh, seed 9202's
  8d 2h against Qc Jc on 3d Ah Ts As 9s, and none of the first 1,000 deals is the same on both.
- Ten more fresh seeds at 2,000,000 deals (9203 to 9212) give +2.41 to +4.33. Over all 12 seeds
  the results' sd is 0.505 against an SE of 0.486 (chi-square 11.8 on 11 degrees of freedom, p =
  0.38), and a second pair is as close (9210 and 9212, 0.0025). Pooled: +3.57 ± 0.14 bb/100.
