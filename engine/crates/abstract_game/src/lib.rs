//! Action abstraction for the solver-based agent, and a shrunk heads-up No-Limit Hold'em
//! game the CFR library can train on (Phase 5 of the roadmap).
//!
//! - [`Menus`]: the bet sizes on offer in every spot, as settings.
//! - [`mapping`]: the pseudo-harmonic mapping for bets that are not on the menu.
//! - [`Bucketer`]: hole cards and board to a bucket per street, with two simple ones,
//!   [`Lossless`] and [`EquityBands`].
//! - [`AbstractGame`]: the game itself, a [`cfr::Game`]. Its betting tree and payoffs come
//!   from `nlhe`; showdowns are ranked by `eval` through [`EvalRanker`].
//! - [`TreeSize`]: decision points, information sets and memory for regrets.
//!
//! ```
//! use abstract_game::{AbstractGame, GameConfig, Lossless};
//! use cfr::{Mccfr, MccfrConfig, Sampling, Solver};
//!
//! // Push-or-fold with 10 big blinds: two decision points, 169 hands each.
//! let game = AbstractGame::new(GameConfig::push_fold(10), Lossless).unwrap();
//! assert_eq!(game.info_sets(), 338);
//! let mut solver = Mccfr::new(game, MccfrConfig::new(Sampling::External, 1));
//! solver.run(1_000);
//! ```
//!
//! See README.md for the settings, the size table and the tests.

#![forbid(unsafe_code)]

pub mod bucket;
pub mod game;
pub mod mapping;
pub mod menu;
pub mod ranker;
pub mod size;
pub mod tree;

pub use bucket::{
    class_combos, class_from_name, class_name, hand_strength, preflop_class, Bucketer, EquityBands,
    Lossless, LOSSLESS_BUCKETS, PREFLOP_CLASSES,
};
pub use game::{
    encode, raise_amount, raise_to, AbstractGame, BuildError, GameConfig, HandState, Translation,
    CALL, CHIPS_PER_BIG_BLIND, DEFAULT_MAX_DECISIONS, FOLD,
};
pub use mapping::{map_size, pseudo_harmonic, Mapping};
pub use menu::{pot_fraction, raises_this_street, MenuError, Menus, Size};
pub use ranker::EvalRanker;
pub use size::TreeSize;
pub use tree::{BettingTree, Edge, Next, Node, Payoff, Showdown};

pub use nlhe::{Card, Chips, Street};
