//! The search agent on a small trained blueprint (a bucketer that needs no tables): leaf
//! tables, legal play, ranges that keep the hand held, re-solving after an off-tree bet.

use std::sync::Arc;

use abstract_game::{preflop_class, AbstractGame, Bucketer, Card, GameConfig, Menus, Street};
use blueprint::{Blueprint, StrategyFile};
use cfr::{Mccfr, MccfrConfig, Sampling, Solver};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::{Action, Config, Deal, State};
use search::cards::{combo_index, mix};
use search::leaf::{build, BuildConfig, LeafTables, TABLE_LANES};
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
    let strategy = std::env::current_exe().unwrap(); // any file: only hashed
    let config = BuildConfig {
        deals,
        seed: 3,
        block: 4096,
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
        for lane in 0..TABLE_LANES {
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
    for lane in 1..TABLE_LANES {
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
    // Several blocks, the last one short.
    let config = BuildConfig {
        deals: 5_000,
        seed: 11,
        block: 1_200,
    };
    let reference = build_reference(&bp, &nodes, &config);
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
