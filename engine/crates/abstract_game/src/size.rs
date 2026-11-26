//! How big an abstract game is: decision points, information sets and memory for regrets.
//!
//! The betting tree is counted without building it. What can happen from the start of a
//! street depends only on the street and on the chips already in the pot, so each such
//! starting point is walked once and reused. That makes menus countable whose trees are
//! far too big to store.

use std::collections::HashMap;

use nlhe::{Chips, State, Street};

use crate::menu::Menus;

/// The size of a betting tree, by street (preflop, flop, turn, river).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TreeSize {
    /// Decision points: the betting sequences after which a player has to act.
    pub decisions: [u128; 4],
    /// Actions summed over the decision points: a solver keeps one regret for each of
    /// these per bucket.
    pub actions: [u128; 4],
    /// Sequences that end with a fold.
    pub folds: u128,
    /// Sequences that end at a showdown.
    pub showdowns: u128,
    /// The most actions at one decision point.
    pub max_actions: usize,
    /// The most actions in one hand.
    pub longest: usize,
}

impl TreeSize {
    /// Decision points on all streets.
    pub fn decision_points(&self) -> u128 {
        self.decisions.iter().sum()
    }

    /// Ways a hand can end.
    pub fn terminals(&self) -> u128 {
        self.folds + self.showdowns
    }

    /// Information sets with `buckets[s]` buckets on street `s`: each decision point
    /// once per bucket of its street.
    pub fn info_sets(&self, buckets: [u64; 4]) -> u128 {
        (0..4).map(|s| self.decisions[s] * buckets[s] as u128).sum()
    }

    /// Regrets to store: one per action at every information set.
    pub fn regrets(&self, buckets: [u64; 4]) -> u128 {
        (0..4).map(|s| self.actions[s] * buckets[s] as u128).sum()
    }

    /// Memory for the regrets at `bytes` bytes each. The cfr crate keeps an `f64`
    /// (8 bytes); Pluribus kept 4-byte integers.
    pub fn regret_bytes(&self, buckets: [u64; 4], bytes: u32) -> u128 {
        self.regrets(buckets) * bytes as u128
    }

    /// The last street on which anyone acts.
    pub fn last_street(&self) -> Option<Street> {
        (0..4)
            .rev()
            .find(|&s| self.decisions[s] > 0)
            .map(|s| Street::ALL[s])
    }

    fn add(&mut self, other: &TreeSize) {
        for s in 0..4 {
            self.decisions[s] += other.decisions[s];
            self.actions[s] += other.actions[s];
        }
        self.folds += other.folds;
        self.showdowns += other.showdowns;
        self.max_actions = self.max_actions.max(other.max_actions);
    }
}

/// Counts the betting tree the menus make from `root`, without building it.
pub fn count(root: &State, menus: &Menus) -> TreeSize {
    Counter {
        menus,
        memo: HashMap::new(),
    }
    .walk(root)
}

struct Counter<'a> {
    menus: &'a Menus,
    /// The tree under the first decision of a street, by street and by what each player
    /// has put in so far.
    memo: HashMap<(Street, Chips, Chips), TreeSize>,
}

impl Counter<'_> {
    fn walk(&mut self, state: &State) -> TreeSize {
        if state.is_terminal() {
            let folded = state.is_folded(0) || state.is_folded(1);
            return TreeSize {
                folds: folded as u128,
                showdowns: !folded as u128,
                ..TreeSize::default()
            };
        }
        let mut actions = Vec::new();
        self.menus.actions(state, &mut actions);
        let street = state.street();
        let mut size = TreeSize {
            max_actions: actions.len(),
            ..TreeSize::default()
        };
        size.decisions[street.index()] = 1;
        size.actions[street.index()] = actions.len() as u128;
        let mut longest = 0;
        for &action in &actions {
            let mut next = state.clone();
            next.apply(action)
                .expect("the menus only offer legal actions");
            let below = if !next.is_terminal() && next.street() != street {
                // A new street starts with no bets and nobody having acted: nothing of
                // the path matters any more except the chips put in.
                let key = (next.street(), next.committed()[0], next.committed()[1]);
                match self.memo.get(&key) {
                    Some(&known) => known,
                    None => {
                        let fresh = self.walk(&next);
                        self.memo.insert(key, fresh);
                        fresh
                    }
                }
            } else {
                self.walk(&next)
            };
            size.add(&below);
            longest = longest.max(below.longest);
        }
        size.longest = longest + 1;
        size
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tree::{BettingTree, Next};
    use nlhe::Config;

    fn root(stack: Chips) -> State {
        State::from_seed(&Config::new(&[stack, stack], 50, 100, 0, 0).unwrap(), 9)
    }

    /// The same numbers read off a tree that was built in full.
    fn measured(tree: &BettingTree) -> TreeSize {
        let mut size = TreeSize::default();
        for (id, node) in tree.nodes().iter().enumerate() {
            let n = tree.edges(id as u32).len();
            size.decisions[node.street.index()] += 1;
            size.actions[node.street.index()] += n as u128;
            size.max_actions = size.max_actions.max(n);
        }
        // Endings and the longest line: follow every line down the tree.
        fn follow(tree: &BettingTree, id: u32, depth: usize, size: &mut TreeSize) {
            for edge in tree.edges(id) {
                match edge.next() {
                    Next::Decision(next) => follow(tree, next, depth + 1, size),
                    Next::End(payoff) => {
                        if tree.payoff(payoff).is_showdown() {
                            size.showdowns += 1;
                        } else {
                            size.folds += 1;
                        }
                        size.longest = size.longest.max(depth + 1);
                    }
                }
            }
        }
        follow(tree, 0, 0, &mut size);
        size
    }

    #[test]
    fn push_or_fold_by_hand() {
        let size = count(&root(1_000), &Menus::push_fold());
        assert_eq!(size.decisions, [2, 0, 0, 0]);
        assert_eq!(size.actions, [4, 0, 0, 0]);
        // Fold; jam and fold; jam and call.
        assert_eq!((size.folds, size.showdowns), (2, 1));
        assert_eq!((size.max_actions, size.longest), (2, 2));
        assert_eq!(size.last_street(), Some(Street::Preflop));
        assert_eq!(size.info_sets([169, 0, 0, 0]), 338);
        assert_eq!(size.regrets([169, 0, 0, 0]), 676);
        assert_eq!(size.regret_bytes([169, 0, 0, 0], 8), 5_408);
    }

    #[test]
    fn a_two_big_blind_game_by_hand() {
        // 2 big blinds each, one size. Preflop the small blind folds, calls or goes all
        // in (2.5 big blinds is more than the stack). After call the big blind checks or
        // goes all in; after all in it folds or calls. On each later street the pot is 2
        // and each player has 1 big blind left: the big blind checks or bets it (three
        // quarters of the pot, 1.5, is more than is left), and so on.
        let size = count(&root(200), &Menus::minimal());
        // Preflop: the small blind; the big blind after a limp; the big blind after a
        // jam; the small blind after limp and jam.
        assert_eq!(size.decisions[0], 4);
        assert_eq!(size.actions[0], 3 + 2 + 2 + 2);
        // Each later street, reached only by limp, check and then checks: the big blind
        // (check or bet), the small blind after a check (check or bet), the small blind
        // after a bet (fold or call), the big blind after check and bet (fold or call).
        assert_eq!(size.decisions[1..], [4, 4, 4]);
        assert_eq!(size.actions[1..], [8, 8, 8]);
        // Folds: preflop 3 (open fold, fold to the jam, fold to the jam over the limp),
        // then 2 on each later street.
        assert_eq!(size.folds, 3 + 6);
        // Showdowns: preflop 2 (jam called, limp then jam called), 2 on each later street
        // (bet called, check then bet called) and the river checked through.
        assert_eq!(size.showdowns, 2 + 6 + 1);
        assert_eq!(size.max_actions, 3);
        // Limp, check, then check-check on the flop and the turn, then check, bet, call.
        assert_eq!(size.longest, 2 + 2 + 2 + 3);
        assert_eq!(size.last_street(), Some(Street::River));
        assert_eq!(size.decision_points(), 16);
        assert_eq!(size.terminals(), 18);
        assert_eq!(size.info_sets([169, 10, 10, 10]), 4 * 169 + 120);
    }

    #[test]
    fn counting_agrees_with_the_built_tree() {
        for (stack, menus) in [
            (1_000, Menus::push_fold()),
            (200, Menus::minimal()),
            (2_000, Menus::minimal()),
            (10_000, Menus::minimal()),
            (700, Menus::small()),
            (2_500, Menus::small()),
            (450, Menus::standard()),
            (1_500, Menus::standard()),
            (330, Menus::wide()),
        ] {
            let root = root(stack);
            let tree = BettingTree::build(&root, &menus);
            let size = count(&root, &menus);
            assert_eq!(size, measured(&tree), "stack {stack}");
            assert_eq!(size.decision_points(), tree.len() as u128);
            assert_eq!(
                size.actions.iter().sum::<u128>(),
                tree.num_actions() as u128
            );
        }
    }

    #[test]
    fn more_sizes_and_deeper_stacks_make_bigger_trees() {
        let points = |stack, menus: Menus| count(&root(stack), &menus).decision_points();
        let by_menu = [
            points(10_000, Menus::minimal()),
            points(10_000, Menus::small()),
            points(10_000, Menus::standard()),
            points(10_000, Menus::wide()),
        ];
        assert!(by_menu.windows(2).all(|w| w[0] < w[1]), "{by_menu:?}");
        let by_stack = [
            points(2_000, Menus::standard()),
            points(5_000, Menus::standard()),
            points(10_000, Menus::standard()),
            points(20_000, Menus::standard()),
        ];
        assert!(by_stack.windows(2).all(|w| w[0] < w[1]), "{by_stack:?}");
    }
}
