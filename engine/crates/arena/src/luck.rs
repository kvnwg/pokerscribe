//! Luck reduction: what a finished hand is scored as.
//!
//! A [`Scorer`] turns a finished hand into each seat's score in chips. [`ActualChips`]
//! keeps the real payouts. [`AllInEquity`] scores the equity when the players were all
//! in before the river. A scorer must not change any agent's expected result, only the
//! luck around it.
//!
//! # The hook for AIVAT
//!
//! AIVAT (Burch, Schmid, Moravcik, Morrill and Bowling, 2018) goes further: with a
//! value estimate for every situation and the strategy of the agents being measured, it
//! also corrects for the luck of the hole cards, of every board card and of the agents'
//! own random choices. It fits here as one more `Scorer`: build it holding the value
//! function and the strategies, read the whole hand from [`HandRecord::state`] (every
//! card, the full history, the starting stacks), and write the corrected scores. Pass
//! it to [`crate::run_match_scored`]. Nothing else in the arena changes: duplicate play,
//! the standard errors and the report work on whatever the scorer returns.

use std::cell::RefCell;

use nlhe::{Chips, Deal, State, MAX_PLAYERS};

use crate::equity::{all_in_equity, all_in_runout};

/// One finished hand of a match, with everything known about it.
#[derive(Clone, Copy, Debug)]
pub struct HandRecord<'a> {
    /// The number of the deal in the match, from 0.
    pub deal: u64,
    /// Which replay of the deal this is (the rotation of the lineup), from 0.
    pub replay: usize,
    /// A seed for the scorer's own random numbers: the same for every replay of a deal.
    pub seed: u64,
    /// The agent in each seat (an index into the match's agents).
    pub agents: &'a [usize],
    /// The final state: all hole cards, the board, the history, the stacks.
    pub state: &'a State,
    /// The real result per seat, in chips.
    pub payouts: &'a [i64],
}

/// Scores a finished hand.
pub trait Scorer: Send + Sync {
    /// A short name for the report.
    fn name(&self) -> String;

    /// Writes each seat's score in chips into `scores`, which arrives holding the real
    /// payouts: change only what is adjusted.
    fn score(&self, hand: &HandRecord<'_>, scores: &mut [f64]);
}

/// No adjustment: the real chips.
#[derive(Clone, Copy, Debug, Default)]
pub struct ActualChips;

impl Scorer for ActualChips {
    fn name(&self) -> String {
        "actual chips".to_string()
    }

    fn score(&self, _hand: &HandRecord<'_>, _scores: &mut [f64]) {}
}

/// When players are all in before the river, scores each seat's equity in place of the
/// cards that came: its payout averaged over every board that could still come.
///
/// `AllInEquity::default()` is exact. A match uses [`crate::DEFAULT_MAX_RUNOUTS`] unless
/// its config says otherwise.
#[derive(Clone, Copy, Debug, Default)]
pub struct AllInEquity {
    /// With `Some(k)`: when more than `k` boards are possible, average over `k` boards
    /// drawn at random in place of all of them (see [`all_in_equity`]). The draw is seeded
    /// by the deal, and the result still has no bias. `None` is exact.
    pub max_runouts: Option<u32>,
}

impl Scorer for AllInEquity {
    fn name(&self) -> String {
        match self.max_runouts {
            None => "all-in equity".to_string(),
            Some(k) => format!("all-in equity (at most {k} boards)"),
        }
    }

    fn score(&self, hand: &HandRecord<'_>, scores: &mut [f64]) {
        let state = hand.state;
        let Some(known) = all_in_runout(state) else {
            return;
        };
        let sample = self.max_runouts.map(|k| (k, hand.seed));
        let mut committed = [0; MAX_PLAYERS];
        committed[..state.num_players()].copy_from_slice(state.committed());
        let key = Situation {
            deal: *state.deal(),
            players: state.num_players(),
            button: state.button(),
            known,
            active: state.active_mask(),
            committed,
            sample,
        };
        let expected = LAST_DEAL.with_borrow_mut(|seen| {
            // The replays of a deal often end all in with the same cards and chips: one
            // answer serves them all.
            if seen.first().is_some_and(|(k, _)| k.deal != key.deal) {
                seen.clear();
            }
            if let Some((_, expected)) = seen.iter().find(|(k, _)| *k == key) {
                return *expected;
            }
            let expected = all_in_equity(state, sample).expect("the hand is an all-in runout");
            seen.push((key, expected));
            expected
        });
        scores.copy_from_slice(&expected[..scores.len()]);
    }
}

/// Everything the all-in equity depends on.
#[derive(Clone, Copy, PartialEq)]
struct Situation {
    deal: Deal,
    players: usize,
    button: usize,
    known: usize,
    active: u8,
    committed: [Chips; MAX_PLAYERS],
    sample: Option<(u32, u64)>,
}

thread_local! {
    /// The all-in situations of the deal this thread scored last, with their answers.
    static LAST_DEAL: RefCell<Vec<(Situation, [f64; MAX_PLAYERS])>> =
        const { RefCell::new(Vec::new()) };
}
