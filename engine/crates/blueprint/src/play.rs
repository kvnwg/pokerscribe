//! Playing a blueprint in the real game: `lbr::Strategy` for a trained strategy.
//!
//! A real hand can hold bets the menu does not have. The betting so far is walked through
//! the abstract game's tree, one action at a time:
//!
//! - fold, check and call are the abstract fold and check-or-call;
//! - an all-in is the menu's all-in when the menu has one there;
//! - any other raise is read as one of the two menu raises around it, with the
//!   pseudo-harmonic mapping of `abstract_game` on sizes measured as shares of the pot
//!   (the real raise in the real pot, the menu raises in the abstract pot). The mapping is
//!   random; the draw comes from a hash of the public cards and the betting up to that
//!   raise, so the same public state is always read the same way and the strategy LBR
//!   reads is the strategy that plays.
//! - a raise smaller than every menu raise is read as the smallest one ([`SmallBets::Smallest`],
//!   the mapping's own rule and the default), or, with [`SmallBets::CheckOrCall`], between
//!   a check or call and the smallest raise (the mapping with 0 first on the menu, as
//!   `abstract_game::map_size` suggests). A raise read as a check or call that ends the
//!   abstract street is answered with a call before the abstract game moves on.
//!
//! The answer is the stored strategy for the decision point reached and the hand's bucket
//! on this street, with each menu raise turned back into a real one: the same share of the
//! real pot (all in stays all in), rounded and kept inside the legal range. Raises that land
//! on the same amount are merged.
//!
//! When the abstract game cannot follow (a raise where the menu has none, or a hand that is
//! over in the abstract game but not in the real one, which happens after a real bet is
//! read as an abstract all-in), the blueprint checks or calls for the rest of the hand.
//! [`Blueprint::off_tree_share`] says how often that happened.

use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::{io, sync::Arc};

use abstract_game::{map_size, pot_fraction, AbstractGame, Bucketer, GameConfig, Next};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::{Action, Card, Config, LegalActions, State};

use crate::buckets::Buckets;
use crate::file::{decode, Layout, StrategyFile};

/// How a real raise smaller than every raise on the menu is read.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum SmallBets {
    /// As the smallest menu raise.
    #[default]
    Smallest,
    /// As a check or call, or as the smallest menu raise, by the pseudo-harmonic mapping
    /// between 0 and the smallest raise.
    CheckOrCall,
}

impl SmallBets {
    pub fn parse(name: &str) -> Option<SmallBets> {
        match name {
            "smallest" => Some(SmallBets::Smallest),
            "check-or-call" => Some(SmallBets::CheckOrCall),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            SmallBets::Smallest => "smallest",
            SmallBets::CheckOrCall => "check-or-call",
        }
    }
}

/// A trained strategy, ready to play and to be measured.
pub struct Blueprint<B> {
    game: AbstractGame<B>,
    layout: Layout,
    probs: Vec<u16>,
    /// The abstract game's first state as a real `nlhe` hand, for replaying abstract lines.
    root: State,
    /// Feeds the hash that draws the mapping of off-menu raises.
    seed: u64,
    small_bets: SmallBets,
    decisions: AtomicU64,
    off_tree: AtomicU64,
}

/// Where a public state falls in the abstract game.
struct Place {
    /// The decision point, or `None` once the abstract game can't follow the hand.
    node: Option<u32>,
    /// The abstract line as an `nlhe` hand (meaningful while `node` is `Some`).
    abs: State,
    /// The real betting, replayed.
    real: State,
}

/// SplitMix64's output step.
fn mix(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

fn action_code(action: Action) -> u64 {
    match action {
        Action::Fold => 1,
        Action::Check => 2,
        Action::Call => 3,
        Action::RaiseTo(x) => 4 + x as u64,
    }
}

fn passive(legal: &LegalActions) -> Action {
    if legal.check {
        Action::Check
    } else {
        Action::Call
    }
}

/// Up to this many actions at a decision point (fold, call and the menu's 64 sizes).
const MAX_ACTIONS: usize = 66;

impl<B: Bucketer> Blueprint<B> {
    /// A blueprint from a game and a strategy file made for it.
    pub fn new(game: AbstractGame<B>, file: StrategyFile) -> Result<Blueprint<B>, String> {
        let layout = file.check_game(&game)?;
        let c = game.config();
        let rules = Config::new(&[c.stack, c.stack], c.small_blind, c.big_blind, 0, 0)
            .map_err(|e| e.to_string())?;
        Ok(Blueprint {
            root: State::from_seed(&rules, 0),
            game,
            layout,
            probs: file.probs,
            seed: 0x5053_424C_5545_5052,
            small_bets: SmallBets::Smallest,
            decisions: AtomicU64::new(0),
            off_tree: AtomicU64::new(0),
        })
    }

    /// Another seed for the draws that map off-menu raises.
    pub fn with_translation_seed(mut self, seed: u64) -> Blueprint<B> {
        self.seed = seed;
        self
    }

    pub fn set_translation_seed(&mut self, seed: u64) {
        self.seed = seed;
    }

    /// How raises smaller than the menu's are read ([`SmallBets`]).
    pub fn with_small_bets(mut self, small_bets: SmallBets) -> Blueprint<B> {
        self.small_bets = small_bets;
        self
    }

    pub fn small_bets(&self) -> SmallBets {
        self.small_bets
    }

    pub fn game(&self) -> &AbstractGame<B> {
        &self.game
    }

    pub fn layout(&self) -> &Layout {
        &self.layout
    }

    /// The stored strategy at decision point `node` for a hand in `bucket`: one
    /// probability per action of the node, in the tree's order.
    pub fn strategy(&self, node: u32, bucket: u64) -> Vec<f64> {
        let n = self.layout.actions(node);
        let start = self.layout.start(node, bucket);
        let mut out = vec![0.0; n];
        decode(&self.probs[start..start + n], &mut out);
        out
    }

    /// Decisions answered through [`Strategy::action_probs`] so far.
    pub fn decisions(&self) -> u64 {
        self.decisions.load(Ordering::Relaxed)
    }

    /// The share of those decisions where the abstract game could not follow the hand and
    /// the blueprint checked or called.
    pub fn off_tree_share(&self) -> f64 {
        let d = self.decisions();
        if d == 0 {
            0.0
        } else {
            self.off_tree.load(Ordering::Relaxed) as f64 / d as f64
        }
    }

    /// The abstract decision point a public state is read as, or `None` when the abstract
    /// game can't follow the hand (the blueprint then checks or calls).
    pub fn decision_point(&self, public: &PublicState<'_>) -> Option<u32> {
        self.place(public).node
    }

    pub fn reset_counters(&self) {
        self.decisions.store(0, Ordering::Relaxed);
        self.off_tree.store(0, Ordering::Relaxed);
    }

    /// The uniform draw for reading the raise at `index` of the history, from the public
    /// information at that moment.
    fn draw(&self, public: &PublicState<'_>, index: usize) -> f64 {
        let history = public.history();
        let mut h = mix(self.seed);
        for m in &history[..=index] {
            h = mix(h ^ action_code(m.action) ^ (m.seat as u64) << 40);
        }
        let shown = history[index].street.board_len();
        for &card in &public.board()[..shown] {
            h = mix(h ^ (card as u64 + 1) << 48);
        }
        (h >> 11) as f64 / (1u64 << 53) as f64
    }

    /// Walks the public betting through the abstract tree.
    fn place(&self, public: &PublicState<'_>) -> Place {
        let config = Config::new(
            public.starting_stacks(),
            public.small_blind(),
            public.big_blind(),
            public.ante(),
            public.button(),
        )
        .expect("the public state's table is valid");
        let mut real = State::from_seed(&config, 0);
        let mut abs = self.root.clone();
        let tree = self.game.tree();
        let mut node = (!tree.is_empty() && public.num_players() == 2).then_some(0u32);
        let small_blind = public.small_blind_seat();
        // A real raise read as a check or call that ended the abstract street: the real
        // street goes on until the raise is answered.
        let mut answer_due = false;
        for (i, m) in public.history().iter().enumerate() {
            if answer_due {
                // A call is what the abstract game already played; anything else can't
                // be followed.
                answer_due = false;
                if m.action != Action::Call {
                    node = None;
                }
            } else if let Some(at) = node {
                let seat = if m.seat as usize == small_blind { 0 } else { 1 };
                node = if tree.node(at).player as usize != seat {
                    None
                } else {
                    let (next, read_passive) =
                        self.step(at, &mut abs, &real, m.action, || self.draw(public, i));
                    answer_due =
                        read_passive && next.is_some_and(|n| tree.node(n).street != m.street);
                    next
                };
            }
            real.apply(m.action)
                .expect("the public history is legal in its own table");
        }
        if answer_due {
            // Facing that raise now: call it.
            node = None;
        }
        if let Some(at) = node {
            if tree.node(at).street != public.street() {
                node = None;
            }
        }
        Place { node, abs, real }
    }

    /// The abstract action for a real one at decision point `at`; `abs` moves along it.
    /// Returns the next decision point, or `None` when the abstract game can't follow, and
    /// whether a real raise was read as a check or call.
    fn step(
        &self,
        at: u32,
        abs: &mut State,
        real: &State,
        action: Action,
        draw: impl FnOnce() -> f64,
    ) -> (Option<u32>, bool) {
        let edges = self.game.tree().edges(at);
        let passive_edge = || {
            edges
                .iter()
                .find(|e| matches!(e.action, Action::Check | Action::Call))
        };
        let mut read_passive = false;
        let edge = match action {
            Action::Fold => match edges.iter().find(|e| e.action == Action::Fold) {
                Some(e) => e,
                None => return (None, false),
            },
            Action::Check | Action::Call => match passive_edge() {
                Some(e) => e,
                None => return (None, false),
            },
            Action::RaiseTo(to) => {
                let mut raises = [0usize; MAX_ACTIONS];
                let mut amounts = [0u32; MAX_ACTIONS];
                let mut n = 0;
                for (i, e) in edges.iter().enumerate() {
                    if let Action::RaiseTo(x) = e.action {
                        raises[n] = i;
                        amounts[n] = x;
                        n += 1;
                    }
                }
                if n == 0 {
                    return (None, false);
                }
                let real_all_in = real.legal_actions().raise.map(|r| r.max_to) == Some(to);
                let abs_all_in = abs.legal_actions().raise.map(|r| r.max_to);
                let x = pot_fraction(real, to);
                let zero = self.small_bets == SmallBets::CheckOrCall
                    && !real_all_in
                    && x < pot_fraction(abs, amounts[0]);
                let pick = if real_all_in && abs_all_in == Some(amounts[n - 1]) {
                    n - 1
                } else if zero {
                    // 0 first on the menu: the check or call, then the smallest raise.
                    let sizes = [0.0, pot_fraction(abs, amounts[0])];
                    match map_size(&sizes, x).pick(draw()) {
                        0 => usize::MAX,
                        _ => 0,
                    }
                } else {
                    let mut sizes = [0f64; MAX_ACTIONS];
                    for k in 0..n {
                        sizes[k] = pot_fraction(abs, amounts[k]);
                    }
                    map_size(&sizes[..n], x).pick(draw())
                };
                if pick == usize::MAX {
                    read_passive = true;
                    match passive_edge() {
                        Some(e) => e,
                        None => return (None, false),
                    }
                } else {
                    &edges[raises[pick]]
                }
            }
        };
        abs.apply(edge.action)
            .expect("the tree holds legal actions");
        let next = match edge.next() {
            Next::Decision(next) => Some(next),
            Next::End(_) => None,
        };
        (next, read_passive)
    }

    /// The real action for each of the node's abstract actions.
    fn real_actions(&self, at: u32, abs: &State, real: &State, out: &mut [Action]) {
        let legal = real.legal_actions();
        let abs_all_in = abs.legal_actions().raise.map(|r| r.max_to);
        let seat = real.current_player().expect("someone is to act");
        let to_call = real.max_bet() - real.bets()[seat];
        let pot_after_call = (real.pot() + to_call) as f64;
        for (o, e) in out.iter_mut().zip(self.game.tree().edges(at)) {
            *o = match e.action {
                Action::Fold if legal.fold => Action::Fold,
                Action::Fold | Action::Check | Action::Call => passive(&legal),
                Action::RaiseTo(y) => match legal.raise {
                    None => passive(&legal),
                    Some(r) if Some(y) == abs_all_in => Action::RaiseTo(r.max_to),
                    Some(r) => {
                        let share = pot_fraction(abs, y);
                        let to = (real.max_bet() as f64 + share * pot_after_call)
                            .round()
                            .clamp(r.min_to as f64, r.max_to as f64);
                        Action::RaiseTo(to as u32)
                    }
                },
            };
        }
    }
}

impl Blueprint<Arc<Buckets>> {
    /// Loads a strategy file and the bucket tables it was trained with. `tables` overrides
    /// the directory recorded in the file. The tables' checksums must match the file's.
    pub fn load(path: &Path, tables: Option<&Path>) -> io::Result<Blueprint<Arc<Buckets>>> {
        let file = StrategyFile::load(path)?;
        let bad = |m: String| io::Error::new(io::ErrorKind::InvalidData, m);
        let spec = file
            .header
            .spec
            .clone()
            .ok_or_else(|| bad("the strategy file has no spec".into()))?;
        let dir = tables.unwrap_or(&spec.abstraction);
        let buckets = Arc::new(Buckets::load(dir)?);
        if let Some(info) = &file.header.tables {
            if info != buckets.info() {
                return Err(bad(format!(
                    "the tables in {} are not the ones the strategy was trained with",
                    dir.display()
                )));
            }
        }
        let config: GameConfig = spec.game_config().map_err(bad)?;
        let game = AbstractGame::new(config, buckets).map_err(|e| bad(e.to_string()))?;
        Blueprint::new(game, file).map_err(bad)
    }
}

impl<B: Bucketer + Sync> Strategy for Blueprint<B> {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        self.decisions.fetch_add(1, Ordering::Relaxed);
        let place = self.place(public);
        let legal = place.real.legal_actions();
        let Some(at) = place.node else {
            self.off_tree.fetch_add(1, Ordering::Relaxed);
            out.push(passive(&legal), 1.0);
            return;
        };
        let n = self.layout.actions(at);
        let mut actions = [Action::Fold; MAX_ACTIONS];
        self.real_actions(at, &place.abs, &place.real, &mut actions[..n]);
        let bucket = self.game.bucketer().bucket(hole, public.board());
        let start = self.layout.start(at, bucket);
        let mut probs = [0f64; MAX_ACTIONS];
        decode(&self.probs[start..start + n], &mut probs[..n]);
        // Merge actions that became the same real action.
        for i in 0..n {
            if probs[i] == 0.0 {
                continue;
            }
            let mut p = probs[i];
            for j in i + 1..n {
                if actions[j] == actions[i] {
                    p += probs[j];
                    probs[j] = 0.0;
                }
            }
            out.push(actions[i], p);
        }
        if out.is_empty() {
            out.push(passive(&legal), 1.0);
        }
    }

    fn action_prob_for_range(
        &self,
        public: &PublicState<'_>,
        action: Action,
        hands: &[[Card; 2]],
        out: &mut [f64],
    ) {
        let place = self.place(public);
        let Some(at) = place.node else {
            let p = if action == passive(&place.real.legal_actions()) {
                1.0
            } else {
                0.0
            };
            out.fill(p);
            return;
        };
        let n = self.layout.actions(at);
        let mut actions = [Action::Fold; MAX_ACTIONS];
        self.real_actions(at, &place.abs, &place.real, &mut actions[..n]);
        let mut mask = [false; MAX_ACTIONS];
        let mut any = false;
        for i in 0..n {
            mask[i] = actions[i] == action;
            any |= mask[i];
        }
        if !any {
            out.fill(0.0);
            return;
        }
        let uniform = mask[..n].iter().filter(|&&m| m).count() as f64 / n as f64;
        let board = public.board();
        for (hand, slot) in hands.iter().zip(out.iter_mut()) {
            let start = self
                .layout
                .start(at, self.game.bucketer().bucket(*hand, board));
            let stored = &self.probs[start..start + n];
            let (mut hit, mut sum) = (0u32, 0u32);
            for i in 0..n {
                let q = stored[i] as u32;
                sum += q;
                if mask[i] {
                    hit += q;
                }
            }
            *slot = if sum == 0 {
                uniform
            } else {
                hit as f64 / sum as f64
            };
        }
    }
}
