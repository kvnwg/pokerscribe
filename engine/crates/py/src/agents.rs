//! The Rust agents Python can name in `run_match`, and the adapters that make one.
//!
//! Two kinds of Rust agent can play in the arena:
//!
//! - a [`Player`] (the arena's trait: it is shown a [`View`] and returns an action), made an
//!   agent with [`Agent::of`] or [`Agent::new`];
//! - a [`Strategy`] (LBR's trait: a probability for each action), made an agent with
//!   [`strategy_agent`], which draws its action with [`View::pick`].
//!
//! [`rust_agent`] is the list Python chooses from. To let Python play a new agent, add one
//! line to it. The blueprint is named by its strategy file: `blueprint:<file>`
//! ([`blueprint_agent`]), and so is the search agent on top of it: `search:<file>`
//! ([`search_agent`]).

use std::path::Path;
use std::sync::Arc;

use arena::{bots, Agent, Player, View};
use lbr::{
    ActionProbs, AlwaysCall, AlwaysFold, AlwaysRaise, CallOrRaise, PublicState, RaiseSize,
    Strategy, UniformRandom,
};
use nlhe::{Action, Card, Deal, State, MAX_PLAYERS};

/// The agents [`rust_agent`] knows, in the order `agents()` lists them.
pub const RUST_AGENTS: [&str; 15] = [
    // the arena's test bots (engine/crates/arena/src/bots.rs)
    "fold",
    "call",
    "raise",
    "minraise",
    "jam",
    "random",
    "tag",
    "tag-loose",
    "mixed",
    "mixed-loose",
    // LBR's chumps (engine/crates/lbr/src/chumps.rs), played through their Strategy
    "lbr-fold",
    "lbr-call",
    "lbr-jam",
    "lbr-call-or-raise",
    "lbr-random",
];

/// A Rust agent by name (see [`RUST_AGENTS`]), or `None` for a name it doesn't know.
///
/// The hook for the agents to come: a [`Player`] goes in as `Agent::of(name, player)`, a
/// [`Strategy`] as `strategy_agent(name, strategy)`. Both are copied into every seat and
/// thread the arena needs, so share big tables through an `Arc`.
pub fn rust_agent(name: &str) -> Option<Agent> {
    if let Some(agent) = bots::builtin(name) {
        return Some(agent);
    }
    if let Some(made) = blueprint_agent(name) {
        return made.ok();
    }
    if let Some(made) = search_agent(name) {
        return made.ok();
    }
    Some(match name {
        "lbr-fold" => strategy_agent(name, AlwaysFold),
        "lbr-call" => strategy_agent(name, AlwaysCall),
        "lbr-jam" => strategy_agent(
            name,
            AlwaysRaise {
                size: RaiseSize::AllIn,
            },
        ),
        "lbr-call-or-raise" => strategy_agent(name, CallOrRaise),
        "lbr-random" => strategy_agent(name, UniformRandom::Kinds),
        _ => return None,
    })
}

/// The agent a name `blueprint:<file>` asks for: the blueprint in that strategy file
/// (engine/crates/blueprint), with the bucket tables it was trained with (the directory
/// the file records), played through [`strategy_agent`]. `blueprint:<file>?tables=<dir>`
/// loads the tables from `dir` instead, for a file trained on another machine; they must
/// still be the same tables (the file's checksums are checked). `None` for any other
/// name; an error when the file or its tables can't be loaded. Play it at the stacks and
/// blinds it was trained for (`blueprint info <file>` shows them).
pub fn blueprint_agent(name: &str) -> Option<Result<Agent, String>> {
    let rest = name.strip_prefix("blueprint:")?;
    let (path, tables) = match rest.rsplit_once("?tables=") {
        Some((path, tables)) => (path, Some(Path::new(tables))),
        None => (rest, None),
    };
    Some(
        blueprint::Blueprint::load(Path::new(path), tables)
            .map(|b| strategy_agent(name, b))
            .map_err(|e| format!("{name}: {e}")),
    )
}

/// The agent a name `search:<file>` asks for: depth-limited search (engine/crates/search)
/// on the blueprint in that strategy file, with the leaf tables `<file>.leaf` when they are
/// there (`search leaf --strategy <file>` builds them; without them the flop's leaves are
/// checked down), and the search crate's default settings. `None` for any other name; an
/// error when the file, its bucket tables or its leaf tables can't be loaded. Like the
/// blueprint, play it at the stacks and blinds it was trained for.
pub fn search_agent(name: &str) -> Option<Result<Agent, String>> {
    let path = name.strip_prefix("search:")?;
    Some(
        search::SearchAgent::load(Path::new(path), search::Settings::default())
            // It reports the chances it played with, but answering for situations the
            // hand didn't reach would mean a search for each one (seconds): AIVAT asks
            // only the chances it played with.
            .map(|s| strategy_agent_with(name, s, false))
            .map_err(|e| format!("{name}: {e}")),
    )
}

/// An agent that plays a [`Strategy`]: at each decision it asks the strategy for its action
/// probabilities and draws one with [`View::pick`], so a match repeats exactly. It reports
/// the probabilities ([`Player::probabilities`]), so AIVAT corrects its choices, and says
/// what the strategy would play at any other situation ([`Player::chances_at`]), so AIVAT
/// values the other players' actions by its answers. For a strategy that is cheap to ask
/// and depends only on the public state and the cards, as a blueprint does.
pub fn strategy_agent<S>(name: &str, strategy: S) -> Agent
where
    S: Strategy + Send + 'static,
{
    strategy_agent_with(name, strategy, true)
}

/// [`strategy_agent`], answering for other situations only when `answers` is true.
pub fn strategy_agent_with<S>(name: &str, strategy: S, answers: bool) -> Agent
where
    S: Strategy + Send + 'static,
{
    let strategy = Arc::new(strategy);
    Agent::new(name, move || {
        Box::new(StrategyPlayer {
            strategy: Arc::clone(&strategy),
            probs: ActionProbs::new(),
            weights: Vec::new(),
            answers,
        })
    })
}

/// A [`Strategy`] seated at the table.
pub struct StrategyPlayer<S> {
    strategy: Arc<S>,
    probs: ActionProbs,
    weights: Vec<f64>,
    answers: bool,
}

impl<S: Strategy + Send> Player for StrategyPlayer<S> {
    fn act(&mut self, view: &View<'_>) -> Action {
        let state = visible_state(view);
        self.probs.clear();
        self.strategy
            .action_probs(&PublicState::new(&state), view.hole(), &mut self.probs);
        self.weights.clear();
        self.weights
            .extend(self.probs.as_slice().iter().map(|&(_, p)| p.max(0.0)));
        if self.weights.iter().sum::<f64>() <= 0.0 {
            // An empty distribution breaks the Strategy contract: hand back an action that
            // is never legal, so the arena counts it (as an illegal action) and replaces it.
            return Action::RaiseTo(0);
        }
        self.probs.as_slice()[view.pick(&self.weights)].0
    }

    /// The strategy's probabilities: the action was drawn from them with `View::pick`, so
    /// AIVAT can take the luck of this agent's choices out of its result.
    fn probabilities(&self) -> Option<&[(Action, f64)]> {
        Some(self.probs.as_slice())
    }

    /// What the strategy plays at any view: AIVAT values an action by these answers.
    fn chances_at(&self, view: &View<'_>, out: &mut Vec<(Action, f64)>) -> bool {
        if !self.answers {
            return false;
        }
        let state = visible_state(view);
        let mut probs = ActionProbs::new();
        self.strategy
            .action_probs(&PublicState::new(&state), view.hole(), &mut probs);
        out.extend_from_slice(probs.as_slice());
        true
    }
}

/// What `view` shows, as an nlhe [`State`]: the same table, the same betting and the same
/// board cards face up, this seat's own cards, and at a showdown the cards turned up
/// ([`View::shown`]). Every other card (the other seats' hole cards, the board still to
/// come) is made up: the lowest cards not in sight. A [`PublicState`] of it is the public
/// situation for a [`Strategy`]; the Python `View` is built on it, so the real hidden cards
/// never reach Python.
pub fn visible_state(view: &View<'_>) -> State {
    let n = view.num_players();
    let shown: Vec<Option<[Card; 2]>> = (0..n).map(|seat| view.shown(seat)).collect();
    let mut used = 0u64;
    for &c in shown.iter().flatten().flatten().chain(view.board()) {
        used |= 1 << c;
    }
    let mut spare = (0..52 as Card).filter(move |&c| used & (1 << c) == 0);
    let mut hole = [[0 as Card; 2]; MAX_PLAYERS];
    for (pair, seen) in hole.iter_mut().zip(&shown) {
        *pair = match seen {
            Some(cards) => *cards,
            None => [spare.next().unwrap(), spare.next().unwrap()],
        };
    }
    let mut board = [0 as Card; 5];
    for (k, slot) in board.iter_mut().enumerate() {
        *slot = match view.board().get(k) {
            Some(&c) => c,
            None => spare.next().unwrap(),
        };
    }
    let deal = Deal::new(&hole[..n], board).expect("distinct cards");
    let mut state = State::new(&view.config(), deal).expect("a valid deal");
    for m in view.history() {
        state.apply(m.action).expect("the history was legal");
    }
    state
}
