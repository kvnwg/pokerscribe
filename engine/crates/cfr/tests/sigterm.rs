//! SIGTERM, which a Spot machine gets before it is shut down: the run stops
//! at once, saves, and the resumed run ends where an uninterrupted one does.
//!
//! The stop flag is one per process, so these steps are one test, in order.

#![cfg(unix)]

mod common;

use std::time::Duration;

use cfr::{signal, Checkpoints, Mccfr, MccfrConfig, Sampling, Solver, Stop};
use common::{run_state, TempDir};
use toygames::Leduc;

extern "C" {
    fn getpid() -> i32;
    fn kill(pid: i32, signal: i32) -> i32;
}

const SIGTERM: i32 = 15;

/// Sends this process a real SIGTERM a little later, as the cloud would.
fn sigterm_in(delay: Duration) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        std::thread::sleep(delay);
        // SAFETY: the C library's kill and getpid; the handler is installed.
        assert_eq!(unsafe { kill(getpid(), SIGTERM) }, 0);
    })
}

#[test]
fn sigterm_stops_the_run_which_saves_and_resumes_to_the_same_end() {
    let dir = TempDir::new("sigterm");
    let saves = Checkpoints::new(dir.file("run.ckpt"));
    signal::watch_sigterm().unwrap();
    assert!(!signal::stop_requested());

    // One thread: stopped by the signal, far from the end.
    let cfg = MccfrConfig::new(Sampling::External, 17).linear(200, 50_000);
    let mut solver = Mccfr::new(Leduc::new(2), cfg);
    let sender = sigterm_in(Duration::from_millis(40));
    let report = solver.train(u64::MAX / 2, Some(&saves)).unwrap();
    sender.join().unwrap();
    assert_eq!(report.stop, Stop::Requested);
    assert_eq!(report.saves, 1);
    assert!(signal::stop_requested());
    let stopped_at = solver.iterations();
    assert!(stopped_at > 0, "40 ms is thousands of Leduc iterations");
    let at_stop = run_state(&solver);
    drop(solver);

    // While the flag is up, train only saves: nothing more is run.
    let mut resumed = Mccfr::resume(Leduc::new(2), saves.path()).unwrap();
    assert_eq!(run_state(&resumed), at_stop);
    let held = resumed.train(stopped_at + 1_000, Some(&saves)).unwrap();
    assert_eq!((held.stop, held.saves), (Stop::Requested, 1));
    assert_eq!(resumed.iterations(), stopped_at);

    // The next start: the flag is down, and the run goes on to its end.
    signal::clear();
    let target = stopped_at + 7_777;
    let done = resumed.train(target, Some(&saves)).unwrap();
    assert_eq!(done.stop, Stop::Finished);
    let mut whole = Mccfr::new(Leduc::new(2), cfg);
    whole.run(target);
    assert_eq!(run_state(&resumed), run_state(&whole));

    // Several threads stop on the same signal, each after the iteration it
    // is in, and every iteration started is counted.
    let mut team = Mccfr::new(Leduc::new(2), cfg.threads(4));
    let sender = sigterm_in(Duration::from_millis(40));
    let report = team.train(u64::MAX / 2, Some(&saves)).unwrap();
    sender.join().unwrap();
    assert_eq!(report.stop, Stop::Requested);
    assert!(team.iterations() > 0);
    let back = Mccfr::resume(Leduc::new(2), saves.path()).unwrap();
    assert_eq!(run_state(&back), run_state(&team));
    assert_eq!(back.config().threads, 4);

    // A stop asked for by hand does the same as the signal.
    signal::clear();
    let mut by_hand = Mccfr::new(Leduc::new(2), cfg);
    let asker = std::thread::spawn(|| {
        std::thread::sleep(Duration::from_millis(20));
        signal::request_stop();
    });
    let report = by_hand.train(u64::MAX / 2, None).unwrap();
    asker.join().unwrap();
    assert_eq!((report.stop, report.saves), (Stop::Requested, 0));
    signal::clear();
}
