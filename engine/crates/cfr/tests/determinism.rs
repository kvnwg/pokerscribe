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
