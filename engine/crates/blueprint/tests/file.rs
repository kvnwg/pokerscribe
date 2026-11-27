//! The strategy file: what goes in comes out, damage and the wrong game are refused, and
//! the dense layout agrees with the solver's own table.

mod common;

use std::path::PathBuf;

use abstract_game::Menus;
use blueprint::{decode, Layout, StrategyFile};
use cfr::{Policy, Solver};
use common::{game, trained};

fn temp(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("blueprint-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    dir.join(name)
}

#[test]
fn the_file_holds_the_average_strategy() {
    let iterations = if cfg!(debug_assertions) {
        2_000
    } else {
        20_000
    };
    let solver = trained(8, Menus::minimal(), iterations);
    let export = StrategyFile::from_solver(&solver, None, None, 1.5);
    let file = &export.file;
    let g = solver.game();
    let layout = Layout::of(g);
    assert_eq!(file.header.iterations, iterations);
    assert_eq!(file.header.info_sets, layout.info_sets());
    assert_eq!(file.header.slots, layout.slots());
    assert_eq!(file.header.info_sets as u128, g.info_sets());
    assert!(file.header.visited > 0 && file.header.visited <= file.header.info_sets);
    assert_eq!(file.header.train_seconds, 1.5);

    // Every information set the solver has: the stored numbers are its average strategy
    // to within rounding.
    // Where training left no strategy sums, the current strategy (regret matching).
    let average = solver.average_policy();
    let current = solver.current_policy();
    let sums = solver.strategy_sums();
    let nodes = g.tree().len() as u64;
    let (mut checked, mut current_only) = (0, 0);
    for (i, set) in average.table().sets().iter().enumerate() {
        let key = average.table().key(i as u32);
        let (node, bucket) = ((key % nodes) as u32, key / nodes);
        let start = layout.start(node, bucket);
        let n = set.num_actions as usize;
        let mut stored = vec![0.0; n];
        decode(&file.probs[start..start + n], &mut stored);
        let mut want = vec![0.0; n];
        if sums[set.range()].iter().sum::<f64>() > 0.0 {
            average.action_probs(key, &mut want);
        } else {
            current.action_probs(key, &mut want);
            current_only += 1;
        }
        for (a, b) in stored.iter().zip(&want) {
            assert!((a - b).abs() < 1e-4, "{key}: {stored:?} against {want:?}");
        }
        checked += 1;
    }
    assert_eq!(checked, solver.info_sets());
    assert!(current_only as u64 >= export.from_regrets);
    assert!(export.weights.iter().sum::<f64>() > 0.0);

    // Saved and loaded: the same bytes and the same strategy.
    let path = temp("round_trip.bps");
    let bytes = file.save(&path).unwrap();
    let back = StrategyFile::load(&path).unwrap();
    assert_eq!(&back, file);
    assert_eq!(bytes as usize, file.to_bytes().len());
    assert_eq!(
        bytes,
        24 + serde_json::to_vec(&file.header).unwrap().len() as u64 + 2 * file.header.slots
    );
    assert!(back.check_game(g).is_ok());

    // The wrong game is refused, and so is a damaged file.
    assert!(back.check_game(&game(9, Menus::minimal())).is_err());
    assert!(back.check_game(&game(8, Menus::small())).is_err());
    let mut damaged = file.to_bytes();
    let k = damaged.len() - 20;
    damaged[k] ^= 1;
    let err = StrategyFile::from_bytes(&damaged).unwrap_err();
    assert!(err.to_string().contains("checksum"), "{err}");
    let mut short = file.to_bytes();
    short.truncate(short.len() - 3);
    assert!(StrategyFile::from_bytes(&short).is_err());
    assert!(StrategyFile::from_bytes(b"not a strategy file at all").is_err());
    std::fs::remove_file(&path).unwrap();
}

#[test]
fn the_change_between_two_strategies() {
    let a = trained(8, Menus::minimal(), 3_000);
    let first = StrategyFile::from_solver(&a, None, None, 0.0);
    let layout = Layout::of(a.game());
    // A strategy has not moved from itself.
    assert_eq!(
        first.file.change_from(&first.file, &layout, &first.weights),
        0.0
    );
    let mut b = a;
    b.run(3_000);
    let second = StrategyFile::from_solver(&b, None, None, 0.0);
    let change = second
        .file
        .change_from(&first.file, &layout, &second.weights);
    assert!(change > 0.0 && change < 1.0, "{change}");
}
