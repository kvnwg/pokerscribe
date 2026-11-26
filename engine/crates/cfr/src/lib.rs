//! Counterfactual regret minimization core for PokerScribe.
//!
//! - [`Game`]: the n-player game interface (chance with explicit
//!   probabilities, information set keys, legal actions, utilities).
//! - [`Cfr`]: full-width vanilla CFR, CFR+, Linear CFR and Discounted CFR.
//! - [`Mccfr`]: Monte Carlo CFR with external or outcome sampling, linear
//!   weighting and Pluribus-style negative-regret pruning.
//! - [`eval`]: exact expected values, best responses, NashConv and
//!   exploitability for games small enough to walk.
//!
//! Regrets and strategy sums live in flat `f64` arrays indexed through an
//! [`InfoTable`]; tree walks reuse per-depth buffers, so a warmed-up
//! iteration allocates nothing. Sampling uses this crate's own seeded
//! [`Rng`], so a seed always reproduces the same run.

pub mod cfr;
pub mod eval;
pub mod game;
pub mod mccfr;
pub mod policy;
pub mod rng;
mod scratch;
pub mod table;

pub use crate::cfr::{Cfr, Variant};
pub use crate::eval::{best_response_value, expected_values, exploitability, nash_conv};
pub use crate::game::{child, Action, Game, InfoKey, Node};
pub use crate::mccfr::{LinearWeighting, Mccfr, MccfrConfig, MccfrStats, Pruning, Sampling};
pub use crate::policy::{Policy, TabularPolicy, UniformPolicy};
pub use crate::rng::Rng;
pub use crate::table::{InfoSet, InfoTable};

/// What every solver offers.
pub trait Solver {
    /// Runs one iteration: one update per player.
    fn iterate(&mut self);

    /// Iterations run so far.
    fn iterations(&self) -> u64;

    /// The normalised average strategy, the one that converges to
    /// equilibrium in two-player zero-sum games.
    fn average_policy(&self) -> TabularPolicy;

    /// Information sets indexed so far.
    fn info_sets(&self) -> usize;

    /// Game nodes visited so far, over all iterations.
    fn nodes_touched(&self) -> u64;

    /// Runs `n` more iterations.
    fn run(&mut self, n: u64) {
        for _ in 0..n {
            self.iterate();
        }
    }
}
