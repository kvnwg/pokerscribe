//! A `Strategy` seated in the arena: at each decision it is asked for its action
//! probabilities at the public state the seat sees, and the action is drawn with
//! `View::pick`, so a match repeats exactly (the same as the py crate's `strategy_agent`).
//! It reports those probabilities (`Player::probabilities`), so the arena's AIVAT can take
//! the luck of its choices out of the result. Seated with [`answering_strategy_agent`], it
//! also says what it would play at situations the hand didn't reach
//! (`Player::chances_at`), and AIVAT values the other player's actions by those answers.

use std::sync::Arc;

use arena::{Agent, Player, View};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::Action;

use crate::real::rebuild;

/// `strategy` seated in the arena as `name`. It gives AIVAT no answers: for the search
/// agent each would be a search.
pub fn strategy_agent<S>(name: &str, strategy: Arc<S>) -> Agent
where
    S: Strategy + Send + Sync + 'static,
{
    seat(name, strategy, false)
}

/// [`strategy_agent`] that also answers AIVAT: what the strategy would play at any
/// situation. Only for a strategy that is cheap to ask and depends on nothing but the
/// situation and its cards, as the blueprint does (the py crate's
/// `answering_strategy_agent`, as in the AIVAT checks of experiments.md).
pub fn answering_strategy_agent<S>(name: &str, strategy: Arc<S>) -> Agent
where
    S: Strategy + Send + Sync + 'static,
{
    seat(name, strategy, true)
}

fn seat<S>(name: &str, strategy: Arc<S>, answers: bool) -> Agent
where
    S: Strategy + Send + Sync + 'static,
{
    Agent::new(name, move || {
        Box::new(Seated {
            strategy: Arc::clone(&strategy),
            probs: ActionProbs::new(),
            answers,
        })
    })
}

struct Seated<S> {
    strategy: Arc<S>,
    probs: ActionProbs,
    answers: bool,
}

impl<S: Strategy + Send + Sync> Player for Seated<S> {
    fn act(&mut self, view: &View<'_>) -> Action {
        let state = rebuild(&view.config(), view.history(), view.board());
        self.probs.clear();
        self.strategy
            .action_probs(&PublicState::new(&state), view.hole(), &mut self.probs);
        let weights: Vec<f64> = self
            .probs
            .as_slice()
            .iter()
            .map(|&(_, p)| p.max(0.0))
            .collect();
        if weights.iter().sum::<f64>() <= 0.0 {
            return Action::RaiseTo(0); // never legal: the arena counts and replaces it
        }
        self.probs.as_slice()[view.pick(&weights)].0
    }

    /// The probabilities the action was drawn from, for AIVAT.
    fn probabilities(&self) -> Option<&[(Action, f64)]> {
        Some(self.probs.as_slice())
    }

    /// What the strategy would play at `view`, when this seat answers.
    fn chances_at(&self, view: &View<'_>, out: &mut Vec<(Action, f64)>) -> bool {
        if !self.answers {
            return false;
        }
        let state = rebuild(&view.config(), view.history(), view.board());
        let mut probs = ActionProbs::new();
        self.strategy
            .action_probs(&PublicState::new(&state), view.hole(), &mut probs);
        out.extend_from_slice(probs.as_slice());
        true
    }
}
