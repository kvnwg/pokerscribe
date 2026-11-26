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
  - `.threads(n)`: external sampling on `n` threads that share the tables without locks, as
    Pluribus ran it. One thread (the default) is deterministic. See "Threads" below.
  - `.compact(scale)`: regrets as 32-bit integers with a floor in place of 64-bit floats. See
    "Integer regrets" below.
- Checkpoints (`src/checkpoint.rs`, `src/signal.rs`): `Mccfr::save`, `Mccfr::resume`, and
  `Mccfr::train`, which runs with a save every N minutes, at the end, and on SIGTERM. See
  "Checkpoints" below.
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

## Built for scale

- Regrets and strategy sums are flat per-action arrays. An index maps each information set key to
  its slots (offset, action count). MCCFR adds information sets the first time it reaches them,
  so it never needs the whole tree. `reserve` pre-sizes the index and the arrays.
- The Monte Carlo solver's arrays grow in blocks that double (4,096 slots, then 8,192, and so
  on) and never move, so threads can keep reading while the arrays grow (`src/store.rs`). Its
  index is a hash table in 1,024 parts: looking a key up takes no lock, adding a key locks one
  part (`src/shared.rs`).
- No allocation in steady state: tree walks take per-depth buffers and put them back. A test
  (`tests/no_alloc.rs`) counts allocations with a custom global allocator and requires zero for
  warmed-up iterations of every solver.
- Deterministic on one thread: the crate has its own xoshiro256++ generator, so a seed gives the
  same run bit for bit (`tests/determinism.rs`) on any machine and with any dependency versions.
  `tests/golden.rs` pins 15 runs (3 games, 5 settings) to fingerprints recorded before the
  solver learned to use threads: one thread with float regrets is still exactly that run.

## Checkpoints

A multi-day run on a machine that can be taken away has to survive being stopped.

```rust
use cfr::{signal, Checkpoints, Mccfr, MccfrConfig, Sampling, Stop};

signal::watch_sigterm()?;                       // SIGTERM sets a flag; the process lives on
let saves = Checkpoints::new("blueprint.ckpt").every_minutes(10.0);
let mut solver = match Mccfr::resume(game, saves.path()) {
    Ok(solver) => solver,                       // continue the saved run
    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
        Mccfr::new(game, MccfrConfig::new(Sampling::External, 1).threads(64).compact(1.0))
    }
    Err(e) => return Err(e),                    // damaged: don't start over silently
};
if solver.train(1_000_000_000, Some(&saves))?.stop == Stop::Requested {
    // SIGTERM: the state is on disk. Exit; the next start resumes.
}
```

- **What is saved:** the settings, the iteration count, every thread's random generator state
  and counters, and every information set's key, regrets and strategy sums as raw bits.
- **Bit for bit:** a run on one thread that is saved, loaded and continued ends exactly where the
  uninterrupted run with the same seed ends. `tests/checkpoint.rs` checks every regret, strategy
  sum, generator state and counter, for external and outcome sampling, with linear weighting,
  pruning, a floor, and integer regrets. A run on several threads is saved and resumed whole
  too, but it depends on timing, so it has no "same run" to compare with.
- **A crash never costs the last checkpoint:** `save` writes `<path>.tmp`, flushes it to the
  disk, then renames it over `<path>`, which the file system does in one step. `<path>` is
  always the old checkpoint or the new one, whole. The disk needs room for two checkpoints.
- **Damage is noticed:** the file ends with a checksum. `resume` refuses a file that is cut
  short, altered, of another game (player count), or not a checkpoint, with an `InvalidData`
  error. A missing file is `NotFound`, so "start fresh" and "something is wrong" stay apart.
- **Save every N minutes:** `Checkpoints::every_minutes(n)`. The threads finish their current
  traversal, the run is saved, and they go on. Saves change nothing about the run (tested).
- **SIGTERM:** after `signal::watch_sigterm()`, the signal sets a flag. `train` sees it after
  the current traversal, saves, and returns `Stop::Requested`. `tests/sigterm.rs` sends the
  process a real SIGTERM in the middle of a run and resumes it to the same end as an
  uninterrupted one. `signal::request_stop()` does the same by hand, and `watch_sigint()`
  covers Ctrl-C. No dependency: the handler is registered through the C library's `signal`.
- **Another machine:** `resume` keeps the saved thread count; `set_threads(n)` changes it.

The file is 19 bytes for each information set plus 16 bytes for each action slot (12 with
integer regrets). The format is in the module text of `src/checkpoint.rs`. Both arrays are
written front to back in large blocks, so saving runs at the speed of the disk:

| Wide, 2.69 million information sets | File | Save | Load |
|---|---:|---:|---:|
| Float regrets | 151.7 MB | 0.24 s (642 MB/s) | 0.19 s (800 MB/s) |
| Integer regrets | 126.6 MB | 0.28 s (444 MB/s) | 0.22 s (588 MB/s) |

Into memory instead of onto the disk, saving runs at 1.0 to 1.4 GB/s, so the disk is the limit.

**The 30-second warning has a size limit.** Google stops a Spot machine about 30 seconds after
SIGTERM. A save that isn't finished by then is lost, and the last timed checkpoint is what the
next start resumes from (it stays whole). What fits in the window is the disk's write speed
times about 25 seconds: 10 GB at 400 MB/s. A blueprint of 100 million information sets with 3
actions each and integer regrets is 5.5 GB. For a bigger one, either take a faster disk (a
local SSD) or accept losing up to one save interval of work on each shutdown. Check the save
time on the real machine before relying on it: `train` returns it (`TrainReport::longest_save`)
and the `scale` example prints it.

## Threads

`MccfrConfig::threads(n)` runs external sampling on `n` threads, as Pluribus did on 64 cores:

- The threads share the regret and strategy sum arrays and update them without locks. An update
  is "read, add, write", so two threads that update the same slot at the same moment can lose
  one of the two updates. Monte Carlo CFR tolerates that: the lost update is one noisy sample
  among millions. Nothing is ever torn: every value is one whole 32-bit or 64-bit word.
- Each thread has its own random stream (xoshiro256++ `jump`, streams 2^128 draws apart), its
  own buffers and its own counters, kept on separate cache lines.
- Iteration numbers come from one shared counter. For linear weighting the threads stop
  together at each discount, one thread applies it, and they go on, so the discount is exact.
- One thread takes the old path: same draws, same arithmetic, same bits (`tests/golden.rs`).
  Tests that need a repeatable run use one thread.
- Outcome sampling stays on one thread (`threads(2)` with it panics).

Speed, external sampling from scratch, on the 4-core cloud container (so "all cores" is 4 here):

| Game | Information sets | 1 thread | 2 threads | 4 threads (all cores) |
|---|---:|---:|---:|---:|
| Kuhn, 3 players | 48 | 879,000 it/s | 975,000 (1.11x) | 1,366,000 (1.55x) |
| Leduc, 2 players | 936 | 531,000 it/s | 613,000 (1.15x) | 929,000 (1.75x) |
| Leduc, 3 players | 25,600 | 197,000 it/s | 240,000 (1.22x) | 411,000 (2.08x) |
| Wide (Leduc betting, 300 cards) | 2,690,000 | 109,000 it/s | 197,000 (1.80x) | 371,000 (3.40x) |

- The bigger the game, the better the threads scale. On the toy games every thread writes the
  same few hundred regrets, so the cores spend their time passing the same cache lines around.
  "Wide" is a synthetic game (in `examples/scale.rs`) with enough information sets that the
  threads rarely meet, which is the blueprint's situation. Expect its row, not Kuhn's.
- One thread costs nothing against the code before threads: 2,193,000 against 2,126,000
  iterations/s on 2-player Kuhn, 838,000 against 862,000 on 3-player Kuhn, 550,000 against
  552,000 on Leduc, with identical exploitability at every checkpoint.
- The container is a shared machine and the figures move by about 15% between runs (4 threads
  on Leduc gave 1.75x to 2.07x).
- **Not measured: more than 4 cores.** The 64-core figure has to come from the rented machine:
  `cargo run --release -p cfr --example scale` prints these tables for 1, 2, 4 and all cores.

It still converges (`tests/parallel.rs`, 4 threads, 4 million iterations of Leduc, bound 2.5e-2
on exploitability and 5e-2 on the value; one thread is at about 1.05e-2 after the same work):

| Leduc, 4 threads, 4 million iterations | Exploitability | Value (equilibrium -0.085606) |
|---|---:|---:|
| ES-MCCFR | 1.30e-2 | -0.087267 |
| ES, linear to 400,000 | 1.10e-2 | -0.087053 |
| ES, linear, pruning | 1.11e-2 | -0.086784 |
| ES, integer regrets | 1.11e-2 | -0.087093 |

These are single runs and change a little every time, because the threads' timing does.

## Integer regrets

`MccfrConfig::compact(scale)` stores each regret as a 32-bit integer, `round(regret * scale)`,
in place of a 64-bit float: 4 bytes a slot, not 8. Pluribus did this to fit its blueprint in
memory.

- The integer never wraps. It stops at `regret_floor * scale` below if a floor is set (at
  -2^31 otherwise) and at 2^31 - 1 above.
- Picking `scale`: one typical regret update should be many units, and regrets times `scale`
  should stay well under two billion. A game with payoffs in whole chips can use 1, as Pluribus
  did. Kuhn and Leduc, whose payoffs are a few units, use 1,000 in the tests.
- With integer regrets Kuhn and Leduc pass the gates of the float ones (`tests/parallel.rs`):
  Kuhn 6.2e-4 and 7.2e-4 with linear weighting (gate 1e-3, value exact to 1e-3), Leduc 1.97e-2
  after a million iterations (floats: 2.05e-2).
- Strategy sums stay 64-bit floats.

Memory in use for each information set (`Mccfr::memory()`):

| Game | Information sets | Slots | Index | Regrets, float / integer | Strategy sums | Total, float / integer |
|---|---:|---:|---:|---:|---:|---:|
| Wide | 2,692,644 | 6,282,888 | 24.9 B | 18.7 / 9.3 B | 18.7 B | 62.3 / 52.9 B |
| Leduc, 3 players | 25,639 | 58,726 | 33.6 B | 18.3 / 9.2 B | 18.3 B | 70.2 / 61.0 B |
| Leduc, 2 players | 936 | 2,184 | 140.9 B | 18.7 / 9.3 B | 18.7 B | 178.3 / 168.9 B |
| Kuhn, 3 players | 48 | 96 | 2,730.7 B | 16.0 / 8.0 B | 16.0 B | 2,762.7 / 2,754.7 B |

- For each action slot: 16 bytes with float regrets, 12 with integer ones. An information set
  with `a` actions takes 16a or 12a bytes plus its share of the index.
- The index is 16 bytes a cell and a quarter to three quarters full, so 21 to 64 bytes for
  each information set, and never smaller than about 128 KB in all (that floor is the whole
  figure for Kuhn and most of it for 2-player Leduc).
- The arrays grow by doubling, so up to half of the address space they hold is untouched pages
  that take no memory. `Memory::reserved_bytes` reports it.
- Integer regrets save 15% in total here, because the strategy sums are now the bigger half.
  That is the next thing to shrink.

## Next steps for Phase 6

- Run `--example scale` on the rented machine: the thread table above stops at 4 cores.
- Smaller strategy sums. Pluribus kept the average strategy only for the first betting round
  and took snapshots of the current strategy for the others. That, or 32-bit sums, would bring
  a slot from 12 bytes to 8 or less.
- If the blueprint outgrows what the disk can take in 25 seconds, write the checkpoint from
  several threads into several files, or save only what changed.
- NUMA: on a two-socket machine the arrays should be spread over both sockets' memory.

## Results

All numbers in this section are from `cargo run --release -p cfr --example bench` on the 4-core
cloud container these were built in, one thread. Exploitability is NashConv divided by the number of players.

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
cargo test --release            # everything, about 50 s
cargo test                      # debug build: skips the 10 long Monte Carlo tests of this crate
cargo run --release -p cfr --example bench              # the Results tables, about 3 minutes
cargo run --release -p cfr --example bench -- leduc es  # one game, one solver
cargo run --release -p cfr --example scale              # threads, memory, checkpoint: 5 minutes
cargo run --release -p cfr --example scale -- wide      # one part: kuhn3, leduc, leduc3, wide,
                                                        # memory or checkpoint
```

To regenerate the OpenSpiel reference (about 2 minutes, mostly the Python CFR):

```
python3 -m venv /tmp/osenv && /tmp/osenv/bin/pip install open_spiel
/tmp/osenv/bin/python tools/reference/openspiel_leduc.py
```
