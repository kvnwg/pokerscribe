//! Ranges: a weight for each of the 1,326 two-card hands.

use nlhe::Card;

/// The number of two-card hands.
pub const NUM_COMBOS: usize = 1326;

/// The index of the hand holding cards `a` and `b`, in `0..1326`: `hi * (hi - 1) / 2 + lo`.
#[inline(always)]
pub fn combo_index(a: Card, b: Card) -> usize {
    let (lo, hi) = if a < b { (a, b) } else { (b, a) };
    debug_assert!(lo != hi && hi < 52, "not two different cards");
    hi as usize * (hi as usize - 1) / 2 + lo as usize
}

const COMBOS: [[Card; 2]; NUM_COMBOS] = {
    let mut table = [[0; 2]; NUM_COMBOS];
    let mut hi = 1;
    while hi < 52 {
        let mut lo = 0;
        while lo < hi {
            table[hi * (hi - 1) / 2 + lo] = [lo as Card, hi as Card];
            lo += 1;
        }
        hi += 1;
    }
    table
};

const COMBO_MASKS: [u64; NUM_COMBOS] = {
    let mut table = [0; NUM_COMBOS];
    let mut i = 0;
    while i < NUM_COMBOS {
        table[i] = 1 << COMBOS[i][0] | 1 << COMBOS[i][1];
        i += 1;
    }
    table
};

/// The two cards of hand `index`, lower card first.
#[inline(always)]
pub fn combo_cards(index: usize) -> [Card; 2] {
    COMBOS[index]
}

/// The cards as bits: bit `c` for card `c`.
pub fn card_mask(cards: &[Card]) -> u64 {
    cards.iter().fold(0, |mask, &c| mask | 1 << c)
}

/// How likely each two-card hand is, as weights that need not sum to 1.
#[derive(Clone, Debug, PartialEq)]
pub struct Range {
    weights: [f64; NUM_COMBOS],
}

impl Range {
    /// No hands.
    pub fn empty() -> Range {
        Range {
            weights: [0.0; NUM_COMBOS],
        }
    }

    /// Every hand equally likely.
    pub fn uniform() -> Range {
        Range {
            weights: [1.0; NUM_COMBOS],
        }
    }

    /// The listed hands, equally likely.
    pub fn from_hands(hands: &[[Card; 2]]) -> Range {
        let mut range = Range::empty();
        for hand in hands {
            range.set(*hand, 1.0);
        }
        range
    }

    pub fn weights(&self) -> &[f64; NUM_COMBOS] {
        &self.weights
    }

    pub fn weights_mut(&mut self) -> &mut [f64; NUM_COMBOS] {
        &mut self.weights
    }

    /// The weight of one hand.
    pub fn weight(&self, hand: [Card; 2]) -> f64 {
        self.weights[combo_index(hand[0], hand[1])]
    }

    pub fn set(&mut self, hand: [Card; 2], weight: f64) {
        assert!(weight >= 0.0, "a weight cannot be negative");
        self.weights[combo_index(hand[0], hand[1])] = weight;
    }

    /// The sum of all weights.
    pub fn total(&self) -> f64 {
        self.weights.iter().sum()
    }

    /// The probability of one hand: its weight over the total (0 for an empty range).
    pub fn probability(&self, hand: [Card; 2]) -> f64 {
        let total = self.total();
        if total > 0.0 {
            self.weight(hand) / total
        } else {
            0.0
        }
    }

    /// Removes every hand that holds one of the `dead` cards (a bit mask, see [`card_mask`]).
    /// Returns true if a hand with a positive weight was removed.
    pub fn remove_cards(&mut self, dead: u64) -> bool {
        let mut removed = false;
        for (w, mask) in self.weights.iter_mut().zip(COMBO_MASKS.iter()) {
            if mask & dead != 0 && *w > 0.0 {
                *w = 0.0;
                removed = true;
            }
        }
        removed
    }

    /// Scales the weights to sum to 1. Returns false, changing nothing, for an empty range.
    pub fn normalize(&mut self) -> bool {
        let total = self.total();
        if total > 0.0 {
            for w in &mut self.weights {
                *w /= total;
            }
        }
        total > 0.0
    }

    /// The hands with a positive weight, as `(index, weight)`.
    pub fn live(&self) -> impl Iterator<Item = (usize, f64)> + '_ {
        self.weights
            .iter()
            .enumerate()
            .filter(|(_, w)| **w > 0.0)
            .map(|(i, w)| (i, *w))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn indices_and_cards_round_trip() {
        let mut seen = [false; NUM_COMBOS];
        for a in 0..52 {
            for b in 0..a {
                let i = combo_index(a, b);
                assert_eq!(i, combo_index(b, a));
                assert_eq!(combo_cards(i), [b, a]);
                assert!(!seen[i]);
                seen[i] = true;
            }
        }
        assert!(seen.iter().all(|&s| s));
    }

    #[test]
    fn removing_cards_leaves_the_hands_without_them() {
        let mut range = Range::uniform();
        range.remove_cards(card_mask(&[0, 17, 51]));
        assert_eq!(range.total(), (49 * 48 / 2) as f64);
        assert_eq!(range.weight([0, 1]), 0.0);
        assert_eq!(range.weight([1, 2]), 1.0);
        assert!(range.normalize());
        assert!((range.total() - 1.0).abs() < 1e-12);
        assert!((range.probability([1, 2]) - 1.0 / 1176.0).abs() < 1e-15);
        assert!(!Range::empty().normalize());
    }
}
