//! River and turn subgame solver for PokerScribe (Phase 4 of `docs/research/README.md`).
//!
//! The Rust successor of the Python river solver in `app/solver`, with the same
//! conventions (`docs/research/SOLVER.md`): player 0 is out of position, node keys are the
//! actions so far, payoffs count the starting pot as nobody's yet, and exploitability is
//! `(best response as OOP + best response as IP - pot) / 2`.
//!
//! Its input is a SPOT and its output is a RESULT, both as `data/SPOT_FORMAT.md` defines
//! them.
//!
//! ```no_run
//! use subgame::{solve, Game, SolveConfig, Spot};
//!
//! let spot = Spot::load("data/answer_keys/spots/r05.json".as_ref())?;
//! let game = Game::new(spot)?;
//! let solution = solve(&game, &SolveConfig::default());
//! println!(
//!     "{} iterations, {:.3}% of the pot, OOP wins {:.2}",
//!     solution.iterations,
//!     100.0 * solution.exploitability,
//!     solution.values[0]
//! );
//! # Ok::<(), subgame::SpotError>(())
//! ```
//!
//! | Module | What |
//! | --- | --- |
//! | [`spot`] | Reading and checking a SPOT. |
//! | [`tree`] | The betting tree: the format's size rules, and the river card on turn spots. |
//! | [`game`] | Ranges as combo weight vectors, exact card removal, sorted showdowns. |
//! | [`cfr`] | Discounted CFR over all combos, and `solve`. |
//! | [`exploit`] | Exact best response, strategy values and exploitability. |
//! | [`result`] | Writing a RESULT, and reading one (plain or gzipped) as a strategy. |
//! | [`expected`] | The "expected" checks of a spot. |

pub mod cards;
pub mod cfr;
pub mod expected;
pub mod exploit;
pub mod game;
pub mod gz;
pub mod pyfmt;
pub mod result;
pub mod sha256;
pub mod spot;
pub mod tree;

pub use cards::Combo;
pub use cfr::{solve, solve_as, Play, Solution, SolveConfig, Solver};
pub use exploit::{exploitability, Exploitability, Policy, Strategy};
pub use game::Game;
pub use result::{NodeRecord, ResultFile};
pub use spot::{Spot, SpotError, Street, IP, OOP, PLAYER_NAMES};
pub use tree::{Action, Node, NodeId, NodeKind, Tree};
