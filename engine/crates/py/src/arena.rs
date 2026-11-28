//! Matches in the arena (engine/crates/arena) from Python, with Rust and Python agents.
//!
//! The arena plays the match: the deals and their seeds, duplicate play, the all-in equity,
//! the standard errors and the report are all its own, exactly as in a match between Rust
//! agents. A Python agent is an object with an `act(view)` method; the arena calls it
//! whenever its seat is to act, with the GIL taken for that call only.

use std::sync::{Arc, Mutex};

use arena::{
    run_match as arena_match, Agent, Aivat, Facing, MatchConfig, Player, View as ArenaView,
};
use nlhe::{Action, Card, Chips, State};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString, PyTuple};

use crate::agents::{blueprint_agent, rust_agent, search_agent, visible_state, RUST_AGENTS};
use crate::game::{history_dicts, parse_action, street_name, value_error, LegalActions};

/// What one seat may see: its own cards and everything public. A Python agent gets one at
/// each decision (act), at the start of each hand (begin_hand) and at its end (end_hand).
/// The other seats' cards can't be reached: the view holds only the cards this seat may
/// see (the others are made up and never shown; `shown` gives the showdown cards).
#[pyclass(module = "pokerscribe_engine", frozen)]
pub struct View {
    state: State,
    seat: usize,
    seed: u64,
    net: Option<i64>,
}

impl View {
    fn new(view: &ArenaView<'_>) -> View {
        View {
            state: visible_state(view),
            seat: view.seat(),
            seed: view.seed(),
            net: view.net(),
        }
    }

    /// The arena's view of the same seat, to answer from.
    fn arena(&self) -> ArenaView<'_> {
        ArenaView::new(&self.state, self.seat, self.seed)
    }

    fn check_seat(&self, seat: usize) -> PyResult<usize> {
        if seat < self.state.num_players() {
            Ok(seat)
        } else {
            Err(pyo3::exceptions::PyIndexError::new_err(format!(
                "seat {seat} is not at the table (seats 0 to {})",
                self.state.num_players() - 1
            )))
        }
    }
}

fn cards(cards: &[Card]) -> Vec<String> {
    cards.iter().map(|&c| nlhe::card_string(c)).collect()
}

#[pymethods]
impl View {
    // ----- this seat -----

    /// The seat this view belongs to (the button is seat 0 in a match).
    #[getter]
    fn seat(&self) -> usize {
        self.seat
    }
    /// This seat's two hole cards, as strings.
    #[getter]
    fn hole(&self) -> Vec<String> {
        cards(&self.state.hole_cards(self.seat))
    }
    /// What this seat may do now (nothing is allowed when it is not its turn).
    fn legal_actions(&self) -> LegalActions {
        LegalActions::from_engine(self.arena().legal())
    }
    /// Chips this seat must add to call (0 when checking is free).
    #[getter]
    fn to_call(&self) -> Chips {
        self.arena().to_call()
    }
    /// This seat's private random number for the hand: the same at every decision of the
    /// hand, different for every seat, deal and replay.
    #[getter]
    fn seed(&self) -> u64 {
        self.seed
    }
    /// An index drawn with these weights (non-negative, not all zero) from this decision's
    /// random number, as the Rust agents draw theirs.
    fn pick(&self, weights: Vec<f64>) -> PyResult<usize> {
        if weights.is_empty()
            || weights.iter().any(|w| w.is_nan() || *w < 0.0)
            || weights.iter().sum::<f64>() <= 0.0
        {
            return Err(PyValueError::new_err(
                "weights must be non-negative numbers, not all zero",
            ));
        }
        Ok(self.arena().pick(&weights))
    }

    // ----- the table -----

    #[getter]
    fn num_players(&self) -> usize {
        self.state.num_players()
    }
    #[getter]
    fn button(&self) -> usize {
        self.state.button()
    }
    #[getter]
    fn small_blind_seat(&self) -> usize {
        self.state.small_blind_seat()
    }
    #[getter]
    fn big_blind_seat(&self) -> usize {
        self.state.big_blind_seat()
    }
    #[getter]
    fn small_blind(&self) -> Chips {
        self.state.small_blind()
    }
    #[getter]
    fn big_blind(&self) -> Chips {
        self.state.big_blind()
    }
    #[getter]
    fn ante(&self) -> Chips {
        self.state.ante()
    }
    /// Each seat's stack before the antes and blinds.
    #[getter]
    fn starting_stacks(&self) -> Vec<Chips> {
        self.state.starting_stacks().to_vec()
    }

    // ----- the hand so far -----

    /// "preflop", "flop", "turn" or "river".
    #[getter]
    fn street(&self) -> &'static str {
        street_name(self.state.street())
    }
    /// The board cards face up, as strings.
    #[getter]
    fn board(&self) -> Vec<String> {
        cards(self.state.board())
    }
    /// Every action so far, each a dict: street, seat, action, amount, added (as
    /// State.history()).
    fn history<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        history_dicts(py, self.state.history())
    }
    /// Chips behind, per seat.
    #[getter]
    fn stacks(&self) -> Vec<Chips> {
        self.state.stacks().to_vec()
    }
    /// This street's bets, per seat.
    #[getter]
    fn bets(&self) -> Vec<Chips> {
        self.state.bets().to_vec()
    }
    /// Everything each seat has put in this hand, this street's bets included.
    #[getter]
    fn committed(&self) -> Vec<Chips> {
        self.state.committed().to_vec()
    }
    /// All the chips in the middle, this street's bets included.
    #[getter]
    fn pot(&self) -> Chips {
        self.state.pot()
    }
    /// The largest bet of this street.
    #[getter]
    fn max_bet(&self) -> Chips {
        self.state.max_bet()
    }
    /// The smallest raise increment on this street (the big blind or the last full raise).
    #[getter]
    fn full_raise(&self) -> Chips {
        self.state.full_raise()
    }
    fn is_folded(&self, seat: usize) -> PyResult<bool> {
        Ok(self.state.is_folded(self.check_seat(seat)?))
    }
    fn is_all_in(&self, seat: usize) -> PyResult<bool> {
        Ok(self.state.is_all_in(self.check_seat(seat)?))
    }

    // ----- the end of the hand -----

    /// True once the hand is over.
    #[getter]
    fn is_over(&self) -> bool {
        self.state.is_terminal()
    }
    /// This seat's result in chips, in end_hand (None before).
    #[getter]
    fn net(&self) -> Option<i64> {
        self.net
    }
    /// The cards of `seat` if this seat may see them: its own, and after a showdown those
    /// of every player who did not fold. None otherwise.
    fn shown(&self, seat: usize) -> PyResult<Option<Vec<String>>> {
        let seat = self.check_seat(seat)?;
        Ok(self.arena().shown(seat).map(|c| cards(&c)))
    }

    fn __repr__(&self) -> String {
        format!(
            "View(seat {}, {}, {}, pot {}, to call {})",
            self.seat,
            self.hole().join(""),
            street_name(self.state.street()),
            self.state.pot(),
            self.arena().to_call()
        )
    }
}

/// The first error a Python agent raised in a match. Once there is one, the Python agents
/// of the match stop being called (they check or fold) and the match ends quickly, then
/// run_match raises it.
type Failure = Arc<Mutex<Option<PyErr>>>;

/// A Python object seated at the table.
struct PythonPlayer {
    agent: Py<PyAny>,
    begin: bool,
    end: bool,
    failure: Failure,
}

impl PythonPlayer {
    fn failed(&self) -> bool {
        self.failure.lock().unwrap().is_some()
    }

    fn fail(&self, error: PyErr) {
        let mut slot = self.failure.lock().unwrap();
        if slot.is_none() {
            *slot = Some(error);
        }
    }

    /// Calls `method(view)` on the agent.
    fn call<'py>(
        &self,
        py: Python<'py>,
        method: &str,
        view: &ArenaView<'_>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let view = Py::new(py, View::new(view))?;
        self.agent.bind(py).call_method1(method, (view,))
    }
}

impl Player for PythonPlayer {
    fn act(&mut self, view: &ArenaView<'_>) -> Action {
        if self.failed() {
            return view.check_or_fold();
        }
        Python::attach(|py| {
            let answer = self.call(py, "act", view).and_then(|a| to_action(&a));
            answer.unwrap_or_else(|e| {
                self.fail(e);
                view.check_or_fold()
            })
        })
    }

    fn begin_hand(&mut self, view: &ArenaView<'_>) {
        if self.begin && !self.failed() {
            Python::attach(|py| {
                if let Err(e) = self.call(py, "begin_hand", view) {
                    self.fail(e);
                }
            });
        }
    }

    fn end_hand(&mut self, view: &ArenaView<'_>) {
        if self.end && !self.failed() {
            Python::attach(|py| {
                if let Err(e) = self.call(py, "end_hand", view) {
                    self.fail(e);
                }
            });
        }
    }
}

/// What a Python agent's act() returned, as an nlhe action: "fold", "check", "call", or
/// ("raise", amount) with amount the total bet of the street ("bet" is the same).
fn to_action(answer: &Bound<'_, PyAny>) -> PyResult<Action> {
    if let Ok(name) = answer.cast::<PyString>() {
        return parse_action(&name.to_cow()?, None);
    }
    if let Ok(pair) = answer.cast::<PyTuple>() {
        if pair.len() == 2 {
            let name: String = pair.get_item(0)?.extract()?;
            let amount: Option<Chips> = pair.get_item(1)?.extract()?;
            return parse_action(&name, amount);
        }
    }
    Err(PyTypeError::new_err(format!(
        "act() must return \"fold\", \"check\", \"call\" or (\"raise\", amount), not {}",
        answer.repr()?
    )))
}

/// The agent a run_match argument names: a Rust agent by name, or a Python object.
fn agent(spec: &Bound<'_, PyAny>, failure: &Failure) -> PyResult<(Agent, bool)> {
    if let Ok(name) = spec.cast::<PyString>() {
        let name = name.to_cow()?;
        if let Some(made) = blueprint_agent(&name).or_else(|| search_agent(&name)) {
            return made
                .map(|agent| (agent, false))
                .map_err(PyValueError::new_err);
        }
        return match rust_agent(&name) {
            Some(agent) => Ok((agent, false)),
            None => Err(PyValueError::new_err(format!(
                "no Rust agent is called {name:?}: the names are {}, blueprint:<strategy file> and search:<strategy file>",
                RUST_AGENTS.join(", ")
            ))),
        };
    }
    if !spec.hasattr("act")? {
        return Err(PyTypeError::new_err(format!(
            "an agent is a Rust agent's name or an object with an act(view) method, not {}",
            spec.repr()?
        )));
    }
    let name: String = match spec.getattr("name") {
        Ok(name) => name.extract()?,
        Err(_) => spec.get_type().name()?.to_string(),
    };
    let begin = spec.hasattr("begin_hand")?;
    let end = spec.hasattr("end_hand")?;
    let object: Py<PyAny> = spec.clone().unbind();
    let failure = Arc::clone(failure);
    let agent = Agent::new(name, move || {
        let agent = Python::attach(|py| object.clone_ref(py));
        Box::new(PythonPlayer {
            agent,
            begin,
            end,
            failure: Arc::clone(&failure),
        })
    });
    Ok((agent, true))
}

/// The result of a match: the arena's report (`format` "pokerscribe-arena/1").
#[pyclass(module = "pokerscribe_engine", frozen)]
pub struct MatchReport {
    inner: arena::MatchReport,
}

#[pymethods]
impl MatchReport {
    /// The report as a dict, the same fields as its JSON.
    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        py.import("json")?
            .call_method1("loads", (self.inner.to_json(),))
    }
    /// The report as JSON text.
    fn to_json(&self) -> String {
        self.inner.to_json()
    }
    /// The report as a short text table, as the arena command prints it.
    fn summary(&self) -> String {
        self.inner.summary()
    }
    /// Writes the report as JSON.
    fn save(&self, path: std::path::PathBuf) -> PyResult<()> {
        self.inner.save(&path).map_err(value_error)
    }
    /// The result of the agent with this name (the first, if two share it) or with this
    /// index in the agents list, as a dict; None if there is none.
    fn result<'py>(
        &self,
        py: Python<'py>,
        agent: &Bound<'py, PyAny>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        let found = if let Ok(index) = agent.extract::<usize>() {
            self.inner.result_of(index)
        } else {
            self.inner.result(&agent.extract::<String>()?)
        };
        let Some(found) = found else {
            return Ok(None);
        };
        let json = serde_json::to_string(found).expect("a result is plain data");
        Ok(Some(py.import("json")?.call_method1("loads", (json,))?))
    }
    fn __str__(&self) -> String {
        self.inner.summary()
    }
    fn __repr__(&self) -> String {
        let results: Vec<String> = self
            .inner
            .results
            .iter()
            .map(|r| format!("{} {:+.2}", r.agent, r.bb_per_100))
            .collect();
        format!(
            "MatchReport({} hands, bb/100: {})",
            self.inner.hands,
            results.join(", ")
        )
    }
}

/// The Rust agents run_match knows by name.
#[pyfunction]
pub fn agents() -> Vec<&'static str> {
    RUST_AGENTS.to_vec()
}

/// Plays a match in the arena and returns its report.
///
/// agents: each a Rust agent's name (agents() lists them) or a Python object with an
/// act(view) method that returns "fold", "check", "call" or ("raise", amount), amount being
/// the total bet of the street. Optional begin_hand(view) and end_hand(view) are called at
/// the start and end of every hand. The name in the report is the object's `name`
/// attribute, or its class name. A Python object listed once but seated at several places
/// plays all of them; pass one object per place to keep them apart.
///
/// players: the table size, 2 to 6; the second agent sits in each seat in turn and the
/// first in all the others. lineup: the agent (an index into agents) at each place, for any
/// other mix. The other settings are the arena's (engine/crates/arena/README.md). threads:
/// None means one thread when a Python agent plays (they take turns holding the GIL
/// anyway) and every core otherwise. aivat: also score the match with AIVAT (each result's
/// "aivat" entry: bb_per_100, se, minus_main and its SE, se_ratio, decisions corrected);
/// the Rust strategy agents (blueprint, search, the lbr chumps) report their chances, so
/// their choices are corrected, a Python agent's are not. aivat_facing: how AIVAT values a
/// bet still to be answered ("minimum-defense", "called" or "taken-back"); aivat_boards:
/// the boards it draws before the flop.
#[pyfunction]
#[pyo3(signature = (agents, deals, seed=1, *, players=2, lineup=None, stack=10_000, small_blind=50,
                    big_blind=100, ante=0, duplicate=true, all_in_equity=true, max_runouts=Some(10_000),
                    shared_randomness=false, threads=None, aivat=true, aivat_facing=None,
                    aivat_boards=None))]
#[allow(clippy::too_many_arguments)]
pub fn run_match(
    py: Python<'_>,
    agents: Vec<Bound<'_, PyAny>>,
    deals: u64,
    seed: u64,
    players: usize,
    lineup: Option<Vec<usize>>,
    stack: Chips,
    small_blind: Chips,
    big_blind: Chips,
    ante: Chips,
    duplicate: bool,
    all_in_equity: bool,
    max_runouts: Option<u32>,
    shared_randomness: bool,
    threads: Option<usize>,
    aivat: bool,
    aivat_facing: Option<String>,
    aivat_boards: Option<u32>,
) -> PyResult<MatchReport> {
    let mut aivat_settings = Aivat::default();
    if let Some(name) = aivat_facing {
        aivat_settings.facing = Facing::parse(&name).ok_or_else(|| {
            PyValueError::new_err(format!(
                "aivat_facing: {name:?} is not one of {}",
                Facing::NAMES.join(", ")
            ))
        })?;
    }
    if let Some(boards) = aivat_boards {
        aivat_settings.boards = boards;
    }
    let failure: Failure = Arc::new(Mutex::new(None));
    let mut list = Vec::with_capacity(agents.len());
    let mut python = false;
    for spec in &agents {
        let (agent, is_python) = agent(spec, &failure)?;
        list.push(agent);
        python |= is_python;
    }
    let lineup = match lineup {
        Some(lineup) => lineup,
        None if players == 2 => vec![0, 1],
        None => {
            let mut places = vec![0; players];
            if let Some(first) = places.first_mut() {
                *first = 1;
            }
            places
        }
    };
    let mut config = MatchConfig::new(&lineup, deals, seed);
    config.stack = stack;
    config.small_blind = small_blind;
    config.big_blind = big_blind;
    config.ante = ante;
    config.duplicate = duplicate;
    config.all_in_equity = all_in_equity;
    config.max_runouts = max_runouts;
    config.shared_randomness = shared_randomness;
    config.threads = threads.unwrap_or(if python { 1 } else { 0 });
    config.aivat = aivat.then_some(aivat_settings);
    let report = py.detach(|| arena_match(&config, &list));
    if let Some(error) = failure.lock().unwrap().take() {
        return Err(error);
    }
    Ok(MatchReport {
        inner: report.map_err(value_error)?,
    })
}
