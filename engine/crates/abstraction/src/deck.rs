//! The deck. The real game uses all 13 ranks. Tests and the small tables in
//! `tests/fixtures` use a deck of the top few ranks, so the whole build runs in seconds.

/// The top `ranks` ranks of the standard deck in all four suits. Cards keep their usual
/// numbers (`rank * 4 + suit`, rank 0 = 2 up to 12 = ace), so a 6-rank deck holds the
/// cards 28 to 51: the nines to the aces.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Deck {
    ranks: u8,
}

impl Deck {
    /// The 52-card deck.
    pub const FULL: Deck = Deck { ranks: 13 };

    /// A deck of the top `ranks` ranks, from 2 to 13.
    pub fn new(ranks: u8) -> Deck {
        assert!((2..=13).contains(&ranks), "a deck has 2 to 13 ranks");
        Deck { ranks }
    }

    /// Ranks in the deck.
    pub const fn ranks(self) -> u8 {
        self.ranks
    }

    /// The lowest rank in the deck (0 = deuce).
    pub const fn low_rank(self) -> u8 {
        13 - self.ranks
    }

    /// The lowest card number in the deck.
    pub const fn first_card(self) -> u8 {
        self.low_rank() * 4
    }

    /// Cards in the deck.
    pub const fn len(self) -> usize {
        self.ranks as usize * 4
    }

    /// Never true: a deck has at least 8 cards.
    pub const fn is_empty(self) -> bool {
        false
    }

    /// True when the card is in the deck.
    pub const fn contains(self, card: u8) -> bool {
        card >= self.first_card() && card < 52
    }

    /// Every card, lowest number first.
    pub fn cards(self) -> impl Iterator<Item = u8> + Clone {
        self.first_card()..52
    }
}

/// Parses cards like "AhKs" or "Ah Ks" into card numbers.
pub fn parse_cards(text: &str) -> Result<Vec<u8>, String> {
    eval::parse_cards(text)
        .map(|cards| cards.iter().map(|c| c.index()).collect())
        .map_err(|e| format!("{e:?}"))
}

/// Card numbers as text, like "AhKs".
pub fn format_cards(cards: &[u8]) -> String {
    let cards: Vec<eval::Card> = cards
        .iter()
        .map(|&c| eval::Card::from_index(c).expect("card number under 52"))
        .collect();
    eval::format_cards(&cards)
}
