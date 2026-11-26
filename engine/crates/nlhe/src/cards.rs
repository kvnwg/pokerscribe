//! Cards, deals and the seeded shuffle.
//!
//! A card is `rank * 4 + suit`: rank 0 is a two and 12 an ace, suits 0 to 3 are clubs,
//! diamonds, hearts and spades. This is the encoding the eval crate uses too.

use std::fmt;

use crate::MAX_PLAYERS;

/// A card, `rank * 4 + suit`, in `0..52`.
pub type Card = u8;

pub const RANK_CHARS: &[u8; 13] = b"23456789TJQKA";
pub const SUIT_CHARS: &[u8; 4] = b"cdhs";

/// The card with this rank (0 = two ... 12 = ace) and suit (0..4 = c, d, h, s).
pub const fn card(rank: u8, suit: u8) -> Card {
    rank * 4 + suit
}

pub const fn rank_of(c: Card) -> u8 {
    c / 4
}

pub const fn suit_of(c: Card) -> u8 {
    c % 4
}

/// Parses a card like `"As"` or `"7d"`.
pub fn parse_card(s: &str) -> Option<Card> {
    let b = s.as_bytes();
    if b.len() != 2 {
        return None;
    }
    let r = RANK_CHARS
        .iter()
        .position(|&x| x == b[0].to_ascii_uppercase())?;
    let su = SUIT_CHARS
        .iter()
        .position(|&x| x == b[1].to_ascii_lowercase())?;
    Some(card(r as u8, su as u8))
}

/// Writes a card like `"As"`.
pub fn card_string(c: Card) -> String {
    let mut s = String::with_capacity(2);
    s.push(RANK_CHARS[rank_of(c) as usize] as char);
    s.push(SUIT_CHARS[suit_of(c) as usize] as char);
    s
}

/// Every card of one hand: two hole cards per seat and the five board cards.
///
/// The board is fixed up front; the state shows only the cards of the streets reached.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Deal {
    pub hole: [[Card; 2]; MAX_PLAYERS],
    pub board: [Card; 5],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DealError {
    /// A card is not in `0..52`.
    BadCard(Card),
    /// The same card appears twice.
    Duplicate(Card),
    /// Hole cards were given for a number of seats other than the table's.
    WrongSeatCount,
}

impl fmt::Display for DealError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DealError::BadCard(c) => write!(f, "card {c} is not in 0..52"),
            DealError::Duplicate(c) => write!(f, "card {} is dealt twice", card_string(*c)),
            DealError::WrongSeatCount => {
                write!(f, "hole cards given for the wrong number of seats")
            }
        }
    }
}

impl std::error::Error for DealError {}

impl Deal {
    /// A deal with the given hole cards (one pair per seat, seat 0 first) and board.
    /// Seats past `hole.len()` get no cards.
    pub fn new(hole: &[[Card; 2]], board: [Card; 5]) -> Result<Deal, DealError> {
        if hole.len() < 2 || hole.len() > MAX_PLAYERS {
            return Err(DealError::WrongSeatCount);
        }
        let mut seen = 0u64;
        for &c in hole.iter().flatten().chain(board.iter()) {
            if c >= 52 {
                return Err(DealError::BadCard(c));
            }
            if seen & (1 << c) != 0 {
                return Err(DealError::Duplicate(c));
            }
            seen |= 1 << c;
        }
        let mut h = [[NO_CARD; 2]; MAX_PLAYERS];
        h[..hole.len()].copy_from_slice(hole);
        Ok(Deal { hole: h, board })
    }

    /// A deterministic deal from a seed: the same seed always gives the same cards.
    ///
    /// The 52 cards are shuffled with [`Rng`] (Fisher-Yates). Hole cards go one at a time
    /// round the table starting with the seat after the button, twice, then the next five
    /// cards are the board.
    pub fn from_seed(seed: u64, num_players: usize, button: usize) -> Deal {
        assert!((2..=MAX_PLAYERS).contains(&num_players) && button < num_players);
        let mut rng = Rng::new(seed);
        let mut deck: [Card; 52] = std::array::from_fn(|i| i as Card);
        rng.shuffle(&mut deck);
        let mut hole = [[NO_CARD; 2]; MAX_PLAYERS];
        let mut k = 0;
        for round in 0..2 {
            for j in 1..=num_players {
                hole[(button + j) % num_players][round] = deck[k];
                k += 1;
            }
        }
        let board = [deck[k], deck[k + 1], deck[k + 2], deck[k + 3], deck[k + 4]];
        Deal { hole, board }
    }
}

/// Placeholder for the hole cards of seats that are not at the table.
pub const NO_CARD: Card = 255;

/// A small, fast, seedable generator (SplitMix64). Deterministic on every platform.
#[derive(Clone, Copy, Debug)]
pub struct Rng {
    state: u64,
}

impl Rng {
    pub fn new(seed: u64) -> Rng {
        Rng { state: seed }
    }

    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// A uniform integer in `0..n` (rejection sampling, so no bias).
    pub fn below(&mut self, n: u64) -> u64 {
        assert!(n > 0);
        let zone = u64::MAX - u64::MAX % n;
        loop {
            let x = self.next_u64();
            if x < zone {
                return x % n;
            }
        }
    }

    pub fn shuffle<T>(&mut self, items: &mut [T]) {
        for i in (1..items.len()).rev() {
            let j = self.below(i as u64 + 1) as usize;
            items.swap(i, j);
        }
    }
}
