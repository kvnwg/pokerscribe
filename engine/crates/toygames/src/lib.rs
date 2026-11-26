//! Small poker games for testing the CFR core, with OpenSpiel's rules:
//! [`Kuhn`] poker for 2 or more players and [`Leduc`] hold'em for 2 or 3.

pub mod kuhn;
pub mod leduc;

pub use kuhn::{Kuhn, KuhnState};
pub use leduc::{Leduc, LeducState};
