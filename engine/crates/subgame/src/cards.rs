//! Cards and combos, spelled as in `data/SPOT_FORMAT.md`.
//!
//! A card is the `eval` crate's [`Card`]: `index = rank * 4 + suit`, suits in the order
//! c, d, h, s. The canonical spelling of a combo is "higher rank first, then by suit in the
//! order s, h, d, c", which is the same as "higher card index first".

use eval::Card;

const RANKS: &str = "23456789TJQKA";
const SUITS: &str = "cdhs";

/// Reads one card. Unlike `Card::from_str` this takes only the exact spelling of the
/// format: an upper-case rank and a lower-case suit (`"Ah"`, `"Td"`).
pub fn parse_card(text: &str) -> Result<Card, String> {
    let b = text.as_bytes();
    if b.len() == 2 {
        if let (Some(r), Some(s)) = (RANKS.find(b[0] as char), SUITS.find(b[1] as char)) {
            return Ok(Card::new(r as u8, s as u8));
        }
    }
    Err(format!("not a card: {text:?}"))
}

/// Two different hole cards, the higher card index first.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct Combo {
    pub hi: Card,
    pub lo: Card,
}

impl Combo {
    /// The combo of two cards in either order. `None` when they are the same card.
    pub fn new(a: Card, b: Card) -> Option<Combo> {
        match a.index().cmp(&b.index()) {
            std::cmp::Ordering::Greater => Some(Combo { hi: a, lo: b }),
            std::cmp::Ordering::Less => Some(Combo { hi: b, lo: a }),
            std::cmp::Ordering::Equal => None,
        }
    }

    /// Reads `"AhKd"`, with the two cards in either order.
    pub fn parse(text: &str) -> Result<Combo, String> {
        if text.len() != 4 || !text.is_ascii() {
            return Err(format!("not a combo: {text:?}"));
        }
        let a = parse_card(&text[..2]).map_err(|_| format!("not a combo: {text:?}"))?;
        let b = parse_card(&text[2..]).map_err(|_| format!("not a combo: {text:?}"))?;
        Combo::new(a, b).ok_or_else(|| format!("{text:?} uses the same card twice"))
    }

    /// The canonical spelling, `"AhKd"`.
    pub fn text(&self) -> String {
        format!("{}{}", self.hi, self.lo)
    }

    pub fn contains(&self, card: Card) -> bool {
        self.hi == card || self.lo == card
    }

    /// The two card indices, `[hi, lo]`.
    pub fn indices(&self) -> [u8; 2] {
        [self.hi.index(), self.lo.index()]
    }
}

/// The cards that can still come, in the order of the format: 2c 2d 2h 2s 3c ... As.
pub fn deck_left(board: &[Card]) -> Vec<Card> {
    Card::all().filter(|c| !board.contains(c)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn combos_are_spelled_higher_rank_first_then_s_h_d_c() {
        for (given, want) in [
            ("AhKd", "AhKd"),
            ("KdAh", "AhKd"),
            ("QhQs", "QsQh"),
            ("QsKh", "KhQs"),
            ("2c2d", "2d2c"),
            ("TdTc", "TdTc"),
        ] {
            assert_eq!(Combo::parse(given).unwrap().text(), want);
        }
    }

    #[test]
    fn bad_cards_and_combos_are_refused() {
        for bad in ["ah", "AH", "1h", "Ah ", "A", ""] {
            assert!(parse_card(bad).is_err(), "{bad:?}");
        }
        for bad in ["AhAh", "AhK", "AhKdQc", "ahkd", "Ah Kd"] {
            assert!(Combo::parse(bad).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn the_deck_is_dealt_in_format_order() {
        let board: Vec<Card> = ["2c", "As"]
            .iter()
            .map(|c| parse_card(c).unwrap())
            .collect();
        let left = deck_left(&board);
        assert_eq!(left.len(), 50);
        let names: Vec<String> = left.iter().take(4).map(|c| c.to_string()).collect();
        assert_eq!(names, ["2d", "2h", "2s", "3c"]);
        assert_eq!(left.last().unwrap().to_string(), "Ah");
    }
}
