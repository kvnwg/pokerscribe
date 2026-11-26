//! Times the arena on the built-in bots. Prints the speed tables of the README.
//!
//! ```bash
//! cargo run --release -p arena --example speed
//! ```

use std::time::Instant;

use arena::{all_in_equity, bots, run_match, EvalRanker, MatchConfig};
use nlhe::{parse_card, Action, Card, Config, Deal, State};

fn cards(s: &str) -> Vec<Card> {
    s.as_bytes()
        .chunks(2)
        .map(|c| parse_card(std::str::from_utf8(c).unwrap()).unwrap())
        .collect()
}

/// A hand where everyone left is all in with `known` board cards face up.
fn all_in(holes: &[&str], known: usize) -> State {
    let hole: Vec<[Card; 2]> = holes.iter().map(|h| cards(h).try_into().unwrap()).collect();
    let deal = Deal::new(&hole, cards("2c7d8h3s4c").try_into().unwrap()).unwrap();
    let config = Config::new(&vec![10_000; holes.len()], 50, 100, 0, 0).unwrap();
    let mut state = State::new(&config, deal).unwrap();
    while state.board().len() < known {
        let action = if state.legal_actions().check {
            Action::Check
        } else {
            Action::Call
        };
        state.apply(action).unwrap();
    }
    let mut first = true;
    while state.current_player().is_some() {
        let legal = state.legal_actions();
        let action = match legal.raise {
            Some(range) if first => Action::RaiseTo(range.max_to),
            _ => Action::Call,
        };
        first = false;
        state.apply(action).unwrap();
    }
    assert!(state.payouts(&EvalRanker).is_some());
    state
}

fn time_equity(label: &str, state: &State, sample: Option<(u32, u64)>, repeats: u32) {
    let start = Instant::now();
    let mut check = 0.0;
    for i in 0..repeats {
        let sample = sample.map(|(k, seed)| (k, seed + i as u64));
        check += all_in_equity(state, sample).unwrap()[0];
    }
    let each = start.elapsed().as_secs_f64() / repeats as f64;
    println!(
        "| {label} | {} | {:+.1} |",
        if each >= 1e-3 {
            format!("{:.2} ms", each * 1e3)
        } else {
            format!("{:.1} µs", each * 1e6)
        },
        check / repeats as f64 / 100.0
    );
}

fn time_match(label: &str, names: [&str; 2], config: MatchConfig) {
    let agents = [
        bots::builtin(names[0]).unwrap(),
        bots::builtin(names[1]).unwrap(),
    ];
    let one = run_match(
        &MatchConfig {
            threads: 1,
            ..config.clone()
        },
        &agents,
    )
    .unwrap();
    let all = run_match(&config, &agents).unwrap();
    assert_eq!(one.results, all.results);
    println!(
        "| {label} | {} | {:.0} | {:.0} | {:.1}% |",
        all.hands,
        one.timing.hands_per_second,
        all.timing.hands_per_second,
        100.0 * all.adjusted_hands as f64 / all.hands as f64
    );
}

fn main() {
    println!("| All-in equity, one hand | Time | Seat 0 expects (bb) |\n| --- | --- | --- |");
    let hu = ["AsAh", "KdKc"];
    let six = ["AsAh", "KdKc", "QsQh", "JdJc", "Ts9s", "7h6h"];
    let pre = all_in(&hu, 0);
    time_equity(
        "Heads-up before the flop, all 1,712,304 boards",
        &pre,
        None,
        20,
    );
    time_equity(
        "Heads-up before the flop, 10,000 boards",
        &pre,
        Some((10_000, 1)),
        2_000,
    );
    time_equity(
        "Heads-up before the flop, 1,000 boards",
        &pre,
        Some((1_000, 1)),
        20_000,
    );
    time_equity(
        "Heads-up on the flop, all 990 boards",
        &all_in(&hu, 3),
        None,
        20_000,
    );
    time_equity(
        "Heads-up on the turn, all 44 boards",
        &all_in(&hu, 4),
        None,
        200_000,
    );
    let pre6 = all_in(&six, 0);
    time_equity(
        "Six players before the flop, all 658,008 boards",
        &pre6,
        None,
        20,
    );
    time_equity(
        "Six players before the flop, 10,000 boards",
        &pre6,
        Some((10_000, 1)),
        2_000,
    );
    time_equity(
        "Six players on the flop, all 666 boards",
        &all_in(&six, 3),
        None,
        20_000,
    );

    let threads = rayon::current_num_threads();
    println!(
        "\n| Match | Hands | Hands/s, 1 thread | Hands/s, {threads} threads | All-in hands |\n\
         | --- | --- | --- | --- | --- |"
    );
    let hu = |deals| MatchConfig::heads_up(deals, 1);
    let six = |deals| MatchConfig::one_against_the_rest(6, deals, 1);
    let exact = |config: MatchConfig| MatchConfig {
        max_runouts: None,
        ..config
    };
    time_match(
        "Heads-up, call against call, plain",
        ["call", "call"],
        hu(2_000_000).plain(),
    );
    time_match("Heads-up, tag against call", ["call", "tag"], hu(500_000));
    time_match(
        "Heads-up, tag-loose against tag",
        ["tag", "tag-loose"],
        hu(500_000),
    );
    time_match(
        "Heads-up, tag against random",
        ["random", "tag"],
        hu(250_000),
    );
    time_match("Heads-up, tag against raise", ["raise", "tag"], hu(250_000));
    time_match(
        "Heads-up, tag against raise, every board",
        ["raise", "tag"],
        exact(hu(20_000)),
    );
    time_match(
        "Six-max, tag-loose against 5 tag",
        ["tag", "tag-loose"],
        six(100_000),
    );
    time_match(
        "Six-max, tag against 5 random",
        ["random", "tag"],
        six(100_000),
    );
    time_match(
        "Six-max, tag against 5 random, every board",
        ["random", "tag"],
        exact(six(5_000)),
    );
}
