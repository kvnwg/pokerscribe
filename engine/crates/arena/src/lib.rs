//! The match arena: plays poker agents against each other and says who won, by how much
//! and how sure that is.
//!
//! ```
//! use arena::{bots, run_match, MatchConfig};
//!
//! // Heads-up, 2,000 deals, each played twice with the seats swapped.
//! let agents = [bots::builtin("call").unwrap(), bots::builtin("tag").unwrap()];
//! let report = run_match(&MatchConfig::heads_up(2_000, 7), &agents).unwrap();
//! let tag = report.result("tag").unwrap();
//! println!("tag: {:+.1} bb/100, standard error {:.1}", tag.bb_per_100, tag.se.unwrap());
//! assert!(tag.bb_per_100 > 0.0);
//! ```
//!
//! - [`Player`] is what an agent implements: it is shown a [`View`] (its own cards and
//!   everything public) and returns an action.
//! - [`run_match`] plays the deals of a [`MatchConfig`] on every core and returns a
//!   [`MatchReport`]: bb/100 with its standard error, per agent and per seat.
//! - Duplicate play (every deal replayed with the agents rotated through the seats) and
//!   the all-in equity adjustment ([`AllInEquity`]) take most of the luck out. [`Aivat`]
//!   takes out more, next to the main figure when [`MatchConfig::aivat`] is set: the luck
//!   of every card, and of the random choices of the agents whose chances are known
//!   ([`Player::probabilities`]). A custom [`Scorer`] can replace the main figure.
//! - [`bots`] has the simple test agents.
//!
//! See README.md for the rules of a match, the JSON format and the measured results.

// Loops over seat numbers read better than iterator chains over several arrays at once.
#![allow(clippy::needless_range_loop)]

pub mod aivat;
pub mod bots;
pub mod equity;
pub mod hand;
pub mod luck;
pub mod player;
pub mod ranker;
pub mod report;
pub mod runner;

pub use aivat::{Aivat, AivatHand, Facing, Stakes, DEFAULT_AIVAT_BOARDS};
pub use equity::{all_in_equity, all_in_runout, Pots};
pub use hand::{play_hand, play_hand_recorded, Decisions, PlayedHand};
pub use luck::{ActualChips, AllInEquity, HandRecord, Scorer};
pub use player::{Agent, Player, View};
pub use ranker::EvalRanker;
pub use report::{position_name, AgentResult, AivatResult, MatchReport, SeatResult, Timing};
pub use runner::{run_match, run_match_scored, ArenaError, MatchConfig, DEFAULT_MAX_RUNOUTS};

/// Mixes two numbers into one seed. Every seed of a match (the cards of a deal, each
/// seat's private random numbers) comes from the match seed through this, so a match
/// replays exactly whatever the number of threads.
pub fn mix(a: u64, b: u64) -> u64 {
    let first = nlhe::Rng::new(a).next_u64();
    nlhe::Rng::new(first ^ b).next_u64()
}
