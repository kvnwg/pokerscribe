//! Checks on the real 52-card deck. They need a release build and are ignored by default.
//!
//! The first builds the real river table itself (about a minute on 4 cores):
//!
//! ```bash
//! cargo test --release -p abstraction --test real_deck -- --ignored real_river
//! ```
//!
//! The second checks tables that were built with `abstraction-build`:
//!
//! ```bash
//! ABSTRACTION_TABLES=/path/to/tables cargo test --release -p abstraction --test real_deck -- --ignored built_tables
//! ```

use abstraction::builder::{self, Settings};
use abstraction::{checks, parse_cards, Abstraction, Deck, HandIndexer};

/// The checksum of the real river table with 50 buckets, seed 1 and the default settings.
/// The same seed must give the same buckets on every machine and with any number of
/// threads. When a change to the code changes the buckets on purpose, update this number,
/// and remember that every table built before is stale too.
const RIVER_50_CHECKSUM: &str = "2da07a5e22348338";

#[test]
#[ignore = "builds the real river table: about a minute in a release build"]
fn real_river_table_groups_hands_sensibly() {
    let deck = Deck::FULL;
    let indexer = HandIndexer::new(&[2, 5]);
    let equity = builder::river_equity(deck);
    assert_eq!(equity.numerators.len(), 123_156_254);
    assert_eq!(equity.denominator, 1980);
    let index = |hole: &str, board: &str| {
        let mut cards = parse_cards(hole).unwrap();
        cards.extend(parse_cards(board).unwrap());
        indexer.index(&cards)
    };
    // A set of kings is the nuts here; a royal flush on the board ties everyone.
    assert_eq!(equity.numerators[index("KhKd", "Ks9d7h4c2s") as usize], 1980);
    assert_eq!(equity.numerators[index("9h9c", "Ks9d7h4c2s") as usize], 1980 - 2 * 3);
    assert_eq!(equity.numerators[index("2c3d", "AsKsQsJsTs") as usize], 990);

    let settings = Settings::new(50);
    let (river, report) = builder::build_river(&equity, &settings.river, settings.seed);
    println!("{}", serde_json::to_string(&report).unwrap());
    assert_eq!(river.buckets(), 50);
    assert_eq!(river.sizes.iter().sum::<u64>(), 1326 * 2_118_760);
    assert!(river.equity.windows(2).all(|w| w[0] <= w[1]));

    let bucket = |hole: &str, board: &str| river.bucket(index(hole, board)) as usize;
    let equity_of = |hole: &str, board: &str| river.equity[bucket(hole, board)];
    // The nuts and the near-nuts share a bucket: the top one.
    let board = "Ks9d7h4c2s";
    assert_eq!(bucket("KhKd", board), 49, "the nuts are in the top bucket");
    assert_eq!(bucket("9h9c", board), 49, "the second nuts are with the nuts");
    assert_eq!(bucket("7s7c", board), 49, "the third nuts are with the nuts");
    assert_eq!(bucket("KhQh", "AhJh8h4c2d"), 49, "the nut flush");
    assert_eq!(bucket("QhTh", "AhJh8h4c2d"), 49, "the second nut flush");
    assert!(river.equity[49] > 0.95);
    // Air sits apart, at the bottom.
    assert_eq!(bucket("5h3d", board), 0);
    assert_eq!(bucket("6h5d", board), 0);
    assert!(river.equity[0] < 0.05);
    // In between, stronger hands are in higher buckets.
    let ladder = ["5h3d", "QhJh", "AcQd", "8h8c", "AhAd", "KhKd"];
    for pair in ladder.windows(2) {
        assert!(
            bucket(pair[0], board) < bucket(pair[1], board),
            "{} is in bucket {} and {} in bucket {}",
            pair[0],
            bucket(pair[0], board),
            pair[1],
            bucket(pair[1], board)
        );
    }
    // Every hand ties on a royal flush board.
    assert_eq!(bucket("2c3d", "AsKsQsJsTs"), bucket("AhAd", "AsKsQsJsTs"));
    assert!((0.4..0.65).contains(&equity_of("2c3d", "AsKsQsJsTs")));
    // Hole cards that don't play.
    assert_eq!(bucket("7c2d", "AsAdKsKdQh"), bucket("8c3d", "AsAdKsKdQh"));
    // Other suits, same hand.
    assert_eq!(bucket("KhQh", "AhJh8h4c2d"), bucket("KsQs", "AsJs8s4d2h"));

    // Same seed, same buckets.
    assert_eq!(river.checksum(), RIVER_50_CHECKSUM);
}

#[test]
#[ignore = "needs built tables: set ABSTRACTION_TABLES to their directory"]
fn built_tables_pass_the_checks() {
    let dir = std::env::var("ABSTRACTION_TABLES")
        .expect("set ABSTRACTION_TABLES to a directory holding flop.abs, turn.abs and river.abs");
    let abstraction = Abstraction::load(std::path::Path::new(&dir)).expect("tables load");
    let results = checks::run(&abstraction);
    for r in &results {
        println!("{} {}: {}", if r.passed { "ok  " } else { "FAIL" }, r.name, r.detail);
    }
    let failed: Vec<&str> = results.iter().filter(|r| !r.passed).map(|r| r.name.as_str()).collect();
    assert!(failed.is_empty(), "failed: {failed:?}");
}
