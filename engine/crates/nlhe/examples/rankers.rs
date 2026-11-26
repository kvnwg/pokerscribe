//! Times the two showdown rankers on the same random hands.
//!
//!     cargo run --release -p nlhe --example rankers

use std::hint::black_box;
use std::time::Instant;

use nlhe::{BruteForceRanker, Card, Deal, EvalRanker, HandRanker};

fn time<R: HandRanker>(name: &str, ranker: &R, hands: &[[Card; 7]], rounds: usize) -> u64 {
    let start = Instant::now();
    let mut sum = 0u64;
    for _ in 0..rounds {
        for hand in hands {
            sum += ranker.rank7(black_box(hand)) as u64;
        }
    }
    let per_hand = start.elapsed().as_secs_f64() * 1e9 / (rounds * hands.len()) as f64;
    println!("{name:<18}{per_hand:>8.1} ns a hand");
    sum
}

fn main() {
    let hands: Vec<[Card; 7]> = (0..10_000u64)
        .map(|seed| {
            let deal = Deal::from_seed(seed, 2, 0);
            let [a, b] = deal.hole[0];
            let d = deal.board;
            [a, b, d[0], d[1], d[2], d[3], d[4]]
        })
        .collect();
    black_box(time("BruteForceRanker", &BruteForceRanker, &hands, 20));
    black_box(time("EvalRanker", &EvalRanker, &hands, 2_000));
}
