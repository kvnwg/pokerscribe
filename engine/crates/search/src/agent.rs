//! The search agent: the blueprint before the flop, then a solve of every street from its
//! start, with both players' ranges there worked out from the betting.
//!
//! **Ranges.** Both players start the hand with every combo at weight 1. Each action
//! multiplies the actor's weights by the probability of that action for each combo, and
//! each board card removes the combos that hold it. The opponent's probabilities are the
//! blueprint's: the probability of the exact real action, or, when no live combo would make
//! it (an off-menu size), of the menu action the blueprint reads it as (the same
//! pseudo-harmonic mapping it plays with); when even that is 0 for every combo the weights
//! are kept. The searching player's own probabilities are those it really played with: the
//! blueprint's before the flop, and afterwards its own solved strategy at that decision, so
//! the hand it holds always stays in its range (with the blueprint's numbers it would drop
//! out whenever the search plays something the blueprint never would).
//!
//! **Solving and re-solving.** At a decision on a street, the street is solved from its
//! start with the ranges there. Later on the same street the same solve is used while the
//! opponent's actions are in its tree (a raise within [`crate::street::tolerance`] of a
//! size in the tree counts as that size). When the opponent makes an action that is not in
//! it, the action is added to the tree and the street is solved again from its start, with
//! the searcher's earlier decisions on this street fixed to the strategy it played them with
//! (for every combo), so only the opponent's play and the searcher's later play can change.
//! This is unsafe re-solving (as Pluribus re-solves each betting round): the opponent's
//! range at the start of the street is taken as given, with no gadget holding the
//! opponent's values to what it could get before.
//!
//! Every solve depends only on the public state, so it is cached by the public betting, and
//! a match or an LBR run repeats exactly.

use std::collections::{HashMap, VecDeque};
use std::path::Path;
use std::sync::{Arc, Mutex};

use abstract_game::{Bucketer, Menus};
use blueprint::{Blueprint, Buckets};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::{Action, Card, Config, Street};

use crate::cards::{blocked, card_mask, combo_cards, combo_index, NUM_COMBOS};
use crate::equity::{flop_equity, Equity};
use crate::leaf::LeafTables;
use crate::real::{board_at, config, key, rebuild, street_start};
use crate::solve::{solve_street, Inputs, Settings, StreetSolve};
use crate::street::{find_action, legalize, legalize_with, player_of, Extra, Kind, StreetTree};

/// A map that forgets its oldest entries past a size.
struct Bounded<V> {
    map: HashMap<String, V>,
    order: VecDeque<String>,
    cap: usize,
}

impl<V: Clone> Bounded<V> {
    fn new(cap: usize) -> Self {
        Bounded {
            map: HashMap::new(),
            order: VecDeque::new(),
            cap,
        }
    }
    fn get(&self, k: &str) -> Option<V> {
        self.map.get(k).cloned()
    }
    fn insert(&mut self, k: String, v: V) {
        if self.map.insert(k.clone(), v).is_none() {
            self.order.push_back(k);
            while self.order.len() > self.cap {
                if let Some(old) = self.order.pop_front() {
                    self.map.remove(&old);
                }
            }
        }
    }
}

struct Caches {
    ranges: Bounded<Arc<[Vec<f64>; 2]>>,
    solves: Bounded<Arc<StreetSolve>>,
    equity: Bounded<Arc<Equity>>,
}

/// One solve the agent ran, for timing reports.
#[derive(Clone, Debug)]
pub struct SolveRecord {
    pub street: Street,
    pub ms: f64,
    pub iterations: u32,
    pub exploitability: f64,
    pub combos: [usize; 2],
    pub resolve: bool,
    pub solver_nodes: usize,
}

/// Where a decision falls: the solve and its node, and the searcher's player there.
#[derive(Clone)]
pub struct Plan {
    pub solve: Arc<StreetSolve>,
    pub node: usize,
    pub player: usize,
}

pub struct SearchAgent<B = Arc<Buckets>> {
    pub bp: Arc<Blueprint<B>>,
    pub leaf: Option<Arc<LeafTables>>,
    pub settings: Settings,
    menus: Menus,
    caches: Mutex<Caches>,
    records: Mutex<Vec<SolveRecord>>,
    /// Keep a record of every solve (for the timing report).
    pub keep_records: bool,
}

/// How many entries each cache keeps.
pub const CACHE_ENTRIES: usize = 1024;

impl SearchAgent<Arc<Buckets>> {
    /// The agent for a strategy file and its leaf tables (`<file>.leaf`, when there).
    pub fn load(strategy: &Path, settings: Settings) -> std::io::Result<SearchAgent> {
        SearchAgent::load_with(strategy, None, settings)
    }

    /// The same, with the bucket tables from `tables` instead of the folder the strategy
    /// file names (a file trained on another machine; the tables must still be the ones it
    /// was trained with).
    pub fn load_with(
        strategy: &Path,
        tables: Option<&Path>,
        settings: Settings,
    ) -> std::io::Result<SearchAgent> {
        let bp = Arc::new(Blueprint::load(strategy, tables)?);
        SearchAgent::with_leaf_tables(bp, strategy, settings)
    }

    /// The agent on a loaded blueprint, with the leaf tables next to its strategy file
    /// (`<file>.leaf`, when there), checked against the file.
    pub fn with_leaf_tables(
        bp: Arc<Blueprint<Arc<Buckets>>>,
        strategy: &Path,
        settings: Settings,
    ) -> std::io::Result<SearchAgent> {
        let leaf_path = leaf_path(strategy);
        let leaf = if leaf_path.exists() {
            // The header first: a table for another file, or with too few lanes, is refused
            // before gigabytes load.
            let header = LeafTables::read_header(&leaf_path)?;
            crate::solve::check_lanes(header.lanes, settings.leaf_choice).map_err(|e| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!("{}: {e}", leaf_path.display()),
                )
            })?;
            let hash = crate::leaf::file_hash(strategy)?;
            if header.strategy_hash != hash {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!(
                        "{} was built from another strategy file",
                        leaf_path.display()
                    ),
                ));
            }
            Some(Arc::new(LeafTables::load(&leaf_path)?))
        } else {
            None
        };
        Ok(SearchAgent::new(bp, leaf, settings))
    }
}

impl<B: Bucketer + Sync + Send> SearchAgent<B> {
    pub fn new(
        bp: Arc<Blueprint<B>>,
        leaf: Option<Arc<LeafTables>>,
        settings: Settings,
    ) -> SearchAgent<B> {
        if let Some(tables) = &leaf {
            if let Err(e) = crate::solve::check_lanes(tables.header.lanes, settings.leaf_choice) {
                panic!("{e}");
            }
        }
        let menus = bp.game().config().menus.clone();
        SearchAgent {
            bp,
            leaf,
            settings,
            menus,
            caches: Mutex::new(Caches {
                ranges: Bounded::new(CACHE_ENTRIES),
                solves: Bounded::new(CACHE_ENTRIES),
                equity: Bounded::new(64),
            }),
            records: Mutex::new(Vec::new()),
            keep_records: false,
        }
    }

    pub fn take_records(&self) -> Vec<SolveRecord> {
        std::mem::take(&mut self.records.lock().unwrap())
    }

    /// Forget every cached range and solve.
    pub fn clear(&self) {
        let mut c = self.caches.lock().unwrap();
        c.ranges = Bounded::new(CACHE_ENTRIES);
        c.solves = Bounded::new(CACHE_ENTRIES);
        c.equity = Bounded::new(64);
    }

    /// Both seats' weights over the 1,326 combos at the start of `street`, for the
    /// agent searching in seat `me`.
    pub fn street_ranges(
        &self,
        public: &PublicState<'_>,
        street: Street,
        me: usize,
    ) -> Arc<[Vec<f64>; 2]> {
        let history = public.history();
        let len = street_start(history, street);
        let k = format!("R{me}|{}", key(public, len, street));
        if let Some(r) = self.caches.lock().unwrap().ranges.get(&k) {
            return r;
        }
        let r = Arc::new(self.compute_ranges(public, street, me));
        self.caches.lock().unwrap().ranges.insert(k, Arc::clone(&r));
        r
    }

    fn compute_ranges(&self, public: &PublicState<'_>, street: Street, me: usize) -> [Vec<f64>; 2] {
        if street == Street::Preflop {
            return [vec![1.0; NUM_COMBOS], vec![1.0; NUM_COMBOS]];
        }
        let prev = match street {
            Street::Flop => Street::Preflop,
            Street::Turn => Street::Flop,
            _ => Street::Turn,
        };
        let mut r = (*self.street_ranges(public, prev, me)).clone();
        let history = public.history();
        let cfg = config(public);
        let (from, to) = (street_start(history, prev), street_start(history, street));
        for i in from..to {
            self.update(&cfg, public, i, me, &mut r);
        }
        let mask = card_mask(board_at(public.board(), street));
        for w in r.iter_mut() {
            for (c, x) in w.iter_mut().enumerate() {
                if blocked(c, mask) {
                    *x = 0.0;
                }
            }
        }
        r
    }

    /// Multiplies the weights of the actor of history move `i` by its probabilities.
    fn update(
        &self,
        cfg: &Config,
        public: &PublicState<'_>,
        i: usize,
        me: usize,
        r: &mut [Vec<f64>; 2],
    ) {
        let m = public.history()[i];
        let seat = m.seat as usize;
        let state = rebuild(cfg, &public.history()[..i], public.board());
        let before = PublicState::new(&state);
        let mask = card_mask(before.board());
        let w = &mut r[seat];
        let live: Vec<usize> = (0..NUM_COMBOS)
            .filter(|&c| w[c] > 0.0 && !blocked(c, mask))
            .collect();
        if live.is_empty() {
            return;
        }
        let mut p = vec![0.0; live.len()];
        if seat == me && before.street() != Street::Preflop {
            if let Some(plan) = self.plan(&before) {
                let node = &plan.solve.tree.nodes[plan.node];
                let Kind::Decision { actions, .. } = &node.kind else {
                    return;
                };
                let Some(a) = find_action(&node.state, actions, m.action) else {
                    return;
                };
                let k = actions.len();
                let list = &plan.solve.combos[plan.player];
                let probs = &plan.solve.strategy[plan.node];
                for (slot, &c) in p.iter_mut().zip(&live) {
                    *slot = match list.binary_search(&c) {
                        Ok(pos) => probs[pos * k + a] as f64,
                        Err(_) => 0.0,
                    };
                }
                for (&c, &x) in live.iter().zip(&p) {
                    w[c] *= x;
                }
                return;
            }
            // The blueprint played this decision: fall through to its probabilities.
        }
        let hands: Vec<[Card; 2]> = live.iter().map(|&c| combo_cards(c)).collect();
        self.bp
            .action_prob_for_range(&before, m.action, &hands, &mut p);
        let mass = |p: &[f64]| live.iter().zip(p).map(|(&c, x)| w[c] * x).sum::<f64>();
        if mass(&p) <= 0.0 {
            self.bp
                .read_action_prob_for_range(&before, m.action, &hands, &mut p);
            if mass(&p) <= 0.0 {
                return; // nothing explains the action: keep the range
            }
        }
        for (&c, &x) in live.iter().zip(&p) {
            w[c] *= x;
        }
    }

    fn equity(&self, flop: &[Card], combos: [&[usize]; 2]) -> Arc<Equity> {
        let mut k = String::new();
        for c in flop {
            k.push_str(&format!("{c}."));
        }
        let h = combos
            .iter()
            .flat_map(|l| l.iter())
            .fold(0xcbf2_9ce4_8422_2325u64, |h, &c| {
                (h ^ c as u64).wrapping_mul(0x0100_0000_01b3)
            });
        k.push_str(&format!("{h:x}/{}/{}", combos[0].len(), combos[1].len()));
        if let Some(e) = self.caches.lock().unwrap().equity.get(&k) {
            return e;
        }
        let e = Arc::new(flop_equity(flop, combos));
        self.caches.lock().unwrap().equity.insert(k, Arc::clone(&e));
        e
    }

    /// The solve and node for the decision at `public` (the player to act searching), or
    /// `None` before the flop or when the street can't be solved (the blueprint plays).
    pub fn plan(&self, public: &PublicState<'_>) -> Option<Plan> {
        let street = public.street();
        if street == Street::Preflop || public.num_players() != 2 {
            return None;
        }
        let me = public.current_player()?;
        let history = public.history();
        let start = street_start(history, street);
        let actions: Vec<Action> = history[start..].iter().map(|m| m.action).collect();
        let mine: Vec<usize> = (0..actions.len())
            .filter(|&k| history[start + k].seat as usize == me)
            .chain(std::iter::once(actions.len()))
            .collect();
        let cfg = config(public);
        let start_state = rebuild(&cfg, &history[..start], public.board());
        let player = player_of(&start_state, me);
        let mut prev: Option<Arc<StreetSolve>> = None;
        let mut frozen: Vec<(Vec<Action>, Vec<f32>)> = Vec::new();
        for &k in &mine {
            let ck = format!("S{me}|{}", key(public, start + k, street));
            let cached = self.caches.lock().unwrap().solves.get(&ck);
            let solve = match cached {
                Some(s) => s,
                None => {
                    let s = match &prev {
                        Some(p) if p.tree.walk(&actions[..k]).is_ok() => Arc::clone(p),
                        _ => {
                            let extras = self.extras_for(
                                &start_state,
                                prev.as_ref().map(|p| p.extras.clone()).unwrap_or_default(),
                                &actions[..k],
                            )?;
                            let ranges = self.street_ranges(public, street, me);
                            let bb = start_state.big_blind_seat();
                            let weights = [&ranges[bb][..], &ranges[1 - bb][..]];
                            let board = board_at(public.board(), street);
                            let inputs = Inputs {
                                start: &start_state,
                                board,
                                weights,
                                extras,
                                frozen: frozen.clone(),
                                searcher: player,
                            };
                            let eq = |f: &[Card], c: [&[usize]; 2]| self.equity(f, c);
                            let solved = solve_street(
                                &*self.bp,
                                self.leaf.as_deref(),
                                &self.menus,
                                &self.settings,
                                &inputs,
                                Some(&eq),
                            )
                            .ok()?;
                            if self.keep_records {
                                self.records.lock().unwrap().push(SolveRecord {
                                    street,
                                    ms: solved.ms,
                                    iterations: solved.iterations,
                                    exploitability: solved.exploitability,
                                    combos: [solved.combos[0].len(), solved.combos[1].len()],
                                    resolve: prev.is_some(),
                                    solver_nodes: solved.solver_nodes,
                                });
                            }
                            Arc::new(solved)
                        }
                    };
                    self.caches
                        .lock()
                        .unwrap()
                        .solves
                        .insert(ck, Arc::clone(&s));
                    s
                }
            };
            if k < actions.len() {
                let node = solve.tree.walk(&actions[..k]).ok()?;
                frozen.push((
                    solve.tree.nodes[node].path.clone(),
                    solve.strategy[node].clone(),
                ));
            }
            prev = Some(solve);
        }
        let solve = prev?;
        let node = solve.tree.walk(&actions).ok()?;
        match &solve.tree.nodes[node].kind {
            Kind::Decision { player: p, .. } if *p == player => Some(Plan {
                solve,
                node,
                player,
            }),
            _ => None,
        }
    }

    /// `extras` plus every action of `actions` (the street so far) the tree doesn't have.
    fn extras_for(
        &self,
        start: &nlhe::State,
        mut extras: Vec<Extra>,
        actions: &[Action],
    ) -> Option<Vec<Extra>> {
        for _ in 0..=actions.len() {
            let tree = StreetTree::build(start, &self.menus, &extras);
            match tree.walk(actions) {
                Ok(_) => return Some(extras),
                Err(j) => {
                    let at = tree.walk(&actions[..j]).ok()?;
                    let node = &tree.nodes[at];
                    if !matches!(node.kind, Kind::Decision { .. }) {
                        return None;
                    }
                    extras.push(Extra {
                        path: node.path.clone(),
                        action: legalize(&node.state, actions[j]),
                    });
                }
            }
        }
        None
    }

    /// The searcher's action probabilities with `hole` at `plan`, as real actions legal
    /// at `public`; `false` when the hand is not in the solve.
    fn plan_probs(
        &self,
        plan: &Plan,
        public: &PublicState<'_>,
        hole: [Card; 2],
        out: &mut ActionProbs,
    ) -> bool {
        let c = combo_index(hole[0], hole[1]);
        let Ok(pos) = plan.solve.combos[plan.player].binary_search(&c) else {
            return false;
        };
        let Kind::Decision { actions, .. } = &plan.solve.tree.nodes[plan.node].kind else {
            return false;
        };
        let legal = public.legal_actions();
        let row = plan.solve.row(plan.node, pos);
        let mut merged: Vec<(Action, f64)> = Vec::with_capacity(actions.len());
        for (&a, &p) in actions.iter().zip(row) {
            if p <= 0.0 {
                continue;
            }
            let a = legalize_with(&legal, a);
            match merged.iter_mut().find(|(b, _)| *b == a) {
                Some(slot) => slot.1 += p as f64,
                None => merged.push((a, p as f64)),
            }
        }
        let total: f64 = merged.iter().map(|x| x.1).sum();
        if total <= 0.0 {
            return false;
        }
        for (a, p) in merged {
            out.push(a, p / total);
        }
        true
    }
}

/// Where the leaf tables of a strategy file are kept.
pub fn leaf_path(strategy: &Path) -> std::path::PathBuf {
    let mut s = strategy.as_os_str().to_owned();
    s.push(".leaf");
    s.into()
}

impl<B: Bucketer + Sync + Send> Strategy for SearchAgent<B> {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        if let Some(plan) = self.plan(public) {
            if self.plan_probs(&plan, public, hole, out) {
                return;
            }
            out.clear();
        }
        self.bp.action_probs(public, hole, out)
    }

    fn action_prob_for_range(
        &self,
        public: &PublicState<'_>,
        action: Action,
        hands: &[[Card; 2]],
        out: &mut [f64],
    ) {
        let Some(plan) = self.plan(public) else {
            return self.bp.action_prob_for_range(public, action, hands, out);
        };
        let mut probs = ActionProbs::new();
        let mut missing = Vec::new();
        for (i, (hand, slot)) in hands.iter().zip(out.iter_mut()).enumerate() {
            probs.clear();
            if self.plan_probs(&plan, public, *hand, &mut probs) {
                *slot = probs.prob(action);
            } else {
                missing.push(i);
            }
        }
        if !missing.is_empty() {
            let hs: Vec<[Card; 2]> = missing.iter().map(|&i| hands[i]).collect();
            let mut p = vec![0.0; hs.len()];
            self.bp.action_prob_for_range(public, action, &hs, &mut p);
            for (&i, x) in missing.iter().zip(p) {
                out[i] = x;
            }
        }
    }
}
