//! The betting tree of a spot, by the size rules of `data/SPOT_FORMAT.md`.
//!
//! One street is built exactly as `app/solver/tree.py` builds the river: the same sizes,
//! caps, min-raise rule, amount rounding and action order. A turn spot adds a chance node
//! after every way the turn can end without a fold: one branch per card left in the deck
//! (2c 2d 2h 2s 3c ... As), each a river street with pot `pot + 2 * called` and stack
//! `stack - called`, or a plain showdown when the turn call was all in.
//!
//! Nodes are stored parent first, and the subtree of a node is the `size` nodes starting
//! at it. The solver relies on that to hand each river branch its own slice of storage.

use std::collections::HashMap;

use eval::Card;

use crate::cards::deck_left;
use crate::pyfmt::round_to;
use crate::spot::{BetSizes, Spot, Street, IP, OOP, PLAYER_NAMES};

pub type NodeId = usize;

/// One action at a decision node. Amounts are what the player has put in on the current
/// street once the action is made ("bet 50", "raise to 150").
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Action {
    Check,
    Bet(f64),
    Raise(f64),
    Call,
    Fold,
}

impl Action {
    /// The token of the format: `x`, `b50`, `r150`, `c`, `f`.
    pub fn token(&self) -> String {
        match self {
            Action::Check => "x".to_string(),
            Action::Bet(a) => format!("b{}", fmt_amount(*a)),
            Action::Raise(a) => format!("r{}", fmt_amount(*a)),
            Action::Call => "c".to_string(),
            Action::Fold => "f".to_string(),
        }
    }

    /// The kind an expected check counts: `x`, `b`, `r`, `c` or `f`.
    pub fn kind(&self) -> char {
        match self {
            Action::Check => 'x',
            Action::Bet(_) => 'b',
            Action::Raise(_) => 'r',
            Action::Call => 'c',
            Action::Fold => 'f',
        }
    }
}

/// An amount as the format prints it: 2 decimal places, no trailing zeros (`50`, `33.5`).
pub fn fmt_amount(x: f64) -> String {
    let r = round_to(x, 2);
    if (r - r.round()).abs() < 1e-9 {
        format!("{}", r.round() as i64)
    } else {
        let text = format!("{r:.2}");
        text.trim_end_matches('0').trim_end_matches('.').to_string()
    }
}

/// Bet or raise-to amounts: capped at the stack, above `floor`, each offered once, sorted.
/// `tree.py::_amounts`.
fn amounts(wanted: &[f64], stack: f64, allin: bool, floor: f64) -> Vec<f64> {
    let mut out: Vec<f64> = Vec::new();
    for &x in wanted.iter().chain(allin.then_some(&stack)) {
        let x = round_to(x.min(stack), 2);
        if x > floor + 1e-9 && !out.contains(&x) {
            out.push(x);
        }
    }
    out.sort_by(|a, b| a.partial_cmp(b).unwrap());
    out
}

#[derive(Clone, Debug, PartialEq)]
pub enum NodeKind {
    /// `player` chooses one of `actions`; `children[i]` follows `actions[i]`.
    Decision {
        player: usize,
        actions: Vec<Action>,
        children: Vec<NodeId>,
    },
    /// The river card is dealt (turn spots): `children[i]` follows `cards[i]`.
    Chance {
        cards: Vec<Card>,
        children: Vec<NodeId>,
    },
    /// `folder` gave up.
    Fold {
        folder: usize,
    },
    Showdown,
}

#[derive(Clone, Debug)]
pub struct Node {
    /// The actions so far, as in the format: `"x b50 c 7h b100"`.
    pub key: String,
    pub kind: NodeKind,
    pub street: Street,
    /// Which board this node is played on: an index into [`Tree::runouts`]. `None` on the
    /// turn street of a turn spot, where the river card isn't known yet.
    pub runout: Option<usize>,
    /// Chips each player has put in since the spot started (every street).
    pub put: [f64; 2],
    /// Chips each player has put in on this node's street.
    pub street_put: [f64; 2],
    /// Pot and effective stack at the start of this node's street.
    pub street_pot: f64,
    pub street_stack: f64,
    /// Number of nodes in this node's subtree, itself included.
    pub size: usize,
}

impl Node {
    pub fn is_terminal(&self) -> bool {
        matches!(self.kind, NodeKind::Fold { .. } | NodeKind::Showdown)
    }

    pub fn player(&self) -> Option<usize> {
        match self.kind {
            NodeKind::Decision { player, .. } => Some(player),
            _ => None,
        }
    }

    pub fn actions(&self) -> &[Action] {
        match &self.kind {
            NodeKind::Decision { actions, .. } => actions,
            _ => &[],
        }
    }

    pub fn children(&self) -> &[NodeId] {
        match &self.kind {
            NodeKind::Decision { children, .. } | NodeKind::Chance { children, .. } => children,
            _ => &[],
        }
    }
}

#[derive(Clone, Debug)]
pub struct Tree {
    /// Parents before children; node 0 is the start of the spot.
    pub nodes: Vec<Node>,
    /// The river card of each runout: one `None` for a river spot (the board is whole),
    /// every card left in the deck for a turn spot.
    pub runouts: Vec<Option<Card>>,
    /// The decision nodes in the order of `spots.decision_nodes` (the order of RESULT
    /// lines): each street children first, the turn before the rivers.
    pub decision_order: Vec<NodeId>,
    /// The chance nodes (turn spots: one for each way the turn ends without a fold), in
    /// node order.
    pub chance_nodes: Vec<NodeId>,
    by_key: HashMap<String, NodeId>,
}

impl Tree {
    pub fn new(spot: &Spot) -> Tree {
        let runouts: Vec<Option<Card>> = match spot.street {
            Street::River => vec![None],
            Street::Turn => deck_left(&spot.board).into_iter().map(Some).collect(),
        };
        let mut b = Builder {
            spot,
            nodes: Vec::new(),
            runouts: &runouts,
        };
        let ctx = StreetCtx {
            street: spot.street,
            pot: spot.pot,
            stack: spot.effective_stack(),
            before: 0.0,
            runout: if spot.street == Street::River {
                Some(0)
            } else {
                None
            },
        };
        b.street(&ctx, String::new(), OOP, [0.0, 0.0], 0, false);
        let nodes = b.nodes;
        let decision_order = decision_order(&nodes);
        let by_key = decision_order
            .iter()
            .map(|&id| (nodes[id].key.clone(), id))
            .collect::<HashMap<_, _>>();
        let chance_nodes = (0..nodes.len())
            .filter(|&id| matches!(nodes[id].kind, NodeKind::Chance { .. }))
            .collect();
        Tree {
            nodes,
            runouts,
            decision_order,
            chance_nodes,
            by_key,
        }
    }

    /// Where a chance node is in `chance_nodes`.
    pub fn chance_index(&self, id: NodeId) -> usize {
        self.chance_nodes.binary_search(&id).expect("a chance node")
    }

    /// The decision node with this key.
    pub fn decision(&self, key: &str) -> Option<NodeId> {
        self.by_key.get(key).copied()
    }

    pub fn actor_name(&self, id: NodeId) -> &'static str {
        PLAYER_NAMES[self.nodes[id].player().expect("a decision node")]
    }

    /// The most decision and chance nodes on any path from the root: how deep a walk goes.
    pub fn depth(&self) -> usize {
        fn below(nodes: &[Node], id: NodeId) -> usize {
            let n = &nodes[id];
            if n.is_terminal() {
                0
            } else {
                1 + n
                    .children()
                    .iter()
                    .map(|&c| below(nodes, c))
                    .max()
                    .unwrap_or(0)
            }
        }
        below(&self.nodes, 0)
    }
}

struct StreetCtx {
    street: Street,
    /// Pot and effective stack at the start of the street.
    pot: f64,
    stack: f64,
    /// What each player put in on earlier streets of the spot.
    before: f64,
    runout: Option<usize>,
}

struct Builder<'a> {
    spot: &'a Spot,
    nodes: Vec<Node>,
    runouts: &'a [Option<Card>],
}

fn join(key: &str, token: &str) -> String {
    if key.is_empty() {
        token.to_string()
    } else {
        format!("{key} {token}")
    }
}

impl Builder<'_> {
    fn push(
        &mut self,
        ctx: &StreetCtx,
        key: String,
        kind: NodeKind,
        street_put: [f64; 2],
    ) -> NodeId {
        self.nodes.push(Node {
            key,
            kind,
            street: ctx.street,
            runout: ctx.runout,
            put: [ctx.before + street_put[0], ctx.before + street_put[1]],
            street_put,
            street_pot: ctx.pot,
            street_stack: ctx.stack,
            size: 1,
        });
        self.nodes.len() - 1
    }

    /// `tree.py::GameTree._build`, one decision node and everything under it.
    fn street(
        &mut self,
        ctx: &StreetCtx,
        key: String,
        player: usize,
        put: [f64; 2],
        raises: u32,
        checked: bool,
    ) -> NodeId {
        let id = self.push(
            ctx,
            key.clone(),
            NodeKind::Decision {
                player,
                actions: Vec::new(),
                children: Vec::new(),
            },
            put,
        );
        let other = 1 - player;
        let (mine, theirs) = (put[player], put[other]);
        let sizes: &BetSizes = self.spot.sizes_on(ctx.street, player);
        let mut actions = Vec::new();
        let mut children = Vec::new();

        if theirs <= mine + 1e-9 {
            // no bet to answer: check or bet
            let k = join(&key, "x");
            actions.push(Action::Check);
            children.push(if checked || player == IP {
                self.street_end(ctx, k, put[0], put)
            } else {
                self.street(ctx, k, other, put, raises, true)
            });
            let wanted: Vec<f64> = sizes.bets.iter().map(|f| f * ctx.pot).collect();
            for amount in amounts(&wanted, ctx.stack, sizes.allin, 0.0) {
                let action = Action::Bet(amount);
                let mut new = put;
                new[player] = amount;
                let k = join(&key, &action.token());
                actions.push(action);
                children.push(self.street(ctx, k, other, new, raises, checked));
            }
        } else {
            // facing a bet or raise: fold, call or raise
            actions.push(Action::Fold);
            children.push(self.push(ctx, join(&key, "f"), NodeKind::Fold { folder: player }, put));
            actions.push(Action::Call);
            let mut called = put;
            called[player] = theirs;
            children.push(self.street_end(ctx, join(&key, "c"), theirs, called));
            if raises < self.spot.max_raises && theirs < ctx.stack - 1e-9 {
                let after_call = ctx.pot + 2.0 * theirs;
                let least = theirs + (theirs - mine); // a raise is at least the bet it answers
                let wanted: Vec<f64> = sizes
                    .raises
                    .iter()
                    .map(|f| least.max(theirs + f * after_call))
                    .collect();
                for amount in amounts(&wanted, ctx.stack, sizes.allin, theirs) {
                    let action = Action::Raise(amount);
                    let mut new = put;
                    new[player] = amount;
                    let k = join(&key, &action.token());
                    actions.push(action);
                    children.push(self.street(ctx, k, other, new, raises + 1, checked));
                }
            }
        }
        self.nodes[id].kind = NodeKind::Decision {
            player,
            actions,
            children,
        };
        self.nodes[id].size = self.nodes.len() - id;
        id
    }

    /// The street ended without a fold, each player having put in `called` on it: a
    /// showdown on the river, the river card on the turn.
    fn street_end(&mut self, ctx: &StreetCtx, key: String, called: f64, put: [f64; 2]) -> NodeId {
        if ctx.street == Street::River {
            return self.push(ctx, key, NodeKind::Showdown, put);
        }
        let id = self.push(
            ctx,
            key.clone(),
            NodeKind::Chance {
                cards: Vec::new(),
                children: Vec::new(),
            },
            put,
        );
        let all_in = called >= ctx.stack - 1e-9;
        let mut cards = Vec::new();
        let mut children = Vec::new();
        for (runout, card) in self.runouts.iter().enumerate() {
            let card = card.expect("a turn spot's runouts are cards");
            let river = StreetCtx {
                street: Street::River,
                pot: ctx.pot + 2.0 * called,
                stack: ctx.stack - called,
                before: ctx.before + called,
                runout: Some(runout),
            };
            let k = join(&key, &card.to_string());
            cards.push(card);
            children.push(if all_in {
                self.push(&river, k, NodeKind::Showdown, [0.0, 0.0])
            } else {
                self.street(&river, k, OOP, [0.0, 0.0], 0, false)
            });
        }
        self.nodes[id].kind = NodeKind::Chance { cards, children };
        self.nodes[id].size = self.nodes.len() - id;
        id
    }
}

/// The order of `spots.decision_nodes`: the first street with children before parents,
/// then, for every way it ends in the order those ends are met, each river card's street
/// the same way.
fn decision_order(nodes: &[Node]) -> Vec<NodeId> {
    fn street(nodes: &[Node], id: NodeId, out: &mut Vec<NodeId>, ends: &mut Vec<NodeId>) {
        for &child in nodes[id].children() {
            match nodes[child].kind {
                NodeKind::Decision { .. } => street(nodes, child, out, ends),
                NodeKind::Chance { .. } => ends.push(child),
                _ => {}
            }
        }
        out.push(id);
    }
    let mut out = Vec::new();
    let mut ends = Vec::new();
    street(nodes, 0, &mut out, &mut ends);
    for end in ends {
        for &river in nodes[end].children() {
            if matches!(nodes[river].kind, NodeKind::Decision { .. }) {
                let mut none = Vec::new();
                street(nodes, river, &mut out, &mut none);
                debug_assert!(none.is_empty(), "the river is the last street");
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spot::tests::RIVER;
    use serde_json::Value;

    fn spot(change: impl Fn(&mut Value)) -> Spot {
        let mut v: Value = serde_json::from_str(RIVER).unwrap();
        change(&mut v);
        Spot::from_json(&v.to_string()).unwrap()
    }

    fn tokens(tree: &Tree, key: &str) -> Vec<String> {
        let id = tree
            .decision(key)
            .unwrap_or_else(|| panic!("no node {key:?}"));
        tree.nodes[id].actions().iter().map(Action::token).collect()
    }

    #[test]
    fn amounts_print_like_the_format() {
        assert_eq!(fmt_amount(50.0), "50");
        assert_eq!(fmt_amount(33.5), "33.5");
        assert_eq!(fmt_amount(33.25), "33.25");
        assert_eq!(fmt_amount(116.00000000000001), "116");
        assert_eq!(fmt_amount(0.1 + 0.2), "0.3");
    }

    #[test]
    fn sizes_follow_the_format_example() {
        // SPOT_FORMAT.md: r05, pot 100, stacks 300, oop bets 0.5 raises 0.5, ip bets 0.33 and 1.0.
        let s = spot(|v| {
            v["stacks"] = serde_json::json!([300, 300]);
            v["sizes"] = serde_json::json!({
                "oop": {"bets": [0.5], "raises": [0.5], "allin": true},
                "ip": {"bets": [0.33, 1.0], "raises": [0.5], "allin": true}});
        });
        let t = Tree::new(&s);
        assert_eq!(tokens(&t, ""), ["x", "b50", "b300"]);
        assert_eq!(tokens(&t, "x"), ["x", "b33", "b100", "b300"]);
        assert_eq!(tokens(&t, "b50"), ["f", "c", "r150", "r300"]); // 50 + 0.5 * (100 + 2 * 50)
        assert_eq!(tokens(&t, "x b33"), ["f", "c", "r116", "r300"]);
        assert_eq!(tokens(&t, "x b33 r116"), ["f", "c", "r282", "r300"]);
        assert_eq!(tokens(&t, "x b33 r116 r282"), ["f", "c", "r300"]);
        assert_eq!(tokens(&t, "x b33 r116 r282 r300"), ["f", "c"]); // the third raise is the last
        assert_eq!(tokens(&t, "b300"), ["f", "c"]); // nothing left to raise with
        assert_eq!(t.decision_order.len(), 18);
        // children before parents, in action order
        let keys: Vec<&str> = t
            .decision_order
            .iter()
            .map(|&i| t.nodes[i].key.as_str())
            .collect();
        assert_eq!(
            &keys[..4],
            [
                "x b33 r116 r282 r300",
                "x b33 r116 r282",
                "x b33 r116 r300",
                "x b33 r116"
            ]
        );
        assert_eq!(*keys.last().unwrap(), "");
    }

    #[test]
    fn max_raises_and_the_min_raise_rule() {
        let base = |v: &mut Value| {
            v["stacks"] = serde_json::json!([1000, 1000]);
            v["sizes"] = serde_json::json!({
                "oop": {"bets": [0.5], "raises": [0.1], "allin": false},
                "ip": {"bets": [0.5], "raises": [0.1], "allin": false}});
        };
        let t = Tree::new(&spot(|v| {
            base(v);
            v["max_raises"] = 0.into();
        }));
        assert_eq!(tokens(&t, "b50"), ["f", "c"]);
        let t = Tree::new(&spot(|v| {
            base(v);
            v["max_raises"] = 2.into();
        }));
        // 0.1 of the pot after calling is 20 more: under the bet of 50, so the raise is to 100
        assert_eq!(tokens(&t, "b50"), ["f", "c", "r100"]);
        // then 100 + 0.1 * 300 = 130 is under 100 + (100 - 50)
        assert_eq!(tokens(&t, "b50 r100"), ["f", "c", "r150"]);
        assert_eq!(tokens(&t, "b50 r100 r150"), ["f", "c"]);
    }

    #[test]
    fn sizes_at_or_over_the_stack_merge_into_the_all_in() {
        let t = Tree::new(&spot(|v| {
            v["stacks"] = serde_json::json!([80, 500]);
            v["sizes"] = serde_json::json!({
                "oop": {"bets": [0.5, 0.8, 1.0, 2.0], "raises": [1.0], "allin": true},
                "ip": {"bets": [0.9], "raises": [0.5], "allin": false}});
        }));
        assert_eq!(tokens(&t, ""), ["x", "b50", "b80"]);
        assert_eq!(tokens(&t, "x"), ["x", "b80"]); // 0.9 of the pot is over the stack of 80
        assert_eq!(tokens(&t, "b50"), ["f", "c", "r80"]); // 50 + 0.5 * 200 is capped
        assert_eq!(tokens(&t, "b50 r80"), ["f", "c"]);
    }

    #[test]
    fn terminals_know_what_was_put_in() {
        let t = Tree::new(&spot(|_| {}));
        let by_key = |key: &str| t.nodes.iter().find(|n| n.key == key).unwrap();
        assert_eq!(by_key("x x").kind, NodeKind::Showdown);
        assert_eq!(by_key("x x").put, [0.0, 0.0]);
        assert_eq!(by_key("b50 c").put, [50.0, 50.0]);
        assert_eq!(by_key("b50 f").kind, NodeKind::Fold { folder: IP });
        assert_eq!(by_key("b50 f").put, [50.0, 0.0]);
        assert_eq!(by_key("x b33 r116 f").kind, NodeKind::Fold { folder: IP });
        assert_eq!(by_key("x b33 r116 f").put, [116.0, 33.0]);
        // parents come first and a subtree is contiguous
        for (id, n) in t.nodes.iter().enumerate() {
            for &c in n.children() {
                assert!(c > id && c + t.nodes[c].size <= id + n.size);
            }
        }
        assert_eq!(t.nodes[0].size, t.nodes.len());
    }

    #[test]
    fn a_turn_spot_deals_every_river_card() {
        // t01: pot 100, stacks 300, half-pot bets and all in, on both streets.
        let s = spot(|v| {
            v["street"] = "turn".into();
            v["board"] = serde_json::json!(["Ks", "7d", "2c", "4h"]);
            v["stacks"] = serde_json::json!([300, 300]);
            let sizes = serde_json::json!({
                "oop": {"bets": [0.5], "raises": [], "allin": true},
                "ip": {"bets": [0.5], "raises": [], "allin": true}});
            v["sizes"] = sizes.clone();
            v["river_sizes"] = sizes;
        });
        let t = Tree::new(&s);
        assert_eq!(t.runouts.len(), 48);
        assert_eq!(t.runouts[0].unwrap().to_string(), "2d");
        for end in ["x x", "b50 c", "x b50 c"] {
            for card in &t.runouts {
                let key = format!("{end} {}", card.unwrap());
                let id = t.decision(&key).unwrap();
                assert_eq!(t.nodes[id].player(), Some(OOP));
                assert_eq!(t.nodes[id].street, Street::River);
            }
        }
        let n = &t.nodes[t.decision("b50 c 2d").unwrap()];
        assert_eq!((n.street_pot, n.street_stack), (200.0, 250.0));
        assert_eq!(tokens(&t, "b50 c 2d"), ["x", "b100", "b250"]);
        assert_eq!(n.runout, Some(0));
        // all in on the turn: the river is dealt, nobody acts
        assert!(t.decision("b300 c 2d").is_none());
        let allin = t.nodes.iter().find(|n| n.key == "b300 c").unwrap();
        assert!(matches!(&allin.kind, NodeKind::Chance { children, .. } if children.len() == 48));
        let leaf = &t.nodes[allin.children()[5]];
        assert_eq!(leaf.kind, NodeKind::Showdown);
        assert_eq!(leaf.put, [300.0, 300.0]);
        // what was put in on the turn stays in on the river
        let fold = t.nodes.iter().find(|n| n.key == "b50 c 2d b100 f").unwrap();
        assert_eq!(fold.kind, NodeKind::Fold { folder: IP });
        assert_eq!(fold.put, [150.0, 50.0]);
        // RESULT order: the turn's 8 nodes, then the rivers of "x x", card by card
        let keys: Vec<&str> = t
            .decision_order
            .iter()
            .map(|&i| t.nodes[i].key.as_str())
            .collect();
        assert_eq!(keys[7], "");
        assert!(keys[8].starts_with("x x 2d "));
        assert_eq!(t.decision_order.len(), 1160);
        // x x, x b50 c, x b300 c, b50 c, b50 r300 c, b300 c... every end without a fold
        let ends: Vec<&str> = t
            .chance_nodes
            .iter()
            .map(|&c| t.nodes[c].key.as_str())
            .collect();
        assert_eq!(
            ends,
            [
                "x x",
                "x b50 c",
                "x b50 r300 c",
                "x b300 c",
                "b50 c",
                "b50 r300 c",
                "b300 c"
            ]
        );
        assert_eq!(t.chance_index(t.chance_nodes[3]), 3);
        assert!(t.depth() >= 6);
    }
}
