//! The abstraction crate's bucket tables as the abstract game's card abstraction.
//!
//! This is the adapter from the abstraction crate's README ("With the abstract game"),
//! plus what a blueprint needs to know about the tables it was trained with: where they
//! came from and their checksums, so a strategy file is never played with other tables.

use std::io;
use std::path::{Path, PathBuf};

use abstract_game::{Bucketer, Card, Street};
use abstraction::{table::Feature, Abstraction};
use serde::{Deserialize, Serialize};

/// What identifies a set of bucket tables.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TablesInfo {
    /// Buckets on each street: 169 preflop, then the flop, turn and river tables'.
    pub buckets: [u64; 4],
    /// The checksums of `flop.abs`, `turn.abs` and `river.abs`, as their headers give them.
    pub checksums: [String; 3],
    /// What describes a river hand: "ochs" or "equity".
    pub river_feature: String,
}

/// The built tables as the abstract game's card abstraction.
pub struct Buckets {
    abstraction: Abstraction,
    dir: PathBuf,
    info: TablesInfo,
}

fn street_of(street: Street) -> abstraction::Street {
    match street {
        Street::Preflop => abstraction::Street::Preflop,
        Street::Flop => abstraction::Street::Flop,
        Street::Turn => abstraction::Street::Turn,
        Street::River => abstraction::Street::River,
    }
}

impl Buckets {
    /// Reads `flop.abs`, `turn.abs` and `river.abs` from `dir`, checking their checksums.
    /// The tables must be for the full 52-card deck.
    pub fn load(dir: &Path) -> io::Result<Buckets> {
        Buckets::from_abstraction(Abstraction::load(dir)?, dir)
    }

    /// As [`Buckets::load`] without checking the checksums (faster, for a second load of
    /// tables already checked).
    pub fn load_unchecked(dir: &Path) -> io::Result<Buckets> {
        Buckets::from_abstraction(Abstraction::load_unchecked(dir)?, dir)
    }

    /// Wraps tables already loaded. Refuses tables for a smaller deck: the abstract game
    /// deals all 52 cards.
    pub fn from_abstraction(abstraction: Abstraction, dir: &Path) -> io::Result<Buckets> {
        if abstraction.deck().ranks() != 13 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "the tables in {} are for a deck of {} ranks, not the full deck",
                    dir.display(),
                    abstraction.deck().ranks()
                ),
            ));
        }
        let info = tables_info(&abstraction);
        Ok(Buckets {
            abstraction,
            dir: dir.to_path_buf(),
            info,
        })
    }

    pub fn abstraction(&self) -> &Abstraction {
        &self.abstraction
    }

    /// Where the tables were read from.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    pub fn info(&self) -> &TablesInfo {
        &self.info
    }
}

/// The buckets, checksums and river feature of a set of tables.
pub fn tables_info(abstraction: &Abstraction) -> TablesInfo {
    let table = |s| abstraction.table(s).expect("a postflop street has a table");
    let flop = table(abstraction::Street::Flop);
    let turn = table(abstraction::Street::Turn);
    let river = table(abstraction::Street::River);
    let river_feature = match river.header().settings.feature {
        Feature::Equity => "equity".to_string(),
        Feature::Ochs { clusters } => format!("ochs{clusters}"),
        ref other => format!("{other:?}"),
    };
    TablesInfo {
        buckets: Street::ALL.map(|s| abstraction.buckets(street_of(s)) as u64),
        checksums: [flop.checksum(), turn.checksum(), river.checksum()],
        river_feature,
    }
}

impl Bucketer for Buckets {
    fn num_buckets(&self, street: Street) -> u64 {
        self.abstraction.buckets(street_of(street)) as u64
    }

    #[inline]
    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
        self.abstraction.bucket(&hole, board) as u64
    }
}
