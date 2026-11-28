//! The half-street river game of The Mathematics of Poker (Chen and Ankenman), whose
//! equilibrium is known in closed form. The same game and numbers as the Phase 2 tests
//! (`app/tests/solver_games.py`, `app/tests/test_solver_answer_keys.py`).
//!
//! Pot 100, board Kh 8d 5c 3s 2h. The caller (out of position) holds QQ and can only check,
//! then call or fold. The bettor (in position) holds KK (3 combos, the value) or JT (16
//! combos, the air) and may bet `s` times the pot. KK beats QQ beats JT and no combo of one
//! player shares a card with the other's. At the equilibrium:
//!
//! - bluffs are `s / (1 + 2s)` of the bets;
//! - the caller calls `1 / (1 + s)` of the time;
//! - the bettor wins `(3 / 19) * (P + sP / (1 + s))` a hand.

use subgame::exploit::exploitability;
use subgame::{solve, solve_as, Game, Play, SolveConfig, Spot, Strategy, IP, OOP};

const POT: f64 = 100.0;
const VALUE: f64 = 3.0;
const AIR: f64 = 16.0;

/// (s, bluff share of bets, call share, bettor's value), hand-checked in solver_games.py.
const HALF_STREET: [(f64, f64, f64, f64); 4] = [
    (0.5, 1.0 / 4.0, 2.0 / 3.0, 400.0 / 19.0),
    (0.75, 3.0 / 10.0, 4.0 / 7.0, 3000.0 / 133.0),
    (1.0, 1.0 / 3.0, 1.0 / 2.0, 450.0 / 19.0),
    (2.0, 2.0 / 5.0, 1.0 / 3.0, 500.0 / 19.0),
];

fn half_street(s: f64) -> Game {
    let suits = ["s", "h", "d", "c"];
    let mut oop = serde_json::Map::new();
    for (i, a) in suits.iter().enumerate() {
        for b in &suits[i + 1..] {
            oop.insert(format!("Q{a}Q{b}"), 1.0.into());
        }
    }
    let mut ip = serde_json::Map::new();
    for combo in ["KsKd", "KsKc", "KdKc"] {
        ip.insert(combo.to_string(), 1.0.into());
    }
    for a in suits {
        for b in suits {
            ip.insert(format!("J{a}T{b}"), 1.0.into());
        }
    }
    let spot = serde_json::json!({
        "format": "pokerscribe-spot", "version": 1, "id": format!("half-street-{s}"), "street": "river",
        "board": ["Kh", "8d", "5c", "3s", "2h"], "pot": POT, "stacks": [100.0 * POT, 100.0 * POT],
        "max_raises": 0,
        "sizes": {"oop": {"bets": [], "raises": [], "allin": false},
                  "ip": {"bets": [s], "raises": [], "allin": false}},
        "ranges": {"oop": oop, "ip": ip},
    });
    Game::new(Spot::from_json(&spot.to_string()).unwrap()).unwrap()
}

/// The three decision nodes: OOP's forced check, the bettor's choice, the caller's answer.
fn nodes(game: &Game) -> (usize, usize) {
    let tree = &game.tree;
    let bettor = tree.decision("x").expect("the bettor's node");
    let bet = tree.nodes[bettor].actions()[1].token();
    let caller = tree
        .decision(&format!("x {bet}"))
        .expect("the caller's node");
    assert_eq!(tree.nodes[tree.decision("").unwrap()].actions().len(), 1); // only a check
    assert_eq!(tree.nodes[bettor].actions().len(), 2); // check or bet
    assert_eq!(tree.nodes[caller].actions().len(), 2); // fold or call, no raise
    (bettor, caller)
}

fn is_value(game: &Game, combo: usize) -> bool {
    game.combos[IP][combo].text().starts_with('K')
}

/// (share of the bets made with air, how often KK bets, how often the caller calls).
fn frequencies(game: &Game, strategy: &Strategy) -> (f64, f64, f64) {
    let (bettor, caller) = nodes(game);
    let (mut bets, mut bluffs, mut value_bets) = (0.0, 0.0, 0.0);
    for combo in 0..game.n(IP) {
        let p_bet = strategy.row(game, bettor, combo)[1];
        bets += p_bet;
        if is_value(game, combo) {
            value_bets += p_bet / VALUE;
        } else {
            bluffs += p_bet;
        }
    }
    let calls: f64 = (0..game.n(OOP))
        .map(|c| strategy.row(game, caller, c)[1])
        .sum::<f64>()
        / game.n(OOP) as f64;
    (bluffs / bets, value_bets, calls)
}

#[test]
fn the_closed_form_answer_cannot_be_exploited() {
    for (s, _, call, value) in HALF_STREET {
        let game = half_street(s);
        assert_eq!((game.n(OOP), game.n(IP)), (6, 19));
        let (bettor, caller) = nodes(&game);
        let mut strategy = Strategy::uniform(&game);
        let bluff = (VALUE * s / (1.0 + s)) / AIR; // each JT combo
        for combo in 0..game.n(IP) {
            let p = if is_value(&game, combo) { 1.0 } else { bluff };
            strategy.probs[bettor][combo * 2..combo * 2 + 2].copy_from_slice(&[1.0 - p, p]);
        }
        for combo in 0..game.n(OOP) {
            strategy.probs[caller][combo * 2..combo * 2 + 2].copy_from_slice(&[1.0 - call, call]);
        }
        let e = exploitability(&game, &strategy, false);
        assert!(e.chips().abs() < 1e-9, "s = {s}: {} chips", e.chips());
        assert!(
            (e.value[IP] - value).abs() < 1e-9,
            "s = {s}: the bettor wins {}",
            e.value[IP]
        );
        assert!((e.value[OOP] - (POT - value)).abs() < 1e-9);
        // and a caller who never calls can be: every bluff then wins the pot
        for combo in 0..game.n(OOP) {
            strategy.probs[caller][combo * 2..combo * 2 + 2].copy_from_slice(&[1.0, 0.0]);
        }
        assert!(exploitability(&game, &strategy, false).pot_share() > 0.1);
    }
}

#[test]
fn the_solver_finds_the_closed_form_answer() {
    const MAX_EXPLOITABILITY: f64 = 0.002; // share of the pot, as the Phase 2 test
    const FREQ_TOL: f64 = 0.02;
    for (s, bluffs, calls, value) in HALF_STREET {
        let game = half_street(s);
        let config = SolveConfig {
            target_exploitability: 0.0005,
            max_iterations: Some(100_000),
            time_ms: None,
            threads: 1,
        };
        let solution = solve(&game, &config);
        assert!(
            solution.exploitability <= MAX_EXPLOITABILITY,
            "s = {s}: {}",
            solution.exploitability
        );
        let (bluff_share, value_bets, call_share) = frequencies(&game, &solution.strategy);
        assert!(
            (bluff_share - bluffs).abs() <= FREQ_TOL,
            "s = {s}: bluffs {bluff_share:.4}, not {bluffs:.4}"
        );
        assert!(
            (call_share - calls).abs() <= FREQ_TOL,
            "s = {s}: calls {call_share:.4}, not {calls:.4}"
        );
        assert!(
            value_bets >= 1.0 - FREQ_TOL,
            "s = {s}: KK bets {value_bets:.4}"
        );
        let tolerance = MAX_EXPLOITABILITY * POT * 2.0;
        assert!(
            (solution.values[IP] - value).abs() <= tolerance,
            "s = {s}: bettor wins {}",
            solution.values[IP]
        );
        assert!((solution.values[OOP] - (POT - value)).abs() <= tolerance);
    }
}

/// `Play::Final` hands back the last iteration's strategy, with that strategy's own
/// exploitability and values; `Play::Average` is `solve` exactly.
#[test]
fn a_solve_can_hand_back_the_last_iteration() {
    let game = half_street(1.0);
    let config = SolveConfig {
        target_exploitability: 0.0,
        max_iterations: Some(500),
        time_ms: None,
        threads: 1,
    };
    let average = solve(&game, &config);
    assert_eq!(
        solve_as(&game, &config, Play::Average).strategy.probs,
        average.strategy.probs
    );
    let last = solve_as(&game, &config, Play::Final);
    assert_eq!(last.iterations, average.iterations);
    assert_ne!(last.strategy.probs, average.strategy.probs);
    let (bettor, caller) = nodes(&game);
    for (node, n) in [(bettor, game.n(IP)), (caller, game.n(OOP))] {
        for combo in last.strategy.probs[node].chunks_exact(2).take(n) {
            assert!((combo.iter().sum::<f64>() - 1.0).abs() < 1e-12, "{combo:?}");
        }
    }
    let e = exploitability(&game, &last.strategy, false);
    assert!((e.pot_share() - last.exploitability).abs() < 1e-12);
    assert!((e.value[OOP] - last.values[OOP]).abs() < 1e-9);
    assert!((e.value[IP] - last.values[IP]).abs() < 1e-9);
    eprintln!(
        "average {:.6}, last {:.6}",
        average.exploitability, last.exploitability
    );
}
