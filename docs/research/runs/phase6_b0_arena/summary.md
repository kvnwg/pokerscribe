# B0 against Rust agents in the arena

Made by `docs/research/runs/phase6_b0_arena.py`. Heads-up, 100 big blinds, blinds 50/100, B0 as
agent 0. Duplicate (each deal twice, seats swapped) and all-in equity unless the row says plain.
Speed is per CPU second of one process.

| Opponent | Deals | Hands | B0 bb/100 | SE | z | Plain SE | sd per deal | All-in hands adjusted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b0 | 400 | 800 | +0.00 | 0.00 |  | 39.71 | 0 | 4 |
| b0, plain | 1000 | 1000 | -42.06 | 32.47 | -1.3 | 34.90 | 1027 | 4 |
| b0 bet_size 0.5 | 1500 | 3000 | +2.91 | 3.89 | +0.7 | 14.06 | 150 | 8 |
| fold | 1000 | 2000 | +34.73 | 1.18 | +29.3 | 1.23 | 37 | 0 |
| call | 1000 | 2000 | +239.50 | 19.17 | +12.5 | 22.04 | 606 | 0 |
| tag | 3000 | 6000 | +8.15 | 5.62 | +1.4 | 7.66 | 308 | 10 |
| tag-loose | 3000 | 6000 | +2.49 | 7.36 | +0.3 | 8.61 | 403 | 13 |
| lbr-random | 1000 | 2000 | +157.70 | 34.26 | +4.6 | 38.09 | 1083 | 23 |
| lbr-call-or-raise | 1000 | 2000 | +362.63 | 53.07 | +6.8 | 65.13 | 1678 | 101 |
| jam | 1000 | 2000 | +8.10 | 20.08 | +0.4 | 32.54 | 635 | 42 |

B0 against itself in duplicate play is exactly 0: B0 is deterministic, so each deal's two hands
cancel (the report's 1e-15 is float noise).

| Opponent | Hands/s | ms per B0 instruction | B0 instructions per hand | Time outside B0 | Not legal as said | Always-wrong (simulate.check_advice) |
| --- | --- | --- | --- | --- | --- | --- |
| b0 | 12.4 | 28.9 | 2.78 | 0.1% | none | none |
| b0, plain | 7.1 | 54.7 | 2.57 | 0.0% | none | none |
| b0 bet_size 0.5 | 13.1 | 29.1 | 2.63 | 0.1% | none | none |
| fold | 91.4 | 21.9 | 0.50 | 0.1% | none | none |
| call | 4.6 | 69.7 | 3.11 | 0.0% | none | none |
| tag | 32.3 | 36.7 | 0.84 | 0.1% | none | none |
| tag-loose | 22.0 | 40.9 | 1.11 | 0.1% | none | none |
| lbr-random | 15.8 | 42.8 | 1.47 | 0.2% | none | all in 100bb deep preflop with AKo x3 |
| lbr-call-or-raise | 9.8 | 49.2 | 2.07 | 0.2% | none | all in 100bb deep preflop with AKo x6 |
| jam | 33.3 | 24.7 | 1.22 | 0.1% | none | none |

Time outside B0: the match's time less the time in `B0Player.act` (the arena, the other agent,
and crossing between Rust and Python).

The always-wrong instructions (the first of each match, up to 25), with the betting so far:

- lbr-random: AsKd on the BB, all in 100bb deep preflop with AKo: ALL IN (200) after opp call B0 raise 450 opp raise 3061 (played ['raise', 10000])
- lbr-random: KcAh on the BB, all in 100bb deep preflop with AKo: ALL IN (200) after opp call B0 raise 450 opp raise 5957 (played ['raise', 10000])
- lbr-random: KdAh on the BB, all in 100bb deep preflop with AKo: ALL IN (200) after opp call B0 raise 450 opp raise 5396 (played ['raise', 10000])
- lbr-call-or-raise: AsKh on the BB, all in 100bb deep preflop with AKo: ALL IN (200) after opp call B0 raise 450 opp raise 2642 (played ['raise', 10000])
- lbr-call-or-raise: AdKc on the BTN/SB, all in 100bb deep preflop with AKo: ALL IN (200) after B0 raise 250 opp raise 5646 (played ['raise', 10000])
- lbr-call-or-raise: AdKh on the BTN/SB, all in 100bb deep preflop with AKo: ALL IN (200) after B0 raise 250 opp raise 6218 (played ['raise', 10000])
- lbr-call-or-raise: KcAh on the BTN/SB, all in 100bb deep preflop with AKo: ALL IN (200) after B0 raise 250 opp raise 8721 (played ['raise', 10000])
- lbr-call-or-raise: AhKc on the BB, all in 100bb deep preflop with AKo: ALL IN (200) after opp call B0 raise 450 opp raise 7514 (played ['raise', 10000])
- lbr-call-or-raise: KdAc on the BB, all in 100bb deep preflop with AKo: ALL IN (200) after opp call B0 raise 450 opp raise 3642 (played ['raise', 10000])

Hands for an edge to be 2.5 SE at this sd per deal (hands = 2 x (2.5 sd / edge)^2):

| Opponent | sd per deal | Edge 5 bb/100 | Edge 10 bb/100 | Edge 20 bb/100 |
| --- | --- | --- | --- | --- |
| b0 bet_size 0.5 | 150 | 11,324 | 2,832 | 708 |
| fold | 37 | 700 | 176 | 44 |
| call | 606 | 183,774 | 45,944 | 11,486 |
| tag | 308 | 47,414 | 11,854 | 2,964 |
| tag-loose | 403 | 81,230 | 20,308 | 5,078 |
| lbr-random | 1083 | 586,766 | 146,692 | 36,674 |
| lbr-call-or-raise | 1678 | 1,408,332 | 352,084 | 88,022 |
| jam | 635 | 201,600 | 50,400 | 12,600 |

Profile, B0 against tag, 300 hands, 253 B0 instructions, 56.3 CPU seconds (cProfile slows Python down, so these are shares, not speeds):

| Part | Seconds | Share | Calls |
| --- | --- | --- | --- |
| B0Player.act (everything B0 does) | 56.34 | 100% | 253 |
| advise, with its own equity runs | 6.11 | 11% | 253 |
| sim_compute (the equity the advice is given) | 49.45 | 88% | 253 |
| equity (all Monte Carlo equity runs) | 53.05 | 94% | 526 |
| app_state (the GameState) | 0.03 | 0% | 253 |
| table (the simulator's Hand from the view) | 0.01 | 0% | 253 |
| check_advice (the always-wrong checks) | 0.06 | 0% | 253 |
| engine_action (instruction to nlhe action) | 0.00 | 0% | 253 |
| treys evaluations (hands.evaluate) | 0.19 | 0% | 10759 |
| Outside B0 (the arena, tag, crossing into Python) | 0.01 | 0% | |
