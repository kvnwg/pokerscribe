//! Solving one street from its start, with both players' ranges there: the flop
//! depth-limited ([`crate::flop`]), the turn and the river with the subgame crate.

use std::sync::Arc;
use std::time::Instant;

use abstract_game::{Bucketer, Menus, Size};
use lbr::PublicState;
use nlhe::{Action, Card, State, Street};

use crate::cards::{blocked, card_mask, combo_cards, subgame_combo, NUM_COMBOS};
use crate::equity::{flop_equity, Equity};
use crate::flop::{self, Leaf, Problem, LANES};
use crate::leaf::{chooser_lanes, LeafTables};
use crate::street::{to_subgame, Extra, Kind, StreetTree};

/// How each street is solved.
#[derive(Clone, Debug)]
pub struct Settings {
    /// Exploitability targets (shares of the pot) and iteration caps. There is no time
    /// limit: a solve depends only on the public state, so a match repeats exactly.
    pub flop_target: f64,
    pub flop_iterations: u32,
    pub turn_target: f64,
    pub turn_iterations: u32,
    pub river_target: f64,
    pub river_iterations: u32,
    /// A combo whose weight is under this share of the largest weight in its range is
    /// left out of the solve.
    pub prune: f64,
    /// Threads for a turn solve (subgame) and whether the flop solver and the flop
    /// equity use rayon.
    pub turn_threads: usize,
    pub flop_parallel: bool,
    /// The bets offered on the river inside a turn solve (the river is solved again, with
    /// the blueprint's menu, when it comes).
    pub turn_river_menu: Menus,
}

impl Default for Settings {
    fn default() -> Settings {
        Settings {
            flop_target: 0.01,
            flop_iterations: 400,
            turn_target: 0.02,
            turn_iterations: 300,
            river_target: 0.005,
            river_iterations: 1000,
            prune: 1e-3,
            turn_threads: 1,
            flop_parallel: true,
            turn_river_menu: river_menu_in_turn(),
        }
    }
}

/// The river inside a turn solve: a bet of three quarters of the pot or all in, and all
/// in over a bet.
pub fn river_menu_in_turn() -> Menus {
    river_menu_named("075").expect("a known menu")
}

/// River menus for turn solves by name: `allin` (check or all in), `075` (three quarters
/// of the pot or all in, then all in), `standard` (the blueprint's).
pub fn river_menu_named(name: &str) -> Option<Menus> {
    let mut m = Menus::standard();
    m.streets[3] = match name {
        "allin" => vec![vec![Size::AllIn]],
        "075" => vec![vec![Size::Pot(0.75), Size::AllIn], vec![Size::AllIn]],
        "standard" => return Some(m),
        _ => return None,
    };
    Some(m)
}

/// A solved street: its tree and the strategy of every decision node.
#[derive(Debug)]
pub struct StreetSolve {
    pub street: Street,
    pub tree: StreetTree,
    pub extras: Vec<Extra>,
    /// Each player's combos in the solve (lbr indices, sorted): 0 the big blind.
    pub combos: [Vec<usize>; 2],
    /// By street-tree node: `[combo][action]` at decision nodes, empty elsewhere.
    pub strategy: Vec<Vec<f32>>,
    pub iterations: u32,
    pub exploitability: f64,
    pub ms: f64,
    /// Nodes of the tree the solver worked on (a turn's includes every river).
    pub solver_nodes: usize,
    /// Flop leaves valued from the leaf tables, and checked down.
    pub table_leaves: usize,
    pub equity_leaves: usize,
}

impl StreetSolve {
    /// The strategy of the combo at `pos` in `player`'s list at decision node `node`.
    pub fn row(&self, node: usize, pos: usize) -> &[f32] {
        let k = match &self.tree.nodes[node].kind {
            Kind::Decision { actions, .. } => actions.len(),
            _ => panic!("not a decision node"),
        };
        &self.strategy[node][pos * k..(pos + 1) * k]
    }
}

/// What a street solve starts from.
pub struct Inputs<'a> {
    /// The real state at the start of the street (made-up cards, real board seen).
    pub start: &'a State,
    /// The board cards face up on this street.
    pub board: &'a [Card],
    /// Each player's weights over the 1,326 combos (0 the big blind).
    pub weights: [&'a [f64]; 2],
    pub extras: Vec<Extra>,
    /// Fixed strategies: the street's actions to a decision node, and `[combo][action]`.
    pub frozen: Vec<(Vec<Action>, Vec<f32>)>,
    /// The player searching (0 the big blind): the other one picks at the flop's leaves.
    pub searcher: usize,
}

/// The combos of a range worth solving: not blocked by the board and at least
/// `prune` of the largest weight. Weights are scaled to a largest of 1.
pub fn live_combos(weights: &[f64], board: u64, prune: f64) -> (Vec<usize>, Vec<f64>) {
    let max = (0..NUM_COMBOS)
        .filter(|&c| !blocked(c, board))
        .map(|c| weights[c])
        .fold(0.0, f64::max);
    if max <= 0.0 {
        return (Vec::new(), Vec::new());
    }
    let (mut combos, mut w) = (Vec::new(), Vec::new());
    for c in 0..NUM_COMBOS {
        if !blocked(c, board) && weights[c] >= prune * max && weights[c] > 0.0 {
            combos.push(c);
            w.push(weights[c] / max);
        }
    }
    (combos, w)
}

/// Why a street could not be solved.
#[derive(Clone, Debug)]
pub struct SolveError(pub String);

/// Cached flop equity, keyed by the caller.
pub type EquityCache<'a> = &'a dyn Fn(&[Card], [&[usize]; 2]) -> Arc<Equity>;

/// Solves the street `inputs.start` is at the start of.
pub fn solve_street<B: Bucketer + Sync>(
    bp: &blueprint::Blueprint<B>,
    leaf: Option<&LeafTables>,
    menus: &Menus,
    settings: &Settings,
    inputs: &Inputs<'_>,
    equity: Option<EquityCache<'_>>,
) -> Result<StreetSolve, SolveError> {
    let t0 = Instant::now();
    let street = inputs.start.street();
    let mask = card_mask(inputs.board);
    let (c0, w0) = live_combos(inputs.weights[0], mask, settings.prune);
    let (c1, w1) = live_combos(inputs.weights[1], mask, settings.prune);
    if c0.is_empty() || c1.is_empty() {
        return Err(SolveError("a range is empty".into()));
    }
    let tree = StreetTree::build(inputs.start, menus, &inputs.extras);
    let mut frozen_ids = Vec::new();
    for (path, probs) in &inputs.frozen {
        let id = tree
            .walk(path)
            .map_err(|_| SolveError("a frozen decision is not in the tree".into()))?;
        frozen_ids.push((id, probs));
    }
    let combos = [c0, c1];
    let weights = [w0, w1];
    let mut out = StreetSolve {
        street,
        tree,
        extras: inputs.extras.clone(),
        combos,
        strategy: Vec::new(),
        iterations: 0,
        exploitability: 0.0,
        ms: 0.0,
        solver_nodes: 0,
        table_leaves: 0,
        equity_leaves: 0,
    };
    match street {
        Street::Flop => solve_flop(
            bp,
            leaf,
            settings,
            inputs,
            &weights,
            &frozen_ids,
            equity,
            &mut out,
        )?,
        Street::Turn | Street::River => {
            solve_late(settings, inputs, &weights, &frozen_ids, &mut out)?
        }
        Street::Preflop => return Err(SolveError("the blueprint plays the preflop".into())),
    }
    out.ms = t0.elapsed().as_secs_f64() * 1000.0;
    Ok(out)
}

fn check_frozen(
    tree: &StreetTree,
    id: usize,
    probs: &[f32],
    combos: &[Vec<usize>; 2],
) -> Result<(), SolveError> {
    match &tree.nodes[id].kind {
        Kind::Decision {
            player, actions, ..
        } if probs.len() == combos[*player].len() * actions.len() => Ok(()),
        _ => Err(SolveError("a frozen strategy does not fit its node".into())),
    }
}

fn solve_late(
    settings: &Settings,
    inputs: &Inputs<'_>,
    weights: &[Vec<f64>; 2],
    frozen: &[(usize, &Vec<f32>)],
    out: &mut StreetSolve,
) -> Result<(), SolveError> {
    let tree = &out.tree;
    let (target, iterations, threads) = match out.street {
        Street::Turn => (
            settings.turn_target,
            settings.turn_iterations,
            settings.turn_threads,
        ),
        _ => (settings.river_target, settings.river_iterations, 1),
    };
    let rivers: Vec<Option<StreetTree>> = if out.street == Street::Turn {
        tree.nodes
            .iter()
            .map(|n| match n.kind {
                Kind::End => Some(StreetTree::build(&n.state, &settings.turn_river_menu, &[])),
                _ => None,
            })
            .collect()
    } else {
        Vec::new()
    };
    let converted = to_subgame(tree, &rivers, inputs.board);
    let start = inputs.start;
    let seats = tree.seats;
    let spot = subgame::Spot {
        id: "search".into(),
        street: if out.street == Street::Turn {
            subgame::Street::Turn
        } else {
            subgame::Street::River
        },
        board: inputs
            .board
            .iter()
            .map(|&c| crate::cards::eval_card(c))
            .collect(),
        pot: start.pot() as f64,
        stacks: [
            start.stacks()[seats[0]] as f64,
            start.stacks()[seats[1]] as f64,
        ],
        max_raises: 0,
        sizes: std::array::from_fn(|_| subgame::spot::BetSizes {
            bets: Vec::new(),
            raises: Vec::new(),
            allin: false,
        }),
        river_sizes: None,
        ranges: [0, 1].map(|p| {
            out.combos[p]
                .iter()
                .zip(&weights[p])
                .map(|(&c, &w)| (subgame_combo(c), w))
                .collect()
        }),
        expected: Vec::new(),
        sha256: String::new(),
    };
    let mut game = subgame::Game::with_tree(spot, converted.tree).map_err(|e| SolveError(e.0))?;
    for &(id, probs) in frozen {
        check_frozen(tree, id, probs, &out.combos)?;
        game.freeze(converted.ids[id], probs.iter().map(|&p| p as f64).collect());
    }
    let solution = subgame::solve(
        &game,
        &subgame::SolveConfig {
            target_exploitability: target,
            max_iterations: Some(iterations),
            time_ms: None,
            threads,
        },
    );
    out.strategy = tree
        .nodes
        .iter()
        .enumerate()
        .map(|(id, n)| match n.kind {
            Kind::Decision { .. } => solution.strategy.probs[converted.ids[id]]
                .iter()
                .map(|&p| p as f32)
                .collect(),
            _ => Vec::new(),
        })
        .collect();
    out.iterations = solution.iterations;
    out.exploitability = solution.exploitability;
    out.solver_nodes = game.tree.nodes.len();
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn solve_flop<B: Bucketer + Sync>(
    bp: &blueprint::Blueprint<B>,
    leaf: Option<&LeafTables>,
    settings: &Settings,
    inputs: &Inputs<'_>,
    weights: &[Vec<f64>; 2],
    frozen: &[(usize, &Vec<f32>)],
    equity: Option<EquityCache<'_>>,
    out: &mut StreetSolve,
) -> Result<(), SolveError> {
    let tree = &out.tree;
    let flop = inputs.board;
    let eq = match equity {
        Some(f) => f(flop, [&out.combos[0], &out.combos[1]]),
        None => Arc::new(flop_equity(flop, [&out.combos[0], &out.combos[1]])),
    };
    let bucketer = bp.game().bucketer();
    // Local flop buckets per player.
    let mut global: [Vec<u64>; 2] = [Vec::new(), Vec::new()];
    let mut buckets: [Vec<u32>; 2] = [Vec::new(), Vec::new()];
    for p in 0..2 {
        let mut seen: Vec<u64> = Vec::new();
        for &c in &out.combos[p] {
            let g = bucketer.bucket(combo_cards(c), flop);
            let local = match seen.iter().position(|&x| x == g) {
                Some(i) => i,
                None => {
                    seen.push(g);
                    seen.len() - 1
                }
            };
            buckets[p].push(local as u32);
        }
        global[p] = seen;
    }
    let num_buckets = [global[0].len(), global[1].len()];
    let chooser = 1 - inputs.searcher;
    let lanes = chooser_lanes(chooser == 0);
    let mut leaves = vec![Leaf::None; tree.nodes.len()];
    for (id, node) in tree.nodes.iter().enumerate() {
        if !matches!(node.kind, Kind::End) {
            continue;
        }
        let table = leaf.and_then(|lt| {
            let public = PublicState::new(&node.state);
            let d = bp.decision_point(&public)?;
            let nb = lt.header.buckets;
            let mut qs = Vec::with_capacity(LANES);
            for &lane in &lanes {
                let t = lt.table(d, lane)?;
                let mut q = vec![0.0; num_buckets[0] * num_buckets[1]];
                for (i, &go) in global[0].iter().enumerate() {
                    for (j, &gi) in global[1].iter().enumerate() {
                        q[i * num_buckets[1] + j] = t[go as usize * nb + gi as usize] as f64;
                    }
                }
                qs.push(q);
            }
            Some(qs)
        });
        leaves[id] = match table {
            Some(qs) => {
                out.table_leaves += 1;
                Leaf::Table(qs)
            }
            None => {
                out.equity_leaves += 1;
                Leaf::Equity
            }
        };
    }
    let mut frozen_by_id: Vec<Option<Vec<f64>>> = vec![None; tree.nodes.len()];
    for &(id, probs) in frozen {
        check_frozen(tree, id, probs, &out.combos)?;
        frozen_by_id[id] = Some(probs.iter().map(|&p| p as f64).collect());
    }
    let problem = Problem {
        tree,
        combos: out.combos.clone(),
        weights: weights.clone(),
        pot: inputs.start.pot() as f64,
        equity: &eq,
        leaves,
        buckets,
        num_buckets,
        chooser,
        frozen: frozen_by_id,
    };
    let solution = flop::solve(
        &problem,
        settings.flop_target,
        settings.flop_iterations,
        settings.flop_parallel,
    );
    out.strategy = tree
        .nodes
        .iter()
        .enumerate()
        .map(|(id, n)| match n.kind {
            Kind::Decision { .. } => solution.strategy[id].iter().map(|&p| p as f32).collect(),
            _ => Vec::new(),
        })
        .collect();
    out.iterations = solution.iterations;
    out.exploitability = solution.exploitability;
    out.solver_nodes = tree.nodes.len();
    Ok(())
}
