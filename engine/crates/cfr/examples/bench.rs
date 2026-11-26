//! Convergence and speed of every solver on Kuhn (2 and 3 players) and Leduc.
//!
//!     cargo run --release -p cfr --example bench
//!     cargo run --release -p cfr --example bench -- leduc es
//!
//! Optional filters: a game (kuhn2, kuhn3, leduc) and a solver name. Prints
//! exploitability (NashConv / players) of the average strategy at each
//! checkpoint, player 0's value at the end, and speed. Timing covers the
//! solver only, not the exact evaluation.

use std::time::Instant;

use cfr::{expected_values, nash_conv, Cfr, Game, Mccfr, MccfrConfig, Sampling, Solver, Variant};
use toygames::{Kuhn, Leduc};

struct Entry {
    name: &'static str,
    solver: Box<dyn Solver>,
    checkpoints: &'static [u64],
}

const FULL: &[u64] = &[10, 100, 1_000, 10_000];
const SAMPLED: &[u64] = &[10_000, 100_000, 1_000_000, 10_000_000];

fn entries<G: Game + Copy + 'static>(game: G) -> Vec<Entry> {
    let es = MccfrConfig::new(Sampling::External, 1);
    let os = MccfrConfig::new(Sampling::OUTCOME, 1);
    let mut v = Vec::new();
    for (name, variant) in [
        ("cfr", Variant::Vanilla),
        ("cfr+", Variant::CfrPlus),
        ("linear", Variant::Linear),
        ("dcfr", Variant::DCFR),
    ] {
        v.push(Entry {
            name,
            solver: Box::new(Cfr::new(game, variant)),
            checkpoints: FULL,
        });
    }
    for (name, cfg) in [
        ("es", es),
        ("es-linear", es.linear(100, 100_000)),
        ("es-prune", es.pruning(10_000, -10_000.0, 0.95)),
        ("os", os),
        ("os-linear", os.linear(1_000, 10_000_000)),
    ] {
        v.push(Entry {
            name,
            solver: Box::new(Mccfr::new(game, cfg)),
            checkpoints: SAMPLED,
        });
    }
    v
}

fn report<G: Game + Copy + 'static>(label: &str, game: G, filter: Option<&str>) {
    println!("\n{label}");
    for mut e in entries(game) {
        if filter.is_some_and(|f| f != e.name) {
            continue;
        }
        let mut solve_time = 0.0;
        let mut line = format!("  {:10}", e.name);
        for &c in e.checkpoints {
            let t0 = Instant::now();
            e.solver.run(c - e.solver.iterations());
            solve_time += t0.elapsed().as_secs_f64();
            let pol = e.solver.average_policy();
            let expl = nash_conv(&game, &pol) / game.num_players() as f64;
            line += &format!(" | {:>8}: {expl:.2e}", c);
        }
        let pol = e.solver.average_policy();
        let v = expected_values(&game, &pol)[0];
        line += &format!(
            " | v0 {v:+.6} | {:>9.0} it/s | {:>5.1} M nodes/s | {:.1} s",
            e.solver.iterations() as f64 / solve_time,
            e.solver.nodes_touched() as f64 / solve_time / 1e6,
            solve_time
        );
        println!("{line}");
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let game = args.first().map(String::as_str);
    let filter = args.get(1).map(String::as_str);
    if game.is_none_or(|g| g == "kuhn2") {
        report(
            "Kuhn, 2 players (12 information sets)",
            Kuhn::new(2),
            filter,
        );
    }
    if game.is_none_or(|g| g == "kuhn3") {
        report(
            "Kuhn, 3 players (48 information sets)",
            Kuhn::new(3),
            filter,
        );
    }
    if game.is_none_or(|g| g == "leduc") {
        report(
            "Leduc, 2 players (936 information sets)",
            Leduc::new(2),
            filter,
        );
    }
}
