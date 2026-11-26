//! The result of a match, and its JSON file.

use std::fmt::Write as _;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::runner::{ArenaError, MatchConfig};

/// The `format` field of a report file.
pub const FORMAT: &str = "pokerscribe-arena/1";

/// The result of a match. Saved as JSON with [`MatchReport::save`].
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct MatchReport {
    pub format: String,
    pub config: MatchConfig,
    /// The scorer's name: "actual chips", "all-in equity", or a custom one.
    pub scoring: String,
    /// The agents' names; `config.lineup` holds indexes into this list.
    pub agents: Vec<String>,
    /// The table size.
    pub players: usize,
    pub deals: u64,
    /// How many times each deal was played: 1, or with duplicate play the number of
    /// different rotations of the lineup.
    pub replays_per_deal: usize,
    /// Hands played: `deals * replays_per_deal`.
    pub hands: u64,
    /// Hands whose score differs from the real chips (all-in before the river).
    pub adjusted_hands: u64,
    /// One entry per agent in the lineup.
    pub results: Vec<AgentResult>,
    pub timing: Timing,
}

/// One agent's result.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentResult {
    /// The agent's index in `agents`.
    pub index: usize,
    pub agent: String,
    /// How many seats of the table it holds.
    pub seats: usize,
    /// Hands it played, counting each of its seats.
    pub hands: u64,
    /// The win rate in big blinds per 100 hands, per seat it holds, after the luck
    /// reduction the match used.
    pub bb_per_100: f64,
    /// The standard error of `bb_per_100` (`null` with fewer than 2 deals). One sample
    /// per deal: the agent's average over the deal's replays.
    pub se: Option<f64>,
    /// The same match scored in real chips, before the scorer's adjustment.
    pub actual_bb_per_100: f64,
    pub actual_se: Option<f64>,
    /// The standard error plain play would give over the same number of hands: real
    /// chips, every hand counted as its own sample.
    pub plain_se: Option<f64>,
    /// Illegal actions it returned (each replaced by a check or a fold).
    pub illegal_actions: u64,
    /// The result in each seat. The button is always seat 0.
    pub by_seat: Vec<SeatResult>,
}

impl AgentResult {
    /// The win rate in standard errors: the number the 2.5 rule looks at. `None` when
    /// the standard error is unknown or 0 (identical agents with nothing random).
    pub fn z(&self) -> Option<f64> {
        self.se
            .filter(|&se| se > 1e-9)
            .map(|se| self.bb_per_100 / se)
    }
}

/// An agent's result in one seat.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SeatResult {
    pub seat: usize,
    /// "BTN", "SB", "BB", "UTG", "HJ", "CO"; heads-up "BTN/SB" and "BB".
    pub position: String,
    pub hands: u64,
    pub bb_per_100: f64,
    pub se: Option<f64>,
}

/// How long the match took. Not part of the result: it changes from run to run.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Timing {
    pub seconds: f64,
    pub hands_per_second: f64,
    pub threads: usize,
}

/// The usual name of a seat when the button is seat 0.
pub fn position_name(players: usize, seat: usize) -> &'static str {
    match (players, seat) {
        (2, 0) => "BTN/SB",
        (2, 1) => "BB",
        (_, 0) => "BTN",
        (_, 1) => "SB",
        (_, 2) => "BB",
        (n, s) if s + 1 == n => "CO",
        (6, 4) => "HJ",
        _ => "UTG",
    }
}

impl MatchReport {
    /// The first result of the agent with this name.
    pub fn result(&self, agent: &str) -> Option<&AgentResult> {
        self.results.iter().find(|r| r.agent == agent)
    }

    /// The result of the agent with this index in `agents`.
    pub fn result_of(&self, index: usize) -> Option<&AgentResult> {
        self.results.iter().find(|r| r.index == index)
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).expect("a report is plain data")
    }

    pub fn from_json(text: &str) -> Result<MatchReport, ArenaError> {
        Ok(serde_json::from_str(text)?)
    }

    /// Writes the report as JSON.
    pub fn save(&self, path: &Path) -> Result<(), ArenaError> {
        Ok(std::fs::write(path, self.to_json() + "\n")?)
    }

    pub fn load(path: &Path) -> Result<MatchReport, ArenaError> {
        MatchReport::from_json(&std::fs::read_to_string(path)?)
    }

    /// The report as a short text table.
    pub fn summary(&self) -> String {
        let mut out = String::new();
        let c = &self.config;
        let lineup: Vec<&str> = c.lineup.iter().map(|&a| self.agents[a].as_str()).collect();
        let _ = writeln!(
            out,
            "{} players [{}], blinds {}/{}, stacks {}, seed {}",
            self.players,
            lineup.join(" "),
            c.small_blind,
            c.big_blind,
            c.stack,
            c.seed
        );
        let _ = writeln!(
            out,
            "{} deals x {} = {} hands, {}, scored as {} ({} hands adjusted)",
            self.deals,
            self.replays_per_deal,
            self.hands,
            if c.duplicate { "duplicate" } else { "plain" },
            self.scoring,
            self.adjusted_hands
        );
        let se = |x: Option<f64>| x.map_or("n/a".to_string(), |v| format!("{v:.2}"));
        let _ = writeln!(
            out,
            "{:<14} {:>5} {:>10} {:>8} {:>7} {:>10} {:>9}",
            "agent", "seats", "bb/100", "SE", "z", "plain SE", "illegal"
        );
        for r in &self.results {
            let _ = writeln!(
                out,
                "{:<14} {:>5} {:>+10.2} {:>8} {:>7} {:>10} {:>9}",
                r.agent,
                r.seats,
                r.bb_per_100,
                se(r.se),
                r.z().map_or("n/a".to_string(), |z| format!("{z:+.1}")),
                se(r.plain_se),
                r.illegal_actions
            );
            for s in &r.by_seat {
                let _ = writeln!(
                    out,
                    "  {:<12} {:>5} {:>+10.2} {:>8}",
                    s.position,
                    "",
                    s.bb_per_100,
                    se(s.se)
                );
            }
        }
        let _ = write!(
            out,
            "{:.2} s, {:.0} hands/s on {} threads",
            self.timing.seconds, self.timing.hands_per_second, self.timing.threads
        );
        out
    }
}
