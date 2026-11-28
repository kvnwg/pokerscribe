//! The depth-limited flop: Discounted CFR over every combo of both ranges on the flop's
//! betting, with the hand cut off where the flop ends.
//!
//! The ends of the flop are valued in three ways:
//!
//! - a fold: exactly, with card removal (the same per-card sums as the subgame crate);
//! - an all-in call: exactly, from the showdown equity of every pair of combos over every
//!   turn and river (`equity.rs`);
//! - a leaf, where the flop ends with chips behind (the depth limit): a player picks one of
//!   four continuation strategies for the rest of the hand (the blueprint, and the blueprint
//!   biased toward folding, toward checking or calling, and toward betting or raising). As
//!   in Modicum only the player who is not searching picks and the searching player plays
//!   the blueprint (`choices` 4 and 1); as in Pluribus both pick (4 and 4), neither seeing
//!   the other's pick. A pick is a decision of that player at the leaf; the value of a pair
//!   of picks is the share of the pot the out-of-position player ends up with under that
//!   pair of strategies, looked up by the two hands' flop buckets in the leaf table
//!   (`leaf.rs`). Where the blueprint can't follow the line, the leaf is checked down (the
//!   equity table).
//!
//! Card removal is exact everywhere: at a leaf, the bucket sums over the whole opposing
//! range are corrected combo by combo for the opposing combos that share a card.
//!
//! The same discounts and update order as the subgame crate (alpha 1.5, beta 0, gamma 2;
//! out of position first). A node can be frozen (the searching player's earlier decisions
//! on the street, when the street is solved again).

use rayon::prelude::*;

use crate::cards::combo_cards;
use crate::equity::Equity;
use crate::street::{Kind, StreetTree};
pub use subgame::Play;

const ALPHA: f64 = 1.5;
const BETA: f64 = 0.0;
const GAMMA: f64 = 2.0;

/// The continuation strategies a player can pick at a leaf: the blueprint, then biased
/// toward folding, toward checking or calling, toward betting or raising.
pub const LANES: usize = crate::leaf::CHOICES;

/// How one end of the flop is valued.
#[derive(Clone, Debug)]
pub enum Leaf {
    /// Not a leaf.
    None,
    /// Checked down: the showdown equity.
    Equity,
    /// For each pair of picks (`c0` of the out-of-position player, `c1` of the in-position
    /// player, at `c0 * choices[1] + c1`; a player with one choice plays the blueprint), the
    /// out-of-position player's share of the pot, `[oop bucket][ip bucket]` with the local
    /// bucket numbers of [`Problem`].
    Table(Vec<Vec<f64>>),
}

/// A flop to solve.
pub struct Problem<'a> {
    pub tree: &'a StreetTree,
    /// Each player's combos (lbr indices, sorted) and their weights at the start of the
    /// flop.
    pub combos: [Vec<usize>; 2],
    pub weights: [Vec<f64>; 2],
    /// The pot at the start of the flop.
    pub pot: f64,
    pub equity: &'a Equity,
    /// How each `End` node is valued (indexed by node id).
    pub leaves: Vec<Leaf>,
    /// Each combo's local flop bucket, and the number of local buckets, per player.
    pub buckets: [Vec<u32>; 2],
    pub num_buckets: [usize; 2],
    /// How many continuation strategies each player picks among at the leaves: 1 (it plays
    /// the blueprint) or [`LANES`]. Modicum: the searcher 1 and its opponent 4; Pluribus:
    /// both 4.
    pub choices: [usize; 2],
    /// Fixed strategies by node id (`[combo][action]`).
    pub frozen: Vec<Option<Vec<f64>>>,
}

#[derive(Clone, Debug, Default)]
struct Data {
    regret: Vec<f64>,
    sum: Vec<f64>,
}

pub struct Solver<'a> {
    p: &'a Problem<'a>,
    cards: [Vec<[u8; 2]>; 2],
    /// Where a combo of a player sits in the other player's list, or `u32::MAX`.
    same: [Vec<u32>; 2],
    /// For each combo of a player, the other player's combos that share a card with it.
    conflicts: [Vec<Vec<u32>>; 2],
    /// Regrets and strategy sums for decision nodes (the actor's combos).
    data: Vec<Data>,
    /// Each player's picks at the table leaves (its combos, `choices` actions), when it has
    /// more than one.
    leaf: [Vec<Data>; 2],
    total: f64,
    pub iterations: u32,
    pub parallel: bool,
}

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

/// The current strategy of `d` (`k` actions), or its average where a combo has one.
fn mixed(d: &Data, k: usize, average: bool) -> Vec<f64> {
    let mut out = vec![0.0; d.regret.len()];
    regret_match(&d.regret, k, &mut out);
    if average {
        for (s, o) in d.sum.chunks_exact(k).zip(out.chunks_exact_mut(k)) {
            let t: f64 = s.iter().sum();
            if t > 0.0 {
                for (y, x) in o.iter_mut().zip(s) {
                    *y = x / t;
                }
            }
        }
    }
    out
}

/// A strategy of both players: at every decision node (`[combo][action]`, empty elsewhere),
/// and each player's picks at the table leaves (`[combo][pick]`, empty where it has one
/// choice).
#[derive(Clone, Debug)]
pub struct Sigma {
    pub node: Vec<Vec<f64>>,
    pub leaf: [Vec<Vec<f64>>; 2],
}

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Update,
    Best,
}

/// How a terminal node is evaluated in a walk.
#[derive(Clone, Copy, PartialEq)]
enum Eval {
    Fold,
    Equity,
    Table,
}

impl<'a> Solver<'a> {
    pub fn new(p: &'a Problem<'a>) -> Solver<'a> {
        let cards = [0, 1].map(|q: usize| {
            p.combos[q]
                .iter()
                .map(|&c| combo_cards(c))
                .collect::<Vec<_>>()
        });
        let same = [0, 1].map(|q: usize| {
            p.combos[q]
                .iter()
                .map(|c| {
                    p.combos[1 - q]
                        .binary_search(c)
                        .map_or(u32::MAX, |i| i as u32)
                })
                .collect::<Vec<_>>()
        });
        let conflicts = [0, 1].map(|q: usize| {
            let mut holding: Vec<Vec<u32>> = vec![Vec::new(); 52];
            for (j, c) in cards[1 - q].iter().enumerate() {
                holding[c[0] as usize].push(j as u32);
                holding[c[1] as usize].push(j as u32);
            }
            cards[q]
                .iter()
                .map(|c| {
                    let mut list: Vec<u32> = holding[c[0] as usize]
                        .iter()
                        .chain(&holding[c[1] as usize])
                        .copied()
                        .collect();
                    list.sort_unstable();
                    list.dedup();
                    list
                })
                .collect::<Vec<_>>()
        });
        let data = p
            .tree
            .nodes
            .iter()
            .map(|node| match &node.kind {
                Kind::Decision {
                    player, actions, ..
                } => {
                    let len = p.combos[*player].len() * actions.len();
                    Data {
                        regret: vec![0.0; len],
                        sum: vec![0.0; len],
                    }
                }
                _ => Data::default(),
            })
            .collect();
        for &k in &p.choices {
            assert!(
                k == 1 || k == LANES,
                "a player picks among 1 or {LANES} at a leaf"
            );
        }
        for leaf in &p.leaves {
            if let Leaf::Table(qs) = leaf {
                assert_eq!(
                    qs.len(),
                    p.choices[0] * p.choices[1],
                    "a table per pair of picks"
                );
            }
        }
        let leaf = [0, 1].map(|q: usize| {
            p.leaves
                .iter()
                .map(|leaf| match leaf {
                    Leaf::Table(_) if p.choices[q] > 1 => {
                        let len = p.combos[q].len() * p.choices[q];
                        Data {
                            regret: vec![0.0; len],
                            sum: vec![0.0; len],
                        }
                    }
                    _ => Data::default(),
                })
                .collect::<Vec<_>>()
        });
        let mut s = Solver {
            p,
            cards,
            same,
            conflicts,
            data,
            leaf,
            total: 0.0,
            iterations: 0,
            parallel: false,
        };
        let mut met = vec![0.0; p.combos[0].len()];
        s.meets(0, &p.weights[1], &mut met);
        s.total = met.iter().zip(&p.weights[0]).map(|(m, w)| m * w).sum();
        s
    }

    fn eval_kind(&self, id: usize) -> Option<Eval> {
        match &self.p.tree.nodes[id].kind {
            Kind::Decision { .. } => None,
            Kind::Fold { .. } => Some(Eval::Fold),
            Kind::Showdown => Some(Eval::Equity),
            Kind::End => Some(match self.p.leaves[id] {
                Leaf::Table(_) => Eval::Table,
                _ => Eval::Equity,
            }),
        }
    }

    /// For each combo of `player`, the opposing reach it can meet.
    fn meets(&self, player: usize, opp: &[f64], out: &mut [f64]) {
        let o = 1 - player;
        let mut all = 0.0;
        let mut with = [0.0f64; 52];
        for (r, c) in opp.iter().zip(&self.cards[o]) {
            all += r;
            with[c[0] as usize] += r;
            with[c[1] as usize] += r;
        }
        for (i, c) in self.cards[player].iter().enumerate() {
            let s = self.same[player][i];
            let both = if s == u32::MAX { 0.0 } else { opp[s as usize] };
            out[i] = all - with[c[0] as usize] - with[c[1] as usize] + both;
        }
    }

    /// The out-of-position player's share of the pot summed over the opposing reach, for
    /// several reaches at once (one pass over the equity table): for `player` 0,
    /// `out[t][i] = sum_j W[i][j] r_t[j]`; for player 1, `out[t][j] = sum_i W[i][j] r_t[i]`.
    fn equity_sums(&self, player: usize, reaches: &[&[f64]]) -> Vec<Vec<f64>> {
        let e = self.p.equity;
        let (n0, n1) = (e.n[0], e.n[1]);
        let m = reaches.len();
        if m == 0 {
            return Vec::new();
        }
        let r32: Vec<Vec<f32>> = reaches
            .iter()
            .map(|r| r.iter().map(|&x| x as f32).collect())
            .collect();
        if player == 0 {
            let row_sums = |i: usize| -> Vec<f32> {
                let row = &e.w[i * n1..(i + 1) * n1];
                r32.iter()
                    .map(|r| row.iter().zip(r).map(|(w, x)| w * x).sum::<f32>())
                    .collect()
            };
            let rows: Vec<Vec<f32>> = if self.parallel {
                (0..n0).into_par_iter().map(row_sums).collect()
            } else {
                (0..n0).map(row_sums).collect()
            };
            (0..m)
                .map(|t| rows.iter().map(|r| r[t] as f64).collect())
                .collect()
        } else {
            const CHUNK: usize = 64;
            let chunk_sums = |c: usize| -> Vec<Vec<f32>> {
                let (lo, hi) = (c * CHUNK, ((c + 1) * CHUNK).min(n1));
                let mut acc = vec![vec![0f32; hi - lo]; m];
                for i in 0..n0 {
                    let row = &e.w[i * n1 + lo..i * n1 + hi];
                    for (a, r) in acc.iter_mut().zip(&r32) {
                        let x = r[i];
                        if x != 0.0 {
                            for (y, w) in a.iter_mut().zip(row) {
                                *y += w * x;
                            }
                        }
                    }
                }
                acc
            };
            let chunks = n1.div_ceil(CHUNK);
            let parts: Vec<Vec<Vec<f32>>> = if self.parallel {
                (0..chunks).into_par_iter().map(chunk_sums).collect()
            } else {
                (0..chunks).map(chunk_sums).collect()
            };
            (0..m)
                .map(|t| {
                    parts
                        .iter()
                        .flat_map(|p| p[t].iter().map(|&x| x as f64))
                        .collect()
                })
                .collect()
        }
    }

    /// `sum_j Q(i, j) r[j]` over the opposing combos `j` that share no card with `i`, for
    /// every combo `i` of `player`, with `Q` the leaf table `q` (out of position by in
    /// position, by local bucket) seen from `player`'s side.
    fn table_sum(&self, player: usize, q: &[f64], opp: &[f64], out: &mut [f64]) {
        let p = self.p;
        let o = 1 - player;
        let n1 = p.num_buckets[1];
        let cell = |mine: usize, theirs: usize| -> f64 {
            if player == 0 {
                q[mine * n1 + theirs]
            } else {
                q[theirs * n1 + mine]
            }
        };
        let mut by = vec![0.0; p.num_buckets[o]];
        for (r, &b) in opp.iter().zip(&p.buckets[o]) {
            by[b as usize] += r;
        }
        let t: Vec<f64> = (0..p.num_buckets[player])
            .map(|bm| {
                by.iter()
                    .enumerate()
                    .filter(|(_, &r)| r != 0.0)
                    .map(|(bo, &r)| cell(bm, bo) * r)
                    .sum()
            })
            .collect();
        for (i, slot) in out.iter_mut().enumerate() {
            let bm = p.buckets[player][i] as usize;
            let mut s = t[bm];
            for &j in &self.conflicts[player][i] {
                let r = opp[j as usize];
                if r != 0.0 {
                    s -= cell(bm, p.buckets[o][j as usize] as usize) * r;
                }
            }
            *slot = s;
        }
    }

    /// Values where each player has put in `x` more than at the start and `oop` is the
    /// out-of-position share summed over the reach met: `-x met + (pot + 2x) mine`.
    fn shared(&self, player: usize, x: f64, met: &[f64], oop: &[f64], out: &mut [f64]) {
        let pot = self.p.pot + 2.0 * x;
        for ((o, m), s) in out.iter_mut().zip(met).zip(oop) {
            let mine = if player == 0 { *s } else { m - s };
            *o = -x * m + pot * mine;
        }
    }

    /// A table leaf's values for `player`, against the opposing reach `opp` and the
    /// opponent's picks `opp_picks` (`[combo][pick]`, empty when it has one choice): with
    /// one choice, `player`'s value goes to `out`; with several, each pick's value goes to
    /// `picks_out` (`[pick][combo]`).
    fn table_leaf(
        &self,
        id: usize,
        player: usize,
        opp: &[f64],
        opp_picks: &[f64],
        out: &mut [f64],
        picks_out: &mut [f64],
    ) {
        let p = self.p;
        let Leaf::Table(qs) = &p.leaves[id] else {
            unreachable!("a table leaf")
        };
        let o = 1 - player;
        let (mine, theirs) = (p.choices[player], p.choices[o]);
        let node = &p.tree.nodes[id];
        let x = node.put[0].min(node.put[1]);
        let n = out.len();
        let mut met = vec![0.0; n];
        self.meets(player, opp, &mut met);
        // The opposing reach split by the opponent's pick.
        let parts: Vec<Vec<f64>> = if theirs == 1 {
            vec![opp.to_vec()]
        } else {
            (0..theirs)
                .map(|j| {
                    (0..opp.len())
                        .map(|h| opp[h] * opp_picks[h * theirs + j])
                        .collect()
                })
                .collect()
        };
        let mut sums = vec![0.0; n];
        let mut oop = vec![0.0; n];
        for i in 0..mine {
            oop.fill(0.0);
            for (j, part) in parts.iter().enumerate() {
                let (c0, c1) = if player == 0 { (i, j) } else { (j, i) };
                self.table_sum(player, &qs[c0 * p.choices[1] + c1], part, &mut sums);
                for (a, b) in oop.iter_mut().zip(&sums) {
                    *a += b;
                }
            }
            // The out-of-position share over the whole reach; `shared` makes it a value.
            if mine == 1 {
                self.shared(player, x, &met, &oop, out);
            } else {
                self.shared(player, x, &met, &oop, &mut picks_out[i * n..(i + 1) * n]);
            }
        }
        if mine > 1 {
            out.fill(0.0);
        }
    }

    /// The current (or average) strategy at every decision node, and each player's picks
    /// at the leaves.
    fn strategies(&self, average: bool) -> Sigma {
        let p = self.p;
        let node = p
            .tree
            .nodes
            .iter()
            .enumerate()
            .map(|(id, node)| {
                let Kind::Decision { actions, .. } = &node.kind else {
                    return Vec::new();
                };
                if let Some(f) = p.frozen.get(id).and_then(|f| f.as_ref()) {
                    return f.clone();
                }
                mixed(&self.data[id], actions.len(), average)
            })
            .collect();
        let leaf = [0, 1].map(|q: usize| {
            self.leaf[q]
                .iter()
                .map(|d| {
                    if d.regret.is_empty() {
                        Vec::new()
                    } else {
                        mixed(d, p.choices[q], average)
                    }
                })
                .collect()
        });
        Sigma { node, leaf }
    }

    /// Reach of each player at every node under `sigma`.
    fn reaches(&self, sigma: &Sigma) -> [Vec<Vec<f64>>; 2] {
        let p = self.p;
        let nodes = &p.tree.nodes;
        let mut reach: [Vec<Vec<f64>>; 2] =
            [vec![Vec::new(); nodes.len()], vec![Vec::new(); nodes.len()]];
        reach[0][0] = p.weights[0].clone();
        reach[1][0] = p.weights[1].clone();
        for id in 0..nodes.len() {
            if let Kind::Decision {
                player, children, ..
            } = &nodes[id].kind
            {
                let k = children.len();
                for (a, &c) in children.iter().enumerate() {
                    for q in 0..2 {
                        reach[q][c] = if q == *player {
                            reach[q][id]
                                .iter()
                                .enumerate()
                                .map(|(h, r)| r * sigma.node[id][h * k + a])
                                .collect()
                        } else {
                            reach[q][id].clone()
                        };
                    }
                }
            }
        }
        reach
    }

    /// The values of every terminal node for `player` (and each pick's value at the leaves
    /// when `player` has picks).
    fn terminal_values(
        &self,
        player: usize,
        sigma: &Sigma,
        reach: &[Vec<Vec<f64>>; 2],
    ) -> (Vec<Vec<f64>>, Vec<Vec<f64>>) {
        let p = self.p;
        let nodes = &p.tree.nodes;
        let o = 1 - player;
        let n = p.combos[player].len();
        let mut values = vec![Vec::new(); nodes.len()];
        let mut lane_values = vec![Vec::new(); nodes.len()];
        // Showdowns and checked-down leaves: one pass over the equity table.
        let eq_ids: Vec<usize> = (0..nodes.len())
            .filter(|&id| self.eval_kind(id) == Some(Eval::Equity))
            .collect();
        let eq_reach: Vec<&[f64]> = eq_ids.iter().map(|&id| &reach[o][id][..]).collect();
        let sums = self.equity_sums(player, &eq_reach);
        for (&id, oop) in eq_ids.iter().zip(&sums) {
            let node = &nodes[id];
            let mut met = vec![0.0; n];
            self.meets(player, &reach[o][id], &mut met);
            let mut v = vec![0.0; n];
            self.shared(player, node.put[0].min(node.put[1]), &met, oop, &mut v);
            values[id] = v;
        }
        // Folds and table leaves, node by node.
        let rest: Vec<usize> = (0..nodes.len())
            .filter(|&id| matches!(self.eval_kind(id), Some(Eval::Fold) | Some(Eval::Table)))
            .collect();
        let eval = |&id: &usize| -> (Vec<f64>, Vec<f64>) {
            let node = &nodes[id];
            let mut v = vec![0.0; n];
            match node.kind {
                Kind::Fold { folder } => {
                    let u = if folder == player {
                        -node.put[player]
                    } else {
                        p.pot + node.put[folder]
                    };
                    self.meets(player, &reach[o][id], &mut v);
                    v.iter_mut().for_each(|x| *x *= u);
                    (v, Vec::new())
                }
                _ => {
                    let mut lv = if p.choices[player] > 1 {
                        vec![0.0; p.choices[player] * n]
                    } else {
                        Vec::new()
                    };
                    let opp_picks = &sigma.leaf[o][id];
                    self.table_leaf(id, player, &reach[o][id], opp_picks, &mut v, &mut lv);
                    (v, lv)
                }
            }
        };
        let evaluated: Vec<(Vec<f64>, Vec<f64>)> = if self.parallel {
            rest.par_iter().map(eval).collect()
        } else {
            rest.iter().map(eval).collect()
        };
        for (&id, (v, lv)) in rest.iter().zip(evaluated) {
            values[id] = v;
            lane_values[id] = lv;
        }
        (values, lane_values)
    }

    /// One walk for `player`: regrets and sums (`Update`), or a best response's values
    /// against `sigma` (`Best`). Returns the root values for every combo of `player`.
    fn walk(&mut self, player: usize, sigma: &Sigma, mode: Mode, t: f64) -> Vec<f64> {
        let p = self.p;
        let nodes = &p.tree.nodes;
        let reach = self.reaches(sigma);
        let n = p.combos[player].len();
        let (mut values, lane_values) = self.terminal_values(player, sigma, &reach);
        let it = self.iterations as f64;
        let (keep_pos, keep_neg) = if it > 1.0 {
            let (a, b) = ((it - 1.0).powf(ALPHA), (it - 1.0).powf(BETA));
            (a / (a + 1.0), b / (b + 1.0))
        } else {
            (1.0, 1.0)
        };
        let weight = t.powf(GAMMA);
        for id in (0..nodes.len()).rev() {
            let frozen = p.frozen.get(id).and_then(|f| f.as_ref()).is_some();
            match &nodes[id].kind {
                Kind::End if !lane_values[id].is_empty() => {
                    // The player's pick of a continuation strategy.
                    let lv = &lane_values[id];
                    let s = &sigma.leaf[player][id];
                    let k = p.choices[player];
                    let mut v = vec![0.0; n];
                    for (h, x) in v.iter_mut().enumerate() {
                        *x = match mode {
                            Mode::Best => (0..k).map(|l| lv[l * n + h]).fold(f64::MIN, f64::max),
                            Mode::Update => (0..k).map(|l| s[h * k + l] * lv[l * n + h]).sum(),
                        };
                    }
                    if mode == Mode::Update {
                        let own = &reach[player][id];
                        let d = &mut self.leaf[player][id];
                        for h in 0..n {
                            for l in 0..k {
                                let i = h * k + l;
                                d.sum[i] += weight * own[h] * s[i];
                                let r = d.regret[i];
                                d.regret[i] = r * if r > 0.0 { keep_pos } else { keep_neg }
                                    + (lv[l * n + h] - v[h]);
                            }
                        }
                    }
                    values[id] = v;
                }
                Kind::Decision {
                    player: actor,
                    children,
                    ..
                } => {
                    let k = children.len();
                    let mut v = vec![0.0; n];
                    if *actor == player {
                        let s = &sigma.node[id];
                        for (h, x) in v.iter_mut().enumerate() {
                            *x = match mode {
                                Mode::Best if !frozen => children
                                    .iter()
                                    .map(|&c| values[c][h])
                                    .fold(f64::MIN, f64::max),
                                _ => children
                                    .iter()
                                    .enumerate()
                                    .map(|(a, &c)| s[h * k + a] * values[c][h])
                                    .sum(),
                            };
                        }
                        if mode == Mode::Update && !frozen {
                            let own = &reach[player][id];
                            let d = &mut self.data[id];
                            for h in 0..n {
                                for (a, &c) in children.iter().enumerate() {
                                    let i = h * k + a;
                                    d.sum[i] += weight * own[h] * s[i];
                                    let r = d.regret[i];
                                    d.regret[i] = r * if r > 0.0 { keep_pos } else { keep_neg }
                                        + (values[c][h] - v[h]);
                                }
                            }
                        }
                    } else {
                        for &c in children {
                            for (x, y) in v.iter_mut().zip(&values[c]) {
                                *x += y;
                            }
                        }
                    }
                    for &c in children {
                        values[c] = Vec::new();
                    }
                    values[id] = v;
                }
                _ => {}
            }
        }
        std::mem::take(&mut values[0])
    }

    /// One iteration: out of position, then in position against the new strategy.
    pub fn iterate(&mut self) {
        self.iterations += 1;
        let t = self.iterations as f64;
        for player in 0..2 {
            let sigma = self.strategies(false);
            self.walk(player, &sigma, Mode::Update, t);
        }
    }

    /// The average strategy at every decision node and each player's picks at the leaves.
    pub fn average(&self) -> Sigma {
        self.strategies(true)
    }

    /// The current strategy (the last iteration's regrets, matched).
    pub fn current(&self) -> Sigma {
        self.strategies(false)
    }

    /// What `player` gets per deal (in chips, the start pot counted as nobody's) against
    /// `sigma`: by best response when `best`, by `sigma` itself otherwise.
    fn value_against(&mut self, player: usize, sigma: &Sigma, best: bool) -> f64 {
        let mode = if best { Mode::Best } else { Mode::Update };
        let root = if best {
            self.walk(player, sigma, mode, 1.0)
        } else {
            // A plain evaluation: walk with updates turned off by a copy of the data.
            let saved = (self.data.clone(), self.leaf.clone());
            let it = self.iterations;
            let v = self.walk(player, sigma, Mode::Update, 0.0);
            (self.data, self.leaf) = saved;
            self.iterations = it;
            v
        };
        root.iter()
            .zip(&self.p.weights[player])
            .map(|(v, w)| v * w)
            .sum::<f64>()
            / self.total
    }

    /// What a best response wins playing as `player` against the average strategy, in
    /// chips per deal.
    pub fn best_response(&mut self, player: usize) -> f64 {
        let sigma = self.average();
        self.value_against(player, &sigma, true)
    }

    /// What each player wins per deal when both play the average strategy.
    pub fn values(&mut self) -> [f64; 2] {
        let sigma = self.average();
        [
            self.value_against(0, &sigma, false),
            self.value_against(1, &sigma, false),
        ]
    }

    /// Exploitability of the average strategy as a share of the pot.
    pub fn exploitability(&mut self) -> f64 {
        let sigma = self.average();
        self.exploitability_of(&sigma)
    }

    /// Exploitability of `sigma` as a share of the pot.
    pub fn exploitability_of(&mut self, sigma: &Sigma) -> f64 {
        let b0 = self.value_against(0, sigma, true);
        let b1 = self.value_against(1, sigma, true);
        (b0 + b1 - self.p.pot) / 2.0 / self.p.pot
    }
}

/// A finished flop solve.
pub struct Solution {
    /// The strategy played (the average, or the last iteration's: [`Play`]) at every
    /// decision node (`[combo][action]`, empty elsewhere).
    pub strategy: Vec<Vec<f64>>,
    /// Each player's picks at the leaves under that strategy (`[combo][pick]`).
    pub picks: [Vec<Vec<f64>>; 2],
    pub iterations: u32,
    /// Exploitability of the strategy played, as a share of the pot.
    pub exploitability: f64,
    pub elapsed_ms: f64,
}

/// Solves to `target` (share of the pot, checked at iterations 8, 12, 16, ... as the
/// subgame crate does) or `max_iterations`, whichever comes first, and plays the average
/// strategy.
pub fn solve(problem: &Problem<'_>, target: f64, max_iterations: u32, parallel: bool) -> Solution {
    solve_as(problem, target, max_iterations, parallel, Play::Average)
}

/// [`solve`], playing the average strategy or the last iteration's. The stop is the same
/// either way: the average's exploitability against `target`.
pub fn solve_as(
    problem: &Problem<'_>,
    target: f64,
    max_iterations: u32,
    parallel: bool,
    play: Play,
) -> Solution {
    let start = std::time::Instant::now();
    let mut s = Solver::new(problem);
    s.parallel = parallel;
    let mut next = 8;
    let mut last;
    loop {
        s.iterate();
        last = None;
        if s.iterations >= max_iterations {
            break;
        }
        if target > 0.0 && s.iterations >= next {
            next = s.iterations + (s.iterations / 8).max(4);
            let e = s.exploitability();
            last = Some(e);
            if e <= target {
                break;
            }
        }
    }
    let (sigma, exploitability) = match play {
        Play::Average => {
            let e = match last {
                Some(e) => e,
                None => s.exploitability(),
            };
            (s.average(), e)
        }
        Play::Final => {
            let sigma = s.current();
            let e = s.exploitability_of(&sigma);
            (sigma, e)
        }
    };
    Solution {
        strategy: sigma.node,
        picks: sigma.leaf,
        iterations: s.iterations,
        exploitability,
        elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cards::{card_mask, combo_cards, mix, NUM_COMBOS};
    use crate::equity::flop_equity;
    use crate::street::tests::{c, hand};
    use abstract_game::Menus;

    /// `n` combos not on the flop, chosen by `seed`, sorted.
    fn combos(n: usize, seed: u64, dead: u64) -> Vec<usize> {
        let mut out: Vec<usize> = (0..NUM_COMBOS)
            .filter(|&i| {
                let [a, b] = combo_cards(i);
                dead & (1 << a | 1 << b) == 0
            })
            .map(|i| (mix(seed ^ i as u64), i))
            .collect::<std::collections::BTreeMap<_, _>>()
            .into_values()
            .take(n)
            .collect();
        out.sort_unstable();
        out
    }

    struct Setup {
        tree: StreetTree,
        combos: [Vec<usize>; 2],
        equity: Equity,
    }

    fn setup() -> Setup {
        let flop = [c("Kh"), c("7d"), c("2c")];
        let dead = card_mask(&flop);
        let tree = StreetTree::build(&hand(&[]), &Menus::standard(), &[]);
        let combos = [combos(50, 1, dead), combos(50, 2, dead)];
        let equity = flop_equity(&flop, [&combos[0], &combos[1]]);
        Setup {
            tree,
            combos,
            equity,
        }
    }

    /// The table of a pair of picks (`c0` out of position, `c1` in position).
    type Table<'a> = &'a dyn Fn(usize, usize) -> Vec<f64>;

    /// The setup's flop, each player picking among `choices` at the leaves: valued by
    /// `table` (one bucket per combo), or checked down.
    fn problem<'a>(s: &'a Setup, choices: [usize; 2], table: Option<Table<'_>>) -> Problem<'a> {
        let n = [s.combos[0].len(), s.combos[1].len()];
        let leaves = s
            .tree
            .nodes
            .iter()
            .map(|node| match (&node.kind, table) {
                (Kind::End, Some(f)) => Leaf::Table(
                    (0..choices[0])
                        .flat_map(|c0| (0..choices[1]).map(move |c1| f(c0, c1)))
                        .collect(),
                ),
                (Kind::End, None) => Leaf::Equity,
                _ => Leaf::None,
            })
            .collect();
        Problem {
            tree: &s.tree,
            combos: s.combos.clone(),
            weights: [vec![1.0; n[0]], vec![1.0; n[1]]],
            pot: 200.0,
            equity: &s.equity,
            leaves,
            buckets: [(0..n[0] as u32).collect(), (0..n[1] as u32).collect()],
            num_buckets: n,
            choices,
            frozen: Vec::new(),
        }
    }

    /// The equity, plus `bonus(c0, c1)` to the out-of-position share.
    fn equity_table<'a>(
        s: &'a Setup,
        bonus: impl Fn(usize, usize) -> f64 + 'a,
    ) -> impl Fn(usize, usize) -> Vec<f64> + 'a {
        move |c0, c1| {
            s.equity
                .w
                .iter()
                .map(|&w| w as f64 + bonus(c0, c1))
                .collect()
        }
    }

    /// Each player's picks at a reached leaf, weighted by how often its combos get there
    /// (card removal included): `[pick]`, or `None` where nobody gets there.
    fn pick_shares(
        solver: &Solver<'_>,
        sigma: &Sigma,
        player: usize,
        id: usize,
    ) -> Option<Vec<f64>> {
        let p = solver.p;
        let k = p.choices[player];
        let reach = solver.reaches(sigma);
        let n = p.combos[player].len();
        let mut met = vec![0.0; n];
        solver.meets(player, &reach[1 - player][id], &mut met);
        let weight: Vec<f64> = (0..n).map(|h| reach[player][id][h] * met[h]).collect();
        let total: f64 = weight.iter().sum();
        if total < 1e-6 {
            return None;
        }
        let picks = &sigma.leaf[player][id];
        Some(
            (0..k)
                .map(|l| (0..n).map(|h| weight[h] * picks[h * k + l]).sum::<f64>() / total)
                .collect(),
        )
    }

    fn table_leaves(s: &Setup) -> Vec<usize> {
        (0..s.tree.nodes.len())
            .filter(|&id| matches!(s.tree.nodes[id].kind, Kind::End))
            .collect()
    }

    #[test]
    fn exploitability_falls_to_the_target() {
        let s = setup();
        let p = problem(&s, [1, 1], None);
        let early = solve(&p, 0.0, 10, false);
        let late = solve(&p, 0.0, 300, false);
        assert!(late.exploitability >= -1e-9);
        assert!(late.exploitability < early.exploitability);
        assert!(late.exploitability < 0.005, "{}", late.exploitability);
        let parallel = solve(&p, 0.0, 300, true);
        assert_eq!(parallel.strategy.len(), late.strategy.len());
        for (a, b) in parallel.strategy.iter().zip(&late.strategy) {
            for (x, y) in a.iter().zip(b) {
                assert!((x - y).abs() < 1e-6);
            }
        }
    }

    #[test]
    fn leaf_tables_of_the_equity_give_the_checked_down_values() {
        // One bucket per combo and every table the equity: a leaf is worth exactly what a
        // check-down is, card removal included, for both players, any reach, and whoever
        // picks.
        let s = setup();
        let plain = problem(&s, [1, 1], None);
        let f = equity_table(&s, |_, _| 0.0);
        for choices in [[LANES, 1], [1, LANES], [LANES, LANES]] {
            let tables = problem(&s, choices, Some(&f));
            let mut a = Solver::new(&plain);
            let mut b = Solver::new(&tables);
            for _ in 0..20 {
                a.iterate();
                b.iterate();
            }
            let sigma = b.strategies(false);
            let reach = b.reaches(&sigma);
            for player in 0..2 {
                let (va, _) = a.terminal_values(player, &sigma, &reach);
                let (vb, picks) = b.terminal_values(player, &sigma, &reach);
                let n = s.combos[player].len();
                for id in table_leaves(&s) {
                    let want = &va[id];
                    let close = |x: f64, y: f64| (x - y).abs() <= 1e-4 * (1.0 + y.abs());
                    if choices[player] > 1 {
                        // Every pick is worth the check-down.
                        for l in 0..LANES {
                            for h in 0..n {
                                let x = picks[id][l * n + h];
                                assert!(close(x, want[h]), "{choices:?} {x} {}", want[h]);
                            }
                        }
                    } else {
                        for (&x, &y) in vb[id].iter().zip(want) {
                            assert!(close(x, y), "{choices:?} {x} {y}");
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn a_player_picks_the_continuation_that_pays_it_most() {
        let s = setup();
        // Out of position, the raise-biased continuation pays 5% of the pot more; in
        // position, the call-biased one (the out-of-position share falls).
        let f = equity_table(&s, |c0, c1| {
            (if c0 == 3 { 0.05 } else { 0.0 }) - (if c1 == 2 { 0.05 } else { 0.0 })
        });
        for (choices, player, best) in [
            ([LANES, 1], 0, 3),
            ([1, LANES], 1, 2),
            ([LANES, LANES], 0, 3),
            ([LANES, LANES], 1, 2),
        ] {
            let p = problem(&s, choices, Some(&f));
            let mut solver = Solver::new(&p);
            for _ in 0..200 {
                solver.iterate();
            }
            let avg = solver.average();
            let mut leaves = 0;
            for id in table_leaves(&s) {
                let Some(shares) = pick_shares(&solver, &avg, player, id) else {
                    continue; // nobody gets here
                };
                leaves += 1;
                assert!(
                    shares[best] > 0.95,
                    "{choices:?} player {player}, leaf {id}: {shares:?}"
                );
            }
            assert!(leaves > 0);
        }
    }

    #[test]
    fn picks_neither_player_sees_are_a_simultaneous_game() {
        // Rock, paper, scissors on picks 1 to 3, worth 10% of the pot, and pick 0 loses to
        // all three for whoever makes it: at the equilibrium both players play 1 to 3 a
        // third of the time each (weighted over their combos), and never 0.
        let s = setup();
        let rps = |a: usize, b: usize| -> f64 {
            match (a, b) {
                (0, 0) => 0.0,
                (0, _) => -1.0,
                (_, 0) => 1.0,
                _ if a == b => 0.0,
                _ if (a % 3) + 1 == b => -1.0, // b beats a: 1 < 2 < 3 < 1
                _ => 1.0,
            }
        };
        assert_eq!(
            (rps(1, 2), rps(2, 3), rps(3, 1), rps(2, 1)),
            (-1.0, -1.0, -1.0, 1.0)
        );
        let f = equity_table(&s, |c0, c1| 0.1 * rps(c0, c1));
        let p = problem(&s, [LANES, LANES], Some(&f));
        let sol = solve(&p, 0.0, 400, false);
        assert!(sol.exploitability < 0.01, "{}", sol.exploitability);
        let mut solver = Solver::new(&p);
        for _ in 0..400 {
            solver.iterate();
        }
        let avg = solver.average();
        let reach = solver.reaches(&avg);
        // A player's share of its starting reach at `id`.
        let share = |q: usize, id: usize| {
            reach[q][id].iter().sum::<f64>() / reach[q][0].iter().sum::<f64>()
        };
        let mut leaves = 0;
        for id in table_leaves(&s) {
            // Where one player almost never gets, the other's picks hardly matter.
            if share(0, id) < 0.01 || share(1, id) < 0.01 {
                continue;
            }
            leaves += 1;
            for player in 0..2 {
                let shares = pick_shares(&solver, &avg, player, id).expect("reached");
                assert!(shares[0] < 0.01, "player {player}, leaf {id}: {shares:?}");
                for &x in &shares[1..] {
                    assert!(
                        (x - 1.0 / 3.0).abs() < 0.02,
                        "player {player}, leaf {id}: {shares:?}"
                    );
                }
            }
        }
        assert!(leaves >= 5, "{leaves}");
    }

    #[test]
    fn a_pick_that_changes_nothing_is_the_same_as_no_pick() {
        // Both pick, but the table only depends on the out-of-position pick: the solve is
        // the one where only the out-of-position player picks.
        let s = setup();
        let f = equity_table(&s, |c0, _| [0.0, -0.02, 0.01, 0.03][c0]);
        let one = problem(&s, [LANES, 1], Some(&f));
        let both = problem(&s, [LANES, LANES], Some(&f));
        let a = solve(&one, 0.0, 60, false);
        let b = solve(&both, 0.0, 60, false);
        assert!((a.exploitability - b.exploitability).abs() < 1e-9);
        for (x, y) in a.strategy.iter().zip(&b.strategy) {
            for (u, v) in x.iter().zip(y) {
                assert!((u - v).abs() < 1e-9, "{u} {v}");
            }
        }
        for (x, y) in a.picks[0].iter().zip(&b.picks[0]) {
            for (u, v) in x.iter().zip(y) {
                assert!((u - v).abs() < 1e-9, "{u} {v}");
            }
        }
        // The in-position picks stay even: no pick ever has a regret.
        assert!(a.picks[1].iter().all(|x| x.is_empty()));
        for x in b.picks[1].iter().filter(|x| !x.is_empty()) {
            assert!(
                x.iter().all(|&u| (u - 1.0 / LANES as f64).abs() < 1e-9),
                "{x:?}"
            );
        }
    }

    #[test]
    fn a_solve_can_play_the_last_iteration() {
        let s = setup();
        let f = equity_table(&s, |c0, c1| 0.02 * (c0 as f64 - c1 as f64));
        let p = problem(&s, [LANES, LANES], Some(&f));
        let average = solve(&p, 0.0, 50, false);
        let last = solve_as(&p, 0.0, 50, false, Play::Final);
        assert_eq!(last.iterations, average.iterations);
        assert_ne!(last.strategy, average.strategy);
        let mut solver = Solver::new(&p);
        for _ in 0..50 {
            solver.iterate();
        }
        let current = solver.current();
        assert_eq!(last.strategy, current.node);
        assert_eq!(last.picks, current.leaf);
        assert!((last.exploitability - solver.exploitability_of(&current)).abs() < 1e-12);
        assert!((average.exploitability - solver.exploitability()).abs() < 1e-12);
    }

    #[test]
    fn a_frozen_node_keeps_its_strategy() {
        let s = setup();
        let mut p = problem(&s, [1, 1], None);
        let Kind::Decision { actions, .. } = &s.tree.nodes[0].kind else {
            panic!("a decision")
        };
        let k = actions.len();
        let n = s.combos[0].len();
        let mut fixed = vec![0.0; n * k];
        for h in 0..n {
            fixed[h * k] = 1.0; // check
        }
        p.frozen = vec![None; s.tree.nodes.len()];
        p.frozen[0] = Some(fixed.clone());
        let sol = solve(&p, 0.0, 100, false);
        assert_eq!(sol.strategy[0], fixed);
        assert!(sol.exploitability >= -1e-9);
    }
}
