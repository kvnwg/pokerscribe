//! Several threads sharing the tables without locks, and regrets stored as
//! 32-bit integers: both still converge.
//!
//! A run on several threads depends on timing, so these tests check where
//! it ends up (exploitability, value), never an exact state. The bounds
//! leave room: on one thread, plain external sampling is at 2.1e-2 after
//! 10^6 iterations of Leduc and 5.9e-3 after 10^7.

mod common;

use cfr::{Game, Mccfr, MccfrConfig, RegretStorage, Sampling, Solver};
use common::{measure, run_state};
use toygames::{Kuhn, Leduc};

/// Leduc's value for player 0 (OpenSpiel, CFR+ to 4e-6).
const LEDUC_VALUE: f64 = -0.085606;

fn leduc(name: &str, cfg: MccfrConfig, iterations: u64, bound: f64) -> Mccfr<Leduc> {
    let game = Leduc::new(2);
    let mut solver = Mccfr::new(game, cfg);
    solver.run(iterations);
    assert_eq!(solver.iterations(), iterations, "{name}");
    assert_eq!(solver.info_sets(), 936, "{name}");
    let (expl, value) = measure(&game, &solver);
    println!("{name}: {iterations} iterations, exploitability {expl:.2e}, value {value:.6}");
    assert!(expl < bound, "{name}: exploitability {expl}");
    assert!(
        (value - LEDUC_VALUE).abs() < 2.0 * bound,
        "{name}: value {value}"
    );
    solver
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn four_threads_converge_on_leduc() {
    let es = MccfrConfig::new(Sampling::External, 1).threads(4);
    let solver = leduc("ES, 4 threads", es, 4_000_000, 2.5e-2);
    // Every thread did part of the work.
    assert!(solver.stats().nodes_touched > 4_000_000 * 10);
    // With linear weighting the threads stop together for every discount,
    // and with pruning each thread draws its own pruned traversals.
    let linear = es.linear(20_000, 400_000);
    leduc("ES linear, 4 threads", linear, 4_000_000, 2.5e-2);
    let pruned = linear.pruning(100_000, -10_000.0, 0.95);
    let solver = leduc("ES linear pruning, 4 threads", pruned, 4_000_000, 2.5e-2);
    let share = solver.stats().pruned_traversals as f64 / (2.0 * 3_900_000.0);
    assert!((share - 0.95).abs() < 0.01, "pruned share {share}");
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn four_threads_with_integer_regrets_converge_on_leduc() {
    let cfg = MccfrConfig::new(Sampling::External, 1)
        .threads(4)
        .compact(1_000.0)
        .regret_floor(-300_000.0);
    leduc("ES, 4 threads, i32", cfg, 4_000_000, 2.5e-2);
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn integer_regrets_pass_the_gates_of_the_float_ones() {
    // Kuhn: the gate of tests/kuhn2.rs, same seed and budget as the floats.
    let game = Kuhn::new(2);
    for (name, cfg, iterations) in [
        (
            "ES i32",
            MccfrConfig::new(Sampling::External, 1).compact(1_000.0),
            2_000_000,
        ),
        (
            "ES linear i32",
            MccfrConfig::new(Sampling::External, 1)
                .linear(100, 100_000)
                .compact(1_000.0),
            2_000_000,
        ),
    ] {
        let mut solver = Mccfr::new(game, cfg);
        solver.run(iterations);
        let (expl, value) = measure(&game, &solver);
        println!("Kuhn {name}: exploitability {expl:.2e}, value {value:.6}");
        assert!(expl < 1e-3, "{name}: exploitability {expl}");
        assert!((value + 1.0 / 18.0).abs() < 1e-3, "{name}: value {value}");
    }
    // Leduc on one thread: as good as the floats at the same budget.
    let es = MccfrConfig::new(Sampling::External, 1);
    leduc("ES i32", es.compact(1_000.0), 1_000_000, 2.5e-2);
}

#[test]
fn integer_regrets_take_half_the_regret_memory() {
    let es = MccfrConfig::new(Sampling::External, 2);
    let mut floats = Mccfr::new(Leduc::new(2), es);
    let mut integers = Mccfr::new(Leduc::new(2), es.compact(1_000.0));
    assert_eq!(
        integers.config().storage,
        RegretStorage::I32 { scale: 1_000.0 }
    );
    floats.run(30_000);
    integers.run(30_000);
    let (f, i) = (floats.memory(), integers.memory());
    assert_eq!((f.info_sets, i.info_sets), (936, 936));
    assert_eq!(f.slots, i.slots);
    assert_eq!(f.regret_bytes, 8 * f.slots);
    assert_eq!(i.regret_bytes, 4 * f.slots);
    assert_eq!(f.strategy_bytes, i.strategy_bytes);
    assert_eq!(f.strategy_bytes, 8 * f.slots);
    assert!(i.bytes_per_info_set() < f.bytes_per_info_set());
    assert!(f.reserved_bytes >= f.regret_bytes + f.strategy_bytes);
    // Integer regrets are whole numbers of 1/scale and stay in range.
    for r in integers.regrets() {
        assert!(((r * 1_000.0).round() - r * 1_000.0).abs() < 1e-6, "{r}");
        assert!(r.abs() <= i32::MAX as f64 / 1_000.0 + 1.0);
    }
    // The same draws at first, so the same information sets in both.
    assert_eq!(floats.table().keys(), integers.table().keys());
}

#[test]
fn one_thread_is_the_same_run_however_it_is_asked_for() {
    let cfg = MccfrConfig::new(Sampling::External, 6).linear(100, 3_000);
    let mut plain = Mccfr::new(Leduc::new(2), cfg);
    plain.run(5_000);
    // Asked for by name, sized ahead, and stepped one iteration at a time.
    let mut named = Mccfr::new(Leduc::new(2), cfg.threads(1));
    named.reserve(2_000, 10_000);
    for _ in 0..5_000 {
        named.iterate();
    }
    assert_eq!(run_state(&named), run_state(&plain));
    // Stepping by hand uses the first thread's stream whatever the count.
    let mut team = Mccfr::new(Leduc::new(2), cfg.threads(3));
    for _ in 0..5_000 {
        team.iterate();
    }
    assert_eq!(run_state(&team), run_state(&plain));
    assert_eq!(plain.game().num_players(), 2);
}

#[test]
#[should_panic(expected = "several threads need external sampling")]
fn outcome_sampling_runs_on_one_thread_only() {
    let _ = Mccfr::new(
        Kuhn::new(2),
        MccfrConfig::new(Sampling::OUTCOME, 1).threads(2),
    );
}
