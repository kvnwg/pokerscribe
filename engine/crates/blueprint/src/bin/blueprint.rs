//! `blueprint`: train a heads-up blueprint, save it, measure it with LBR.
//!
//! ```text
//! blueprint train --spec FILE --dir RUN --until N [--every-minutes M] [--threads T]
//! blueprint lbr --strategy FILE [--tables DIR] [--hands N] [--seed S] [--settings LIST]
//!               [--small-bets smallest|check-or-call]
//! blueprint reference --stack BB [--hands N] [--seed S] [--settings LIST]
//! blueprint bench --spec FILE [--seconds S] [--warmup S] [--threads 1,2,4]
//! blueprint size --stack BB --menu NAME --buckets B
//! blueprint compare --a DEALS --b DEALS
//! blueprint gate --plan FILE
//! blueprint info FILE
//! blueprint --config FILE --checkpoint-dir DIR [--resume] [--threads T]
//! ```
//!
//! `lbr` and `reference` take `--deals DIR` to keep every deal's result there (one file per
//! strategy and setting), for `compare`: the difference between two matches on the same
//! deals with its paired standard error. `gate` runs a whole plan (`blueprint::gate`).
//!
//! The last form is the trainer contract of `tools/cloud` (its README, "The trainer"), for
//! a long run on a rented machine. The config file is JSON: `{"spec": {...}, "until": N,
//! "every_minutes": M}` (a [`Spec`], the iterations to reach, and how often to save, 10
//! minutes if left out). It trains in the checkpoint directory as `train` does, saves
//! `checkpoint.ckpt` about every M minutes and prints a progress line after each save. On
//! SIGTERM it saves and exits with 75; when it reaches N it writes `strategy.bps` there
//! and exits with 0.
//!
//! Every command prints one JSON object per result on standard output.

use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::time::Instant;

use abstract_game::GameConfig;
use blueprint::{
    build_game, gate, lbr_match, menu, peak_resident_bytes, Blueprint, Buckets, Deals, Layout, Run,
    SmallBets, Spec, StrategyFile,
};
use cfr::{signal, Mccfr, Solver};
use lbr::{AlwaysCall, LbrConfig, MatchConfig, Strategy, UniformRandom};
use serde_json::json;

struct Args {
    map: HashMap<String, String>,
}

impl Args {
    fn parse(items: &[String]) -> Result<Args, String> {
        let mut map = HashMap::new();
        let mut it = items.iter();
        while let Some(key) = it.next() {
            let Some(name) = key.strip_prefix("--") else {
                return Err(format!("expected an option, got {key:?}"));
            };
            let value = it.next().ok_or_else(|| format!("--{name} needs a value"))?;
            map.insert(name.to_string(), value.clone());
        }
        Ok(Args { map })
    }

    fn get(&self, name: &str) -> Option<&str> {
        self.map.get(name).map(|s| s.as_str())
    }

    fn need(&self, name: &str) -> Result<&str, String> {
        self.get(name)
            .ok_or_else(|| format!("--{name} is required"))
    }

    fn num<T: std::str::FromStr>(&self, name: &str, default: T) -> Result<T, String> {
        match self.get(name) {
            None => Ok(default),
            Some(v) => v
                .replace('_', "")
                .parse()
                .map_err(|_| format!("--{name}: {v:?} is not a number")),
        }
    }
}

fn lbr_settings(list: &str) -> Result<Vec<(&'static str, &'static str, LbrConfig)>, String> {
    let names: Vec<&str> = match list {
        "paper" => vec!["fc14", "fc34", "fcpa34", "b56_14", "b56_34"],
        other => other.split(',').collect(),
    };
    names
        .iter()
        .map(|&n| {
            let (long, config) =
                gate::lbr_setting(n).ok_or_else(|| format!("unknown LBR setting {n:?}"))?;
            let short: &'static str = match n {
                "fcpa34" => "fcpa34",
                "fcpa14" => "fcpa14",
                "fc34" => "fc34",
                "fc14" => "fc14",
                "b56_34" => "b56_34",
                _ => "b56_14",
            };
            Ok((short, long, config))
        })
        .collect()
}

fn table(stack_bb: u32, hands: u64, seed: u64) -> MatchConfig {
    MatchConfig {
        stack: stack_bb * 100,
        ..MatchConfig::acpc(hands, seed)
    }
}

fn append(path: Option<&str>, line: &serde_json::Value) -> Result<(), String> {
    println!("{line}");
    if let Some(p) = path {
        let mut f = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(p)
            .map_err(|e| e.to_string())?;
        writeln!(f, "{line}").map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn train(a: &Args) -> Result<(), String> {
    let mut spec =
        Spec::from_json(&fs::read_to_string(a.need("spec")?).map_err(|e| format!("--spec: {e}"))?)?;
    if let Some(t) = a.get("threads") {
        spec.training.threads = t.parse().map_err(|_| "--threads: a number")?;
    }
    let dir = PathBuf::from(a.need("dir")?);
    let until: u64 = a.num("until", 0)?;
    let every = a.get("every-minutes").map(|m| m.parse::<f64>()).transpose();
    let every = every.map_err(|_| "--every-minutes: a number")?;
    signal::watch_sigterm().map_err(|e| e.to_string())?;
    let opened = Instant::now();
    let mut run = Run::open(spec, &dir).map_err(|e| e.to_string())?;
    let open_seconds = opened.elapsed().as_secs_f64();
    let session = run.train(until, every).map_err(|e| e.to_string())?;
    let exported = Instant::now();
    let export = run.export();
    let layout = Layout::of(run.solver.game());
    let name = format!("strategy-{}.bps", session.to);
    let path = dir.join(&name);
    let bytes = export.file.save(&path).map_err(|e| e.to_string())?;
    // How far the strategy moved since the last export of this run.
    let latest = dir.join("latest.txt");
    let change = match fs::read_to_string(&latest) {
        Ok(prev) if prev.trim() != name => {
            let before = StrategyFile::load(&dir.join(prev.trim())).map_err(|e| e.to_string())?;
            Some(export.file.change_from(&before, &layout, &export.weights))
        }
        _ => None,
    };
    fs::write(&latest, &name).map_err(|e| e.to_string())?;
    let line = json!({
        "command": "train",
        "dir": dir,
        "session": session,
        "open_seconds": open_seconds,
        "export_seconds": exported.elapsed().as_secs_f64(),
        "strategy": path,
        "strategy_bytes": bytes,
        "info_sets": export.file.header.info_sets,
        "visited": export.file.header.visited,
        "from_regrets": export.from_regrets,
        "train_seconds": export.file.header.train_seconds,
        "change": change,
        "peak_resident_bytes": peak_resident_bytes(),
    });
    append(Some(&dir.join("stages.jsonl").to_string_lossy()), &line)
}

fn measure(
    strategy: &dyn Strategy,
    who: &str,
    stack_bb: u32,
    a: &Args,
    extra: impl Fn() -> serde_json::Value,
    reset: impl Fn(),
) -> Result<(), String> {
    let hands: u64 = a.num("hands", 100_000)?;
    let seed: u64 = a.num("seed", 1)?;
    for (short, name, config) in lbr_settings(a.get("settings").unwrap_or("fcpa34"))? {
        let config = match a.get("sampled-preflop") {
            Some(b) => config.with_sampled_preflop(b.parse().map_err(|_| "--sampled-preflop")?),
            None => config,
        };
        reset();
        let start = Instant::now();
        let deals = lbr_match(strategy, &config, &table(stack_bb, hands, seed));
        let seconds = start.elapsed().as_secs_f64();
        let r = deals.result();
        let saved = match a.get("deals") {
            Some(dir) => {
                fs::create_dir_all(dir).map_err(|e| e.to_string())?;
                let file: String = who
                    .chars()
                    .map(|c| {
                        if c.is_ascii_alphanumeric() || c == '-' {
                            c
                        } else {
                            '_'
                        }
                    })
                    .collect();
                let path = Path::new(dir).join(format!("{file}.{short}.s{seed}.deals"));
                deals.save(&path).map_err(|e| e.to_string())?;
                Some(path)
            }
            None => None,
        };
        let line = json!({
            "command": "lbr",
            "strategy": who,
            "setting": name,
            "stack_bb": stack_bb,
            "hands": r.hands,
            "seed": seed,
            "bb_per_100": r.bb_per_100,
            "std_err": r.std_err,
            "button_bb_per_100": r.button_bb_per_100,
            "big_blind_bb_per_100": r.big_blind_bb_per_100,
            "seconds": seconds,
            "hands_per_second": r.hands as f64 / seconds,
            "deals_file": saved,
            "extra": extra(),
        });
        append(a.get("out"), &line)?;
    }
    Ok(())
}

fn lbr_command(a: &Args) -> Result<(), String> {
    let path = PathBuf::from(a.need("strategy")?);
    let tables = a.get("tables").map(PathBuf::from);
    let small_bets = match a.get("small-bets") {
        None => SmallBets::default(),
        Some(name) => SmallBets::parse(name)
            .ok_or_else(|| format!("--small-bets: smallest or check-or-call, not {name:?}"))?,
    };
    let blueprint = Blueprint::load(&path, tables.as_deref())
        .map_err(|e| e.to_string())?
        .with_small_bets(small_bets);
    let stack_bb = blueprint.game().config().stack / blueprint.game().config().big_blind;
    let header = StrategyFile::load(&path).map_err(|e| e.to_string())?.header;
    let label = a
        .get("label")
        .unwrap_or(path.to_str().unwrap_or("strategy"));
    measure(
        &blueprint,
        label,
        stack_bb,
        a,
        || {
            json!({
                "iterations": header.iterations,
                "train_seconds": header.train_seconds,
                "decisions": blueprint.decisions(),
                "off_tree_share": blueprint.off_tree_share(),
                "small_bets": small_bets.name(),
            })
        },
        || blueprint.reset_counters(),
    )
}

fn reference(a: &Args) -> Result<(), String> {
    let stack_bb: u32 = a.num("stack", 20)?;
    let strategies: [(&str, &dyn Strategy); 3] = [
        ("always call", &AlwaysCall),
        ("random action", &UniformRandom::Actions),
        ("random kind of action", &UniformRandom::Kinds),
    ];
    for (name, s) in strategies {
        measure(s, name, stack_bb, a, || json!({}), || {})?;
    }
    Ok(())
}

fn bench(a: &Args) -> Result<(), String> {
    let spec =
        Spec::from_json(&fs::read_to_string(a.need("spec")?).map_err(|e| format!("--spec: {e}"))?)?;
    let seconds: f64 = a.num("seconds", 30.0)?;
    let warmup: f64 = a.num("warmup", 10.0)?;
    let buckets = Arc::new(Buckets::load(&spec.abstraction).map_err(|e| e.to_string())?);
    let threads: Vec<usize> = a
        .get("threads")
        .unwrap_or("1,2,4")
        .split(',')
        .map(|t| t.parse().map_err(|_| format!("--threads: {t:?}")))
        .collect::<Result<_, _>>()?;
    for t in threads {
        let game = build_game(&spec, buckets.clone()).map_err(|e| e.to_string())?;
        let mut cfg = spec.training.mccfr_config();
        cfg.threads = t;
        let mut solver = Mccfr::new(game, cfg);
        // Warm up: the first iterations mostly add information sets.
        let start = Instant::now();
        let mut chunk = 1_000u64;
        while start.elapsed().as_secs_f64() < warmup {
            solver.run(chunk);
            chunk = (chunk * 2).min(200_000);
        }
        let (it0, nodes0) = (solver.iterations(), solver.nodes_touched());
        let start = Instant::now();
        while start.elapsed().as_secs_f64() < seconds {
            solver.run(chunk);
        }
        let s = start.elapsed().as_secs_f64();
        let it = (solver.iterations() - it0) as f64;
        let memory = solver.memory();
        let line = json!({
            "command": "bench",
            "spec": spec,
            "threads": t,
            "iterations": it,
            "seconds": s,
            "iterations_per_second": it / s,
            "iterations_per_second_per_thread": it / s / t as f64,
            "nodes_per_second": (solver.nodes_touched() - nodes0) as f64 / s,
            "warmup_iterations": it0,
            "info_sets": memory.info_sets,
            "bytes_per_info_set": memory.bytes_per_info_set(),
        });
        append(a.get("out"), &line)?;
    }
    Ok(())
}

fn size(a: &Args) -> Result<(), String> {
    let stack: u32 = a.num("stack", 200)?;
    let name = a.need("menu")?;
    let menus = menu(name).ok_or_else(|| format!("unknown menu {name:?}"))?;
    let b: u64 = a.num("buckets", 200)?;
    let size = GameConfig::new(stack, menus)
        .tree_size()
        .map_err(|e| e.to_string())?;
    let buckets = [169, b, b, b];
    let info_sets = size.info_sets(buckets);
    let slots = size.regrets(buckets);
    let line = json!({
        "command": "size",
        "stack_bb": stack,
        "menu": name,
        "buckets": buckets,
        "decision_points": size.decisions.map(|x| x as f64),
        "actions": size.actions.map(|x| x as f64),
        "info_sets": info_sets as f64,
        "info_sets_by_street": (0..4).map(|s| (size.decisions[s] * buckets[s] as u128) as f64).collect::<Vec<_>>(),
        "slots": slots as f64,
        "slots_per_info_set": slots as f64 / info_sets as f64,
    });
    append(a.get("out"), &line)
}

fn gate_command(a: &Args) -> Result<(), String> {
    let text = fs::read_to_string(a.need("plan")?).map_err(|e| format!("--plan: {e}"))?;
    let plan: gate::Plan = serde_json::from_str(&text).map_err(|e| format!("--plan: {e}"))?;
    signal::watch_sigterm().map_err(|e| e.to_string())?;
    gate::run_plan(&plan).map_err(|e| e.to_string())
}

fn compare(a: &Args) -> Result<(), String> {
    let x = Deals::load(Path::new(a.need("a")?)).map_err(|e| e.to_string())?;
    let y = Deals::load(Path::new(a.need("b")?)).map_err(|e| e.to_string())?;
    let (d, se) = x.minus(&y)?;
    let line = json!({
        "command": "compare",
        "a": a.need("a")?,
        "b": a.need("b")?,
        "a_bb_per_100": x.result().bb_per_100,
        "b_bb_per_100": y.result().bb_per_100,
        "difference": d,
        "std_err": se,
        "z": d / se,
    });
    append(a.get("out"), &line)
}

fn info(path: &Path) -> Result<(), String> {
    let file = StrategyFile::load(path).map_err(|e| e.to_string())?;
    println!(
        "{}",
        serde_json::to_string_pretty(&file.header).expect("valid JSON")
    );
    Ok(())
}

/// The `--config` file of the cloud trainer.
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct CloudConfig {
    spec: Spec,
    until: u64,
    #[serde(default = "ten_minutes")]
    every_minutes: f64,
}

fn ten_minutes() -> f64 {
    10.0
}

/// Exit code after a stop asked for by SIGTERM: the state is saved, start again with
/// `--resume` (EX_TEMPFAIL, as `tools/cloud` suggests).
const STOPPED: u8 = 75;

/// The `tools/cloud` trainer: see the module documentation.
fn cloud(items: &[String]) -> Result<ExitCode, String> {
    let resume = items.iter().any(|s| s == "--resume");
    let rest: Vec<String> = items.iter().filter(|s| *s != "--resume").cloned().collect();
    let a = Args::parse(&rest)?;
    for key in a.map.keys() {
        if !["config", "checkpoint-dir", "threads"].contains(&key.as_str()) {
            return Err(format!("the trainer takes no --{key}"));
        }
    }
    let text = fs::read_to_string(a.need("config")?).map_err(|e| format!("--config: {e}"))?;
    let mut config: CloudConfig =
        serde_json::from_str(&text).map_err(|e| format!("--config: {e}"))?;
    if !(config.every_minutes.is_finite() && config.every_minutes > 0.0) {
        return Err("--config: every_minutes must be more than 0".into());
    }
    if let Some(t) = a.get("threads") {
        config.spec.training.threads = t.parse().map_err(|_| "--threads: a number")?;
    }
    let dir = PathBuf::from(a.need("checkpoint-dir")?);
    if resume && !Run::checkpoint_path(&dir).exists() {
        return Err(format!(
            "--resume, but {} is not there",
            Run::checkpoint_path(&dir).display()
        ));
    }
    signal::watch_sigterm().map_err(|e| e.to_string())?;
    let until = config.until;
    let mut run = Run::open(config.spec, &dir).map_err(|e| e.to_string())?;
    let started_at = run.solver.iterations();
    append(
        None,
        &json!({
            "event": if started_at > 0 { "resumed" } else { "started" },
            "iterations": started_at,
            "target_iterations": until,
            "threads": run.spec.training.threads,
        }),
    )?;
    // Each session trains for about `every_minutes` and ends with a save (cfr saves when a
    // train call returns), then reports. The first one is short, to measure the speed.
    let mut chunk = 1_000_000u64;
    while run.solver.iterations() < until {
        let at = run.solver.iterations();
        let s = run
            .train(until.min(at.saturating_add(chunk)), None)
            .map_err(|e| e.to_string())?;
        append(
            None,
            &json!({
                "iterations": s.to,
                "target_iterations": until,
                "iterations_per_second": s.iterations_per_second,
                "info_sets": s.info_sets,
                "table_bytes": s.table_bytes,
                "resident_bytes": s.resident_bytes,
                "save_seconds": s.longest_save_seconds,
                "stopped": s.stopped,
            }),
        )?;
        if s.stopped {
            append(
                None,
                &json!({"event": "saved on SIGTERM", "iterations": s.to, "target_iterations": until}),
            )?;
            return Ok(ExitCode::from(STOPPED));
        }
        chunk = ((s.iterations_per_second * config.every_minutes * 60.0) as u64).max(1_000);
    }
    let export = run.export();
    let path = dir.join("strategy.bps");
    let bytes = export.file.save(&path).map_err(|e| e.to_string())?;
    append(
        None,
        &json!({
            "event": "done",
            "iterations": run.solver.iterations(),
            "target_iterations": until,
            "train_seconds": run.train_seconds(),
            "strategy": path,
            "strategy_bytes": bytes,
            "peak_resident_bytes": peak_resident_bytes(),
        }),
    )?;
    Ok(ExitCode::SUCCESS)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args
        .iter()
        .any(|s| s == "--config" || s == "--checkpoint-dir")
    {
        return match cloud(&args) {
            Ok(code) => code,
            Err(e) => {
                eprintln!("blueprint: {e}");
                ExitCode::FAILURE
            }
        };
    }
    let result = match args.first().map(|s| s.as_str()) {
        Some("info") if args.len() == 2 => info(Path::new(&args[1])),
        Some(cmd) => Args::parse(&args[1..]).and_then(|a| match cmd {
            "train" => train(&a),
            "lbr" => lbr_command(&a),
            "reference" => reference(&a),
            "bench" => bench(&a),
            "size" => size(&a),
            "compare" => compare(&a),
            "gate" => gate_command(&a),
            _ => Err(format!("unknown command {cmd:?}")),
        }),
        None => Err("a command: train, lbr, reference, bench, size, compare, gate or info".into()),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("blueprint: {e}");
            ExitCode::FAILURE
        }
    }
}
