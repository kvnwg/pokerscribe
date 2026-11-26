//! Sanity checks on built tables: that the buckets group hands sensibly.

use crate::{Abstraction, Street};

/// One check's outcome.
#[derive(Clone, Debug)]
pub struct CheckResult {
    pub name: String,
    pub passed: bool,
    pub detail: String,
}

/// Runs every check that applies to the abstraction's deck.
pub fn run(abstraction: &Abstraction) -> Vec<CheckResult> {
    let mut out = Vec::new();
    for street in [Street::Flop, Street::Turn, Street::River] {
        let table = abstraction.table(street).unwrap();
        let ordered = table.equity.windows(2).all(|w| w[0] <= w[1]);
        out.push(CheckResult {
            name: format!("{} buckets are numbered by equity", street.name()),
            passed: ordered,
            detail: format!(
                "bucket 0 has equity {:.3}, bucket {} has {:.3}",
                table.equity[0],
                table.buckets() - 1,
                table.equity[table.buckets() - 1]
            ),
        });
    }
    out
}
