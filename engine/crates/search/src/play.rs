//! A `Strategy` seated in the arena: at each decision it is asked for its action
//! probabilities at the public state the seat sees, and the action is drawn with
//! `View::pick`, so a match repeats exactly (the same as the py crate's `strategy_agent`).

use std::sync::Arc;

use arena::{Agent, Player, View};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::Action;

use crate::real::rebuild;

pub fn strategy_agent<S>(name: &str, strategy: Arc<S>) -> Agent
where
    S: Strategy + Send + Sync + 'static,
{
    Agent::new(name, move || {
        Box::new(Seated {
            strategy: Arc::clone(&strategy),
            probs: ActionProbs::new(),
        })
    })
}

struct Seated<S> {
    strategy: Arc<S>,
    probs: ActionProbs,
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
}
