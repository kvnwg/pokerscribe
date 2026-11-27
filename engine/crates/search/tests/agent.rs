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
