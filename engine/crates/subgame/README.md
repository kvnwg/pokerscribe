# subgame: river and turn solver (Phase 4)

A Rust solver for one river or turn spot. It is the successor of the Python river solver in
`app/solver`, with the same conventions (`docs/research/SOLVER.md`). Its input is a SPOT and
its output is a RESULT, both as `data/SPOT_FORMAT.md` defines them.

Status, 27 Nov 2026: every gate below passes on the 40 answer-key spots, at the default target
of 0.2% of the pot. Nothing in the app uses it yet.

| Gate | Result |
| --- | --- |
| River tree matches `app/solver/tree.py` on all 30 spots | Pass: 882 nodes, same players, actions, ends and chips. |
| Closed-form results (the half-street game, bet sizes 0.5, 0.75, 1 and 2) | Pass: the book's answer has 0 exploitability by our measure, and the solver finds its bluff share, call share and value. |
| Matches Phase 2 (`app/solver`) | Pass: at a 0.1% target the river EVs are at most 0.132% of the pot from `app/solver`'s. |
| Our exploitability of TexasSolver's river answers is TexasSolver's number, to the third decimal | Pass on all 30. It also equals `app/solver`'s number for the same answers within 0.00001% of the pot, and our values and bounds for them equal the ones stored in the keys (`checks.values`, `checks.oop_value_bounds`) to the sixth decimal. |
| River: exploitability under 0.5% of the pot on all 30 | Pass. |
| River: each player's EV within 0.5% of the pot of TexasSolver's (`checks.values` of the key) | Pass at the default target of 0.2% (largest gap 0.148%, r01), and our bounds on the true value meet the key's on all 30. Stopping at exactly 0.5% is not enough: see "Things to know", 1. |
| The 3 trivial spots pass their expected checks | Pass. |
| River speed: p95 under 400 ms at a 0.5% target | Pass: p50 2.1 ms, p95 6.0 ms. At the default of 0.2%: p50 3.4 ms, p95 9.7 ms. |
| Turn: all 10 under 0.5%, EVs within 0.5% of the pot of TexasSolver's | Pass (largest EV gap 0.275%, t10, where TexasSolver's own answer is 0.33% of the pot from the exact value: "Things to know", 2), and the bounds meet on all 10. |
| Our exploitability of TexasSolver's turn answers, against its own number | Recorded: ours is 0.18 to 0.49 higher (0.42% to 0.71% against 0.17% to 0.28%). The cause is found: "Things to know", 2. |
| Turn solve times | 103 to 349 ms a spot at a 0.5% target, 142 to 533 ms at 0.2% (whole decision, 4 threads). No target yet. |

## Use

```bash
cd engine
```

```bash
cargo build --release -p subgame
```

```bash
./target/release/subgame-solve ../data/answer_keys/spots/r05.json --out r05.jsonl
```

```
subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.2]
              [--max-iterations N] [--time-ms N] [--threads N]
```

| Option | Meaning | Default |
| --- | --- | --- |
| `<spot.json>` | A SPOT, river or turn. | |
| `--out FILE` | Where the RESULT goes. Without it: standard output. | |
| `--target-exploitability PCT` | Stop at or under this percent of the pot. 0 turns it off. | 0.2 |
| `--max-iterations N` | Stop after N iterations. | 10000 |
| `--time-ms N` | Stop when the next iteration and the last check would not fit in N ms. | no limit |
| `--threads N` | Threads for the river cards of a turn spot. River spots always use 1. | every core |

- The solve stops at the first limit it reaches. At least one iteration always runs.
- The RESULT is plain JSON Lines: the header, then one line per decision node in the order of
  `spots.decision_nodes`. A turn RESULT is 2.5 to 6 MB; gzip it to store it as `<id>.jsonl.gz`.
- The header's `solver` block has `iterations`, `elapsed_s` (solve time), `exploitability_pot`
  (the exact exploitability of the final strategy, as a share of the pot),
  `exploitability_trace` (`[iteration, percent]` at every check), `converged` and `settings`.
- The header's `checks` block is the answer measured again as it is written (the node lines
  read back, six decimals): `exploitability_pot`, `filled_rows` (always 0), `values` (each
  player's EV in chips; the two add up to the pot), `oop_value_bounds` (`[low, high]` for
  the spot's true value: pot less IP's best response, and OOP's best response) and
  `expected_failures` (the spot's expected checks that fail). The measure is this crate's
  own best response, not `app/solver`'s, and turn spots get the numbers too: "Things to
  know", 4.
- A one-line summary goes to standard error: iterations, time, exploitability and both EVs.
- Exit code 0: solved. 1: the spot is bad or a file can't be read or written, with the reason
  on standard error. 2: the command line is wrong.

From Rust:

```rust
use subgame::{solve, Game, SolveConfig, Spot};

let game = Game::new(Spot::load("data/answer_keys/spots/r05.json".as_ref())?)?;
let solution = solve(&game, &SolveConfig::default());
// solution.strategy, .iterations, .elapsed_ms, .exploitability, .trace, .converged, .values
```

## Tests

```bash
cargo test --release -p subgame
```

The turn tests and the speed test are skipped in a debug build (`cargo test -p subgame`).
The tables below come from one more test:

```bash
cargo test --release -p subgame --test answer_keys report -- --ignored --nocapture
```

The tests read `data/answer_keys` (spots and TexasSolver's answers) and two fixtures made
from the Python solver: `tests/fixtures/river_trees.json` (`app/solver/tree.py`'s tree of the
30 river spots) and `tests/fixtures/phase2_values.json` (`app/solver`'s EVs on them at a 0.1%
target). After a change to `app/solver` or the spots, rebuild them from the repository root:

```bash
python engine/crates/subgame/tests/fixtures/make_river_trees.py
```

```bash
python engine/crates/subgame/tests/fixtures/make_phase2_values.py
```

| Test | Checks |
| --- | --- |
| `river_trees_match_app_solver` | Every node of the 30 river trees against `tree.py`: player, actions, kind of end, folder, chips put in. |
| `river_trees_match_the_answer_keys`, `turn_trees_match_the_answer_keys` | All 40 spots: the same decision nodes, actors and actions as the keys, in the same order, with exactly the combos that can be dealt at each node. |
| `every_spot_is_read_and_hashes_as_its_answer_key_says` | `spot_sha256` of all 40 spots. |
| `our_exploitability_of_texassolvers_river_answers_is_texassolvers` | 30 river keys: our number against TexasSolver's (within 0.0005 of a percent) and against `app/solver`'s (within 0.00001 of a percent). Our values and bounds for the key's answer against the stored `checks.values` and `checks.oop_value_bounds` (within 0.000002 chips). |
| `river_spots_solve_under_half_a_percent_with_texassolvers_values` | 30 river spots at the default target of 0.2%: exploitability under 0.5%, both EVs within 0.5% of the pot of the key's `checks.values`, our bounds meet the key's, the solver's own number equal to the checker's. Then again at a 0.5% target for exploitability. |
| `river_values_match_the_phase_2_solver` | 30 river spots at a 0.1% target: both EVs against `app/solver`'s. |
| `tests/closed_form.rs` | The half-street game of The Mathematics of Poker at four bet sizes, as the Phase 2 tests: the closed-form strategy is unexploitable by our measure, and the solver's bluff share, call share and value match it. |
| `trivial_spots_pass_their_expected_checks` | r01, r02, r03 at both targets. TexasSolver's answers pass too and random play fails. |
| `river_decisions_take_under_400_ms_at_p95` | Whole decisions at a 0.5% target; prints p50 and p95. |
| `turn_spots_solve_under_half_a_percent_with_texassolvers_values` | The 10 turn spots, as for the river. A turn key stores no values, so the value and bounds of TexasSolver's answer are worked out here. |
| `our_exploitability_of_texassolvers_turn_answers_is_recorded_and_explained` | "Things to know", 2. |
| `turn_values_match_deal_by_deal_enumeration` | A turn spot's EV against a plain loop over every (oop combo, ip combo, river card). |
| `a_turn_solve_is_the_same_on_one_thread_and_on_many` | Bit-for-bit. |
| `a_solve_repeats_exactly_and_stops_on_each_limit` | Target, iterations, time. |
| `the_binary_*` | The RESULT file (header fields and their order, `checks` against the node lines read back and against the key), standard output, and bad spots and bad command lines. |
| Unit tests (30) | Card removal against a pair-by-pair sum on every terminal, the tree's size rules, spot checks, Python's rounding and JSON, sha256, gzip, the expected checks. |

Also checked by hand, with the Python tools: `python -m tools.answer_keys validate` accepts
all 40 RESULT files from `subgame-solve`, and `tools.answer_keys.checks.river_checks`
(`app/solver`'s best response) gives exactly the header's `checks` for each of the 30 river
ones: the same exploitability to 8 decimals, the same values and bounds to 6.

## Results

Machine: the cloud session, Linux, 4 cores (Intel Xeon, 2.1 GHz), rustc 1.97.0, release build.
Measured 27 Nov 2026, when the default target went from 0.3% to 0.2%.

- Times are whole decisions: read the spot file, build the tree and tables, solve, write the
  RESULT text. Each is the median of 5 runs.
- "EV gap" is the distance between OOP's EV with our strategy and with TexasSolver's, in
  percent of the pot. IP's gap is the same, since the two EVs add up to the pot.
- TexasSolver prints no EVs. "TexasSolver's EV" is the value of its strategy: for a river
  spot the key's `checks.values.oop` (worked out by `app/solver`, and the same as our own
  calculation to the sixth decimal), for a turn spot our own exact calculation.

### River

Whole decision at a 0.5% target: **p50 2.1 ms, p95 6.0 ms**, worst 9.2 ms. At 0.2%, the default:
p50 3.4 ms, p95 9.7 ms, worst 13.4 ms. `subgame-solve` as a process, start-up included: p50
4.1 ms, p95 10.1 ms at 0.5%, and p50 5.3 ms, p95 13.3 ms at 0.2%. For scale, `app/solver` takes
p50 20 ms, p95 47 ms on the same spots at 0.5%.

| Spot | Combos (oop, ip) | Nodes | Iter. at 0.5% | ms | Expl. | EV gap | Iter. at 0.2% | ms | Expl. | EV oop | TexasSolver's EV oop | EV gap | TexasSolver's answer: its number | our number |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r01 | 3, 16 | 8 | 12 | 0.3 | 0.224% | 0.057% | 16 | 0.2 | 0.097% | 100.159 | 100.307 | 0.148% | 0.166% | 0.166% |
| r02 | 16, 6 | 8 | 24 | 0.3 | 0.397% | 0.570% | 32 | 0.4 | 0.170% | -0.340 | -0.222 | 0.117% | 0.124% | 0.124% |
| r03 | 105, 42 | 8 | 8 | 0.6 | 0.266% | 0.260% | 12 | 0.7 | 0.083% | 50.082 | 50.000 | 0.082% | 0.000% | 0.000% |
| r04 | 65, 54 | 8 | 40 | 1.5 | 0.487% | 0.279% | 70 | 2.2 | 0.179% | 40.823 | 40.904 | 0.080% | 0.205% | 0.205% |
| r05 | 65, 54 | 18 | 50 | 3.8 | 0.422% | 0.051% | 87 | 6.1 | 0.167% | 38.430 | 38.499 | 0.069% | 0.257% | 0.257% |
| r06 | 61, 47 | 8 | 28 | 1.0 | 0.321% | 0.181% | 36 | 1.2 | 0.184% | 47.077 | 47.162 | 0.085% | 0.289% | 0.289% |
| r07 | 61, 47 | 26 | 97 | 9.2 | 0.499% | 0.060% | 154 | 13.4 | 0.187% | 45.600 | 45.598 | 0.003% | 0.236% | 0.236% |
| r08 | 234, 112 | 8 | 40 | 3.9 | 0.459% | 0.153% | 78 | 6.7 | 0.191% | 37.268 | 37.296 | 0.028% | 0.296% | 0.296% |
| r09 | 78, 61 | 8 | 63 | 2.4 | 0.470% | 0.033% | 109 | 3.7 | 0.191% | 30.773 | 30.773 | 0.000% | 0.266% | 0.266% |
| r10 | 100, 53 | 10 | 45 | 2.5 | 0.483% | 0.063% | 70 | 3.6 | 0.156% | 10.902 | 10.956 | 0.054% | 0.209% | 0.209% |
| r11 | 66, 63 | 12 | 78 | 4.0 | 0.455% | 0.191% | 122 | 5.8 | 0.190% | 26.761 | 26.801 | 0.040% | 0.298% | 0.298% |
| r12 | 51, 81 | 8 | 36 | 1.5 | 0.484% | 0.262% | 63 | 2.2 | 0.200% | 43.824 | 43.794 | 0.031% | 0.297% | 0.297% |
| r13 | 61, 58 | 10 | 50 | 2.1 | 0.404% | 0.104% | 87 | 3.4 | 0.179% | 6.122 | 6.166 | 0.044% | 0.266% | 0.266% |
| r14 | 61, 58 | 8 | 36 | 1.3 | 0.415% | 0.159% | 50 | 1.7 | 0.165% | 9.602 | 9.669 | 0.067% | 0.147% | 0.147% |
| r15 | 62, 66 | 12 | 45 | 2.5 | 0.471% | 0.304% | 70 | 3.6 | 0.165% | 15.202 | 15.343 | 0.140% | 0.227% | 0.227% |
| r16 | 84, 79 | 10 | 36 | 2.2 | 0.447% | 0.125% | 63 | 3.4 | 0.172% | 53.992 | 53.974 | 0.018% | 0.232% | 0.232% |
| r17 | 66, 44 | 24 | 56 | 5.4 | 0.360% | 0.300% | 70 | 6.3 | 0.185% | -0.218 | -0.107 | 0.111% | 0.154% | 0.154% |
| r18 | 222, 185 | 8 | 36 | 4.1 | 0.471% | 0.033% | 63 | 6.5 | 0.181% | 42.960 | 42.966 | 0.006% | 0.273% | 0.273% |
| r19 | 54, 63 | 8 | 50 | 1.7 | 0.462% | 0.301% | 78 | 2.4 | 0.180% | 81.834 | 81.864 | 0.029% | 0.165% | 0.165% |
| r20 | 83, 43 | 10 | 45 | 2.1 | 0.468% | 0.504% | 63 | 2.6 | 0.172% | -0.262 | -0.195 | 0.067% | 0.188% | 0.188% |
| r21 | 299, 230 | 8 | 32 | 4.8 | 0.450% | 0.132% | 50 | 6.9 | 0.199% | 39.696 | 39.741 | 0.045% | 0.185% | 0.185% |
| r22 | 52, 51 | 10 | 50 | 1.9 | 0.494% | 0.361% | 97 | 3.2 | 0.182% | 68.536 | 68.585 | 0.049% | 0.300% | 0.300% |
| r23 | 62, 66 | 8 | 28 | 1.2 | 0.469% | 0.135% | 40 | 1.5 | 0.193% | 26.548 | 26.661 | 0.112% | 0.283% | 0.283% |
| r24 | 84, 79 | 16 | 70 | 6.0 | 0.446% | 0.023% | 122 | 9.7 | 0.161% | 55.575 | 55.596 | 0.021% | 0.238% | 0.238% |
| r25 | 231, 198 | 10 | 36 | 5.5 | 0.418% | 0.005% | 56 | 7.9 | 0.166% | 42.875 | 42.866 | 0.009% | 0.258% | 0.258% |
| r26 | 66, 53 | 12 | 36 | 2.0 | 0.452% | 0.393% | 50 | 2.6 | 0.171% | -0.241 | -0.240 | 0.001% | 0.245% | 0.245% |
| r27 | 100, 53 | 8 | 36 | 1.7 | 0.421% | 0.347% | 50 | 2.1 | 0.174% | 22.047 | 22.168 | 0.121% | 0.131% | 0.131% |
| r28 | 78, 61 | 10 | 78 | 3.5 | 0.455% | 0.079% | 109 | 4.6 | 0.193% | 17.195 | 17.245 | 0.050% | 0.192% | 0.192% |
| r29 | 58, 61 | 14 | 56 | 3.3 | 0.383% | 0.177% | 78 | 4.3 | 0.195% | 94.483 | 94.540 | 0.057% | 0.203% | 0.203% |
| r30 | 66, 54 | 8 | 56 | 1.9 | 0.361% | 0.138% | 78 | 2.4 | 0.165% | 47.770 | 47.828 | 0.058% | 0.180% | 0.180% |

The last two columns are TexasSolver's own exploitability and ours for the same strategy.

### Turn

4 threads. Whole decision at a 0.5% target: p50 167 ms, p95 349 ms. At 0.2%: p50 244 ms, p95
533 ms. On 1 thread: p50 353 ms, p95 794 ms at 0.5%, and p50 503 ms, p95 1,333 ms at 0.2%.
The times move by about 10% from run to run on this machine.

| Spot | Combos (oop, ip) | Nodes | Iter. at 0.5% | ms | ms, 1 thread | Expl. | EV gap | Iter. at 0.2% | ms | ms, 1 thread | Expl. | EV oop | TexasSolver's EV oop | EV gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| t01 | 71, 49 | 1160 | 70 | 167 | 326 | 0.435% | 0.044% | 109 | 244 | 503 | 0.166% | 32.721 | 32.714 | 0.007% |
| t02 | 64, 53 | 1160 | 63 | 152 | 297 | 0.465% | 0.062% | 97 | 204 | 426 | 0.188% | 45.865 | 45.874 | 0.009% |
| t03 | 72, 73 | 1736 | 97 | 349 | 794 | 0.454% | 0.102% | 173 | 533 | 1333 | 0.191% | 45.740 | 45.788 | 0.048% |
| t04 | 102, 51 | 1160 | 56 | 161 | 353 | 0.483% | 0.174% | 87 | 240 | 488 | 0.164% | 8.901 | 8.885 | 0.016% |
| t05 | 58, 43 | 1160 | 40 | 103 | 184 | 0.448% | 0.019% | 63 | 142 | 270 | 0.184% | 40.652 | 40.667 | 0.015% |
| t06 | 57, 62 | 1736 | 50 | 179 | 369 | 0.467% | 0.183% | 78 | 263 | 557 | 0.161% | 54.760 | 54.825 | 0.065% |
| t07 | 75, 48 | 1932 | 87 | 304 | 659 | 0.441% | 0.281% | 137 | 432 | 1054 | 0.183% | 40.282 | 40.430 | 0.149% |
| t08 | 63, 39 | 1160 | 63 | 129 | 262 | 0.461% | 0.020% | 97 | 194 | 377 | 0.156% | 15.544 | 15.533 | 0.010% |
| t09 | 66, 65 | 1736 | 78 | 259 | 624 | 0.437% | 0.005% | 122 | 430 | 941 | 0.167% | 7.302 | 7.329 | 0.027% |
| t10 | 63, 50 | 2320 | 63 | 262 | 580 | 0.434% | 0.164% | 97 | 362 | 832 | 0.167% | 0.107 | -0.167 | 0.275% |

The 1-thread times are the median of 3 runs and vary more from run to run than the others.

### TexasSolver's turn answers

| Spot | TexasSolver's number | Our number (exact card removal) | Difference | Its arithmetic redone on our tree |
| --- | ---: | ---: | ---: | ---: |
| t01 | 0.264% | 0.504% | +0.240 | 0.264% |
| t02 | 0.235% | 0.482% | +0.247 | 0.235% |
| t03 | 0.283% | 0.693% | +0.411 | 0.283% |
| t04 | 0.202% | 0.454% | +0.252 | 0.202% |
| t05 | 0.221% | 0.552% | +0.331 | 0.221% |
| t06 | 0.245% | 0.710% | +0.465 | 0.245% |
| t07 | 0.210% | 0.703% | +0.493 | 0.210% |
| t08 | 0.221% | 0.447% | +0.227 | 0.221% |
| t09 | 0.233% | 0.417% | +0.184 | 0.233% |
| t10 | 0.165% | 0.611% | +0.446 | 0.165% |

### Wider than the keys

Not a gate. r05's tree (K7249, two bet sizes and a raise size for IP, 3 raises) with every combo
for both players (1,081 each), whole decision, median of 3 runs: 75 ms to 0.5%, 101 ms to 0.3%
and 123 ms to 0.2%. (A first run on 26 Nov 2026, on a spot like it that wasn't kept, took 88 ms
to 0.5% and 131 ms to 0.3%.) Every combo for both players on the turn K724 (1,128 each, 1,160
nodes) solves to 0.5% in 2.0 s on 4 threads (one run, 26 Nov 2026).

## Things to know

1. **The EV gate needs a tighter target than 0.5%.** A strategy that is 0.5% exploitable can
   still be up to 1% of the pot from the game's value, because the measure is the average of
   two players' gains and one of them can hold nearly all of it. Stopping at exactly 0.5%,
   two river spots miss the EV gate: r02 (0.570%) and r20 (0.504%). In both, OOP's range is
   weak and its early bluffs are still in the average strategy. At the default target of 0.2%
   every spot passes, with the largest gap 0.148% (r01). The default was 0.3% until 27 Nov
   2026. That passes too (largest gap 0.281%, r02), but against the Python reference
   (`docs/research/PHASE4.md`) r02 was 0.498% of the pot off, 0.002% inside the gate, and
   0.2% costs little time. So the tests check exploitability at both targets, EVs at 0.2%,
   and speed at 0.5% as asked. If one setting must pass everything, use the default.

2. **TexasSolver's turn answers are solved for a slightly different game.** By our exact
   measure they are 0.42% to 0.71% exploitable, not the 0.17% to 0.28% TexasSolver reports.
   The cause: where the river is dealt, TexasSolver gives each card the weight 1/46 (52 cards
   less the board's 4 and one hand's 2). But only 44 cards can come for any two hands that are
   dealt together, so each should weigh 1/44. Every line that sees a river then counts 44/46
   of what it is worth next to a fold on the turn. How this was checked: redoing TexasSolver's
   arithmetic on our tree (weight 1/46, payoffs counted from half the pot each so that they
   add up to 0) gives its number to the third decimal on all 10 spots. The answers are still
   close to right: by our measure their EVs are within 0.3% of the pot of ours. But a turn key
   is a looser reference than its header says, and a solver should not be asked to match
   TexasSolver's turn frequencies closely. The river keys are not affected. The 1/46 began
   as a guess at TexasSolver's rule; what is shown here is only that the guess reproduces
   its numbers. Its source was not read or used.

3. **The Python solver and this one part ways on exact ties.** They run the same method in
   the same order, and their strategies agree to rounding on iterations 1 to 3 of r05 and r24
   and after 100 iterations of r07 and r21 (same exploitability to 8 decimals). On r05 and
   r24 they differ from iteration 4 or 5: a combo has two actions worth exactly the same (the
   nut flush calling or raising all in once every hand folds to the raise), the two programs
   add the same numbers in a different order, and the last bit decides which action gets the
   regret. Both still converge. It means strategies can't be compared bit for bit between the
   two, only exploitability and values.

4. **The `checks` block is this crate's measure, on both streets.** In TexasSolver's keys
   `checks` holds `app/solver`'s numbers, and `null` on turn spots because `app/solver` has
   no turn checker. `subgame-solve` fills the block itself, for river and turn spots, with its
   own exact best response on the answer as written (`data/SPOT_FORMAT.md` says so since
   this crate was added). On river answers the two measures give the same numbers (the
   tests, and the check by hand above), and `python -m tools.answer_keys recheck` puts
   `app/solver`'s in their place if wanted. On turn answers the other exact measure is
   `tools/answer_keys/values.py`, written separately, in Python: the two give the same
   exploitability to the third decimal on all ten turn spots (`docs/research/PHASE4.md`).
   The check costs under 0.3 ms on a river spot and 7 to 11 ms on a turn
   spot.

5. **Spot checks differ from `validate_spot` in three places.** `range_text` is not expanded
   and compared with `ranges` (`ranges` is the range). Raise sizes under 0.5 are accepted: the
   min-raise rule of the format covers them, and a unit test checks it. And three size
   options that `app/solver` got on 26 Nov 2026 (`reraises`, `allin_within`, `exact` in
   `BetSizes`) are refused with a message. `data/SPOT_FORMAT.md` doesn't define them and no
   answer-key spot uses them, but the Python tools would read them from a spot and build a
   different tree, so passing over them silently would be wrong. Both fixtures were rebuilt
   with that version of `app/solver` and came out the same, byte for byte.

6. **Not done.** Suit isomorphism (optional in the brief). Writing gzip (`--out x.jsonl.gz`
   is refused with a message). Single precision and SIMD: everything is `f64`.

## How it works

| File | What |
| --- | --- |
| `src/spot.rs` | Reads and checks a SPOT. Ranges keep the file's order. `spot_sha256` as `spots.spot_hash`. |
| `src/tree.rs` | The betting tree. One street follows `app/solver/tree.py` line by line: the same sizes, caps, min-raise rule, rounding and order. A turn spot gets a chance node after every way the turn ends without a fold, with one branch per card left (2c 2d 2h 2s 3c ... As): a river street with pot `pot + 2 * called` and stack `stack - called`, or a plain showdown when the turn call was all in. |
| `src/game.rs` | Ranges as combo weight vectors, and the value of every end of the hand. |
| `src/cfr.rs` | Discounted CFR and `solve`. |
| `src/exploit.rs` | Exact best response, strategy values, exploitability. |
| `src/result.rs` | Writes a RESULT, reads one (plain or gzipped) as a strategy on our tree, and works out the header's `checks`. |
| `src/expected.rs` | The expected checks, with a small pattern matcher for node keys (no `regex` crate). |
| `src/pyfmt.rs`, `src/sha256.rs`, `src/gz.rs` | Python's `round` and `json.dumps`, sha256, and gunzip, so that only serde, serde_json and rayon are needed. |
| `src/bin/subgame-solve.rs` | The binary. |

- **Card removal.** A combo meets only the opposing combos it shares no card with. Their
  total reach is: all of them, less those holding my first card, less those holding my second
  card, plus the one holding both. That is one pass over the opposing range with 52 per-card
  sums, for every combo at once.
- **Showdowns.** Both ranges are sorted by hand strength once per board (the `eval` crate).
  A showdown then walks the two sorted lists together, weakest first for the reach each
  combo beats and strongest first for the reach it loses to, keeping the same per-card sums
  for the combos passed so far. O(n log n) to set up, O(n) per showdown per iteration.
- **Discounted CFR.** Alpha 1.5, beta 0, gamma 2, players updated in turn, the average
  strategy returned: as `app/solver/cfr.py`. Regrets and strategy sums are stored
  `[node][combo][action]`. One update of a player is one walk of the tree for all its combos.
- **Stopping.** Exploitability is checked at iteration 8 and then every `max(4, t / 8)`
  iterations. The final number is always the exact exploitability of the strategy returned.
- **Turn.** A chance node deals every card left. For each card the opponent's combos that
  hold it are dropped and the rest weigh 1/44; the player's combos that hold it are worth 0
  there. Each of the 48 boards has its own sorted showdown lists. RESULT nodes after a river
  card list only the combos that can be held.
- **Threads.** On a turn spot an update is three steps: walk the turn's few nodes to note the
  reaches where the river is dealt, walk every river card in parallel (each card owns its
  slices of the storage), then walk the turn's nodes again with the rivers' values. The
  values are added in card order, so the answer is the same for any number of threads.
- **Payoffs and exploitability.** As `app/solver/exploitability.py`: the winner takes the pot
  plus what the loser put in since the spot started, the loser loses that, a split gives each
  half the pot. Exploitability is (best response as OOP + best response as IP - pot) / 2.

## Next

1. The same solver on flop spots: another chance node, and suit isomorphism starts to pay.
2. Depth-limited solving, where the leaves are values and not showdowns (Phase 4's other half).
3. Wider ranges and bigger trees in the timing set, once Phase 3 gives real ranges.
4. If turn answer keys are needed as a tight reference, solve them again with a solver that
   weighs river cards 1/44 (this one, checked against its own exact best response).
