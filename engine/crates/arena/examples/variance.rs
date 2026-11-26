//! Measures what duplicate play and the all-in equity adjustment do to the standard
//! error, on the built-in bots. Prints the tables of the README.
//!
//! ```bash
//! cargo run --release -p arena --example variance
//! ```
//!
//! An optional argument scales the number of hands (default 1.0; 0.1 for a quick look).

use arena::{bots, run_match, MatchConfig, MatchReport};

/// The standard errors of one matchup over the same number of hands.
fn row(label: &str, names: [&str; 2], players: usize, hands: u64, seed: u64) {
    let agents = [
        bots::builtin(names[0]).unwrap(),
        bots::builtin(names[1]).unwrap(),
    ];
    let base = MatchConfig::one_against_the_rest(players, 1, seed);
    let replays = base.replays() as u64;
    let run = |deals: u64, duplicate: bool, shared: bool| -> MatchReport {
        let config = MatchConfig {
            deals,
            duplicate,
            shared_randomness: shared,
            ..base.clone()
        };
        run_match(&config, &agents).unwrap()
    };
    // Agent 1 is the one that visits every seat; its result is the match result.
    let plain = run(hands, false, false);
    let dup = run(hands / replays, true, false);
    let shared = run(hands / replays, true, true);
    let (p, d, s) = (
        plain.result_of(1).unwrap(),
        dup.result_of(1).unwrap(),
        shared.result_of(1).unwrap(),
    );
    let plain_se = p.actual_se.unwrap();
    let ratio = |se: f64| {
        if se > 1e-9 {
            format!("{:.2}", plain_se / se)
        } else {
            "all".to_string()
        }
    };
    println!(
        "| {label} | {:+.1} | {:.2} | {:.2} | {:.2} | {:.2} | {:.2} | {} | {} | {:.1}% |",
        d.bb_per_100,
        plain_se,
        p.se.unwrap(),
        d.actual_se.unwrap(),
        d.se.unwrap(),
        s.se.unwrap(),
        ratio(d.se.unwrap()),
        ratio(s.se.unwrap()),
        100.0 * dup.adjusted_hands as f64 / dup.hands as f64,
    );
}

fn main() {
    let scale: f64 = std::env::args()
        .nth(1)
        .map_or(1.0, |a| a.parse().expect("a number"));
    let header = "| Match | bb/100 | Plain | Plain + equity | Duplicate | Duplicate + equity | \
                  and shared randomness | Plain / (dup + equity) | Plain / shared | All-in hands |\n\
                  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |";

    let hands = ((400_000.0 * scale) as u64).max(1_000) / 2 * 2;
    println!("Heads-up, {hands} hands each (standard errors in bb/100)\n\n{header}");
    for (label, names) in [
        ("tag-loose against tag", ["tag", "tag-loose"]),
        ("tag against tag", ["tag", "tag"]),
        ("random against random", ["random", "random"]),
        ("tag against random", ["random", "tag"]),
        ("tag against call", ["call", "tag"]),
        ("tag against raise", ["raise", "tag"]),
        ("raise against random", ["random", "raise"]),
    ] {
        row(label, names, 2, hands, 2026);
    }

    let hands = ((600_000.0 * scale) as u64).max(1_200) / 6 * 6;
    println!("\nSix-max, one against five, {hands} hands each\n\n{header}");
    for (label, names) in [
        ("tag-loose against 5 tag", ["tag", "tag-loose"]),
        ("tag against 5 tag", ["tag", "tag"]),
        ("random against 5 random", ["random", "random"]),
        ("tag against 5 random", ["random", "tag"]),
        ("tag against 5 call", ["call", "tag"]),
        ("raise against 5 tag", ["tag", "raise"]),
    ] {
        row(label, names, 6, hands, 2026);
    }
}
