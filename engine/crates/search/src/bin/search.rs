//! The search agent's command line: leaf tables, matches, LBR, timing and the range check.
//!
//! ```text
//! search leaf    --strategy F [--deals N] [--seed S] [--lanes 7|16] [--part-nodes K] [--work DIR] [--threads T]
//! search match   --strategy F --deals N --seed S [--threads T] [--against blueprint|search] [--out FILE]
//! search lbr     --strategy F --agent search|blueprint --setting fcpa14|b56_14 --hands N --seed S --out FILE
//! search compare FILE_A FILE_B
//! search bench   --strategy F --hands N --seed S [--threads T] [--out FILE]
//! search ranges  --strategy F --hands N --seed S [--out FILE]
//! search trees   [--stack-bb B] [--menu standard]     (tree sizes, for the 200bb estimate)
//! search scale   --strategy F --hands N --seed S [--spots K] (the same solves on 1, 2, 4 threads)
//! search --config FILE --checkpoint-dir DIR [--resume] [--threads T]
//! ```
//!
//! The commands that play the search agent take its settings: `--flop-target`,
//! `--flop-iterations` (and the same for the turn and river), `--prune`, `--turn-river-menu
//! allin|075|standard`, `--leaf-choice opponent|both` (who picks at the flop's leaves; both
//! needs 16-lane tables) and `--play average|final` (the strategy a solve plays).
//!
//! Every command that loads a strategy file takes `--tables DIR`: the bucket tables, for a
//! file trained on another machine (by default the folder the file names). They must be the
//! tables it was trained with; the file's checksums are checked.
//!
//! `leaf` builds the leaf tables in parts (`search::leaf_job`) in a work folder (default
//! `<strategy file>.leaf-parts`), and when every part is there writes `<strategy file>.leaf`
//! and deletes the folder. Stopped (Ctrl-C), the same command goes on from the parts done.
//! The last form is the same job under the `tools/cloud` trainer contract (its README, "The
//! trainer"): the config is a `search::leaf_job::JobConfig` in JSON, the parts and the
//! table file are written in the checkpoint directory, SIGTERM stops it with exit code 75,
//! and it exits with 0 once the table file is written.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use blueprint::{Blueprint, Deals};
use lbr::{PublicState, Strategy};
use nlhe::{Card, Config, Deal, State, Street};
use search::cards::combo_index;
use search::runs::{self, play_hands, street_name};
use search::solve::LeafChoice;
use search::{leaf_path, SearchAgent, Settings};
use serde_json::json;

fn args() -> (String, HashMap<String, String>, Vec<String>) {
    let mut it = std::env::args().skip(1);
    let cmd = it.next().unwrap_or_default();
    let mut opts = HashMap::new();
    let mut rest = Vec::new();
    let all: Vec<String> = it.collect();
    let mut i = 0;
    while i < all.len() {
        if let Some(k) = all[i].strip_prefix("--") {
            let v = all.get(i + 1).cloned().unwrap_or_default();
            opts.insert(k.to_string(), v);
            i += 2;
        } else {
            rest.push(all[i].clone());
            i += 1;
        }
    }
    (cmd, opts, rest)
}

fn get<T: std::str::FromStr>(opts: &HashMap<String, String>, k: &str, default: T) -> T {
    opts.get(k).and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn need(opts: &HashMap<String, String>, k: &str) -> String {
    opts.get(k)
        .cloned()
        .unwrap_or_else(|| panic!("--{k} is needed"))
}

/// `--tables`, when given.
fn tables(opts: &HashMap<String, String>) -> Option<PathBuf> {
    opts.get("tables").map(PathBuf::from)
}

fn load_blueprint(
    opts: &HashMap<String, String>,
    strategy: &Path,
) -> Blueprint<Arc<blueprint::Buckets>> {
    Blueprint::load(strategy, tables(opts).as_deref()).expect("the blueprint loads")
}

fn load_search(opts: &HashMap<String, String>, strategy: &Path, settings: Settings) -> SearchAgent {
    SearchAgent::load_with(strategy, tables(opts).as_deref(), settings)
        .expect("the search agent loads")
}

/// The table every 20 big blind game here is played at: 2,000 chips, blinds 50 and 100.
fn stack_of(bp: &Blueprint<Arc<blueprint::Buckets>>) -> u32 {
    bp.game().config().stack
}

/// Settings from the command line (each one optional).
fn settings(opts: &HashMap<String, String>) -> Settings {
    let d = Settings::default();
    let mut s = Settings {
        flop_target: get(opts, "flop-target", d.flop_target),
        flop_iterations: get(opts, "flop-iterations", d.flop_iterations),
        turn_target: get(opts, "turn-target", d.turn_target),
        turn_iterations: get(opts, "turn-iterations", d.turn_iterations),
        river_target: get(opts, "river-target", d.river_target),
        river_iterations: get(opts, "river-iterations", d.river_iterations),
        prune: get(opts, "prune", d.prune),
        ..d
    };
    if let Some(m) = opts.get("turn-river-menu") {
        s.turn_river_menu = search::solve::river_menu_named(m).expect("a known river menu");
    }
    if let Some(c) = opts.get("leaf-choice") {
        s.leaf_choice = LeafChoice::named(c).expect("--leaf-choice opponent or both");
    }
    if let Some(p) = opts.get("play") {
        s.play = search::solve::play_named(p).expect("--play average or final");
    }
    s
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    // The tools/cloud trainer has no command word: its first argument is an option.
    if raw.first().is_some_and(|s| s.starts_with("--")) {
        std::process::exit(cloud_job(&raw));
    }
    let (cmd, opts, rest) = args();
    match cmd.as_str() {
        "leaf" => leaf(&opts),
        "match" => head_to_head(&opts),
        "lbr" => lbr(&opts),
        "compare" => compare(&rest),
        "bench" => bench(&opts),
        "ranges" => ranges(&opts),
        "trees" => trees(&opts),
        "scale" => scale(&opts),
        _ => {
            eprintln!("search leaf|match|lbr|compare|bench|ranges (see the source for options)");
            std::process::exit(2);
        }
    }
}

/// Exit code after a stop asked for by a signal: the parts done are saved, start again
/// (with `--resume` under the trainer contract) to go on.
const STOPPED: i32 = 75;

fn say_line(v: serde_json::Value) {
    use std::io::Write;
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{v}");
    let _ = out.flush();
}

fn global_threads(threads: Option<usize>) {
    if let Some(t) = threads {
        rayon::ThreadPoolBuilder::new()
            .num_threads(t)
            .build_global()
            .ok();
    }
}

/// `search leaf`: the leaf tables of a strategy file, in parts in a work folder, then
/// `<file>.leaf`.
fn leaf(opts: &HashMap<String, String>) {
    use search::leaf_job::{self, JobConfig, JobEnd, CHECKPOINT};
    let strategy = PathBuf::from(need(opts, "strategy"));
    global_threads(opts.get("threads").and_then(|t| t.parse().ok()));
    let config = JobConfig {
        strategy: strategy.clone(),
        tables: tables(opts),
        deals: get(opts, "deals", 4_000_000),
        seed: get(opts, "seed", 7),
        part_nodes: get(opts, "part-nodes", leaf_job::PART_NODES),
        lanes: get(opts, "lanes", search::leaf::MODICUM_LANES),
        out: None,
    };
    let work = opts.get("work").map(PathBuf::from).unwrap_or_else(|| {
        let mut w = strategy.as_os_str().to_owned();
        w.push(".leaf-parts");
        w.into()
    });
    let bp = load_blueprint(opts, &strategy);
    cfr::signal::watch_sigterm().ok();
    cfr::signal::watch_sigint().ok();
    let resume = work.join(CHECKPOINT).exists();
    let end = leaf_job::run(
        &bp,
        &config,
        &work,
        resume,
        &cfr::signal::stop_requested,
        &mut |v| eprintln!("{v}"),
    )
    .unwrap_or_else(|e| {
        eprintln!("search leaf: {e}");
        std::process::exit(1)
    });
    match end {
        JobEnd::Stopped => {
            eprintln!(
                "stopped; the parts done are in {}: run the same command again to go on",
                work.display()
            );
            std::process::exit(STOPPED);
        }
        JobEnd::Done(built) => {
            let out = leaf_path(&strategy);
            if std::fs::rename(&built, &out).is_err() {
                std::fs::copy(&built, &out)
                    .expect("the tables are copied next to the strategy file");
            }
            std::fs::remove_dir_all(&work).ok();
            let header =
                search::leaf::LeafTables::read_header(&out).expect("the tables were written");
            println!("{}", serde_json::to_string(&header).unwrap());
            eprintln!("wrote {}", out.display());
        }
    }
}

/// The leaf table job under the `tools/cloud` trainer contract (see the module
/// documentation). Returns the exit code.
fn cloud_job(items: &[String]) -> i32 {
    use search::leaf_job::{self, JobConfig, JobEnd};
    use search::plan_job::{self, PlanConfig, PlanEnd};
    let fail = |e: String| {
        eprintln!("search: {e}");
        1
    };
    let resume = items.iter().any(|s| s == "--resume");
    let mut map = HashMap::new();
    let rest: Vec<&String> = items.iter().filter(|s| *s != "--resume").collect();
    let mut i = 0;
    while i < rest.len() {
        let Some(k) = rest[i].strip_prefix("--") else {
            return fail(format!("unexpected argument {:?}", rest[i]));
        };
        if !["config", "checkpoint-dir", "threads"].contains(&k) {
            return fail(format!("the job takes no --{k}"));
        }
        let Some(v) = rest.get(i + 1) else {
            return fail(format!("--{k} needs a value"));
        };
        map.insert(k.to_string(), v.to_string());
        i += 2;
    }
    let (Some(config), Some(dir)) = (map.get("config"), map.get("checkpoint-dir")) else {
        return fail("--config and --checkpoint-dir are needed".into());
    };
    let threads = match map.get("threads").map(|t| t.parse::<usize>()) {
        Some(Ok(t)) if t > 0 => Some(t),
        Some(_) => return fail("--threads: a number above 0".into()),
        None => None,
    };
    let text = match std::fs::read_to_string(config) {
        Ok(t) => t,
        Err(e) => return fail(format!("--config: {e}")),
    };
    // A plan has a gate; anything else is the leaf table job alone.
    let is_plan = serde_json::from_str::<serde_json::Value>(&text)
        .map(|v| v.get("gate").is_some())
        .unwrap_or(false);
    global_threads(threads);
    if let Err(e) = cfr::signal::watch_sigterm() {
        return fail(e.to_string());
    }
    let dir = Path::new(dir);
    if is_plan {
        let config = match PlanConfig::from_json(&text) {
            Ok(c) => c,
            Err(e) => return fail(format!("--config: {e}")),
        };
        let bp = match Blueprint::load(&config.strategy, config.tables.as_deref()) {
            Ok(bp) => Arc::new(bp),
            Err(e) => return fail(format!("{}: {e}", config.strategy.display())),
        };
        return match plan_job::run(
            bp,
            &config,
            dir,
            resume,
            &cfr::signal::stop_requested,
            &mut say_line,
        ) {
            Ok(PlanEnd::Done(_)) => 0,
            // The run being played is given up: leave at once, before the machine goes.
            Ok(PlanEnd::Stopped) => STOPPED,
            Err(e) => fail(e),
        };
    }
    let config: JobConfig = match serde_json::from_str(&text) {
        Ok(c) => c,
        Err(e) => return fail(format!("--config: {e}")),
    };
    if let Err(e) = config.check() {
        return fail(format!("--config: {e}"));
    }
    let bp = match Blueprint::load(&config.strategy, config.tables.as_deref()) {
        Ok(bp) => bp,
        Err(e) => return fail(format!("{}: {e}", config.strategy.display())),
    };
    match leaf_job::run(
        &bp,
        &config,
        dir,
        resume,
        &cfr::signal::stop_requested,
        &mut say_line,
    ) {
        Ok(JobEnd::Done(_)) => 0,
        Ok(JobEnd::Stopped) => STOPPED,
        Err(e) => fail(e),
    }
}

fn agent_named(
    opts: &HashMap<String, String>,
    name: &str,
    strategy: &Path,
    settings: Settings,
) -> Arc<dyn Strategy + Send + Sync> {
    match name {
        "search" => Arc::new(load_search(opts, strategy, settings)),
        "blueprint" => Arc::new(load_blueprint(opts, strategy)),
        _ => panic!("unknown agent {name}"),
    }
}

fn head_to_head(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let deals: u64 = get(opts, "deals", 1000);
    let seed: u64 = get(opts, "seed", 1);
    let threads: usize = get(opts, "threads", 4);
    let against = opts
        .get("against")
        .cloned()
        .unwrap_or_else(|| "blueprint".into());
    // One blueprint, shared by the search agent and the opponent (a 200bb file is 0.5 GB).
    let bp = Arc::new(load_blueprint(opts, &strategy));
    let stack = stack_of(&bp);
    let searcher = SearchAgent::with_leaf_tables(Arc::clone(&bp), &strategy, settings(opts))
        .expect("the search agent loads");
    let other: Arc<dyn Strategy + Send + Sync> = match against.as_str() {
        "blueprint" => Arc::clone(&bp) as Arc<dyn Strategy + Send + Sync>,
        "search" => Arc::new(
            SearchAgent::with_leaf_tables(Arc::clone(&bp), &strategy, settings(opts))
                .expect("the search agent loads"),
        ),
        _ => panic!("unknown agent {against}"),
    };
    let t0 = Instant::now();
    let report = runs::head_to_head(
        runs::Side {
            name: "search",
            strategy: Arc::new(searcher),
            answers: false,
        },
        runs::Side {
            name: &against,
            strategy: other,
            answers: against == "blueprint",
        },
        stack,
        deals,
        seed,
        threads,
    )
    .expect("the match runs");
    eprintln!("{} s", t0.elapsed().as_secs_f64());
    println!("{}", report.summary());
    if let Some(out) = opts.get("out") {
        report.save(Path::new(out)).expect("the report saves");
    }
}

fn lbr(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let name = need(opts, "agent");
    let setting = need(opts, "setting");
    let hands: u64 = get(opts, "hands", 1000);
    let seed: u64 = get(opts, "seed", 1);
    let bp = Arc::new(load_blueprint(opts, &strategy));
    // The search agent keeps a record of its solves, to count the re-solves LBR's bets cause.
    let searcher = (name == "search").then(|| {
        let mut a = SearchAgent::with_leaf_tables(Arc::clone(&bp), &strategy, settings(opts))
            .expect("the search agent loads");
        a.keep_records = true;
        Arc::new(a)
    });
    let agent: Arc<dyn Strategy + Send + Sync> = match &searcher {
        Some(a) => Arc::clone(a) as Arc<dyn Strategy + Send + Sync>,
        None if name == "blueprint" => Arc::clone(&bp) as Arc<dyn Strategy + Send + Sync>,
        None => agent_named(opts, &name, &strategy, settings(opts)),
    };
    let (deals, summary) = runs::lbr_run(
        &name,
        agent,
        searcher.as_deref(),
        &setting,
        stack_of(&bp),
        hands,
        seed,
    )
    .expect("LBR runs");
    println!("{summary}");
    let out = need(opts, "out");
    deals.save(Path::new(&out)).expect("the deals save");
}

fn compare(rest: &[String]) {
    let a = Deals::load(Path::new(&rest[0])).expect("deals A");
    let b = Deals::load(Path::new(&rest[1])).expect("deals B");
    let mut v = runs::compare(&a, &b).expect("the same deals");
    v["a"] = json!(rest[0]);
    v["b"] = json!(rest[1]);
    println!("{v}");
}

fn bench(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let hands: u64 = get(opts, "hands", 100);
    let seed: u64 = get(opts, "seed", 1);
    let threads: usize = get(opts, "threads", 4);
    rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build_global()
        .ok();
    let settings = Settings {
        turn_threads: threads,
        ..settings(opts)
    };
    let mut agent = load_search(opts, &strategy, settings);
    let report = runs::bench(&mut agent, hands, seed);
    let text = serde_json::to_string_pretty(&report).unwrap();
    println!("{text}");
    if let Some(path) = opts.get("out") {
        std::fs::write(path, text).expect("the report saves");
    }
}

fn ranges(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let hands: u64 = get(opts, "hands", 200);
    let seed: u64 = get(opts, "seed", 1);
    let agent = load_search(opts, &strategy, settings(opts));
    // [street][own, opponent]: (decisions, in the range, in the solve, sum of percentile)
    let mut tally: HashMap<&'static str, [[f64; 4]; 2]> = HashMap::new();
    play_hands(&agent, hands, seed, |state, me, _| {
        let street = state.street();
        if street == Street::Preflop {
            return;
        }
        let public = PublicState::new(state);
        let r = agent.street_ranges(&public, street, me);
        let plan = agent.plan(&public);
        let bb = state.big_blind_seat();
        let t = tally.entry(street_name(street)).or_default();
        for (k, seat) in [me, 1 - me].into_iter().enumerate() {
            let hole = state.hole_cards(seat);
            let c = combo_index(hole[0], hole[1]);
            let w = &r[seat];
            let in_range = w[c] > 0.0;
            let player = if seat == bb { 0 } else { 1 };
            let in_solve = plan
                .as_ref()
                .is_some_and(|p| p.solve.combos[player].binary_search(&c).is_ok());
            // The share of the range's weight on combos lighter than the real one.
            let total: f64 = w.iter().sum();
            let lighter: f64 = w.iter().filter(|&&x| x < w[c]).sum();
            let x = &mut t[k];
            x[0] += 1.0;
            x[1] += in_range as u8 as f64;
            x[2] += in_solve as u8 as f64;
            x[3] += if total > 0.0 { lighter / total } else { 0.0 };
        }
    });
    let mut out = serde_json::Map::new();
    for s in ["flop", "turn", "river"] {
        if let Some(t) = tally.get(s) {
            let one = |x: &[f64; 4]| {
                json!({"decisions": x[0], "in_range": x[1] / x[0], "in_solve": x[2] / x[0],
                       "mean_weight_below": x[3] / x[0]})
            };
            out.insert(s.into(), json!({"own": one(&t[0]), "opponent": one(&t[1])}));
        }
    }
    out.insert("hands".into(), json!(hands));
    out.insert("seed".into(), json!(seed));
    let text = serde_json::to_string_pretty(&out).unwrap();
    println!("{text}");
    if let Some(path) = opts.get("out") {
        std::fs::write(path, text).expect("the report saves");
    }
}

/// Sizes of the trees the search solves, on a few common lines, at a stack depth: the
/// flop's street tree, the turn's subgame tree (every river, the river menu of a turn solve)
/// and the river's subgame tree.
fn trees(opts: &HashMap<String, String>) {
    use nlhe::Action::{Call, Check, RaiseTo};
    use search::street::{to_subgame, Kind, StreetTree};
    let bb: u32 = get(opts, "stack-bb", 20);
    let menus = blueprint::menu(
        &opts
            .get("menu")
            .cloned()
            .unwrap_or_else(|| "standard".into()),
    )
    .expect("a known menu");
    let settings = settings(opts);
    let config = Config::new(&[bb * 100, bb * 100], 50, 100, 0, 0).unwrap();
    let deal = Deal::new(&[[0, 1], [2, 3]], [12, 25, 38, 47, 51]).unwrap();
    let board: Vec<Card> = vec![12, 25, 38, 47, 51];
    let preflops: [(&str, Vec<nlhe::Action>); 3] = [
        ("limped", vec![Call, Check]),
        ("raised 2.5", vec![RaiseTo(250), Call]),
        ("3-bet to 7.5", vec![RaiseTo(250), RaiseTo(750), Call]),
    ];
    let mut out = Vec::new();
    for (name, pre) in preflops {
        let mut s = State::new(&config, deal).unwrap();
        for &a in &pre {
            s.apply(a).unwrap();
        }
        let flop = StreetTree::build(&s, &menus, &[]);
        let decisions = flop.decisions();
        let leaves = flop
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, Kind::End))
            .count();
        // The turn after the flop checks through, and after a bet of three quarters called.
        let mut turns = Vec::new();
        for line in [
            vec![Check, Check],
            vec![Check, RaiseTo(s.pot() * 3 / 4), Call],
        ] {
            let mut t = s.clone();
            let mut ok = true;
            for &a in &line {
                ok &= t.apply(search::street::legalize(&t, a)).is_ok();
            }
            if !ok || t.street() != Street::Turn {
                continue;
            }
            let tree = StreetTree::build(&t, &menus, &[]);
            let rivers: Vec<Option<StreetTree>> = tree
                .nodes
                .iter()
                .map(|n| {
                    matches!(n.kind, Kind::End)
                        .then(|| StreetTree::build(&n.state, &settings.turn_river_menu, &[]))
                })
                .collect();
            let conv = to_subgame(&tree, &rivers, &board[..4]);
            let mut r = t.clone();
            r.apply(Check).unwrap();
            r.apply(Check).unwrap();
            let river = StreetTree::build(&r, &menus, &[]);
            let rconv = to_subgame(&river, &[], &board);
            turns.push(json!({"turn_pot": t.pot(), "turn_street_nodes": tree.nodes.len(),
                              "turn_ends": tree.nodes.iter().filter(|n| matches!(n.kind, Kind::End)).count(),
                              "turn_subgame_nodes": conv.tree.nodes.len(),
                              "river_subgame_nodes": rconv.tree.nodes.len()}));
        }
        out.push(
            json!({"line": name, "flop_pot": s.pot(), "flop_nodes": flop.nodes.len(),
                        "flop_decisions": decisions, "flop_leaves": leaves, "turns": turns}),
        );
    }
    // The whole abstract game's turn starts: one leaf table per start, 7 or 16 lanes of
    // 200 x 200 flop buckets in f32.
    let root = State::new(&config, deal).unwrap();
    let abstract_tree = abstract_game::tree::BettingTree::build(&root, &menus);
    let starts = search::leaf::turn_starts_in(&abstract_tree).len();
    // Decision points by street: the turn's and river's are what a leaf table build walks.
    let mut by_street = [0usize; 4];
    for id in 0..abstract_tree.len() as u32 {
        by_street[abstract_tree.node(id).street as usize] += 1;
    }
    let table_bytes = |lanes: usize| starts as u64 * lanes as u64 * 200 * 200 * 4;
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({"stack_bb": bb, "lines": out,
            "abstract_nodes": abstract_tree.len(), "abstract_nodes_by_street": by_street,
            "turn_starts": starts,
            "leaf_table_bytes_at_200_buckets": table_bytes(search::leaf::MODICUM_LANES),
            "leaf_table_bytes_at_200_buckets_16_lanes": table_bytes(search::leaf::BOTH_LANES)}))
        .unwrap()
    );
}

/// Collects flop and turn decisions from hands against the blueprint, then times the solve
/// of each again from scratch on 1, 2 and 4 threads.
fn scale(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let hands: u64 = get(opts, "hands", 40);
    let seed: u64 = get(opts, "seed", 1);
    let spots: usize = get(opts, "spots", 6);
    let base = load_search(opts, &strategy, settings(opts));
    let mut saved: Vec<State> = Vec::new();
    play_hands(&base, hands, seed, |state, _, _| {
        let street = state.street();
        let n = saved.iter().filter(|s| s.street() == street).count();
        if matches!(street, Street::Flop | Street::Turn) && n < spots {
            saved.push(state.clone());
        }
    });
    let mut rows = Vec::new();
    for state in &saved {
        let public = PublicState::new(state);
        let mut row = serde_json::Map::new();
        row.insert("street".into(), json!(street_name(state.street())));
        for t in [1usize, 2, 4] {
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(t)
                .build()
                .unwrap();
            let ms = pool.install(|| {
                let mut agent = SearchAgent::new(
                    Arc::clone(&base.bp),
                    base.leaf.clone(),
                    Settings {
                        turn_threads: t,
                        flop_parallel: t > 1,
                        ..settings(opts)
                    },
                );
                agent.keep_records = true;
                agent.plan(&public);
                agent
                    .take_records()
                    .into_iter()
                    .rev()
                    .find(|r| r.street == state.street())
                    .map(|r| (r.ms, r.solver_nodes, r.combos, r.iterations))
            });
            if let Some((ms, nodes, combos, it)) = ms {
                row.insert(format!("ms_{t}"), json!(ms));
                row.insert("nodes".into(), json!(nodes));
                row.insert("combos".into(), json!(combos));
                row.insert("iterations".into(), json!(it));
            }
        }
        rows.push(serde_json::Value::Object(row));
    }
    let text = serde_json::to_string_pretty(&rows).unwrap();
    println!("{text}");
    if let Some(path) = opts.get("out") {
        std::fs::write(path, text).expect("the report saves");
    }
}
