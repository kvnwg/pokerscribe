//! Cross-check against PokerKit 0.7.8 on 1,000,000 random heads-up showdowns.
//!
//! The fixture comes from tools/reference/eval_fixtures.py (see its docstring for the
//! format). The deals are not stored: this test deals them again from the same seed with
//! the same generator, and first checks the header's checksum of every dealt card.

mod common;

use common::SplitMix64;
use eval::{Category, Hand, format_cards};
use std::collections::HashMap;

const FIXTURE: &[u8] = include_bytes!("fixtures/pokerkit_showdowns.bin");

#[test]
fn one_million_showdowns_match_pokerkit() {
    let split = FIXTURE
        .windows(2)
        .position(|w| w == b"\n\n")
        .expect("header end")
        + 2;
    let header: HashMap<&str, &str> = std::str::from_utf8(&FIXTURE[..split])
        .unwrap()
        .lines()
        .filter_map(|l| l.split_once('='))
        .collect();
    assert_eq!(header["pokerkit"], "0.7.8");
    assert_eq!(header["record"], "rank_a:u16le rank_b:u16le");
    let seed: u64 = header["seed"].parse().unwrap();
    let count: usize = header["count"].parse().unwrap();
    let body = &FIXTURE[split..];
    assert_eq!(count, 1_000_000);
    assert_eq!(body.len(), count * 4);

    // PokerKit's categories: every hand it labelled with category i has a rank in the
    // i-th range, so each range must sit inside our range for that category.
    let ranges: Vec<(u16, u16)> = header["category_ranges"]
        .split(',')
        .map(|r| {
            let (lo, hi) = r.split_once('-').unwrap();
            (lo.parse().unwrap(), hi.parse().unwrap())
        })
        .collect();
    assert_eq!(ranges.len(), 9);
    for (cat, (lo, hi)) in Category::ALL.into_iter().zip(ranges) {
        let (our_lo, our_hi) = cat.value_range();
        assert!(
            our_lo <= lo && hi <= our_hi,
            "{cat}: PokerKit {lo}-{hi}, ours {our_lo}-{our_hi}"
        );
    }

    let mut rng = SplitMix64(seed);
    let mut fnv = 0xCBF2_9CE4_8422_2325u64;
    let mut mismatches = Vec::new();
    let (mut a_wins, mut ties) = (0usize, 0usize);
    for (i, record) in body.chunks_exact(4).enumerate() {
        let deal = rng.deal(9);
        for c in &deal {
            fnv = (fnv ^ c.index() as u64).wrapping_mul(0x100_0000_01B3);
        }
        let expected_a = u16::from_le_bytes([record[0], record[1]]);
        let expected_b = u16::from_le_bytes([record[2], record[3]]);
        let board = Hand::from_cards(&deal[..5]);
        let a = board.add(deal[5]).add(deal[6]).eval7();
        let b = board.add(deal[7]).add(deal[8]).eval7();
        a_wins += (a > b) as usize;
        ties += (a == b) as usize;
        if a.value() != expected_a
            || b.value() != expected_b
            || a.cmp(&b) != expected_a.cmp(&expected_b)
        {
            mismatches.push(format!(
                "#{i} board {} A {} -> {a} (PokerKit {expected_a}), B {} -> {b} (PokerKit {expected_b})",
                format_cards(&deal[..5]),
                format_cards(&deal[5..7]),
                format_cards(&deal[7..9]),
            ));
        }
    }
    assert_eq!(
        format!("{fnv:016x}"),
        header["deal_fnv1a64"],
        "the deals differ from the Python script's; fix the dealing before reading results"
    );
    assert!(
        mismatches.is_empty(),
        "{} mismatches, first: {:#?}",
        mismatches.len(),
        &mismatches[..mismatches.len().min(10)]
    );
    // Same totals as the script printed: A wins 479,539, ties 40,635.
    assert_eq!((a_wins, ties), (479_539, 40_635));
}
