//! The whole build on a small deck (nines to aces, 24 cards), where it takes about a second.

use abstraction::builder::{self, Settings};
use abstraction::table::Feature;
use abstraction::{parse_cards, Abstraction, Deck, HandIndexer, Street};

fn small(buckets: u32) -> Settings {
    let mut s = Settings::new(buckets);
    s.ranks = 6;
    s
}

#[test]
fn builds_and_prints() {
    let started = std::time::Instant::now();
    let settings = small(30);
    let ([flop, turn, river], reports) = builder::build_all(&settings);
    for r in &reports {
        println!("{}", serde_json::to_string(r).unwrap());
    }
    println!("took {:?}", started.elapsed());
    for t in [&flop, &turn, &river] {
        println!(
            "{} hands {} buckets {} equity {:?}",
            t.header.street.name(),
            t.len(),
            t.buckets(),
            &t.equity
        );
        println!("sizes {:?}", t.sizes);
    }
    let a = Abstraction::from_tables(flop, turn, river).unwrap();
    assert_eq!(a.buckets(Street::Preflop), 36);
    let _ = (Deck::new(6), HandIndexer::new(&[2]), parse_cards("AhKh"), Feature::Equity);
}
