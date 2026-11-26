//! Showdowns: the eval crate's evaluator behind nlhe's [`HandRanker`] trait.

use nlhe::{Card, HandRanker};

/// Ranks showdowns with the eval crate. `nlhe` only needs the order of the values:
/// higher is better and equal values tie, which is how `eval::HandRank` is numbered.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct EvalRanker;

impl HandRanker for EvalRanker {
    #[inline]
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        let mut hand = eval::Hand::new();
        for &card in cards {
            hand = hand.add(to_eval(card));
        }
        hand.eval7().value() as u32
    }
}

/// An `nlhe` card as an `eval` card. Both number cards `rank * 4 + suit`.
#[inline]
pub(crate) fn to_eval(card: Card) -> eval::Card {
    eval::Card::from_index(card).expect("a card is 0..52")
}

#[cfg(test)]
mod tests {
    use super::*;
    use cfr::Rng;
    use nlhe::{card_string, BruteForceRanker};

    #[test]
    fn cards_are_numbered_the_same_way() {
        for card in 0..52u8 {
            let e = to_eval(card);
            assert_eq!(e.to_string(), card_string(card));
            assert_eq!((e.rank(), e.suit()), (card / 4, card % 4));
        }
    }

    #[test]
    fn same_order_as_the_brute_force_ranker() {
        // Two hands on a shared board, 20,000 times: the two rankers agree on who wins.
        let mut rng = Rng::new(42);
        let mut ties = 0;
        for _ in 0..20_000 {
            let mut deck: Vec<Card> = (0..52).collect();
            for i in 0..9 {
                let j = i + rng.below(52 - i);
                deck.swap(i, j);
            }
            let hand = |a: usize| {
                let mut seven = [0; 7];
                seven[..2].copy_from_slice(&deck[a..a + 2]);
                seven[2..].copy_from_slice(&deck[4..9]);
                seven
            };
            let (x, y) = (hand(0), hand(2));
            let fast = EvalRanker.rank7(&x).cmp(&EvalRanker.rank7(&y));
            let slow = BruteForceRanker.rank7(&x).cmp(&BruteForceRanker.rank7(&y));
            assert_eq!(fast, slow, "{x:?} against {y:?}");
            ties += (fast == std::cmp::Ordering::Equal) as u32;
        }
        assert!(ties > 100, "split pots should turn up: {ties}");
    }
}
