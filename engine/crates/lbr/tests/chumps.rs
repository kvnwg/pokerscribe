//! LBR against strategies that ignore their cards: it wins big, by the amounts the paper
//! reports where it reports them (Table 2, and 750 mBB per hand for always folding).
//!
//! The paper's numbers are in big blinds per hand; 1 BB per hand is 100 bb/100. These tests
//! play a few thousand hands so they pass in a debug build. The 100,000-hand comparison is
//! `paper_table_2` below (ignored: run it with `--release -- --ignored`) and the table in
//! README.md.

use lbr::{
    play_match, AlwaysCall, AlwaysFold, AlwaysRaise, CallOrRaise, LbrConfig, MatchConfig,
    MatchResult, RaiseSize, Strategy, UniformRandom,
};
use nlhe::Street;

const SEED: u64 = 20261126;

fn play(opponent: &dyn Strategy, config: &LbrConfig, hands: u64) -> MatchResult {
    let result = play_match(opponent, config, &MatchConfig::acpc(hands, SEED));
    println!("{result}");
    result
}

/// LBR wins at least `floor` bb/100, and by far more than luck: over 5 standard errors.
fn assert_wins_big(result: &MatchResult, floor: f64) {
    assert!(result.bb_per_100 > floor, "{result}");
    assert!(result.bb_per_100 > 5.0 * result.std_err, "{result}");
}

#[test]
fn always_fold_loses_exactly_three_quarters_of_a_big_blind() {
    // The paper: "a bot that always folds as the first action would lose 750 mBB/h". On the
    // button LBR calls, the big blind may not fold a free check, and LBR's first bet wins
    // the pot (1 BB). In the big blind LBR wins the small blind at once (0.5 BB).
    for config in [
        LbrConfig::fcpa(Street::Turn),
        LbrConfig::bets56(Street::Turn),
        LbrConfig::fcpa(Street::Flop),
    ] {
        let result = play(&AlwaysFold, &config, 400);
        assert_eq!(result.bb_per_100, 75.0);
        assert_eq!(result.std_err, 0.0);
        assert_eq!(result.button_bb_per_100, 100.0);
        assert_eq!(result.big_blind_bb_per_100, 50.0);
    }
    // Without bets LBR cannot make the big blind fold: it still wins the small blinds, and
    // plays the other hands to a showdown for one big blind each.
    let result = play(&AlwaysFold, &LbrConfig::fc(Street::Turn), 2_000);
    assert_eq!(result.big_blind_bb_per_100, 50.0);
    assert!(
        (result.bb_per_100 - 25.0).abs() < 5.0 * result.std_err,
        "{result}"
    );
}

#[test]
fn always_call() {
    // Fold and call only: both players check every hand down, and with each deal played
    // from both seats the results cancel exactly. The paper's table has 0 here.
    let result = play(&AlwaysCall, &LbrConfig::fc(Street::Turn), 400);
    assert_eq!((result.bb_per_100, result.std_err), (0.0, 0.0));

    // With bets LBR moves all in once it is ahead. The paper: 49.0 ± 0.4 BB per hand
    // (fcpa, rounds 3-4), close to the 50 a true best response gets.
    let result = play(&AlwaysCall, &LbrConfig::fcpa(Street::Turn), 3_000);
    assert_wins_big(&result, 3_500.0);
    assert!(
        (result.bb_per_100 - 4_900.0).abs() < 4.0 * result.std_err,
        "{result}"
    );
}

#[test]
fn always_raise() {
    // Not in the paper. A minimum raise every time builds a pot LBR moves all in over.
    let result = play(
        &AlwaysRaise {
            size: RaiseSize::Min,
        },
        &LbrConfig::fcpa(Street::Turn),
        3_000,
    );
    assert_wins_big(&result, 3_500.0);
    let result = play(
        &AlwaysRaise {
            size: RaiseSize::Pot,
        },
        &LbrConfig::fcpa(Street::Turn),
        3_000,
    );
    assert_wins_big(&result, 2_500.0);

    // Always all in: LBR has to decide before the flop, so it must think there (rounds
    // 1-4). It calls with the hands that are ahead of a random hand and folds the rest.
    let all_in = AlwaysRaise {
        size: RaiseSize::AllIn,
    };
    let config = LbrConfig::fc(Street::Preflop).with_sampled_preflop(300);
    let result = play(&all_in, &config, 2_000);
    assert_wins_big(&result, 600.0);
    // Told to call before the flop whatever it holds (rounds 3-4), it wins nothing: every
    // hand is an all-in showdown, and the two seats of each deal cancel.
    let result = play(&all_in, &LbrConfig::fcpa(Street::Turn), 400);
    assert_eq!((result.bb_per_100, result.std_err), (0.0, 0.0));
}

#[test]
fn uniform_random() {
    // Every legal action equally likely, each raise amount its own action: the paper's
    // "random", 80.7 ± 0.7 BB per hand with fcpa on rounds 3-4. It folds half the time to
    // an all-in, after raising most of its stack in.
    let result = play(
        &UniformRandom::Actions,
        &LbrConfig::fcpa(Street::Turn),
        3_000,
    );
    assert_wins_big(&result, 6_000.0);
    assert!(
        (result.bb_per_100 - 8_070.0).abs() < 4.0 * result.std_err,
        "{result}"
    );

    // Fold, call or raise with a third each.
    let result = play(&UniformRandom::Kinds, &LbrConfig::fcpa(Street::Turn), 3_000);
    assert_wins_big(&result, 3_500.0);
    // The 56 bets find more than pot and all in do.
    let more = play(
        &UniformRandom::Kinds,
        &LbrConfig::bets56(Street::Turn),
        3_000,
    );
    assert!(more.bb_per_100 > result.bb_per_100);
}

#[test]
fn half_call_half_raise() {
    // The paper's third trivial strategy. See README.md for how our numbers compare.
    let result = play(&CallOrRaise, &LbrConfig::fcpa(Street::Turn), 3_000);
    assert_wins_big(&result, 1_500.0);
    // With fold and call only the edge is smaller (about 700), so ask for 3 standard errors.
    let result = play(&CallOrRaise, &LbrConfig::fc(Street::Turn), 3_000);
    assert!(
        result.bb_per_100 > 300.0 && result.bb_per_100 > 3.0 * result.std_err,
        "{result}"
    );
}

#[test]
fn the_same_seed_gives_the_same_match_on_any_number_of_cores() {
    let config = LbrConfig::fcpa(Street::Turn);
    let table = MatchConfig::acpc(600, 99);
    let all_cores = play_match(&UniformRandom::Kinds, &config, &table);
    let one_core = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap()
        .install(|| play_match(&UniformRandom::Kinds, &config, &table));
    assert_eq!(all_cores, one_core);
    assert_eq!(
        all_cores,
        play_match(&UniformRandom::Kinds, &config, &table)
    );
    let other_seed = play_match(&UniformRandom::Kinds, &config, &MatchConfig::acpc(600, 100));
    assert_ne!(all_cores.bb_per_100, other_seed.bb_per_100);
    // An odd number of hands is rounded up to whole deals.
    assert_eq!(
        play_match(&AlwaysFold, &config, &MatchConfig::acpc(7, 1)).hands,
        8
    );
}

/// How far a result may be from the paper's: 3 standard errors of the difference. The paper
/// gives 95% confidence intervals in BB per hand, so its standard error is the interval over
/// 1.96, times 100 for bb/100.
fn assert_matches_paper(result: &MatchResult, paper_bb: f64, paper_interval_bb: f64) {
    let paper_se = 100.0 * paper_interval_bb / 1.96;
    let allowed = 3.0 * (result.std_err.powi(2) + paper_se.powi(2)).sqrt();
    let difference = result.bb_per_100 - 100.0 * paper_bb;
    println!(
        "  paper {:.0}, difference {difference:+.0}, allowed {allowed:.0}",
        100.0 * paper_bb
    );
    assert!(
        difference.abs() < allowed,
        "{result} against the paper's {paper_bb} BB per hand"
    );
}

/// The cells of the paper's Table 2 that need no thinking before the flop, at the paper's
/// 100,000 hands. About 20 seconds in a release build.
#[test]
#[ignore = "100,000 hands per cell; run with --release -- --ignored"]
fn paper_table_2() {
    let hands = 100_000;
    let fc = LbrConfig::fc(Street::Turn);
    let fcpa = LbrConfig::fcpa(Street::Turn);
    assert_eq!(play(&AlwaysFold, &fcpa, hands).bb_per_100, 75.0);
    assert_eq!(play(&AlwaysCall, &fc, hands).bb_per_100, 0.0);
    assert_matches_paper(&play(&AlwaysCall, &fcpa, hands), 49.0, 0.4);
    assert_matches_paper(&play(&UniformRandom::Actions, &fcpa, hands), 80.7, 0.7);
    assert_matches_paper(&play(&UniformRandom::Actions, &fc, hands), 2.2, 0.7);
}

/// The cells where LBR thinks on every street, with the exact preflop table. Several
/// minutes in a release build, most of it the table.
#[test]
#[ignore = "builds the exact preflop table; run with --release -- --ignored"]
fn paper_table_2_rounds_1_to_4() {
    let hands = 100_000;
    lbr::warm_preflop_table();
    let fc = LbrConfig::fc(Street::Preflop);
    let fcpa = LbrConfig::fcpa(Street::Preflop);
    assert_eq!(play(&AlwaysFold, &fcpa, hands).bb_per_100, 75.0);
    assert_eq!(play(&AlwaysCall, &fc, hands).bb_per_100, 0.0);
    assert_matches_paper(&play(&AlwaysCall, &fcpa, hands), 34.0, 0.5);
    assert_matches_paper(&play(&UniformRandom::Actions, &fcpa, hands), 39.1, 0.6);
    assert_matches_paper(&play(&UniformRandom::Actions, &fc, hands), 15.7, 0.4);
}
