//! Exhaustive and randomized checks of eval5, eval6 and eval7.
//!
//! The 6- and 7-card enumerations are slow in a debug build; run them with
//! `cargo test --release -p eval -- --ignored`.

mod common;

use common::{SplitMix64, best_of_subsets, naive5};
use eval::{Card, Category, DISTINCT_RANKS, Hand, eval, eval5, eval6, eval7};
use std::collections::{BTreeMap, HashSet};

fn cards() -> Vec<Card> {
    Card::all().collect()
}

#[test]
fn five_card_hands_have_7462_ranks_in_naive_order() {
    let deck = cards();
    let mut seen: BTreeMap<(u8, Vec<u8>), u16> = BTreeMap::new();
    let mut counts = [0u64; 9];
    let mut total = 0u64;
    for a in 0..52 {
        for b in a + 1..52 {
            for c in b + 1..52 {
                for d in c + 1..52 {
                    for e in d + 1..52 {
                        let five = [deck[a], deck[b], deck[c], deck[d], deck[e]];
                        let r = eval5(&five);
                        let key = naive5(&five);
                        assert_eq!(r.category() as u8, key.0, "{five:?}");
                        let prev = *seen.entry(key).or_insert(r.value());
                        assert_eq!(prev, r.value(), "same naive class, two ranks: {five:?}");
                        counts[r.category() as usize] += 1;
                        total += 1;
                    }
                }
            }
        }
    }
    assert_eq!(total, 2_598_960);
    assert_eq!(seen.len(), DISTINCT_RANKS as usize);
    // The naive order and the crate's numbers agree: 1, 2, ..., 7462 in naive order.
    let values: Vec<u16> = seen.values().copied().collect();
    assert_eq!(values, (1..=DISTINCT_RANKS).collect::<Vec<_>>());
    assert_eq!(
        counts,
        [
            1_302_540, 1_098_240, 123_552, 54_912, 10_200, 5_108, 3_744, 624, 40
        ]
    );
}

#[test]
fn random_six_and_seven_card_hands_match_best_subset() {
    let mut rng = SplitMix64(0xC0FFEE);
    for _ in 0..200_000 {
        let seven = rng.deal(7);
        let r7 = eval7(&seven.clone().try_into().unwrap());
        assert_eq!(r7, best_of_subsets(&seven), "{seven:?}");
        assert_eq!(r7, eval(&seven));
        assert_eq!(r7, Hand::from_cards(&seven).eval());
        let six = &seven[..6];
        let r6 = eval6(&six.try_into().unwrap());
        assert_eq!(r6, best_of_subsets(six), "{six:?}");
        assert_eq!(r6, Hand::from_cards(six).eval());
    }
}

#[test]
fn input_order_does_not_matter() {
    let mut rng = SplitMix64(42);
    for _ in 0..10_000 {
        let mut seven = rng.deal(7);
        let r = eval(&seven);
        seven.reverse();
        assert_eq!(eval(&seven), r);
        seven.rotate_left(3);
        assert_eq!(eval(&seven), r);
    }
}

#[test]
#[ignore = "slow: 133,784,560 hands; run with --release -- --ignored"]
#[allow(clippy::needless_range_loop)]
fn seven_card_category_counts() {
    let deck = cards();
    let mut counts = [0u64; 9];
    let mut distinct = vec![false; DISTINCT_RANKS as usize + 1];
    for a in 0..52 {
        let ha = Hand::new().add(deck[a]);
        for b in a + 1..52 {
            let hb = ha.add(deck[b]);
            for c in b + 1..52 {
                let hc = hb.add(deck[c]);
                for d in c + 1..52 {
                    let hd = hc.add(deck[d]);
                    for e in d + 1..52 {
                        let he = hd.add(deck[e]);
                        for f in e + 1..52 {
                            let hf = he.add(deck[f]);
                            for g in f + 1..52 {
                                let r = hf.add(deck[g]).eval7();
                                counts[r.category() as usize] += 1;
                                distinct[r.value() as usize] = true;
                            }
                        }
                    }
                }
            }
        }
    }
    let expected = [
        (Category::HighCard, 23_294_460),
        (Category::Pair, 58_627_800),
        (Category::TwoPair, 31_433_400),
        (Category::ThreeOfAKind, 6_461_620),
        (Category::Straight, 6_180_020),
        (Category::Flush, 4_047_644),
        (Category::FullHouse, 3_473_184),
        (Category::FourOfAKind, 224_848),
        (Category::StraightFlush, 41_584),
    ];
    for (cat, n) in expected {
        assert_eq!(counts[cat as usize], n, "{cat}");
    }
    assert_eq!(counts.iter().sum::<u64>(), 133_784_560);
    // Known result: only 4,824 of the 7,462 classes can be the best hand of 7 cards.
    assert_eq!(distinct.iter().filter(|&&x| x).count(), 4824);
}

#[test]
#[ignore = "slow: 20,358,520 hands; run with --release -- --ignored"]
fn every_six_card_hand_matches_best_subset() {
    let deck = cards();
    let mut distinct = HashSet::new();
    let mut total = 0u64;
    for a in 0..52 {
        for b in a + 1..52 {
            for c in b + 1..52 {
                for d in c + 1..52 {
                    for e in d + 1..52 {
                        for f in e + 1..52 {
                            let six = [deck[a], deck[b], deck[c], deck[d], deck[e], deck[f]];
                            let r = eval6(&six);
                            let best = (0..6)
                                .map(|skip| {
                                    let mut five = [six[0]; 5];
                                    let mut k = 0;
                                    for (i, &card) in six.iter().enumerate() {
                                        if i != skip {
                                            five[k] = card;
                                            k += 1;
                                        }
                                    }
                                    eval5(&five)
                                })
                                .max()
                                .unwrap();
                            assert_eq!(r, best, "{six:?}");
                            distinct.insert(r);
                            total += 1;
                        }
                    }
                }
            }
        }
    }
    assert_eq!(total, 20_358_520);
    // Known result: 6,075 classes can be the best hand of 6 cards.
    assert_eq!(distinct.len(), 6075);
}
