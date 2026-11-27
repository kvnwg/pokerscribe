//! One street's betting, built over real `nlhe` states: the blueprint's bet menu at every
//! decision (`abstract_game::Menus::actions`, so every action is legal in the real game and
//! sized exactly as the blueprint sizes it), plus the real actions that are not on the menu,
//! each at the decision where it was taken. Turned into a `subgame::Tree` for the river and
//! the turn (with every river card); the flop solver uses it as it is.

use abstract_game::Menus;
use nlhe::{Action, Card, State, Street};

/// A real action that is not on the menu, at the decision reached by `path` (the street's
/// actions before it).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Extra {
    pub path: Vec<Action>,
    pub action: Action,
}

/// What a node of a street is.
#[derive(Clone, Debug)]
pub enum Kind {
    /// `player` (0 out of position, 1 in position) picks one of `actions`.
    Decision {
        player: usize,
        actions: Vec<Action>,
        children: Vec<usize>,
    },
    /// `folder` gave up.
    Fold { folder: usize },
    /// No more betting: a player is all in (or the river was called), and the cards decide.
    Showdown,
    /// The street ended without an all in: the next street starts from `state`.
    End,
}

#[derive(Clone, Debug)]
pub struct Node {
    /// The street's actions that lead here.
    pub path: Vec<Action>,
    pub kind: Kind,
    /// Chips each player (0 out of position, 1 in position) has put in since the street
    /// started.
    pub put: [f64; 2],
    /// The real state here (after the street ended, for `End`).
    pub state: State,
    /// Nodes in this node's subtree, itself included (parents come first).
    pub size: usize,
}

/// One street's tree. Node 0 is the start of the street.
#[derive(Clone, Debug)]
pub struct StreetTree {
    pub street: Street,
    /// The seat out of position (the big blind) and in position.
    pub seats: [usize; 2],
    pub nodes: Vec<Node>,
}

/// How far a real raise may be from a raise in the tree and still be read as it (chips):
/// one percent of the pot after calling, and at least two chips. A bet one percent of the
/// pot away is the same bet strategically, and the blueprint rounds its own sizes in a
/// slightly different way from `Menus::actions`, by a chip at times.
pub fn tolerance(state: &State) -> u32 {
    let seat = state.current_player().unwrap_or(0);
    let to_call = state.max_bet() - state.bets()[seat];
    ((0.01 * (state.pot() + to_call) as f64).round() as u32).max(2)
}

/// The subgame player of a seat: 0 for the big blind (first to act after the flop).
pub fn player_of(state: &State, seat: usize) -> usize {
    if seat == state.big_blind_seat() {
        0
    } else {
        1
    }
}

/// An action made legal at `state`: a raise is kept inside the legal range, a call with
/// nothing to call is a check, a fold when checking is free is a check.
pub fn legalize(state: &State, action: Action) -> Action {
    legalize_with(&state.legal_actions(), action)
}

/// [`legalize`] with the legal actions given.
pub fn legalize_with(legal: &nlhe::LegalActions, action: Action) -> Action {
    let passive = if legal.check {
        Action::Check
    } else {
        Action::Call
    };
    match action {
        Action::Fold if legal.fold => Action::Fold,
        Action::Fold | Action::Check | Action::Call => passive,
        Action::RaiseTo(x) => match legal.raise {
            Some(r) => Action::RaiseTo(x.clamp(r.min_to, r.max_to)),
            None => passive,
        },
    }
}

/// The index of `action` among `actions`, reading a raise as the nearest raise there when
/// it is within [`tolerance`] of it.
pub fn find_action(state: &State, actions: &[Action], action: Action) -> Option<usize> {
    let action = legalize(state, action);
    match action {
        Action::RaiseTo(x) => {
            let tol = tolerance(state);
            actions
                .iter()
                .enumerate()
                .filter_map(|(i, a)| match a {
                    Action::RaiseTo(y) => Some((i, x.abs_diff(*y))),
                    _ => None,
                })
                .filter(|&(_, d)| d <= tol)
                .min_by_key(|&(_, d)| d)
                .map(|(i, _)| i)
        }
        a => actions.iter().position(|b| *b == a),
    }
}

impl StreetTree {
    /// The street that `start` is at the beginning of, with `menus` at every decision and
    /// `extras` where they were taken.
    pub fn build(start: &State, menus: &Menus, extras: &[Extra]) -> StreetTree {
        let street = start.street();
        let bb = start.big_blind_seat();
        let seats = [bb, 1 - bb];
        let mut tree = StreetTree {
            street,
            seats,
            nodes: Vec::new(),
        };
        let base = [
            start.committed()[seats[0]] as f64,
            start.committed()[seats[1]] as f64,
        ];
        let mut scratch = Vec::new();
        tree.grow(start.clone(), Vec::new(), menus, extras, base, &mut scratch);
        tree
    }

    fn grow(
        &mut self,
        state: State,
        path: Vec<Action>,
        menus: &Menus,
        extras: &[Extra],
        base: [f64; 2],
        scratch: &mut Vec<Action>,
    ) -> usize {
        let id = self.nodes.len();
        let put = [
            state.committed()[self.seats[0]] as f64 - base[0],
            state.committed()[self.seats[1]] as f64 - base[1],
        ];
        let kind = if state.is_terminal() {
            let folded = (0..2).find(|&s| state.is_folded(s));
            match folded {
                Some(seat) => Kind::Fold {
                    folder: player_of(&state, seat),
                },
                None => Kind::Showdown,
            }
        } else if state.street() != self.street {
            Kind::End
        } else {
            Kind::Decision {
                player: player_of(&state, state.current_player().expect("someone acts")),
                actions: Vec::new(),
                children: Vec::new(),
            }
        };
        let is_decision = matches!(kind, Kind::Decision { .. });
        self.nodes.push(Node {
            path: path.clone(),
            kind,
            put,
            state: state.clone(),
            size: 1,
        });
        if !is_decision {
            return id;
        }
        scratch.clear();
        menus.actions(&state, scratch);
        let mut actions = scratch.clone();
        for e in extras.iter().filter(|e| e.path == path) {
            let a = legalize(&state, e.action);
            if !actions.contains(&a) {
                actions.push(a);
            }
        }
        actions.sort_by_key(order_key);
        let mut children = Vec::with_capacity(actions.len());
        for &a in &actions {
            let mut next = state.clone();
            next.apply(a).expect("menu and extra actions are legal");
            let mut p = path.clone();
            p.push(a);
            children.push(self.grow(next, p, menus, extras, base, scratch));
        }
        let player = match self.nodes[id].kind {
            Kind::Decision { player, .. } => player,
            _ => unreachable!(),
        };
        self.nodes[id].kind = Kind::Decision {
            player,
            actions,
            children,
        };
        self.nodes[id].size = self.nodes.len() - id;
        id
    }

    /// The node reached by the street's `actions` from the start, reading raises within
    /// [`tolerance`]; `Err(k)` when the `k`-th action is not in the tree.
    pub fn walk(&self, actions: &[Action]) -> Result<usize, usize> {
        let mut at = 0;
        for (k, &a) in actions.iter().enumerate() {
            let node = &self.nodes[at];
            let Kind::Decision {
                actions: here,
                children,
                ..
            } = &node.kind
            else {
                return Err(k);
            };
            match find_action(&node.state, here, a) {
                Some(i) => at = children[i],
                None => return Err(k),
            }
        }
        Ok(at)
    }

    pub fn decisions(&self) -> usize {
        self.nodes
            .iter()
            .filter(|n| matches!(n.kind, Kind::Decision { .. }))
            .count()
    }
}

/// Fold, check, call, then raises from small to large: the order of `Menus::actions` and of
/// the subgame crate.
fn order_key(a: &Action) -> (u8, u32) {
    match a {
        Action::Fold => (0, 0),
        Action::Check => (1, 0),
        Action::Call => (2, 0),
        Action::RaiseTo(x) => (3, *x),
    }
}

/// The subgame crate's action for a real one at `state` (a raise with no bet to answer is a
/// bet). Amounts are the street's chips after the action, as in the SPOT format.
pub fn subgame_action(state: &State, action: Action) -> subgame::Action {
    match action {
        Action::Fold => subgame::Action::Fold,
        Action::Check => subgame::Action::Check,
        Action::Call => subgame::Action::Call,
        Action::RaiseTo(x) if state.max_bet() == 0 => subgame::Action::Bet(x as f64),
        Action::RaiseTo(x) => subgame::Action::Raise(x as f64),
    }
}

/// A river or turn subgame tree, and where each of the street's decision nodes went.
pub struct Converted {
    pub tree: subgame::Tree,
    /// For each node of the (first) street tree, its id in `tree`.
    pub ids: Vec<usize>,
}

fn token_key(parent: &str, token: &str) -> String {
    if parent.is_empty() {
        token.to_string()
    } else {
        format!("{parent} {token}")
    }
}

struct Ctx<'a> {
    street: subgame::Street,
    runout: Option<usize>,
    /// Chips put in on earlier streets of the spot, by player.
    before: [f64; 2],
    street_pot: f64,
    street_stack: f64,
    /// For a turn spot: each river card, and the river tree after each `End` of the turn.
    rivers: Option<(&'a [Card], &'a [Option<StreetTree>])>,
}

/// The subgame tree of a river spot (`tree` on the river) or a turn spot (`tree` on the
/// turn, `rivers[i]` the river tree after node `i` when it is an `End`), with `board` the
/// spot's board (5 or 4 cards).
pub fn to_subgame(tree: &StreetTree, rivers: &[Option<StreetTree>], board: &[Card]) -> Converted {
    let start = &tree.nodes[0].state;
    let pot = start.pot() as f64;
    let stack = start.stacks()[tree.seats[0]].min(start.stacks()[tree.seats[1]]) as f64;
    let mut nodes = Vec::new();
    let mut ids = vec![usize::MAX; tree.nodes.len()];
    let (street, runouts, cards): (subgame::Street, Vec<Option<eval::Card>>, Vec<Card>) =
        match tree.street {
            Street::River => (subgame::Street::River, vec![None], Vec::new()),
            Street::Turn => {
                let board: Vec<eval::Card> =
                    board.iter().map(|&c| crate::cards::eval_card(c)).collect();
                let left = subgame::cards::deck_left(&board);
                let cards = left.iter().map(|c| c.index()).collect();
                (
                    subgame::Street::Turn,
                    left.into_iter().map(Some).collect(),
                    cards,
                )
            }
            s => panic!("a subgame starts on the turn or the river, not the {s:?}"),
        };
    let ctx = Ctx {
        street,
        runout: (street == subgame::Street::River).then_some(0),
        before: [0.0, 0.0],
        street_pot: pot,
        street_stack: stack,
        rivers: (street == subgame::Street::Turn).then_some((&cards[..], rivers)),
    };
    emit(tree, 0, String::new(), &ctx, &mut nodes, Some(&mut ids));
    Converted {
        tree: subgame::Tree::from_parts(nodes, runouts),
        ids,
    }
}

fn push(
    nodes: &mut Vec<subgame::Node>,
    ctx: &Ctx,
    key: String,
    kind: subgame::NodeKind,
    put: [f64; 2],
) -> usize {
    nodes.push(subgame::Node {
        key,
        kind,
        street: ctx.street,
        runout: ctx.runout,
        put: [ctx.before[0] + put[0], ctx.before[1] + put[1]],
        street_put: put,
        street_pot: ctx.street_pot,
        street_stack: ctx.street_stack,
        size: 1,
    });
    nodes.len() - 1
}

fn emit(
    tree: &StreetTree,
    id: usize,
    key: String,
    ctx: &Ctx,
    nodes: &mut Vec<subgame::Node>,
    mut ids: Option<&mut Vec<usize>>,
) -> usize {
    let node = &tree.nodes[id];
    let at = match &node.kind {
        Kind::Fold { folder } => push(
            nodes,
            ctx,
            key,
            subgame::NodeKind::Fold { folder: *folder },
            node.put,
        ),
        Kind::Showdown if ctx.street == subgame::Street::River => {
            push(nodes, ctx, key, subgame::NodeKind::Showdown, node.put)
        }
        Kind::Showdown | Kind::End => {
            // The turn is over: deal every river card.
            let (cards, rivers) = ctx.rivers.expect("a turn street ends at a chance node");
            let all_in = matches!(node.kind, Kind::Showdown);
            let at = push(
                nodes,
                ctx,
                key.clone(),
                subgame::NodeKind::Chance {
                    cards: Vec::new(),
                    children: Vec::new(),
                },
                node.put,
            );
            let mut children = Vec::with_capacity(cards.len());
            let mut card_list = Vec::with_capacity(cards.len());
            let state = &node.state;
            let river_ctx = |runout: usize| Ctx {
                street: subgame::Street::River,
                runout: Some(runout),
                before: [ctx.before[0] + node.put[0], ctx.before[1] + node.put[1]],
                street_pot: state.pot() as f64,
                street_stack: ctx.street_stack - node.put[0].max(node.put[1]),
                rivers: None,
            };
            for (runout, &card) in cards.iter().enumerate() {
                let card_key = token_key(&key, &crate::cards::eval_card(card).to_string());
                let rc = river_ctx(runout);
                let child = if all_in {
                    push(
                        nodes,
                        &rc,
                        card_key,
                        subgame::NodeKind::Showdown,
                        [0.0, 0.0],
                    )
                } else {
                    let river = rivers[id].as_ref().expect("a river tree after the turn");
                    emit(river, 0, card_key, &rc, nodes, None)
                };
                children.push(child);
                card_list.push(crate::cards::eval_card(card));
            }
            nodes[at].kind = subgame::NodeKind::Chance {
                cards: card_list,
                children,
            };
            nodes[at].size = nodes.len() - at;
            at
        }
        Kind::Decision {
            player,
            actions,
            children,
        } => {
            let at = push(
                nodes,
                ctx,
                key.clone(),
                subgame::NodeKind::Decision {
                    player: *player,
                    actions: Vec::new(),
                    children: Vec::new(),
                },
                node.put,
            );
            let mut sub_actions = Vec::with_capacity(actions.len());
            let mut sub_children = Vec::with_capacity(actions.len());
            for (&a, &child) in actions.iter().zip(children) {
                let sa = subgame_action(&node.state, a);
                let k = token_key(&key, &sa.token());
                sub_actions.push(sa);
                sub_children.push(emit(tree, child, k, ctx, nodes, ids.as_deref_mut()));
            }
            nodes[at].kind = subgame::NodeKind::Decision {
                player: *player,
                actions: sub_actions,
                children: sub_children,
            };
            nodes[at].size = nodes.len() - at;
            at
        }
    };
    if let Some(ids) = ids {
        ids[id] = at;
    }
    at
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::cards::eval_card;
    use nlhe::{parse_card, Config, Deal};

    pub(crate) fn c(s: &str) -> Card {
        parse_card(s).unwrap()
    }

    /// A 20 big blind hand (2,000 chips, blinds 50 and 100, button in seat 0) after a
    /// limp and a check, then `more` actions; board Kh 7d 2c Js 4h.
    pub(crate) fn hand(more: &[Action]) -> State {
        let config = Config::new(&[2_000, 2_000], 50, 100, 0, 0).unwrap();
        let deal = Deal::new(
            &[[c("As"), c("Ad")], [c("9c"), c("8c")]],
            [c("Kh"), c("7d"), c("2c"), c("Js"), c("4h")],
        )
        .unwrap();
        let mut s = State::new(&config, deal).unwrap();
        for &a in [Action::Call, Action::Check].iter().chain(more) {
            s.apply(a).unwrap();
        }
        s
    }

    #[test]
    fn raises_within_the_tolerance_are_read_and_extras_extend_the_tree() {
        let start = hand(&[]);
        assert_eq!(start.street(), Street::Flop);
        let menus = Menus::standard();
        let tree = StreetTree::build(&start, &menus, &[]);
        // The big blind acts first: check, or bet a third (66, under the minimum bet, so
        // 100), three quarters, one and a half pots, or all in (pot 200).
        let Kind::Decision {
            player, actions, ..
        } = &tree.nodes[0].kind
        else {
            panic!("the flop starts with a decision")
        };
        assert_eq!(*player, 0);
        assert_eq!(
            actions,
            &[
                Action::Check,
                Action::RaiseTo(100),
                Action::RaiseTo(150),
                Action::RaiseTo(300),
                Action::RaiseTo(1_900)
            ]
        );
        // 152 is within two chips of 150; 120 is no menu size.
        let at = tree.walk(&[Action::RaiseTo(152)]).unwrap();
        assert_eq!(tree.nodes[at].path, vec![Action::RaiseTo(150)]);
        assert_eq!(tree.walk(&[Action::RaiseTo(120)]), Err(0));
        assert_eq!(tree.walk(&[Action::Check, Action::RaiseTo(120)]), Err(1));
        let extra = Extra {
            path: Vec::new(),
            action: Action::RaiseTo(120),
        };
        let tree = StreetTree::build(&start, &menus, &[extra]);
        let at = tree.walk(&[Action::RaiseTo(120), Action::Call]).unwrap();
        assert!(matches!(tree.nodes[at].kind, Kind::End));
        assert_eq!(tree.nodes[at].put, [120.0, 120.0]);
        // Only where it was made.
        assert_eq!(tree.walk(&[Action::Check, Action::RaiseTo(120)]), Err(1));
        // Every subtree is its root and the nodes after it.
        for (id, n) in tree.nodes.iter().enumerate() {
            if let Kind::Decision { children, .. } = &n.kind {
                assert!(children.iter().all(|&ch| ch > id && ch < id + n.size));
            }
        }
    }

    #[test]
    fn a_river_tree_converts_and_solves() {
        let start = hand(&[Action::Check, Action::Check, Action::Check, Action::Check]);
        assert_eq!(start.street(), Street::River);
        let tree = StreetTree::build(&start, &Menus::standard(), &[]);
        let board = [c("Kh"), c("7d"), c("2c"), c("Js"), c("4h")];
        let conv = to_subgame(&tree, &[], &board);
        for (id, n) in tree.nodes.iter().enumerate() {
            let sub = &conv.tree.nodes[conv.ids[id]];
            match &n.kind {
                Kind::Decision {
                    player, actions, ..
                } => {
                    assert_eq!(sub.player(), Some(*player));
                    assert_eq!(sub.actions().len(), actions.len());
                }
                _ => assert!(sub.is_terminal()),
            }
            assert_eq!(sub.put, n.put);
        }
        let range = |hands: &[(&str, &str)]| {
            hands
                .iter()
                .map(|(a, b)| {
                    (
                        subgame::Combo::new(eval_card(c(a)), eval_card(c(b))).unwrap(),
                        1.0,
                    )
                })
                .collect::<Vec<_>>()
        };
        let spot = subgame::Spot {
            id: "test".into(),
            street: subgame::Street::River,
            board: board.iter().map(|&x| eval_card(x)).collect(),
            pot: 200.0,
            stacks: [1_900.0, 1_900.0],
            max_raises: 0,
            sizes: std::array::from_fn(|_| subgame::spot::BetSizes {
                bets: Vec::new(),
                raises: Vec::new(),
                allin: false,
            }),
            river_sizes: None,
            ranges: [
                range(&[("Ac", "Kc"), ("Qd", "Td"), ("7h", "7s"), ("5c", "3c")]),
                range(&[("Kd", "Qc"), ("Jh", "Tc"), ("6s", "5s"), ("Ah", "Ks")]),
            ],
            expected: Vec::new(),
            sha256: String::new(),
        };
        let game = subgame::Game::with_tree(spot, conv.tree).unwrap();
        let s = subgame::solve(&game, &subgame::SolveConfig::default());
        assert!(s.converged && s.exploitability <= 0.002);
    }

    #[test]
    fn a_turn_tree_deals_every_river() {
        let start = hand(&[Action::Check, Action::Check]);
        assert_eq!(start.street(), Street::Turn);
        let tree = StreetTree::build(&start, &Menus::standard(), &[]);
        let rivers: Vec<Option<StreetTree>> = tree
            .nodes
            .iter()
            .map(|n| {
                matches!(n.kind, Kind::End)
                    .then(|| StreetTree::build(&n.state, &Menus::standard(), &[]))
            })
            .collect();
        let board = [c("Kh"), c("7d"), c("2c"), c("Js")];
        let conv = to_subgame(&tree, &rivers, &board);
        assert_eq!(conv.tree.runouts.len(), 48);
        let mut chance = 0;
        for n in &conv.tree.nodes {
            if let subgame::NodeKind::Chance { cards, children } = &n.kind {
                chance += 1;
                assert_eq!(cards.len(), 48);
                for (r, &ch) in children.iter().enumerate() {
                    assert_eq!(conv.tree.nodes[ch].runout, Some(r));
                    assert_eq!(conv.tree.nodes[ch].street, subgame::Street::River);
                }
            }
        }
        let ends = tree
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, Kind::End | Kind::Showdown))
            .count();
        assert_eq!(chance, ends);
    }
}
