//! Running a match: many deals, on every core, with fixed seeds.
//!
//! # Seats
//!
//! The button is always seat 0, so a seat number is a position: seat 1 is the small
//! blind, seat 2 the big blind and so on (heads-up, seat 0 is the button and small
//! blind and seat 1 the big blind). The agents move, not the button.
//!
//! `lineup` says which agent holds each place at the table. Rotation `r` moves every
//! place `r` seats clockwise: the agent of place `j` sits in seat `(j + r) % players`.
//!
//! - Plain play: deal `d` is played once, with rotation `d % players`, so every agent
//!   visits every seat equally often.
//! - Duplicate play: every deal is played with every rotation. Heads-up that is twice,
//!   seats swapped. With `[b, a, a, a, a, a]`, b sits in each seat in turn with a in the
//!   five others. Any other lineup works the same way. Rotations that give the same
//!   seating again are played once.
//!
//! # Samples
//!
//! One sample per deal and agent: the agent's score averaged over all its seats in all
//! the replays of the deal. The win rate is the mean of the samples and its standard
//! error is `sd / sqrt(deals)`. Deals are independent; hands of the same deal are not,
//! which is the point of duplicate play.
//!
//! # Seeds
//!
//! Every random number comes from `seed`: the cards of deal `d`, and one private number
//! per seat and hand that the players draw their own randomness from. Deals are split
//! into fixed blocks, each block is added up in order and the blocks are merged in
//! order, so the result is the same to the last bit on 1 thread or 64.

use std::fmt;
use std::time::Instant;

use nlhe::{Chips, Config, ConfigError, Deal, MAX_PLAYERS};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};

use crate::hand::play_hand;
use crate::luck::{ActualChips, AllInEquity, HandRecord, Scorer};
use crate::mix;
use crate::player::{Agent, Player};
use crate::report::{position_name, AgentResult, MatchReport, SeatResult, Timing, FORMAT};

/// The default of [`MatchConfig::max_runouts`]. On the test bots it gives the same
/// standard error as every board, to three digits (see the README).
pub const DEFAULT_MAX_RUNOUTS: u32 = 10_000;

/// The settings of a match.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct MatchConfig {
    /// The agent (an index into the agents given to [`run_match`]) at each place of the
    /// table. Its length is the table size, 2 to 6.
    pub lineup: Vec<usize>,
    /// Every seat starts every hand with this many chips.
    pub stack: Chips,
    pub small_blind: Chips,
    pub big_blind: Chips,
    pub ante: Chips,
    /// How many deals. With duplicate play each is played several times.
    pub deals: u64,
    pub seed: u64,
    /// Replay every deal with the lineup rotated through every seat.
    pub duplicate: bool,
    /// Score the equity when players are all in before the river.
    pub all_in_equity: bool,
    /// The most boards the equity is averaged over (see [`AllInEquity::max_runouts`]).
    /// The default, 10,000, is exact on the flop and the turn and draws 10,000 random
    /// boards before the flop. `None` is exact everywhere, at 10 to 15 ms per hand that
    /// is all in before the flop.
    pub max_runouts: Option<u32>,
    /// Give a seat the same private random numbers in every replay of a deal. Agents
    /// that play alike then make the same random choices in the same spot, which
    /// tightens the comparison of two close versions. Off, every replay has its own.
    pub shared_randomness: bool,
    /// Worker threads. 0 uses every core.
    pub threads: usize,
}

impl MatchConfig {
    /// A match with this lineup: 100 big blinds deep at 50/100, duplicate play and
    /// all-in equity on (over at most [`DEFAULT_MAX_RUNOUTS`] boards).
    pub fn new(lineup: &[usize], deals: u64, seed: u64) -> MatchConfig {
        MatchConfig {
            lineup: lineup.to_vec(),
            stack: 10_000,
            small_blind: 50,
            big_blind: 100,
            ante: 0,
            deals,
            seed,
            duplicate: true,
            all_in_equity: true,
            max_runouts: Some(DEFAULT_MAX_RUNOUTS),
            shared_randomness: false,
            threads: 0,
        }
    }

    /// Agent 0 against agent 1 heads-up: every deal played twice, seats swapped.
    pub fn heads_up(deals: u64, seed: u64) -> MatchConfig {
        MatchConfig::new(&[0, 1], deals, seed)
    }

    /// Agent 1 against copies of agent 0 at a table of `players`: every deal replayed so
    /// that agent 1 sits in each seat in turn, with agent 0 in all the others.
    pub fn one_against_the_rest(players: usize, deals: u64, seed: u64) -> MatchConfig {
        let mut lineup = vec![0; players];
        lineup[0] = 1;
        MatchConfig::new(&lineup, deals, seed)
    }

    /// Plain play with real chips: no duplicate, no adjustment.
    pub fn plain(mut self) -> MatchConfig {
        self.duplicate = false;
        self.all_in_equity = false;
        self
    }

    /// The table size.
    pub fn players(&self) -> usize {
        self.lineup.len()
    }

    /// How many times each deal is played.
    pub fn replays(&self) -> usize {
        if !self.duplicate {
            return 1;
        }
        // The smallest rotation that gives the same seating again.
        let n = self.lineup.len();
        (1..=n)
            .find(|&p| (0..n).all(|j| self.lineup[j] == self.lineup[(j + p) % n]))
            .unwrap_or(n)
    }

    /// Hands played: `deals` times [`MatchConfig::replays`].
    pub fn hands(&self) -> u64 {
        self.deals * self.replays() as u64
    }

    fn table(&self, agents: usize) -> Result<Config, ArenaError> {
        let n = self.lineup.len();
        if !(2..=MAX_PLAYERS).contains(&n) {
            return Err(ArenaError::Config(format!(
                "the lineup has {n} places; a table takes 2 to 6"
            )));
        }
        if let Some(&a) = self.lineup.iter().find(|&&a| a >= agents) {
            return Err(ArenaError::Config(format!(
                "the lineup names agent {a} but only {agents} agents were given"
            )));
        }
        if self.deals == 0 {
            return Err(ArenaError::Config("a match needs at least 1 deal".into()));
        }
        if self.max_runouts == Some(0) {
            return Err(ArenaError::Config("max_runouts must be at least 1".into()));
        }
        let stacks = vec![self.stack; n];
        Ok(Config::new(
            &stacks,
            self.small_blind,
            self.big_blind,
            self.ante,
            0,
        )?)
    }
}

/// Why a match could not run or a report could not be saved.
#[derive(Debug)]
pub enum ArenaError {
    /// The match settings make no sense.
    Config(String),
    Io(std::io::Error),
    Json(serde_json::Error),
}

impl fmt::Display for ArenaError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ArenaError::Config(why) => write!(f, "{why}"),
            ArenaError::Io(e) => write!(f, "{e}"),
            ArenaError::Json(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for ArenaError {}

impl From<ConfigError> for ArenaError {
    fn from(e: ConfigError) -> ArenaError {
        ArenaError::Config(e.to_string())
    }
}
impl From<std::io::Error> for ArenaError {
    fn from(e: std::io::Error) -> ArenaError {
        ArenaError::Io(e)
    }
}
impl From<serde_json::Error> for ArenaError {
    fn from(e: serde_json::Error) -> ArenaError {
        ArenaError::Json(e)
    }
}

/// A running count, sum and sum of squares.
#[derive(Clone, Copy, Debug, Default)]
struct Tally {
    n: u64,
    sum: f64,
    sum_sq: f64,
}

impl Tally {
    fn add(&mut self, x: f64) {
        self.n += 1;
        self.sum += x;
        self.sum_sq += x * x;
    }

    fn merge(&mut self, other: &Tally) {
        self.n += other.n;
        self.sum += other.sum;
        self.sum_sq += other.sum_sq;
    }

    fn mean(&self) -> f64 {
        if self.n == 0 {
            0.0
        } else {
            self.sum / self.n as f64
        }
    }

    /// The standard error of the mean, from the sample variance.
    fn se(&self) -> Option<f64> {
        if self.n < 2 {
            return None;
        }
        let n = self.n as f64;
        let variance = ((self.sum_sq - self.sum * self.sum / n) / (n - 1.0)).max(0.0);
        Some((variance / n).sqrt())
    }
}

/// What one agent has added up so far.
#[derive(Clone, Debug, Default)]
struct AgentTally {
    /// Per deal: the score averaged over the agent's seats and the deal's replays.
    score: Tally,
    /// Per deal: the same in real chips.
    actual: Tally,
    /// Per hand: real chips averaged over the agent's seats.
    per_hand: Tally,
    /// Per deal and seat: the score averaged over the replays that had the agent there.
    by_seat: [Tally; MAX_PLAYERS],
    seat_hands: [u64; MAX_PLAYERS],
    illegal: u64,
}

/// The sums of a block of deals.
#[derive(Clone, Debug)]
struct Totals {
    agents: Vec<AgentTally>,
    adjusted_hands: u64,
}

impl Totals {
    fn new(agents: usize) -> Totals {
        Totals {
            agents: vec![AgentTally::default(); agents],
            adjusted_hands: 0,
        }
    }

    fn merge(&mut self, other: &Totals) {
        self.adjusted_hands += other.adjusted_hands;
        for (mine, theirs) in self.agents.iter_mut().zip(&other.agents) {
            mine.score.merge(&theirs.score);
            mine.actual.merge(&theirs.actual);
            mine.per_hand.merge(&theirs.per_hand);
            for s in 0..MAX_PLAYERS {
                mine.by_seat[s].merge(&theirs.by_seat[s]);
                mine.seat_hands[s] += theirs.seat_hands[s];
            }
            mine.illegal += theirs.illegal;
        }
    }
}

/// The players of one worker: one per place of the lineup, kept in seat order.
struct Table {
    players: Vec<Box<dyn Player>>,
    rotation: usize,
}

impl Table {
    fn new(lineup: &[usize], agents: &[Agent]) -> Table {
        Table {
            players: lineup.iter().map(|&a| agents[a].player()).collect(),
            rotation: 0,
        }
    }

    /// Seats the player of place `j` in seat `(j + rotation) % n`.
    fn rotate_to(&mut self, rotation: usize) {
        let n = self.players.len();
        self.players
            .rotate_right((rotation + n - self.rotation) % n);
        self.rotation = rotation;
    }
}

/// Deals per block. Fixed, so that the sums do not depend on the number of threads.
const BLOCK: u64 = 32;

/// Plays the match and scores it as the config says: all-in equity or real chips.
pub fn run_match(config: &MatchConfig, agents: &[Agent]) -> Result<MatchReport, ArenaError> {
    if config.all_in_equity {
        let scorer = AllInEquity {
            max_runouts: config.max_runouts,
        };
        run_match_scored(config, agents, &scorer)
    } else {
        run_match_scored(config, agents, &ActualChips)
    }
}

/// Plays the match with a scorer of your own (the hook for AIVAT, see [`crate::luck`]).
/// `config.all_in_equity` and `config.max_runouts` are not used.
pub fn run_match_scored(
    config: &MatchConfig,
    agents: &[Agent],
    scorer: &dyn Scorer,
) -> Result<MatchReport, ArenaError> {
    let table = config.table(agents.len())?;
    let n = config.players();
    let replays = config.replays();
    let mut places = vec![0usize; agents.len()];
    for &a in &config.lineup {
        places[a] += 1;
    }

    let block = |seats: &mut Table, first: u64| -> Totals {
        let mut totals = Totals::new(agents.len());
        let mut score = vec![0.0; agents.len()];
        let mut actual = vec![0.0; agents.len()];
        let mut hand_actual = vec![0.0; agents.len()];
        let mut seat_sum = vec![[0.0; MAX_PLAYERS]; agents.len()];
        let mut seat_count = vec![[0u32; MAX_PLAYERS]; agents.len()];
        for d in first..(first + BLOCK).min(config.deals) {
            let deal_seed = mix(config.seed, d);
            let deal = Deal::from_seed(deal_seed, n, 0);
            score.fill(0.0);
            actual.fill(0.0);
            seat_sum.fill([0.0; MAX_PLAYERS]);
            seat_count.fill([0; MAX_PLAYERS]);
            for k in 0..replays {
                let rotation = if config.duplicate {
                    k
                } else {
                    (d % n as u64) as usize
                };
                seats.rotate_to(rotation);
                let replay_key = if config.shared_randomness {
                    0
                } else {
                    1 + rotation as u64
                };
                let mut seeds = [0; MAX_PLAYERS];
                let mut agent_at = [0; MAX_PLAYERS];
                for s in 0..n {
                    seeds[s] = mix(mix(deal_seed, replay_key), 100 + s as u64);
                    agent_at[s] = config.lineup[(s + n - rotation) % n];
                }
                let played = play_hand(&table, deal, &mut seats.players, &seeds[..n])
                    .expect("a seeded deal is valid");
                let mut scores = [0.0; MAX_PLAYERS];
                for s in 0..n {
                    scores[s] = played.payouts[s] as f64;
                }
                scorer.score(
                    &HandRecord {
                        deal: d,
                        replay: rotation,
                        seed: mix(deal_seed, 99),
                        agents: &agent_at[..n],
                        state: &played.state,
                        payouts: &played.payouts[..n],
                    },
                    &mut scores[..n],
                );
                if (0..n).any(|s| scores[s] != played.payouts[s] as f64) {
                    totals.adjusted_hands += 1;
                }
                hand_actual.fill(0.0);
                for s in 0..n {
                    let a = agent_at[s];
                    let chips = played.payouts[s] as f64;
                    score[a] += scores[s];
                    actual[a] += chips;
                    hand_actual[a] += chips;
                    seat_sum[a][s] += scores[s];
                    seat_count[a][s] += 1;
                    totals.agents[a].seat_hands[s] += 1;
                    totals.agents[a].illegal += played.illegal[s] as u64;
                }
                for a in 0..agents.len() {
                    if places[a] > 0 {
                        totals.agents[a]
                            .per_hand
                            .add(hand_actual[a] / places[a] as f64);
                    }
                }
            }
            for a in 0..agents.len() {
                if places[a] == 0 {
                    continue;
                }
                let hands = (places[a] * replays) as f64;
                totals.agents[a].score.add(score[a] / hands);
                totals.agents[a].actual.add(actual[a] / hands);
                for s in 0..n {
                    if seat_count[a][s] > 0 {
                        totals.agents[a].by_seat[s].add(seat_sum[a][s] / seat_count[a][s] as f64);
                    }
                }
            }
        }
        totals
    };

    let start = Instant::now();
    let firsts: Vec<u64> = (0..config.deals).step_by(BLOCK as usize).collect();
    let (blocks, threads): (Vec<Totals>, usize) = if config.threads == 1 {
        let mut seats = Table::new(&config.lineup, agents);
        (firsts.iter().map(|&f| block(&mut seats, f)).collect(), 1)
    } else {
        let run = || {
            let blocks = firsts
                .par_iter()
                .map_init(
                    || Table::new(&config.lineup, agents),
                    |seats, &f| block(seats, f),
                )
                .collect();
            (blocks, rayon::current_num_threads())
        };
        if config.threads == 0 {
            run()
        } else {
            rayon::ThreadPoolBuilder::new()
                .num_threads(config.threads)
                .build()
                .map_err(|e| ArenaError::Config(format!("cannot start the threads: {e}")))?
                .install(run)
        }
    };
    let mut totals = Totals::new(agents.len());
    for b in &blocks {
        totals.merge(b);
    }
    let seconds = start.elapsed().as_secs_f64();

    let per_100 = 100.0 / config.big_blind as f64;
    let results = (0..agents.len())
        .filter(|&a| places[a] > 0)
        .map(|a| {
            let t = &totals.agents[a];
            AgentResult {
                index: a,
                agent: agents[a].name().to_string(),
                seats: places[a],
                hands: config.hands() * places[a] as u64,
                bb_per_100: t.score.mean() * per_100,
                se: t.score.se().map(|x| x * per_100),
                actual_bb_per_100: t.actual.mean() * per_100,
                actual_se: t.actual.se().map(|x| x * per_100),
                plain_se: t.per_hand.se().map(|x| x * per_100),
                illegal_actions: t.illegal,
                by_seat: (0..n)
                    .filter(|&s| t.seat_hands[s] > 0)
                    .map(|s| SeatResult {
                        seat: s,
                        position: position_name(n, s).to_string(),
                        hands: t.seat_hands[s],
                        bb_per_100: t.by_seat[s].mean() * per_100,
                        se: t.by_seat[s].se().map(|x| x * per_100),
                    })
                    .collect(),
            }
        })
        .collect();

    Ok(MatchReport {
        format: FORMAT.to_string(),
        config: config.clone(),
        scoring: scorer.name(),
        agents: agents.iter().map(|a| a.name().to_string()).collect(),
        players: n,
        deals: config.deals,
        replays_per_deal: replays,
        hands: config.hands(),
        adjusted_hands: totals.adjusted_hands,
        results,
        timing: Timing {
            seconds,
            hands_per_second: config.hands() as f64 / seconds.max(1e-9),
            threads,
        },
    })
}
