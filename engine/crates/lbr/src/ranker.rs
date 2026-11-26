//! The eval crate's evaluator as an nlhe [`HandRanker`], so showdowns are fast.

use eval::Hand;
use nlhe::{Card, HandRanker};

/// Ranks seven cards with the eval crate (1 to 7,462, higher is better).
#[derive(Clone, Copy, Debug, Default)]
pub struct EvalRanker;

/// An nlhe card (`rank * 4 + suit`) as an eval card. The two crates use the same numbering.
#[inline(always)]
pub(crate) fn ecard(c: Card) -> eval::Card {
    match eval::Card::from_index(c) {
        Some(card) => card,
        None => panic!("card out of range"),
    }
}

impl HandRanker for EvalRanker {
    #[inline]
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        let mut hand = Hand::new();
        for &c in cards {
            hand = hand.add(ecard(c));
        }
        hand.eval7().value() as u32
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nlhe::{BruteForceRanker, Rng};

    #[test]
    fn agrees_with_the_brute_force_ranker_on_who_wins() {
        let mut rng = Rng::new(20261126);
        for _ in 0..3_000 {
            let mut deck: [Card; 52] = std::array::from_fn(|i| i as Card);
            rng.shuffle(&mut deck);
            let board = [deck[4], deck[5], deck[6], deck[7], deck[8]];
            let seven = |a: Card, b: Card| [a, b, board[0], board[1], board[2], board[3], board[4]];
            let (x, y) = (seven(deck[0], deck[1]), seven(deck[2], deck[3]));
            assert_eq!(
                EvalRanker.rank7(&x).cmp(&EvalRanker.rank7(&y)),
                BruteForceRanker.rank7(&x).cmp(&BruteForceRanker.rank7(&y)),
                "{x:?} against {y:?}"
            );
        }
    }
}
