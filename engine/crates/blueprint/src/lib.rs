//! The heads-up blueprint (Phases 5 and 6 of the roadmap): a strategy for the abstract
//! game, trained with external-sampling Monte Carlo CFR.
//!
//! - [`Buckets`]: the abstraction crate's bucket tables as `abstract_game`'s [`Bucketer`].
//! - [`Spec`]: the game (stack, bet menu, tables) and the training settings of a run.
//! - [`Run`]: training with threads and checkpoints, resumable, with a log of sessions.
//! - [`StrategyFile`]: the average strategy, two bytes a probability, dense, checked.
//! - [`Blueprint`]: the strategy in the real game, as `lbr`'s [`Strategy`], with bets that
//!   are not on the menu read by the pseudo-harmonic mapping.
//! - [`lbr_match`]: an LBR match that keeps every deal's result ([`Deals`]), so two
//!   strategies measured on the same deals can be compared with a paired standard error.
//!
//! ```no_run
//! use blueprint::{Blueprint, Run, Spec, Training};
//! use lbr::{play_match, LbrConfig, MatchConfig};
//!
//! let spec = Spec {
//!     stack_bb: 20,
//!     menu: "small".into(),
//!     abstraction: "/root/abstraction/k50".into(),
//!     training: Training::default(),
//! };
//! let mut run = Run::open(spec, "runs/small-k50".as_ref()).unwrap();
//! run.train(10_000_000, Some(10.0)).unwrap();
//! let file = run.export().file;
//! file.save("runs/small-k50/strategy.bps".as_ref()).unwrap();
//!
//! let blueprint = Blueprint::load("runs/small-k50/strategy.bps".as_ref(), None).unwrap();
//! let table = MatchConfig { stack: 2_000, ..MatchConfig::acpc(100_000, 1) };
//! println!("{}", play_match(&blueprint, &LbrConfig::default(), &table));
//! ```
//!
//! See README.md.
//!
//! [`Bucketer`]: abstract_game::Bucketer
//! [`Strategy`]: lbr::Strategy

pub mod buckets;
pub mod file;
pub mod gate;
pub mod matches;
pub mod play;
pub mod spec;
pub mod train;

pub use buckets::{tables_info, Buckets, TablesInfo};
pub use file::{decode, quantize, Export, GameInfo, Header, Layout, StrategyFile};
pub use matches::{lbr_match, Deals};
pub use play::{Blueprint, SmallBets};
pub use spec::{describe_menu, menu, PruneSettings, Spec, Training, MENU_NAMES};
pub use train::{build_game, peak_resident_bytes, resident_bytes, BlueprintGame, Run, Session};
