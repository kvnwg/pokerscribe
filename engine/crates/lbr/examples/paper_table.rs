//! LBR against the trivial strategies, next to the paper's Table 2, with the speed.
//!
//! ```text
//! cargo run --release -p lbr --example paper_table -- [--hands N] [--seed S]
//!                                                     [--preflop | --sampled BOARDS]
//! ```
//!
//! Without options: the settings where LBR checks or calls before the turn (rounds 3-4),
//! 100,000 hands each. `--preflop` adds the settings where it thinks on every street
//! (rounds 1-4). They need the exact preflop table, about a quarter of an hour of CPU time
//! once per run. `--sampled BOARDS` adds them with that many random boards per hand in
//! place of the table.

use std::time::Instant;

use lbr::{
    play_match, warm_preflop_table, AlwaysCall, AlwaysFold, AlwaysRaise, CallOrRaise, LbrConfig,
    MatchConfig, RaiseSize, Strategy, UniformRandom,
};
use nlhe::Street;

/// A cell of the paper's Table 2: BB per hand and the 95% confidence interval.
type Paper = Option<(f64, f64)>;

fn main() {
    let mut hands = 100_000u64;
    let mut seed = 20261126u64;
    let mut preflop = false;
    let mut sampled = 0u32;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        let mut number = |name: &str| -> u64 {
            args.next()
                .and_then(|v| v.parse().ok())
                .unwrap_or_else(|| panic!("{name} needs a number"))
        };
        match arg.as_str() {
            "--hands" => hands = number("--hands"),
            "--seed" => seed = number("--seed"),
            "--preflop" => preflop = true,
            "--sampled" => {
                preflop = true;
                sampled = number("--sampled") as u32;
            }
            other => panic!("unknown argument {other}"),
        }
    }

    // The paper's columns: fc 1-4, fc 3-4, fcpa 1-4, fcpa 3-4. Always fold is from its
    // text: 750 mBB per hand, which holds whenever LBR may bet.
    const NONE: [Paper; 4] = [None; 4];
    let fold = [None, None, Some((0.75, 0.0)), Some((0.75, 0.0))];
    let call = [
        Some((0.0, 0.0)),
        Some((0.0, 0.0)),
        Some((34.0, 0.5)),
        Some((49.0, 0.4)),
    ];
    let half = [
        Some((7.1, 0.5)),
        Some((16.2, 0.3)),
        Some((23.1, 0.5)),
        Some((24.4, 0.6)),
    ];
    let random = [
        Some((15.7, 0.4)),
        Some((2.2, 0.7)),
        Some((39.1, 0.6)),
        Some((80.7, 0.7)),
    ];
    let strategies: [(&str, &dyn Strategy, [Paper; 4]); 8] = [
        ("always fold", &AlwaysFold, fold),
        ("always call", &AlwaysCall, call),
        ("1/2 call, 1/2 raise", &CallOrRaise, half),
        ("random action", &UniformRandom::Actions, random),
        ("random kind of action", &UniformRandom::Kinds, NONE),
        (
            "always raise, minimum",
            &AlwaysRaise {
                size: RaiseSize::Min,
            },
            NONE,
        ),
        (
            "always raise, pot",
            &AlwaysRaise {
                size: RaiseSize::Pot,
            },
            NONE,
        ),
        (
            "always raise, all in",
            &AlwaysRaise {
                size: RaiseSize::AllIn,
            },
            NONE,
        ),
    ];
    // (name, settings, column of the paper's table)
    let settings = [
        ("fc, rounds 1-4", LbrConfig::fc(Street::Preflop), Some(0)),
        ("fc, rounds 3-4", LbrConfig::fc(Street::Turn), Some(1)),
        (
            "fcpa, rounds 1-4",
            LbrConfig::fcpa(Street::Preflop),
            Some(2),
        ),
        ("fcpa, rounds 3-4", LbrConfig::fcpa(Street::Turn), Some(3)),
        (
            "56 bets, rounds 1-4",
            LbrConfig::bets56(Street::Preflop),
            None,
        ),
        ("56 bets, rounds 3-4", LbrConfig::bets56(Street::Turn), None),
    ];

    println!(
        "{hands} hands per row, seed {seed}, {} threads",
        rayon::current_num_threads()
    );
    if preflop && sampled == 0 {
        let start = Instant::now();
        warm_preflop_table();
        println!(
            "exact preflop table: {:.0} s",
            start.elapsed().as_secs_f64()
        );
    }
    println!();
    println!("| Strategy | LBR setting | LBR wins (bb/100) | Paper (bb/100) | Hands per second |");
    println!("| --- | --- | ---: | ---: | ---: |");
    for (name, strategy, paper) in strategies {
        for (setting, config, column) in &settings {
            let thinks_preflop = config.streets[0] != lbr::StreetPolicy::CheckCall;
            if thinks_preflop && !preflop {
                continue;
            }
            let config = match sampled {
                0 => config.clone(),
                boards => config.clone().with_sampled_preflop(boards),
            };
            let start = Instant::now();
            let result = play_match(strategy, &config, &MatchConfig::acpc(hands, seed));
            let seconds = start.elapsed().as_secs_f64();
            let paper = match column.and_then(|c| paper[c]) {
                None => String::new(),
                Some((bb, 0.0)) => format!("{:.0}", 100.0 * bb),
                // The paper's ± is a 95% interval; shown as a standard error like ours.
                Some((bb, interval)) => {
                    format!("{:.0} ± {:.0}", 100.0 * bb, 100.0 * interval / 1.96)
                }
            };
            println!(
                "| {name} | {setting} | {:+.1} ± {:.1} | {paper} | {:.0} |",
                result.bb_per_100,
                result.std_err,
                result.hands as f64 / seconds
            );
        }
    }
}
