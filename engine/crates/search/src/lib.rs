//! Depth-limited search for heads-up No-Limit Hold'em on top of a blueprint (Phase 7
//! groundwork, Modicum: Brown, Sandholm and Amos 2018). See the README.
//!
//! - [`agent`]: the search agent ([`SearchAgent`], an `lbr::Strategy`): Bayesian ranges
//!   from the betting, a solve of each street from its start, re-solving after an
//!   off-tree action.
//! - [`street`]: one street's betting over real states (the blueprint's menu plus the real
//!   off-menu actions), and its conversion to a `subgame::Tree`.
//! - [`solve`]: the solve of one street: the flop depth-limited, the turn and the river
//!   with the subgame crate.
//! - [`flop`]: the depth-limited flop solver (Discounted CFR, Modicum's leaves).
//! - [`leaf`]: the leaf tables (what the rest of the hand is worth by flop buckets, for
//!   the blueprint and its biased versions).
//! - [`leaf_job`]: the leaf tables built in parts, a job that can stop and go on (the
//!   `tools/cloud` trainer contract, and `search leaf`).
//! - [`equity`]: exact flop all-in equity for every pair of combos.
//! - [`play`]: a `Strategy` seated in the arena.
//! - [`runs`]: a match, LBR and the decision-time bench, as the `search` commands and the
//!   plan job run them.
//! - [`plan_job`]: Phase 7's runs as one job on a rented machine (the `tools/cloud` trainer
//!   contract): the leaf tables, the bench and its bounds, the pilot, the gate match, the
//!   reported variants, LBR, and the repeat after a pass.

pub mod agent;
pub mod cards;
pub mod equity;
pub mod flop;
pub mod leaf;
pub mod leaf_job;
pub mod plan_job;
pub mod play;
pub mod real;
pub mod runs;
pub mod solve;
pub mod street;

pub use agent::{leaf_path, Plan, SearchAgent, SolveRecord};
pub use solve::{Settings, StreetSolve};
