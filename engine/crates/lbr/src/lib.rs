//! Local best response (LBR) for heads-up No-Limit Hold'em.
//!
//! LBR (Lisy and Bowling 2017, "Equilibrium Approximation Quality of Current No-Limit Poker
//! Bots") plays against a strategy it can read. It tracks the opponent's range with Bayes'
//! rule and, at each of its decisions, picks fold, call or a bet by estimating each one's
//! value one action ahead: the opponent folds as their strategy says, and otherwise the hand
//! is checked down. What LBR wins is a lower bound on how exploitable the strategy is, so a
//! lower LBR win rate means a stronger strategy.
//!
//! ```
//! use lbr::{play_match, AlwaysFold, LbrConfig, MatchConfig};
//!
//! // 200 hands, 100 deals played from both seats, ACPC table (50/100 blinds, 200 BB deep).
//! let result = play_match(&AlwaysFold, &LbrConfig::default(), &MatchConfig::acpc(200, 1));
//! // A player who always folds loses 0.75 big blinds a hand.
//! assert_eq!(result.bb_per_100, 75.0);
//! ```
//!
//! See README.md for the settings, the results against the paper and the speed.

pub mod chumps;
pub mod config;
pub mod equity;
pub mod player;
pub mod public;
pub mod range;
pub mod ranker;
pub mod runner;
pub mod strategy;

pub use chumps::{AlwaysCall, AlwaysFold, AlwaysRaise, CallOrRaise, RaiseSize, UniformRandom};
pub use config::{bets_56, bets_fcpa, BetSize, LbrConfig, PreflopEquity, StreetPolicy};
pub use equity::{
    preflop_equities, preflop_equities_sampled, showdown_equities, warm_preflop_table,
    win_probability, EquityTable,
};
pub use player::{Evaluation, Lbr};
pub use public::PublicState;
pub use range::{card_mask, combo_cards, combo_index, Range, NUM_COMBOS};
pub use ranker::EvalRanker;
pub use runner::{play_hand, play_match, MatchConfig, MatchResult};
pub use strategy::{ActionProbs, Strategy};
