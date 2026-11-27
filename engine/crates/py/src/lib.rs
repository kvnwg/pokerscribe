//! Python bindings for the PokerScribe engine. The Python module is `pokerscribe_engine`.
//!
//! Everything is behind the Cargo feature `python`, which maturin turns on
//! (`pyproject.toml`). Without it this crate is empty, so `cargo build` and `cargo test`
//! in the workspace need neither PyO3 nor Python. See README.md for the build and the API.
#![cfg(feature = "python")]

mod agents;
mod arena;
mod cards;
mod game;
mod hand_eval;

/// The PokerScribe Rust engine: the hand evaluator and the No-Limit Hold'em rules engine.
///
///     import pokerscribe_engine as pe
///
///     pe.eval7(["Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d"])   # 7462, the best hand
///
///     hand = pe.new_hand([200, 200], 1, 2, seed=7)           # heads-up, 1/2 blinds
///     while not hand.is_terminal:
///         legal = hand.legal_actions()
///         hand.apply("check" if legal.check else "call")
///     hand.payouts()                                         # chips won or lost per seat
///
/// A card is a string like "Ah" (rank 23456789TJQKA, suit cdhs) or an int, rank * 4 + suit
/// with rank 0 = two ... 12 = ace and suit 0..3 = c, d, h, s. Chips are whole numbers.
#[pyo3::pymodule]
mod pokerscribe_engine {
    #[pymodule_export]
    use crate::arena::{agents, run_match, MatchReport, View};
    #[pymodule_export]
    use crate::cards::{card_index, card_string};
    #[pymodule_export]
    use crate::game::{new_hand, LegalActions, State};
    #[pymodule_export]
    use crate::hand_eval::{eval5, eval6, eval7, hand_category};

    /// The largest table the rules engine plays.
    #[pymodule_export]
    const MAX_PLAYERS: usize = nlhe::MAX_PLAYERS;

    /// The best possible hand rank (a royal flush). The worst is 1.
    #[pymodule_export]
    const MAX_RANK: u16 = eval::DISTINCT_RANKS;

    #[pymodule_export]
    #[allow(non_upper_case_globals)]
    const __version__: &str = env!("CARGO_PKG_VERSION");
}
