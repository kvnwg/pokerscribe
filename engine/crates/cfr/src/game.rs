//! The game interface every solver works on.

use crate::rng::Rng;

/// An action at a player or chance node. Games pick their own numbering.
pub type Action = u32;

/// An information set key. It must be unique across all players' information
/// sets (include the acting player in it), and every history in one
/// information set must have the same legal actions in the same order.
pub type InfoKey = u64;

/// What kind of node a state is.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Node {
    /// The game is over; read utilities with [`Game::utility`].
    Terminal,
    /// Nature moves, with the probabilities from [`Game::chance_outcomes`].
    Chance,
    /// This player (0-based) is to act.
    Player(usize),
}

/// An n-player, perfect-recall, extensive-form game with explicit chance.
///
/// Solvers never allocate through this trait in steady state: every list is
/// written into a buffer the caller owns and reuses. The caller clears `out`
/// before each call, so implementations only push.
pub trait Game {
    /// A position in the game. Solvers clone it once per child they visit, so
    /// keep it small and heap-free (fixed arrays, no `Vec`) for speed.
    type State: Clone;

    /// Number of players, not counting chance.
    fn num_players(&self) -> usize;

    /// The start of the game.
    fn root(&self) -> Self::State;

    /// Terminal, chance, or which player acts.
    fn node(&self, state: &Self::State) -> Node;

    /// At a chance node: every outcome with its probability (summing to 1).
    fn chance_outcomes(&self, state: &Self::State, out: &mut Vec<(Action, f64)>);

    /// At a player node: the legal actions, in a fixed order.
    fn legal_actions(&self, state: &Self::State, out: &mut Vec<Action>);

    /// Plays `action` (a chance outcome or a legal action) in place.
    fn apply(&self, state: &mut Self::State, action: Action);

    /// At a player node: the acting player's information set key.
    fn info_key(&self, state: &Self::State) -> InfoKey;

    /// At a terminal node: the payoff to `player`.
    fn utility(&self, state: &Self::State, player: usize) -> f64;

    /// At a chance node: draws one outcome. The default enumerates
    /// [`Game::chance_outcomes`] into `scratch`; large games should override it
    /// with a direct sampler (deal a card without listing the deck).
    fn sample_chance(
        &self,
        state: &Self::State,
        rng: &mut Rng,
        scratch: &mut Vec<(Action, f64)>,
    ) -> Action {
        scratch.clear();
        self.chance_outcomes(state, scratch);
        let mut x = rng.next_f64();
        for &(a, p) in scratch.iter() {
            if x < p {
                return a;
            }
            x -= p;
        }
        scratch.last().expect("chance node without outcomes").0
    }

    /// True where negative-regret pruning must not skip actions at this
    /// player node. Pluribus never pruned on the last betting round; poker
    /// games return true there. Actions that end the game are never pruned
    /// whatever this says.
    fn prune_exempt(&self, _state: &Self::State) -> bool {
        false
    }
}

/// The child reached by playing `action` from `state`.
#[inline]
pub fn child<G: Game>(game: &G, state: &G::State, action: Action) -> G::State {
    let mut c = state.clone();
    game.apply(&mut c, action);
    c
}
