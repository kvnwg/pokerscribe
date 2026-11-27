use cfr::{Mccfr, MccfrConfig, Sampling, Solver};
use toygames::Leduc;

fn run(cfg: MccfrConfig) -> (Vec<f64>, Vec<u64>) {
    let mut solver = Mccfr::new(Leduc::new(2), cfg);
    solver.run(5_000);
    let keys = solver.table().keys().to_vec();
    (solver.regrets().to_vec(), keys)
}

#[test]
fn same_seed_same_run_different_seed_different_run() {
    for sampling in [Sampling::External, Sampling::OUTCOME] {
        let cfg = MccfrConfig::new(sampling, 42).linear(100, 10_000);
        let a = run(cfg);
        let b = run(cfg);
        assert_eq!(a, b, "{sampling:?}: same seed must reproduce bit for bit");
        let c = run(MccfrConfig { seed: 43, ..cfg });
        assert_ne!(
            a.0, c.0,
            "{sampling:?}: a different seed should change the run"
        );
    }
}

#[test]
fn for_each_set_gives_the_same_numbers_as_the_copies() {
    let cfg = MccfrConfig::new(Sampling::External, 7)
        .linear(100, 10_000)
        .compact(100.0)
        .threads(2);
    let mut solver = Mccfr::new(Leduc::new(2), cfg);
    solver.run(3_000);
    let table = solver.table();
    let (regrets, sums) = (solver.regrets(), solver.strategy_sums());
    let mut seen = std::collections::HashMap::new();
    solver.for_each_set(|key, r, s| {
        assert!(
            seen.insert(key, (r.to_vec(), s.to_vec())).is_none(),
            "a set twice"
        );
    });
    assert_eq!(seen.len(), table.len());
    for (i, set) in table.sets().iter().enumerate() {
        let (r, s) = &seen[&table.key(i as u32)];
        assert_eq!(r.as_slice(), &regrets[set.range()]);
        assert_eq!(s.as_slice(), &sums[set.range()]);
    }
}
