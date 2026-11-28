# Huge pages and the Phase 6 trainer (27 Nov 2026, Manager Fred)

The Phase 6 game (200bb, rich, k200 built here), trainer.json with threads 4 and until 4M, the cloud
trainer contract (`blueprint --config ... --checkpoint-dir ... --threads 4`), in a 4-core x86 cloud
container (Xeon 2.1 GHz, THP "madvise"). Huge pages through glibc: GLIBC_TUNABLES=glibc.malloc.hugetlb=1
(about 3.75 of 8 GB ended up in huge pages). Order ABBA: plain, huge, huge, plain.

| Run | Train seconds to 4M | Iterations/s by session | Export + measure at 4M, s |
| --- | ---: | --- | ---: |
| plain | 298.2 | 12685, 16870, 14548 | 73.1 |
| huge | 272.5 | 14054, 18106, 16086 | 64.2 |
| huge2 | 285.0 | 13875, 16928, 15151 | 63.5 |
| plain2 | 340.4 | 11262, 14335, 12908 | 87.7 |

Means: plain 319.3 s, huge 278.8 s, 1.145 times as fast (huge won both pairs, 1.09 and 1.19; the
container's neighbours make runs vary by about 14%). A 6 GB random read-modify-write test gave 1.35.
Not used for the heads-up full run (saves about $2 to $4 there); worth it for six-max (Phase 8), and
madvising every big table in the trainer may give more than the glibc tunable's half.
