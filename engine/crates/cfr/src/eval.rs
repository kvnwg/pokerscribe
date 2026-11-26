//! Exact evaluation for games small enough to walk completely: expected
//! values of a policy profile, best responses, NashConv and exploitability.

use crate::game::{child, Action, Game, Node};
use crate::policy::Policy;
use crate::table::KeyMap;

/// Expected payoff of every player when all of them follow `policy`.
pub fn expected_values<G: Game, P: Policy + ?Sized>(game: &G, policy: &P) -> Vec<f64> {
    let mut out = vec![0.0; game.num_players()];
    ev_walk(game, policy, &game.root(), 1.0, &mut out);
    out
}

fn ev_walk<G: Game, P: Policy + ?Sized>(
    game: &G,
    policy: &P,
    s: &G::State,
    reach: f64,
    out: &mut [f64],
) {
    match game.node(s) {
        Node::Terminal => {
            for (p, o) in out.iter_mut().enumerate() {
                *o += reach * game.utility(s, p);
            }
        }
        Node::Chance => {
            let mut outcomes = Vec::new();
            game.chance_outcomes(s, &mut outcomes);
            for (a, prob) in outcomes {
                ev_walk(game, policy, &child(game, s, a), reach * prob, out);
            }
        }
        Node::Player(_) => {
            let mut actions = Vec::new();
            game.legal_actions(s, &mut actions);
            let mut probs = vec![0.0; actions.len()];
            policy.action_probs(game.info_key(s), &mut probs);
            for (&a, &p) in actions.iter().zip(&probs) {
                if p > 0.0 {
                    ev_walk(game, policy, &child(game, s, a), reach * p, out);
                }
            }
        }
    }
}

/// Value to `player` of a best response against everyone else playing
/// `policy`. Exact: the full tree is walked.
pub fn best_response_value<G: Game, P: Policy + ?Sized>(
    game: &G,
    policy: &P,
    player: usize,
) -> f64 {
    let mut br = BestResponse::new(game, policy, player);
    let root = game.root();
    br.value(&root)
}

/// The best response itself: for every information set of `player`, the
/// index (into the legal actions) of the action it plays.
pub fn best_response_actions<G: Game, P: Policy + ?Sized>(
    game: &G,
    policy: &P,
    player: usize,
) -> KeyMap<usize> {
    let mut br = BestResponse::new(game, policy, player);
    let keys: Vec<_> = br.histories.keys().copied().collect();
    for k in keys {
        br.best_action(k);
    }
    br.memo
}

/// Sum over players of what each gains by switching alone to a best
/// response. Zero exactly at a Nash equilibrium.
pub fn nash_conv<G: Game, P: Policy + ?Sized>(game: &G, policy: &P) -> f64 {
    let ev = expected_values(game, policy);
    (0..game.num_players())
        .map(|p| best_response_value(game, policy, p) - ev[p])
        .sum()
}

/// NashConv divided by the number of players, OpenSpiel's definition. In a
/// two-player zero-sum game this is the mean of the two best-response values.
pub fn exploitability<G: Game, P: Policy + ?Sized>(game: &G, policy: &P) -> f64 {
    nash_conv(game, policy) / game.num_players() as f64
}

struct BestResponse<'a, G: Game, P: Policy + ?Sized> {
    game: &'a G,
    policy: &'a P,
    player: usize,
    /// For each of `player`'s information sets, its histories with their
    /// counterfactual reach (chance times the other players' probabilities).
    histories: KeyMap<Vec<(G::State, f64)>>,
    /// Best action index per information set, filled on demand.
    memo: KeyMap<usize>,
}

impl<'a, G: Game, P: Policy + ?Sized> BestResponse<'a, G, P> {
    fn new(game: &'a G, policy: &'a P, player: usize) -> Self {
        let mut br = BestResponse {
            game,
            policy,
            player,
            histories: KeyMap::default(),
            memo: KeyMap::default(),
        };
        let root = game.root();
        br.collect(&root, 1.0);
        br
    }

    fn collect(&mut self, s: &G::State, reach: f64) {
        match self.game.node(s) {
            Node::Terminal => {}
            Node::Chance => {
                let mut outcomes = Vec::new();
                self.game.chance_outcomes(s, &mut outcomes);
                for (a, p) in outcomes {
                    self.collect(&child(self.game, s, a), reach * p);
                }
            }
            Node::Player(q) => {
                let mut actions = Vec::new();
                self.game.legal_actions(s, &mut actions);
                if q == self.player {
                    self.histories
                        .entry(self.game.info_key(s))
                        .or_default()
                        .push((s.clone(), reach));
                    for &a in &actions {
                        self.collect(&child(self.game, s, a), reach);
                    }
                } else {
                    let mut probs = vec![0.0; actions.len()];
                    self.policy.action_probs(self.game.info_key(s), &mut probs);
                    for (&a, &p) in actions.iter().zip(&probs) {
                        self.collect(&child(self.game, s, a), reach * p);
                    }
                }
            }
        }
    }

    fn actions(&self, s: &G::State) -> Vec<Action> {
        let mut actions = Vec::new();
        self.game.legal_actions(s, &mut actions);
        actions
    }

    fn best_action(&mut self, key: u64) -> usize {
        if let Some(&a) = self.memo.get(&key) {
            return a;
        }
        let hist = std::mem::take(
            self.histories
                .get_mut(&key)
                .expect("unknown information set"),
        );
        let actions = self.actions(&hist[0].0);
        let mut q = vec![0.0; actions.len()];
        for (h, w) in &hist {
            for (i, &a) in actions.iter().enumerate() {
                q[i] += w * self.value(&child(self.game, h, a));
            }
        }
        *self.histories.get_mut(&key).unwrap() = hist;
        let mut best = 0;
        for i in 1..q.len() {
            if q[i] > q[best] {
                best = i;
            }
        }
        self.memo.insert(key, best);
        best
    }

    fn value(&mut self, s: &G::State) -> f64 {
        match self.game.node(s) {
            Node::Terminal => self.game.utility(s, self.player),
            Node::Chance => {
                let mut outcomes = Vec::new();
                self.game.chance_outcomes(s, &mut outcomes);
                outcomes
                    .into_iter()
                    .map(|(a, p)| p * self.value(&child(self.game, s, a)))
                    .sum()
            }
            Node::Player(q) => {
                let actions = self.actions(s);
                if q == self.player {
                    let i = self.best_action(self.game.info_key(s));
                    self.value(&child(self.game, s, actions[i]))
                } else {
                    let mut probs = vec![0.0; actions.len()];
                    self.policy.action_probs(self.game.info_key(s), &mut probs);
                    let mut v = 0.0;
                    for (&a, &p) in actions.iter().zip(&probs) {
                        if p > 0.0 {
                            v += p * self.value(&child(self.game, s, a));
                        }
                    }
                    v
                }
            }
        }
    }
}
