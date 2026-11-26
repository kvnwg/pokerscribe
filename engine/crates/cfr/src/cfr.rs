//! Full-width CFR and its variants: vanilla CFR, CFR+, Linear CFR and
//! Discounted CFR. Each iteration walks the whole tree once per player.
//!
//! Updates alternate between players, as in OpenSpiel's `CFRSolver`: on
//! iteration t, player 0's regrets are updated against the current profile,
//! player 0's current strategy is recomputed, then player 1 does the same
//! against the new profile, and so on. The current strategy is held fixed
//! during a player's pass, so an information set reached by several
//! histories sees one strategy in all of them.

use crate::game::{child, Game, Node};
use crate::policy::{regret_matching, TabularPolicy};
use crate::scratch::Scratch;
use crate::table::InfoTable;
use crate::Solver;

/// Which full-width CFR.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Variant {
    /// Zinkevich et al. 2007. Average strategy weighted by own reach only.
    Vanilla,
    /// Tammelin 2014: regrets floored at zero after each pass, average
    /// strategy weighted by iteration number.
    CfrPlus,
    /// Brown and Sandholm 2019: iteration t's regrets and average strategy
    /// contribution weighted by t. Same as `Discounted { 1, 1, 1 }`.
    Linear,
    /// Brown and Sandholm 2019: after iteration t, positive regrets are
    /// scaled by t^alpha / (t^alpha + 1), negative ones by
    /// t^beta / (t^beta + 1), and the average strategy sum by
    /// (t / (t + 1))^gamma.
    Discounted { alpha: f64, beta: f64, gamma: f64 },
}

impl Variant {
    /// DCFR with the paper's recommended parameters: alpha 1.5, beta 0,
    /// gamma 2.
    pub const DCFR: Variant = Variant::Discounted {
        alpha: 1.5,
        beta: 0.0,
        gamma: 2.0,
    };
}

/// A full-width CFR solver over any [`Game`] small enough to walk each
/// iteration.
pub struct Cfr<G: Game> {
    game: G,
    variant: Variant,
    table: InfoTable,
    regret: Vec<f64>,
    strategy_sum: Vec<f64>,
    current: Vec<f64>,
    /// Information set indices of each player, for the end-of-pass updates.
    by_player: Vec<Vec<u32>>,
    iteration: u64,
    nodes: u64,
    scratch: Scratch,
    reach: Vec<f64>,
}

impl<G: Game> Cfr<G> {
    /// Builds the solver, walking the tree once to index every information
    /// set. The current strategy starts uniform.
    pub fn new(game: G, variant: Variant) -> Self {
        let mut table = InfoTable::new();
        discover(&game, &game.root(), &mut table);
        let slots = table.slots();
        let mut current = vec![0.0; slots];
        let mut by_player = vec![Vec::new(); game.num_players()];
        for (i, set) in table.sets().iter().enumerate() {
            let r = set.range();
            let p = 1.0 / set.num_actions as f64;
            current[r].fill(p);
            by_player[set.player as usize].push(i as u32);
        }
        Cfr {
            game,
            variant,
            table,
            regret: vec![0.0; slots],
            strategy_sum: vec![0.0; slots],
            current,
            by_player,
            iteration: 0,
            nodes: 0,
            scratch: Scratch::default(),
            reach: Vec::new(),
        }
    }

    pub fn game(&self) -> &G {
        &self.game
    }

    pub fn variant(&self) -> Variant {
        self.variant
    }

    pub fn table(&self) -> &InfoTable {
        &self.table
    }

    /// Cumulative regrets, flat, laid out by [`Cfr::table`].
    pub fn regrets(&self) -> &[f64] {
        &self.regret
    }

    /// The strategy the next iteration will play.
    pub fn current_policy(&self) -> TabularPolicy {
        TabularPolicy::from_weights(&self.table, &self.current)
    }

    fn strategy_weight(&self) -> f64 {
        match self.variant {
            Variant::CfrPlus => self.iteration as f64,
            _ => 1.0,
        }
    }

    fn end_of_pass(&mut self, player: usize) {
        let t = self.iteration as f64;
        let (pos, neg, strat) = match self.variant {
            Variant::Vanilla | Variant::CfrPlus => (1.0, 1.0, 1.0),
            Variant::Linear => (t / (t + 1.0), t / (t + 1.0), t / (t + 1.0)),
            Variant::Discounted { alpha, beta, gamma } => {
                let ta = t.powf(alpha);
                let tb = t.powf(beta);
                (
                    ta / (ta + 1.0),
                    tb / (tb + 1.0),
                    (t / (t + 1.0)).powf(gamma),
                )
            }
        };
        let plus = self.variant == Variant::CfrPlus;
        let discount = !matches!(self.variant, Variant::Vanilla | Variant::CfrPlus);
        for &i in &self.by_player[player] {
            let r = self.table.set(i).range();
            if plus {
                self.regret[r.clone()]
                    .iter_mut()
                    .for_each(|x| *x = x.max(0.0));
            } else if discount {
                for x in &mut self.regret[r.clone()] {
                    *x *= if *x > 0.0 { pos } else { neg };
                }
                self.strategy_sum[r.clone()]
                    .iter_mut()
                    .for_each(|x| *x *= strat);
            }
            regret_matching(&self.regret[r.clone()], &mut self.current[r]);
        }
    }

    /// One pass for `player`. Returns `player`'s expected value under the
    /// current profile. `reach[q]` is player q's reach probability and
    /// `reach[n]` chance's. Keeping them apart (rather than one running
    /// product for everyone but `player`) multiplies in the same order as
    /// OpenSpiel, so results agree with it to rounding.
    fn traverse(&mut self, s: &G::State, player: usize, reach: &mut [f64], depth: usize) -> f64 {
        self.nodes += 1;
        let n_players = reach.len() - 1;
        match self.game.node(s) {
            Node::Terminal => self.game.utility(s, player),
            Node::Chance => {
                let mut f = self.scratch.take(depth);
                self.game.chance_outcomes(s, &mut f.chance);
                let old = reach[n_players];
                let mut v = 0.0;
                for &(a, p) in &f.chance {
                    let c = child(&self.game, s, a);
                    reach[n_players] = old * p;
                    v += p * self.traverse(&c, player, reach, depth + 1);
                }
                reach[n_players] = old;
                self.scratch.put(depth, f);
                v
            }
            Node::Player(q) => {
                // Nothing below can change any regret or strategy sum.
                if reach[..n_players].iter().all(|&r| r == 0.0) {
                    return 0.0;
                }
                let key = self.game.info_key(s);
                let idx = self
                    .table
                    .get(key)
                    .expect("information set missing from the table");
                let set = self.table.set(idx);
                let off = set.offset as usize;
                let n = set.num_actions as usize;
                let mut f = self.scratch.take(depth);
                self.game.legal_actions(s, &mut f.actions);
                debug_assert_eq!(f.actions.len(), n);
                let old = reach[q];
                let mut v = 0.0;
                f.values.clear();
                for i in 0..n {
                    let sigma = self.current[off + i];
                    let c = child(&self.game, s, f.actions[i]);
                    reach[q] = old * sigma;
                    let u = self.traverse(&c, player, reach, depth + 1);
                    f.values.push(u);
                    v += sigma * u;
                }
                reach[q] = old;
                if q == player {
                    let before: f64 = reach[..q].iter().product();
                    let after: f64 = reach[q + 1..].iter().product();
                    let cf_reach = before * after;
                    let w = self.strategy_weight() * old;
                    for i in 0..n {
                        self.regret[off + i] += cf_reach * (f.values[i] - v);
                        self.strategy_sum[off + i] += w * self.current[off + i];
                    }
                }
                self.scratch.put(depth, f);
                v
            }
        }
    }
}

impl<G: Game> Solver for Cfr<G> {
    fn iterate(&mut self) {
        self.iteration += 1;
        let root = self.game.root();
        let mut reach = std::mem::take(&mut self.reach);
        for p in 0..self.game.num_players() {
            reach.clear();
            reach.resize(self.game.num_players() + 1, 1.0);
            self.traverse(&root, p, &mut reach, 0);
            self.end_of_pass(p);
        }
        self.reach = reach;
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
        self.nodes
    }
}

/// Adds every information set below `s` to `table`.
pub(crate) fn discover<G: Game>(game: &G, s: &G::State, table: &mut InfoTable) {
    match game.node(s) {
        Node::Terminal => {}
        Node::Chance => {
            let mut outcomes = Vec::new();
            game.chance_outcomes(s, &mut outcomes);
            for (a, _) in outcomes {
                discover(game, &child(game, s, a), table);
            }
        }
        Node::Player(q) => {
            let mut actions = Vec::new();
            game.legal_actions(s, &mut actions);
            table.get_or_insert(game.info_key(s), actions.len(), q);
            for a in actions {
                discover(game, &child(game, s, a), table);
            }
        }
    }
}
