//! The search agent's command line: leaf tables, matches, LBR, timing and the range check.
//!
//! ```text
//! search leaf    --strategy F [--deals N] [--seed S]
//! search match   --strategy F --deals N --seed S [--threads T] [--against blueprint|search] [--out FILE]
//! search lbr     --strategy F --agent search|blueprint --setting fcpa14|b56_14 --hands N --seed S --out FILE
//! search compare FILE_A FILE_B
//! search bench   --strategy F --hands N --seed S [--threads T] [--out FILE]
//! search ranges  --strategy F --hands N --seed S [--out FILE]
//! search trees   [--stack-bb B] [--menu standard]     (tree sizes, for the 200bb estimate)
//! search scale   --strategy F --hands N --seed S [--spots K] (the same solves on 1, 2, 4 threads)
//! ```

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use arena::{run_match, MatchConfig};
use blueprint::{lbr_match, Blueprint, Deals};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::{Card, Config, Deal, State, Street};
use search::cards::{combo_index, mix};
use search::play::strategy_agent;
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
    s
}

fn main() {
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

fn leaf(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let bp = Blueprint::load(&strategy, None).expect("the strategy loads");
    let config = search::leaf::BuildConfig {
        deals: get(opts, "deals", 4_000_000),
        seed: get(opts, "seed", 7),
        ..Default::default()
    };
    let nodes = search::leaf::turn_starts(&bp);
    eprintln!("{} turn-start nodes, {} deals", nodes.len(), config.deals);
    let t0 = Instant::now();
    let tables = search::leaf::build(&bp, &strategy, &config, |done| {
        eprintln!("  {done} deals, {:.0} s", t0.elapsed().as_secs_f64());
    })
    .expect("the tables build");
    let out = leaf_path(&strategy);
    tables.save(&out).expect("the tables save");
    println!("{}", serde_json::to_string(&tables.header).unwrap());
    eprintln!("wrote {}", out.display());
}

fn agent_named(name: &str, strategy: &Path, settings: Settings) -> Arc<dyn Strategy + Send + Sync> {
    match name {
        "search" => {
            Arc::new(SearchAgent::load(strategy, settings).expect("the search agent loads"))
        }
        "blueprint" => Arc::new(Blueprint::load(strategy, None).expect("the blueprint loads")),
        _ => panic!("unknown agent {name}"),
    }
}

struct Dyn(Arc<dyn Strategy + Send + Sync>);

impl Strategy for Dyn {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        self.0.action_probs(public, hole, out)
    }
    fn action_prob_for_range(
        &self,
        public: &PublicState<'_>,
        action: nlhe::Action,
        hands: &[[Card; 2]],
        out: &mut [f64],
    ) {
        self.0.action_prob_for_range(public, action, hands, out)
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
    let bp = Blueprint::load(&strategy, None).expect("the blueprint loads");
    let stack = stack_of(&bp);
    let a = strategy_agent(
        "search",
        Arc::new(Dyn(agent_named("search", &strategy, settings(opts)))),
    );
    let b = strategy_agent(
        &against,
        Arc::new(Dyn(agent_named(&against, &strategy, settings(opts)))),
    );
    let mut config = MatchConfig::heads_up(deals, seed);
    config.stack = stack;
    config.threads = threads;
    let t0 = Instant::now();
    let report = run_match(&config, &[a, b]).expect("the match runs");
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
    let (paper, lbr_config) = blueprint::gate::lbr_setting(&setting).expect("a known LBR setting");
    let bp = Blueprint::load(&strategy, None).expect("the blueprint loads");
    let table = lbr::MatchConfig {
        stack: stack_of(&bp),
        ..lbr::MatchConfig::acpc(hands, seed)
    };
    let agent = Dyn(agent_named(&name, &strategy, settings(opts)));
    let t0 = Instant::now();
    let deals = lbr_match(&agent, &lbr_config, &table);
    let secs = t0.elapsed().as_secs_f64();
    let r = deals.result();
    println!(
        "{}",
        json!({"agent": name, "setting": setting, "paper": paper, "hands": r.hands, "seed": seed,
               "lbr_bb_per_100": r.bb_per_100, "se": r.std_err, "seconds": secs})
    );
    let out = need(opts, "out");
    deals.save(Path::new(&out)).expect("the deals save");
}

fn compare(rest: &[String]) {
    let a = Deals::load(Path::new(&rest[0])).expect("deals A");
    let b = Deals::load(Path::new(&rest[1])).expect("deals B");
    let (diff, se) = a.minus(&b).expect("the same deals");
    let (ra, rb) = (a.result(), b.result());
    println!(
        "{}",
        json!({"a": rest[0], "b": rest[1], "a_bb_per_100": ra.bb_per_100, "a_se": ra.std_err,
               "b_bb_per_100": rb.bb_per_100, "b_se": rb.std_err, "a_minus_b": diff, "se": se,
               "z": if se > 0.0 { diff / se } else { 0.0 }})
    );
}

/// Plays `hands` hands of the search agent against the blueprint, seats alternating, with
/// the real cards known, calling `look` before every decision of the search agent.
fn play_hands(
    agent: &SearchAgent,
    hands: u64,
    seed: u64,
    mut look: impl FnMut(&State, usize, f64),
) -> (f64, u64) {
    let bp = &agent.bp;
    let c = bp.game().config();
    let mut won = 0.0;
    let mut decisions = 0;
    for h in 0..hands {
        let s = mix(seed ^ mix(h));
        let config = Config::new(
            &[c.stack, c.stack],
            c.small_blind,
            c.big_blind,
            0,
            (h % 2) as usize,
        )
        .unwrap();
        let mut cards: Vec<Card> = (0..52).collect();
        let mut x = s;
        for i in 0..9 {
            x = mix(x.wrapping_add(i as u64 + 1));
            let j = i + (x % (52 - i as u64)) as usize;
            cards.swap(i, j);
        }
        let deal = Deal::new(
            &[[cards[0], cards[1]], [cards[2], cards[3]]],
            [cards[4], cards[5], cards[6], cards[7], cards[8]],
        )
        .unwrap();
        let mut state = State::new(&config, deal).unwrap();
        // The search agent sits in seat 0.
        let mut probs = ActionProbs::new();
        let mut step = 0u64;
        while !state.is_terminal() {
            let seat = state.current_player().unwrap();
            let public = PublicState::new(&state);
            let hole = state.hole_cards(seat);
            probs.clear();
            if seat == 0 {
                let t0 = Instant::now();
                agent.action_probs(&public, hole, &mut probs);
                let ms = t0.elapsed().as_secs_f64() * 1000.0;
                look(&state, seat, ms);
                decisions += 1;
            } else {
                bp.action_probs(&public, hole, &mut probs);
            }
            step += 1;
            let u = (mix(s ^ (step << 8)) >> 11) as f64 / (1u64 << 53) as f64;
            let a = probs.sample(u).expect("some action");
            state.apply(a).expect("a legal action");
        }
        let payouts = state.payouts(&lbr::EvalRanker).expect("the hand is over");
        won += payouts[0] as f64;
    }
    (won, decisions)
}

fn percentile(v: &mut [f64], p: f64) -> f64 {
    if v.is_empty() {
        return f64::NAN;
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let i = ((v.len() as f64 - 1.0) * p).round() as usize;
    v[i]
}

fn street_name(s: Street) -> &'static str {
    match s {
        Street::Preflop => "preflop",
        Street::Flop => "flop",
        Street::Turn => "turn",
        Street::River => "river",
    }
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
    let mut agent = SearchAgent::load(&strategy, settings).expect("the agent loads");
    agent.keep_records = true;
    let mut by_street: HashMap<&'static str, Vec<f64>> = HashMap::new();
    let t0 = Instant::now();
    let (_, decisions) = play_hands(&agent, hands, seed, |state, _, ms| {
        by_street
            .entry(street_name(state.street()))
            .or_default()
            .push(ms);
    });
    let records = agent.take_records();
    let mut out = serde_json::Map::new();
    for s in ["preflop", "flop", "turn", "river"] {
        let mut v = by_street.remove(s).unwrap_or_default();
        let n = v.len();
        let (p50, p95, max) = (
            percentile(&mut v, 0.5),
            percentile(&mut v, 0.95),
            percentile(&mut v, 1.0),
        );
        let mut solves: Vec<f64> = records
            .iter()
            .filter(|r| street_name(r.street) == s)
            .map(|r| r.ms)
            .collect();
        let ns = solves.len();
        let (s50, s95, smax) = (
            percentile(&mut solves, 0.5),
            percentile(&mut solves, 0.95),
            percentile(&mut solves, 1.0),
        );
        let iters: Vec<f64> = records
            .iter()
            .filter(|r| street_name(r.street) == s)
            .map(|r| r.iterations as f64)
            .collect();
        let expl: Vec<f64> = records
            .iter()
            .filter(|r| street_name(r.street) == s)
            .map(|r| r.exploitability)
            .collect();
        let combos: Vec<f64> = records
            .iter()
            .filter(|r| street_name(r.street) == s)
            .map(|r| (r.combos[0] + r.combos[1]) as f64 / 2.0)
            .collect();
        let nodes: Vec<f64> = records
            .iter()
            .filter(|r| street_name(r.street) == s)
            .map(|r| r.solver_nodes as f64)
            .collect();
        let mean = |v: &[f64]| {
            if v.is_empty() {
                f64::NAN
            } else {
                v.iter().sum::<f64>() / v.len() as f64
            }
        };
        out.insert(
            s.into(),
            json!({"decisions": n, "decision_ms_p50": p50, "decision_ms_p95": p95, "decision_ms_max": max,
                   "solves": ns, "resolves": records.iter().filter(|r| street_name(r.street) == s && r.resolve).count(),
                   "solve_ms_p50": s50, "solve_ms_p95": s95, "solve_ms_max": smax,
                   "mean_iterations": mean(&iters), "mean_exploitability": mean(&expl),
                   "mean_combos": mean(&combos), "mean_solver_nodes": mean(&nodes)}),
        );
    }
    out.insert("hands".into(), json!(hands));
    out.insert("decisions".into(), json!(decisions));
    out.insert("threads".into(), json!(threads));
    out.insert("seconds".into(), json!(t0.elapsed().as_secs_f64()));
    let text = serde_json::to_string_pretty(&out).unwrap();
    println!("{text}");
    if let Some(path) = opts.get("out") {
        std::fs::write(path, text).expect("the report saves");
    }
}

fn ranges(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let hands: u64 = get(opts, "hands", 200);
    let seed: u64 = get(opts, "seed", 1);
    let agent = SearchAgent::load(&strategy, settings(opts)).expect("the agent loads");
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
        let mut s = State::new(&config, deal.clone()).unwrap();
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
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({"stack_bb": bb, "lines": out})).unwrap()
    );
}

/// Collects flop and turn decisions from hands against the blueprint, then times the solve
/// of each again from scratch on 1, 2 and 4 threads.
fn scale(opts: &HashMap<String, String>) {
    let strategy = PathBuf::from(need(opts, "strategy"));
    let hands: u64 = get(opts, "hands", 40);
    let seed: u64 = get(opts, "seed", 1);
    let spots: usize = get(opts, "spots", 6);
    let base = SearchAgent::load(&strategy, settings(opts)).expect("the agent loads");
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
