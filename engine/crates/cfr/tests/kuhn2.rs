//! Two-player Kuhn poker: every solver reaches the game value -1/18 for
//! player 0 within 1e-3, with exploitability under 1e-3.
//!
//! The Monte Carlo tests run tens of millions of iterations: a few seconds
//! each with `cargo test --release`, minutes in a debug build, so debug
//! builds skip them.

mod common;

use cfr::{Cfr, Game, Mccfr, MccfrConfig, Sampling, Solver, Variant};
use common::measure;
use toygames::Kuhn;

const VALUE: f64 = -1.0 / 18.0;

fn check<S: Solver>(name: &str, mut solver: S, iterations: u64) -> S {
    let game = Kuhn::new(2);
    solver.run(iterations);
    let (expl, value) = measure(&game, &solver);
    println!("{name}: {iterations} iterations, exploitability {expl:.2e}, value {value:.6}");
    assert!(expl < 1e-3, "{name}: exploitability {expl}");
    assert!((value - VALUE).abs() < 1e-3, "{name}: value {value}");
    assert_eq!(game.num_players(), 2);
    solver
}

#[test]
fn vanilla_cfr() {
    check("CFR", Cfr::new(Kuhn::new(2), Variant::Vanilla), 2_000);
}

#[test]
fn cfr_plus() {
    check("CFR+", Cfr::new(Kuhn::new(2), Variant::CfrPlus), 1_000);
}

#[test]
fn linear_cfr() {
    check("Linear CFR", Cfr::new(Kuhn::new(2), Variant::Linear), 1_000);
}

#[test]
fn discounted_cfr() {
    assert_eq!(
        Variant::DCFR,
        Variant::Discounted {
            alpha: 1.5,
            beta: 0.0,
            gamma: 2.0
        }
    );
    check("DCFR", Cfr::new(Kuhn::new(2), Variant::DCFR), 1_000);
}

#[test]
fn custom_discounted_cfr() {
    let v = Variant::Discounted {
        alpha: 1.0,
        beta: 1.0,
        gamma: 1.0,
    };
    check("DCFR(1,1,1)", Cfr::new(Kuhn::new(2), v), 1_000);
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn external_sampling() {
    let cfg = MccfrConfig::new(Sampling::External, 1);
    check("ES-MCCFR", Mccfr::new(Kuhn::new(2), cfg), 2_000_000);
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn external_sampling_linear() {
    let cfg = MccfrConfig::new(Sampling::External, 1).linear(100, 100_000);
    check("ES-MCCFR linear", Mccfr::new(Kuhn::new(2), cfg), 2_000_000);
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn external_sampling_pruning() {
    let cfg = MccfrConfig::new(Sampling::External, 1).pruning(10_000, -10_000.0, 0.95);
    let solver = check("ES-MCCFR pruning", Mccfr::new(Kuhn::new(2), cfg), 8_000_000);
    let stats = solver.stats();
    let traversals = 2 * solver.iterations();
    // After warm-up, about 95% of traversals are pruned ones, and they skip
    // the actions with very negative regret.
    let share = stats.pruned_traversals as f64 / traversals as f64;
    assert!((share - 0.95).abs() < 0.01, "pruned share {share}");
    assert!(stats.pruned_actions > traversals / 10, "{stats:?}");
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn outcome_sampling() {
    // Outcome sampling hovers around 1e-3 on Kuhn for tens of millions of
    // iterations. Linear weighting up to 10^7 and 6 x 10^7 iterations put
    // four seeds out of four under 1e-3 (worst 7.2e-4).
    let cfg = MccfrConfig::new(Sampling::OUTCOME, 1).linear(1_000, 10_000_000);
    check("OS-MCCFR", Mccfr::new(Kuhn::new(2), cfg), 60_000_000);
}

#[test]
fn pruning_skips_work() {
    // Same seed with and without pruning: the pruned run visits fewer nodes.
    let base = MccfrConfig::new(Sampling::External, 5);
    let mut plain = Mccfr::new(Kuhn::new(2), base);
    let mut pruned = Mccfr::new(Kuhn::new(2), base.pruning(1_000, -100.0, 0.95));
    plain.run(20_000);
    pruned.run(20_000);
    assert_eq!(plain.stats().pruned_actions, 0);
    assert!(pruned.stats().pruned_actions > 0);
    assert!(pruned.stats().nodes_touched < plain.stats().nodes_touched * 95 / 100);
}

#[test]
fn regret_floor_holds() {
    let floor = -3.0;
    let mut solver = Mccfr::new(
        Kuhn::new(2),
        MccfrConfig::new(Sampling::External, 9).regret_floor(floor),
    );
    solver.run(10_000);
    let min = solver
        .regrets()
        .iter()
        .cloned()
        .fold(f64::INFINITY, f64::min);
    assert!(min >= floor, "min regret {min}");
    assert!(
        min < floor + 1e-9,
        "the floor should bind in Kuhn (min {min})"
    );
}
