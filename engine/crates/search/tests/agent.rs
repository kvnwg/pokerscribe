//! The search agent on a small trained blueprint (a bucketer that needs no tables): leaf
//! tables, legal play, ranges that keep the hand held, re-solving after an off-tree bet.

use std::sync::Arc;

use abstract_game::{preflop_class, AbstractGame, Bucketer, Card, GameConfig, Menus, Street};
use blueprint::{Blueprint, StrategyFile};
use cfr::{Mccfr, MccfrConfig, Sampling, Solver};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::{Action, Config, Deal, State};
use search::cards::{combo_index, mix};
use search::leaf::{build, lane_of, BuildConfig, LeafTables, BOTH_LANES, MODICUM_LANES};
use search::solve::{LeafChoice, Play};
use search::{SearchAgent, Settings};

/// The 169 starting hands, then the category of the best hand (9 buckets a street).
#[derive(Clone, Copy, Debug, Default)]
struct Category;

impl Bucketer for Category {
    fn num_buckets(&self, street: Street) -> u64 {
        if street == Street::Preflop {
            169
        } else {
            9
        }
    }
    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
        if board.is_empty() {
            return preflop_class(hole) as u64;
        }
        let cards: Vec<eval::Card> = hole
            .iter()
            .chain(board)
            .map(|&c| eval::Card::from_index(c).unwrap())
            .collect();
        eval::eval(&cards).category() as u64
    }
}

fn blueprint() -> Arc<Blueprint<Category>> {
    let game = AbstractGame::new(GameConfig::new(20, Menus::standard()), Category).unwrap();
    let mut solver = Mccfr::new(game, MccfrConfig::new(Sampling::External, 7));
    solver.run(3_000);
    let file = StrategyFile::from_solver(&solver, None, None, 0.0).file;
    let config = solver.game().config().clone();
    Arc::new(Blueprint::new(AbstractGame::new(config, Category).unwrap(), file).unwrap())
}

fn tables(bp: &Blueprint<Category>, deals: u64) -> LeafTables {
    tables_with(bp, deals, MODICUM_LANES)
}

fn tables_with(bp: &Blueprint<Category>, deals: u64, lanes: usize) -> LeafTables {
    let strategy = std::env::current_exe().unwrap(); // any file: only hashed
    let config = BuildConfig {
        deals,
        seed: 3,
        block: 4096,
        lanes,
    };
    build(bp, &strategy, &config, |_| {}).unwrap()
}

fn fast() -> Settings {
    Settings {
        flop_iterations: 40,
        turn_iterations: 16,
        river_iterations: 60,
        prune: 0.02,
        ..Settings::default()
    }
}

/// A hand at 2,000 chips, blinds 50 and 100, the button in seat 0, after `actions`.
fn hand(seed: u64, actions: &[Action]) -> State {
    let config = Config::new(&[2_000, 2_000], 50, 100, 0, 0).unwrap();
    let mut cards: Vec<u8> = (0..52).collect();
    let mut x = seed;
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
    let mut s = State::new(&config, deal).unwrap();
    for &a in actions {
        s.apply(a).unwrap();
    }
    s
}

#[test]
fn leaf_tables_are_the_same_on_any_number_of_threads_and_in_range() {
    let bp = blueprint();
    let one = rayon::ThreadPoolBuilder::new()
        .num_threads(1)
        .build()
        .unwrap();
    let three = rayon::ThreadPoolBuilder::new()
        .num_threads(3)
        .build()
        .unwrap();
    let a = one.install(|| tables(&bp, 20_000));
    let b = three.install(|| tables(&bp, 20_000));
    assert_eq!(a.header.nodes, b.header.nodes);
    assert!(!a.header.nodes.is_empty());
    for &node in &a.header.nodes {
        for lane in 0..MODICUM_LANES {
            let (x, y) = (a.table(node, lane).unwrap(), b.table(node, lane).unwrap());
            assert_eq!(x, y);
            // A share of the pot at the node: within what the stacks allow.
            assert!(x
                .iter()
                .all(|v| v.is_finite() && (-20.0..=21.0).contains(v)));
        }
    }
    // The biased lanes are other strategies: somewhere they change the value.
    let node = a.header.nodes[0];
    let base = a.table(node, 0).unwrap();
    for lane in 1..MODICUM_LANES {
        let t = a.table(node, lane).unwrap();
        assert!(
            t.iter().zip(base).any(|(x, y)| (x - y).abs() > 1e-3),
            "lane {lane}"
        );
    }
}

#[test]
fn the_agent_plays_legal_actions_and_keeps_its_hand_in_its_range() {
    let bp = blueprint();
    let leaf = Arc::new(tables(&bp, 20_000));
    let agent = SearchAgent::new(Arc::clone(&bp), Some(leaf), fast());
    let mut searched = 0;
    let mut in_solve = 0;
    for h in 0..10u64 {
        let mut state = hand(mix(h + 100), &[]);
        let mut step = 0;
        while !state.is_terminal() {
            let seat = state.current_player().unwrap();
            let public = PublicState::new(&state);
            let hole = state.hole_cards(seat);
            let mut probs = ActionProbs::new();
            if seat == (h % 2) as usize {
                agent.action_probs(&public, hole, &mut probs);
                let legal = state.legal_actions();
                assert!(probs.as_slice().iter().all(|&(a, _)| legal.allows(a)));
                assert!((probs.total() - 1.0).abs() < 1e-6);
                if state.street() != nlhe::Street::Preflop {
                    searched += 1;
                    let r = agent.street_ranges(&public, state.street(), seat);
                    let c = combo_index(hole[0], hole[1]);
                    assert!(r[seat][c] > 0.0, "the hand held left its own range");
                    let plan = agent.plan(&public);
                    if let Some(p) = plan {
                        in_solve += p.solve.combos[p.player].binary_search(&c).is_ok() as u32;
                    }
                }
            } else {
                bp.action_probs(&public, hole, &mut probs);
            }
            step += 1;
            let u = (mix(h * 1000 + step) >> 11) as f64 / (1u64 << 53) as f64;
            state.apply(probs.sample(u).unwrap()).unwrap();
        }
    }
    assert!(
        searched > 0 && in_solve > 0,
        "{searched} searched, {in_solve} in the solve"
    );
}

#[test]
fn an_off_tree_bet_is_added_and_the_street_solved_again_with_the_earlier_decision_fixed() {
    let bp = blueprint();
    let leaf = Arc::new(tables(&bp, 20_000));
    let agent = SearchAgent::new(Arc::clone(&bp), Some(leaf), fast());
    // A limped pot of 200: on the flop the big blind (seat 1) acts first.
    let flop = hand(9, &[Action::Call, Action::Check]);
    let first = agent
        .plan(&PublicState::new(&flop))
        .expect("the flop is solved");
    assert!(first.solve.extras.is_empty());
    // The big blind checks; the button bets 150 (on the menu) or 120 (off it).
    let on = hand(
        9,
        &[
            Action::Call,
            Action::Check,
            Action::Check,
            Action::RaiseTo(150),
        ],
    );
    let again = agent.plan(&PublicState::new(&on)).unwrap();
    assert!(
        Arc::ptr_eq(&again.solve, &first.solve),
        "an on-menu bet reuses the solve"
    );
    let off = hand(
        9,
        &[
            Action::Call,
            Action::Check,
            Action::Check,
            Action::RaiseTo(120),
        ],
    );
    let resolved = agent.plan(&PublicState::new(&off)).unwrap();
    assert!(!Arc::ptr_eq(&resolved.solve, &first.solve));
    assert_eq!(resolved.solve.extras.len(), 1);
    assert_eq!(resolved.solve.extras[0].action, Action::RaiseTo(120));
    assert_eq!(
        resolved.solve.tree.nodes[resolved.node].path,
        vec![Action::Check, Action::RaiseTo(120)]
    );
    // The check the big blind made is fixed to the strategy it was made with.
    assert_eq!(resolved.solve.strategy[0], first.solve.strategy[0]);
    assert_eq!(resolved.solve.combos, first.solve.combos);
    // The answer to 120 is legal for every hand.
    let public = PublicState::new(&off);
    let legal = off.legal_actions();
    for &c in resolved.solve.combos[resolved.player].iter().take(50) {
        let [a, b] = lbr::combo_cards(c);
        let mut probs = ActionProbs::new();
        agent.action_probs(&public, [a, b], &mut probs);
        assert!(probs.as_slice().iter().all(|&(x, _)| legal.allows(x)));
    }
}

#[test]
fn the_same_public_state_gets_the_same_answer() {
    let bp = blueprint();
    let leaf = Arc::new(tables(&bp, 20_000));
    let state = hand(
        11,
        &[
            Action::Call,
            Action::Check,
            Action::Check,
            Action::RaiseTo(100),
        ],
    );
    let public = PublicState::new(&state);
    let hands: Vec<[u8; 2]> = (0..30u64)
        .map(|i| {
            let a = (mix(i) % 52) as u8;
            let b = ((a as u64 + 1 + mix(i + 99) % 51) % 52) as u8;
            [a, b]
        })
        .filter(|h| !public.board().contains(&h[0]) && !public.board().contains(&h[1]))
        .collect();
    let answer = || {
        let agent = SearchAgent::new(Arc::clone(&bp), Some(Arc::clone(&leaf)), fast());
        let mut out = vec![0.0; hands.len()];
        agent.action_prob_for_range(&public, Action::Call, &hands, &mut out);
        out
    };
    assert_eq!(answer(), answer());
}

/// The leaf tables built in parts, in parallel, are the sequential build's bit for bit (the
/// build as it was before parts: every node walks every deal in the stream's order), on any
/// number of threads, and however the nodes are split.
#[test]
fn leaf_tables_in_parts_are_the_sequential_build_bit_for_bit() {
    use search::leaf::{build_part, build_reference, turn_starts};
    let bp = blueprint();
    let nodes = turn_starts(&bp);
    assert!(nodes.len() > 10, "{} turn starts", nodes.len());
    for lanes in [MODICUM_LANES, BOTH_LANES] {
        // Several blocks, the last one short.
        let config = BuildConfig {
            deals: 5_000,
            seed: 11,
            block: 1_200,
            lanes,
        };
        let reference = build_reference(&bp, &nodes, &config);
        assert_eq!(reference.len(), nodes.len() * lanes * 81);
        for threads in [1, 3] {
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(threads)
                .build()
                .unwrap();
            pool.install(|| {
                let whole = build_part(&bp, &nodes, &config, &|| false, |_| {}).unwrap();
                assert!(whole.q == reference, "one part, {threads} thread(s)");
                assert_eq!(whole.count.iter().sum::<u64>(), config.deals);
                let mut joined = Vec::new();
                for chunk in nodes.chunks(7) {
                    let part = build_part(&bp, chunk, &config, &|| false, |_| {}).unwrap();
                    assert_eq!(part.count, whole.count);
                    joined.extend(part.q);
                }
                assert!(joined == reference, "parts of 7 nodes, {threads} thread(s)");
            });
        }
        // A stop asked for gives the part up.
        assert!(build_part(&bp, &nodes[..3], &config, &|| true, |_| {}).is_none());
    }
}

/// Every lane is walked on its own, so the 16 lanes of both players' picks hold the 7 of
/// Modicum's (one player biased at a time) bit for bit.
#[test]
fn sixteen_lanes_hold_the_seven_bit_for_bit() {
    use search::leaf::lane_choices;
    let bp = blueprint();
    let seven = tables_with(&bp, 20_000, MODICUM_LANES);
    let sixteen = tables_with(&bp, 20_000, BOTH_LANES);
    assert_eq!((seven.header.lanes, sixteen.header.lanes), (7, 16));
    assert_eq!(seven.header.nodes, sixteen.header.nodes);
    assert_eq!(seven.header.cell_deals, sixteen.header.cell_deals);
    for &node in &seven.header.nodes {
        for lane in 0..MODICUM_LANES {
            let [sb, bb] = lane_choices(MODICUM_LANES, lane);
            assert_eq!(lane_of(MODICUM_LANES, sb, bb), Some(lane));
            let both = lane_of(BOTH_LANES, sb, bb).unwrap();
            assert_eq!(
                seven.table(node, lane),
                sixteen.table(node, both),
                "lane {lane}"
            );
        }
    }
    // Both biased at once is new: somewhere it is neither one alone.
    let node = seven.header.nodes[0];
    let both = sixteen
        .table(node, lane_of(BOTH_LANES, 3, 3).unwrap())
        .unwrap();
    let sb = seven
        .table(node, lane_of(MODICUM_LANES, 3, 0).unwrap())
        .unwrap();
    let bb = seven
        .table(node, lane_of(MODICUM_LANES, 0, 3).unwrap())
        .unwrap();
    assert!(both
        .iter()
        .zip(sb.iter().zip(bb))
        .any(|(x, (y, z))| (x - y).abs() > 1e-3 && (x - z).abs() > 1e-3));
    // And a 7-lane table has no pair of biased players.
    assert_eq!(lane_of(MODICUM_LANES, 1, 2), None);
}

/// With both players picking at the leaves (16 lanes) the agent plays legal actions, and
/// either way of playing a solve works; on 7-lane tables that setting is refused.
#[test]
fn both_players_pick_on_sixteen_lane_tables() {
    let bp = blueprint();
    let both = Settings {
        leaf_choice: LeafChoice::Both,
        ..fast()
    };
    let seven = Arc::new(tables(&bp, 5_000));
    let refused = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        SearchAgent::new(Arc::clone(&bp), Some(Arc::clone(&seven)), both.clone())
    }));
    let message = refused
        .err()
        .and_then(|e| e.downcast_ref::<String>().cloned());
    assert!(
        message.as_deref().is_some_and(|m| m.contains("needs 16")),
        "{message:?}"
    );
    let sixteen = Arc::new(tables_with(&bp, 5_000, BOTH_LANES));
    for play in [Play::Average, Play::Final] {
        let settings = Settings {
            play,
            ..both.clone()
        };
        let agent = SearchAgent::new(Arc::clone(&bp), Some(Arc::clone(&sixteen)), settings);
        let mut flops = 0;
        for h in 0..4u64 {
            // A limped pot: every hand gets to the flop.
            let mut state = hand(mix(h + 500), &[Action::Call, Action::Check]);
            let mut step = 0;
            while !state.is_terminal() {
                let seat = state.current_player().unwrap();
                let public = PublicState::new(&state);
                let hole = state.hole_cards(seat);
                let mut probs = ActionProbs::new();
                if seat == (h % 2) as usize {
                    agent.action_probs(&public, hole, &mut probs);
                    let legal = state.legal_actions();
                    assert!(probs.as_slice().iter().all(|&(a, _)| legal.allows(a)));
                    assert!((probs.total() - 1.0).abs() < 1e-6);
                    if state.street() == nlhe::Street::Flop {
                        let plan = agent.plan(&public).expect("a flop solve");
                        assert!(plan.solve.table_leaves > 0, "no leaf from the tables");
                        flops += 1;
                    }
                } else {
                    bp.action_probs(&public, hole, &mut probs);
                }
                step += 1;
                let u = (mix(h * 1000 + step) >> 11) as f64 / (1u64 << 53) as f64;
                state.apply(probs.sample(u).unwrap()).unwrap();
            }
        }
        assert!(flops > 0, "{play:?}: no flop solve");
    }
}

/// The leaf table job (`search::leaf_job`): it stops between blocks and goes on from the
/// parts on the disk, refuses a checkpoint that isn't its build's, builds again a part
/// that is missing or damaged, and ends with the same tables as a build in one piece.
#[test]
fn the_leaf_job_stops_goes_on_and_gives_the_one_piece_tables() {
    use search::leaf_job::{part_name, run, Checkpoint, JobConfig, JobEnd, CHECKPOINT};
    let bp = blueprint();
    let dir = std::env::temp_dir().join(format!("search-leaf-job-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let strategy = std::env::current_exe().unwrap(); // any file: only hashed
    let config = JobConfig {
        strategy: strategy.clone(),
        tables: None,
        deals: 3_000,
        seed: 3,
        part_nodes: 9,
        lanes: MODICUM_LANES,
        out: Some("t.leaf".into()),
    };
    let parts_on_disk = || {
        std::fs::read_dir(&dir)
            .map(|d| {
                d.filter_map(|e| e.ok())
                    .filter(|e| e.file_name().to_string_lossy().ends_with(".leafpart"))
                    .count()
            })
            .unwrap_or(0)
    };
    let mut events = Vec::new();
    // --resume with nothing to resume is an error.
    assert!(run(&bp, &config, &dir, true, &|| false, &mut |v| events.push(v)).is_err());
    // Stopped once two parts are done.
    let end = run(
        &bp,
        &config,
        &dir,
        false,
        &|| parts_on_disk() >= 2,
        &mut |v| events.push(v),
    );
    assert_eq!(end, Ok(JobEnd::Stopped));
    assert_eq!(events.last().unwrap()["event"], "saved on SIGTERM");
    let ckpt: Checkpoint =
        serde_json::from_str(&std::fs::read_to_string(dir.join(CHECKPOINT)).unwrap()).unwrap();
    assert_eq!(ckpt.done, vec![0, 1]);
    assert!(ckpt.parts > 3, "{} parts", ckpt.parts);
    // A checkpoint is there: without --resume, or for another build, it is refused.
    assert!(run(&bp, &config, &dir, false, &|| false, &mut |_| {}).is_err());
    let other = JobConfig {
        seed: 4,
        ..config.clone()
    };
    let err = run(&bp, &other, &dir, true, &|| false, &mut |_| {}).unwrap_err();
    assert!(err.contains("another build"), "{err}");
    let other = JobConfig {
        lanes: BOTH_LANES,
        ..config.clone()
    };
    let err = run(&bp, &other, &dir, true, &|| false, &mut |_| {}).unwrap_err();
    assert!(err.contains("another build"), "{err}");
    // Part 0 damaged (one value changed), part 1 gone (an upload cut off): both built again.
    let p0 = dir.join(part_name(0));
    let mut bytes = std::fs::read(&p0).unwrap();
    let n = bytes.len();
    bytes[n - 3] ^= 0x40;
    std::fs::write(&p0, bytes).unwrap();
    std::fs::remove_file(dir.join(part_name(1))).unwrap();
    events.clear();
    let end = run(&bp, &config, &dir, true, &|| false, &mut |v| events.push(v)).unwrap();
    assert_eq!(events[0]["event"], "resumed");
    assert_eq!(events[0]["parts_done"], 0);
    assert_eq!(
        events[0]["parts_listed_but_missing"],
        serde_json::json!([0, 1])
    );
    assert_eq!(events.last().unwrap()["event"], "done");
    let JobEnd::Done(path) = end else {
        panic!("not done")
    };
    assert_eq!(path, dir.join("t.leaf"));
    // The same tables as the one-piece build.
    let job = LeafTables::load(&path).unwrap();
    let one = build(
        &bp,
        &strategy,
        &BuildConfig {
            deals: 3_000,
            seed: 3,
            ..Default::default()
        },
        |_| {},
    )
    .unwrap();
    assert!(job.values() == one.values());
    assert_eq!(job.header.nodes, one.header.nodes);
    assert_eq!(
        (job.header.buckets, job.header.deals, job.header.seed),
        (one.header.buckets, one.header.deals, one.header.seed)
    );
    assert_eq!(job.header.strategy_hash, one.header.strategy_hash);
    assert_eq!(job.header.cell_deals, one.header.cell_deals);
    // A finished job run again is done at once, from the parts.
    let again = run(&bp, &config, &dir, true, &|| true, &mut |_| {}).unwrap();
    assert_eq!(again, JobEnd::Done(dir.join("t.leaf")));
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A small plan for the test blueprint: 16-lane tables, both players picking, every step
/// in a few deals (the gate passes by construction, so the repeat is played).
fn small_plan(strategy: &std::path::Path, flop_bound_ms: f64) -> search::plan_job::PlanConfig {
    let agent = |leaf_choice: &str, play: &str| {
        serde_json::json!({"leaf_choice": leaf_choice, "play": play, "flop_iterations": 40,
                           "turn_iterations": 16, "river_iterations": 60, "prune": 0.02})
    };
    let text = serde_json::json!({
        "strategy": strategy,
        "leaf": {"deals": 2000, "seed": 3, "lanes": 16, "part_nodes": 9},
        "agent": agent("both", "average"),
        "bench": {"hands": 2, "seed": 581, "threads": 2,
                  "bound_ms": {"flop": flop_bound_ms, "turn": 600000, "river": 600000}},
        "pilot": {"deals": 8, "seed": 501},
        "size": {"edge_bb_per_100": 10, "z": 2.5, "step": 8, "min": 8, "max": 16},
        "gate": {"chunk": 8, "seed": 600, "pass_z": -1e9, "measure": "aivat"},
        "variants": [{"name": "final", "agent": agent("both", "final"), "chunks": 1, "seed": 900},
                     {"name": "modicum", "agent": agent("opponent", "average"), "chunks": 1, "seed": 950}],
        "lbr": {"hands": 4, "chunks": 1, "settings": [{"name": "fcpa14", "seed": 560}]},
        "repeat": {"seed": 700}
    })
    .to_string();
    search::plan_job::PlanConfig::from_json(&text).unwrap()
}

/// The plan job (`search::plan_job`): it refuses a missing or another plan's checkpoint,
/// stops between runs and goes on from the results on the disk without playing them
/// again, writes every step's results, and its leaf tables are the one-piece build's.
#[test]
fn the_plan_job_plays_every_step_stops_and_goes_on() {
    use search::plan_job::{run, MatchPlan, PlanConfig, PlanEnd};
    let bp = Arc::new(blueprint());
    let dir = std::env::temp_dir().join(format!("search-plan-job-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let strategy = std::env::current_exe().unwrap(); // any file: only hashed
    let config = small_plan(&strategy, 600_000.0);
    let read = |name: &str| -> serde_json::Value {
        serde_json::from_slice(&std::fs::read(dir.join(name)).unwrap()).unwrap()
    };
    // --resume with nothing to resume is an error.
    assert!(run(Arc::clone(&bp), &config, &dir, true, &|| false, &mut |_| {}).is_err());
    // Stopped once the pilot is written: the gate's first chunk is given up.
    let pilot = dir.join("pilot.json");
    let mut events = Vec::new();
    let end = run(
        Arc::clone(&bp),
        &config,
        &dir,
        false,
        &|| pilot.exists(),
        &mut |v| events.push(v),
    )
    .unwrap();
    assert_eq!(end, PlanEnd::Stopped);
    assert_eq!(events.last().unwrap()["event"], "saved on SIGTERM");
    assert_eq!(events.last().unwrap()["step"], "gate");
    // The build's own lines carry its step; the plan's start is the only "started".
    let named = |e: &serde_json::Value, name: &str| e["event"] == name;
    assert!(named(&events[0], "started") && events[0].get("step").is_none());
    assert!(!events[1..]
        .iter()
        .any(|e| named(e, "started") || named(e, "resumed") || named(e, "done")));
    let built: Vec<_> = (0..events.len())
        .filter(|&i| named(&events[i], "leaf tables built"))
        .collect();
    assert_eq!(built.len(), 1);
    assert!(named(&events[1], "leaf build started"));
    assert!(events[1..=built[0]].iter().all(|e| e["step"] == "leaf"));
    for f in ["bench.json", "bounds.json", "pilot.json", "size.json"] {
        assert!(dir.join(f).exists(), "{f}");
    }
    assert!(!dir.join("match-01.json").exists());
    let bench = std::fs::read(dir.join("bench.json")).unwrap();
    // A checkpoint is there: without --resume, or for another plan, it is refused.
    assert!(run(
        Arc::clone(&bp),
        &config,
        &dir,
        false,
        &|| false,
        &mut |_| {}
    )
    .is_err());
    let other = PlanConfig {
        pilot: MatchPlan {
            deals: 8,
            seed: 502,
        },
        ..config.clone()
    };
    let err = run(Arc::clone(&bp), &other, &dir, true, &|| false, &mut |_| {}).unwrap_err();
    assert!(err.contains("another plan"), "{err}");
    // Resumed: every step is played, and nothing done is played again.
    events.clear();
    let end = run(Arc::clone(&bp), &config, &dir, true, &|| false, &mut |v| {
        events.push(v)
    })
    .unwrap();
    let PlanEnd::Done(summary) = end else {
        panic!("not done")
    };
    assert_eq!(summary["end"], "every step is played");
    assert_eq!(std::fs::read(dir.join("bench.json")).unwrap(), bench);
    assert!(
        !events.iter().any(|e| e.get("parts_done").is_some()),
        "the leaf tables were built again"
    );
    let size = read("size.json");
    let chunks = size["chunks"].as_u64().unwrap();
    assert!((1..=2).contains(&chunks) && size["deals"] == chunks * 8);
    for k in 1..=chunks {
        for prefix in ["match", "repeat"] {
            let r = read(&format!("{prefix}-{k:02}.json"));
            let seed = if prefix == "match" { 600 } else { 700 } + k;
            assert_eq!(r["config"]["seed"], seed);
            assert_eq!(r["deals"], 8);
        }
    }
    let gate = read("gate.json");
    assert_eq!(gate["deals"], chunks * 8);
    assert_eq!(gate["passes"], true);
    assert_eq!(gate["illegal_actions"], 0);
    // AIVAT is pooled beside the plain figure and decides, as registered: every decision of
    // both agents is corrected (their chances are known), none unexplained.
    assert_eq!(size["measure"], "aivat");
    assert!(size["plain"]["sd_per_deal"].as_f64().unwrap() > 0.0);
    let a = &gate["aivat"];
    assert!(a["se"].as_f64().unwrap() > 0.0, "{a}");
    assert_eq!(a["unexplained_decisions"], 0);
    for who in ["search", "blueprint"] {
        assert!(
            a["decisions"][who]["corrected"].as_u64().unwrap() > 0,
            "{a}"
        );
        assert_eq!(a["decisions"][who]["unknown"], 0, "{a}");
    }
    assert_eq!(gate["decides"]["measure"], "aivat");
    assert_eq!(gate["decides"]["z"], a["z"]);
    let match1 = read("match-01.json");
    assert!(match1["aivat_scoring"].as_str().is_some());
    let repeat = read("repeat.json");
    assert_eq!(repeat["deals"], chunks * 8);
    assert_eq!(repeat["decides"]["measure"], "aivat");
    assert_eq!(repeat["passes"], true);
    for v in ["final", "modicum"] {
        let r = read(&format!("variant-{v}.json"));
        assert_eq!(r["deals"], 8);
        assert!(r["aivat"]["se"].as_f64().unwrap() > 0.0);
        let d = &r["minus_gate_agent"];
        assert_eq!(d["measure"], "aivat");
        assert!(d["se"].as_f64().unwrap() > 0.0);
        assert!(d["plain"]["se"].as_f64().unwrap() > 0.0);
    }
    let lbr = read("lbr-search-fcpa14-1.json");
    assert_eq!(lbr["hands"], 4);
    assert!(lbr["solves"]["flop"]["solves"].as_u64().is_some());
    assert!(read("compare-fcpa14-1.json")["se"].as_f64().is_some());
    assert!(dir.join("lbr-blueprint-fcpa14-1.deals").exists());
    // The tables in the folder are the one-piece build's, bit for bit.
    let name = search::leaf_job::JobConfig {
        strategy: strategy.clone(),
        tables: None,
        deals: 2000,
        seed: 3,
        lanes: BOTH_LANES,
        part_nodes: 9,
        out: None,
    }
    .out_name();
    let job = LeafTables::load(&dir.join(name)).unwrap();
    let one = build(
        &bp,
        &strategy,
        &BuildConfig {
            deals: 2000,
            seed: 3,
            lanes: BOTH_LANES,
            ..Default::default()
        },
        |_| {},
    )
    .unwrap();
    assert!(job.values() == one.values());
    // A finished plan run again is done at once.
    let again = run(Arc::clone(&bp), &config, &dir, true, &|| true, &mut |_| {}).unwrap();
    assert!(matches!(again, PlanEnd::Done(_)));
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A street over its bound in the bench ends the plan before any match.
#[test]
fn the_plan_job_plays_no_match_over_the_bound() {
    use search::plan_job::{run, PlanEnd};
    let bp = Arc::new(blueprint());
    let dir = std::env::temp_dir().join(format!("search-plan-bound-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let strategy = std::env::current_exe().unwrap();
    let config = small_plan(&strategy, 1e-6);
    let end = run(
        Arc::clone(&bp),
        &config,
        &dir,
        false,
        &|| false,
        &mut |_| {},
    )
    .unwrap();
    let PlanEnd::Done(v) = end else {
        panic!("not done")
    };
    assert!(v["end"].as_str().unwrap().contains("over its bound"), "{v}");
    assert_eq!(v["bounds"]["over"], serde_json::json!(["flop"]));
    assert!(!dir.join("pilot.json").exists());
    std::fs::remove_dir_all(&dir).unwrap();
}
