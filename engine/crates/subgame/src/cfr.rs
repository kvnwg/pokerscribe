//! Discounted CFR (Brown and Sandholm 2019; alpha 1.5, beta 0, gamma 2) over all combos
//! at once, with the players updated in turn: the same method, discounts and update order
//! as `app/solver/cfr.py`. The two give the same strategy iteration for iteration, up to
//! rounding, until a combo has two actions worth exactly the same; there the last bit of
//! rounding picks the action and the runs part (the README has the comparison).
//!
//! Regrets and strategy sums are stored `[node][combo][action]`. One update of a player
//! is one walk of the tree: on the way down the opponent's reach (range weight, times its
//! current strategy, times the chance of the river card) and the player's own reach are
//! carried along; every end of the hand is valued for all of the player's combos in one
//! pass (`game.rs`); on the way back up the player's nodes turn action values into
//! regrets.
//!
//! On a turn spot the river cards are independent of each other, so with more than one
//! thread an update is done in three steps: a walk of the turn's few nodes that only notes
//! the reaches where the river is dealt; every river card in parallel, each one walking
//! its own branches under all of those places; and the turn's nodes again, now with the
//! values of the rivers known. Each card owns its slices of the storage and the cards'
//! values are added in card order, so a run gives the same numbers with any number of
//! threads.

use std::time::Instant;

use rayon::prelude::*;

use crate::exploit::{exploitability_share, strategy_value, Policy, Strategy};
use crate::game::Game;
use crate::spot::OOP;
use crate::tree::{NodeId, NodeKind};

pub const DCFR_ALPHA: f64 = 1.5;
pub const DCFR_BETA: f64 = 0.0;
pub const DCFR_GAMMA: f64 = 2.0;

/// What the solver keeps for one decision node, both laid out `[combo][action]`.
#[derive(Clone, Debug, Default)]
struct NodeData {
    regret: Vec<f64>,
    strategy_sum: Vec<f64>,
}

/// Work space for one level of the walk.
struct Level {
    sigma: Vec<f64>,
    reach: Vec<f64>,
    action_values: Vec<f64>,
    values: Vec<f64>,
}

fn levels(game: &Game, depth: usize) -> Vec<Level> {
    let n = game.n(0).max(game.n(1));
    let k = game
        .tree
        .nodes
        .iter()
        .map(|node| node.actions().len())
        .max()
        .unwrap_or(1);
    (0..depth)
        .map(|_| Level {
            sigma: vec![0.0; n * k],
            reach: vec![0.0; n],
            action_values: vec![0.0; n * k],
            values: vec![0.0; n],
        })
        .collect()
}

/// Regret matching: each action in proportion to its positive regret, evenly when none is
/// positive. `regret` and `out` are `[combo][action]`.
fn regret_match(regret: &[f64], k: usize, out: &mut [f64]) {
    let even = 1.0 / k as f64;
    for (r, s) in regret.chunks_exact(k).zip(out.chunks_exact_mut(k)) {
        let mut total = 0.0;
        for (x, y) in r.iter().zip(s.iter_mut()) {
            *y = x.max(0.0);
            total += *y;
        }
        if total > 0.0 {
            s.iter_mut().for_each(|y| *y /= total);
        } else {
            s.fill(even);
        }
    }
}

/// What is known at one chance node between the steps of a parallel update.
#[derive(Clone, Debug, Default)]
struct Dealt {
    opp_reach: Vec<f64>,
    own_reach: Vec<f64>,
    values: Vec<f64>,
}

/// What a walk does where the river is dealt.
enum Rivers<'s> {
    /// Walks the river cards one after another, there and then.
    Inline,
    /// Only notes the reaches (and updates nothing on the way back up).
    Note(&'s mut [Dealt]),
    /// Takes the values worked out since.
    Known(&'s [Dealt]),
}

/// One player's update on iteration `t`.
struct Update<'a> {
    game: &'a Game,
    player: usize,
    /// Weight of this iteration in the average strategy: `t ^ gamma`.
    weight: f64,
    /// What old positive and negative regrets are multiplied by (1 on the first iteration).
    keep_positive: f64,
    keep_negative: f64,
    /// Levels of work space a river branch needs.
    river_depth: usize,
}

impl Update<'_> {
    /// Walks the subtree of `id`, whose storage is `data` (`data[0]` is the node's own).
    /// Writes the value of the node for every combo of the player into `out`.
    #[allow(clippy::too_many_arguments)]
    fn walk(
        &self,
        id: NodeId,
        data: &mut [NodeData],
        opp_reach: &[f64],
        own_reach: &[f64],
        out: &mut [f64],
        scratch: &mut [Level],
        rivers: &mut Rivers,
    ) {
        let game = self.game;
        let node = &game.tree.nodes[id];
        match &node.kind {
            NodeKind::Fold { .. } | NodeKind::Showdown => {
                game.terminal_values(node, self.player, opp_reach, out);
            }
            NodeKind::Decision {
                player,
                actions,
                children,
            } => {
                let k = actions.len();
                let (me, below) = data.split_first_mut().expect("storage for the node");
                let (level, deeper) = scratch.split_first_mut().expect("a level per depth");
                let Level {
                    sigma,
                    reach,
                    action_values,
                    values,
                } = level;
                let sigma = &mut sigma[..game.n(*player) * k];
                regret_match(&me.regret, k, sigma);
                // where a child's subtree sits in `below`
                let slice = |child: NodeId| {
                    let start = child - id - 1;
                    start..start + game.tree.nodes[child].size
                };
                if *player == self.player {
                    let n = out.len();
                    let reach = &mut reach[..n];
                    for (a, &child) in children.iter().enumerate() {
                        for (h, r) in reach.iter_mut().enumerate() {
                            *r = own_reach[h] * sigma[h * k + a];
                        }
                        let child_out = &mut action_values[a * n..(a + 1) * n];
                        self.walk(
                            child,
                            &mut below[slice(child)],
                            opp_reach,
                            reach,
                            child_out,
                            deeper,
                            rivers,
                        );
                    }
                    if matches!(rivers, Rivers::Note(_)) {
                        return; // the values aren't known yet
                    }
                    let regret = &mut me.regret;
                    let strategy_sum = &mut me.strategy_sum;
                    for h in 0..n {
                        let row = h * k;
                        let mut v = 0.0;
                        for a in 0..k {
                            v += sigma[row + a] * action_values[a * n + h];
                        }
                        out[h] = v;
                        let w = self.weight * own_reach[h];
                        for a in 0..k {
                            let i = row + a;
                            strategy_sum[i] += w * sigma[i];
                            let r = regret[i];
                            let kept = r * if r > 0.0 {
                                self.keep_positive
                            } else {
                                self.keep_negative
                            };
                            regret[i] = kept + (action_values[a * n + h] - v);
                        }
                    }
                } else {
                    let reach = &mut reach[..opp_reach.len()];
                    let values = &mut values[..out.len()];
                    for (a, &child) in children.iter().enumerate() {
                        for (h, r) in reach.iter_mut().enumerate() {
                            *r = opp_reach[h] * sigma[h * k + a];
                        }
                        if a == 0 {
                            self.walk(
                                child,
                                &mut below[slice(child)],
                                reach,
                                own_reach,
                                out,
                                deeper,
                                rivers,
                            );
                        } else {
                            self.walk(
                                child,
                                &mut below[slice(child)],
                                reach,
                                own_reach,
                                values,
                                deeper,
                                rivers,
                            );
                            for (o, v) in out.iter_mut().zip(values.iter()) {
                                *o += v;
                            }
                        }
                    }
                }
            }
            NodeKind::Chance { children, .. } => match rivers {
                Rivers::Note(dealt) => {
                    let d = &mut dealt[game.tree.chance_index(id)];
                    d.opp_reach.clear();
                    d.opp_reach.extend_from_slice(opp_reach);
                    d.own_reach.clear();
                    d.own_reach.extend_from_slice(own_reach);
                }
                Rivers::Known(dealt) => {
                    out.copy_from_slice(&dealt[game.tree.chance_index(id)].values)
                }
                Rivers::Inline => {
                    let (_, mut below) = data.split_first_mut().expect("storage for the node");
                    let (level, deeper) = scratch.split_first_mut().expect("a level per depth");
                    let reach = &mut level.reach[..opp_reach.len()];
                    let values = &mut level.values[..out.len()];
                    out.fill(0.0);
                    for &child in children {
                        let (branch, rest) = below.split_at_mut(game.tree.nodes[child].size);
                        below = rest;
                        self.deal(child, opp_reach, reach);
                        self.walk(
                            child,
                            branch,
                            reach,
                            own_reach,
                            values,
                            deeper,
                            &mut Rivers::Inline,
                        );
                        for (o, v) in out.iter_mut().zip(values.iter()) {
                            *o += v;
                        }
                    }
                }
            },
        }
    }

    /// The opponent's reach after the river card of branch `child`: the combos that hold
    /// the card are gone, the others are weighed by the chance of the card.
    fn deal(&self, child: NodeId, opp_reach: &[f64], reach: &mut [f64]) {
        let game = self.game;
        let runout = &game.runouts[game.tree.nodes[child].runout.expect("a dealt river")];
        for ((r, o), alive) in reach
            .iter_mut()
            .zip(opp_reach)
            .zip(&runout.alive[1 - self.player])
        {
            *r = o * alive * game.chance_weight;
        }
    }

    /// Every river card in parallel: each walks its branch under every chance node, with
    /// the reaches noted there, and the values are added up card by card.
    fn rivers(&self, data: &mut [NodeData], dealt: &mut [Dealt]) {
        let game = self.game;
        let nodes = &game.tree.nodes;
        let n = game.n(self.player);
        // Hand each river card its branches: (chance node, branch root, the branch's storage).
        let mut per_card: Vec<Vec<(usize, NodeId, &mut [NodeData])>> = (0..game.runouts.len())
            .map(|_| Vec::with_capacity(dealt.len()))
            .collect();
        let mut rest = data;
        let mut at = 0;
        for (index, &chance) in game.tree.chance_nodes.iter().enumerate() {
            for &child in nodes[chance].children() {
                let size = nodes[child].size;
                let (_, tail) = std::mem::take(&mut rest).split_at_mut(child - at);
                let (branch, tail) = tail.split_at_mut(size);
                per_card[nodes[child].runout.expect("a dealt river")].push((index, child, branch));
                rest = tail;
                at = child + size;
            }
        }
        let noted: &[Dealt] = dealt;
        let values: Vec<Vec<f64>> = per_card
            .into_par_iter()
            .map_init(
                || {
                    (
                        levels(game, self.river_depth),
                        vec![0.0; game.n(1 - self.player)],
                    )
                },
                |(scratch, reach), branches| {
                    let mut values = vec![0.0; noted.len() * n];
                    for (index, child, branch) in branches {
                        let d = &noted[index];
                        let out = &mut values[index * n..(index + 1) * n];
                        self.deal(child, &d.opp_reach, reach);
                        self.walk(
                            child,
                            branch,
                            reach,
                            &d.own_reach,
                            out,
                            scratch,
                            &mut Rivers::Inline,
                        );
                    }
                    values
                },
            )
            .collect();
        for (index, d) in dealt.iter_mut().enumerate() {
            d.values.clear();
            d.values.resize(n, 0.0);
            for card in &values {
                for (o, v) in d.values.iter_mut().zip(&card[index * n..(index + 1) * n]) {
                    *o += v;
                }
            }
        }
    }
}

/// The solver's state for one spot. `iterate()` runs one iteration (both players); the
/// average strategy and its exploitability can be asked at any time.
pub struct Solver<'a> {
    game: &'a Game,
    data: Vec<NodeData>,
    scratch: Vec<Level>,
    root_values: [Vec<f64>; 2],
    ones: [Vec<f64>; 2],
    dealt: Vec<Dealt>,
    depth: usize,
    pub iterations: u32,
    /// Walk the river cards of a turn spot on the current rayon pool.
    pub parallel: bool,
}

impl<'a> Solver<'a> {
    pub fn new(game: &'a Game) -> Solver<'a> {
        let data = game
            .tree
            .nodes
            .iter()
            .map(|node| match node.player() {
                Some(p) => {
                    let len = game.n(p) * node.actions().len();
                    NodeData {
                        regret: vec![0.0; len],
                        strategy_sum: vec![0.0; len],
                    }
                }
                None => NodeData::default(),
            })
            .collect();
        let depth = game.tree.depth();
        Solver {
            game,
            data,
            scratch: levels(game, depth),
            root_values: [vec![0.0; game.n(0)], vec![0.0; game.n(1)]],
            ones: [vec![1.0; game.n(0)], vec![1.0; game.n(1)]],
            dealt: vec![Dealt::default(); game.tree.chance_nodes.len()],
            depth,
            iterations: 0,
            parallel: false,
        }
    }

    pub fn game(&self) -> &'a Game {
        self.game
    }

    /// One iteration: OOP's update, then IP's against OOP's new strategy.
    pub fn iterate(&mut self) {
        self.iterations += 1;
        let t = self.iterations as f64;
        let (keep_positive, keep_negative) = if self.iterations > 1 {
            let (a, b) = ((t - 1.0).powf(DCFR_ALPHA), (t - 1.0).powf(DCFR_BETA));
            (a / (a + 1.0), b / (b + 1.0))
        } else {
            (1.0, 1.0)
        };
        let game = self.game;
        for player in 0..2 {
            let update = Update {
                game,
                player,
                weight: t.powf(DCFR_GAMMA),
                keep_positive,
                keep_negative,
                river_depth: self.depth, // a river branch is never deeper than the whole tree
            };
            let opp_reach = &game.weights[1 - player];
            let (own_reach, out) = (&self.ones[player], &mut self.root_values[player]);
            if self.parallel && !self.dealt.is_empty() {
                let mut note = Rivers::Note(&mut self.dealt);
                update.walk(
                    0,
                    &mut self.data,
                    opp_reach,
                    own_reach,
                    out,
                    &mut self.scratch,
                    &mut note,
                );
                update.rivers(&mut self.data, &mut self.dealt);
                let mut known = Rivers::Known(&self.dealt);
                update.walk(
                    0,
                    &mut self.data,
                    opp_reach,
                    own_reach,
                    out,
                    &mut self.scratch,
                    &mut known,
                );
            } else {
                update.walk(
                    0,
                    &mut self.data,
                    opp_reach,
                    own_reach,
                    out,
                    &mut self.scratch,
                    &mut Rivers::Inline,
                );
            }
        }
    }

    /// The average strategy at every decision node. A combo that never reached a node by
    /// its own choices has no average there: it gets the current strategy.
    pub fn average(&self) -> Strategy {
        let probs = self
            .game
            .tree
            .nodes
            .iter()
            .enumerate()
            .map(|(id, node)| match node.player() {
                Some(_) => {
                    let mut out = vec![0.0; self.data[id].regret.len()];
                    self.probs(id, &mut out);
                    out
                }
                None => Vec::new(),
            })
            .collect();
        Strategy { probs }
    }

    /// Exploitability of the average strategy, as a share of the pot.
    pub fn exploitability(&self) -> f64 {
        exploitability_share(self.game, self, self.parallel)
    }

    /// What (OOP, IP) win, in chips per hand, when both play the average strategy.
    pub fn values(&self) -> [f64; 2] {
        let oop = strategy_value(self.game, self, OOP, self.parallel);
        [oop, self.game.spot.pot - oop]
    }
}

/// The running average strategy, read straight from the solver's sums.
impl Policy for Solver<'_> {
    fn probs(&self, node: NodeId, out: &mut [f64]) {
        let data = &self.data[node];
        let k = self.game.tree.nodes[node].actions().len();
        regret_match(&data.regret, k, out);
        for (sum, s) in data
            .strategy_sum
            .chunks_exact(k)
            .zip(out.chunks_exact_mut(k))
        {
            let total: f64 = sum.iter().sum();
            if total > 0.0 {
                for (y, x) in s.iter_mut().zip(sum) {
                    *y = x / total;
                }
            }
        }
    }
}

/// When to stop. The first of the three that is reached ends the solve; at least one
/// iteration always runs.
#[derive(Clone, Debug, PartialEq)]
pub struct SolveConfig {
    /// Stop when the average strategy's exploitability is at or under this share of the
    /// pot (0.002 is 0.2%). 0 turns the target off.
    pub target_exploitability: f64,
    pub max_iterations: Option<u32>,
    pub time_ms: Option<f64>,
    /// Threads for the river cards of a turn spot. 1 walks them one after another.
    pub threads: usize,
}

impl Default for SolveConfig {
    fn default() -> SolveConfig {
        SolveConfig {
            target_exploitability: 0.002,
            max_iterations: Some(10_000),
            time_ms: None,
            threads: 1,
        }
    }
}

/// A solved spot.
#[derive(Clone, Debug)]
pub struct Solution {
    /// The average strategy.
    pub strategy: Strategy,
    pub iterations: u32,
    /// From the start of the solve to the finished strategy, the solver's own tables and
    /// every exploitability check included.
    pub elapsed_ms: f64,
    /// Exploitability of `strategy`, as a share of the pot.
    pub exploitability: f64,
    /// (iteration, exploitability in percent of the pot) at every check.
    pub trace: Vec<(u32, f64)>,
    /// The exploitability is at or under the target.
    pub converged: bool,
    /// What (OOP, IP) win, in chips per hand, when both play `strategy`.
    pub values: [f64; 2],
}

/// The first iteration the exploitability is checked on, and how the gap to the next
/// check grows. A check costs about as much as an iteration.
const FIRST_CHECK: u32 = 8;

fn next_check_after(iteration: u32) -> u32 {
    iteration + (iteration / 8).max(4)
}

/// Solves a game on the current thread (and, when `config.threads` is over 1 on a turn
/// spot, on a rayon pool of that many threads).
///
/// Panics when the config sets no limit at all: the solve would never end.
pub fn solve(game: &Game, config: &SolveConfig) -> Solution {
    assert!(
        config.target_exploitability > 0.0
            || config.max_iterations.is_some()
            || config.time_ms.is_some(),
        "give a target exploitability, max_iterations or a time budget"
    );
    if config.threads > 1 && game.is_turn() {
        if let Ok(pool) = rayon::ThreadPoolBuilder::new()
            .num_threads(config.threads)
            .build()
        {
            return pool.install(|| solve_here(game, config, true));
        }
    }
    solve_here(game, config, false)
}

fn solve_here(game: &Game, config: &SolveConfig, parallel: bool) -> Solution {
    let start = Instant::now();
    let ms = |since: Instant| since.elapsed().as_secs_f64() * 1000.0;
    let mut solver = Solver::new(game);
    solver.parallel = parallel;
    let target = config.target_exploitability;
    let mut trace = Vec::new();
    let mut next_check = FIRST_CHECK;
    let mut spent_iterating = 0.0;
    let mut last: Option<f64>;
    loop {
        let t0 = Instant::now();
        solver.iterate();
        spent_iterating += ms(t0);
        last = None;
        if config
            .max_iterations
            .is_some_and(|m| solver.iterations >= m)
        {
            break;
        }
        if target > 0.0 && solver.iterations >= next_check {
            next_check = next_check_after(solver.iterations);
            let e = solver.exploitability();
            trace.push((solver.iterations, 100.0 * e));
            last = Some(e);
            if e <= target {
                break;
            }
        }
        // Another iteration, then the last check (about one more), must still fit.
        if let Some(budget) = config.time_ms {
            if ms(start) + 3.0 * spent_iterating / solver.iterations as f64 > budget {
                break;
            }
        }
    }
    let exploitability = last.unwrap_or_else(|| {
        let e = solver.exploitability();
        trace.push((solver.iterations, 100.0 * e));
        e
    });
    let strategy = solver.average();
    let elapsed_ms = ms(start);
    Solution {
        strategy,
        iterations: solver.iterations,
        elapsed_ms,
        exploitability,
        trace,
        converged: target > 0.0 && exploitability <= target,
        values: solver.values(),
    }
}
