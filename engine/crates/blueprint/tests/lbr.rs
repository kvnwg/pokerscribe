//! LBR against a trained blueprint: training makes it much harder to exploit than playing
//! uniformly at random over the same menu, and the match runs end to end.

mod common;

use abstract_game::{AbstractGame, GameConfig, Menus};
use blueprint::{Blueprint, StrategyFile};
use cfr::{Mccfr, MccfrConfig, Sampling, Solver};
use common::{play, Category};
use lbr::{play_match, LbrConfig, MatchConfig};

#[test]
fn training_lowers_what_lbr_wins() {
    if cfg!(debug_assertions) {
        eprintln!("skipped in a debug build: run cargo test --release");
        return;
    }
    let config = GameConfig::new(10, Menus::minimal());
    let game = AbstractGame::new(config.clone(), Category).unwrap();
    let mut solver = Mccfr::new(game, MccfrConfig::new(Sampling::External, 3).compact(100.0));
    solver.run(300_000);
    let trained = play(&solver);

    // The same menu played uniformly: every information set left at zero.
    let mut file = StrategyFile::from_solver(&solver, None, None, 0.0).file;
    file.probs.fill(0);
    let uniform = Blueprint::new(AbstractGame::new(config, Category).unwrap(), file).unwrap();

    let table = MatchConfig {
        stack: 1_000,
        ..MatchConfig::acpc(4_000, 9)
    };
    let lbr = LbrConfig::default();
    let against_trained = play_match(&trained, &lbr, &table);
    let against_uniform = play_match(&uniform, &lbr, &table);
    eprintln!("trained {against_trained}\nuniform {against_uniform}");
    let se = (against_trained.std_err.powi(2) + against_uniform.std_err.powi(2)).sqrt();
    assert!(
        against_uniform.bb_per_100 - against_trained.bb_per_100 > 5.0 * se,
        "trained {against_trained}, uniform {against_uniform}"
    );
    assert!(trained.decisions() > 4_000);
    assert!(
        trained.off_tree_share() < 0.05,
        "{}",
        trained.off_tree_share()
    );
}
