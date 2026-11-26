//! The betting tree: every sequence of abstract actions, built once by playing the menus
//! through the `nlhe` rules. Cards do not change what may be bet, so one tree serves every
//! deal. Each decision point gets a number, which is what makes information set keys exact,
//! and each way a hand can end carries the payoffs `nlhe` gives for it, so that playing a
//! hand at training time is a walk down the tree.

use std::cmp::Ordering;
use std::collections::HashMap;

use nlhe::{Action, Card, HandRanker, State, Street};

use crate::menu::Menus;

/// Flag in an edge's target: the action ends the hand.
const END: u32 = 1 << 31;

/// The most decision points a tree can number.
pub const MAX_DECISIONS: usize = END as usize;

/// Where an action leads.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Next {
    /// To this decision point.
    Decision(u32),
    /// The hand is over, with this payoff (an index for [`BettingTree::payoff`]).
    End(u32),
}

/// One decision point: who acts, on which street, and where its actions are stored.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Node {
    /// 0 is the small blind (the button), 1 the big blind.
    pub player: u8,
    pub street: Street,
    len: u16,
    first: u32,
    /// The decision point before this one and which of its actions led here (the root
    /// points at itself).
    parent: u32,
    via: u16,
}

/// One action at a decision point and where it leads.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Edge {
    /// The action in the real game.
    pub action: Action,
    target: u32,
}

impl Edge {
    pub fn next(&self) -> Next {
        if self.target & END != 0 {
            Next::End(self.target & !END)
        } else {
            Next::Decision(self.target)
        }
    }
}

/// How a showdown comes out.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Showdown {
    /// The small blind (player 0) has the better hand.
    SmallBlind = 0,
    Tie = 1,
    /// The big blind (player 1) has the better hand.
    BigBlind = 2,
}

/// What each player wins or loses in chips at one ending of the hand, for each way a
/// showdown can come out. After a fold the three rows are the same.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Payoff {
    /// `chips[result][player]`, with `result` a [`Showdown`] as an index.
    pub chips: [[i64; 2]; 3],
}

impl Payoff {
    /// True when the cards decide who wins: the hand went to showdown.
    pub fn is_showdown(&self) -> bool {
        self.chips[0] != self.chips[2]
    }
}

/// A ranker that makes one player's hand the best, the worst, or equal: `nlhe` then says
/// what that outcome pays, pots, returned bets and odd chips included.
struct Fixed {
    /// A card only the small blind holds.
    small_blind_card: Card,
    result: Showdown,
}

impl HandRanker for Fixed {
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        let small_blind = cards.contains(&self.small_blind_card);
        match (self.result, small_blind) {
            (Showdown::Tie, _) => 1,
            (Showdown::SmallBlind, true) | (Showdown::BigBlind, false) => 2,
            _ => 1,
        }
    }
}

/// The payoffs of a finished hand for each showdown result, from `nlhe`.
fn payoff_of(state: &State) -> Payoff {
    let mut chips = [[0i64; 2]; 3];
    let results = [Showdown::SmallBlind, Showdown::Tie, Showdown::BigBlind];
    for (row, result) in chips.iter_mut().zip(results) {
        let ranker = Fixed {
            small_blind_card: state.hole_cards(0)[0],
            result,
        };
        let won = state.payouts(&ranker).expect("the hand is over");
        *row = [won[0], won[1]];
    }
    Payoff { chips }
}

/// All decision points of an abstract game, numbered from the root (0) in the order a
/// depth-first walk meets them.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BettingTree {
    nodes: Vec<Node>,
    edges: Vec<Edge>,
    payoffs: Vec<Payoff>,
}

impl BettingTree {
    /// Walks every line of play the menus allow from `root`, a heads-up hand. The tree is
    /// empty when `root` is already over.
    pub fn build(root: &State, menus: &Menus) -> BettingTree {
        assert_eq!(root.num_players(), 2, "the betting tree is heads-up");
        let mut tree = BettingTree::default();
        let mut known = HashMap::new();
        if !root.is_terminal() {
            tree.grow(root, menus, 0, 0, &mut known);
        }
        tree
    }

    fn grow(
        &mut self,
        state: &State,
        menus: &Menus,
        parent: u32,
        via: u16,
        known: &mut HashMap<Payoff, u32>,
    ) -> u32 {
        let Some(player) = state.current_player() else {
            // The same few payoffs end most lines: keep one copy of each.
            let payoff = payoff_of(state);
            let id = *known.entry(payoff).or_insert_with(|| {
                self.payoffs.push(payoff);
                (self.payoffs.len() - 1) as u32
            });
            return END | id;
        };
        let mut actions = Vec::new();
        menus.actions(state, &mut actions);
        assert!(!actions.is_empty(), "a player to act has an action");
        assert!(self.nodes.len() < MAX_DECISIONS, "too many decision points");
        let id = self.nodes.len() as u32;
        let first = self.edges.len();
        self.nodes.push(Node {
            player: player as u8,
            street: state.street(),
            len: actions.len() as u16,
            first: u32::try_from(first).expect("more than 2^32 actions"),
            parent,
            via,
        });
        self.edges
            .extend(actions.iter().map(|&action| Edge { action, target: 0 }));
        for (i, &action) in actions.iter().enumerate() {
            let mut next = state.clone();
            next.apply(action)
                .expect("the menus only offer legal actions");
            self.edges[first + i].target = self.grow(&next, menus, id, i as u16, known);
        }
        id
    }

    /// Number of decision points.
    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    /// Total number of actions over all decision points.
    pub fn num_actions(&self) -> usize {
        self.edges.len()
    }

    pub fn node(&self, id: u32) -> &Node {
        &self.nodes[id as usize]
    }

    /// The decision points in order; the index is the id.
    pub fn nodes(&self) -> &[Node] {
        &self.nodes
    }

    /// The actions at a decision point: fold, check or call, then raises by size.
    pub fn edges(&self, id: u32) -> &[Edge] {
        let node = &self.nodes[id as usize];
        &self.edges[node.first as usize..node.first as usize + node.len as usize]
    }

    /// The payoff of an ending, by the index in [`Next::End`].
    pub fn payoff(&self, id: u32) -> &Payoff {
        &self.payoffs[id as usize]
    }

    /// The different payoffs a hand can end with.
    pub fn payoffs(&self) -> &[Payoff] {
        &self.payoffs
    }

    /// Where `action` leads from decision point `id`, or `None` when the action is not
    /// offered there.
    pub fn next(&self, id: u32, action: Action) -> Option<Next> {
        self.edges(id)
            .iter()
            .find(|e| e.action == action)
            .map(|e| e.next())
    }

    /// The decision point reached from the root by `line`, if the line is in the tree
    /// and the hand is not over after it.
    pub fn find(&self, line: &[Action]) -> Option<u32> {
        if self.is_empty() {
            return None;
        }
        let mut id = 0;
        for &action in line {
            match self.next(id, action)? {
                Next::Decision(next) => id = next,
                Next::End(_) => return None,
            }
        }
        Some(id)
    }

    /// The actions that lead from the root to decision point `id`, in order.
    pub fn line(&self, id: u32) -> Vec<Action> {
        let mut line = Vec::new();
        let mut at = id;
        while at != 0 {
            let node = &self.nodes[at as usize];
            line.push(self.edges(node.parent)[node.via as usize].action);
            at = node.parent;
        }
        line.reverse();
        line
    }
}

impl Showdown {
    /// The result when the small blind's hand compares this way with the big blind's.
    pub fn from_ordering(small_blind_against_big_blind: Ordering) -> Showdown {
        match small_blind_against_big_blind {
            Ordering::Greater => Showdown::SmallBlind,
            Ordering::Equal => Showdown::Tie,
            Ordering::Less => Showdown::BigBlind,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nlhe::Config;
    use Action::{Call, Check, Fold, RaiseTo};

    fn root(stack: u32, seed: u64) -> State {
        State::from_seed(&Config::new(&[stack, stack], 50, 100, 0, 0).unwrap(), seed)
    }

    #[test]
    fn push_or_fold_has_two_decision_points() {
        let tree = BettingTree::build(&root(1_000, 3), &Menus::push_fold());
        assert_eq!(tree.len(), 2);
        assert_eq!(tree.num_actions(), 4);
        assert_eq!(tree.node(0).player, 0);
        assert_eq!(tree.node(1).player, 1);
        assert_eq!(tree.node(1).street, Street::Preflop);
        let actions = |id| tree.edges(id).iter().map(|e| e.action).collect::<Vec<_>>();
        assert_eq!(actions(0), [Fold, RaiseTo(1_000)]);
        assert_eq!(actions(1), [Fold, Call]);
        assert_eq!(tree.next(0, RaiseTo(1_000)), Some(Next::Decision(1)));
        assert_eq!(tree.next(0, Call), None);
        assert_eq!(tree.find(&[]), Some(0));
        assert_eq!(tree.find(&[RaiseTo(1_000)]), Some(1));
        assert_eq!(tree.find(&[Fold]), None);
        assert_eq!(tree.find(&[Call]), None);
        assert_eq!(tree.find(&[RaiseTo(1_000), Call, Check]), None);
        assert_eq!(tree.line(1), [RaiseTo(1_000)]);
        assert!(tree.line(0).is_empty());

        // Three ways to end, in chips: the small blind folds its 50; the big blind folds
        // its 100; a showdown for the 1,000 chip stacks.
        let payoff = |id, action| match tree.next(id, action) {
            Some(Next::End(p)) => *tree.payoff(p),
            other => panic!("{other:?}"),
        };
        assert_eq!(payoff(0, Fold).chips, [[-50, 50]; 3]);
        assert_eq!(payoff(1, Fold).chips, [[100, -100]; 3]);
        assert_eq!(
            payoff(1, Call).chips,
            [[1_000, -1_000], [0, 0], [-1_000, 1_000]]
        );
        assert!(payoff(1, Call).is_showdown() && !payoff(1, Fold).is_showdown());
        assert_eq!(tree.payoffs().len(), 3);
    }

    #[test]
    fn the_tree_does_not_depend_on_the_cards() {
        let a = BettingTree::build(&root(600, 1), &Menus::small());
        let b = BettingTree::build(&root(600, 2), &Menus::small());
        assert!(a.len() > 100);
        assert_eq!(a, b);
    }

    #[test]
    fn the_big_blind_acts_first_after_the_flop() {
        let tree = BettingTree::build(&root(2_000, 1), &Menus::minimal());
        let flop = tree.find(&[Call, Check]).unwrap();
        assert_eq!(tree.node(flop).street, Street::Flop);
        assert_eq!(tree.node(flop).player, 1);
        let turn = tree.find(&[Call, Check, Check, Check]).unwrap();
        assert_eq!(tree.node(turn).street, Street::Turn);
        // Checked down to the river and checked again: a showdown for the big blinds.
        let line = [Call, Check, Check, Check, Check, Check, Check];
        let river = tree.find(&line).unwrap();
        assert_eq!(tree.node(river).street, Street::River);
        assert_eq!(tree.node(river).player, 0);
        assert_eq!(tree.line(river), line);
        let Some(Next::End(p)) = tree.next(river, Check) else {
            panic!("the river check ends the hand");
        };
        assert_eq!(tree.payoff(p).chips, [[100, -100], [0, 0], [-100, 100]]);
        // Every decision point is found again from its own line.
        for id in 0..tree.len() as u32 {
            assert_eq!(tree.find(&tree.line(id)), Some(id));
        }
        // An empty tree when the hand is over before anyone acts.
        let done = root(50, 1);
        assert!(done.is_terminal());
        assert!(BettingTree::build(&done, &Menus::minimal()).is_empty());
    }

    #[test]
    fn payoffs_are_what_nlhe_pays_for_real_hands() {
        // Every ending of a small tree, with real cards for each result: the stored
        // payoff is the payout nlhe gives with a real ranker.
        use nlhe::{parse_card, BruteForceRanker, Deal};
        let c = |s: &str| parse_card(s).unwrap();
        let aces = [c("As"), c("Ah")];
        let rags = [c("7c"), c("2d")];
        let dry = [c("Ks"), c("Qd"), c("9h"), c("5c"), c("3s")];
        let royal = [c("Ad"), c("Kd"), c("Qd"), c("Jd"), c("Td")];
        let deals = [
            (Showdown::SmallBlind, Deal::new(&[aces, rags], dry).unwrap()),
            (
                Showdown::Tie,
                Deal::new(&[[c("2c"), c("3c")], rags], royal).unwrap(),
            ),
            (Showdown::BigBlind, Deal::new(&[rags, aces], dry).unwrap()),
        ];
        for (stack, small_blind, big_blind) in [(700, 50, 100), (37, 1, 2), (64, 3, 7)] {
            let config = Config::new(&[stack, stack], small_blind, big_blind, 0, 0).unwrap();
            let tree = BettingTree::build(&State::from_seed(&config, 5), &Menus::small());
            let mut endings = 0;
            for id in 0..tree.len() as u32 {
                for edge in tree.edges(id) {
                    let Next::End(p) = edge.next() else { continue };
                    for (result, deal) in &deals {
                        let mut hand = State::new(&config, *deal).unwrap();
                        for action in tree.line(id) {
                            hand.apply(action).unwrap();
                        }
                        hand.apply(edge.action).unwrap();
                        let paid = hand.payouts(&BruteForceRanker).unwrap();
                        assert_eq!(tree.payoff(p).chips[*result as usize], paid[..2]);
                    }
                    endings += 1;
                }
            }
            assert!(endings > 300);
            // Few different payoffs for many endings.
            assert!(tree.payoffs().len() * 4 < endings);
        }
    }
}
