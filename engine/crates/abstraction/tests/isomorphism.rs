//! Suit isomorphism: the counts, and that every hand maps to a canonical one and back.
//!
//! The fast tests run with `cargo test -p abstraction`. The exhaustive ones over every
//! turn and river hand are slow in a debug build, so they are ignored by default:
//!
//! ```bash
//! cargo test --release -p abstraction --test isomorphism -- --ignored
//! ```

use abstraction::{Deck, HandIndexer};
use rayon::prelude::*;

const SUIT_ORDERS: [[u8; 4]; 24] = {
    let mut out = [[0u8; 4]; 24];
    let mut n = 0;
    let mut a = 0;
    while a < 4 {
        let mut b = 0;
        while b < 4 {
            let mut c = 0;
            while c < 4 {
                let d = 6 - a - b - c;
                if a != b && a != c && b != c && d < 4 && d != a && d != b && d != c {
                    out[n] = [a as u8, b as u8, c as u8, d as u8];
                    n += 1;
                }
                c += 1;
            }
            b += 1;
        }
        a += 1;
    }
    assert!(n == 24);
    out
};

fn relabel(cards: &[u8], order: &[u8; 4]) -> Vec<u8> {
    cards.iter().map(|&c| (c & !3) | order[(c & 3) as usize]).collect()
}

/// A hand's cards as sorted rounds, so two hands can be compared as sets.
fn sorted_rounds(cards: &[u8], rounds: &[u8]) -> Vec<u8> {
    let mut out = cards.to_vec();
    let mut at = 0;
    for &n in rounds {
        out[at..at + n as usize].sort_unstable();
        at += n as usize;
    }
    out
}

#[test]
fn canonical_hand_counts() {
    assert_eq!(HandIndexer::new(&[2]).size(), 169);
    assert_eq!(HandIndexer::new(&[2, 3]).size(), 1_286_792);
    assert_eq!(HandIndexer::new(&[2, 4]).size(), 13_960_050);
    assert_eq!(HandIndexer::new(&[2, 5]).size(), 123_156_254);
}

/// The counts when the order of the board cards is remembered (flop, then turn, then
/// river), and for boards alone. These are not used for buckets; they check the method
/// against the other published numbers.
#[test]
fn counts_for_other_deals() {
    assert_eq!(HandIndexer::new(&[2, 3, 1]).size(), 55_190_538);
    assert_eq!(HandIndexer::new(&[2, 3, 1, 1]).size(), 2_428_287_420);
    assert_eq!(HandIndexer::new(&[3]).size(), 1_755);
    assert_eq!(HandIndexer::new(&[4]).size(), 16_432);
    assert_eq!(HandIndexer::new(&[5]).size(), 134_459);
}

/// Burnside's lemma gives the number of suit classes without using the indexer: the average,
/// over the 24 suit relabellings, of the hands each one leaves unchanged. Counted here by
/// brute force on a small deck.
#[test]
fn small_deck_counts_match_brute_force() {
    for ranks in [3u8, 4, 5] {
        let deck = Deck::new(ranks);
        for rounds in [&[2u8][..], &[2, 3], &[2, 4], &[2, 5], &[3], &[5], &[2, 3, 1]] {
            let cards: usize = rounds.iter().map(|&n| n as usize).sum();
            if cards > deck.len() {
                continue;
            }
            let indexer = HandIndexer::with_deck(deck, rounds);
            // Every deal: a set of cards for each round, as the smallest relabelling.
            let mut classes = std::collections::HashSet::new();
            let mut hits = vec![0u32; indexer.size() as usize];
            let mut hand = vec![0u8; cards];
            for_each_deal(deck, rounds, 0, 0, &mut hand, &mut |hand| {
                let smallest = SUIT_ORDERS
                    .iter()
                    .map(|o| sorted_rounds(&relabel(hand, o), rounds))
                    .min()
                    .unwrap();
                classes.insert(smallest);
                hits[indexer.index(hand) as usize] += 1;
            });
            assert_eq!(indexer.size(), classes.len() as u64, "ranks {ranks} rounds {rounds:?}");
            for (i, &n) in hits.iter().enumerate() {
                assert_eq!(n, indexer.multiplicity(i as u64), "ranks {ranks} rounds {rounds:?} index {i}");
            }
        }
    }
}

/// Calls `f` with every deal: all choices of each round's cards, as sets.
fn for_each_deal(deck: Deck, rounds: &[u8], round: usize, at: usize, hand: &mut Vec<u8>, f: &mut impl FnMut(&[u8])) {
    if round == rounds.len() {
        f(hand);
        return;
    }
    fn choose_round(
        deck: Deck,
        rounds: &[u8],
        round: usize,
        at: usize,
        picked: usize,
        from: u8,
        hand: &mut Vec<u8>,
        f: &mut impl FnMut(&[u8]),
    ) {
        if picked == rounds[round] as usize {
            for_each_deal(deck, rounds, round + 1, at + picked, hand, f);
            return;
        }
        for c in from..52 {
            if hand[..at + picked].contains(&c) {
                continue;
            }
            hand[at + picked] = c;
            choose_round(deck, rounds, round, at, picked + 1, c + 1, hand, f);
        }
    }
    choose_round(deck, rounds, round, at, 0, deck.first_card(), hand, f);
}

/// `index(unindex(i)) == i` for every index, and the canonical hand has distinct cards.
fn check_round_trip(indexer: &HandIndexer) {
    let n = indexer.cards();
    (0..indexer.size()).into_par_iter().for_each(|i| {
        let mut hand = [0u8; 7];
        indexer.unindex(i, &mut hand[..n]);
        let mut seen = 0u64;
        for &c in &hand[..n] {
            assert!(c < 52 && seen & (1 << c) == 0, "index {i}: bad hand {:?}", &hand[..n]);
            seen |= 1 << c;
        }
        assert_eq!(indexer.index(&hand[..n]), i, "hand {:?}", &hand[..n]);
    });
}

/// Every raw deal of hole cards and board maps to an index in range, and each index is hit
/// by exactly `multiplicity` deals. So every index is used and the multiplicities are right.
fn check_every_deal(board_cards: usize) {
    let indexer = HandIndexer::new(&[2, board_cards as u8]);
    let hits: Vec<std::sync::atomic::AtomicU8> =
        (0..indexer.size()).map(|_| std::sync::atomic::AtomicU8::new(0)).collect();
    let holes: Vec<(u8, u8)> = (0..52u8).flat_map(|a| (a + 1..52).map(move |b| (a, b))).collect();
    let deals: u64 = holes
        .par_iter()
        .map(|&(a, b)| {
            let rest: Vec<u8> = (0..52u8).filter(|&c| c != a && c != b).collect();
            let mut hand = [0u8; 7];
            hand[0] = a;
            hand[1] = b;
            let mut pick = [0usize; 5];
            for (i, p) in pick.iter_mut().enumerate().take(board_cards) {
                *p = i;
            }
            let mut deals = 0u64;
            loop {
                for i in 0..board_cards {
                    hand[2 + i] = rest[pick[i]];
                }
                let index = indexer.index(&hand[..2 + board_cards]);
                hits[index as usize].fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                deals += 1;
                // Next combination of board cards.
                let mut i = board_cards;
                loop {
                    if i == 0 {
                        return deals;
                    }
                    i -= 1;
                    if pick[i] < rest.len() - (board_cards - i) {
                        pick[i] += 1;
                        for j in i + 1..board_cards {
                            pick[j] = pick[j - 1] + 1;
                        }
                        break;
                    }
                }
            }
        })
        .sum();
    let expected: u64 = match board_cards {
        3 => 1326 * 19_600,
        4 => 1326 * 230_300,
        5 => 1326 * 2_118_760,
        _ => unreachable!(),
    };
    assert_eq!(deals, expected);
    let wrong = (0..indexer.size())
        .into_par_iter()
        .filter(|&i| {
            hits[i as usize].load(std::sync::atomic::Ordering::Relaxed) as u32 != indexer.multiplicity(i)
        })
        .count();
    assert_eq!(wrong, 0, "indexes hit a number of times other than their multiplicity");
}

#[test]
fn preflop_and_flop_round_trip() {
    check_round_trip(&HandIndexer::new(&[2]));
    check_round_trip(&HandIndexer::new(&[2, 3]));
    check_round_trip(&HandIndexer::new(&[5]));
}

#[test]
fn every_flop_deal_maps_to_a_canonical_hand() {
    check_every_deal(3);
}

#[test]
#[ignore = "slow in a debug build"]
fn turn_round_trip() {
    check_round_trip(&HandIndexer::new(&[2, 4]));
}

#[test]
#[ignore = "slow in a debug build"]
fn river_round_trip() {
    check_round_trip(&HandIndexer::new(&[2, 5]));
}

#[test]
#[ignore = "305 million deals"]
fn every_turn_deal_maps_to_a_canonical_hand() {
    check_every_deal(4);
}

#[test]
#[ignore = "2.8 billion deals"]
fn every_river_deal_maps_to_a_canonical_hand() {
    check_every_deal(5);
}

/// On random turn and river hands: all 24 suit relabellings and any order inside a round
/// give the same index, and the canonical hand is one of the relabellings.
#[test]
fn relabelled_hands_share_an_index() {
    let mut rng = abstraction::rng::Rng::new(2026);
    for rounds in [&[2u8, 3][..], &[2, 4], &[2, 5], &[2, 3, 1, 1]] {
        let indexer = HandIndexer::new(rounds);
        let n = indexer.cards();
        for _ in 0..20_000 {
            let mut deck: Vec<u8> = (0..52).collect();
            for i in 0..n {
                let j = i + rng.below((52 - i) as u64) as usize;
                deck.swap(i, j);
            }
            let hand = &deck[..n];
            let index = indexer.index(hand);
            let mut canonical = vec![0u8; n];
            indexer.unindex(index, &mut canonical);
            let canonical = sorted_rounds(&canonical, rounds);
            let mut found = false;
            for order in &SUIT_ORDERS {
                let mut other = relabel(hand, order);
                assert_eq!(indexer.index(&other), index);
                found |= sorted_rounds(&other, rounds) == canonical;
                // Order inside a round doesn't matter.
                other[..2].reverse();
                let board = rounds[1] as usize;
                other[2..2 + board].reverse();
                assert_eq!(indexer.index(&other), index);
            }
            assert!(found, "canonical hand is not a relabelling of {hand:?}");
        }
    }
}

/// Hands that are not relabellings of each other get different indexes: swapping a hole
/// card with a board card of another rank or suit pattern changes the index.
#[test]
fn hole_cards_and_board_are_kept_apart() {
    let indexer = HandIndexer::new(&[2, 3]);
    let cards = abstraction::parse_cards("AhKh QhJh2c").unwrap();
    let swapped = abstraction::parse_cards("QhJh AhKh2c").unwrap();
    assert_ne!(indexer.index(&cards), indexer.index(&swapped));
    let other_suits = abstraction::parse_cards("AsKs QsJs2d").unwrap();
    assert_eq!(indexer.index(&cards), indexer.index(&other_suits));
    let offsuit_two = abstraction::parse_cards("AsKs QsJs2s").unwrap();
    assert_ne!(indexer.index(&cards), indexer.index(&offsuit_two));
}
