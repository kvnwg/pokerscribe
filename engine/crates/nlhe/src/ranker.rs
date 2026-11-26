//! Showdown ranking.
//!
//! The engine never ranks hands itself: it asks a [`HandRanker`]. Two are provided:
//!
//! - [`BruteForceRanker`] is slow on purpose and simple enough to check by reading. It is
//!   the reference the tests use.
//! - [`EvalRanker`] (feature `eval`, on by default) uses the eval crate's table evaluator.
//!   It is the one to play and solve with. The tests check that the two always agree.

use crate::cards::{rank_of, suit_of, Card};

/// Ranks seven-card Hold'em hands (two hole cards and five board cards).
///
/// A higher value is a better hand and equal values tie. Only the order matters, so any
/// evaluator works as long as it agrees with standard high-hand rules.
pub trait HandRanker {
    fn rank7(&self, cards: &[Card; 7]) -> u32;
}

impl<R: HandRanker + ?Sized> HandRanker for &R {
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        (**self).rank7(cards)
    }
}

/// Tries all 21 five-card hands and keeps the best.
#[derive(Clone, Copy, Debug, Default)]
pub struct BruteForceRanker;

/// Hand categories, worst to best. `rank5` puts the category in bits 20 and up.
pub const HIGH_CARD: u32 = 0;
pub const PAIR: u32 = 1;
pub const TWO_PAIR: u32 = 2;
pub const TRIPS: u32 = 3;
pub const STRAIGHT: u32 = 4;
pub const FLUSH: u32 = 5;
pub const FULL_HOUSE: u32 = 6;
pub const QUADS: u32 = 7;
pub const STRAIGHT_FLUSH: u32 = 8;

/// The category of a value from [`rank5`] or [`BruteForceRanker`].
pub fn category(value: u32) -> u32 {
    value >> 20
}

/// Ranks five cards: the category in bits 20 and up, then five 4-bit ranks that break
/// ties, most important first.
pub fn rank5(cards: [Card; 5]) -> u32 {
    let mut counts = [0u8; 13];
    for &c in &cards {
        counts[rank_of(c) as usize] += 1;
    }
    let flush = cards.iter().all(|&c| suit_of(c) == suit_of(cards[0]));

    // Ranks ordered by how many times they appear, then by rank, both descending.
    let mut order: Vec<(u8, u8)> = (0..13u8)
        .filter(|&r| counts[r as usize] > 0)
        .map(|r| (counts[r as usize], r))
        .collect();
    order.sort_unstable_by(|a, b| b.cmp(a));

    // Five different ranks in a row; the wheel (A-2-3-4-5) counts the ace as low.
    let straight_high = if order.len() == 5 {
        let ranks: Vec<u8> = order.iter().map(|&(_, r)| r).collect();
        if ranks[0] - ranks[4] == 4 {
            Some(ranks[0])
        } else if ranks == [12, 3, 2, 1, 0] {
            Some(3)
        } else {
            None
        }
    } else {
        None
    };

    let shape: Vec<u8> = order.iter().map(|&(n, _)| n).collect();
    let cat = match (straight_high, flush, shape.as_slice()) {
        (Some(_), true, _) => STRAIGHT_FLUSH,
        (_, _, [4, 1]) => QUADS,
        (_, _, [3, 2]) => FULL_HOUSE,
        (_, true, _) => FLUSH,
        (Some(_), false, _) => STRAIGHT,
        (_, _, [3, 1, 1]) => TRIPS,
        (_, _, [2, 2, 1]) => TWO_PAIR,
        (_, _, [2, 1, 1, 1]) => PAIR,
        _ => HIGH_CARD,
    };

    let mut tiebreak = [0u8; 5];
    match straight_high {
        Some(high) if cat == STRAIGHT || cat == STRAIGHT_FLUSH => tiebreak[0] = high,
        _ => {
            for (slot, &(_, r)) in tiebreak.iter_mut().zip(order.iter()) {
                *slot = r;
            }
        }
    }
    let mut value = cat << 20;
    for (k, &r) in tiebreak.iter().enumerate() {
        value |= (r as u32) << (16 - 4 * k);
    }
    value
}

impl HandRanker for BruteForceRanker {
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        let mut best = 0;
        for skip_a in 0..7 {
            for skip_b in skip_a + 1..7 {
                let mut five = [0; 5];
                let mut k = 0;
                for (i, &c) in cards.iter().enumerate() {
                    if i != skip_a && i != skip_b {
                        five[k] = c;
                        k += 1;
                    }
                }
                best = best.max(rank5(five));
            }
        }
        best
    }
}

/// Ranks with the eval crate's table evaluator: about 6 nanoseconds a hand, against about
/// 4 microseconds for [`BruteForceRanker`] (`cargo run --release -p nlhe --example rankers`).
///
/// The value is the eval crate's hand rank, 1 (7-5-4-3-2 offsuit) to 7,462 (royal flush).
/// It orders hands exactly as [`BruteForceRanker`] does, but the numbers themselves are
/// different, so never compare a value from one ranker with a value from the other.
///
/// Panics if a card is not in `0..52`. The seven cards must be different (the engine only
/// passes cards from a checked [`crate::Deal`]).
#[cfg(feature = "eval")]
#[derive(Clone, Copy, Debug, Default)]
pub struct EvalRanker;

#[cfg(feature = "eval")]
impl HandRanker for EvalRanker {
    #[inline]
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        // Both crates number the cards the same way: rank * 4 + suit.
        let hand = cards.iter().fold(eval::Hand::new(), |hand, &c| {
            hand.add(eval::Card::from_index(c).expect("a card is in 0..52"))
        });
        hand.eval7().value() as u32
    }
}
