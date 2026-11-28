//! What an agent implements, and what it is shown.

use std::fmt;
use std::sync::Arc;

use nlhe::{Action, Card, Chips, Config, LegalActions, Move, Rng, State, Street};

use crate::mix;

/// One seat's decision maker.
///
/// Only [`Player::act`] is needed. The arena asks it whenever it is this seat's turn and
/// expects a legal action back (`view.legal()` says which are). An illegal action is
/// replaced by a check, or by a fold when checking is not allowed, and counted in the
/// match report.
///
/// For a match to replay exactly on several threads, a decision should depend only on
/// the view. Random choices should come from [`View::rng`] or [`View::seed`], not from a
/// generator kept in the player. A player that learns from one hand to the next still
/// works, but repeats exactly only with `threads: 1`.
pub trait Player: Send {
    /// The action for the seat `view.seat()`, which is to act.
    fn act(&mut self, view: &View<'_>) -> Action;

    /// A new hand starts: the blinds are posted and this seat has its cards.
    fn begin_hand(&mut self, _view: &View<'_>) {}

    /// The hand is over. `view.net()` is this seat's result and `view.shown(seat)` the
    /// cards turned up at a showdown.
    fn end_hand(&mut self, _view: &View<'_>) {}

    /// The chances the action just returned by [`Player::act`] was drawn with, when this
    /// player knows them: each action it could have returned, with its weight (weights
    /// need not add up to 1; those not above 0 are left out). AIVAT
    /// ([`crate::aivat`]) uses them to take the luck of this player's own random choices
    /// out of its result.
    ///
    /// The action must really have been drawn with these chances, from a random number
    /// that nothing else in the hand depends on: [`View::pick`] with the same weights does
    /// exactly that. A player whose action is not among them is not corrected at that
    /// decision (the report counts it). `None`, the default, says the chances are not
    /// known: the player's own choices are then left as they are.
    fn probabilities(&self) -> Option<&[(Action, f64)]> {
        None
    }

    /// The chances this player would play with at `view`, which need not be a situation
    /// the hand reached, written into `out` (empty on arrival) as for
    /// [`Player::probabilities`]. `false`, the default, when it can't say. AIVAT asks this
    /// after a hand about the situations each action could have led to, to value an
    /// action by the answers this player would give to it. The answers only steer how much
    /// luck AIVAT takes out, never the expected result, so answers that are off cost
    /// precision, not correctness, on one condition: they depend only on the view, not on
    /// anything the player saw or did in the hand (a player that learns from its hands
    /// should say `false`). The view's [`View::seed`] is 0.
    fn chances_at(&self, _view: &View<'_>, _out: &mut Vec<(Action, f64)>) -> bool {
        false
    }
}

/// A closure is a player: `|view: &View<'_>| view.check_or_call()`.
impl<F> Player for F
where
    F: FnMut(&View<'_>) -> Action + Send,
{
    fn act(&mut self, view: &View<'_>) -> Action {
        self(view)
    }
}

/// Everything one seat may see: its own cards and what is public. The other players'
/// cards are not reachable from here before a showdown.
#[derive(Clone, Copy)]
pub struct View<'a> {
    state: &'a State,
    seat: usize,
    hole: [Card; 2],
    seed: u64,
    net: Option<i64>,
}

impl<'a> View<'a> {
    /// What `seat` sees of `state`. `seed` is the seat's private random number for this
    /// hand. The arena builds the views of a match; this is for adapters and tests.
    pub fn new(state: &'a State, seat: usize, seed: u64) -> View<'a> {
        assert!(seat < state.num_players());
        View {
            state,
            seat,
            hole: state.hole_cards(seat),
            seed,
            net: None,
        }
    }

    pub(crate) fn finished(state: &'a State, seat: usize, seed: u64, net: i64) -> View<'a> {
        View {
            net: Some(net),
            ..View::new(state, seat, seed)
        }
    }

    /// The same public situation through the eyes of `seat`, as if it held `hole`. An
    /// agent that tracks an opponent's range asks the opponent's strategy what it would
    /// do with each hand this way. Nothing hidden is revealed: the caller supplies the cards.
    pub fn imagine(&self, seat: usize, hole: [Card; 2]) -> View<'a> {
        assert!(seat < self.state.num_players());
        View {
            seat,
            hole,
            net: None,
            ..*self
        }
    }

    // ----- this seat -----

    pub fn seat(&self) -> usize {
        self.seat
    }
    /// This seat's two hole cards (`rank * 4 + suit`, as in nlhe and eval).
    pub fn hole(&self) -> [Card; 2] {
        self.hole
    }
    /// What this seat may do now (nothing once the hand is over).
    pub fn legal(&self) -> LegalActions {
        if self.state.current_player() == Some(self.seat) {
            self.state.legal_actions()
        } else {
            LegalActions::default()
        }
    }
    /// Chips this seat must add to call (0 when checking is free).
    pub fn to_call(&self) -> Chips {
        let owed = self.state.max_bet() - self.state.bets()[self.seat];
        owed.min(self.state.stacks()[self.seat])
    }
    /// This seat's private random number for the hand: the same for every decision of
    /// the hand, different for every seat, deal and replay.
    pub fn seed(&self) -> u64 {
        self.seed
    }
    /// A generator for this decision, seeded from [`View::seed`] and the number of
    /// actions so far. Asking twice at the same decision gives the same numbers.
    pub fn rng(&self) -> Rng {
        Rng::new(mix(self.seed, self.state.history().len() as u64))
    }

    /// Draws an index with the given weights (any non-negative numbers, not all zero),
    /// using this decision's random number. An agent with a mixed strategy passes its
    /// action probabilities. Two agents with close probabilities and the same seed
    /// mostly pick the same index, which is what `shared_randomness` relies on.
    pub fn pick(&self, weights: &[f64]) -> usize {
        let total: f64 = weights.iter().sum();
        assert!(total > 0.0, "weights must not all be zero");
        // 53 random bits: a number in [0, 1).
        let mut x = (self.rng().next_u64() >> 11) as f64 / (1u64 << 53) as f64 * total;
        let mut last = 0;
        for (i, &w) in weights.iter().enumerate() {
            if w > 0.0 {
                if x < w {
                    return i;
                }
                x -= w;
                last = i;
            }
        }
        last
    }

    // ----- the table -----

    pub fn num_players(&self) -> usize {
        self.state.num_players()
    }
    pub fn button(&self) -> usize {
        self.state.button()
    }
    pub fn small_blind_seat(&self) -> usize {
        self.state.small_blind_seat()
    }
    pub fn big_blind_seat(&self) -> usize {
        self.state.big_blind_seat()
    }
    pub fn small_blind(&self) -> Chips {
        self.state.small_blind()
    }
    pub fn big_blind(&self) -> Chips {
        self.state.big_blind()
    }
    pub fn ante(&self) -> Chips {
        self.state.ante()
    }
    /// Each seat's stack before the blinds.
    pub fn starting_stacks(&self) -> &'a [Chips] {
        self.state.starting_stacks()
    }
    /// The table this hand started from. With [`View::history`] it is enough to rebuild
    /// the public state in an nlhe `State` with made-up cards, to search or walk a tree.
    pub fn config(&self) -> Config {
        Config::new(
            self.state.starting_stacks(),
            self.state.small_blind(),
            self.state.big_blind(),
            self.state.ante(),
            self.state.button(),
        )
        .expect("the hand started from a valid table")
    }

    // ----- the hand so far -----

    pub fn street(&self) -> Street {
        self.state.street()
    }
    /// The board cards face up.
    pub fn board(&self) -> &'a [Card] {
        self.state.board()
    }
    /// Every action so far, in order, with its street, seat and chips.
    pub fn history(&self) -> &'a [Move] {
        self.state.history()
    }
    /// Chips behind, per seat.
    pub fn stacks(&self) -> &'a [Chips] {
        self.state.stacks()
    }
    /// This street's bets, per seat.
    pub fn bets(&self) -> &'a [Chips] {
        self.state.bets()
    }
    /// Everything each seat has put in this hand.
    pub fn committed(&self) -> &'a [Chips] {
        self.state.committed()
    }
    /// All chips in the middle, this street's bets included.
    pub fn pot(&self) -> Chips {
        self.state.pot()
    }
    /// The largest bet of this street.
    pub fn max_bet(&self) -> Chips {
        self.state.max_bet()
    }
    pub fn is_folded(&self, seat: usize) -> bool {
        self.state.is_folded(seat)
    }
    pub fn is_all_in(&self, seat: usize) -> bool {
        self.state.is_all_in(seat)
    }

    // ----- the end of the hand -----

    pub fn is_over(&self) -> bool {
        self.state.is_terminal()
    }
    /// This seat's result in chips, in [`Player::end_hand`].
    pub fn net(&self) -> Option<i64> {
        self.net
    }
    /// The cards of `seat` if this seat may see them: its own, and after a showdown
    /// those of every player who did not fold.
    pub fn shown(&self, seat: usize) -> Option<[Card; 2]> {
        if seat == self.seat {
            return Some(self.hole);
        }
        let showdown = self.state.is_terminal() && self.state.active_mask().count_ones() >= 2;
        (showdown && !self.state.is_folded(seat)).then(|| self.state.hole_cards(seat))
    }

    // ----- building actions -----

    /// Check when it is free, otherwise call.
    pub fn check_or_call(&self) -> Action {
        if self.state.max_bet() == self.state.bets()[self.seat] {
            Action::Check
        } else {
            Action::Call
        }
    }
    /// Check when it is free, otherwise fold.
    pub fn check_or_fold(&self) -> Action {
        if self.state.max_bet() == self.state.bets()[self.seat] {
            Action::Check
        } else {
            Action::Fold
        }
    }
    /// A raise to `amount` (this street's total bet), moved into the legal range: up to
    /// the minimum raise or down to all in. When raising is not allowed: call or check.
    pub fn raise_to(&self, amount: Chips) -> Action {
        match self.legal().raise {
            Some(range) => Action::RaiseTo(amount.clamp(range.min_to, range.max_to)),
            None => self.check_or_call(),
        }
    }
    /// A bet or raise of `fraction` of the pot (the pot after calling), made legal as in
    /// [`View::raise_to`].
    pub fn raise_pot(&self, fraction: f64) -> Action {
        let after_call = self.pot() as f64 + self.to_call() as f64;
        let extra = (fraction * after_call)
            .round()
            .clamp(0.0, Chips::MAX as f64 / 2.0);
        self.raise_to(self.max_bet().saturating_add(extra as Chips))
    }
}

impl fmt::Debug for View<'_> {
    /// Prints what the seat sees, never the hidden cards.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("View")
            .field("seat", &self.seat)
            .field("hole", &self.hole.map(nlhe::card_string))
            .field(
                "board",
                &self
                    .board()
                    .iter()
                    .map(|&c| nlhe::card_string(c))
                    .collect::<String>(),
            )
            .field("street", &self.street())
            .field("pot", &self.pot())
            .field("to_call", &self.to_call())
            .field("stacks", &self.stacks())
            .finish()
    }
}

/// A named agent that can seat any number of players. The arena makes one player per
/// seat and per worker thread, so players never share state.
#[derive(Clone)]
pub struct Agent {
    name: String,
    make: Arc<dyn Fn() -> Box<dyn Player> + Send + Sync>,
}

impl Agent {
    /// An agent whose players come from `make`.
    pub fn new<F>(name: impl Into<String>, make: F) -> Agent
    where
        F: Fn() -> Box<dyn Player> + Send + Sync + 'static,
    {
        Agent {
            name: name.into(),
            make: Arc::new(make),
        }
    }

    /// An agent whose players are copies of `player`.
    pub fn of<P>(name: impl Into<String>, player: P) -> Agent
    where
        P: Player + Clone + Sync + 'static,
    {
        Agent::new(name, move || Box::new(player.clone()))
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    /// A new player of this agent.
    pub fn player(&self) -> Box<dyn Player> {
        (self.make)()
    }
}

impl fmt::Debug for Agent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Agent({:?})", self.name)
    }
}
