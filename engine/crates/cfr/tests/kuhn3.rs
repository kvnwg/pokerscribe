//! Three-player Kuhn poker: NashConv of the average strategy falls as Monte
//! Carlo CFR runs. There is no convergence guarantee with three players; the
//! test checks the observed behaviour at fixed seeds.

use cfr::{nash_conv, Cfr, Mccfr, MccfrConfig, Sampling, Solver, Variant};
use toygames::Kuhn;

fn nash_conv_curve<S: Solver>(mut solver: S, checkpoints: &[u64]) -> Vec<f64> {
    let game = Kuhn::new(3);
    checkpoints
        .iter()
        .map(|&c| {
            solver.run(c - solver.iterations());
            nash_conv(&game, &solver.average_policy())
        })
        .collect()
}

fn assert_falls(name: &str, curve: &[f64], final_below: f64) {
    let shown: Vec<String> = curve.iter().map(|x| format!("{x:.2e}")).collect();
    println!("{name}: NashConv {}", shown.join(", "));
    for w in curve.windows(2) {
        assert!(w[1] < w[0], "{name}: NashConv rose: {curve:?}");
    }
    assert!(*curve.last().unwrap() < final_below, "{name}: {curve:?}");
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn external_sampling_nash_conv_falls() {
    for seed in [1, 2] {
        let cfg = MccfrConfig::new(Sampling::External, seed);
        let curve = nash_conv_curve(
            Mccfr::new(Kuhn::new(3), cfg),
            &[1_000, 10_000, 100_000, 1_000_000],
        );
        assert_falls(&format!("ES seed {seed}"), &curve, 0.01);
    }
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn external_sampling_linear_nash_conv_falls() {
    let cfg = MccfrConfig::new(Sampling::External, 1).linear(100, 100_000);
    let curve = nash_conv_curve(
        Mccfr::new(Kuhn::new(3), cfg),
        &[1_000, 10_000, 100_000, 1_000_000],
    );
    assert_falls("ES linear", &curve, 0.01);
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn outcome_sampling_nash_conv_falls() {
    let cfg = MccfrConfig::new(Sampling::OUTCOME, 1).linear(100, u64::MAX);
    let curve = nash_conv_curve(
        Mccfr::new(Kuhn::new(3), cfg),
        &[10_000, 100_000, 1_000_000, 4_000_000],
    );
    assert_falls("OS linear", &curve, 0.03);
}

#[test]
fn quick_external_sampling_nash_conv_falls() {
    // Short version that also runs in debug builds.
    let cfg = MccfrConfig::new(Sampling::External, 1);
    let curve = nash_conv_curve(Mccfr::new(Kuhn::new(3), cfg), &[100, 1_000, 10_000]);
    assert_falls("ES short", &curve, 0.05);
}

#[test]
fn full_width_cfr_three_players() {
    let curve = nash_conv_curve(Cfr::new(Kuhn::new(3), Variant::Vanilla), &[10, 100, 1_000]);
    assert_falls("CFR", &curve, 0.01);
}
