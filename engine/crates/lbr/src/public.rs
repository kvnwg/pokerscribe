//! What both players can see.

use std::fmt;

use nlhe::{Card, Chips, LegalActions, Move, State, Street};

/// The public part of a hand: the betting so far, the stacks and the board cards face up.
///
/// An nlhe [`State`] also holds both players' hole cards and the board cards still to come.
/// A [`crate::Strategy`] gets this view instead, so it cannot look at them.
#[derive(Clone, Copy)]
pub struct PublicState<'a> {
    state: &'a State,
}

impl<'a> PublicState<'a> {
    pub fn new(state: &'a State) -> PublicState<'a> {
        PublicState { state }
    }

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
    pub fn street(&self) -> Street {
        self.state.street()
    }
    pub fn is_terminal(&self) -> bool {
        self.state.is_terminal()
    }
    /// The seat to act, or `None` when the hand is over.
    pub fn current_player(&self) -> Option<usize> {
        self.state.current_player()
    }
    pub fn starting_stacks(&self) -> &'a [Chips] {
        self.state.starting_stacks()
    }
    /// Chips behind for each seat.
    pub fn stacks(&self) -> &'a [Chips] {
        self.state.stacks()
    }
    /// This street's bets.
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
    pub fn max_bet(&self) -> Chips {
        self.state.max_bet()
    }
    pub fn full_raise(&self) -> Chips {
        self.state.full_raise()
    }
    pub fn is_folded(&self, seat: usize) -> bool {
        self.state.is_folded(seat)
    }
    pub fn is_all_in(&self, seat: usize) -> bool {
        self.state.is_all_in(seat)
    }
    /// The board cards face up so far.
    pub fn board(&self) -> &'a [Card] {
        self.state.board()
    }
    /// Every action so far, in order.
    pub fn history(&self) -> &'a [Move] {
        self.state.history()
    }
    /// What the player to act may do.
    pub fn legal_actions(&self) -> LegalActions {
        self.state.legal_actions()
    }
}

impl fmt::Debug for PublicState<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PublicState")
            .field("street", &self.street())
            .field("board", &self.board())
            .field("stacks", &self.stacks())
            .field("bets", &self.bets())
            .field("committed", &self.committed())
            .field("to_act", &self.current_player())
            .field("history", &self.history())
            .finish()
    }
}
