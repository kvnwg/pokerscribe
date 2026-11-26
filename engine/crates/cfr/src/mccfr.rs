//! Monte Carlo CFR (Lanctot et al. 2009): external sampling and outcome
//! sampling, with optional linear weighting and Pluribus-style
//! negative-regret pruning.
//!
//! Information sets are added to the table the first time a traversal
//! reaches them, so the tree is never walked in full. Each iteration runs one
//! traversal per player, players in order.
//!
//! One thread (the default): a run is deterministic given the seed, bit for
//! bit, and can be saved and resumed without changing it
//! ([`Mccfr::save`], [`Mccfr::resume`]).
//!
//! Several threads ([`MccfrConfig::threads`], external sampling only), as
//! Pluribus trained: every thread runs its own traversals with its own random
//! stream, and all of them read and write the same regrets and strategy sums
//! without locks. Two threads that update the same slot at the same moment
//! can lose one of the updates. That is harmless noise for Monte Carlo CFR,
//! but it makes a run depend on timing: several threads are never
//! reproducible.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Instant;

use crate::game::{child, Game, Node};
use crate::policy::TabularPolicy;
use crate::rng::Rng;
use crate::scratch::Scratch;
use crate::shared::{Entry, SharedTable};
use crate::signal;
use crate::store::{RegretStorage, Regrets, Sums};
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
    /// 64-bit floats (the default) or 32-bit integers.
    pub storage: RegretStorage,
    /// Threads that traverse at once. 1 (the default) is deterministic.
    /// More needs external sampling and gives a run that depends on timing.
    pub threads: usize,
}

impl MccfrConfig {
    pub fn new(sampling: Sampling, seed: u64) -> Self {
        MccfrConfig {
            sampling,
            seed,
            linear: None,
            pruning: None,
            regret_floor: None,
            storage: RegretStorage::F64,
            threads: 1,
        }
    }

    /// Regrets as 32-bit integers: half the memory of the floats. See
    /// [`RegretStorage::I32`] for how to pick `scale`.
    pub fn compact(mut self, scale: f64) -> Self {
        self.storage = RegretStorage::I32 { scale };
        self
    }

    /// Traverse on `threads` threads sharing the regrets (external sampling).
    pub fn threads(mut self, threads: usize) -> Self {
        self.threads = threads;
        self
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

/// What the solver's memory goes to.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Memory {
    pub info_sets: usize,
    /// (information set, action) pairs.
    pub slots: usize,
    /// The key index: 16 bytes a cell, a quarter to three quarters full.
    pub index_bytes: usize,
    /// Regrets in use: 8 bytes a slot as floats, 4 as integers.
    pub regret_bytes: usize,
    /// Strategy sums in use: 8 bytes a slot.
    pub strategy_bytes: usize,
    /// Address space reserved for the two arrays. They grow by doubling, so
    /// up to half of it is pages that have never been touched and take no
    /// memory.
    pub reserved_bytes: usize,
}

impl Memory {
    /// Bytes in use for each information set, index included.
    pub fn bytes_per_info_set(&self) -> f64 {
        (self.index_bytes + self.regret_bytes + self.strategy_bytes) as f64
            / self.info_sets.max(1) as f64
    }
}

/// What one traversing thread owns. Aligned to two cache lines so that one
/// thread's generator and counters, written at every node, never share a
/// line with another thread's.
#[repr(align(128))]
pub(crate) struct Worker {
    pub rng: Rng,
    scratch: Scratch,
    pub stats: MccfrStats,
}

impl Worker {
    pub fn new(rng: Rng) -> Self {
        Worker {
            rng,
            scratch: Scratch::default(),
            stats: MccfrStats::default(),
        }
    }
}

/// What all the threads share.
pub(crate) struct Core<G: Game> {
    pub game: G,
    pub cfg: MccfrConfig,
    pub table: SharedTable,
    pub regret: Regrets,
    pub sums: Sums,
}

pub struct Mccfr<G: Game> {
    pub(crate) core: Core<G>,
    /// One per thread; `workers[0]` also runs every single-threaded
    /// iteration.
    pub(crate) workers: Vec<Worker>,
    pub(crate) iteration: u64,
}

/// When a run should stop before its last iteration: a stop was asked for
/// ([`signal::stop_requested`]) or the next save is due.
pub(crate) struct Pause {
    pub deadline: Option<Instant>,
}

impl Pause {
    #[inline]
    fn asked(&self) -> bool {
        signal::stop_requested()
    }

    #[inline]
    fn due(&self) -> bool {
        self.deadline.is_some_and(|d| Instant::now() >= d)
    }
}

/// Iterations between two looks at the clock.
const CLOCK_EVERY: u64 = 64;

impl<G: Game> Core<G> {
    fn new(game: G, cfg: MccfrConfig, table: SharedTable) -> Self {
        Core {
            game,
            cfg,
            table,
            regret: Regrets::new(cfg.storage, cfg.regret_floor),
            sums: Sums::new(),
        }
    }

    /// First slot of the information set at `s`, adding it if it is new.
    #[inline]
    fn lookup(&self, s: &G::State, num_actions: usize, player: usize) -> usize {
        self.table
            .get_or_insert(self.game.info_key(s), num_actions, player, |offset| {
                self.regret.ensure(offset);
                self.sums.ensure(offset);
            })
    }

    /// Iteration `t`: one traversal per player, players in order.
    fn traverse(&self, w: &mut Worker, t: u64) {
        let root = self.game.root();
        for p in 0..self.game.num_players() {
            match self.cfg.sampling {
                Sampling::External => {
                    let prune = match self.cfg.pruning {
                        Some(c) if t > c.warmup => w.rng.next_f64() < c.probability,
                        _ => false,
                    };
                    if prune {
                        w.stats.pruned_traversals += 1;
                    }
                    self.external(w, &root, p, prune, 0);
                }
                Sampling::Outcome { .. } => {
                    self.outcome(w, &root, p, 1.0, 1.0, 1.0, 0);
                }
            }
        }
    }

    /// External sampling traversal for `player`; returns the sampled value.
    fn external(
        &self,
        w: &mut Worker,
        s: &G::State,
        player: usize,
        prune: bool,
        depth: usize,
    ) -> f64 {
        w.stats.nodes_touched += 1;
        match self.game.node(s) {
            Node::Terminal => self.game.utility(s, player),
            Node::Chance => {
                let mut f = w.scratch.take(depth);
                let a = self.game.sample_chance(s, &mut w.rng, &mut f.chance);
                w.scratch.put(depth, f);
                let c = child(&self.game, s, a);
                self.external(w, &c, player, prune, depth + 1)
            }
            Node::Player(q) => {
                let mut f = w.scratch.take(depth);
                self.game.legal_actions(s, &mut f.actions);
                let n = f.actions.len();
                let off = self.lookup(s, n, q);
                f.probs.resize(n, 0.0);
                self.regret.matching(off, &mut f.probs);
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
                            && self.regret.get(off + i) < threshold
                            && self.game.node(&c) != Node::Terminal
                        {
                            f.explored[i] = false;
                            w.stats.pruned_actions += 1;
                            continue;
                        }
                        let u = self.external(w, &c, player, prune, depth + 1);
                        f.values[i] = u;
                        v += f.probs[i] * u;
                    }
                    self.regret.update(off, &f.values, v, &f.explored);
                    v
                } else {
                    self.sums.add_plain(off, &f.probs);
                    let i = w.rng.sample(&f.probs);
                    let c = child(&self.game, s, f.actions[i]);
                    self.external(w, &c, player, prune, depth + 1)
                };
                w.scratch.put(depth, f);
                v
            }
        }
    }

    /// Outcome sampling traversal for `player`. `my_reach` is `player`'s
    /// reach under the current strategy, `opp_reach` everyone else's with
    /// chance, `sample_reach` the probability this history was sampled.
    /// Returns the importance-weighted value estimate of this node for
    /// `player`, with the weighting below this node only.
    #[allow(clippy::too_many_arguments)]
    fn outcome(
        &self,
        w: &mut Worker,
        s: &G::State,
        player: usize,
        my_reach: f64,
        opp_reach: f64,
        sample_reach: f64,
        depth: usize,
    ) -> f64 {
        w.stats.nodes_touched += 1;
        match self.game.node(s) {
            Node::Terminal => self.game.utility(s, player),
            Node::Chance => {
                // Sampled from the true distribution: the probability
                // cancels in opp_reach / sample_reach, so neither is scaled.
                let mut f = w.scratch.take(depth);
                let a = self.game.sample_chance(s, &mut w.rng, &mut f.chance);
                w.scratch.put(depth, f);
                let c = child(&self.game, s, a);
                self.outcome(w, &c, player, my_reach, opp_reach, sample_reach, depth + 1)
            }
            Node::Player(q) => {
                let mut f = w.scratch.take(depth);
                self.game.legal_actions(s, &mut f.actions);
                let n = f.actions.len();
                let off = self.lookup(s, n, q);
                f.probs.resize(n, 0.0);
                self.regret.matching(off, &mut f.probs);
                let v = if q == player {
                    // Sampling policy: epsilon-uniform mix, kept in `values`.
                    let Sampling::Outcome { epsilon } = self.cfg.sampling else {
                        unreachable!()
                    };
                    let u = 1.0 / n as f64;
                    f.values.clear();
                    f.values
                        .extend(f.probs.iter().map(|&p| epsilon * u + (1.0 - epsilon) * p));
                    let i = w.rng.sample(&f.values);
                    let sp = f.values[i];
                    let pi = f.probs[i];
                    let c = child(&self.game, s, f.actions[i]);
                    let child_value = self.outcome(
                        w,
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
                    let weight = opp_reach / sample_reach;
                    for a in 0..n {
                        let av = if a == i { action_value } else { 0.0 };
                        self.regret.add(off + a, weight * (av - value));
                    }
                    self.sums.add(off, &f.probs, my_reach / sample_reach);
                    value
                } else {
                    let i = w.rng.sample(&f.probs);
                    let pi = f.probs[i];
                    let c = child(&self.game, s, f.actions[i]);
                    // Sampled on-policy: pi cancels between opp_reach and
                    // sample_reach, and the value needs no correction.
                    self.outcome(
                        w,
                        &c,
                        player,
                        my_reach,
                        opp_reach * pi,
                        sample_reach * pi,
                        depth + 1,
                    )
                };
                w.scratch.put(depth, f);
                v
            }
        }
    }
}

impl<G: Game> Mccfr<G> {
    pub fn new(game: G, cfg: MccfrConfig) -> Self {
        Self::check(&cfg);
        Self::from_parts(game, cfg, SharedTable::new())
    }

    fn check(cfg: &MccfrConfig) {
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
        assert!(cfg.threads >= 1, "at least one thread");
        assert!(
            cfg.threads == 1 || cfg.sampling == Sampling::External,
            "several threads need external sampling"
        );
    }

    pub(crate) fn from_parts(game: G, cfg: MccfrConfig, table: SharedTable) -> Self {
        Mccfr {
            core: Core::new(game, cfg, table),
            workers: (0..cfg.threads)
                .map(|t| Worker::new(Rng::for_thread(cfg.seed, t)))
                .collect(),
            iteration: 0,
        }
    }

    /// Pre-sizes the index for `info_sets` information sets and the arrays
    /// for `slots` (information set, action) pairs, so neither has to grow
    /// during the run if the estimates are high enough. Call it before the
    /// first iteration.
    pub fn reserve(&mut self, info_sets: usize, slots: usize) {
        assert!(
            self.core.table.len() == 0,
            "reserve before the first iteration"
        );
        self.core.table = SharedTable::with_capacity(info_sets);
        // Touch the first slot of every segment the arrays will need.
        let mut slot = 0;
        while slot < slots {
            self.core.regret.ensure(slot);
            self.core.sums.ensure(slot);
            slot = (slot + 4096) * 2 - 4096;
        }
    }

    pub fn game(&self) -> &G {
        &self.core.game
    }

    pub fn config(&self) -> &MccfrConfig {
        &self.core.cfg
    }

    /// Changes how many threads traverse from now on (a run resumed on a
    /// machine with more or fewer cores). Threads that stay keep their random
    /// streams; a dropped thread's counters are dropped with it.
    pub fn set_threads(&mut self, threads: usize) {
        let cfg = MccfrConfig {
            threads,
            ..self.core.cfg
        };
        Self::check(&cfg);
        self.core.cfg = cfg;
        // Mixing the iteration in keeps a thread that is added back later
        // from replaying the draws it made before it was dropped.
        let seed = cfg.seed ^ self.iteration.wrapping_mul(0x9E37_79B9_7F4A_7C15);
        self.workers.truncate(threads);
        while self.workers.len() < threads {
            let rng = Rng::for_thread(seed, self.workers.len());
            self.workers.push(Worker::new(rng));
        }
    }

    /// The information sets seen so far, in key order. Slot `i` of
    /// [`Mccfr::regrets`] and [`Mccfr::strategy_sums`] belongs to the set
    /// whose range holds `i`.
    pub fn table(&self) -> InfoTable {
        self.view().0
    }

    /// Every regret, in the game's units, laid out as [`Mccfr::table`] says.
    pub fn regrets(&self) -> Vec<f64> {
        let mut out = Vec::with_capacity(self.core.table.used_slots());
        for e in self.core.table.sorted() {
            out.extend((0..e.num_actions).map(|i| self.core.regret.get(e.offset + i)));
        }
        out
    }

    /// Every strategy sum, laid out as [`Mccfr::table`] says.
    pub fn strategy_sums(&self) -> Vec<f64> {
        let mut out = Vec::with_capacity(self.core.table.used_slots());
        for e in self.core.table.sorted() {
            out.extend((0..e.num_actions).map(|i| self.core.sums.get(e.offset + i)));
        }
        out
    }

    /// The table in key order, with each entry of the shared index.
    fn view(&self) -> (InfoTable, Vec<Entry>) {
        let entries = self.core.table.sorted();
        let mut table = InfoTable::with_capacity(entries.len());
        for e in &entries {
            table.get_or_insert(e.key, e.num_actions, e.player);
        }
        (table, entries)
    }

    /// Counters summed over every thread.
    pub fn stats(&self) -> MccfrStats {
        let mut total = MccfrStats::default();
        for w in &self.workers {
            total.nodes_touched += w.stats.nodes_touched;
            total.pruned_traversals += w.stats.pruned_traversals;
            total.pruned_actions += w.stats.pruned_actions;
        }
        total
    }

    /// What the tables take.
    pub fn memory(&self) -> Memory {
        let mut slots = 0;
        self.core.table.for_each(|e| slots += e.num_actions);
        Memory {
            info_sets: self.core.table.len(),
            slots,
            index_bytes: self.core.table.index_bytes(),
            regret_bytes: slots * self.core.regret.bytes_per_slot(),
            strategy_bytes: slots * 8,
            reserved_bytes: self.core.regret.allocated_bytes() + self.core.sums.allocated_bytes(),
        }
    }

    /// The regret-matching strategy at every information set seen so far.
    pub fn current_policy(&self) -> TabularPolicy {
        let (table, entries) = self.view();
        let mut cur = vec![0.0; table.slots()];
        for (set, e) in table.sets().iter().zip(&entries) {
            self.core.regret.matching(e.offset, &mut cur[set.range()]);
        }
        TabularPolicy::from_weights(&table, &cur)
    }

    fn discount(&mut self) {
        let Some(l) = self.core.cfg.linear else {
            return;
        };
        let t = self.iteration;
        if !t.is_multiple_of(l.interval) || t > l.until {
            return;
        }
        let k = (t / l.interval) as f64;
        let d = k / (k + 1.0);
        let used = self.core.table.used_slots();
        self.core.regret.scale_all(used, d);
        self.core.sums.scale_all(used, d);
    }

    /// The last iteration that can run before the next discount is due.
    fn stretch_end(&self, until: u64) -> u64 {
        match self.core.cfg.linear {
            Some(l) if self.iteration < l.until => {
                until.min((self.iteration / l.interval + 1) * l.interval)
            }
            _ => until,
        }
    }
}

impl<G: Game + Sync> Mccfr<G> {
    /// Runs up to iteration `until`, or until `pause` says to stop. Returns
    /// true when it stopped early.
    pub(crate) fn advance(&mut self, until: u64, pause: Option<&Pause>) -> bool {
        if self.core.cfg.threads == 1 {
            self.advance_alone(until, pause)
        } else {
            self.advance_together(until, pause)
        }
    }

    fn advance_alone(&mut self, until: u64, pause: Option<&Pause>) -> bool {
        while self.iteration < until {
            self.iteration += 1;
            self.core.traverse(&mut self.workers[0], self.iteration);
            self.discount();
            if let Some(p) = pause {
                if p.asked() || (self.iteration.is_multiple_of(CLOCK_EVERY) && p.due()) {
                    return self.iteration < until;
                }
            }
        }
        false
    }

    /// Every thread takes the next iteration number from a shared counter,
    /// runs that iteration's traversals, and takes another. The threads stop
    /// together where a discount is due, since the discount rewrites every
    /// slot and must have the tables to itself.
    fn advance_together(&mut self, until: u64, pause: Option<&Pause>) -> bool {
        while self.iteration < until {
            let end = self.stretch_end(until);
            let next = AtomicU64::new(self.iteration + 1);
            let halt = AtomicBool::new(false);
            let core = &self.core;
            std::thread::scope(|scope| {
                for (i, w) in self.workers.iter_mut().enumerate() {
                    let (next, halt) = (&next, &halt);
                    scope.spawn(move || {
                        let mut done = 0u64;
                        while !halt.load(Ordering::Relaxed) {
                            let t = next.fetch_add(1, Ordering::Relaxed);
                            if t > end {
                                break;
                            }
                            core.traverse(w, t);
                            done += 1;
                            if let Some(p) = pause {
                                // Thread 0 keeps the clock for everyone.
                                if p.asked()
                                    || (i == 0 && done.is_multiple_of(CLOCK_EVERY) && p.due())
                                {
                                    halt.store(true, Ordering::Relaxed);
                                }
                            }
                        }
                    });
                }
            });
            // Every number taken up to `end` was run to its end.
            self.iteration = (next.into_inner() - 1).min(end);
            self.core.table.collect();
            self.discount();
            if halt.into_inner() && self.iteration < until {
                return true;
            }
        }
        false
    }
}

impl<G: Game + Sync> Solver for Mccfr<G> {
    /// One iteration on the calling thread, whatever `threads` is.
    fn iterate(&mut self) {
        self.iteration += 1;
        self.core.traverse(&mut self.workers[0], self.iteration);
        self.core.table.collect();
        self.discount();
    }

    /// `n` more iterations, on as many threads as the configuration says.
    fn run(&mut self, n: u64) {
        self.advance(self.iteration + n, None);
        self.core.table.collect();
    }

    fn iterations(&self) -> u64 {
        self.iteration
    }

    fn average_policy(&self) -> TabularPolicy {
        let (table, entries) = self.view();
        let mut sums = vec![0.0; table.slots()];
        for (set, e) in table.sets().iter().zip(&entries) {
            for (i, x) in sums[set.range()].iter_mut().enumerate() {
                *x = self.core.sums.get(e.offset + i);
            }
        }
        TabularPolicy::from_weights(&table, &sums)
    }

    fn info_sets(&self) -> usize {
        self.core.table.len()
    }

    fn nodes_touched(&self) -> u64 {
        self.stats().nodes_touched
    }
}
