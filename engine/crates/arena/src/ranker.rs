//! Showdowns: the eval crate's evaluator behind nlhe's [`HandRanker`](nlhe::HandRanker) trait.
//!
//! [`EvalRanker`] is nlhe's own (`nlhe::EvalRanker`, feature `eval`), re-exported so that
//! `arena::EvalRanker` and `arena::ranker::EvalRanker` name it. This crate used to have a
//! copy of its own.

use nlhe::Card;

pub use nlhe::EvalRanker;

/// An nlhe card as an eval card. Both crates use `rank * 4 + suit`.
#[inline]
pub fn to_eval(card: Card) -> eval::Card {
    eval::Card::from_index(card).expect("a card is below 52")
}
