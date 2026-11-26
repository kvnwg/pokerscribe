//! An exact No-Limit Hold'em rules engine for 2 to 6 players.
//!
//! ```
//! use nlhe::{Action, BruteForceRanker, Config, State};
//!
//! // Heads-up, 1/2 blinds, button on seat 0 (the button posts the small blind).
//! let config = Config::new(&[200, 200], 1, 2, 0, 0).unwrap();
//! let mut state = State::from_seed(&config, 7);
//! assert_eq!(state.current_player(), Some(0)); // the button acts first preflop
//! state.apply(Action::RaiseTo(6)).unwrap();
//! state.apply(Action::Fold).unwrap();
//! assert!(state.is_terminal());
//! assert_eq!(state.payouts(&BruteForceRanker).unwrap()[..2], [2, -2]);
//! ```
//!
//! See README.md for the rules, the API and how the tests check them against PokerKit.

// Loops over seat numbers read better than iterator chains over several arrays at once.
#![allow(clippy::needless_range_loop)]

pub mod cards;
pub mod history;
pub mod ranker;
pub mod state;

pub use cards::{card, card_string, parse_card, Card, Deal, DealError, Rng};
pub use history::Move;
pub use ranker::{BruteForceRanker, HandRanker};
pub use state::{
    Action, ActionError, Config, ConfigError, LegalActions, Pot, Pots, RaiseRange, State, Street,
};

/// Chips are whole numbers.
pub type Chips = u32;

/// The largest table the engine plays.
pub const MAX_PLAYERS: usize = 6;
