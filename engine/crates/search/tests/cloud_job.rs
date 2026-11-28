//! The leaf table job through the `search` binary, on a blueprint trained with built bucket
//! tables: the `tools/cloud` trainer contract (`search --config ... --checkpoint-dir ...
//! [--resume]`) and `search leaf`. Ignored: set `BLUEPRINT_TABLES` to built tables (the
//! nightly workflow, `rust-slow.yml`, sets it to k10), or it does nothing and passes.
//!
//! ```text
//! BLUEPRINT_TABLES=~/abstraction/k10 cargo test --release -p search --test cloud_job -- --ignored
//! ```

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;

use blueprint::{Blueprint, Buckets, Run, Spec, Training};
use search::leaf::{build, BuildConfig, LeafTables};

/// A small blueprint (10 big blinds, the minimal menu) trained with `tables`, saved in `dir`.
/// The file names a folder for its tables that is gone afterwards (a link to `tables`), as a
/// file trained on another machine does, so every load below needs `--tables`.
fn small_blueprint(tables: &Path, dir: &Path) -> PathBuf {
    let named = dir.join("tables-on-another-machine");
    std::os::unix::fs::symlink(tables, &named).unwrap();
    let buckets = Arc::new(Buckets::load(&named).unwrap());
    let spec = Spec {
        stack_bb: 10,
        menu: "minimal".into(),
        abstraction: named.clone(),
        training: Training {
            threads: 2,
            ..Training::default()
        },
    };
    let mut run = Run::open_with(spec, &dir.join("run"), buckets).unwrap();
    run.train(200_000, None).unwrap();
    let path = dir.join("strategy.bps");
    run.export().file.save(&path).unwrap();
    std::fs::remove_file(&named).unwrap();
    assert!(
        Blueprint::load(&path, None).is_err(),
        "the folder the file names is gone"
    );
    path
}

#[test]
#[ignore = "needs built tables: set BLUEPRINT_TABLES to their directory"]
fn the_leaf_job_keeps_the_cloud_trainer_contract() {
    let Some(tables) = std::env::var_os("BLUEPRINT_TABLES") else {
        eprintln!("BLUEPRINT_TABLES is not set: nothing to check");
        return;
    };
    let tables = PathBuf::from(tables);
    let dir = std::env::temp_dir().join(format!("search-cloud-job-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let strategy = small_blueprint(&tables, &dir);
    let deals = 300_000u64;
    let config = dir.join("leaf.json");
    std::fs::write(
        &config,
        serde_json::json!({"strategy": strategy, "tables": tables, "deals": deals, "seed": 5,
                           "part_nodes": 1, "out": "small.leaf"})
        .to_string(),
    )
    .unwrap();
    let ckdir = dir.join("ck");
    let job = |resume: bool| {
        let mut c = Command::new(env!("CARGO_BIN_EXE_search"));
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
    let line = |s: &str| -> serde_json::Value { serde_json::from_str(s).expect("JSON lines") };

    // --resume with nothing to resume is an error, and so is an option it doesn't take.
    assert!(!job(true).status().unwrap().success());
    let bad = Command::new(env!("CARGO_BIN_EXE_search"))
        .args(["--config", "x", "--checkpoint-dir", "y", "--hands", "3"])
        .output()
        .unwrap();
    assert!(!bad.status.success());

    // Started; SIGTERM once a part is done.
    let mut child = job(false).spawn().unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    let first = line(&lines.next().unwrap().unwrap());
    assert_eq!(first["event"], "started");
    let parts = first["parts"].as_u64().unwrap();
    assert!(parts >= 3, "{parts} parts: too few to stop in the middle");
    let target = parts * deals;
    assert_eq!(first["target_iterations"].as_u64(), Some(target));
    loop {
        let v = line(&lines.next().unwrap().unwrap());
        if v["parts_done"].as_u64().unwrap_or(0) >= 1 {
            break;
        }
    }
    assert!(ckdir.join("leaf.ckpt").exists());
    assert!(Command::new("kill")
        .args(["-TERM", &child.id().to_string()])
        .status()
        .unwrap()
        .success());
    let mut last = serde_json::Value::Null;
    for l in lines {
        last = line(&l.unwrap());
    }
    assert_eq!(
        child.wait().unwrap().code(),
        Some(75),
        "a stop exits with 75"
    );
    assert_eq!(last["event"], "saved on SIGTERM");
    let saved = last["parts_done"].as_u64().unwrap();
    assert!(saved >= 1 && saved < parts, "{saved} of {parts} parts");

    // Resumed: it goes on from the parts done and finishes.
    let out = job(true).output().unwrap();
    assert!(out.status.success());
    let text = String::from_utf8(out.stdout).unwrap();
    let resumed = line(text.lines().next().unwrap());
    assert_eq!(resumed["event"], "resumed");
    assert_eq!(resumed["parts_done"].as_u64(), Some(saved));
    assert_eq!(resumed["iterations"].as_u64(), Some(saved * deals));
    let done = line(text.lines().last().unwrap());
    assert_eq!(done["event"], "done");
    assert_eq!(done["iterations"].as_u64(), Some(target));

    // The tables are a build in one piece's, bit for bit.
    let bp = Blueprint::load(&strategy, Some(&tables)).unwrap();
    let one = build(
        &bp,
        &strategy,
        &BuildConfig {
            deals,
            seed: 5,
            ..Default::default()
        },
        |_| {},
    )
    .unwrap();
    let job_tables = LeafTables::load(&ckdir.join("small.leaf")).unwrap();
    assert!(job_tables.values() == one.values());
    assert_eq!(job_tables.header.strategy_hash, one.header.strategy_hash);

    // `search leaf` builds the same next to the strategy file, and deletes its parts;
    // without --tables it can't find them.
    let missing = Command::new(env!("CARGO_BIN_EXE_search"))
        .arg("leaf")
        .arg("--strategy")
        .arg(&strategy)
        .args(["--deals", "1000"])
        .output()
        .unwrap();
    assert!(!missing.status.success());
    let local = Command::new(env!("CARGO_BIN_EXE_search"))
        .arg("leaf")
        .arg("--strategy")
        .arg(&strategy)
        .arg("--tables")
        .arg(&tables)
        .args([
            "--deals",
            &deals.to_string(),
            "--seed",
            "5",
            "--threads",
            "2",
        ])
        .output()
        .unwrap();
    assert!(
        local.status.success(),
        "{}",
        String::from_utf8_lossy(&local.stderr)
    );
    let leaf = search::leaf_path(&strategy);
    assert!(LeafTables::load(&leaf).unwrap().values() == one.values());
    let mut work = strategy.as_os_str().to_owned();
    work.push(".leaf-parts");
    assert!(!Path::new(&work).exists(), "the parts are deleted");
    // The search agent plays with the tables given and the leaf tables next to the file.
    let agent =
        search::SearchAgent::load_with(&strategy, Some(&tables), search::Settings::default())
            .unwrap();
    assert!(agent.leaf.is_some());
    let bench = Command::new(env!("CARGO_BIN_EXE_search"))
        .arg("bench")
        .arg("--strategy")
        .arg(&strategy)
        .arg("--tables")
        .arg(&tables)
        .args(["--hands", "4", "--seed", "1", "--threads", "2"])
        .output()
        .unwrap();
    assert!(
        bench.status.success(),
        "{}",
        String::from_utf8_lossy(&bench.stderr)
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

/// The plan job (`search::plan_job`) through the binary: a config with a gate is a plan;
/// SIGTERM in the middle of the gate match exits 75 at once (the chunk being played is
/// given up), and `--resume` goes on and ends with every step's results and exit 0.
#[test]
#[ignore = "needs built tables: set BLUEPRINT_TABLES to their directory"]
fn the_plan_job_keeps_the_cloud_trainer_contract() {
    let Some(tables) = std::env::var_os("BLUEPRINT_TABLES") else {
        eprintln!("BLUEPRINT_TABLES is not set: nothing to check");
        return;
    };
    let tables = PathBuf::from(tables);
    let dir = std::env::temp_dir().join(format!("search-cloud-plan-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let strategy = small_blueprint(&tables, &dir);
    let agent = |play: &str| {
        serde_json::json!({"leaf_choice": "both", "play": play, "flop_iterations": 40,
                           "turn_iterations": 16, "river_iterations": 60})
    };
    let config = dir.join("plan.json");
    std::fs::write(
        &config,
        serde_json::json!({
            "strategy": strategy, "tables": tables,
            "leaf": {"deals": 20000, "seed": 5, "lanes": 16, "part_nodes": 2},
            "agent": agent("average"),
            "bench": {"hands": 4, "seed": 581, "threads": 2,
                      "bound_ms": {"flop": 600000, "turn": 600000, "river": 600000}},
            "pilot": {"deals": 16, "seed": 501},
            "size": {"edge_bb_per_100": 10, "z": 2.5, "step": 16, "min": 32, "max": 32},
            "gate": {"chunk": 16, "seed": 600, "pass_z": 2.5},
            "variants": [{"name": "final", "agent": agent("final"), "chunks": 1, "seed": 900}],
            "lbr": {"hands": 4, "chunks": 1, "settings": [{"name": "fcpa14", "seed": 560}]},
            "repeat": {"seed": 700}
        })
        .to_string(),
    )
    .unwrap();
    let ckdir = dir.join("ck");
    let job = |resume: bool| {
        let mut c = Command::new(env!("CARGO_BIN_EXE_search"));
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
    let line = |s: &str| -> serde_json::Value { serde_json::from_str(s).expect("JSON lines") };
    // SIGTERM once the gate match is playing.
    let mut child = job(false).spawn().unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    assert_eq!(line(&lines.next().unwrap().unwrap())["event"], "started");
    loop {
        let v = line(&lines.next().unwrap().unwrap());
        if v["step"] == "size" {
            break;
        }
    }
    assert!(ckdir.join("plan.ckpt").exists() && ckdir.join("pilot.json").exists());
    let asked = std::time::Instant::now();
    assert!(Command::new("kill")
        .args(["-TERM", &child.id().to_string()])
        .status()
        .unwrap()
        .success());
    let mut last = serde_json::Value::Null;
    for l in lines {
        last = line(&l.unwrap());
    }
    assert_eq!(child.wait().unwrap().code(), Some(75));
    assert!(asked.elapsed().as_secs_f64() < 5.0, "it stops at once");
    assert_eq!(last["event"], "saved on SIGTERM");
    assert_eq!(last["step"], "gate");
    // Resumed: it ends with every step played.
    let out = job(true).output().unwrap();
    assert!(out.status.success());
    let text = String::from_utf8(out.stdout).unwrap();
    assert_eq!(line(text.lines().next().unwrap())["event"], "resumed");
    assert_eq!(line(text.lines().last().unwrap())["event"], "done");
    for f in [
        "bench.json",
        "pilot.json",
        "size.json",
        "match-01.json",
        "match-02.json",
        "gate.json",
        "variant-final.json",
        "compare-fcpa14-1.json",
        "end.json",
    ] {
        assert!(ckdir.join(f).exists(), "{f}");
    }
    std::fs::remove_dir_all(&dir).unwrap();
}
