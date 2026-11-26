//! The eval crate's evaluator behind nlhe's [`HandRanker`] trait.

use nlhe::{Card, HandRanker};

/// Ranks showdowns with the eval crate: 1 (worst) to 7,462 (royal flush).
#[derive(Clone, Copy, Debug, Default)]
pub struct EvalRanker;

impl HandRanker for EvalRanker {
    #[inline]
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        let mut hand = eval::Hand::new();
        for &c in cards {
            hand = hand.add(to_eval(c));
        }
        hand.eval7().value() as u32
    }
}

/// An nlhe card as an eval card. Both crates use `rank * 4 + suit`.
#[inline]
pub fn to_eval(card: Card) -> eval::Card {
    eval::Card::from_index(card).expect("a card is below 52")
}
