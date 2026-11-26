# cfr: the CFR core

Counterfactual regret minimization for PokerScribe's solver-based agent (Modicum first, then
Pluribus). The crate has no dependencies. The test games live next to it in `../toygames`.

## What is in it

- `Game` trait (`src/game.rs`): n players, chance nodes with explicit probabilities, information
  set keys (`u64`), legal actions, terminal utilities. Lists are written into buffers the caller
  owns. Optional hooks: `sample_chance` (deal without listing the deck) and `prune_exempt` (no
  pruning on the last betting round, as in Pluribus).
- Full-width solvers (`Cfr`, `src/cfr.rs`): `Variant::Vanilla`, `CfrPlus`, `Linear`, and
  `Discounted { alpha, beta, gamma }` with `Variant::DCFR` = alpha 1.5, beta 0, gamma 2. Updates
  alternate between players, as in OpenSpiel's `CFRSolver`.
- Monte Carlo CFR (`Mccfr`, `src/mccfr.rs`), configured with `MccfrConfig`:
  - `Sampling::External` and `Sampling::Outcome { epsilon }` (`Sampling::OUTCOME` is epsilon 0.6).
  - `.linear(interval, until)`: linear weighting as Pluribus did it. Every `interval` iterations,
    up to iteration `until`, regrets and strategy sums are multiplied by k / (k + 1).
  - `.pruning(warmup, threshold, probability)`: Pluribus-style negative-regret pruning (external
    sampling only). After `warmup` iterations, a traversal is pruned with probability
    `probability`, and it skips the traverser's actions whose regret is below `threshold`,
    except actions that end the game and nodes the game marks exempt.
  - `.regret_floor(x)`: regrets never go below `x` (Pluribus used -310 million).
- Evaluation (`src/eval.rs`): `expected_values`, `best_response_value`, `nash_conv`,
  `exploitability` (NashConv / players, OpenSpiel's definition). All exact, for games small enough
  to walk.
- `Solver` trait over every solver: `iterate`, `run`, `average_policy`, `info_sets`,
  `nodes_touched`.

```rust
use cfr::{exploitability, Cfr, Mccfr, MccfrConfig, Sampling, Solver, Variant};
use toygames::Leduc;

let mut dcfr = Cfr::new(Leduc::new(2), Variant::DCFR);
dcfr.run(1_000);
let expl = exploitability(&Leduc::new(2), &dcfr.average_policy());

let cfg = MccfrConfig::new(Sampling::External, 7).linear(100, 100_000);
let mut es = Mccfr::new(Leduc::new(2), cfg);
es.run(1_000_000);
```

## Built for scale later

- Regrets and strategy sums are flat `Vec<f64>`s. An `InfoTable` maps each key to a dense index
  and a slice (offset, action count). MCCFR adds information sets the first time it reaches them,
  so it never needs the whole tree. `reserve` pre-sizes the table.
- No allocation in steady state: tree walks take per-depth buffers and put them back. A test
  (`tests/no_alloc.rs`) counts allocations with a custom global allocator and requires zero for
  warmed-up iterations of every solver.
- Deterministic: the crate has its own xoshiro256++ generator, so a seed gives the same run bit for
  bit (`tests/determinism.rs`) on any machine and with any dependency versions.
- Single-threaded for now. Parallel MCCFR (Pluribus ran on 64 cores with shared regrets) and
  smaller regret types (Pluribus stored them as integers) are the obvious next steps.

## Results

All numbers are from `cargo run --release -p cfr --example bench` on the 4-core cloud container
these were built in, one thread. Exploitability is NashConv divided by the number of players.

### Leduc hold'em against OpenSpiel

`tools/reference/openspiel_leduc.py` runs OpenSpiel 2.0.2's vanilla CFR (the Python `CFRSolver`;
the C++ one gives identical numbers) and stores the result in `tests/data/openspiel_leduc.json`.
Both games have 936 information sets (468 per player) and the same NashConv for the uniform policy.

| Iterations | OpenSpiel exploitability | Ours | OpenSpiel value (player 0) | Ours |
|---:|---:|---:|---:|---:|
| 1 | 2.373611111111 | 2.373611111111 | -0.078125000000 | -0.078125000000 |
| 10 | 0.888578983169 | 0.888578983169 | -0.444830940935 | -0.444830940935 |
| 100 | 0.095716353005 | 0.095716353005 | -0.113975303068 | -0.113975303068 |
| 1000 | 0.011817810260 | 0.011817810260 | -0.087223602948 | -0.087223602948 |

The test (`tests/leduc_openspiel.rs`) requires agreement to 1e-12. Matching at iteration 1000
needed the same floating-point order as OpenSpiel: one reach probability per player (not one
running product) and regret matching that divides by the sum instead of multiplying by its
inverse. Before those two changes the runs agreed to 1e-15 up to iteration 100, then drifted
apart by about a factor of 1000 every 100 iterations, to 2e-5 relative at iteration 1000. CFR
amplifies rounding differences; the algorithm was already the same.

OpenSpiel's equilibrium value for player 0 (C++ CFR+, 20,000 iterations, exploitability 4e-6) is
-0.085606. Our CFR+ and DCFR reach it within 1e-5:

| Leduc | 10 | 100 | 1,000 | 10,000 | value at 10,000 | iterations/s |
|---|---:|---:|---:|---:|---:|---:|
| CFR | 8.89e-1 | 9.57e-2 | 1.18e-2 | 2.04e-3 | -0.085807 | 2,079 |
| CFR+ | 6.10e-1 | 1.34e-2 | 2.57e-4 | 6.46e-6 | -0.085606 | 1,564 |
| Linear CFR | 7.21e-1 | 3.45e-2 | 4.83e-3 | 1.11e-3 | -0.085622 | 1,897 |
| DCFR | 7.79e-1 | 7.75e-3 | 1.43e-4 | 5.70e-6 | -0.085606 | 1,891 |

| Leduc | 10^4 | 10^5 | 10^6 | 10^7 | iterations/s |
|---|---:|---:|---:|---:|---:|
| ES-MCCFR | 3.18e-1 | 8.22e-2 | 2.05e-2 | 5.92e-3 | 549,000 |
| ES, linear to 10^5 | 2.54e-1 | 7.13e-2 | 2.15e-2 | 7.91e-3 | 552,000 |
| ES, pruning | 3.18e-1 | 7.38e-2 | 2.15e-2 | 1.28e-2 | 580,000 |
| OS-MCCFR | 1.08 | 4.76e-1 | 1.40e-1 | 6.80e-2 | 1,453,000 |
| OS, linear to 10^7 | 1.02 | 4.46e-1 | 1.38e-1 | 1.44e-1 | 1,462,000 |

One full-width iteration walks the tree once per player (about 16,000 nodes); one MCCFR iteration
is one sampled traversal per player. Every solver runs at 22 to 34 million nodes per second.

### Kuhn poker, 2 players

Game value -1/18 = -0.055556 for player 0. The tests (`tests/kuhn2.rs`) require exploitability
under 0.001 and value within 0.001 for every solver:

| Solver | Iterations in the test | Exploitability then | Speed (iterations/s) |
|---|---:|---:|---:|
| CFR | 2,000 | 5.4e-4 | 305,000 |
| CFR+ | 1,000 | 8.7e-5 | 306,000 |
| Linear CFR | 1,000 | 9.4e-5 | 294,000 |
| DCFR | 1,000 | 1.5e-4 | 301,000 |
| ES-MCCFR | 2,000,000 | 5.4e-4 | 2,190,000 |
| ES, linear to 10^5 | 2,000,000 | 3.0e-4 | 2,216,000 |
| ES, pruning (warm-up 10^4, threshold -10^4) | 8,000,000 | 2.1e-4 | 2,251,000 |
| OS-MCCFR, linear to 10^7 | 60,000,000 | 3.1e-4 | 2,725,000 |

The Monte Carlo budgets were chosen so four different seeds all pass, not just the one in the
test. Worst of the four: 6.3e-4, 6.5e-4, 3.7e-4 and 7.2e-4. Outcome sampling needs by far the
most iterations: it hovers around 1e-3 for tens of millions of them, and some seeds get worse
between 2 x 10^7 and 6 x 10^7 before improving.

### Kuhn poker, 3 players

There is no convergence guarantee with three players, but NashConv falls in practice
(`tests/kuhn3.rs`). Exploitability:

| Kuhn 3p | 10^4 | 10^5 | 10^6 | 10^7 | iterations/s |
|---|---:|---:|---:|---:|---:|
| ES-MCCFR | 8.61e-3 | 2.54e-3 | 1.85e-3 | 5.31e-4 | 859,000 |
| ES, linear to 10^5 | 1.53e-2 | 3.85e-3 | 8.96e-4 | 2.04e-4 | 826,000 |
| ES, pruning | 8.61e-3 | 3.28e-3 | 1.12e-3 | 6.09e-4 | 1,002,000 |
| OS-MCCFR | 5.96e-2 | 9.72e-3 | 1.78e-2 | 4.63e-4 | 1,172,000 |
| OS, linear to 10^7 | 2.45e-2 | 8.13e-3 | 1.02e-2 | 1.13e-2 | 1,196,000 |

Full-width CFR on 3-player Kuhn: 1.2e-4 after 10,000 iterations, DCFR 1.3e-8.

## What the numbers say

- On small games, CFR+ and DCFR beat everything else by orders of magnitude. DCFR is slightly
  ahead of CFR+ here and is the natural default for Modicum-style depth-limited solving.
- External sampling is the Monte Carlo method to build on (Pluribus used it). Outcome sampling is
  much noisier. On 3-player Kuhn it is not even monotone: OpenSpiel's own C++ outcome sampling
  does the same (one seed goes from 2.2e-3 at 10^6 to 1.0e-2 at 4 x 10^6), so this is the
  algorithm, not this code. Linear weighting helps early but hurts if it runs too long with
  outcome sampling: the average then leans on the most recent iterates, which are noisy (Leduc
  and 3-player Kuhn above). Pluribus only applied it for the first 400 minutes. Variance
  reduction with baselines (VR-MCCFR) would be the fix if outcome sampling is ever needed.
- Pruning saves little on these games: they have few clearly bad actions with subtrees behind
  them, Leduc's second round is exempt, and an aggressive threshold (-1 or -1000 on Kuhn) slows
  convergence per iteration. It is there for big trees, where Pluribus reported large speedups.
  Choose the threshold relative to the regret scale of the game.
- Exploitability here is exact. Evaluation walks the full tree, so it is limited to games of
  roughly Leduc's size; bigger games will need sampled or abstracted best responses.

## Running

From `engine/`:

```
cargo test --release            # everything, about 30 s
cargo test                      # debug build: skips the 7 long Monte Carlo tests
cargo run --release -p cfr --example bench              # all tables above, about 3 minutes
cargo run --release -p cfr --example bench -- leduc es  # one game, one solver
```

To regenerate the OpenSpiel reference (about 2 minutes, mostly the Python CFR):

```
python3 -m venv /tmp/osenv && /tmp/osenv/bin/pip install open_spiel
/tmp/osenv/bin/python tools/reference/openspiel_leduc.py
```
