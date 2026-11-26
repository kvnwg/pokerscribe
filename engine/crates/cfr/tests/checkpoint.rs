//! Checkpoints: a run that is saved, loaded and continued ends bit for bit
//! where the same run ends without stopping, and a save can't damage the
//! checkpoint before it.

mod common;

use std::io::ErrorKind;
use std::time::Duration;

use cfr::{Checkpoints, Mccfr, MccfrConfig, Sampling, Solver, Stop};
use common::{run_state, TempDir};
use toygames::{Kuhn, Leduc};

fn configs() -> Vec<(&'static str, MccfrConfig)> {
    let es = MccfrConfig::new(Sampling::External, 21);
    vec![
        ("es", es),
        (
            "es-linear-prune-floor",
            es.linear(100, 4_000)
                .pruning(1_500, -20.0, 0.95)
                .regret_floor(-300.0),
        ),
        (
            "os-linear",
            MccfrConfig::new(Sampling::OUTCOME, 21).linear(250, 5_000),
        ),
        ("es-integers", es.compact(1_000.0).regret_floor(-300.0)),
    ]
}

#[test]
fn a_resumed_run_ends_where_the_uninterrupted_one_does() {
    let dir = TempDir::new("resume");
    for (name, cfg) in configs() {
        let mut whole = Mccfr::new(Leduc::new(2), cfg);
        whole.run(6_000);

        let path = dir.file(name);
        let mut first = Mccfr::new(Leduc::new(2), cfg);
        first.run(2_500);
        first.save(&path).unwrap();
        let at_save = run_state(&first);
        drop(first);

        // Stopped once, at a point that is no multiple of anything.
        let mut second = Mccfr::resume(Leduc::new(2), &path).unwrap();
        assert_eq!(second.config(), &cfg, "{name}");
        assert_eq!(
            run_state(&second),
            at_save,
            "{name}: loading changes nothing"
        );
        second.run(1_501);
        // And a second time, over the first checkpoint.
        second.save(&path).unwrap();
        drop(second);
        let mut third = Mccfr::resume(Leduc::new(2), &path).unwrap();
        third.run(1_999);

        assert_eq!(third.iterations(), 6_000);
        assert_eq!(run_state(&third), run_state(&whole), "{name}");
        // The same state gives the same strategies.
        let (a, b) = (third.average_policy(), whole.average_policy());
        for &key in whole.table().keys() {
            assert_eq!(a.get(key), b.get(key), "{name}");
        }
    }
}

#[test]
fn training_with_saves_on_a_timer_is_the_same_run() {
    let dir = TempDir::new("timer");
    let cfg = MccfrConfig::new(Sampling::External, 5).linear(500, 20_000);
    let mut whole = Mccfr::new(Leduc::new(2), cfg);
    whole.run(60_000);

    let saves = Checkpoints::new(dir.file("run.ckpt")).every(Duration::from_millis(3));
    assert_eq!(saves.interval(), Some(Duration::from_millis(3)));
    let mut solver = Mccfr::new(Leduc::new(2), cfg);
    let report = solver.train(60_000, Some(&saves)).unwrap();
    assert_eq!(report.stop, Stop::Finished);
    // 60,000 iterations of Leduc take far longer than 3 ms: several saves on
    // the way, and one at the end.
    assert!(report.saves >= 3, "{report:?}");
    assert_eq!(run_state(&solver), run_state(&whole));
    // What is on disk is the finished run.
    let loaded = Mccfr::resume(Leduc::new(2), saves.path()).unwrap();
    assert_eq!(run_state(&loaded), run_state(&whole));
    // Asking for iterations already done only saves.
    let again = solver.train(1_000, Some(&saves)).unwrap();
    assert_eq!((again.stop, again.saves), (Stop::Finished, 1));
    assert_eq!(solver.iterations(), 60_000);
    // Without checkpoints, train is run.
    let mut plain = Mccfr::new(Leduc::new(2), cfg);
    let unsaved = plain.train(60_000, None).unwrap();
    assert_eq!((unsaved.saves, unsaved.longest_save), (0, Duration::ZERO));
    assert!(report.longest_save > Duration::ZERO);
    assert_eq!(run_state(&plain), run_state(&whole));
    assert_eq!(
        Checkpoints::new("x").every_minutes(0.5).interval(),
        Some(Duration::from_secs(30))
    );
}

#[test]
fn a_save_that_dies_half_way_leaves_the_last_checkpoint_whole() {
    let dir = TempDir::new("atomic");
    let path = dir.file("run.ckpt");
    let tmp = dir.file("run.ckpt.tmp");
    let cfg = MccfrConfig::new(Sampling::External, 8);
    let mut solver = Mccfr::new(Kuhn::new(3), cfg);
    solver.run(3_000);
    solver.save(&path).unwrap();
    assert!(!tmp.exists(), "the temporary file is renamed away");
    let good = std::fs::read(&path).unwrap();
    let state = run_state(&solver);

    // A later save killed half way: the first half of a newer checkpoint is
    // in the temporary file, and the checkpoint itself was never touched.
    solver.run(3_000);
    let newer = dir.file("newer");
    solver.save(&newer).unwrap();
    let newer_bytes = std::fs::read(&newer).unwrap();
    std::fs::write(&tmp, &newer_bytes[..newer_bytes.len() / 2]).unwrap();
    assert_eq!(std::fs::read(&path).unwrap(), good);
    let back = Mccfr::resume(Kuhn::new(3), &path).unwrap();
    assert_eq!(run_state(&back), state);
    // The half-written file is no checkpoint.
    assert_eq!(
        Mccfr::resume(Kuhn::new(3), &tmp).err().unwrap().kind(),
        ErrorKind::InvalidData
    );

    // The next save writes over the leftover and replaces the checkpoint.
    solver.save(&path).unwrap();
    assert!(!tmp.exists());
    assert_eq!(std::fs::read(&path).unwrap(), newer_bytes);

    // A save that can't be written reports it and changes nothing.
    let nowhere = dir.file("no-such-folder").join("run.ckpt");
    assert!(solver.save(&nowhere).is_err());
    let blocked = Checkpoints::new(&nowhere);
    assert!(solver
        .train(solver.iterations() + 10, Some(&blocked))
        .is_err());
    assert_eq!(std::fs::read(&path).unwrap(), newer_bytes);
    // Saving the same state twice gives the same bytes.
    let twice = dir.file("twice");
    let resumed = Mccfr::resume(Kuhn::new(3), &path).unwrap();
    resumed.save(&twice).unwrap();
    assert_eq!(
        run_state(&Mccfr::resume(Kuhn::new(3), &twice).unwrap()),
        run_state(&resumed)
    );
}

#[test]
fn damaged_checkpoints_are_refused() {
    let dir = TempDir::new("damage");
    let path = dir.file("run.ckpt");
    let cfg = MccfrConfig::new(Sampling::External, 3)
        .linear(50, 1_000)
        .compact(500.0);
    let mut solver = Mccfr::new(Kuhn::new(2), cfg);
    solver.run(2_000);
    solver.save(&path).unwrap();
    let good = std::fs::read(&path).unwrap();
    let broken = dir.file("broken");
    let refused = |bytes: &[u8], why: &str| {
        std::fs::write(&broken, bytes).unwrap();
        let err = Mccfr::resume(Kuhn::new(2), &broken).err();
        let kind = err.unwrap_or_else(|| panic!("{why}: loaded")).kind();
        assert_eq!(kind, ErrorKind::InvalidData, "{why}");
    };
    // Cut short anywhere, down to nothing.
    for len in [
        0,
        5,
        8,
        40,
        110,
        good.len() / 2,
        good.len() - 9,
        good.len() - 1,
    ] {
        refused(&good[..len], &format!("cut to {len} bytes"));
    }
    // One bit changed anywhere: the header, the settings, the tables, the
    // end marker, the checksum.
    for at in [
        0,
        9,
        13,
        30,
        70,
        120,
        good.len() / 2,
        good.len() - 20,
        good.len() - 10,
        good.len() - 1,
    ] {
        let mut bytes = good.clone();
        bytes[at] ^= 0x10;
        refused(&bytes, &format!("bit changed at byte {at}"));
    }
    refused(&[good.as_slice(), &[0]].concat(), "a byte added at the end");
    refused(b"this is not a checkpoint at all, just some text", "text");
    // Another game: Kuhn with three players.
    let err = Mccfr::resume(Kuhn::new(3), &path).err().unwrap();
    assert_eq!(err.kind(), ErrorKind::InvalidData);
    assert!(err.to_string().contains("2 players"), "{err}");
    // No file at all is its own error, so a first start can tell.
    let missing = Mccfr::resume(Kuhn::new(2), dir.file("missing"))
        .err()
        .unwrap();
    assert_eq!(missing.kind(), ErrorKind::NotFound);
    // And the good file still loads.
    let back = Mccfr::resume(Kuhn::new(2), &path).unwrap();
    assert_eq!(run_state(&back), run_state(&solver));
}

#[test]
fn a_run_on_several_threads_is_saved_whole_and_can_change_its_thread_count() {
    let dir = TempDir::new("threads");
    let path = dir.file("run.ckpt");
    let cfg = MccfrConfig::new(Sampling::External, 4)
        .linear(1_000, 10_000)
        .threads(3);
    let mut solver = Mccfr::new(Leduc::new(2), cfg);
    solver.run(20_000);
    assert_eq!(solver.iterations(), 20_000);
    solver.save(&path).unwrap();
    let mut back = Mccfr::resume(Leduc::new(2), &path).unwrap();
    assert_eq!(back.config().threads, 3);
    assert_eq!(run_state(&back), run_state(&solver));
    // On with three threads, then on a machine with one core, then four.
    back.run(5_000);
    back.set_threads(1);
    back.run(5_000);
    back.set_threads(4);
    back.run(5_000);
    assert_eq!(back.iterations(), 35_000);
    assert_eq!(back.config().threads, 4);
    back.save(&path).unwrap();
    let last = Mccfr::resume(Leduc::new(2), &path).unwrap();
    assert_eq!(run_state(&last), run_state(&back));
}
