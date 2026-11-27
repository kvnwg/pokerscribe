//! The two hooks the search crate uses: a tree built elsewhere (`Tree::from_parts`) and
//! fixed strategies at chosen nodes (`Game::freeze`).

use std::path::{Path, PathBuf};

use subgame::{exploitability, solve, Game, SolveConfig, Spot, Tree, OOP};

fn spot(id: &str) -> Spot {
    let path: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../data/answer_keys/spots")
        .join(format!("{id}.json"));
    Spot::load(&path).unwrap_or_else(|e| panic!("{id}: {e}"))
}

fn fixed(iterations: u32) -> SolveConfig {
    SolveConfig {
        target_exploitability: 0.0,
        max_iterations: Some(iterations),
        time_ms: None,
        threads: 1,
    }
}

#[test]
fn a_tree_rebuilt_from_its_parts_solves_the_same() {
    for id in ["r01", "r12", "t01"] {
        let s = spot(id);
        let tree = Tree::new(&s);
        let again = Tree::from_parts(tree.nodes.clone(), tree.runouts.clone());
        assert_eq!(again.nodes.len(), tree.nodes.len());
        let a = solve(&Game::new(s.clone()).unwrap(), &fixed(20));
        let b = solve(&Game::with_tree(s, again).unwrap(), &fixed(20));
        assert_eq!(a.strategy.probs, b.strategy.probs, "{id}");
        assert_eq!(a.values, b.values, "{id}");
    }
}

#[test]
fn a_frozen_node_keeps_its_strategy_and_the_best_response_follows_it() {
    let s = spot("r01");
    let mut game = Game::new(s).unwrap();
    let root = 0;
    let k = game.tree.nodes[root].actions().len();
    let n = game.n(OOP);
    // Check with every hand at the root, whatever the hand.
    let check = game.tree.nodes[root]
        .actions()
        .iter()
        .position(|a| matches!(a, subgame::Action::Check))
        .expect("the river starts with a check or a bet");
    let mut probs = vec![0.0; n * k];
    for h in 0..n {
        probs[h * k + check] = 1.0;
    }
    game.freeze(root, probs.clone());
    let solution = solve(&game, &fixed(200));
    assert_eq!(solution.strategy.probs[root], probs);
    // The best response is held to the frozen node too: OOP's best response checks first,
    // so it can't win more than a best response free to bet there.
    let frozen = exploitability(&game, &solution.strategy, false);
    assert!(frozen.chips().is_finite() && frozen.chips() >= -1e-9);
    let free = Game::new(spot("r01")).unwrap();
    let unfrozen = exploitability(&free, &solution.strategy, false);
    assert!(
        unfrozen.best_response[OOP] >= frozen.best_response[OOP] - 1e-9,
        "a free best response does at least as well: {} against {}",
        unfrozen.best_response[OOP],
        frozen.best_response[OOP]
    );
}
