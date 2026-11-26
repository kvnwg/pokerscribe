//! Fast 5-, 6- and 7-card hold'em hand evaluator.
//!
//! ```
//! use eval::{eval7, parse_cards, Category};
//!
//! let a: [_; 7] = parse_cards("AhKh QhJh2c 7d Th").unwrap().try_into().unwrap();
//! let b: [_; 7] = parse_cards("AsAd QhJh2c 7d Th").unwrap().try_into().unwrap();
//! assert_eq!(eval7(&a).category(), Category::StraightFlush);
//! assert!(eval7(&a) > eval7(&b));
//! ```
//!
//! Every hand maps to one of the 7,462 five-card classes, numbered 1 (7-5-4-3-2 offsuit)
//! to 7,462 (royal flush). Higher is better and equal numbers tie. See `build.rs` for how
//! the tables are made. Cards must be distinct; duplicates give an unspecified result.

mod card;

pub use card::{Card, ParseCardError, RANK_CHARS, SUIT_CHARS, format_cards, parse_cards};

use std::fmt;

mod tables {
    include!(concat!(env!("OUT_DIR"), "/tables.rs"));
}
use tables::*;

/// Number of distinct 5-card hand strengths.
pub const DISTINCT_RANKS: u16 = 7462;

/// Hand category, weakest first.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Category {
    HighCard = 0,
    Pair = 1,
    TwoPair = 2,
    ThreeOfAKind = 3,
    Straight = 4,
    Flush = 5,
    FullHouse = 6,
    FourOfAKind = 7,
    StraightFlush = 8,
}

impl Category {
    /// All categories, weakest first.
    pub const ALL: [Category; 9] = [
        Category::HighCard,
        Category::Pair,
        Category::TwoPair,
        Category::ThreeOfAKind,
        Category::Straight,
        Category::Flush,
        Category::FullHouse,
        Category::FourOfAKind,
        Category::StraightFlush,
    ];

    /// English name, like "two pair".
    pub const fn name(self) -> &'static str {
        match self {
            Category::HighCard => "high card",
            Category::Pair => "pair",
            Category::TwoPair => "two pair",
            Category::ThreeOfAKind => "three of a kind",
            Category::Straight => "straight",
            Category::Flush => "flush",
            Category::FullHouse => "full house",
            Category::FourOfAKind => "four of a kind",
            Category::StraightFlush => "straight flush",
        }
    }

    /// Lowest and highest [`HandRank::value`] in this category.
    pub fn value_range(self) -> (u16, u16) {
        let i = self as usize;
        (CATEGORY_START[i], CATEGORY_START[i + 1] - 1)
    }
}

impl fmt::Display for Category {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.name())
    }
}

/// Strength of a hand. Compare with `<`, `==`, `>`: higher is better, equal ties.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct HandRank(u16);

impl HandRank {
    /// The comparable integer, 1 (weakest, 7-5-4-3-2 offsuit) to 7,462 (royal flush).
    pub const fn value(self) -> u16 {
        self.0
    }

    /// Rank from a value in `1..=7462`.
    pub const fn from_value(value: u16) -> Option<HandRank> {
        if value >= 1 && value <= DISTINCT_RANKS {
            Some(HandRank(value))
        } else {
            None
        }
    }

    /// The hand's category.
    #[inline]
    pub fn category(self) -> Category {
        let v = self.0;
        let mut i = 0;
        for start in &CATEGORY_START[1..9] {
            i += (v >= *start) as usize;
        }
        Category::ALL[i]
    }
}

impl fmt::Display for HandRank {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} ({})", self.category(), self.0)
    }
}

/// Per-card addend: the base-5 rank number `5^rank` in the low 32 bits, plus one in the
/// suit's 4-bit counter at bit `32 + 4 * suit`.
const CARD_KEY: [u64; 52] = {
    let mut t = [0u64; 52];
    let mut i = 0;
    while i < 52 {
        t[i] = 5u64.pow((i / 4) as u32) + (1u64 << (32 + 4 * (i % 4)));
        i += 1;
    }
    t
};

/// Suit counters start at 3, so a suit with 5 or more cards sets its counter's top bit.
const SUIT_BIAS: u64 = 0x3333 << 32;
const FLUSH_FLAGS: u64 = 0x8888;

/// A set of cards built one card at a time. Adding is two operations, so it suits
/// enumeration: share the board's `Hand` and add each player's hole cards to it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Hand {
    /// Base-5 rank number plus suit counters (see [`CARD_KEY`]).
    key: u64,
    /// Bit `16 * suit + rank` for every card.
    bits: u64,
    len: u8,
}

impl Default for Hand {
    fn default() -> Hand {
        Hand::new()
    }
}

impl Hand {
    /// No cards.
    pub const fn new() -> Hand {
        Hand {
            key: SUIT_BIAS,
            bits: 0,
            len: 0,
        }
    }

    /// The hand holding `cards`.
    pub fn from_cards(cards: &[Card]) -> Hand {
        cards.iter().fold(Hand::new(), |h, &c| h.add(c))
    }

    /// This hand plus `card`. The card must not be in the hand already.
    #[inline(always)]
    #[must_use]
    pub const fn add(self, card: Card) -> Hand {
        let i = card.index() as usize;
        let bit = 1u64 << (16 * (i & 3) + (i >> 2));
        debug_assert!(self.bits & bit == 0, "card added twice");
        Hand {
            key: self.key + CARD_KEY[i],
            bits: self.bits | bit,
            len: self.len + 1,
        }
    }

    /// Number of cards.
    pub const fn len(self) -> usize {
        self.len as usize
    }

    /// True when the hand holds no cards.
    pub const fn is_empty(self) -> bool {
        self.len == 0
    }

    /// True when the hand holds `card`.
    pub const fn contains(self, card: Card) -> bool {
        let i = card.index() as usize;
        self.bits & (1u64 << (16 * (i & 3) + (i >> 2))) != 0
    }

    /// Strength of the best 5 cards. Panics unless the hand has 5, 6 or 7 cards.
    #[inline]
    pub fn eval(self) -> HandRank {
        match self.len {
            7 => self.eval7(),
            6 => self.eval6(),
            5 => self.eval5(),
            n => panic!("can only evaluate 5, 6 or 7 cards, not {n}"),
        }
    }

    #[inline(always)]
    fn flush(self) -> Option<HandRank> {
        let flags = (self.key >> 32) & FLUSH_FLAGS;
        if flags == 0 {
            return None;
        }
        // The flag of suit s is bit 4s + 3.
        let suit = flags.trailing_zeros() >> 2;
        Some(HandRank(
            FLUSH[((self.bits >> (16 * suit)) & 0x1fff) as usize],
        ))
    }

    /// [`Hand::eval`] for a hand known to hold 7 cards.
    #[inline(always)]
    pub fn eval7(self) -> HandRank {
        debug_assert_eq!(self.len, 7);
        if let Some(r) = self.flush() {
            return r;
        }
        let x = (self.key as u32 as u64).wrapping_mul(MULT7);
        let d = DISP7[(x >> BUCKET_SHIFT7) as usize] as u32;
        HandRank(RANKS7[(((x >> SLOT_SHIFT7) as u32 ^ d) & SLOT_MASK7) as usize])
    }

    /// [`Hand::eval`] for a hand known to hold 6 cards.
    #[inline(always)]
    pub fn eval6(self) -> HandRank {
        debug_assert_eq!(self.len, 6);
        if let Some(r) = self.flush() {
            return r;
        }
        let x = (self.key as u32 as u64).wrapping_mul(MULT6);
        let d = DISP6[(x >> BUCKET_SHIFT6) as usize] as u32;
        HandRank(RANKS6[(((x >> SLOT_SHIFT6) as u32 ^ d) & SLOT_MASK6) as usize])
    }

    /// [`Hand::eval`] for a hand known to hold 5 cards.
    #[inline(always)]
    pub fn eval5(self) -> HandRank {
        debug_assert_eq!(self.len, 5);
        if let Some(r) = self.flush() {
            return r;
        }
        let x = (self.key as u32 as u64).wrapping_mul(MULT5);
        let d = DISP5[(x >> BUCKET_SHIFT5) as usize] as u32;
        HandRank(RANKS5[(((x >> SLOT_SHIFT5) as u32 ^ d) & SLOT_MASK5) as usize])
    }
}

/// Strength of the best 5 of 7 cards.
#[inline]
pub fn eval7(cards: &[Card; 7]) -> HandRank {
    let [a, b, c, d, e, f, g] = *cards;
    Hand::new()
        .add(a)
        .add(b)
        .add(c)
        .add(d)
        .add(e)
        .add(f)
        .add(g)
        .eval7()
}

/// Strength of the best 5 of 6 cards.
#[inline]
pub fn eval6(cards: &[Card; 6]) -> HandRank {
    let [a, b, c, d, e, f] = *cards;
    Hand::new()
        .add(a)
        .add(b)
        .add(c)
        .add(d)
        .add(e)
        .add(f)
        .eval6()
}

/// Strength of 5 cards.
#[inline]
pub fn eval5(cards: &[Card; 5]) -> HandRank {
    let [a, b, c, d, e] = *cards;
    Hand::new().add(a).add(b).add(c).add(d).add(e).eval5()
}

/// Strength of the best 5 of 5, 6 or 7 cards. Panics for any other count.
pub fn eval(cards: &[Card]) -> HandRank {
    assert!(
        (5..=7).contains(&cards.len()),
        "can only evaluate 5, 6 or 7 cards, not {}",
        cards.len()
    );
    Hand::from_cards(cards).eval()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn r(s: &str) -> HandRank {
        eval(&parse_cards(s).unwrap())
    }

    #[test]
    fn card_round_trip() {
        for c in Card::all() {
            assert_eq!(c.to_string().parse::<Card>().unwrap(), c);
        }
        let ah: Card = "Ah".parse().unwrap();
        assert_eq!((ah.rank(), ah.suit(), ah.index()), (12, 2, 50));
        assert_eq!("2c".parse::<Card>().unwrap().index(), 0);
        assert_eq!("as".parse::<Card>().unwrap().to_string(), "As");
        assert!("1h".parse::<Card>().is_err());
        assert!("Ax".parse::<Card>().is_err());
        assert!("Ahh".parse::<Card>().is_err());
        assert_eq!(format_cards(&parse_cards("Ah, Ks Qd").unwrap()), "AhKsQd");
    }

    #[test]
    fn known_hands() {
        assert_eq!(r("7c5d4h3s2c").value(), 1);
        assert_eq!(r("AhKhQhJhTh").value(), DISTINCT_RANKS);
        assert_eq!(r("5d4d3d2dAd").category(), Category::StraightFlush);
        assert_eq!(r("5d4c3d2dAd").category(), Category::Straight);
        assert!(r("5d4c3d2dAd") < r("6d5c4d3d2d"));
        assert_eq!(r("AhAdAcAs2h 3c 9d").category(), Category::FourOfAKind);
        assert_eq!(r("KhKdKc QsQh Qc 2d").category(), Category::FullHouse);
        assert_eq!(r("KhKdKc QsQh Qc 2d"), r("KsKdKc QsQh 3c 2d"));
        assert_eq!(r("2h3h4h6h7h Ah Kd").category(), Category::Flush);
        assert_eq!(r("2h3h4h5h7h Ah Kd").category(), Category::StraightFlush);
        assert_eq!(r("2h3h4h5h6h 7h Kd").value(), r("3h4h5h6h7h").value());
        assert_eq!(r("AhKd QcJs 9h 8h 7h").category(), Category::HighCard);
        assert!(r("AhAd KcKs 2h 3h 4d") > r("AhAd QcQs Jh Th 9d"));
        assert_eq!(r("AhAd KcKs QhQc 4d"), r("AhAd KcKs Qh 2c 4d"));
        assert_eq!(r("9h9d9c 8s8h 7c7d").category(), Category::FullHouse);
    }

    #[test]
    fn category_ranges() {
        let sizes: Vec<u16> = Category::ALL
            .iter()
            .map(|c| c.value_range())
            .map(|(lo, hi)| hi - lo + 1)
            .collect();
        assert_eq!(sizes, [1277, 2860, 858, 858, 10, 1277, 156, 156, 10]);
        for c in Category::ALL {
            let (lo, hi) = c.value_range();
            assert_eq!(HandRank(lo).category(), c);
            assert_eq!(HandRank(hi).category(), c);
        }
    }
}
