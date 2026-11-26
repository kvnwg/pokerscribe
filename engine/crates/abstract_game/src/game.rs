//! The abstract game: heads-up No-Limit Hold'em with the menus' bets only and hands
//! grouped by a [`Bucketer`], as a [`cfr::Game`] the CFR library can train on.
//!
//! - Player 0 is the small blind (the button, first to act before the flop) and player 1
//!   the big blind (first to act after it).
//! - Chance deals nine cards one at a time at the start: the small blind's two, the big
//!   blind's two, then the board. The board cards stay face down until their street.
//!   Dealing them up front changes nothing for a sampling solver and keeps chance in one
//!   place.
//! - The betting follows the [`BettingTree`], which was built by playing the menus
//!   through `nlhe`: every action in it is legal in the real game, and every ending holds
//!   the payoffs `nlhe` gives for it. A state is a place in that tree plus the cards, 88
//!   bytes that are copied, never boxed. [`AbstractGame::replay`] gives the same position
//!   as a real `nlhe::State`.
//! - Payoffs are in big blinds. The eval crate, behind `nlhe`'s `HandRanker` trait
//!   ([`EvalRanker`]), says who wins a showdown.

use std::fmt;

use cfr::{Action, Game, InfoKey, Node, Rng};
use nlhe::{Card, Chips, Config, ConfigError, Deal, DealError, HandRanker, State, Street};

use crate::bucket::Bucketer;
use crate::mapping::{map_size, Mapping};
use crate::menu::{pot_fraction, MenuError, Menus};
use crate::ranker::EvalRanker;
use crate::size::{count, TreeSize};
use crate::tree::{BettingTree, Next, Showdown, MAX_DECISIONS};

/// The fold action.
pub const FOLD: Action = 0;
/// Check when there is nothing to call, call otherwise.
pub const CALL: Action = 1;

/// The action "raise (or bet) to this many chips": the total bet for the street, as in
/// `nlhe::Action::RaiseTo`.
pub const fn raise_to(chips: Chips) -> Action {
    chips + 2
}

/// The chips a raise action goes to, or `None` for fold and call.
pub const fn raise_amount(action: Action) -> Option<Chips> {
    if action >= 2 {
        Some(action - 2)
    } else {
        None
    }
}

/// An `nlhe` action as the abstract game numbers it: [`FOLD`], [`CALL`] for a check or a
/// call, or [`raise_to`].
pub const fn encode(action: nlhe::Action) -> Action {
    match action {
        nlhe::Action::Fold => FOLD,
        nlhe::Action::Check | nlhe::Action::Call => CALL,
        nlhe::Action::RaiseTo(chips) => raise_to(chips),
    }
}

/// Chips in a big blind in [`GameConfig::new`]: bet sizes then round to a hundredth of a
/// big blind.
pub const CHIPS_PER_BIG_BLIND: Chips = 100;

/// The most decision points [`AbstractGame::new`] will build a betting tree for.
pub const DEFAULT_MAX_DECISIONS: usize = 10_000_000;

/// The settings of an abstract game.
#[derive(Clone, Debug, PartialEq)]
pub struct GameConfig {
    /// Each player's stack in chips, before the blinds are posted.
    pub stack: Chips,
    pub small_blind: Chips,
    pub big_blind: Chips,
    /// The bets on offer.
    pub menus: Menus,
}

impl GameConfig {
    /// Stacks of `stack_bb` big blinds, with blinds of 50 and 100 chips.
    pub fn new(stack_bb: u32, menus: Menus) -> GameConfig {
        GameConfig {
            stack: stack_bb * CHIPS_PER_BIG_BLIND,
            small_blind: CHIPS_PER_BIG_BLIND / 2,
            big_blind: CHIPS_PER_BIG_BLIND,
            menus,
        }
    }

    /// Push-or-fold: all in or fold for the small blind, call or fold for the big blind.
    pub fn push_fold(stack_bb: u32) -> GameConfig {
        GameConfig::new(stack_bb, Menus::push_fold())
    }

    /// The hand before anyone has acted, in the real game. The cards are placeholders:
    /// they do not change what may be bet.
    fn root(&self) -> Result<(Config, State), BuildError> {
        self.menus.validate().map_err(BuildError::Menu)?;
        let rules = Config::new(
            &[self.stack, self.stack],
            self.small_blind,
            self.big_blind,
            0,
            0,
        )
        .map_err(BuildError::Rules)?;
        let state = State::from_seed(&rules, 0);
        if state.is_terminal() {
            return Err(BuildError::NoDecision);
        }
        Ok((rules, state))
    }

    /// The size of this game's betting tree, counted without building it. Works for
    /// menus far too big to train.
    pub fn tree_size(&self) -> Result<TreeSize, BuildError> {
        let (_, root) = self.root()?;
        Ok(count(&root, &self.menus))
    }
}

/// Why an abstract game could not be built.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum BuildError {
    /// The stacks or blinds are not a playable table.
    Rules(ConfigError),
    /// A bet size in the menus is not usable.
    Menu(MenuError),
    /// The stacks are so short that the blinds put everyone all in.
    NoDecision,
    /// The betting tree has more decision points than the limit. The count is still
    /// available from [`GameConfig::tree_size`].
    TooLarge { decisions: u128, limit: usize },
}

impl fmt::Display for BuildError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            BuildError::Rules(e) => write!(f, "{e}"),
            BuildError::Menu(e) => write!(f, "{e}"),
            BuildError::NoDecision => write!(f, "the blinds put everyone all in"),
            BuildError::TooLarge { decisions, limit } => write!(
                f,
                "the betting tree has {decisions} decision points, more than the limit of {limit}"
            ),
        }
    }
}

impl std::error::Error for BuildError {}

/// A position in the abstract game: the cards dealt so far and a place in the betting
/// tree. Small and `Copy`, so solvers can clone one for every child they visit.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HandState {
    /// The small blind's two cards, the big blind's two, then the board.
    cards: [Card; 9],
    dealt: u8,
    /// The same cards as a set: bit `c` is set when card `c` is out.
    out: u64,
    /// Which action of `node` ended the hand, or [`NOT_OVER`].
    last: u16,
    /// The decision point to act at or, once the hand is over, the one of the last action.
    node: u32,
    /// Each player's bucket on each street the game has decisions on.
    buckets: [[u64; 4]; 2],
}

const NOT_OVER: u16 = u16::MAX;

impl HandState {
    /// The cards dealt so far: the small blind's two, the big blind's two, then the board.
    pub fn cards(&self) -> &[Card] {
        &self.cards[..self.dealt as usize]
    }

    /// True once all nine cards are out.
    pub fn is_dealt(&self) -> bool {
        self.dealt == 9
    }

    /// True once the hand is over.
    pub fn is_over(&self) -> bool {
        self.last != NOT_OVER
    }

    /// The decision point in the betting tree, when a player is to act.
    pub fn decision_point(&self) -> Option<u32> {
        (self.is_dealt() && !self.is_over()).then_some(self.node)
    }

    /// A player's two cards, once dealt.
    pub fn hole_cards(&self, player: usize) -> Option<[Card; 2]> {
        self.is_dealt()
            .then(|| [self.cards[2 * player], self.cards[2 * player + 1]])
    }

    /// The five board cards, once dealt, including those still face down.
    pub fn board(&self) -> Option<[Card; 5]> {
        let c = &self.cards;
        self.is_dealt().then(|| [c[4], c[5], c[6], c[7], c[8]])
    }

    /// A player's seven cards at showdown.
    fn seven(&self, player: usize) -> [Card; 7] {
        let c = &self.cards;
        [
            c[2 * player],
            c[2 * player + 1],
            c[4],
            c[5],
            c[6],
            c[7],
            c[8],
        ]
    }
}

/// A raise that is not on the menu, read as one of the two menu raises around it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Translation {
    /// The menu raise at or below the real one.
    pub lower: Action,
    /// The menu raise at or above the real one. The same as `lower` when the raise is on
    /// the menu, or outside the menu's range.
    pub upper: Action,
    /// The probability of `lower`, by the pseudo-harmonic mapping.
    pub p_lower: f64,
}

/// Heads-up No-Limit Hold'em shrunk to a menu of bets and a bucketing of hands.
#[derive(Clone, Debug)]
pub struct AbstractGame<B> {
    config: GameConfig,
    rules: Config,
    tree: BettingTree,
    size: TreeSize,
    bucketer: B,
    /// Streets with a decision: buckets are worked out for these only.
    streets: usize,
}

impl<B: Bucketer> AbstractGame<B> {
    /// Builds the game, betting tree included. Fails with [`BuildError::TooLarge`] when
    /// the tree has more than [`DEFAULT_MAX_DECISIONS`] decision points.
    pub fn new(config: GameConfig, bucketer: B) -> Result<Self, BuildError> {
        Self::with_limit(config, bucketer, DEFAULT_MAX_DECISIONS)
    }

    /// As [`AbstractGame::new`] with another limit on the tree's decision points. A
    /// decision point takes about 65 bytes, more with long menus.
    pub fn with_limit(
        config: GameConfig,
        bucketer: B,
        max_decisions: usize,
    ) -> Result<Self, BuildError> {
        let (rules, root) = config.root()?;
        let size = count(&root, &config.menus);
        let decisions = size.decision_points();
        if decisions > max_decisions.min(MAX_DECISIONS) as u128 {
            return Err(BuildError::TooLarge {
                decisions,
                limit: max_decisions,
            });
        }
        let tree = BettingTree::build(&root, &config.menus);
        debug_assert_eq!(tree.len() as u128, decisions);
        let streets = size.last_street().map_or(0, |s| s.index() + 1);
        Ok(AbstractGame {
            config,
            rules,
            tree,
            size,
            bucketer,
            streets,
        })
    }

    pub fn config(&self) -> &GameConfig {
        &self.config
    }

    pub fn bucketer(&self) -> &B {
        &self.bucketer
    }

    /// Every betting sequence of the game.
    pub fn tree(&self) -> &BettingTree {
        &self.tree
    }

    /// The size of the betting tree.
    pub fn tree_size(&self) -> &TreeSize {
        &self.size
    }

    /// Buckets per street, with 0 for streets nobody acts on.
    pub fn buckets(&self) -> [u64; 4] {
        let mut out = [0; 4];
        for (s, n) in out.iter_mut().enumerate().take(self.streets) {
            *n = self.bucketer.num_buckets(Street::ALL[s]);
        }
        out
    }

    /// Information sets: every decision point once for each bucket on its street. This
    /// is an upper bound when the bucketer leaves some bucket empty.
    pub fn info_sets(&self) -> u128 {
        self.size.info_sets(self.buckets())
    }

    /// Bytes for the regrets, one `f64` per action at every information set, as the cfr
    /// crate stores them. Its strategy sums take the same again.
    pub fn regret_bytes(&self) -> u128 {
        self.size.regret_bytes(self.buckets(), 8)
    }

    /// The key of the information set at decision point `node` for a hand in `bucket`.
    /// No two information sets share a key.
    pub fn info_key_of(&self, node: u32, bucket: u64) -> InfoKey {
        bucket
            .checked_mul(self.tree.len() as u64)
            .and_then(|k| k.checked_add(node as u64))
            .expect("bucket ids are too large for this tree: the key does not fit in 64 bits")
    }

    /// The position after this deal, with the small blind to act: `hole[0]` is the small
    /// blind's hand and `hole[1]` the big blind's.
    pub fn deal(&self, hole: [[Card; 2]; 2], board: [Card; 5]) -> Result<HandState, DealError> {
        Deal::new(&hole, board)?;
        let [[a, b], [c, d]] = hole;
        let [e, f, g, h, i] = board;
        Ok(self.dealt([a, b, c, d, e, f, g, h, i]))
    }

    /// The state once nine different cards are out.
    fn dealt(&self, cards: [Card; 9]) -> HandState {
        let mut buckets = [[0u64; 4]; 2];
        for (player, row) in buckets.iter_mut().enumerate() {
            let hole = [cards[2 * player], cards[2 * player + 1]];
            for (s, bucket) in row.iter_mut().enumerate().take(self.streets) {
                let seen = &cards[4..4 + Street::ALL[s].board_len()];
                *bucket = self.bucketer.bucket(hole, seen);
            }
        }
        HandState {
            cards,
            dealt: 9,
            out: cards.iter().fold(0, |set, &card| set | 1 << card),
            last: NOT_OVER,
            node: 0,
            buckets,
        }
    }

    /// The same position in the real game: an `nlhe::State` with these cards, played
    /// along the line that leads here. `None` while the cards are being dealt. This walks
    /// the line from the start, so it is for looking at a state, not for training.
    pub fn replay(&self, state: &HandState) -> Option<State> {
        let deal = Deal::new(
            &[state.hole_cards(0)?, state.hole_cards(1)?],
            state.board()?,
        )
        .expect("nine different cards");
        let mut hand = State::new(&self.rules, deal).expect("a valid deal");
        for action in self.tree.line(state.node) {
            hand.apply(action).expect("the tree holds legal actions");
        }
        if state.is_over() {
            let last = self.tree.edges(state.node)[state.last as usize];
            hand.apply(last.action)
                .expect("the tree holds legal actions");
        }
        Some(hand)
    }

    /// Reads a raise to `chips` at `state`, which need not be on the menu, as the menu
    /// raises around it, with the pseudo-harmonic mapping on sizes measured as shares of
    /// the pot. A raise below the smallest on the menu is read as the smallest, and one
    /// above the largest as the largest. `None` when no raise is offered at `state`.
    pub fn translate(&self, state: &HandState, chips: Chips) -> Option<Translation> {
        let node = state.decision_point()?;
        let raises: Vec<Chips> = self
            .tree
            .edges(node)
            .iter()
            .filter_map(|e| raise_amount(encode(e.action)))
            .collect();
        if raises.is_empty() {
            return None;
        }
        let hand = self.replay(state)?;
        let sizes: Vec<f64> = raises.iter().map(|&r| pot_fraction(&hand, r)).collect();
        let m = match raises.iter().position(|&r| r == chips) {
            Some(i) => Mapping {
                lower: i,
                upper: i,
                p_lower: 1.0,
            },
            None => map_size(&sizes, pot_fraction(&hand, chips)),
        };
        Some(Translation {
            lower: raise_to(raises[m.lower]),
            upper: raise_to(raises[m.upper]),
            p_lower: m.p_lower,
        })
    }
}

impl<B: Bucketer> Game for AbstractGame<B> {
    type State = HandState;

    fn num_players(&self) -> usize {
        2
    }

    fn root(&self) -> HandState {
        HandState {
            cards: [0; 9],
            dealt: 0,
            out: 0,
            last: NOT_OVER,
            node: 0,
            buckets: [[0; 4]; 2],
        }
    }

    fn node(&self, state: &HandState) -> Node {
        if !state.is_dealt() {
            Node::Chance
        } else if state.is_over() {
            Node::Terminal
        } else {
            Node::Player(self.tree.node(state.node).player as usize)
        }
    }

    fn chance_outcomes(&self, state: &HandState, out: &mut Vec<(Action, f64)>) {
        assert!(!state.is_dealt(), "not a chance node");
        let p = 1.0 / (52 - state.dealt) as f64;
        for card in 0..52 {
            if state.out >> card & 1 == 0 {
                out.push((card, p));
            }
        }
    }

    fn sample_chance(
        &self,
        state: &HandState,
        rng: &mut Rng,
        _scratch: &mut Vec<(Action, f64)>,
    ) -> Action {
        assert!(!state.is_dealt(), "not a chance node");
        // Draw until the card is new: at most 8 of the 52 are out.
        loop {
            let card = rng.below(52);
            if state.out >> card & 1 == 0 {
                return card as Action;
            }
        }
    }

    fn legal_actions(&self, state: &HandState, out: &mut Vec<Action>) {
        let node = state.decision_point().expect("not a player node");
        out.extend(self.tree.edges(node).iter().map(|e| encode(e.action)));
    }

    fn apply(&self, state: &mut HandState, action: Action) {
        if !state.is_dealt() {
            assert!(
                action < 52 && state.out >> action & 1 == 0,
                "not a card that is still in the deck"
            );
            state.cards[state.dealt as usize] = action as Card;
            state.dealt += 1;
            state.out |= 1 << action;
            if state.is_dealt() {
                *state = self.dealt(state.cards);
            }
            return;
        }
        let node = state.decision_point().expect("the hand is over");
        let (index, edge) = self
            .tree
            .edges(node)
            .iter()
            .enumerate()
            .find(|(_, e)| encode(e.action) == action)
            .expect("not an action of this decision point");
        match edge.next() {
            Next::Decision(next) => state.node = next,
            Next::End(_) => state.last = index as u16,
        }
    }

    fn info_key(&self, state: &HandState) -> InfoKey {
        let node = state.decision_point().expect("not a player node");
        let at = self.tree.node(node);
        self.info_key_of(node, state.buckets[at.player as usize][at.street.index()])
    }

    fn utility(&self, state: &HandState, player: usize) -> f64 {
        assert!(state.is_over(), "not a terminal node");
        let Next::End(ending) = self.tree.edges(state.node)[state.last as usize].next() else {
            unreachable!("the last action ends the hand");
        };
        let payoff = self.tree.payoff(ending);
        let result = if payoff.is_showdown() {
            let small_blind = EvalRanker.rank7(&state.seven(0));
            let big_blind = EvalRanker.rank7(&state.seven(1));
            Showdown::from_ordering(small_blind.cmp(&big_blind))
        } else {
            Showdown::Tie // nobody shows: every row is the same
        };
        payoff.chips[result as usize][player] as f64 / self.config.big_blind as f64
    }

    /// No pruning on the river, as in Pluribus.
    fn prune_exempt(&self, state: &HandState) -> bool {
        state
            .decision_point()
            .is_some_and(|node| self.tree.node(node).street == Street::River)
    }
}
