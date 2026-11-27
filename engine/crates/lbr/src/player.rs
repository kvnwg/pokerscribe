//! The LBR player: range tracking and the local best response decision.

use nlhe::{Action, Card, Chips, RaiseRange, Rng, State};

use crate::config::{BetSize, LbrConfig, PreflopEquity, StreetPolicy};
use crate::equity::{preflop_equities, preflop_equities_sampled, showdown_equities, EquityTable};
use crate::public::PublicState;
use crate::range::{card_mask, combo_cards, Range, NUM_COMBOS};
use crate::strategy::Strategy;

/// What LBR worked out at one decision.
#[derive(Clone, Debug, PartialEq)]
pub struct Evaluation {
    /// The action LBR takes.
    pub action: Action,
    /// The probability of winning a checked-down hand against the opponent's range. `None`
    /// on a street where LBR only checks or calls.
    pub win_probability: Option<f64>,
    /// Each action weighed, with its estimated value in chips. Folding is 0. Empty on a
    /// street where LBR only checks or calls.
    pub options: Vec<(Action, f64)>,
}

/// One seat of a heads-up hand played by local best response.
///
/// Tell it every opponent action with [`Lbr::observe`] before the action is applied, and ask
/// it for its own with [`Lbr::act`].
#[derive(Clone)]
pub struct Lbr<'a> {
    config: &'a LbrConfig,
    opponent: &'a dyn Strategy,
    seat: usize,
    hole: [Card; 2],
    range: Range,
    equities: EquityTable,
    /// The number of board cards `equities` was worked out for.
    equities_for: Option<usize>,
    rng: Rng,
    // Buffers: the hands of the range still possible, and one probability for each.
    live: Vec<u16>,
    hands: Vec<[Card; 2]>,
    probs: Vec<f64>,
    targets: Vec<Chips>,
}

impl<'a> Lbr<'a> {
    /// LBR in `seat` holding `hole`, against `opponent`'s strategy. The opponent starts
    /// equally likely to hold any hand without LBR's cards. `seed` only matters with
    /// [`PreflopEquity::Sampled`].
    pub fn new(
        config: &'a LbrConfig,
        opponent: &'a dyn Strategy,
        seat: usize,
        hole: [Card; 2],
        seed: u64,
    ) -> Lbr<'a> {
        Lbr::with_range(config, opponent, seat, hole, Range::uniform(), seed)
    }

    /// As [`Lbr::new`], but the opponent starts with `range` (less the hands holding one of
    /// LBR's cards). For play that starts in the middle of a hand.
    pub fn with_range(
        config: &'a LbrConfig,
        opponent: &'a dyn Strategy,
        seat: usize,
        hole: [Card; 2],
        mut range: Range,
        seed: u64,
    ) -> Lbr<'a> {
        assert!(seat < 2, "LBR is heads-up: seat 0 or 1");
        range.remove_cards(card_mask(&hole));
        range.normalize();
        Lbr {
            config,
            opponent,
            seat,
            hole,
            range,
            equities: [0.0; NUM_COMBOS],
            equities_for: None,
            rng: Rng::new(seed),
            live: Vec::new(),
            hands: Vec::new(),
            probs: Vec::new(),
            targets: Vec::new(),
        }
    }

    pub fn seat(&self) -> usize {
        self.seat
    }

    pub fn hole(&self) -> [Card; 2] {
        self.hole
    }

    /// The opponent's range as LBR sees it now (weights summing to 1).
    pub fn range(&self) -> &Range {
        &self.range
    }

    /// Drops the hands the board has made impossible and lists the rest.
    fn list_live_hands(&mut self, board: &[Card]) {
        if self.range.remove_cards(card_mask(board)) {
            self.range.normalize();
        }
        self.live.clear();
        self.hands.clear();
        for (i, _) in self.range.live() {
            self.live.push(i as u16);
            self.hands.push(combo_cards(i));
        }
        self.probs.resize(self.hands.len(), 0.0);
    }

    /// Bayes' rule: the opponent, to act in `state`, took `action`. Each hand's weight is
    /// multiplied by the probability their strategy gives that action with that hand.
    ///
    /// Call it before applying the action to the state. If the strategy gives the action no
    /// probability with any hand, the range is left as it was.
    pub fn observe(&mut self, state: &State, action: Action) {
        debug_assert_eq!(state.current_player(), Some(1 - self.seat));
        self.list_live_hands(state.board());
        if self.hands.is_empty() {
            return;
        }
        self.opponent.action_prob_for_range(
            &PublicState::new(state),
            action,
            &self.hands,
            &mut self.probs,
        );
        let weights = self.range.weights_mut();
        let total: f64 = self
            .live
            .iter()
            .zip(&self.probs)
            .map(|(&i, &p)| weights[i as usize] * p)
            .sum();
        if total > 0.0 {
            for (&i, &p) in self.live.iter().zip(&self.probs) {
                weights[i as usize] *= p / total;
            }
        }
    }

    fn refresh_equities(&mut self, board: &[Card]) {
        if self.equities_for == Some(board.len()) {
            return;
        }
        if !board.is_empty() {
            showdown_equities(self.hole, board, &mut self.equities);
        } else {
            match self.config.preflop_equity {
                PreflopEquity::Exhaustive => preflop_equities(self.hole, &mut self.equities),
                PreflopEquity::Sampled { boards } => {
                    preflop_equities_sampled(self.hole, boards, &mut self.rng, &mut self.equities)
                }
            }
        }
        self.equities_for = Some(board.len());
    }

    /// LBR's action in `state`, where it is LBR's turn.
    pub fn act(&mut self, state: &State) -> Action {
        self.evaluate(state).action
    }

    /// LBR's action in `state` with the numbers behind it (the paper's Figure 1).
    pub fn evaluate(&mut self, state: &State) -> Evaluation {
        assert_eq!(state.num_players(), 2, "LBR is heads-up");
        assert_eq!(
            state.current_player(),
            Some(self.seat),
            "it is not LBR's turn"
        );
        let legal = state.legal_actions();
        let passive = if legal.check {
            Action::Check
        } else {
            Action::Call
        };
        let config = self.config;
        let StreetPolicy::Local { bets } = &config.streets[state.street().index()] else {
            return Evaluation {
                action: passive,
                win_probability: None,
                options: Vec::new(),
            };
        };

        self.list_live_hands(state.board());
        self.refresh_equities(state.board());
        let (me, opp) = (self.seat, 1 - self.seat);
        let in_me = state.committed()[me] as f64;
        let in_opp = state.committed()[opp] as f64;
        // What folding gives up: everything in the middle.
        let pot = in_me + in_opp;

        let weights = self.range.weights();
        let (mut total, mut won) = (0.0, 0.0);
        for &i in &self.live {
            let w = weights[i as usize];
            total += w;
            won += w * self.equities[i as usize];
        }
        // Without a single possible hand there is nothing to go on: call it a coin flip.
        let wp = if total > 0.0 { won / total } else { 0.5 };

        // Check or call, then no more betting: win what is in the pot (only the part of the
        // opponent's bet we can match, if we are the shorter stack) or lose what we add.
        let mut options = Vec::with_capacity(1 + bets.len());
        let added = legal.call.unwrap_or(0) as f64;
        let matched = in_opp.min(in_me + added);
        options.push((passive, wp * (in_me + matched) - (1.0 - wp) * added));

        // A bet or raise: the opponent folds as their strategy says, and otherwise calls
        // and the hand is checked down against the hands that did not fold.
        if let Some(range) = legal.raise {
            raise_targets(bets, state, me, range, &mut self.targets);
            let reach_opp = in_opp + state.stacks()[opp] as f64;
            for k in 0..self.targets.len() {
                let to = self.targets[k];
                let mut next = state.clone();
                next.apply(Action::RaiseTo(to))
                    .expect("a raise inside the legal range");
                self.opponent.action_prob_for_range(
                    &PublicState::new(&next),
                    Action::Fold,
                    &self.hands,
                    &mut self.probs,
                );
                let (mut folds, mut stays, mut stays_won) = (0.0, 0.0, 0.0);
                for (&i, &fold) in self.live.iter().zip(&self.probs) {
                    let w = weights[i as usize];
                    folds += w * fold;
                    stays += w * (1.0 - fold);
                    stays_won += w * (1.0 - fold) * self.equities[i as usize];
                }
                let fp = if total > 0.0 { folds / total } else { 0.0 };
                let wp_called = if stays > 0.0 { stays_won / stays } else { 0.0 };
                // Chips we have in if called: no more than the opponent can match.
                let in_called = (in_me + (to - state.bets()[me]) as f64).min(reach_opp);
                let value = fp * pot
                    + (1.0 - fp)
                        * (wp_called * (in_me + in_called)
                            - (1.0 - wp_called) * (in_called - in_me));
                options.push((Action::RaiseTo(to), value));
            }
        }

        // The best action if it beats folding (the first of equals: call, then smaller bets).
        let mut best = options[0];
        for &option in &options[1..] {
            if option.1 > best.1 {
                best = option;
            }
        }
        let action = if best.1 > 0.0 {
            best.0
        } else if legal.fold {
            Action::Fold
        } else {
            passive
        };
        Evaluation {
            action,
            win_probability: Some(wp),
            options,
        }
    }
}

/// The amounts to raise to for `bets`, inside the legal range, in rising order, each once.
fn raise_targets(
    bets: &[BetSize],
    state: &State,
    me: usize,
    range: RaiseRange,
    out: &mut Vec<Chips>,
) {
    out.clear();
    let to_call = (state.max_bet() - state.bets()[me]) as f64;
    let pot_after_call = state.pot() as f64 + to_call;
    for bet in bets {
        let to = match *bet {
            BetSize::AllIn => range.max_to,
            BetSize::Pot(fraction) => {
                let to = state.max_bet() as f64 + fraction * pot_after_call;
                to.round().clamp(range.min_to as f64, range.max_to as f64) as Chips
            }
        };
        out.push(to);
    }
    out.sort_unstable();
    out.dedup();
}
