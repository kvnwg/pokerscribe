//! The abstract game as the CFR library sees it: chance, information sets, sizes, the
//! mapping of off-menu raises, and a training run on a game with every street.

use std::collections::HashMap;

use abstract_game::{
    pseudo_harmonic, raise_amount, raise_to, AbstractGame, Bucketer, BuildError, EquityBands,
    GameConfig, HandState, Lossless, Menus, Size, Translation, CALL, CHIPS_PER_BIG_BLIND, FOLD,
};
use cfr::{Game, InfoKey, Mccfr, MccfrConfig, Node, Policy, Rng, Sampling, Solver, UniformPolicy};
use nlhe::{parse_card, Card, Street};

fn cards<const N: usize>(text: &str) -> [Card; N] {
    let cards: Vec<Card> = text
        .split_whitespace()
        .map(|c| parse_card(c).unwrap())
        .collect();
    cards.try_into().unwrap()
}

/// Nine different cards in random order.
fn random_deal(rng: &mut Rng) -> ([[Card; 2]; 2], [Card; 5]) {
    let mut deck: Vec<Card> = (0..52).collect();
    for i in 0..9 {
        let j = i + rng.below(52 - i);
        deck.swap(i, j);
    }
    let d = &deck;
    ([[d[0], d[1]], [d[2], d[3]]], [d[4], d[5], d[6], d[7], d[8]])
}

fn actions<B: Bucketer>(game: &AbstractGame<B>, state: &HandState) -> Vec<cfr::Action> {
    let mut out = Vec::new();
    game.legal_actions(state, &mut out);
    out
}

fn play<B: Bucketer>(game: &AbstractGame<B>, state: &HandState, line: &[cfr::Action]) -> HandState {
    let mut state = *state;
    for &action in line {
        assert!(
            actions(game, &state).contains(&action),
            "{action} is not offered"
        );
        game.apply(&mut state, action);
    }
    state
}

#[test]
fn chance_deals_nine_cards_one_at_a_time() {
    let game = AbstractGame::new(GameConfig::new(20, Menus::minimal()), Lossless).unwrap();
    assert_eq!(game.num_players(), 2);
    let mut state = game.root();
    let mut outcomes = Vec::new();
    let dealt: [Card; 9] = cards("As Kd 7c 7d 2h 9s Tc 3d Qh");
    for (i, &card) in dealt.iter().enumerate() {
        assert_eq!(game.node(&state), Node::Chance);
        assert_eq!(state.cards(), &dealt[..i]);
        assert!(game.replay(&state).is_none() && state.decision_point().is_none());
        assert!(!state.is_dealt() && !state.is_over());
        outcomes.clear();
        game.chance_outcomes(&state, &mut outcomes);
        // Every card not out yet, equally likely.
        assert_eq!(outcomes.len(), 52 - i);
        assert!(outcomes
            .iter()
            .all(|&(c, p)| !dealt[..i].contains(&(c as Card)) && p == 1.0 / (52 - i) as f64));
        assert!(outcomes.iter().any(|&(c, _)| c == card as cfr::Action));
        game.apply(&mut state, card as cfr::Action);
    }
    // Then the small blind acts, and the state is the same as dealing the cards directly.
    assert_eq!(game.node(&state), Node::Player(0));
    assert_eq!(state.decision_point(), Some(0));
    assert_eq!(state.cards(), dealt);
    let direct = game
        .deal([cards("As Kd"), cards("7c 7d")], cards("2h 9s Tc 3d Qh"))
        .unwrap();
    assert_eq!(state, direct);
    assert_eq!(state.hole_cards(0), Some(cards("As Kd")));
    assert_eq!(state.hole_cards(1), Some(cards("7c 7d")));
    assert_eq!(state.board(), Some(cards("2h 9s Tc 3d Qh")));
    // In the real game it is the same hand, with the board still face down.
    let hand = game.replay(&state).unwrap();
    assert_eq!(hand.hole_cards(0), cards::<2>("As Kd"));
    assert_eq!(hand.hole_cards(1), cards::<2>("7c 7d"));
    assert!(hand.board().is_empty() && hand.history().is_empty());
    assert_eq!(std::mem::size_of::<HandState>(), 88);
    // A card twice is refused.
    assert!(game
        .deal([cards("As Kd"), cards("As 7d")], cards("2h 9s Tc 3d Qh"))
        .is_err());
}

#[test]
fn sampled_cards_are_new_and_evenly_spread() {
    let game = AbstractGame::new(GameConfig::push_fold(10), Lossless).unwrap();
    let mut rng = Rng::new(4);
    let mut scratch = Vec::new();
    let mut state = game.root();
    for card in cards::<8>("As Kd 7c 7d 2h 9s Tc 3d") {
        game.apply(&mut state, card as cfr::Action);
    }
    // The ninth card: each of the 44 left about equally often, none of the 8 out.
    let mut seen = [0u32; 52];
    let draws = 44_000;
    for _ in 0..draws {
        seen[game.sample_chance(&state, &mut rng, &mut scratch) as usize] += 1;
    }
    for card in 0..52u8 {
        let n = seen[card as usize];
        if state.cards().contains(&card) {
            assert_eq!(n, 0);
        } else {
            // 1,000 expected, standard deviation about 31.
            assert!((850..=1_150).contains(&n), "card {card} drawn {n} times");
        }
    }
}

/// What the acting player knows: the betting so far and the bucket of their hand.
type Known = (Vec<nlhe::Action>, u64);
/// What was met under one key: what the player knew, who it was and what they could do.
type Seen = (Known, usize, Vec<cfr::Action>);

#[test]
fn an_information_set_is_a_decision_point_and_a_bucket() {
    let bands = EquityBands::new([6, 4, 3, 3]);
    let game = AbstractGame::new(GameConfig::new(3, Menus::small()), bands.clone()).unwrap();
    let mut by_key: HashMap<InfoKey, Seen> = HashMap::new();
    let mut by_known: HashMap<Known, InfoKey> = HashMap::new();

    fn walk<B: Bucketer>(
        game: &AbstractGame<B>,
        bands: &EquityBands,
        state: &HandState,
        by_key: &mut HashMap<InfoKey, Seen>,
        by_known: &mut HashMap<Known, InfoKey>,
    ) {
        let Node::Player(player) = game.node(state) else {
            return;
        };
        let hand = game.replay(state).unwrap();
        let line: Vec<nlhe::Action> = hand.history().iter().map(|m| m.action).collect();
        let bucket = bands.bucket(hand.hole_cards(player), hand.board());
        let key = game.info_key(state);
        assert_eq!(
            key,
            game.info_key_of(state.decision_point().unwrap(), bucket)
        );
        assert_eq!(game.tree().find(&line), state.decision_point());
        let offered = actions(game, state);
        let known = (line, bucket);
        // One key per (betting, bucket), and one (betting, bucket) per key, always with
        // the same player and the same actions.
        let entry = by_key
            .entry(key)
            .or_insert_with(|| (known.clone(), player, offered.clone()));
        assert_eq!(*entry, (known.clone(), player, offered.clone()));
        assert_eq!(*by_known.entry(known).or_insert(key), key);
        for action in offered {
            let mut next = *state;
            game.apply(&mut next, action);
            walk(game, bands, &next, by_key, by_known);
        }
    }

    let deals = if cfg!(debug_assertions) { 40 } else { 400 };
    let mut rng = Rng::new(8);
    for _ in 0..deals {
        let (hole, board) = random_deal(&mut rng);
        let start = game.deal(hole, board).unwrap();
        walk(&game, &bands, &start, &mut by_key, &mut by_known);
    }
    assert_eq!(by_key.len(), by_known.len());
    assert!(by_key.len() as u128 <= game.info_sets());
    // Enough deals to meet a good part of them.
    assert!(
        by_key.len() as u128 > game.info_sets() / 3,
        "{} of {}",
        by_key.len(),
        game.info_sets()
    );
    assert_eq!(
        game.info_sets(),
        (0..4)
            .map(|s| game.tree_size().decisions[s] * [6, 4, 3, 3][s])
            .sum::<u128>()
    );
}

#[test]
fn a_player_knows_only_their_own_cards_and_the_board_so_far() {
    let game = AbstractGame::new(GameConfig::new(3, Menus::minimal()), Lossless).unwrap();
    let deal = |hole: &str, board: &str| {
        let h: [Card; 4] = cards(hole);
        game.deal([[h[0], h[1]], [h[2], h[3]]], cards(board))
            .unwrap()
    };
    // The same hand and flop for the small blind; the other hand, the turn and the river
    // differ.
    let a = deal("As Kd 7c 7d", "2h 9s Tc 3d Qh");
    let b = deal("As Kd Jh 4c", "2h 9s Tc 8c 5s");
    // The same deal as `a` with the suits renamed and cards shuffled within the hand and
    // the flop.
    // (spades to hearts, diamonds to clubs, clubs to spades, hearts to diamonds)
    let c = deal("Kc Ah 7s 7c", "Ts 2d 9h 3c Qd");

    fn walk(
        game: &AbstractGame<Lossless>,
        a: &HandState,
        b: &HandState,
        c: &HandState,
        seen: &mut [[u32; 2]; 4],
    ) {
        let Node::Player(player) = game.node(a) else {
            return;
        };
        let street = game.replay(a).unwrap().street();
        seen[street.index()][player] += 1;
        let (ka, kb, kc) = (game.info_key(a), game.info_key(b), game.info_key(c));
        assert_eq!(ka, kc, "renamed suits are the same information");
        if player == 0 && street <= Street::Flop {
            assert_eq!(ka, kb, "the small blind cannot see what differs");
        } else {
            assert_ne!(ka, kb);
        }
        for action in actions(game, a) {
            let step = |s: &HandState| {
                let mut next = *s;
                game.apply(&mut next, action);
                next
            };
            walk(game, &step(a), &step(b), &step(c), seen);
        }
    }
    let mut seen = [[0; 2]; 4];
    walk(&game, &a, &b, &c, &mut seen);
    // Both players were met on every street.
    assert!(seen.iter().flatten().all(|&n| n > 0), "{seen:?}");
}

#[test]
fn sizes_and_limits() {
    for (config, buckets) in [
        (GameConfig::push_fold(10), [169, 0, 0, 0]),
        (
            GameConfig::new(2, Menus::minimal()),
            [169, 1_286_792, 55_190_538, 2_428_287_420],
        ),
        (
            GameConfig::new(100, Menus::standard()),
            [169, 1_286_792, 55_190_538, 2_428_287_420],
        ),
    ] {
        let size = config.tree_size().unwrap();
        let game = AbstractGame::new(config, Lossless).unwrap();
        assert_eq!(*game.tree_size(), size);
        assert_eq!(game.tree().len() as u128, size.decision_points());
        assert_eq!(
            game.tree().num_actions() as u128,
            size.actions.iter().sum::<u128>()
        );
        assert_eq!(game.buckets(), buckets);
        assert_eq!(game.info_sets(), size.info_sets(buckets));
        assert_eq!(game.regret_bytes(), size.regrets(buckets) * 8);
    }
    // The default game: the standard menus at 100 big blinds.
    let standard = GameConfig::new(100, Menus::default());
    let size = standard.tree_size().unwrap();
    assert_eq!(size.decisions, [88, 948, 6_012, 29_044]);
    assert_eq!(size.info_sets([169, 200, 200, 200]), 7_215_672);

    // A tree over the limit is refused, with its size; counting it still works.
    let refused = AbstractGame::with_limit(standard.clone(), Lossless, 1_000).unwrap_err();
    assert_eq!(
        refused,
        BuildError::TooLarge {
            decisions: 36_092,
            limit: 1_000
        }
    );
    assert!(refused.to_string().contains("36092 decision points"));
    assert!(AbstractGame::with_limit(standard, Lossless, 36_092).is_ok());

    // Settings that are not a game.
    let build = |config: GameConfig| AbstractGame::new(config, Lossless).map(|_| ());
    let mut short = GameConfig::new(100, Menus::minimal());
    short.stack = 50; // the small blind is the whole stack
    assert_eq!(build(short.clone()), Err(BuildError::NoDecision));
    assert_eq!(short.tree_size(), Err(BuildError::NoDecision));
    short.stack = 0;
    assert!(matches!(build(short), Err(BuildError::Rules(_))));
    let mut bad = GameConfig::new(100, Menus::minimal());
    bad.menus.streets[1][0][0] = Size::Pot(f64::NAN);
    assert!(matches!(build(bad), Err(BuildError::Menu(_))));
}

#[test]
fn off_menu_raises_map_to_their_neighbours() {
    let game = AbstractGame::new(GameConfig::new(100, Menus::standard()), Lossless).unwrap();
    let start = game
        .deal([cards("As Kd"), cards("7c 7d")], cards("2h 9s Tc 3d Qh"))
        .unwrap();
    // Open to 2.5 big blinds, call: the pot is 500 and the big blind may bet 165, 375,
    // 750 or 9,750 (0.33, 0.75, 1.5 and 19.5 times the pot).
    let flop = play(&game, &start, &[raise_to(250), CALL]);
    assert_eq!(
        actions(&game, &flop),
        [
            CALL,
            raise_to(165),
            raise_to(375),
            raise_to(750),
            raise_to(9_750)
        ]
    );
    let t = |chips| game.translate(&flop, chips).unwrap();
    // A bet on the menu is itself.
    for chips in [165, 375, 750, 9_750] {
        assert_eq!(
            t(chips),
            Translation {
                lower: raise_to(chips),
                upper: raise_to(chips),
                p_lower: 1.0
            }
        );
    }
    // Half the pot, between 0.33 and 0.75: (0.75 - 0.5)(1.33) / ((0.75 - 0.33)(1.5)).
    let half = t(250);
    assert_eq!((half.lower, half.upper), (raise_to(165), raise_to(375)));
    assert!((half.p_lower - 0.3325 / 0.63).abs() < 1e-12);
    // Twice the pot, between 1.5 and all in for 19.5: (17.5)(2.5) / ((18)(3)).
    let double = t(1_000);
    assert_eq!(
        (double.lower, double.upper),
        (raise_to(750), raise_to(9_750))
    );
    assert!((double.p_lower - 43.75 / 54.0).abs() < 1e-12);
    // A bigger bet is never read as a smaller size on average: the place on the menu,
    // counting a bet between two sizes by its probabilities, never goes down.
    let menu = [165, 375, 750, 9_750].map(raise_to);
    let place = |action| menu.iter().position(|&a| a == action).unwrap() as f64;
    let mut last = 0.0;
    for chips in 100..=9_750 {
        let m = t(chips);
        let at = place(m.lower) * m.p_lower + place(m.upper) * (1.0 - m.p_lower);
        assert!(at >= last, "{chips}: {at} after {last}");
        last = at;
    }
    assert_eq!(last, 3.0);
    // The minimum bet is below the menu: read as the smallest size.
    assert_eq!(t(100).upper, raise_to(165));
    assert_eq!(t(100).p_lower, 1.0);

    // Facing a bet of 375 the menu has a raise to 1,313 (0.75 of the pot after calling,
    // which is 1,250) and all in. A raise to 2,000 adds 1,625, or 1.3 pots.
    let facing = play(&game, &flop, &[raise_to(375)]);
    assert_eq!(
        actions(&game, &facing),
        [FOLD, CALL, raise_to(1_313), raise_to(9_750)]
    );
    let m = game.translate(&facing, 2_000).unwrap();
    assert_eq!((m.lower, m.upper), (raise_to(1_313), raise_to(9_750)));
    let expected = pseudo_harmonic(938.0 / 1_250.0, 9_375.0 / 1_250.0, 1.3);
    assert!((m.p_lower - expected).abs() < 1e-12);
    assert!((expected - 0.6991).abs() < 1e-4);

    // Nothing to map to when no raise is offered, or the hand is over or not dealt.
    let all_in = play(&game, &facing, &[raise_to(9_750)]);
    assert_eq!(actions(&game, &all_in), [FOLD, CALL]);
    assert_eq!(game.translate(&all_in, 9_750), None);
    assert_eq!(game.translate(&play(&game, &all_in, &[CALL]), 500), None);
    assert_eq!(game.translate(&game.root(), 500), None);

    // The same spot with every chip amount doubled maps the same way.
    let mut doubled = GameConfig::new(100, Menus::standard());
    (doubled.stack, doubled.small_blind, doubled.big_blind) = (20_000, 100, 200);
    let game2 = AbstractGame::new(doubled, Lossless).unwrap();
    let start2 = game2
        .deal([cards("As Kd"), cards("7c 7d")], cards("2h 9s Tc 3d Qh"))
        .unwrap();
    let flop2 = play(&game2, &start2, &[raise_to(500), CALL]);
    for chips in [120, 250, 333, 500, 1_000, 4_000] {
        let (one, two) = (t(chips), game2.translate(&flop2, 2 * chips).unwrap());
        assert!((one.p_lower - two.p_lower).abs() < 1e-12, "{chips}");
        let chips_of = |m: Translation| {
            (
                raise_amount(m.lower).unwrap(),
                raise_amount(m.upper).unwrap(),
            )
        };
        assert_eq!((2 * chips_of(one).0, 2 * chips_of(one).1), chips_of(two));
    }
}

#[test]
fn no_pruning_on_the_river() {
    let game = AbstractGame::new(GameConfig::new(20, Menus::minimal()), Lossless).unwrap();
    let start = game
        .deal([cards("As Kd"), cards("7c 7d")], cards("2h 9s Tc 3d Qh"))
        .unwrap();
    assert!(!game.prune_exempt(&start));
    let turn = play(&game, &start, &[CALL, CALL, CALL, CALL]);
    assert_eq!(game.replay(&turn).unwrap().street(), Street::Turn);
    assert!(!game.prune_exempt(&turn));
    let river = play(&game, &turn, &[CALL, CALL]);
    assert_eq!(game.replay(&river).unwrap().street(), Street::River);
    assert!(game.prune_exempt(&river));
}

/// Average result for player 0 over `hands` hands with each player following a policy.
fn sampled_value<B: Bucketer>(
    game: &AbstractGame<B>,
    policies: [&dyn Policy; 2],
    hands: usize,
    rng: &mut Rng,
) -> f64 {
    let mut total = 0.0;
    let mut scratch = Vec::new();
    let mut offered = Vec::new();
    let mut probs = Vec::new();
    for _ in 0..hands {
        let mut state = game.root();
        loop {
            match game.node(&state) {
                Node::Terminal => break,
                Node::Chance => {
                    let card = game.sample_chance(&state, rng, &mut scratch);
                    game.apply(&mut state, card);
                }
                Node::Player(player) => {
                    offered.clear();
                    game.legal_actions(&state, &mut offered);
                    probs.clear();
                    probs.resize(offered.len(), 0.0);
                    policies[player].action_probs(game.info_key(&state), &mut probs);
                    game.apply(&mut state, offered[rng.sample(&probs)]);
                }
            }
        }
        total += game.utility(&state, 0);
    }
    total / hands as f64
}

#[test]
fn mccfr_trains_a_game_with_every_street() {
    let config = GameConfig::new(6, Menus::minimal());
    let bands = EquityBands::new([12, 5, 5, 5]);
    let game = AbstractGame::new(config, bands).unwrap();
    assert_eq!(game.tree_size().last_street(), Some(Street::River));
    let iterations = if cfg!(debug_assertions) {
        3_000
    } else {
        30_000
    };

    let train = |seed: u64, iterations: u64| {
        let cfg = MccfrConfig::new(Sampling::External, seed)
            .linear(100, iterations / 2)
            .pruning(iterations / 2, -50.0, 0.9);
        let mut solver = Mccfr::new(game.clone(), cfg);
        solver.run(iterations);
        solver
    };
    // The same seed gives the same run, another seed a different one.
    assert_eq!(train(3, 1_000).regrets(), train(3, 1_000).regrets());
    assert_ne!(train(3, 1_000).regrets(), train(4, 1_000).regrets());
    let solver = train(3, iterations);
    // Nothing outside the counted game was reached.
    assert!(solver.info_sets() as u128 <= game.info_sets());
    assert!(solver.regrets().len() as u128 <= game.regret_bytes() / 8);
    assert!(solver.info_sets() as u128 > game.info_sets() / 2);
    println!(
        "{iterations} iterations: {} of {} information sets reached, {} nodes touched, {} actions pruned",
        solver.info_sets(),
        game.info_sets(),
        solver.nodes_touched(),
        solver.stats().pruned_actions
    );

    // The trained strategy beats one that picks actions at random, from both seats.
    if cfg!(debug_assertions) {
        return;
    }
    let trained = solver.average_policy();
    let mut rng = Rng::new(99);
    let hands = 20_000;
    let as_small_blind = sampled_value(&game, [&trained, &UniformPolicy], hands, &mut rng);
    let as_big_blind = -sampled_value(&game, [&UniformPolicy, &trained], hands, &mut rng);
    let mirror = sampled_value(&game, [&UniformPolicy, &UniformPolicy], hands, &mut rng);
    println!(
        "against random play: {as_small_blind:+.3} bb a hand as the small blind, {as_big_blind:+.3} as \
         the big blind (random against random: {mirror:+.3} for the small blind)"
    );
    assert!(as_small_blind > 0.3 && as_big_blind > 0.3);
}

/// The `cfr` crate shares the game between its threads, so the game has to be `Sync`
/// whenever its bucketer is.
#[test]
fn the_game_can_be_shared_between_threads() {
    fn shareable<T: Send + Sync>() {}
    shareable::<AbstractGame<Lossless>>();
    shareable::<AbstractGame<EquityBands>>();
    shareable::<AbstractGame<std::sync::Arc<EquityBands>>>();
    shareable::<HandState>();
}

#[test]
fn mccfr_trains_on_several_threads_with_integer_regrets() {
    let config = GameConfig::new(6, Menus::minimal());
    let game = AbstractGame::new(config, EquityBands::new([12, 5, 5, 5])).unwrap();
    let iterations = if cfg!(debug_assertions) {
        3_000
    } else {
        30_000
    };
    // One unit of regret is one chip. A run on several threads depends on timing, so
    // this checks what holds for every such run, not one exact result.
    let cfg = MccfrConfig::new(Sampling::External, 3)
        .threads(4)
        .compact(CHIPS_PER_BIG_BLIND as f64)
        .linear(100, iterations / 2);
    let mut solver = Mccfr::new(game.clone(), cfg);
    solver.run(iterations);
    assert_eq!(solver.iterations(), iterations);
    assert!(solver.info_sets() as u128 <= game.info_sets());
    assert!(solver.info_sets() as u128 > game.info_sets() / 2);
    assert_eq!(solver.memory().regret_bytes, 4 * solver.regrets().len());

    if cfg!(debug_assertions) {
        return;
    }
    let trained = solver.average_policy();
    let mut rng = Rng::new(99);
    let hands = 20_000;
    let as_small_blind = sampled_value(&game, [&trained, &UniformPolicy], hands, &mut rng);
    let as_big_blind = -sampled_value(&game, [&UniformPolicy, &trained], hands, &mut rng);
    println!(
        "4 threads, integer regrets, against random play: {as_small_blind:+.3} bb a hand as the \
         small blind, {as_big_blind:+.3} as the big blind"
    );
    assert!(as_small_blind > 0.2 && as_big_blind > 0.2);
}
