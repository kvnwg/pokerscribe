//! Cards and combos. Every crate here numbers a card `rank * 4 + suit` (2c is 0, As is 51),
//! and a combo by lbr's index (0 to 1,325), so conversions are only type changes.

use nlhe::Card;

pub use lbr::{card_mask, combo_cards, combo_index, NUM_COMBOS};

/// The eval crate's card.
pub fn eval_card(c: Card) -> eval::Card {
    eval::Card::from_index(c).expect("a card is 0 to 51")
}

/// The subgame crate's combo for lbr's combo index.
pub fn subgame_combo(index: usize) -> subgame::Combo {
    let [a, b] = combo_cards(index);
    subgame::Combo::new(eval_card(a), eval_card(b)).expect("two different cards")
}

/// True when the combo uses a card of `mask`.
pub fn blocked(index: usize, mask: u64) -> bool {
    let [a, b] = combo_cards(index);
    (mask >> a) & 1 == 1 || (mask >> b) & 1 == 1
}

/// Every combo's two cards as a bit mask, by combo index.
pub fn combo_masks() -> Vec<u64> {
    (0..NUM_COMBOS)
        .map(|i| {
            let [a, b] = combo_cards(i);
            (1u64 << a) | (1u64 << b)
        })
        .collect()
}

/// SplitMix64's output step (the hash the blueprint and arena use for draws).
pub fn mix(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}
