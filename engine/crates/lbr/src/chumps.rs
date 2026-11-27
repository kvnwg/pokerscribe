//! Trivial strategies that ignore their cards: the paper's "chumps", used to check LBR.

use nlhe::{Action, Card, Chips, LegalActions, RaiseRange};

use crate::public::PublicState;
use crate::strategy::{ActionProbs, Strategy};

/// Folds whenever there is a bet to fold to, and checks otherwise.
#[derive(Clone, Copy, Debug, Default)]
pub struct AlwaysFold;

/// Checks or calls, always.
#[derive(Clone, Copy, Debug, Default)]
pub struct AlwaysCall;

/// How much [`AlwaysRaise`] raises.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum RaiseSize {
    /// The smallest legal bet or raise.
    #[default]
    Min,
    /// A pot-sized bet or raise.
    Pot,
    /// The whole stack.
    AllIn,
}

/// Bets or raises whenever it may, and calls when it may not.
#[derive(Clone, Copy, Debug, Default)]
pub struct AlwaysRaise {
    pub size: RaiseSize,
}

/// The paper's "1/2 call, 1/2 raise": checks or calls half the time and otherwise raises to
/// an amount drawn evenly from the legal range. Calls when it may not raise.
#[derive(Clone, Copy, Debug, Default)]
pub struct CallOrRaise;

/// A random legal action, in one of two senses.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum UniformRandom {
    /// Every legal action is equally likely, each raise amount counting as its own action.
    /// With thousands of raise amounts this player raises nearly always, to an amount drawn
    /// evenly from the legal range, and folds or calls half and half once it cannot raise.
    /// This reading reproduces the paper's "random" column.
    #[default]
    Actions,
    /// Fold, check or call, and raise are equally likely among those that are legal, and a
    /// raise is to an amount drawn evenly from the legal range.
    Kinds,
}

/// A distribution that does not depend on the cards: fold, check or call, and a raise.
struct Mix {
    fold: f64,
    passive: f64,
    raise: f64,
    target: Target,
}

enum Target {
    None,
    To(Chips),
    /// Every whole amount in the range, equally likely.
    Evenly(RaiseRange),
}

impl Mix {
    fn passive_action(legal: &LegalActions) -> Action {
        if legal.check {
            Action::Check
        } else {
            Action::Call
        }
    }

    fn fill(&self, legal: &LegalActions, out: &mut ActionProbs) {
        if self.fold > 0.0 {
            out.push(Action::Fold, self.fold);
        }
        if self.passive > 0.0 {
            out.push(Mix::passive_action(legal), self.passive);
        }
        match self.target {
            Target::None => {}
            Target::To(to) => out.push(Action::RaiseTo(to), self.raise),
            Target::Evenly(range) => {
                let each = self.raise / (range.max_to - range.min_to + 1) as f64;
                for to in range.min_to..=range.max_to {
                    out.push(Action::RaiseTo(to), each);
                }
            }
        }
    }

    fn prob(&self, legal: &LegalActions, action: Action) -> f64 {
        match action {
            Action::Fold => self.fold,
            Action::Check | Action::Call => {
                if action == Mix::passive_action(legal) {
                    self.passive
                } else {
                    0.0
                }
            }
            Action::RaiseTo(to) => match self.target {
                Target::To(t) if t == to => self.raise,
                Target::Evenly(r) if (r.min_to..=r.max_to).contains(&to) => {
                    self.raise / (r.max_to - r.min_to + 1) as f64
                }
                _ => 0.0,
            },
        }
    }
}

/// A strategy that never looks at its cards: one [`Mix`] per public state.
trait Blind: Sync {
    fn mix(&self, public: &PublicState<'_>, legal: &LegalActions) -> Mix;
}

macro_rules! blind_strategy {
    ($name:ty) => {
        impl Strategy for $name {
            fn action_probs(
                &self,
                public: &PublicState<'_>,
                _hole: [Card; 2],
                out: &mut ActionProbs,
            ) {
                let legal = public.legal_actions();
                self.mix(public, &legal).fill(&legal, out);
            }

            /// The same for every hand, so worked out once.
            fn action_prob_for_range(
                &self,
                public: &PublicState<'_>,
                action: Action,
                _hands: &[[Card; 2]],
                out: &mut [f64],
            ) {
                let legal = public.legal_actions();
                out.fill(self.mix(public, &legal).prob(&legal, action));
            }
        }
    };
}

blind_strategy!(AlwaysFold);
blind_strategy!(AlwaysCall);
blind_strategy!(AlwaysRaise);
blind_strategy!(CallOrRaise);
blind_strategy!(UniformRandom);

impl Blind for AlwaysFold {
    fn mix(&self, _public: &PublicState<'_>, legal: &LegalActions) -> Mix {
        let fold = if legal.fold { 1.0 } else { 0.0 };
        Mix {
            fold,
            passive: 1.0 - fold,
            raise: 0.0,
            target: Target::None,
        }
    }
}

impl Blind for AlwaysCall {
    fn mix(&self, _public: &PublicState<'_>, _legal: &LegalActions) -> Mix {
        Mix {
            fold: 0.0,
            passive: 1.0,
            raise: 0.0,
            target: Target::None,
        }
    }
}

impl Blind for AlwaysRaise {
    fn mix(&self, public: &PublicState<'_>, legal: &LegalActions) -> Mix {
        let Some(range) = legal.raise else {
            return AlwaysCall.mix(public, legal);
        };
        let to = match self.size {
            RaiseSize::Min => range.min_to,
            RaiseSize::AllIn => range.max_to,
            RaiseSize::Pot => {
                let pot_after_call = public.pot() + legal.call.unwrap_or(0);
                (public.max_bet() + pot_after_call).clamp(range.min_to, range.max_to)
            }
        };
        Mix {
            fold: 0.0,
            passive: 0.0,
            raise: 1.0,
            target: Target::To(to),
        }
    }
}

impl Blind for CallOrRaise {
    fn mix(&self, public: &PublicState<'_>, legal: &LegalActions) -> Mix {
        let Some(range) = legal.raise else {
            return AlwaysCall.mix(public, legal);
        };
        Mix {
            fold: 0.0,
            passive: 0.5,
            raise: 0.5,
            target: Target::Evenly(range),
        }
    }
}

impl Blind for UniformRandom {
    fn mix(&self, _public: &PublicState<'_>, legal: &LegalActions) -> Mix {
        // How many actions each kind stands for.
        let raises = match (self, legal.raise) {
            (_, None) => 0.0,
            (UniformRandom::Kinds, Some(_)) => 1.0,
            (UniformRandom::Actions, Some(r)) => (r.max_to - r.min_to + 1) as f64,
        };
        let folds = if legal.fold { 1.0 } else { 0.0 };
        let all = folds + 1.0 + raises;
        Mix {
            fold: folds / all,
            passive: 1.0 / all,
            raise: raises / all,
            target: legal.raise.map_or(Target::None, Target::Evenly),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nlhe::{Config, State};

    /// Every chump's list is legal, sums to 1 and agrees with its per-hand shortcut.
    #[test]
    fn distributions_are_legal_and_complete() {
        let config = Config::new(&[20_000, 20_000], 50, 100, 0, 0).unwrap();
        let chumps: [(&str, &dyn Strategy); 8] = [
            ("fold", &AlwaysFold),
            ("call", &AlwaysCall),
            (
                "raise min",
                &AlwaysRaise {
                    size: RaiseSize::Min,
                },
            ),
            (
                "raise pot",
                &AlwaysRaise {
                    size: RaiseSize::Pot,
                },
            ),
            (
                "raise all in",
                &AlwaysRaise {
                    size: RaiseSize::AllIn,
                },
            ),
            ("call or raise", &CallOrRaise),
            ("random action", &UniformRandom::Actions),
            ("random kind", &UniformRandom::Kinds),
        ];
        // Facing the blind, facing a raise, first to act after the flop, facing an all-in.
        let lines: [&[Action]; 4] = [
            &[],
            &[Action::RaiseTo(300)],
            &[Action::Call, Action::Check],
            &[Action::RaiseTo(20_000)],
        ];
        for (name, chump) in chumps {
            for line in lines {
                let mut state = State::from_seed(&config, 5);
                for &a in line {
                    state.apply(a).unwrap();
                }
                let public = PublicState::new(&state);
                let legal = public.legal_actions();
                let mut probs = ActionProbs::new();
                chump.action_probs(&public, [0, 1], &mut probs);
                assert!((probs.total() - 1.0).abs() < 1e-9, "{name} after {line:?}");
                for &(action, p) in probs.as_slice() {
                    assert!(legal.allows(action) && p > 0.0, "{name}: {action}");
                }
                for action in [
                    Action::Fold,
                    Action::Check,
                    Action::Call,
                    Action::RaiseTo(200),
                    Action::RaiseTo(777),
                    Action::RaiseTo(20_000),
                ] {
                    let mut one = [f64::NAN];
                    chump.action_prob_for_range(&public, action, &[[0, 1]], &mut one);
                    assert!(
                        (one[0] - probs.prob(action)).abs() < 1e-12,
                        "{name} after {line:?}: {action}"
                    );
                }
            }
        }
    }

    #[test]
    fn pot_raise_is_the_usual_size() {
        // Blinds 50 and 100: a pot-sized raise first in is to 300 (call 50, raise by 200).
        let config = Config::new(&[20_000, 20_000], 50, 100, 0, 0).unwrap();
        let state = State::from_seed(&config, 5);
        let mut probs = ActionProbs::new();
        AlwaysRaise {
            size: RaiseSize::Pot,
        }
        .action_probs(&PublicState::new(&state), [0, 1], &mut probs);
        assert_eq!(probs.as_slice(), [(Action::RaiseTo(300), 1.0)]);
    }
}
