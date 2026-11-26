//! The interface a strategy offers to be measured (and, later, to play).

use nlhe::{Action, Card};

use crate::public::PublicState;

/// A probability for each action a player may take. Actions not listed have probability 0.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionProbs {
    items: Vec<(Action, f64)>,
}

impl ActionProbs {
    pub fn new() -> ActionProbs {
        ActionProbs::default()
    }

    pub fn clear(&mut self) {
        self.items.clear();
    }

    /// Adds an action. A raise is `Action::RaiseTo(total bet for the street)`.
    pub fn push(&mut self, action: Action, probability: f64) {
        self.items.push((action, probability));
    }

    pub fn as_slice(&self) -> &[(Action, f64)] {
        &self.items
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// The probability of `action` (0 when it is not listed).
    pub fn prob(&self, action: Action) -> f64 {
        self.items
            .iter()
            .filter(|(a, _)| *a == action)
            .map(|(_, p)| p)
            .sum()
    }

    /// The sum of the probabilities, 1 for a complete distribution.
    pub fn total(&self) -> f64 {
        self.items.iter().map(|(_, p)| p).sum()
    }

    /// The action picked by a uniform draw `u` in `[0, 1)`: the first action whose running
    /// total passes `u`. `None` when nothing has a positive probability.
    pub fn sample(&self, u: f64) -> Option<Action> {
        let mut left = u * self.total();
        let mut last = None;
        for &(action, p) in &self.items {
            if p > 0.0 {
                if left < p {
                    return Some(action);
                }
                left -= p;
                last = Some(action);
            }
        }
        last
    }
}

/// A strategy for No-Limit Hold'em: what a player does with each hand in each public state.
///
/// LBR reads the strategy it plays against through this trait, for the hand the opponent
/// really holds and for every hand they could hold. The future blueprint implements it.
pub trait Strategy: Sync {
    /// Writes the probability of each action for the player to act, holding `hole`.
    ///
    /// `out` arrives empty. Every action pushed must be legal in `public`
    /// (`public.legal_actions()`), with a raise given as `Action::RaiseTo(amount)`, and the
    /// probabilities must sum to 1.
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs);

    /// The probability of one `action` for each of `hands` (`out[i]` for `hands[i]`).
    ///
    /// This is what LBR calls, about 1,200 hands at a time, once per opponent action and once
    /// per bet size it considers. The default asks [`Strategy::action_probs`] hand by hand.
    /// Override it when the work shared by all hands (finding the node for this betting
    /// sequence, say) can be done once.
    fn action_prob_for_range(
        &self,
        public: &PublicState<'_>,
        action: Action,
        hands: &[[Card; 2]],
        out: &mut [f64],
    ) {
        let mut probs = ActionProbs::new();
        for (hand, slot) in hands.iter().zip(out.iter_mut()) {
            probs.clear();
            self.action_probs(public, *hand, &mut probs);
            *slot = probs.prob(action);
        }
    }
}

impl<S: Strategy + ?Sized> Strategy for &S {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        (**self).action_probs(public, hole, out)
    }

    fn action_prob_for_range(
        &self,
        public: &PublicState<'_>,
        action: Action,
        hands: &[[Card; 2]],
        out: &mut [f64],
    ) {
        (**self).action_prob_for_range(public, action, hands, out)
    }
}
