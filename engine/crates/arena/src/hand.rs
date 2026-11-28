//! Playing one hand between players.

use nlhe::{Action, Config, Deal, DealError, State, MAX_PLAYERS};

use crate::player::{Player, View};
use crate::ranker::EvalRanker;

/// A finished hand.
#[derive(Clone, Debug)]
pub struct PlayedHand {
    /// The final state: every card, the whole betting, the stacks.
    pub state: State,
    /// Chips won or lost per seat (final stack minus starting stack). They add up to 0.
    pub payouts: [i64; MAX_PLAYERS],
    /// Illegal actions returned per seat. Each was replaced by a check, or by a fold
    /// when checking was not allowed.
    pub illegal: [u32; MAX_PLAYERS],
}

/// What the players reported at each decision of a hand: the chances their action was
/// drawn with ([`Player::probabilities`]), one entry per move of the history, in order.
/// Kept in one buffer that a worker reuses from hand to hand.
#[derive(Clone, Debug, Default)]
pub struct Decisions {
    /// Per move: the start and end of its chances in `chances`, or `None` when the player
    /// gave none (or its action was illegal and replaced).
    moves: Vec<Option<(u32, u32)>>,
    chances: Vec<(Action, f64)>,
}

impl Decisions {
    pub fn new() -> Decisions {
        Decisions::default()
    }

    pub fn clear(&mut self) {
        self.moves.clear();
        self.chances.clear();
    }

    /// Adds the next move's chances (`None`: not known).
    pub fn push(&mut self, chances: Option<&[(Action, f64)]>) {
        self.moves.push(chances.map(|c| {
            let start = self.chances.len() as u32;
            self.chances.extend_from_slice(c);
            (start, self.chances.len() as u32)
        }));
    }

    /// The number of moves recorded.
    pub fn len(&self) -> usize {
        self.moves.len()
    }

    pub fn is_empty(&self) -> bool {
        self.moves.is_empty()
    }

    /// The chances reported for move `index` of the history, if any.
    pub fn get(&self, index: usize) -> Option<&[(Action, f64)]> {
        self.moves
            .get(index)
            .copied()
            .flatten()
            .map(|(a, b)| &self.chances[a as usize..b as usize])
    }
}

/// Plays one hand: `players[seat]` acts for that seat and `seeds[seat]` is its private
/// random number (see [`View::seed`]). The button is the one in `config`.
pub fn play_hand(
    config: &Config,
    deal: Deal,
    players: &mut [Box<dyn Player>],
    seeds: &[u64],
) -> Result<PlayedHand, DealError> {
    play_hand_recorded(config, deal, players, seeds, &mut Decisions::new())
}

/// [`play_hand`], keeping in `decisions` the chances each player reported for its actions
/// ([`Player::probabilities`]). An action that was illegal, and so replaced, is recorded
/// as having no known chances.
pub fn play_hand_recorded(
    config: &Config,
    deal: Deal,
    players: &mut [Box<dyn Player>],
    seeds: &[u64],
    decisions: &mut Decisions,
) -> Result<PlayedHand, DealError> {
    let n = config.num_players();
    assert_eq!(players.len(), n, "one player per seat");
    assert_eq!(seeds.len(), n, "one seed per seat");
    decisions.clear();
    let mut state = State::new(config, deal)?;
    for seat in 0..n {
        players[seat].begin_hand(&View::new(&state, seat, seeds[seat]));
    }
    let mut illegal = [0; MAX_PLAYERS];
    while let Some(seat) = state.current_player() {
        let legal = state.legal_actions();
        let mut action = players[seat].act(&View::new(&state, seat, seeds[seat]));
        if legal.allows(action) {
            decisions.push(players[seat].probabilities());
        } else {
            illegal[seat] += 1;
            decisions.push(None);
            action = if legal.check {
                Action::Check
            } else {
                Action::Fold
            };
        }
        state
            .apply(action)
            .expect("the action was checked against the legal ones");
    }
    let payouts = state.payouts(&EvalRanker).expect("the hand is over");
    for seat in 0..n {
        players[seat].end_hand(&View::finished(&state, seat, seeds[seat], payouts[seat]));
    }
    Ok(PlayedHand {
        state,
        payouts,
        illegal,
    })
}
