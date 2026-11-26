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

/// Plays one hand: `players[seat]` acts for that seat and `seeds[seat]` is its private
/// random number (see [`View::seed`]). The button is the one in `config`.
pub fn play_hand(
    config: &Config,
    deal: Deal,
    players: &mut [Box<dyn Player>],
    seeds: &[u64],
) -> Result<PlayedHand, DealError> {
    let n = config.num_players();
    assert_eq!(players.len(), n, "one player per seat");
    assert_eq!(seeds.len(), n, "one seed per seat");
    let mut state = State::new(config, deal)?;
    for seat in 0..n {
        players[seat].begin_hand(&View::new(&state, seat, seeds[seat]));
    }
    let mut illegal = [0; MAX_PLAYERS];
    while let Some(seat) = state.current_player() {
        let legal = state.legal_actions();
        let mut action = players[seat].act(&View::new(&state, seat, seeds[seat]));
        if !legal.allows(action) {
            illegal[seat] += 1;
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
