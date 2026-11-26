//! The single-threaded Monte Carlo solver, pinned bit for bit.
//!
//! The fingerprints below were recorded from the solver as it was before it
//! learned to run on several threads (flat `Vec<f64>` arrays, one thread).
//! With one thread and `f64` regrets it must still give exactly these runs:
//! the same random draws in the same order and the same arithmetic.

use cfr::{Game, Mccfr, MccfrConfig, Sampling, Solver};
use toygames::{Kuhn, Leduc};

/// FNV-1a over every information set in key order: the key, the player, the
/// regrets and the average strategy, as raw bits.
fn fingerprint<G: Game + Sync>(solver: &Mccfr<G>) -> u64 {
    let table = solver.table();
    let regrets = solver.regrets();
    let average = solver.average_policy();
    let mut rows: Vec<(u64, Vec<u64>)> = Vec::new();
    for (i, set) in table.sets().iter().enumerate() {
        let key = table.keys()[i];
        let mut bits = vec![set.player as u64, set.num_actions as u64];
        bits.extend(regrets[set.range()].iter().map(|x| x.to_bits()));
        bits.extend(average.get(key).unwrap().iter().map(|x| x.to_bits()));
        rows.push((key, bits));
    }
    rows.sort();
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    let mut eat = |x: u64| {
        for b in x.to_le_bytes() {
            h = (h ^ b as u64).wrapping_mul(0x100_0000_01b3);
        }
    };
    for (key, bits) in &rows {
        eat(*key);
        bits.iter().for_each(|&b| eat(b));
    }
    let stats = solver.stats();
    eat(solver.iterations());
    eat(stats.nodes_touched);
    eat(stats.pruned_traversals);
    eat(stats.pruned_actions);
    h
}

fn configs() -> Vec<(&'static str, MccfrConfig)> {
    let es = MccfrConfig::new(Sampling::External, 11);
    let os = MccfrConfig::new(Sampling::OUTCOME, 11);
    vec![
        ("es", es),
        ("es-linear", es.linear(100, 10_000)),
        (
            "es-prune",
            es.linear(50, 5_000)
                .pruning(2_000, -20.0, 0.95)
                .regret_floor(-500.0),
        ),
        ("os", os),
        ("os-linear", os.linear(250, 20_000)),
    ]
}

fn run<G: Game + Sync + Copy>(game: G) -> Vec<(&'static str, u64)> {
    configs()
        .into_iter()
        .map(|(name, cfg)| {
            let mut solver = Mccfr::new(game, cfg);
            // In two parts, so `run` is entered with a warm table too.
            solver.run(12_345);
            solver.run(17_655);
            (name, fingerprint(&solver))
        })
        .collect()
}

#[test]
fn one_thread_with_float_regrets_is_the_run_it_always_was() {
    let expected: [(&str, [u64; 5]); 3] = [
        (
            "kuhn2",
            [
                0x6719_0f0c_d6f1_7084,
                0x1bc3_5dba_66d0_d97f,
                0x0ebc_7860_cdf4_5253,
                0xb028_bc70_e89f_020b,
                0x7186_4370_3463_e82b,
            ],
        ),
        (
            "kuhn3",
            [
                0x481d_e543_6090_e237,
                0x483c_8db6_e67b_f458,
                0xb3b9_0194_462c_1d2a,
                0x0da4_a40c_51fb_5296,
                0x8a47_d2fe_c016_c4b4,
            ],
        ),
        (
            "leduc",
            [
                0xf328_853a_7b0b_760c,
                0x5cd0_402a_b4b5_ff91,
                0x9e35_2bb0_9ef7_b677,
                0x8015_adf0_c643_e611,
                0x6006_2618_c238_8510,
            ],
        ),
    ];
    let got = [
        ("kuhn2", run(Kuhn::new(2))),
        ("kuhn3", run(Kuhn::new(3))),
        ("leduc", run(Leduc::new(2))),
    ];
    let got: Vec<(&str, Vec<u64>)> = got
        .iter()
        .map(|(game, rows)| (*game, rows.iter().map(|&(_, h)| h).collect()))
        .collect();
    for (game, have) in &got {
        println!("(\"{game}\", {have:#x?}),");
    }
    for ((game, want), (_, have)) in expected.iter().zip(&got) {
        assert_eq!(&have[..], &want[..], "{game}");
    }
}
