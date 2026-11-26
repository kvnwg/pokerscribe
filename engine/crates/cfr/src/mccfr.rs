//! Monte Carlo CFR (Lanctot et al. 2009): external sampling and outcome
//! sampling, with optional linear weighting and Pluribus-style
//! negative-regret pruning.
//!
//! Information sets are added to the table the first time a traversal
//! reaches them, so the tree is never walked in full. Each iteration runs one
//! traversal per player, players in order. Runs are deterministic given the
//! seed.

use crate::game::{child, Game, Node};
use crate::policy::{regret_matching, TabularPolicy};
use crate::rng::Rng;
use crate::scratch::Scratch;
use crate::table::InfoTable;
use crate::Solver;

/// How a traversal samples.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Sampling {
    /// Sample chance and the other players; try every action of the
    /// traversing player. The average strategy is accumulated at the other
    /// players' nodes ("simple" averaging, as in OpenSpiel and Pluribus).
    External,
    /// Sample one terminal history per traversal. The traversing player
    /// samples from `epsilon * uniform + (1 - epsilon) * current strategy`;
    /// estimates are importance weighted.
    Outcome { epsilon: f64 },
}

impl Sampling {
    /// Outcome sampling with OpenSpiel's default exploration, 0.6.
    pub const OUTCOME: Sampling = Sampling::Outcome { epsilon: 0.6 };
}

/// Linear weighting done as Pluribus did it: every `interval` iterations,
/// while the iteration count is at most `until`, all regrets and strategy
/// sums are multiplied by k / (k + 1), where k is the number of intervals
/// done. Iteration t then ends up weighted roughly in proportion to t.
/// After `until`, weights stay constant. `interval: 1` is exact linear
/// weighting.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LinearWeighting {
    pub interval: u64,
    pub until: u64,
}

/// Pluribus-style negative-regret pruning (external sampling only). After
/// `warmup` iterations, each traversal is a pruned one with probability
/// `probability`: actions of the traversing player whose regret is below
/// `threshold` are skipped, unless they end the game or the game says the
/// node is exempt ([`Game::prune_exempt`]). Pluribus used a warm-up of 200
/// minutes, probability 0.95 and a threshold of -300 million on its integer
/// regrets. Pick the threshold relative to the game's regret scale: too close
/// to zero and actions that are only briefly bad get frozen out.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pruning {
    pub warmup: u64,
    pub threshold: f64,
    pub probability: f64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MccfrConfig {
    pub sampling: Sampling,
    pub seed: u64,
    pub linear: Option<LinearWeighting>,
    pub pruning: Option<Pruning>,
    /// Regrets never fall below this (Pluribus floored them at -310 million
    /// so an action can recover). `None` means no floor.
    pub regret_floor: Option<f64>,
}

impl MccfrConfig {
    pub fn new(sampling: Sampling, seed: u64) -> Self {
        MccfrConfig {
            sampling,
            seed,
            linear: None,
            pruning: None,
            regret_floor: None,
        }
    }

    pub fn linear(mut self, interval: u64, until: u64) -> Self {
        self.linear = Some(LinearWeighting { interval, until });
        self
    }

    pub fn pruning(mut self, warmup: u64, threshold: f64, probability: f64) -> Self {
        self.pruning = Some(Pruning {
            warmup,
            threshold,
            probability,
        });
        self
    }

    pub fn regret_floor(mut self, floor: f64) -> Self {
        self.regret_floor = Some(floor);
        self
    }
}

/// Counters for one solver run.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct MccfrStats {
    pub nodes_touched: u64,
    pub pruned_traversals: u64,
    pub pruned_actions: u64,
}

pub struct Mccfr<G: Game> {
    game: G,
    cfg: MccfrConfig,
    table: InfoTable,
    regret: Vec<f64>,
    strategy_sum: Vec<f64>,
    rng: Rng,
    iteration: u64,
    stats: MccfrStats,
    scratch: Scratch,
}

impl<G: Game> Mccfr<G> {
    pub fn new(game: G, cfg: MccfrConfig) -> Self {
        if let Some(l) = cfg.linear {
            assert!(l.interval > 0, "linear weighting interval must be positive");
        }
        if let Some(p) = cfg.pruning {
            assert!(
                cfg.sampling == Sampling::External,
                "pruning is only defined for external sampling"
            );
            assert!((0.0..=1.0).contains(&p.probability));
        }
        if let Sampling::Outcome { epsilon } = cfg.sampling {
            assert!(
                epsilon > 0.0 && epsilon <= 1.0,
                "outcome sampling needs 0 < epsilon <= 1"
            );
        }
        Mccfr {
            game,
            cfg,
            table: InfoTable::new(),
            regret: Vec::new(),
            strategy_sum: Vec::new(),
            rng: Rng::new(cfg.seed),
            iteration: 0,
            stats: MccfrStats::default(),
            scratch: Scratch::default(),
        }
    }

    /// Pre-sizes the table and arrays (no growth during the run if the
    /// estimates are high enough).
    pub fn reserve(&mut self, info_sets: usize, slots: usize) {
        self.table = InfoTable::with_capacity(info_sets);
        self.regret.reserve(slots);
        self.strategy_sum.reserve(slots);
    }

    pub fn game(&self) -> &G {
        &self.game
    }

    pub fn config(&self) -> &MccfrConfig {
        &self.cfg
    }

    pub fn table(&self) -> &InfoTable {
        &self.table
    }

    pub fn regrets(&self) -> &[f64] {
        &self.regret
    }

    pub fn stats(&self) -> MccfrStats {
        self.stats
    }

    /// The regret-matching strategy at every information set seen so far.
    pub fn current_policy(&self) -> TabularPolicy {
        let mut cur = vec![0.0; self.table.slots()];
        for set in self.table.sets() {
            let r = set.range();
            regret_matching(&self.regret[r.clone()], &mut cur[r]);
        }
        TabularPolicy::from_weights(&self.table, &cur)
    }

    #[inline]
    fn lookup(&mut self, s: &G::State, num_actions: usize, player: usize) -> (usize, usize) {
        let (idx, new) = self
            .table
            .get_or_insert(self.game.info_key(s), num_actions, player);
        if new {
            self.regret.resize(self.table.slots(), 0.0);
            self.strategy_sum.resize(self.table.slots(), 0.0);
        }
        let set = self.table.set(idx);
        (set.offset as usize, num_actions)
    }

    #[inline]
    fn add_regret(&mut self, slot: usize, delta: f64) {
        let mut r = self.regret[slot] + delta;
        if let Some(floor) = self.cfg.regret_floor {
            if r < floor {
                r = floor;
            }
        }
        self.regret[slot] = r;
    }

    fn discount(&mut self) {
        let Some(l) = self.cfg.linear else { return };
        let t = self.iteration;
        if !t.is_multiple_of(l.interval) || t > l.until {
            return;
        }
        let k = (t / l.interval) as f64;
        let d = k / (k + 1.0);
        self.regret.iter_mut().for_each(|x| *x *= d);
        self.strategy_sum.iter_mut().for_each(|x| *x *= d);
    }

    /// External sampling traversal for `player`; returns the sampled value.
    fn external(&mut self, s: &G::State, player: usize, prune: bool, depth: usize) -> f64 {
        self.stats.nodes_touched += 1;
        match self.game.node(s) {
            Node::Terminal => self.game.utility(s, player),
            Node::Chance => {
                let mut f = self.scratch.take(depth);
                let a = self.game.sample_chance(s, &mut self.rng, &mut f.chance);
                self.scratch.put(depth, f);
                let c = child(&self.game, s, a);
                self.external(&c, player, prune, depth + 1)
            }
            Node::Player(q) => {
                let mut f = self.scratch.take(depth);
                self.game.legal_actions(s, &mut f.actions);
                let n = f.actions.len();
                let (off, _) = self.lookup(s, n, q);
                f.probs.resize(n, 0.0);
                regret_matching(&self.regret[off..off + n], &mut f.probs);
                let v = if q == player {
                    let threshold = self.cfg.pruning.map_or(f64::NEG_INFINITY, |p| p.threshold);
                    let may_prune = prune && !self.game.prune_exempt(s);
                    f.values.clear();
                    f.values.resize(n, 0.0);
                    f.explored.clear();
                    f.explored.resize(n, true);
                    let mut v = 0.0;
                    for i in 0..n {
                        let c = child(&self.game, s, f.actions[i]);
                        if may_prune
                            && self.regret[off + i] < threshold
                            && self.game.node(&c) != Node::Terminal
                        {
                            f.explored[i] = false;
                            self.stats.pruned_actions += 1;
                            continue;
                        }
                        let u = self.external(&c, player, prune, depth + 1);
                        f.values[i] = u;
                        v += f.probs[i] * u;
                    }
                    for i in 0..n {
                        if f.explored[i] {
                            self.add_regret(off + i, f.values[i] - v);
                        }
                    }
                    v
                } else {
                    for i in 0..n {
                        self.strategy_sum[off + i] += f.probs[i];
                    }
                    let i = self.rng.sample(&f.probs);
                    let c = child(&self.game, s, f.actions[i]);
                    self.external(&c, player, prune, depth + 1)
                };
                self.scratch.put(depth, f);
                v
            }
        }
    }

    /// Outcome sampling traversal for `player`. `my_reach` is `player`'s
    /// reach under the current strategy, `opp_reach` everyone else's with
    /// chance, `sample_reach` the probability this history was sampled.
    /// Returns the importance-weighted value estimate of this node for
    /// `player`, with the weighting below this node only.
    fn outcome(
        &mut self,
        s: &G::State,
        player: usize,
        my_reach: f64,
        opp_reach: f64,
        sample_reach: f64,
        depth: usize,
    ) -> f64 {
        self.stats.nodes_touched += 1;
        match self.game.node(s) {
            Node::Terminal => self.game.utility(s, player),
            Node::Chance => {
                // Sampled from the true distribution: the probability
                // cancels in opp_reach / sample_reach, so neither is scaled.
                let mut f = self.scratch.take(depth);
                let a = self.game.sample_chance(s, &mut self.rng, &mut f.chance);
                self.scratch.put(depth, f);
                let c = child(&self.game, s, a);
                self.outcome(&c, player, my_reach, opp_reach, sample_reach, depth + 1)
            }
            Node::Player(q) => {
                let mut f = self.scratch.take(depth);
                self.game.legal_actions(s, &mut f.actions);
                let n = f.actions.len();
                let (off, _) = self.lookup(s, n, q);
                f.probs.resize(n, 0.0);
                regret_matching(&self.regret[off..off + n], &mut f.probs);
                let v = if q == player {
                    // Sampling policy: epsilon-uniform mix, kept in `values`.
                    let Sampling::Outcome { epsilon } = self.cfg.sampling else {
                        unreachable!()
                    };
                    let u = 1.0 / n as f64;
                    f.values.clear();
                    f.values
                        .extend(f.probs.iter().map(|&p| epsilon * u + (1.0 - epsilon) * p));
                    let i = self.rng.sample(&f.values);
                    let sp = f.values[i];
                    let pi = f.probs[i];
                    let c = child(&self.game, s, f.actions[i]);
                    let child_value = self.outcome(
                        &c,
                        player,
                        my_reach * pi,
                        opp_reach,
                        sample_reach * sp,
                        depth + 1,
                    );
                    // Unbiased estimate of each action's value: only the
                    // sampled one is non-zero.
                    let action_value = child_value / sp;
                    let value = pi * action_value;
                    let w = opp_reach / sample_reach;
                    for a in 0..n {
                        let av = if a == i { action_value } else { 0.0 };
                        self.add_regret(off + a, w * (av - value));
                    }
                    let ws = my_reach / sample_reach;
                    for a in 0..n {
                        self.strategy_sum[off + a] += ws * f.probs[a];
                    }
                    value
                } else {
                    let i = self.rng.sample(&f.probs);
                    let pi = f.probs[i];
                    let c = child(&self.game, s, f.actions[i]);
                    // Sampled on-policy: pi cancels between opp_reach and
                    // sample_reach, and the value needs no correction.
                    self.outcome(
                        &c,
                        player,
                        my_reach,
                        opp_reach * pi,
                        sample_reach * pi,
                        depth + 1,
                    )
                };
                self.scratch.put(depth, f);
                v
            }
        }
    }
}

impl<G: Game> Solver for Mccfr<G> {
    fn iterate(&mut self) {
        self.iteration += 1;
        let root = self.game.root();
        for p in 0..self.game.num_players() {
            match self.cfg.sampling {
                Sampling::External => {
                    let prune = match self.cfg.pruning {
                        Some(c) if self.iteration > c.warmup => self.rng.next_f64() < c.probability,
                        _ => false,
                    };
                    if prune {
                        self.stats.pruned_traversals += 1;
                    }
                    self.external(&root, p, prune, 0);
                }
                Sampling::Outcome { .. } => {
                    self.outcome(&root, p, 1.0, 1.0, 1.0, 0);
                }
            }
        }
        self.discount();
    }

    fn iterations(&self) -> u64 {
        self.iteration
    }

    fn average_policy(&self) -> TabularPolicy {
        TabularPolicy::from_weights(&self.table, &self.strategy_sum)
    }

    fn info_sets(&self) -> usize {
        self.table.len()
    }

    fn nodes_touched(&self) -> u64 {
        self.stats.nodes_touched
    }
}
