//! One hand of No-Limit Hold'em (the nlhe crate), with showdowns ranked by the eval crate.

use nlhe::{Action, Chips, Config, Deal, EvalRanker, Street};
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::cards;

fn value_error(e: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(e.to_string())
}

fn street_name(street: Street) -> &'static str {
    match street {
        Street::Preflop => "preflop",
        Street::Flop => "flop",
        Street::Turn => "turn",
        Street::River => "river",
    }
}

/// An action from Python: a name and, for a raise, the amount to raise to.
fn parse_action(action: &str, amount: Option<Chips>) -> PyResult<Action> {
    match (action, amount) {
        ("fold", None) => Ok(Action::Fold),
        ("check", None) => Ok(Action::Check),
        ("call", None) => Ok(Action::Call),
        ("raise" | "bet", Some(to)) => Ok(Action::RaiseTo(to)),
        ("raise" | "bet", None) => Err(PyValueError::new_err(format!(
            "{action} needs an amount: the player's total bet on this street after it"
        ))),
        ("fold" | "check" | "call", Some(_)) => {
            Err(PyValueError::new_err(format!("{action} takes no amount")))
        }
        _ => Err(PyValueError::new_err(format!(
            "unknown action {action:?}: use \"fold\", \"check\", \"call\" or \"raise\""
        ))),
    }
}

/// What the player to act may do. Every field is read-only.
///
/// fold: folding is allowed (only when there is a bet to call).
/// check: checking is allowed.
/// call: the chips a call would put in, or None when there is nothing to call.
/// min_raise_to, max_raise_to: a bet or raise may make the player's total bet on this
/// street any whole number in this range (max_raise_to is all in), or None when the player
/// may not raise.
#[pyclass(module = "pokerscribe_engine", frozen, get_all, eq, hash)]
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct LegalActions {
    fold: bool,
    check: bool,
    call: Option<Chips>,
    min_raise_to: Option<Chips>,
    max_raise_to: Option<Chips>,
}

impl LegalActions {
    fn engine(&self) -> nlhe::LegalActions {
        nlhe::LegalActions {
            fold: self.fold,
            check: self.check,
            call: self.call,
            raise: self
                .min_raise_to
                .zip(self.max_raise_to)
                .map(|(min_to, max_to)| nlhe::RaiseRange { min_to, max_to }),
        }
    }
}

#[pymethods]
impl LegalActions {
    /// True when a bet or raise is allowed.
    #[getter]
    fn can_raise(&self) -> bool {
        self.min_raise_to.is_some()
    }

    /// The names of the allowed actions, in the order fold, check, call, raise.
    fn names(&self) -> Vec<&'static str> {
        let mut out = Vec::with_capacity(3);
        if self.fold {
            out.push("fold");
        }
        if self.check {
            out.push("check");
        }
        if self.call.is_some() {
            out.push("call");
        }
        if self.min_raise_to.is_some() {
            out.push("raise");
        }
        out
    }

    /// True when State.apply(action, amount) would be accepted.
    #[pyo3(signature = (action, amount=None))]
    fn allows(&self, action: &str, amount: Option<Chips>) -> PyResult<bool> {
        Ok(self.engine().allows(parse_action(action, amount)?))
    }

    fn __repr__(&self) -> String {
        let number = |x: Option<Chips>| x.map_or("None".to_string(), |v| v.to_string());
        format!(
            "LegalActions(fold={}, check={}, call={}, min_raise_to={}, max_raise_to={})",
            if self.fold { "True" } else { "False" },
            if self.check { "True" } else { "False" },
            number(self.call),
            number(self.min_raise_to),
            number(self.max_raise_to)
        )
    }
}

/// One hand of No-Limit Hold'em for 2 to 6 players, from the blinds to the payouts.
///
/// Make one with new_hand(...) (State(...) takes the same arguments). Seats are numbered
/// from 0 clockwise; the small blind is the seat after the button, and heads-up the button
/// posts the small blind and acts first before the flop. Chips are whole numbers.
#[pyclass(module = "pokerscribe_engine", eq)]
#[derive(Clone, Debug, PartialEq)]
pub struct State {
    inner: nlhe::State,
}

impl State {
    fn seat(&self, seat: usize) -> PyResult<usize> {
        if seat < self.inner.num_players() {
            Ok(seat)
        } else {
            Err(PyIndexError::new_err(format!(
                "seat {seat} is not at the table (seats 0 to {})",
                self.inner.num_players() - 1
            )))
        }
    }

    fn not_over() -> PyErr {
        PyValueError::new_err("the hand is not over yet")
    }
}

fn deal_from_cards(
    players: usize,
    hole: &Bound<'_, PyAny>,
    board: &Bound<'_, PyAny>,
) -> PyResult<Deal> {
    let mut seats: Vec<[nlhe::Card; 2]> = Vec::new();
    for pair in hole.try_iter()? {
        let pair = cards::cards(&pair?)?;
        let [a, b] = pair[..] else {
            return Err(PyValueError::new_err(format!(
                "each seat gets two hole cards, got {}",
                pair.len()
            )));
        };
        seats.push([a.index(), b.index()]);
    }
    if seats.len() != players {
        return Err(PyValueError::new_err(format!(
            "hole cards for {} seats, but {players} stacks",
            seats.len()
        )));
    }
    let board = cards::cards(board)?;
    let Ok(board) = <[eval::Card; 5]>::try_from(board.as_slice()) else {
        return Err(PyValueError::new_err(format!(
            "the board is five cards (flop, turn and river), got {}",
            board.len()
        )));
    };
    Deal::new(&seats, board.map(eval::Card::index)).map_err(value_error)
}

#[pymethods]
impl State {
    #[new]
    #[pyo3(signature = (stacks, small_blind, big_blind, ante=0, button=0, *, seed=None, hole=None, board=None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        stacks: Vec<Chips>,
        small_blind: Chips,
        big_blind: Chips,
        ante: Chips,
        button: usize,
        seed: Option<u64>,
        hole: Option<&Bound<'_, PyAny>>,
        board: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<State> {
        let config =
            Config::new(&stacks, small_blind, big_blind, ante, button).map_err(value_error)?;
        let inner = match (seed, hole, board) {
            (Some(seed), None, None) => nlhe::State::from_seed(&config, seed),
            (None, Some(hole), Some(board)) => {
                let deal = deal_from_cards(stacks.len(), hole, board)?;
                nlhe::State::new(&config, deal).map_err(value_error)?
            }
            _ => {
                return Err(PyValueError::new_err(
                    "give either seed (a shuffled deal), or both hole and board (fixed cards)",
                ))
            }
        };
        Ok(State { inner })
    }

    // ----- the table -----

    #[getter]
    fn num_players(&self) -> usize {
        self.inner.num_players()
    }
    #[getter]
    fn button(&self) -> usize {
        self.inner.button()
    }
    #[getter]
    fn small_blind_seat(&self) -> usize {
        self.inner.small_blind_seat()
    }
    #[getter]
    fn big_blind_seat(&self) -> usize {
        self.inner.big_blind_seat()
    }
    #[getter]
    fn small_blind(&self) -> Chips {
        self.inner.small_blind()
    }
    #[getter]
    fn big_blind(&self) -> Chips {
        self.inner.big_blind()
    }
    #[getter]
    fn ante(&self) -> Chips {
        self.inner.ante()
    }
    /// Each seat's stack before the antes and blinds.
    #[getter]
    fn starting_stacks(&self) -> Vec<Chips> {
        self.inner.starting_stacks().to_vec()
    }

    // ----- the hand so far -----

    /// "preflop", "flop", "turn" or "river".
    #[getter]
    fn street(&self) -> &'static str {
        street_name(self.inner.street())
    }
    /// True once the hand is over.
    #[getter]
    fn is_terminal(&self) -> bool {
        self.inner.is_terminal()
    }
    /// The seat to act, or None once the hand is over.
    #[getter]
    fn current_player(&self) -> Option<usize> {
        self.inner.current_player()
    }
    /// The board cards face up so far, as strings. After an all-in it runs out to five.
    #[getter]
    fn board(&self) -> Vec<String> {
        let board = self.inner.board();
        board.iter().map(|&c| nlhe::card_string(c)).collect()
    }
    /// Chips behind (not bet) for each seat.
    #[getter]
    fn stacks(&self) -> Vec<Chips> {
        self.inner.stacks().to_vec()
    }
    /// Each seat's bet on this street.
    #[getter]
    fn bets(&self) -> Vec<Chips> {
        self.inner.bets().to_vec()
    }
    /// Everything each seat has put in this hand, this street's bets included.
    #[getter]
    fn committed(&self) -> Vec<Chips> {
        self.inner.committed().to_vec()
    }
    /// All the chips in the middle, this street's bets included.
    #[getter]
    fn pot(&self) -> Chips {
        self.inner.pot()
    }
    /// The largest bet on this street.
    #[getter]
    fn max_bet(&self) -> Chips {
        self.inner.max_bet()
    }
    /// The smallest raise increment on this street (the big blind or the last full raise).
    #[getter]
    fn full_raise(&self) -> Chips {
        self.inner.full_raise()
    }

    /// A seat's two hole cards, as strings. Every seat's cards can be read: the caller
    /// decides what each player is shown.
    fn hole_cards(&self, seat: usize) -> PyResult<Vec<String>> {
        let hole = self.inner.hole_cards(self.seat(seat)?);
        Ok(hole.iter().map(|&c| nlhe::card_string(c)).collect())
    }
    fn is_folded(&self, seat: usize) -> PyResult<bool> {
        Ok(self.inner.is_folded(self.seat(seat)?))
    }
    fn is_all_in(&self, seat: usize) -> PyResult<bool> {
        Ok(self.inner.is_all_in(self.seat(seat)?))
    }

    /// The main and side pots as (chips, [seats that can win it]), main pot first.
    fn pots(&self) -> Vec<(Chips, Vec<usize>)> {
        let seats = self.inner.num_players();
        let pots = self.inner.pots();
        let pots = pots.as_slice().iter();
        pots.map(|pot| {
            let eligible = (0..seats).filter(|&s| pot.eligible >> s & 1 == 1);
            (pot.amount, eligible.collect())
        })
        .collect()
    }

    /// Every action so far, in order, each a dict: street, seat, action ("fold", "check",
    /// "call" or "raise"), amount (the total bet a raise went to, else None) and added
    /// (the chips the action put in).
    fn history<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let moves = self.inner.history().iter();
        moves
            .map(|m| {
                let (name, amount) = match m.action {
                    Action::Fold => ("fold", None),
                    Action::Check => ("check", None),
                    Action::Call => ("call", None),
                    Action::RaiseTo(to) => ("raise", Some(to)),
                };
                let entry = PyDict::new(py);
                entry.set_item("street", street_name(m.street))?;
                entry.set_item("seat", m.seat)?;
                entry.set_item("action", name)?;
                entry.set_item("amount", amount)?;
                entry.set_item("added", m.added)?;
                Ok(entry)
            })
            .collect()
    }

    // ----- playing -----

    /// What the player to act may do (nothing is allowed once the hand is over).
    fn legal_actions(&self) -> LegalActions {
        let legal = self.inner.legal_actions();
        LegalActions {
            fold: legal.fold,
            check: legal.check,
            call: legal.call,
            min_raise_to: legal.raise.map(|r| r.min_to),
            max_raise_to: legal.raise.map(|r| r.max_to),
        }
    }

    /// The current player acts: apply("fold"), apply("check"), apply("call") or
    /// apply("raise", amount), where amount is the player's total bet on this street after
    /// the raise (raise TO, not raise BY). An opening bet is a raise too, and "bet" is
    /// accepted as another name for it.
    ///
    /// An action that is not legal raises ValueError and changes nothing.
    #[pyo3(signature = (action, amount=None))]
    fn apply(&mut self, action: &str, amount: Option<Chips>) -> PyResult<()> {
        let action = parse_action(action, amount)?;
        self.inner.apply(action).map_err(value_error)
    }

    /// Chips won or lost by each seat: final stack minus starting stack. Showdowns are
    /// ranked by the eval crate. ValueError before the hand is over.
    fn payouts(&self) -> PyResult<Vec<i64>> {
        let net = self.inner.payouts(&EvalRanker);
        let net = net.ok_or_else(State::not_over)?;
        Ok(net[..self.inner.num_players()].to_vec())
    }

    /// Each seat's stack after the hand. ValueError before the hand is over.
    fn final_stacks(&self) -> PyResult<Vec<Chips>> {
        let stacks = self.inner.final_stacks(&EvalRanker);
        let stacks = stacks.ok_or_else(State::not_over)?;
        Ok(stacks[..self.inner.num_players()].to_vec())
    }

    /// An independent copy: playing on in one does not change the other.
    fn copy(&self) -> State {
        self.clone()
    }
    fn __copy__(&self) -> State {
        self.clone()
    }
    fn __deepcopy__(&self, _memo: &Bound<'_, PyAny>) -> State {
        self.clone()
    }

    fn __repr__(&self) -> String {
        let turn = match self.inner.current_player() {
            Some(seat) => format!("seat {seat} to act"),
            None => "over".to_string(),
        };
        format!(
            "State({} players, {}, pot {}, {turn})",
            self.inner.num_players(),
            street_name(self.inner.street()),
            self.inner.pot()
        )
    }
}

/// Starts a hand: posts the antes and blinds and deals the cards.
///
/// stacks: each seat's chips, seat 0 first (2 to 6 seats). small_blind, big_blind, ante:
/// in chips. button: the seat with the button.
///
/// The cards come from one of two keyword arguments:
/// - seed: an int from 0 to 2**64 - 1. The same seed always gives the same cards.
/// - hole and board: fixed cards. hole is one pair per seat, such as
///   [["Ah", "Kd"], ["7c", "2d"]] or ["AhKd", "7c2d"]; board is all five cards, of which
///   the state shows only the streets reached.
#[pyfunction]
#[pyo3(signature = (stacks, small_blind, big_blind, ante=0, button=0, *, seed=None, hole=None, board=None))]
#[allow(clippy::too_many_arguments)]
pub fn new_hand(
    stacks: Vec<Chips>,
    small_blind: Chips,
    big_blind: Chips,
    ante: Chips,
    button: usize,
    seed: Option<u64>,
    hole: Option<&Bound<'_, PyAny>>,
    board: Option<&Bound<'_, PyAny>>,
) -> PyResult<State> {
    State::new(
        stacks,
        small_blind,
        big_blind,
        ante,
        button,
        seed,
        hole,
        board,
    )
}
