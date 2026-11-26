//! Leduc hold'em against OpenSpiel. The reference numbers come from
//! tools/reference/openspiel_leduc.py (OpenSpiel 2.0.2), committed in
//! tests/data/openspiel_leduc.json.

mod common;

use cfr::{expected_values, exploitability, nash_conv, Cfr, Game, Solver, UniformPolicy, Variant};
use common::{measure, Json};
use toygames::Leduc;

fn reference() -> Json {
    Json::parse(include_str!("data/openspiel_leduc.json"))
}

#[test]
fn same_game_as_openspiel() {
    let r = reference();
    let solver = Cfr::new(Leduc::new(2), Variant::Vanilla);
    let per_player: Vec<usize> = (0..2)
        .map(|p| {
            solver
                .table()
                .sets()
                .iter()
                .filter(|s| s.player as usize == p)
                .count()
        })
        .collect();
    let expected: Vec<usize> = r
        .get("info_states_per_player")
        .arr()
        .iter()
        .map(|x| x.num() as usize)
        .collect();
    assert_eq!(per_player, expected);

    let game = Leduc::new(2);
    let uniform = r.get("uniform_policy").get("nash_conv").num();
    let ours = nash_conv(&game, &UniformPolicy);
    assert!(
        (ours - uniform).abs() < 1e-12,
        "uniform NashConv {ours} vs OpenSpiel {uniform}"
    );
    assert!(expected_values(&game, &UniformPolicy)[0].abs() < 1e2);
}

#[test]
fn vanilla_cfr_matches_openspiel() {
    let r = reference();
    let game = Leduc::new(2);
    let mut solver = Cfr::new(game, Variant::Vanilla);
    for row in r.get("vanilla_cfr_python").arr() {
        let it = row.get("iteration").num() as u64;
        solver.run(it - solver.iterations());
        let (expl, value) = measure(&game, &solver);
        let want_expl = row.get("exploitability").num();
        let want_value = row.get("value_player0").num();
        println!("iteration {it}: exploitability {expl:.12} (OpenSpiel {want_expl:.12}), value {value:.12} (OpenSpiel {want_value:.12})");
        assert!(
            (expl - want_expl).abs() <= 1e-12 * want_expl.max(1.0),
            "iteration {it}: exploitability {expl} vs OpenSpiel {want_expl}"
        );
        assert!(
            (value - want_value).abs() <= 1e-12,
            "iteration {it}: value {value} vs OpenSpiel {want_value}"
        );
    }
}

#[test]
fn fast_variants_reach_openspiel_equilibrium_value() {
    let r = reference();
    let want = r.get("equilibrium").get("value_player0").num();
    let game = Leduc::new(2);
    for variant in [Variant::CfrPlus, Variant::DCFR] {
        let mut solver = Cfr::new(game, variant);
        solver.run(2000);
        let pol = solver.average_policy();
        let expl = exploitability(&game, &pol);
        let value = expected_values(&game, &pol)[0];
        println!("{variant:?}: exploitability {expl:.2e}, value {value:.6} (OpenSpiel equilibrium {want:.6})");
        assert!(expl < 2e-4, "{variant:?}: exploitability {expl}");
        assert!(
            (value - want).abs() < 1e-3,
            "{variant:?}: value {value} vs {want}"
        );
    }
    assert_eq!(game.num_players(), 2);
}
