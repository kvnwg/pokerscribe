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
    /// AIVAT's settings when the match was also scored with it (`null` otherwise).
    #[serde(default)]
    pub aivat_scoring: Option<String>,
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
    /// The same hands scored with AIVAT, when the match was (`null` otherwise).
    #[serde(default)]
    pub aivat: Option<AivatResult>,
    /// The result in each seat. The button is always seat 0.
    pub by_seat: Vec<SeatResult>,
}

/// An agent's result scored with AIVAT ([`crate::aivat`]), on the same hands as the main
/// figure.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AivatResult {
    /// The win rate per seat held, in bb/100.
    pub bb_per_100: f64,
    /// Its standard error, one sample per deal as for the main figure.
    pub se: Option<f64>,
    /// AIVAT minus the main figure (`bb_per_100` of the result), deal by deal. Both have
    /// no bias, so this is 0 up to `minus_main_se`.
    pub minus_main: f64,
    pub minus_main_se: Option<f64>,
    /// `se` over the main figure's SE: how much AIVAT narrows it (the hands needed for the
    /// same SE shrink by its square).
    pub se_ratio: Option<f64>,
    /// The agent's decisions whose random choice AIVAT corrected (its chances were known).
    pub corrected_decisions: u64,
    /// Decisions without known chances: not corrected.
    pub unknown_decisions: u64,
    /// Decisions whose reported chances can't be the ones it played with (the action is
    /// not among them, or one is not legal): not corrected. Above 0 means a bug in the agent.
    pub unexplained_decisions: u64,
}

impl AivatResult {
    /// The AIVAT win rate in its standard errors.
    pub fn z(&self) -> Option<f64> {
        self.se
            .filter(|&se| se > 1e-9)
            .map(|se| self.bb_per_100 / se)
    }
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
        let z = |x: Option<f64>| x.map_or("n/a".to_string(), |z| format!("{z:+.1}"));
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
                z(r.z()),
                se(r.plain_se),
                r.illegal_actions
            );
            if let Some(a) = &r.aivat {
                let _ = writeln!(
                    out,
                    "  {:<12} {:>5} {:>+10.2} {:>8} {:>7}   SE x {}, minus the above {:+.2} +- {}",
                    "AIVAT",
                    "",
                    a.bb_per_100,
                    se(a.se),
                    z(a.z()),
                    a.se_ratio.map_or("n/a".to_string(), |x| format!("{x:.3}")),
                    a.minus_main,
                    se(a.minus_main_se)
                );
            }
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
        if let Some(name) = &self.aivat_scoring {
            let counts: Vec<String> = self
                .results
                .iter()
                .filter_map(|r| {
                    let a = r.aivat.as_ref()?;
                    let all = a.corrected_decisions + a.unknown_decisions + a.unexplained_decisions;
                    let mut text = format!("{} {} of {}", r.agent, a.corrected_decisions, all);
                    if a.unexplained_decisions > 0 {
                        text += &format!(" ({} unexplained)", a.unexplained_decisions);
                    }
                    Some(text)
                })
                .collect();
            let _ = writeln!(out, "{name}; decisions corrected: {}", counts.join(", "));
        }
        let _ = write!(
            out,
            "{:.2} s, {:.0} hands/s on {} threads",
            self.timing.seconds, self.timing.hands_per_second, self.timing.threads
        );
        out
    }
}
