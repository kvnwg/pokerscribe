//! Hand abstraction for heads-up No-Limit Hold'em (Phase 5 of the roadmap).
//!
//! Every hand (hole cards plus board) is put in a *bucket*, and the blueprint solver keeps
//! one strategy per bucket. Hands that differ only by a relabelling of the suits are the
//! same hand ([`HandIndexer`]). Preflop keeps all 169 classes. On the flop and turn, hands
//! are grouped by where they land on the next street (potential-aware, with earth mover's
//! distance); on the river, by equity against the opponent's hands. See the crate's
//! `README.md` for the method, the file format and the build times.
//!
//! ```
//! use abstraction::{builder, parse_cards, Abstraction, Deck, Street};
//!
//! // A small deck (nines to aces) builds in well under a second; the real tables are
//! // built with the `abstraction-build` tool and read with `Abstraction::load`.
//! let mut settings = builder::Settings::new(12);
//! settings.ranks = 6;
//! let ([flop, turn, river], _reports) = builder::build_all(&settings);
//! let abstraction = Abstraction::from_tables(flop, turn, river).unwrap();
//!
//! let hole = parse_cards("AhKh").unwrap();
//! let board = parse_cards("QhJhTh9c9d").unwrap();
//! let royal = abstraction.bucket(&hole, &board);
//! let other_suit = abstraction.bucket(&parse_cards("AsKs").unwrap(), &parse_cards("QsJsTs9c9d").unwrap());
//! assert_eq!(royal, other_suit);
//! assert_eq!(abstraction.buckets(Street::Preflop), 36);
//! assert!(Deck::new(6).contains(hole[0]));
//! ```

pub mod builder;
pub mod checks;
pub mod deck;
pub mod emd;
pub mod equity;
pub mod isomorphism;
pub mod kmeans;
pub mod rng;
pub mod table;
pub mod xxh64;

pub use deck::{format_cards, parse_cards, Deck};
pub use isomorphism::{HandIndexer, Preflop};
pub use table::{Street, Table};

use std::io;
use std::path::Path;

/// The bucket of every hand on every street: the 169 preflop classes and the flop, turn
/// and river tables.
pub struct Abstraction {
    deck: Deck,
    preflop: Preflop,
    /// Flop, turn, river.
    streets: [(HandIndexer, Table); 3],
}

impl Abstraction {
    /// Puts three tables together, checking that they are for the same deck and the right
    /// streets.
    pub fn from_tables(flop: Table, turn: Table, river: Table) -> Result<Abstraction, String> {
        let deck = Deck::new(river.header.ranks);
        let mut streets = Vec::with_capacity(3);
        for (street, table) in [(Street::Flop, flop), (Street::Turn, turn), (Street::River, river)] {
            if table.header.street != street {
                return Err(format!("expected a {} table, got a {} table", street.name(), table.header.street.name()));
            }
            if table.header.ranks != deck.ranks() {
                return Err(format!("the {} table is for a deck of {} ranks", street.name(), table.header.ranks));
            }
            let indexer = HandIndexer::with_deck(deck, &[2, street.board_cards() as u8]);
            if indexer.size() != table.len() {
                return Err(format!(
                    "the {} table has {} hands, expected {}",
                    street.name(),
                    table.len(),
                    indexer.size()
                ));
            }
            streets.push((indexer, table));
        }
        let streets: [(HandIndexer, Table); 3] = streets.try_into().ok().expect("three streets");
        Ok(Abstraction {
            deck,
            preflop: Preflop::with_deck(deck),
            streets,
        })
    }

    /// Reads `flop.abs`, `turn.abs` and `river.abs` from a directory and checks their
    /// checksums.
    pub fn load(dir: &Path) -> io::Result<Abstraction> {
        Abstraction::read(dir, true)
    }

    /// [`Abstraction::load`] without checking the checksums.
    pub fn load_unchecked(dir: &Path) -> io::Result<Abstraction> {
        Abstraction::read(dir, false)
    }

    fn read(dir: &Path, verify: bool) -> io::Result<Abstraction> {
        let read = |street: Street| {
            let path = dir.join(street.file_name());
            if verify {
                Table::load(&path)
            } else {
                Table::load_unchecked(&path)
            }
        };
        // The three files are read at the same time.
        let (flop, (turn, river)) = rayon::join(|| read(Street::Flop), || rayon::join(|| read(Street::Turn), || read(Street::River)));
        Abstraction::from_tables(flop?, turn?, river?).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }

    /// The deck the tables are for.
    pub fn deck(&self) -> Deck {
        self.deck
    }

    /// The preflop classes.
    pub fn preflop(&self) -> &Preflop {
        &self.preflop
    }

    /// A street's table. `None` for the preflop.
    pub fn table(&self, street: Street) -> Option<&Table> {
        match street {
            Street::Preflop => None,
            Street::Flop => Some(&self.streets[0].1),
            Street::Turn => Some(&self.streets[1].1),
            Street::River => Some(&self.streets[2].1),
        }
    }

    /// Number of buckets on a street: 169 preflop.
    pub fn buckets(&self, street: Street) -> usize {
        match self.table(street) {
            None => self.preflop.classes(),
            Some(table) => table.buckets(),
        }
    }

    /// The index of a hand among its street's canonical hands. `board` has 0, 3, 4 or 5
    /// cards.
    #[inline]
    pub fn index(&self, hole: &[u8], board: &[u8]) -> u64 {
        assert_eq!(hole.len(), 2, "two hole cards");
        match board.len() {
            0 => self.preflop.class(hole[0], hole[1]) as u64,
            n @ 3..=5 => {
                let mut cards = [0u8; 7];
                cards[..2].copy_from_slice(hole);
                cards[2..2 + n].copy_from_slice(board);
                self.streets[n - 3].0.index(&cards[..2 + n])
            }
            n => panic!("a board has 0, 3, 4 or 5 cards, not {n}"),
        }
    }

    /// The bucket of a hand. `board` has 0, 3, 4 or 5 cards; with none, the bucket is the
    /// preflop class.
    #[inline]
    pub fn bucket(&self, hole: &[u8], board: &[u8]) -> u16 {
        let index = self.index(hole, board);
        match board.len() {
            0 => index as u16,
            n => self.streets[n - 3].1.bucket(index),
        }
    }
}
