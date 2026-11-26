//! Every action the abstract game offers is legal in `nlhe`, and the hand it plays is the
//! real one.
//!
//! The checks keep their own `nlhe::State` next to the game's and ask it, not the game,
//! whether each offered action is legal.

use abstract_game::{
    raise_amount, AbstractGame, Bucketer, EquityBands, EvalRanker, GameConfig, HandState, Menus,
    Size, CALL, FOLD,
};
use cfr::{Game, Node, Rng};
use nlhe::{Action, BruteForceRanker, Config, Deal, State, Street};

fn bands() -> EquityBands {
    EquityBands::new([8, 3, 3, 3])
}

fn config(stack: u32, small_blind: u32, big_blind: u32, menus: Menus) -> GameConfig {
    GameConfig {
        stack,
        small_blind,
        big_blind,
        menus,
    }
}

/// A menu made to hit every corner: tiny and huge sizes, sizes that collide, multiples
/// barely above 1, and a street with no bets.
fn awkward() -> Menus {
    use Size::*;
    Menus {
        streets: [
            vec![
                vec![
                    Times(1.01),
                    Times(2.0),
                    Times(2.01),
                    Pot(0.01),
                    Pot(7.0),
                    Times(50.0),
                ],
                vec![Pot(0.3), Times(1.5), AllIn],
                vec![Times(1.2)],
            ],
            vec![
                vec![Pot(0.01), Pot(0.5), Pot(0.5), Pot(3.0)],
                vec![Pot(0.1), Times(2.0)],
                vec![Times(1.2)],
            ],
            vec![],
            vec![vec![AllIn, Pot(1.0)], vec![]],
        ],
        limp: true,
    }
}

/// The settings whose whole betting tree is walked.
fn settings() -> Vec<(&'static str, GameConfig)> {
    let mut no_limp = Menus::small();
    no_limp.limp = false;
    vec![
        ("push-or-fold, 10 bb", GameConfig::push_fold(10)),
        (
            "push-or-fold, 1.5 bb",
            config(150, 50, 100, Menus::push_fold()),
        ),
        ("minimal, 2 bb", GameConfig::new(2, Menus::minimal())),
        ("minimal, 25 bb", GameConfig::new(25, Menus::minimal())),
        ("minimal, 200 bb", GameConfig::new(200, Menus::minimal())),
        ("small, 12 bb", GameConfig::new(12, Menus::small())),
        ("small, 100 bb", GameConfig::new(100, Menus::small())),
        (
            "small without the limp, 30 bb",
            GameConfig::new(30, no_limp),
        ),
        ("standard, 8 bb", GameConfig::new(8, Menus::standard())),
        ("standard, 100 bb", GameConfig::new(100, Menus::standard())),
        ("wide, 6 bb", GameConfig::new(6, Menus::wide())),
        (
            "standard, blinds 1 and 2, 37 chips",
            config(37, 1, 2, Menus::standard()),
        ),
        (
            "standard, blinds 5 and 10, 195 chips",
            config(195, 5, 10, Menus::standard()),
        ),
        (
            "wide, blinds 1 and 2, 23 chips",
            config(23, 1, 2, Menus::wide()),
        ),
        (
            "small, blinds 2 and 2, 31 chips",
            config(31, 2, 2, Menus::small()),
        ),
        (
            "small, blinds 3 and 7, 64 chips",
            config(64, 3, 7, Menus::small()),
        ),
        ("awkward, 40 bb", GameConfig::new(40, awkward())),
        (
            "awkward, blinds 1 and 3, 50 chips",
            config(50, 1, 3, awkward()),
        ),
    ]
}

/// The real action an abstract action stands for at `hand`.
fn real_action(hand: &State, action: cfr::Action) -> Action {
    match action {
        FOLD => Action::Fold,
        CALL if hand.legal_actions().check => Action::Check,
        CALL => Action::Call,
        raise => Action::RaiseTo(raise_amount(raise).unwrap()),
    }
}

/// Checks one decision: what the game offers there against our own copy of the hand.
/// Returns the offered actions.
fn check_offer<B: Bucketer>(
    game: &AbstractGame<B>,
    state: &HandState,
    hand: &State,
    name: &str,
) -> Vec<cfr::Action> {
    let Node::Player(player) = game.node(state) else {
        panic!("{name}: not a decision");
    };
    assert_eq!(hand.current_player(), Some(player), "{name}: whose turn");
    // The game's position, replayed in the real game, is our own copy of the hand.
    assert_eq!(game.replay(state).as_ref(), Some(hand), "{name}");
    let mut offered = Vec::new();
    game.legal_actions(state, &mut offered);
    assert!(!offered.is_empty(), "{name}: nothing to do");
    let legal = hand.legal_actions();
    for &action in &offered {
        let real = real_action(hand, action);
        assert!(
            legal.allows(real),
            "{name}: {real} is offered but not legal after {:?}",
            hand.history()
        );
    }
    // Fold first, then check or call, then raises from small to large, none twice.
    assert!(
        offered.windows(2).all(|w| w[0] < w[1]),
        "{name}: {offered:?}"
    );
    // Folding is never offered when checking is free.
    if legal.check {
        assert!(
            !offered.contains(&FOLD),
            "{name}: fold offered when checking is free"
        );
        assert!(offered.contains(&CALL), "{name}: no check");
    }
    offered
}

/// Walks every line of play from `state`. Returns the number of decisions met.
fn walk<B: Bucketer>(game: &AbstractGame<B>, state: &HandState, hand: &State, name: &str) -> usize {
    if game.node(state) == Node::Terminal {
        assert!(hand.is_terminal(), "{name}: the game ended early");
        return 0;
    }
    assert!(!hand.is_terminal(), "{name}: the real hand is over");
    let mut decisions = 1;
    for action in check_offer(game, state, hand, name) {
        let mut next_hand = hand.clone();
        next_hand
            .apply(real_action(hand, action))
            .unwrap_or_else(|e| panic!("{name}: {e}"));
        let mut next = *state;
        game.apply(&mut next, action);
        decisions += walk(game, &next, &next_hand, name);
    }
    decisions
}

#[test]
fn every_offered_action_is_legal_in_nlhe() {
    let hole = [[50, 44], [3, 21]];
    let board = [0, 9, 18, 31, 47];
    let mut total = 0;
    for (name, config) in settings() {
        let rules = Config::new(
            &[config.stack, config.stack],
            config.small_blind,
            config.big_blind,
            0,
            0,
        )
        .unwrap();
        let hand = State::new(&rules, Deal::new(&hole, board).unwrap()).unwrap();
        let game = AbstractGame::new(config, bands()).unwrap();
        let start = game.deal(hole, board).unwrap();
        let decisions = walk(&game, &start, &hand, name);
        // The walk met every decision point of the tree, and the count agrees.
        assert_eq!(decisions, game.tree().len(), "{name}");
        assert_eq!(
            decisions as u128,
            game.tree_size().decision_points(),
            "{name}"
        );
        println!("{name}: {decisions} decision points");
        total += decisions;
    }
    assert!(total > 50_000, "the walk covers {total} decision points");
}

/// Plays hands from the chance node on with random cards and random abstract actions, on
/// games too big to walk, checking every offer on the way and the result at the end.
#[test]
fn random_hands_are_legal_and_pay_what_nlhe_pays() {
    let games = [
        ("standard, 100 bb", GameConfig::new(100, Menus::standard())),
        ("standard, 200 bb", GameConfig::new(200, Menus::standard())),
        ("wide, 30 bb", GameConfig::new(30, Menus::wide())),
        (
            "wide, blinds 1 and 2, 301 chips",
            config(301, 1, 2, Menus::wide()),
        ),
        ("awkward, 150 bb", GameConfig::new(150, awkward())),
    ];
    let hands = if cfg!(debug_assertions) { 600 } else { 6_000 };
    let mut rng = Rng::new(77);
    for (name, config) in games {
        let rules = Config::new(
            &[config.stack, config.stack],
            config.small_blind,
            config.big_blind,
            0,
            0,
        )
        .unwrap();
        let big_blind = config.big_blind as f64;
        let game = AbstractGame::new(config, bands()).unwrap();
        let mut scratch = Vec::new();
        let (mut showdowns, mut rivers, mut raises) = (0, 0, 0);
        for _ in 0..hands {
            // Chance deals the nine cards.
            let mut state = game.root();
            let mut dealt = Vec::new();
            while game.node(&state) == Node::Chance {
                let card = game.sample_chance(&state, &mut rng, &mut scratch);
                assert!(!dealt.contains(&card), "{name}: a card dealt twice");
                dealt.push(card);
                game.apply(&mut state, card);
            }
            assert_eq!(dealt.len(), 9);
            let c: Vec<u8> = dealt.iter().map(|&c| c as u8).collect();
            let deal = Deal::new(
                &[[c[0], c[1]], [c[2], c[3]]],
                [c[4], c[5], c[6], c[7], c[8]],
            );
            let mut hand = State::new(&rules, deal.unwrap()).unwrap();
            assert_eq!(state.cards(), c);
            assert_eq!(game.replay(&state).unwrap(), hand);

            while game.node(&state) != Node::Terminal {
                let offered = check_offer(&game, &state, &hand, name);
                // Lean away from folding so hands reach the later streets.
                let mut action = offered[rng.below(offered.len())];
                if action == FOLD && rng.below(4) != 0 {
                    action = offered[1 + rng.below(offered.len() - 1)];
                }
                raises += raise_amount(action).is_some() as u32;
                hand.apply(real_action(&hand, action)).unwrap();
                game.apply(&mut state, action);
            }
            assert!(hand.is_terminal());
            assert_eq!(game.replay(&state).unwrap(), hand);
            rivers += (hand.street() == Street::River) as u32;
            showdowns += (!hand.is_folded(0) && !hand.is_folded(1)) as u32;
            // The payoffs are nlhe's, with a different ranker doing the showdown, in big
            // blinds; what one player wins the other loses.
            let paid = hand.payouts(&BruteForceRanker).unwrap();
            assert_eq!(paid, hand.payouts(&EvalRanker).unwrap(), "{name}");
            let (small, big) = (game.utility(&state, 0), game.utility(&state, 1));
            assert_eq!(small, paid[0] as f64 / big_blind, "{name}");
            assert_eq!(big, paid[1] as f64 / big_blind, "{name}");
            assert_eq!(small + big, 0.0, "{name}");
        }
        println!("{name}: {hands} hands, {showdowns} showdowns, {rivers} reached the river, {raises} raises");
        assert!(
            showdowns > hands / 10 && raises > hands,
            "{name}: the hands are too tame"
        );
    }
}

/// The menus at states the abstract game never reaches: real hands played with any legal
/// bet sizes. Whatever the menus offer there must be legal too, because that is where an
/// opponent's off-menu bets lead.
#[test]
fn menus_are_legal_at_any_real_state() {
    let menus = [
        Menus::push_fold(),
        Menus::minimal(),
        Menus::small(),
        Menus::standard(),
        Menus::wide(),
        awkward(),
    ];
    let tables = [
        (10_000, 50, 100),
        (731, 5, 10),
        (40, 1, 2),
        (9, 1, 2),
        (64, 3, 7),
    ];
    let hands = if cfg!(debug_assertions) { 300 } else { 3_000 };
    let mut rng = Rng::new(5);
    let mut offered = Vec::new();
    let mut checked = 0u64;
    for (stack, small_blind, big_blind) in tables {
        let rules = Config::new(&[stack, stack], small_blind, big_blind, 0, 0).unwrap();
        for seed in 0..hands {
            let mut hand = State::from_seed(&rules, seed);
            while !hand.is_terminal() {
                let legal = hand.legal_actions();
                for menu in &menus {
                    offered.clear();
                    menu.actions(&hand, &mut offered);
                    assert!(!offered.is_empty());
                    for &action in &offered {
                        assert!(legal.allows(action), "{action} after {:?}", hand.history());
                        checked += 1;
                    }
                    for (i, action) in offered.iter().enumerate() {
                        assert!(!offered[..i].contains(action), "{action} offered twice");
                    }
                }
                // Any legal action of the real game, raises of any size included.
                let action = match (rng.below(10), legal.raise) {
                    (0, _) if legal.fold => Action::Fold,
                    (1..=5, Some(range)) => {
                        let span = (range.max_to - range.min_to) as usize;
                        // Mostly small raises, so that hands last.
                        let step = if rng.below(4) == 0 {
                            span
                        } else {
                            span.min(3 * big_blind as usize)
                        };
                        Action::RaiseTo(range.min_to + rng.below(step + 1) as u32)
                    }
                    _ if legal.check => Action::Check,
                    _ => Action::Call,
                };
                hand.apply(action).unwrap();
            }
        }
    }
    println!("{checked} offered actions checked");
    assert!(checked > 100_000);
}
