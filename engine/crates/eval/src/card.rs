//! Cards: `index = rank * 4 + suit`, rank 0 = 2 up to 12 = ace, suit 0..3 = c, d, h, s.

use std::fmt;
use std::str::FromStr;

/// Rank characters, from rank 0 (deuce) to rank 12 (ace).
pub const RANK_CHARS: [char; 13] = [
    '2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A',
];
/// Suit characters, from suit 0 to suit 3.
pub const SUIT_CHARS: [char; 4] = ['c', 'd', 'h', 's'];

/// One card of a 52-card deck.
#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Card(u8);

impl Card {
    /// Card from rank (0 = 2 .. 12 = ace) and suit (0..3 = c, d, h, s). Panics out of range.
    pub const fn new(rank: u8, suit: u8) -> Card {
        assert!(rank < 13 && suit < 4, "rank must be 0..13 and suit 0..4");
        Card(rank * 4 + suit)
    }

    /// Card from its index `rank * 4 + suit`, or `None` when the index is 52 or more.
    pub const fn from_index(index: u8) -> Option<Card> {
        if index < 52 { Some(Card(index)) } else { None }
    }

    /// The index `rank * 4 + suit`, 0..52.
    pub const fn index(self) -> u8 {
        self.0
    }

    /// Rank, 0 = 2 up to 12 = ace.
    pub const fn rank(self) -> u8 {
        self.0 >> 2
    }

    /// Suit, 0..3 = c, d, h, s.
    pub const fn suit(self) -> u8 {
        self.0 & 3
    }

    /// All 52 cards in index order.
    pub fn all() -> impl Iterator<Item = Card> {
        (0..52).map(Card)
    }
}

/// Why a card string could not be read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ParseCardError {
    /// The text was not exactly two characters.
    Length(String),
    /// The first character is not one of `23456789TJQKA`.
    Rank(char),
    /// The second character is not one of `cdhs`.
    Suit(char),
}

impl fmt::Display for ParseCardError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseCardError::Length(s) => write!(f, "a card is 2 characters like \"Ah\", got {s:?}"),
            ParseCardError::Rank(c) => write!(f, "unknown rank {c:?} (use 23456789TJQKA)"),
            ParseCardError::Suit(c) => write!(f, "unknown suit {c:?} (use cdhs)"),
        }
    }
}

impl std::error::Error for ParseCardError {}

fn rank_of(c: char) -> Option<u8> {
    let c = c.to_ascii_uppercase();
    RANK_CHARS.iter().position(|&r| r == c).map(|r| r as u8)
}

fn suit_of(c: char) -> Option<u8> {
    let c = c.to_ascii_lowercase();
    SUIT_CHARS.iter().position(|&s| s == c).map(|s| s as u8)
}

impl FromStr for Card {
    type Err = ParseCardError;

    /// Reads `"Ah"`, `"Td"`, `"2c"`. Letters may be either case (`"ah"`, `"AH"`).
    fn from_str(s: &str) -> Result<Card, ParseCardError> {
        let mut chars = s.chars();
        let (Some(r), Some(u), None) = (chars.next(), chars.next(), chars.next()) else {
            return Err(ParseCardError::Length(s.to_string()));
        };
        let rank = rank_of(r).ok_or(ParseCardError::Rank(r))?;
        let suit = suit_of(u).ok_or(ParseCardError::Suit(u))?;
        Ok(Card::new(rank, suit))
    }
}

impl fmt::Display for Card {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}{}",
            RANK_CHARS[self.rank() as usize],
            SUIT_CHARS[self.suit() as usize]
        )
    }
}

impl fmt::Debug for Card {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

/// Reads a list of cards such as `"AhKs Qd"`, `"Ah Ks Qd"` or `"Ah,Ks,Qd"`.
/// Spaces and commas between cards are optional.
pub fn parse_cards(s: &str) -> Result<Vec<Card>, ParseCardError> {
    let chars: Vec<char> = s
        .chars()
        .filter(|c| !c.is_whitespace() && *c != ',')
        .collect();
    chars
        .chunks(2)
        .map(|pair| pair.iter().collect::<String>().parse())
        .collect()
}

/// Writes cards next to each other, like `"AhKsQd"`.
pub fn format_cards(cards: &[Card]) -> String {
    cards.iter().map(Card::to_string).collect()
}
