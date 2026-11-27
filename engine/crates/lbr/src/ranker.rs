//! Showdowns: the eval crate's evaluator as an nlhe [`HandRanker`](nlhe::HandRanker).
//!
//! [`EvalRanker`] is nlhe's own (`nlhe::EvalRanker`, feature `eval`), re-exported so that
//! `lbr::EvalRanker` names it. This crate used to have a copy of its own.

use nlhe::Card;

pub use nlhe::EvalRanker;

/// An nlhe card (`rank * 4 + suit`) as an eval card. The two crates use the same numbering.
#[inline(always)]
pub(crate) fn ecard(c: Card) -> eval::Card {
    match eval::Card::from_index(c) {
        Some(card) => card,
        None => panic!("card out of range"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nlhe::{BruteForceRanker, HandRanker, Rng};

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
