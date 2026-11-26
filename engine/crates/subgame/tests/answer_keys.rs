//! The solver against the answer keys in `data/answer_keys` (30 river and 10 turn spots,
//! with TexasSolver's answer to each).
//!
//! Run in a release build: the turn tests and the speed test are skipped in a debug build.
//!
//! ```bash
//! cargo test --release -p subgame
//! ```
//!
//! The tables of the README come from the `report` test:
//!
//! ```bash
//! cargo test --release -p subgame --test answer_keys report -- --ignored --nocapture
//! ```

use std::path::{Path, PathBuf};
use std::time::Instant;

use serde_json::Value;
use subgame::expected::check_expected;
use subgame::exploit::{exploitability, strategy_value};
use subgame::result::{checks, encode, records, strategy_from_records, SolveInfo};
use subgame::{
    solve, Action, Exploitability, Game, NodeKind, ResultFile, Solution, SolveConfig, Spot,
    Strategy, IP, OOP,
};

/// The gates of the task: exploitability under 0.5% of the pot, each player's value within
/// 0.5% of the pot of TexasSolver's, river p95 under 400 ms at a 0.5% target.
const GATE_EXPLOITABILITY: f64 = 0.005;
const GATE_VALUE_PCT: f64 = 0.5;
const GATE_RIVER_P95_MS: f64 = 400.0;
/// The binary's default target, 0.3% of the pot (TexasSolver's accuracy for the keys too).
/// The value gate is checked on solves to this target. Stopping at exactly 0.5% isn't
/// enough for it: a strategy that is 0.5% exploitable can sit up to 1% of the pot from the
/// game's value, and r02 and r20 come out 0.57% and 0.50% from TexasSolver's (the README
/// has every spot at both targets).
const DEFAULT_TARGET: f64 = 0.003;

fn keys_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../data/answer_keys")
}

fn spot_ids(street: &str) -> Vec<String> {
    let prefix = &street[..1];
    let n = if street == "river" { 30 } else { 10 };
    (1..=n).map(|i| format!("{prefix}{i:02}")).collect()
}

fn spot_path(id: &str) -> PathBuf {
    keys_dir().join("spots").join(format!("{id}.json"))
}

fn load_game(id: &str) -> Game {
    let spot = Spot::load(&spot_path(id)).unwrap_or_else(|e| panic!("{id}: {e}"));
    Game::new(spot).unwrap_or_else(|e| panic!("{id}: {e}"))
}

/// TexasSolver's answer to a spot: the file, as a strategy on our tree, and the rows it
/// left out (none in the saved keys).
struct Key {
    file: ResultFile,
    strategy: Strategy,
    filled: usize,
}

impl Key {
    fn load(game: &Game) -> Key {
        let id = &game.spot.id;
        let dir = keys_dir().join("texassolver");
        let plain = dir.join(format!("{id}.jsonl"));
        let path = if plain.exists() {
            plain
        } else {
            dir.join(format!("{id}.jsonl.gz"))
        };
        let file = ResultFile::load(&path).unwrap_or_else(|e| panic!("{e}"));
        let (strategy, filled) =
            strategy_from_records(game, &file.nodes).unwrap_or_else(|e| panic!("{id}: {e}"));
        Key {
            file,
            strategy,
            filled,
        }
    }

    /// TexasSolver's own exploitability, as a share of the pot.
    fn reported(&self) -> f64 {
        self.file.header["solver"]["exploitability_pot"]
            .as_f64()
            .expect("solver.exploitability_pot")
    }

    /// What the key's header says of its answer, worked out by `app/solver` (river keys
    /// only; `data/SPOT_FORMAT.md`, "RESULT"): the value of each player and the bounds on
    /// OOP's true value.
    fn stored_values(&self) -> Option<([f64; 2], [f64; 2])> {
        let checks = &self.file.header["checks"];
        let number = |v: &Value| v.as_f64().expect("a number in the key's checks");
        if checks["values"].is_null() {
            return None;
        }
        Some((
            [
                number(&checks["values"]["oop"]),
                number(&checks["values"]["ip"]),
            ],
            [
                number(&checks["oop_value_bounds"][0]),
                number(&checks["oop_value_bounds"][1]),
            ],
        ))
    }
}

/// `[low, high]` for OOP's true value from an answer's two best responses.
fn bounds(e: &Exploitability) -> [f64; 2] {
    [e.pot - e.best_response[IP], e.best_response[OOP]]
}

fn config(target: f64, threads: usize) -> SolveConfig {
    SolveConfig {
        target_exploitability: target,
        max_iterations: Some(20_000),
        time_ms: None,
        threads,
    }
}

fn threads() -> usize {
    std::thread::available_parallelism().map_or(1, |n| n.get())
}

/// Nearest-rank percentile, as `app/solver/timing.py`.
fn percentile(values: &[f64], q: f64) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let rank = ((q / 100.0 * sorted.len() as f64).ceil() as usize).max(1);
    sorted[rank - 1]
}

/// One whole decision, as the binary does it: read the spot file, build the game, solve to
/// the target, and write the RESULT text. Returns the solution and the milliseconds taken.
fn timed_decision(id: &str, target: f64, threads: usize) -> (Game, Solution, f64) {
    let start = Instant::now();
    let game = load_game(id);
    let cfg = config(target, threads);
    let solution = solve(&game, &cfg);
    let nodes = records(&game, &solution.strategy);
    let failures = check_expected(&game.spot, &nodes);
    let checked = checks(&game, &nodes, threads > 1).unwrap();
    let text = encode(
        &game,
        &SolveInfo {
            config: &cfg,
            solution: &solution,
            checks: &checked,
            expected_failures: &failures,
            created: None,
        },
        &nodes,
    );
    let ms = start.elapsed().as_secs_f64() * 1000.0;
    assert!(text.len() > 100);
    (game, solution, ms)
}

// ------------------------------------------------------------------ the spots

#[test]
fn every_spot_is_read_and_hashes_as_its_answer_key_says() {
    for id in spot_ids("river").iter().chain(&spot_ids("turn")) {
        let game = load_game(id);
        assert_eq!(game.spot.id, *id);
        let index: Value = serde_json::from_str(
            &std::fs::read_to_string(keys_dir().join("texassolver/index.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(
            index["spots"][id]["spot_sha256"],
            game.spot.sha256.as_str(),
            "{id}: spot_sha256"
        );
    }
}

// ------------------------------------------------------------------- the tree

/// `tests/fixtures/river_trees.json` is what `app/solver/tree.py` builds for the 30 river
/// spots (`tests/fixtures/make_river_trees.py`). Every node must be there with the same
/// player, actions, kind of end, folder and chips put in.
#[test]
fn river_trees_match_app_solver() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/river_trees.json");
    let fixture: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let mut nodes_checked = 0;
    for id in spot_ids("river") {
        let game = load_game(&id);
        let theirs = fixture["spots"][&id]
            .as_array()
            .unwrap_or_else(|| panic!("{id} isn't in the fixture"));
        assert_eq!(theirs.len(), game.tree.nodes.len(), "{id}: number of nodes");
        for want in theirs {
            let key = want[0].as_str().unwrap();
            let node = game
                .tree
                .nodes
                .iter()
                .find(|n| n.key == key)
                .unwrap_or_else(|| panic!("{id}: node {key:?} is missing"));
            let (player, terminal, folder) = match &node.kind {
                NodeKind::Decision { player, .. } => (*player as i64, "", -1),
                NodeKind::Fold { folder } => (-1, "fold", *folder as i64),
                NodeKind::Showdown => (-1, "showdown", -1),
                NodeKind::Chance { .. } => panic!("{id}: a river tree has no chance node"),
            };
            let actions: Vec<Value> = node
                .actions()
                .iter()
                .map(|a| Value::String(a.token()))
                .collect();
            assert_eq!(want[1], player, "{id} {key:?}: player");
            assert_eq!(want[2], Value::Array(actions), "{id} {key:?}: actions");
            assert_eq!(want[3], terminal, "{id} {key:?}: terminal");
            assert_eq!(want[4], folder, "{id} {key:?}: folder");
            assert_eq!(want[5], serde_json::json!(node.put), "{id} {key:?}: put_in");
            // each action leads to the node keyed by one more token
            for (action, &child) in node.actions().iter().zip(node.children()) {
                let child_key = format!("{key} {}", action.token());
                assert_eq!(
                    game.tree.nodes[child].key,
                    child_key.trim(),
                    "{id} {key:?}: child"
                );
            }
            nodes_checked += 1;
        }
    }
    assert_eq!(nodes_checked, 882);
}

/// Every answer key lists the spot's decision nodes in the order of `spots.decision_nodes`,
/// and TexasSolver's own tree was matched to them when the keys were made. Ours must give
/// the same nodes, actors and actions in the same order, on all 40 spots.
fn tree_matches_key(id: &str) {
    let game = load_game(id);
    let key = Key::load(&game);
    let tree = &game.tree;
    assert_eq!(
        key.file.header["nodes"],
        tree.decision_order.len(),
        "{id}: number of decision nodes"
    );
    assert_eq!(
        key.file.nodes.len(),
        tree.decision_order.len(),
        "{id}: number of node lines"
    );
    for (record, &node_id) in key.file.nodes.iter().zip(&tree.decision_order) {
        let node = &tree.nodes[node_id];
        let actions: Vec<String> = node.actions().iter().map(Action::token).collect();
        assert_eq!(record.node, node.key, "{id}: node order");
        assert_eq!(
            record.actor,
            tree.actor_name(node_id),
            "{id} {:?}: actor",
            node.key
        );
        assert_eq!(record.actions, actions, "{id} {:?}: actions", node.key);
        // the key has exactly the combos that can be dealt at the node
        let player = node.player().unwrap();
        let dealt = match node.runout {
            Some(r) => game.runouts[r].alive[player]
                .iter()
                .filter(|a| **a != 0.0)
                .count(),
            None => game.n(player),
        };
        assert_eq!(record.strategy.len(), dealt, "{id} {:?}: combos", node.key);
    }
    assert_eq!(key.filled, 0, "{id}: rows the key leaves out");
}

#[test]
fn river_trees_match_the_answer_keys() {
    for id in spot_ids("river") {
        tree_matches_key(&id);
    }
}

#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn turn_trees_match_the_answer_keys() {
    for id in spot_ids("turn") {
        tree_matches_key(&id);
    }
}

// ----------------------------------------------------- the exploitability check

/// Our exploitability of TexasSolver's river strategies is the number TexasSolver reports,
/// to the third decimal of the percent, as `app/solver/exploitability.py`'s is. It is also
/// the number `app/solver` itself gave for the same strategies (`checks.exploitability_pot`
/// in each key), far closer than that.
#[test]
fn our_exploitability_of_texassolvers_river_answers_is_texassolvers() {
    for id in spot_ids("river") {
        let game = load_game(&id);
        let key = Key::load(&game);
        let ours = exploitability(&game, &key.strategy, false);
        let (ours_pct, theirs_pct) = (ours.percent(), 100.0 * key.reported());
        assert!(
            (ours_pct - theirs_pct).abs() < 0.0005,
            "{id}: ours {ours_pct:.5}%, TexasSolver's {theirs_pct:.5}%"
        );
        let python = key.file.header["checks"]["exploitability_pot"]
            .as_f64()
            .expect("checks.exploitability_pot");
        assert!(
            (ours.pot_share() - python).abs() < 1e-7,
            "{id}: ours {:.8}, app/solver's {python:.8}",
            ours.pot_share()
        );
        assert!((ours.value[0] + ours.value[1] - game.spot.pot).abs() < 1e-9);
        assert!(
            ours.best_response[0] >= ours.value[0] - 1e-9
                && ours.best_response[1] >= ours.value[1] - 1e-9
        );
        // the answer's values and the bounds on the true value, as app/solver stored them
        // (rounded to six decimals)
        let (values, stored_bounds) = key.stored_values().expect("a river key has values");
        let mine = bounds(&ours);
        for (what, ours, theirs) in [
            ("OOP's value", ours.value[OOP], values[OOP]),
            ("IP's value", ours.value[IP], values[IP]),
            ("the low bound", mine[0], stored_bounds[0]),
            ("the high bound", mine[1], stored_bounds[1]),
        ] {
            assert!(
                (ours - theirs).abs() < 2e-6,
                "{id}: {what} is {ours:.7} here, {theirs:.7} in the key"
            );
        }
    }
}

// ------------------------------------------------------------- solving, river

fn check_against_key(game: &Game, solution: &Solution) {
    let id = &game.spot.id;
    let pot = game.spot.pot;
    // the solver's own number is the exact exploitability of the strategy it returned
    let checked = exploitability(game, &solution.strategy, false);
    assert!(
        (checked.pot_share() - solution.exploitability).abs() < 1e-9,
        "{id}: the solver says {}, the checker {}",
        solution.exploitability,
        checked.pot_share()
    );
    assert!(
        checked.pot_share() < GATE_EXPLOITABILITY,
        "{id}: exploitability {:.4}% of the pot after {} iterations",
        checked.percent(),
        solution.iterations
    );
    assert!(solution.converged, "{id}: the target wasn't reached");
    assert!((solution.values[0] - checked.value[0]).abs() < 1e-9);
    // Each player's value within 0.5% of the pot of TexasSolver's. A river key stores the
    // value of its answer and bounds on the true value; a turn key doesn't, so they are
    // worked out here.
    let key = Key::load(game);
    let (theirs, their_bounds) = match key.stored_values() {
        Some((values, stored_bounds)) => (values[OOP], stored_bounds),
        None => {
            let e = exploitability(game, &key.strategy, game.is_turn());
            (e.value[OOP], bounds(&e))
        }
    };
    for (player, (ours, theirs)) in [(checked.value[0], theirs), (checked.value[1], pot - theirs)]
        .iter()
        .enumerate()
    {
        let gap = 100.0 * (ours - theirs).abs() / pot;
        assert!(
            gap <= GATE_VALUE_PCT,
            "{id}: player {player} wins {ours:.3}, with TexasSolver's strategy {theirs:.3} ({gap:.3}% of the pot apart)"
        );
    }
    // The true value lies inside both answers' bounds, so the two intervals must meet
    // (`data/SPOT_FORMAT.md`, "Comparing a solver with a RESULT").
    let mine = bounds(&checked);
    assert!(
        mine[0] <= mine[1] + 1e-9 && checked.value[0] >= mine[0] - 1e-9,
        "{id}: bounds {mine:?}"
    );
    assert!(
        mine[0] <= their_bounds[1] + 1e-6 && their_bounds[0] <= mine[1] + 1e-6,
        "{id}: the true value is in {mine:?} by our answer and in {their_bounds:?} by TexasSolver's"
    );
    // rows are probabilities
    for (node, probs) in game.tree.nodes.iter().zip(&solution.strategy.probs) {
        let k = node.actions().len().max(1);
        for row in probs.chunks(k) {
            assert!(row.iter().all(|p| (0.0..=1.0 + 1e-12).contains(p)));
            assert!(
                (row.iter().sum::<f64>() - 1.0).abs() < 1e-9,
                "{id} {:?}",
                node.key
            );
        }
    }
}

#[test]
fn river_spots_solve_under_half_a_percent_with_texassolvers_values() {
    assert_eq!(SolveConfig::default().target_exploitability, DEFAULT_TARGET);
    for id in spot_ids("river") {
        let game = load_game(&id);
        let solution = solve(&game, &config(DEFAULT_TARGET, 1));
        check_against_key(&game, &solution);
        // stopping at 0.5% is under 0.5% too (the speed test's setting)
        let quick = solve(&game, &config(GATE_EXPLOITABILITY, 1));
        assert!(
            quick.converged && quick.exploitability <= GATE_EXPLOITABILITY,
            "{id}"
        );
        assert!(quick.iterations <= solution.iterations, "{id}");
    }
}

/// `tests/fixtures/phase2_values.json` is what the Phase 2 solver (`app/solver`) wins on the
/// 30 river spots, solved to 0.1% of the pot (`tests/fixtures/make_phase2_values.py`). At
/// the same target both are within 0.2% of the pot of the game's value, so they can't be
/// more than 0.4% apart.
#[test]
fn river_values_match_the_phase_2_solver() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/phase2_values.json");
    let fixture: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let target = fixture["target_exploitability"].as_f64().unwrap();
    assert_eq!(target, 0.001);
    let mut worst: f64 = 0.0;
    for id in spot_ids("river") {
        let game = load_game(&id);
        let solution = solve(&game, &config(target, 1));
        assert!(solution.converged, "{id}");
        let theirs = &fixture["spots"][&id];
        assert!(
            theirs["exploitability_pot"].as_f64().unwrap() <= target,
            "{id}: the fixture"
        );
        for player in 0..2 {
            let phase2 = theirs["value"][player].as_f64().unwrap();
            let gap = 100.0 * (solution.values[player] - phase2).abs() / game.spot.pot;
            worst = worst.max(gap);
            assert!(
                gap <= GATE_VALUE_PCT,
                "{id}: player {player} wins {:.3}, {phase2:.3} by app/solver ({gap:.3}% of the pot apart)",
                solution.values[player]
            );
        }
    }
    println!("river EVs against app/solver at a 0.1% target: at most {worst:.3}% of the pot apart");
    assert!(worst <= 0.4);
}

#[test]
fn trivial_spots_pass_their_expected_checks() {
    let mut checks = 0;
    for id in ["r01", "r02", "r03"] {
        let game = load_game(id);
        assert!(!game.spot.expected.is_empty(), "{id} has expected checks");
        checks += game.spot.expected.len();
        for target in [GATE_EXPLOITABILITY, 0.003] {
            let solution = solve(&game, &config(target, 1));
            let failures = check_expected(&game.spot, &records(&game, &solution.strategy));
            assert!(failures.is_empty(), "{id} at {target}: {failures:?}");
        }
        // TexasSolver's answer passes them too, and a wrong answer doesn't
        let key = Key::load(&game);
        assert!(check_expected(&game.spot, &key.file.nodes).is_empty());
        let uniform = records(&game, &Strategy::uniform(&game));
        assert!(
            !check_expected(&game.spot, &uniform).is_empty(),
            "{id}: playing at random should fail"
        );
    }
    assert_eq!(checks, 5);
}

#[test]
fn a_solve_repeats_exactly_and_stops_on_each_limit() {
    let game = load_game("r05");
    let fixed = SolveConfig {
        target_exploitability: 0.0,
        max_iterations: Some(40),
        time_ms: None,
        threads: 1,
    };
    let (a, b) = (solve(&game, &fixed), solve(&game, &fixed));
    assert_eq!(a.iterations, 40);
    assert_eq!(a.strategy, b.strategy);
    assert_eq!(a.exploitability, b.exploitability);
    assert!(!a.converged);
    // more iterations get closer
    let more = solve(
        &game,
        &SolveConfig {
            max_iterations: Some(400),
            ..fixed.clone()
        },
    );
    assert!(
        more.exploitability < a.exploitability / 4.0,
        "{} then {}",
        a.exploitability,
        more.exploitability
    );
    // the target stops it early, the clock stops it at all
    let target = solve(&game, &config(0.01, 1));
    assert!(target.converged && target.exploitability <= 0.01 && target.iterations < 400);
    let clock = solve(
        &game,
        &SolveConfig {
            target_exploitability: 0.0,
            max_iterations: None,
            time_ms: Some(20.0),
            threads: 1,
        },
    );
    assert!(
        clock.iterations >= 1 && clock.elapsed_ms < 200.0,
        "{} ms",
        clock.elapsed_ms
    );
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "timing needs a release build: run with --release"
)]
fn river_decisions_take_under_400_ms_at_p95() {
    timed_decision("r01", GATE_EXPLOITABILITY, 1); // warm up
    let mut times = Vec::new();
    for id in spot_ids("river") {
        let (game, solution, ms) = timed_decision(&id, GATE_EXPLOITABILITY, 1);
        assert!(
            solution.exploitability < GATE_EXPLOITABILITY,
            "{}",
            game.spot.id
        );
        times.push(ms);
    }
    let (p50, p95) = (percentile(&times, 50.0), percentile(&times, 95.0));
    let worst = times.iter().cloned().fold(0.0, f64::max);
    println!(
        "river decisions at 0.5% of the pot: p50 {p50:.2} ms, p95 {p95:.2} ms, worst {worst:.2} ms"
    );
    assert!(p95 < GATE_RIVER_P95_MS, "p95 {p95:.1} ms");
}

// -------------------------------------------------------------- solving, turn

#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn turn_spots_solve_under_half_a_percent_with_texassolvers_values() {
    for id in spot_ids("turn") {
        let game = load_game(&id);
        let solution = solve(&game, &config(DEFAULT_TARGET, threads()));
        check_against_key(&game, &solution);
    }
}

/// TexasSolver's turn answers by our exact measure, next to its own number. Ours is higher
/// on every spot, by up to half a percent of the pot, and the reason is known: redoing
/// TexasSolver's arithmetic on our tree (`texassolver_arithmetic`) gives its number to the
/// third decimal on all 10 spots. The README records the numbers.
#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn our_exploitability_of_texassolvers_turn_answers_is_recorded_and_explained() {
    for id in spot_ids("turn") {
        let game = load_game(&id);
        let key = Key::load(&game);
        let theirs_pct = 100.0 * key.reported();
        let exact = exploitability(&game, &key.strategy, true);
        let gap = exact.percent() - theirs_pct;
        println!(
            "{id}: TexasSolver says {theirs_pct:.3}%, exact card removal gives {:.3}% ({gap:+.3}), its own arithmetic {:.3}%",
            exact.percent(),
            100.0 * texassolver_arithmetic(&game, &key.strategy)
        );
        assert!(
            gap > 0.0 && gap < 0.6,
            "{id}: {:.3}% against TexasSolver's {theirs_pct:.3}%",
            exact.percent()
        );
        assert!(exact.pot_share() < 0.0075, "{id}: {:.3}%", exact.percent());
        let redone_pct = 100.0 * texassolver_arithmetic(&game, &key.strategy);
        assert!(
            (redone_pct - theirs_pct).abs() < 0.0005,
            "{id}: TexasSolver's arithmetic gives {redone_pct:.5}%, TexasSolver {theirs_pct:.5}%"
        );
    }
}

#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn a_turn_solve_is_the_same_on_one_thread_and_on_many() {
    let game = load_game("t05");
    let fixed = |threads| SolveConfig {
        target_exploitability: 0.0,
        max_iterations: Some(30),
        time_ms: None,
        threads,
    };
    let (one, many) = (solve(&game, &fixed(1)), solve(&game, &fixed(4)));
    assert_eq!(one.strategy, many.strategy);
    assert_eq!(one.exploitability, many.exploitability);
    let serial = exploitability(&game, &one.strategy, false);
    assert!((serial.pot_share() - one.exploitability).abs() < 1e-12);
}

/// A turn spot's values, the slow way: every (oop combo, ip combo, river card) deal one at
/// a time through the tree, with both players following the strategy. No reach vectors, no
/// card sums, no sorting.
fn value_by_enumeration(game: &Game, strategy: &Strategy) -> f64 {
    fn walk(
        game: &Game,
        strategy: &Strategy,
        id: usize,
        hands: [usize; 2],
        river: Option<eval::Card>,
    ) -> f64 {
        let node = &game.tree.nodes[id];
        match &node.kind {
            NodeKind::Decision {
                player,
                actions,
                children,
            } => {
                let row = strategy.row(game, id, hands[*player]);
                (0..actions.len())
                    .filter(|&a| row[a] > 0.0)
                    .map(|a| row[a] * walk(game, strategy, children[a], hands, river))
                    .sum()
            }
            NodeKind::Chance { cards, children } => {
                let (a, b) = (game.combos[0][hands[0]], game.combos[1][hands[1]]);
                let live: Vec<usize> = (0..cards.len())
                    .filter(|&i| !a.contains(cards[i]) && !b.contains(cards[i]))
                    .collect();
                assert_eq!(live.len(), 44);
                live.iter()
                    .map(|&i| walk(game, strategy, children[i], hands, Some(cards[i])))
                    .sum::<f64>()
                    / 44.0
            }
            NodeKind::Fold { folder } => {
                if *folder == OOP {
                    -node.put[0]
                } else {
                    game.spot.pot + node.put[1]
                }
            }
            NodeKind::Showdown => {
                let board: Vec<eval::Card> = game.spot.board.iter().copied().chain(river).collect();
                let rank =
                    |c: subgame::Combo| eval::eval(&[board.as_slice(), &[c.hi, c.lo]].concat());
                match rank(game.combos[0][hands[0]]).cmp(&rank(game.combos[1][hands[1]])) {
                    std::cmp::Ordering::Greater => game.spot.pot + node.put[1],
                    std::cmp::Ordering::Less => -node.put[0],
                    std::cmp::Ordering::Equal => 0.5 * game.spot.pot,
                }
            }
        }
    }
    let (mut total, mut weight) = (0.0, 0.0);
    for (i, a) in game.combos[0].iter().enumerate() {
        for (j, b) in game.combos[1].iter().enumerate() {
            if b.contains(a.hi) || b.contains(a.lo) {
                continue;
            }
            let w = game.weights[0][i] * game.weights[1][j];
            total += w * walk(game, strategy, 0, [i, j], None);
            weight += w;
        }
    }
    assert!((weight - game.total).abs() < 1e-9 * weight);
    total / weight
}

/// Card removal per runout and the 1/44 river weight, checked against plain enumeration on
/// a real turn spot, for a solved strategy and for TexasSolver's.
#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn turn_values_match_deal_by_deal_enumeration() {
    let game = load_game("t05");
    let key = Key::load(&game);
    let solved = solve(
        &game,
        &SolveConfig {
            max_iterations: Some(20),
            ..config(0.0, 1)
        },
    );
    for (name, strategy) in [("TexasSolver's", &key.strategy), ("ours", &solved.strategy)] {
        let fast = strategy_value(&game, strategy, OOP, false);
        let slow = value_by_enumeration(&game, strategy);
        assert!(
            (fast - slow).abs() < 1e-9,
            "{name}: {fast} by vectors, {slow} deal by deal"
        );
    }
}

/// Exploitability by TexasSolver's own turn arithmetic, as a share of the pot. It weighs
/// each river card 1/46 where 44 cards can come (its source calls this an approximation),
/// on payoffs that add up to 0: each player is taken to have put in half the starting pot.
/// So every line that sees a river counts 44/46 of what it is worth next to a fold on the
/// turn.
fn texassolver_arithmetic(game: &Game, strategy: &Strategy) -> f64 {
    let mut theirs = game.clone();
    theirs.chance_weight = 1.0 / 46.0;
    theirs.payoff_shift = 0.5 * game.spot.pot;
    let best = |player| subgame::exploit::best_response_value(&theirs, strategy, player, true);
    (best(0) + best(1)) / 2.0 / game.spot.pot
}

// ------------------------------------------------------------------ the binary

fn run_binary(args: &[&str]) -> std::process::Output {
    std::process::Command::new(env!("CARGO_BIN_EXE_subgame-solve"))
        .args(args)
        .output()
        .expect("run subgame-solve")
}

#[test]
fn the_binary_writes_a_result_for_the_spot() {
    let spot = spot_path("r05");
    let out = std::env::temp_dir().join(format!("subgame-solve-test-{}.jsonl", std::process::id()));
    let run = run_binary(&[
        spot.to_str().unwrap(),
        "--out",
        out.to_str().unwrap(),
        "--target-exploitability",
        "0.5",
        "--max-iterations",
        "5000",
        "--time-ms",
        "60000",
        "--threads",
        "2",
    ]);
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    assert!(run.stdout.is_empty());
    let file = ResultFile::load(&out).unwrap();
    let written = std::fs::read_to_string(&out).unwrap();
    let header_line = written.lines().next().unwrap();
    std::fs::remove_file(&out).ok();
    let game = load_game("r05");
    let h = &file.header;
    assert_eq!(h["format"], "pokerscribe-answer-key");
    assert_eq!(h["version"], 1);
    assert_eq!(h["label_source"], "solver");
    assert_eq!(h["spot_id"], "r05");
    assert_eq!(h["spot_sha256"], game.spot.sha256.as_str());
    assert_eq!(h["street"], "river");
    assert_eq!(h["nodes"], 18);
    assert_eq!(h["solver"]["name"], "pokerscribe-subgame");
    assert_eq!(h["solver"]["settings"]["accuracy_pct_of_pot"], 0.5);
    assert_eq!(h["solver"]["settings"]["max_iterations"], 5000);
    assert_eq!(h["solver"]["converged"], true);
    assert!(h["solver"]["iterations"].as_u64().unwrap() >= 8);
    assert!(h["solver"]["elapsed_s"].as_f64().unwrap() > 0.0);
    let reported = h["solver"]["exploitability_pot"].as_f64().unwrap();
    assert!(reported <= 0.005);
    let trace = h["solver"]["exploitability_trace"].as_array().unwrap();
    assert!((trace.last().unwrap()[1].as_f64().unwrap() - 100.0 * reported).abs() < 1e-5);
    assert_eq!(h["checks"]["expected_failures"], serde_json::json!([]));
    assert_eq!(h["checks"]["filled_rows"], 0);
    assert_eq!(h["created"].as_str().unwrap().len(), 20);
    // the node lines are the spot's tree, and rebuild a strategy as good as the header says
    let (strategy, filled) = strategy_from_records(&game, &file.nodes).unwrap();
    assert_eq!(filled, 0);
    let ours = exploitability(&game, &strategy, false);
    assert!(
        (ours.pot_share() - reported).abs() < 1e-5,
        "{} from the file, {reported} in the header",
        ours.pot_share()
    );
    // "checks" is the answer as written, measured again: exploitability, values, bounds
    let number = |v: &Value| v.as_f64().unwrap_or_else(|| panic!("not a number: {v}"));
    let checks = &h["checks"];
    assert!((number(&checks["exploitability_pot"]) - ours.pot_share()).abs() < 1e-8);
    let values = [
        number(&checks["values"]["oop"]),
        number(&checks["values"]["ip"]),
    ];
    let range = [
        number(&checks["oop_value_bounds"][0]),
        number(&checks["oop_value_bounds"][1]),
    ];
    assert!(
        (values[OOP] - ours.value[OOP]).abs() < 1e-6 && (values[IP] - ours.value[IP]).abs() < 1e-6
    );
    assert!((values[OOP] + values[IP] - game.spot.pot).abs() < 2e-6);
    assert!(
        (range[0] - bounds(&ours)[0]).abs() < 1e-6 && (range[1] - bounds(&ours)[1]).abs() < 1e-6
    );
    assert!(range[0] <= values[OOP] && values[OOP] <= range[1]);
    assert!(((range[1] - range[0]) / 2.0 / game.spot.pot - ours.pot_share()).abs() < 1e-6);
    // and it meets the answer key's bounds, with a value within the gate of the key's
    let (key_values, key_bounds) = Key::load(&game).stored_values().unwrap();
    assert!(range[0] <= key_bounds[1] && key_bounds[0] <= range[1]);
    assert!(100.0 * (values[OOP] - key_values[OOP]).abs() / game.spot.pot <= 2.0 * GATE_VALUE_PCT);
    // the keys of "checks" come in the order of the format's example
    let block = &header_line[header_line.find("\"checks\":{").expect("a checks block")..];
    let at: Vec<usize> = [
        "\"checks\":{\"exploitability_pot\":",
        "\"filled_rows\":",
        "\"values\":{\"oop\":",
        "\"ip\":",
        "\"oop_value_bounds\":[",
        "\"expected_failures\":[",
    ]
    .iter()
    .map(|key| {
        block
            .find(key)
            .unwrap_or_else(|| panic!("no {key} in {block}"))
    })
    .collect();
    assert!(at[0] == 0 && at.windows(2).all(|w| w[0] < w[1]), "{block}");
    for (record, &id) in file.nodes.iter().zip(&game.tree.decision_order) {
        assert_eq!(record.node, game.tree.nodes[id].key);
        for (_, row) in &record.strategy {
            assert!((row.iter().sum::<f64>() - 1.0).abs() < 1e-4);
        }
    }
}

#[test]
fn the_binary_prints_to_stdout_without_out_and_stops_on_max_iterations() {
    let spot = spot_path("r01");
    let run = run_binary(&[
        spot.to_str().unwrap(),
        "--max-iterations",
        "3",
        "--target-exploitability=0",
    ]);
    assert!(run.status.success());
    let file = ResultFile::parse(&String::from_utf8(run.stdout).unwrap()).unwrap();
    assert_eq!(file.header["solver"]["iterations"], 3);
    assert_eq!(file.header["solver"]["converged"], false);
    assert_eq!(file.nodes.len(), 8);
}

#[test]
fn the_binary_refuses_a_bad_spot_with_a_clear_message() {
    let dir = std::env::temp_dir();
    let good = std::fs::read_to_string(spot_path("r04")).unwrap();
    let cases = [
        ("{ not json", "valid JSON"),
        (
            &good.replace("\"pokerscribe-spot\"", "\"something-else\""),
            "not a pokerscribe-spot",
        ),
        (
            &good.replace("\"street\": \"river\"", "\"street\": \"turn\""),
            "needs 4",
        ),
        (
            &good.replace("\"pot\": 100", "\"pot\": 0"),
            "pot must be more than 0",
        ),
    ];
    for (i, (text, want)) in cases.iter().enumerate() {
        let path = dir.join(format!("subgame-bad-spot-{}-{i}.json", std::process::id()));
        std::fs::write(&path, text).unwrap();
        let run = run_binary(&[path.to_str().unwrap()]);
        std::fs::remove_file(&path).ok();
        let stderr = String::from_utf8_lossy(&run.stderr);
        assert_eq!(run.status.code(), Some(1), "{want}: {stderr}");
        assert!(stderr.contains(want), "{stderr:?} should mention {want:?}");
        assert!(run.stdout.is_empty());
    }
    let missing = run_binary(&["/no/such/spot.json"]);
    assert_eq!(missing.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&missing.stderr).contains("can't read"));
    for args in [
        &[][..],
        &["--threads"][..],
        &["a.json", "--frobnicate"][..],
        &["a.json", "--threads", "0"][..],
        &["a.json", "b.json"][..],
        &["a.json", "--target-exploitability", "lots"][..],
        &["a.json", "--out", "result.jsonl.gz"][..],
    ] {
        let run = run_binary(args);
        assert_eq!(run.status.code(), Some(2), "{args:?}");
        assert!(String::from_utf8_lossy(&run.stderr).contains("usage:"));
    }
}

// ------------------------------------------------------------------ the report

/// Prints the tables of the README. Not a gate: run it by name with `--ignored --nocapture`.
#[test]
#[ignore = "prints the README tables; run by name with --ignored --nocapture"]
fn report() {
    /// The median of five whole decisions (three for one thread on a turn spot).
    fn median_run(id: &str, target: f64, threads: usize, runs: usize) -> (Game, Solution, f64) {
        let mut all: Vec<(Game, Solution, f64)> = (0..runs)
            .map(|_| timed_decision(id, target, threads))
            .collect();
        all.sort_by(|a, b| a.2.partial_cmp(&b.2).unwrap());
        all.swap_remove(runs / 2)
    }
    fn summary(name: &str, times: &[f64]) {
        println!(
            "{name}: p50 {:.1} ms, p95 {:.1} ms, worst {:.1} ms",
            percentile(times, 50.0),
            percentile(times, 95.0),
            times.iter().cloned().fold(0.0, f64::max)
        );
    }
    let n_threads = threads();
    let gap = |game: &Game, solution: &Solution, theirs: f64| {
        100.0 * (solution.values[0] - theirs).abs() / game.spot.pot
    };
    timed_decision("r01", GATE_EXPLOITABILITY, 1); // warm up

    println!("\n### River\n");
    println!("| Spot | Combos (oop, ip) | Nodes | Iter. at 0.5% | ms | Expl. | EV gap | Iter. at 0.3% | ms | Expl. | EV oop | TexasSolver's EV oop | EV gap | TexasSolver's answer: its number | our number |");
    println!("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");
    let (mut quick_times, mut default_times) = (Vec::new(), Vec::new());
    let (mut worst_quick_gap, mut worst_default_gap) = (0.0f64, 0.0f64);
    for id in spot_ids("river") {
        let (game, quick, quick_ms) = median_run(&id, GATE_EXPLOITABILITY, 1, 5);
        let (_, fine, fine_ms) = median_run(&id, DEFAULT_TARGET, 1, 5);
        let key = Key::load(&game);
        let theirs = exploitability(&game, &key.strategy, false);
        quick_times.push(quick_ms);
        default_times.push(fine_ms);
        worst_quick_gap = worst_quick_gap.max(gap(&game, &quick, theirs.value[0]));
        worst_default_gap = worst_default_gap.max(gap(&game, &fine, theirs.value[0]));
        println!(
            "| {id} | {}, {} | {} | {} | {quick_ms:.1} | {:.3}% | {:.3}% | {} | {fine_ms:.1} | {:.3}% | {:.3} | {:.3} | {:.3}% | {:.3}% | {:.3}% |",
            game.n(0),
            game.n(1),
            game.tree.decision_order.len(),
            quick.iterations,
            100.0 * quick.exploitability,
            gap(&game, &quick, theirs.value[0]),
            fine.iterations,
            100.0 * fine.exploitability,
            fine.values[0],
            theirs.value[0],
            gap(&game, &fine, theirs.value[0]),
            100.0 * key.reported(),
            theirs.percent(),
        );
    }
    println!();
    summary("river, whole decision, target 0.5%", &quick_times);
    summary("river, whole decision, target 0.3%", &default_times);
    println!("river, largest EV gap: {worst_quick_gap:.3}% at target 0.5%, {worst_default_gap:.3}% at target 0.3%");
    for target in ["0.5", "0.3"] {
        // the binary, process start included
        let mut times = Vec::new();
        for id in spot_ids("river") {
            let spot = spot_path(&id);
            let start = Instant::now();
            let run = run_binary(&[spot.to_str().unwrap(), "--target-exploitability", target]);
            times.push(start.elapsed().as_secs_f64() * 1000.0);
            assert!(run.status.success());
        }
        summary(
            &format!("river, subgame-solve as a process, target {target}%"),
            &times,
        );
    }

    println!("\n### Turn ({n_threads} threads)\n");
    println!("| Spot | Combos (oop, ip) | Nodes | Iter. at 0.5% | ms | ms, 1 thread | Expl. | EV gap | Iter. at 0.3% | ms | ms, 1 thread | Expl. | EV oop | TexasSolver's EV oop | EV gap |");
    println!("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");
    let mut keys = Vec::new();
    let (mut quick_times, mut default_times, mut quick_one, mut default_one) =
        (Vec::new(), Vec::new(), Vec::new(), Vec::new());
    for id in spot_ids("turn") {
        let (game, quick, quick_ms) = median_run(&id, GATE_EXPLOITABILITY, n_threads, 5);
        let (_, _, quick_one_ms) = median_run(&id, GATE_EXPLOITABILITY, 1, 3);
        let (_, fine, fine_ms) = median_run(&id, DEFAULT_TARGET, n_threads, 5);
        let (_, _, fine_one_ms) = median_run(&id, DEFAULT_TARGET, 1, 3);
        let key = Key::load(&game);
        let theirs = exploitability(&game, &key.strategy, true);
        quick_times.push(quick_ms);
        default_times.push(fine_ms);
        quick_one.push(quick_one_ms);
        default_one.push(fine_one_ms);
        println!(
            "| {id} | {}, {} | {} | {} | {quick_ms:.0} | {quick_one_ms:.0} | {:.3}% | {:.3}% | {} | {fine_ms:.0} | {fine_one_ms:.0} | {:.3}% | {:.3} | {:.3} | {:.3}% |",
            game.n(0),
            game.n(1),
            game.tree.decision_order.len(),
            quick.iterations,
            100.0 * quick.exploitability,
            gap(&game, &quick, theirs.value[0]),
            fine.iterations,
            100.0 * fine.exploitability,
            fine.values[0],
            theirs.value[0],
            gap(&game, &fine, theirs.value[0]),
        );
        keys.push((
            id,
            100.0 * key.reported(),
            theirs.percent(),
            100.0 * texassolver_arithmetic(&game, &key.strategy),
        ));
    }
    println!();
    summary(
        &format!("turn, whole decision, target 0.5%, {n_threads} threads"),
        &quick_times,
    );
    summary("turn, whole decision, target 0.5%, 1 thread", &quick_one);
    summary(
        &format!("turn, whole decision, target 0.3%, {n_threads} threads"),
        &default_times,
    );
    summary("turn, whole decision, target 0.3%, 1 thread", &default_one);

    println!("\n### TexasSolver's turn answers\n");
    println!("| Spot | TexasSolver's number | Our number (exact card removal) | Difference | Its arithmetic redone on our tree |");
    println!("| --- | ---: | ---: | ---: | ---: |");
    for (id, theirs, exact, redone) in keys {
        println!(
            "| {id} | {theirs:.3}% | {exact:.3}% | {:+.3} | {redone:.3}% |",
            exact - theirs
        );
    }
}
