//! The bucket tables in a blueprint run.
//!
//! The first test uses the abstraction crate's small fixture tables (a 20-card deck) and
//! runs everywhere. The ignored one needs built tables for the full deck: set
//! `BLUEPRINT_TABLES` to their directory, or it does nothing and passes (so that a run of
//! every ignored test, as the nightly workflow does, stays green without them):
//!
//! ```text
//! BLUEPRINT_TABLES=~/abstraction/k10 cargo test --release -p blueprint --test tables -- --ignored
//! ```

use std::path::{Path, PathBuf};
use std::sync::Arc;

use abstract_game::{Bucketer, Street};
use abstraction::Abstraction;
use blueprint::{tables_info, Blueprint, Buckets, Run, Spec, Training};
use cfr::{Rng, Solver};
use lbr::{play_match, LbrConfig, MatchConfig};

fn fixture() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../abstraction/tests/fixtures/small")
}

#[test]
fn small_deck_tables_are_described_and_refused() {
    let abstraction = Abstraction::load(&fixture()).unwrap();
    let info = tables_info(&abstraction);
    // Preflop, every class of two hole cards is its own bucket: 25 with 5 ranks.
    let ranks = abstraction.deck().ranks() as u64;
    assert_eq!(ranks, 5);
    assert_eq!(info.buckets[0], ranks * ranks);
    assert!(
        info.buckets[1..].iter().all(|&b| b > 1 && b <= 12),
        "{info:?}"
    );
    for (checksum, street) in info.checksums.iter().zip([
        abstraction::Street::Flop,
        abstraction::Street::Turn,
        abstraction::Street::River,
    ]) {
        assert_eq!(checksum, &abstraction.table(street).unwrap().checksum());
        assert_eq!(checksum.len(), 16);
    }
    assert!(
        info.river_feature.starts_with("ochs"),
        "{}",
        info.river_feature
    );
    // The abstract game deals 52 cards: a blueprint refuses tables for fewer.
    let err = Buckets::load(&fixture()).err().expect("refused");
    assert!(err.to_string().contains("deck of 5 ranks"), "{err}");
}

#[test]
#[ignore = "needs built tables: set BLUEPRINT_TABLES to their directory"]
fn a_run_trains_resumes_saves_and_plays() {
    let Some(dir) = std::env::var_os("BLUEPRINT_TABLES") else {
        eprintln!("BLUEPRINT_TABLES is not set: nothing to check");
        return;
    };
    let tables = PathBuf::from(dir);
    let buckets = Arc::new(Buckets::load(&tables).unwrap());

    // The adapter gives the tables' own buckets.
    let abstraction = buckets.abstraction();
    let mut rng = Rng::new(1);
    for _ in 0..2_000 {
        let mut deck: Vec<u8> = (0..52).collect();
        for i in 0..7 {
            let j = i + rng.below(52 - i);
            deck.swap(i, j);
        }
        let hole = [deck[0], deck[1]];
        for n in [0, 3, 4, 5] {
            let board = &deck[2..2 + n];
            assert_eq!(
                buckets.bucket(hole, board),
                abstraction.bucket(&hole, board) as u64
            );
        }
    }
    assert_eq!(buckets.num_buckets(Street::Preflop), 169);

    // Train, stop, resume: the iterations carry on and the log has both sessions.
    let run_dir = std::env::temp_dir().join(format!("blueprint-run-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&run_dir);
    let spec = Spec {
        stack_bb: 10,
        menu: "minimal".into(),
        abstraction: tables.clone(),
        training: Training {
            threads: 2,
            linear: Some([10_000, 50_000]),
            ..Training::default()
        },
    };
    let mut run = Run::open_with(spec.clone(), &run_dir, buckets.clone()).unwrap();
    let first = run.train(40_000, None).unwrap();
    assert_eq!((first.from, first.to), (0, 40_000));
    drop(run);
    let mut run = Run::open_with(spec.clone(), &run_dir, buckets.clone()).unwrap();
    assert_eq!(run.solver.iterations(), 40_000);
    let second = run.train(80_000, None).unwrap();
    assert_eq!((second.from, second.to), (40_000, 80_000));
    assert_eq!(run.sessions().len(), 2);
    assert!(second.bytes_per_info_set > 0.0 && second.info_sets > 0);
    // Another spec in the same directory is refused.
    let other = Spec {
        stack_bb: 11,
        ..spec.clone()
    };
    assert!(Run::open_with(other, &run_dir, buckets.clone()).is_err());

    // Saved, loaded with its tables, played against LBR.
    let export = run.export();
    assert!(export.file.header.tables.is_some());
    let path = run_dir.join("strategy.bps");
    export.file.save(&path).unwrap();
    let blueprint = Blueprint::load(&path, None).unwrap();
    let table = MatchConfig {
        stack: 1_000,
        ..MatchConfig::acpc(400, 3)
    };
    let r = play_match(&blueprint, &LbrConfig::default(), &table);
    assert!(r.bb_per_100.is_finite());
    assert!(blueprint.decisions() > 0);
    // The file refuses tables other than its own.
    if let Some(other) = std::env::var_os("BLUEPRINT_OTHER_TABLES") {
        let err = Blueprint::load(&path, Some(Path::new(&other)))
            .err()
            .expect("refused");
        assert!(err.to_string().contains("not the ones"), "{err}");
    }
    std::fs::remove_dir_all(&run_dir).unwrap();
}

/// The `tools/cloud` trainer contract (its README, "The trainer"): progress lines, a save
/// and exit code 75 on SIGTERM, `--resume` carrying on, exit 0 and a strategy at the end.
#[test]
#[ignore = "needs built tables: set BLUEPRINT_TABLES to their directory"]
fn the_cloud_trainer_keeps_the_contract() {
    use std::io::{BufRead, BufReader};
    use std::process::{Command, Stdio};

    let Some(tables) = std::env::var_os("BLUEPRINT_TABLES") else {
        eprintln!("BLUEPRINT_TABLES is not set: nothing to check");
        return;
    };
    let dir = std::env::temp_dir().join(format!("blueprint-cloud-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let spec = Spec {
        stack_bb: 10,
        menu: "minimal".into(),
        abstraction: PathBuf::from(tables),
        training: Training {
            threads: 2,
            ..Training::default()
        },
    };
    let until = 6_000_000u64;
    let config = dir.join("config.json");
    std::fs::write(
        &config,
        serde_json::json!({"spec": spec, "until": until, "every_minutes": 0.01}).to_string(),
    )
    .unwrap();
    let ckdir = dir.join("ck");
    let trainer = |resume: bool| {
        let mut c = Command::new(env!("CARGO_BIN_EXE_blueprint"));
        c.arg("--config")
            .arg(&config)
            .arg("--checkpoint-dir")
            .arg(&ckdir);
        if resume {
            c.arg("--resume");
        }
        c.args(["--threads", "2"]).stdout(Stdio::piped());
        c
    };
    let progress = |line: &str| -> Option<u64> {
        let v: serde_json::Value = serde_json::from_str(line).expect("JSON lines");
        assert_eq!(v["target_iterations"], until);
        v.get("event")
            .is_none()
            .then(|| v["iterations"].as_u64().unwrap())
    };

    // --resume with nothing to resume is an error, not a fresh start.
    assert!(!trainer(true).status().unwrap().success());

    // Started, two progress lines (each after a save), then SIGTERM.
    let mut child = trainer(false).spawn().unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    let first = lines.next().unwrap().unwrap();
    assert!(first.contains("\"started\""), "{first}");
    let mut seen = Vec::new();
    while seen.len() < 2 {
        seen.extend(progress(&lines.next().unwrap().unwrap()));
    }
    assert!(Run::checkpoint_path(&ckdir).exists());
    let killed = Command::new("kill")
        .args(["-TERM", &child.id().to_string()])
        .status()
        .unwrap();
    assert!(killed.success());
    let mut last = *seen.last().unwrap();
    for line in lines {
        last = progress(&line.unwrap()).unwrap_or(last);
    }
    let status = child.wait().unwrap();
    assert_eq!(status.code(), Some(75), "a stop saves and exits with 75");
    assert!(last < until, "stopped before the end");

    // Resumed: it carries on from the save and finishes.
    let out = trainer(true).output().unwrap();
    assert!(out.status.success());
    let text = String::from_utf8(out.stdout).unwrap();
    let mut lines = text.lines();
    let resumed: serde_json::Value = serde_json::from_str(lines.next().unwrap()).unwrap();
    assert_eq!(resumed["event"], "resumed");
    assert_eq!(resumed["iterations"].as_u64(), Some(last));
    let finished: serde_json::Value = serde_json::from_str(text.lines().last().unwrap()).unwrap();
    assert_eq!(finished["event"], "done");
    assert_eq!(finished["iterations"].as_u64(), Some(until));
    let file = blueprint::StrategyFile::load(&ckdir.join("strategy.bps")).unwrap();
    assert_eq!(file.header.iterations, until);
    std::fs::remove_dir_all(&dir).unwrap();
}

/// The cloud trainer's strategy files at fixed stages: one file and one `stages.jsonl` line
/// per stage, the change measured from the second stage on, through a SIGTERM and a resume;
/// `strategy.bps` at the end; and `export` from the last checkpoint gives the same strategy.
#[test]
#[ignore = "needs built tables: set BLUEPRINT_TABLES to their directory"]
fn the_cloud_trainer_writes_strategies_at_stages() {
    use std::io::{BufRead, BufReader};
    use std::process::{Command, Stdio};

    let Some(tables) = std::env::var_os("BLUEPRINT_TABLES") else {
        eprintln!("BLUEPRINT_TABLES is not set: nothing to check");
        return;
    };
    let dir = std::env::temp_dir().join(format!("blueprint-stages-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let spec = Spec {
        stack_bb: 10,
        menu: "minimal".into(),
        abstraction: PathBuf::from(tables),
        training: Training {
            threads: 2,
            linear: Some([100_000, 1_000_000]),
            pruning: Some(blueprint::PruneSettings {
                warmup: 1_000_000,
                threshold: -1_000.0,
                probability: 0.95,
            }),
            ..Training::default()
        },
    };
    let until = 4_000_000u64;
    let stages = [500_000u64, 1_000_000, 2_000_000, 4_000_000];
    let config = dir.join("config.json");
    std::fs::write(
        &config,
        serde_json::json!({"spec": spec, "until": until, "every_minutes": 0.005,
                           "strategies": {"first": 500_000, "factor": 2}})
        .to_string(),
    )
    .unwrap();
    let ckdir = dir.join("ck");
    let trainer = |resume: bool| {
        let mut c = Command::new(env!("CARGO_BIN_EXE_blueprint"));
        c.arg("--config")
            .arg(&config)
            .arg("--checkpoint-dir")
            .arg(&ckdir);
        if resume {
            c.arg("--resume");
        }
        c.stdout(Stdio::piped());
        c
    };

    // Train past the first stage, then SIGTERM.
    let mut child = trainer(false).spawn().unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    let first: serde_json::Value = serde_json::from_str(&lines.next().unwrap().unwrap()).unwrap();
    assert_eq!(first["event"], "started");
    assert_eq!(first["stages"], serde_json::json!(stages));
    loop {
        let v: serde_json::Value = serde_json::from_str(&lines.next().unwrap().unwrap()).unwrap();
        if v["event"] == "stage" {
            assert_eq!(v["iterations"].as_u64(), Some(stages[0]));
            assert!(v["change"].is_null(), "nothing to compare the first stage with");
            break;
        }
    }
    let killed = Command::new("kill")
        .args(["-TERM", &child.id().to_string()])
        .status()
        .unwrap();
    assert!(killed.success());
    for line in lines {
        line.unwrap();
    }
    assert_eq!(child.wait().unwrap().code(), Some(75));

    // Resumed to the end.
    let out = trainer(true).output().unwrap();
    assert!(out.status.success());
    let text = String::from_utf8(out.stdout).unwrap();
    let done: serde_json::Value = serde_json::from_str(text.lines().last().unwrap()).unwrap();
    assert_eq!(done["event"], "done");

    // One file and one line per stage (the last one is the end), each change measured
    // against the stage before.
    let log = std::fs::read_to_string(ckdir.join("stages.jsonl")).unwrap();
    let lines: Vec<serde_json::Value> = log
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    let at: Vec<u64> = lines.iter().map(|v| v["iterations"].as_u64().unwrap()).collect();
    assert_eq!(at, stages);
    for (k, v) in lines.iter().enumerate() {
        let file = blueprint::StrategyFile::load(&ckdir.join(format!("strategy-{}.bps", stages[k])))
            .unwrap();
        assert_eq!(file.header.iterations, stages[k]);
        let regrets = &v["regrets"]["streets"];
        assert!(regrets["preflop"]["slots"].as_u64().unwrap() > 0, "{v}");
        assert!(v["regrets"]["threshold"].as_f64() == Some(-1_000.0), "{v}");
        if k == 0 {
            continue;
        }
        let change = v["change"].as_f64().unwrap();
        assert!(change > 0.0 && change < 1.0, "{v}");
        assert_eq!(v["change_from"], format!("strategy-{}.bps", stages[k - 1]));
    }
    // Pruning was on after its warm-up.
    assert!(lines[3]["pruning"]["pruned_traversals"].as_u64().unwrap() > 0);
    let last = blueprint::StrategyFile::load(&ckdir.join("strategy.bps")).unwrap();
    assert_eq!(last.header.iterations, until);

    // export: the same strategy from the checkpoint, off the run.
    let exported = dir.join("exported.bps");
    let out = Command::new(env!("CARGO_BIN_EXE_blueprint"))
        .arg("export")
        .arg("--config")
        .arg(&config)
        .arg("--checkpoint")
        .arg(Run::checkpoint_path(&ckdir))
        .arg("--out")
        .arg(&exported)
        .output()
        .unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let again = blueprint::StrategyFile::load(&exported).unwrap();
    assert_eq!(again.probs, last.probs);
    assert_eq!(again.header.iterations, until);
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A small gate plan: stages double until the stop rule holds, every result is logged, and
/// a plan started again reads its results back instead of redoing them.
#[test]
#[ignore = "needs built tables: set BLUEPRINT_TABLES to their directory"]
fn a_gate_plan_trains_in_stages_measures_and_resumes() {
    use blueprint::gate::{run_plan, LbrPlan, Plan, PlannedRun, StopRule};

    let Some(tables) = std::env::var_os("BLUEPRINT_TABLES") else {
        eprintln!("BLUEPRINT_TABLES is not set: nothing to check");
        return;
    };
    let dir = std::env::temp_dir().join(format!("blueprint-gate-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let spec = Spec {
        stack_bb: 10,
        menu: "minimal".into(),
        abstraction: PathBuf::from(tables),
        training: Training {
            threads: 2,
            ..Training::default()
        },
    };
    let lbr = |seed| LbrPlan {
        hands: 400,
        seed,
        settings: vec!["fc34".into(), "fcpa34".into()],
    };
    let mut plan = Plan {
        dir: dir.clone(),
        first: 50_000,
        max: 400_000,
        save_every_minutes: None,
        stage_lbr: lbr(5),
        final_lbr: lbr(6),
        // Never met: every stage up to `max` is trained.
        stop: StopRule {
            relative: -1e9,
            sigmas: -1e9,
            max_change: Some(0.0),
        },
        runs: vec![PlannedRun {
            name: "a".into(),
            spec,
        }],
        final_readings: vec!["check-or-call".into()],
    };
    run_plan(&plan).unwrap();
    let run = dir.join("a");
    let lines = |name: &str| -> Vec<serde_json::Value> {
        std::fs::read_to_string(run.join(name))
            .unwrap()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    };
    let stages: Vec<u64> = lines("stages.jsonl")
        .iter()
        .map(|v| v["stage"].as_u64().unwrap())
        .collect();
    assert_eq!(stages, [50_000, 100_000, 200_000, 400_000]);
    assert!(lines("stages.jsonl")[1]["change"].as_f64().unwrap() > 0.0);
    assert_eq!(lines("lbr.jsonl").len(), 8);
    let lbr_line = &lines("lbr.jsonl")[0];
    assert!(
        lbr_line["extra"]["decisions"].as_u64().unwrap() > 0,
        "{lbr_line}"
    );
    let progress = lines("progress.jsonl");
    assert_eq!(progress.len(), 3);
    assert!(progress.iter().all(|p| p["converged"] == false));
    // Both settings with the default reading, then with small bets read as checks or calls.
    assert_eq!(lines("final.jsonl").len(), 4);
    assert_eq!(
        lines("final.jsonl")[2]["extra"]["small_bets"],
        "check-or-call"
    );
    let done: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(run.join("done.json")).unwrap()).unwrap();
    assert_eq!(done["stage"], 400_000);
    assert_eq!(done["reason"], "reached the largest stage");

    // Started again, nothing is redone; with the done marker gone, the stages and LBR
    // results are read back and only the decision is made again.
    run_plan(&plan).unwrap();
    assert_eq!(lines("stages.jsonl").len(), 4);
    std::fs::remove_file(run.join("done.json")).unwrap();
    plan.stop = StopRule {
        relative: 0.0,
        sigmas: 1e9,
        max_change: None,
    };
    run_plan(&plan).unwrap();
    assert_eq!(lines("stages.jsonl").len(), 4);
    assert_eq!(lines("lbr.jsonl").len(), 8);
    let done: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(run.join("done.json")).unwrap()).unwrap();
    assert_eq!(
        done["stage"], 100_000,
        "the looser rule stops after the first doubling"
    );
    assert_eq!(done["reason"], "converged");
    // The final measurement is of that stage's strategy, not read back from the first run.
    let finals = lines("final.jsonl");
    assert_eq!(finals.len(), 8);
    assert_eq!(finals[5]["extra"]["stage"], 100_000);
    assert_ne!(finals[5]["bb_per_100"], finals[1]["bb_per_100"]);
    std::fs::remove_dir_all(&dir).unwrap();
}
