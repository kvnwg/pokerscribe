//! The blueprint in the real game: on the menu it plays exactly the stored strategy, from
//! either seat; off the menu every answer is legal and the same however it is asked; bets
//! between two menu sizes are read with the pseudo-harmonic mapping's probabilities, and
//! bets under the smallest size either as the smallest or, on request, as a check or call.

mod common;

use abstract_game::{pot_fraction, pseudo_harmonic, Bucketer, Menus, Next};
use blueprint::{Blueprint, SmallBets};
use cfr::Rng;
use common::{deal, play, real_hand, trained, Category};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::{Action, Card, State};

fn hand_of(cards: &[Card], player: usize) -> [Card; 2] {
    [cards[2 * player], cards[2 * player + 1]]
}

fn probs_of(bp: &Blueprint<Category>, state: &State, hole: [Card; 2]) -> ActionProbs {
    let mut out = ActionProbs::new();
    bp.action_probs(&PublicState::new(state), hole, &mut out);
    out
}

#[test]
fn on_the_menu_the_blueprint_plays_the_stored_strategy() {
    let solver = trained(20, Menus::standard(), 3_000);
    let bp = play(&solver);
    let game = bp.game();
    let tree = game.tree();
    let mut rng = Rng::new(11);
    let mut decisions = 0;
    for hand in 0..400 {
        let cards = deal(&mut rng, 9);
        let board: [Card; 5] = cards[4..9].try_into().unwrap();
        let button = hand % 2;
        let mut real = real_hand(2_000, button, hand_of(&cards, 0), hand_of(&cards, 1), board);
        let mut node = 0u32;
        loop {
            let at = tree.node(node);
            let player = at.player as usize;
            let seat = if player == 0 { button } else { 1 - button };
            assert_eq!(real.current_player(), Some(seat));
            assert_eq!(bp.decision_point(&PublicState::new(&real)), Some(node));
            let hole = hand_of(&cards, player);
            let bucket = game
                .bucketer()
                .bucket(hole, &board[..at.street.board_len()]);
            let want = bp.strategy(node, bucket);
            let got = probs_of(&bp, &real, hole);
            assert!((got.total() - 1.0).abs() < 1e-9);
            for (edge, &p) in tree.edges(node).iter().zip(&want) {
                assert!(
                    (got.prob(edge.action) - p).abs() < 1e-12,
                    "node {node}: {:?} has {} in the file, {} in play",
                    edge.action,
                    p,
                    got.prob(edge.action)
                );
            }
            decisions += 1;
            // Follow a random action of the tree in both games.
            let edges = tree.edges(node);
            let edge = edges[rng.below(edges.len())];
            real.apply(edge.action).unwrap();
            match edge.next() {
                Next::Decision(next) => node = next,
                Next::End(_) => {
                    assert!(real.is_terminal() || real.current_player().is_none());
                    break;
                }
            }
        }
    }
    assert!(decisions > 1_000, "{decisions}");
    assert_eq!(bp.off_tree_share(), 0.0);
}

/// A random legal action, with raises of any size: the minimum, all in, or anything between.
fn random_action(state: &State, rng: &mut Rng) -> Action {
    let legal = state.legal_actions();
    let mut options = Vec::new();
    if legal.fold {
        options.push(Action::Fold);
    }
    if legal.check {
        options.push(Action::Check);
    }
    if legal.call.is_some() {
        options.push(Action::Call);
    }
    if let Some(r) = legal.raise {
        let to = match rng.below(4) {
            0 => r.min_to,
            1 => r.max_to,
            _ => r.min_to + rng.below((r.max_to - r.min_to + 1) as usize) as u32,
        };
        options.push(Action::RaiseTo(to));
        options.push(Action::RaiseTo(to));
    }
    options[rng.below(options.len())]
}

#[test]
fn off_the_menu_every_answer_is_legal_and_consistent() {
    let tables = [
        (20u32, Menus::standard()),
        (8, Menus::minimal()),
        (30, Menus::small()),
    ];
    for ((stack, menus), small_bets) in tables.into_iter().flat_map(|t| {
        [
            (t.clone(), SmallBets::Smallest),
            (t, SmallBets::CheckOrCall),
        ]
    }) {
        let solver = trained(stack, menus, 2_000);
        let bp = play(&solver).with_small_bets(small_bets);
        let mut rng = Rng::new(stack as u64);
        let mut checked = 0;
        for hand in 0..300 {
            let cards = deal(&mut rng, 9);
            let board: [Card; 5] = cards[4..9].try_into().unwrap();
            let mut real = real_hand(
                stack * 100,
                hand % 2,
                hand_of(&cards, 0),
                hand_of(&cards, 1),
                board,
            );
            while let Some(seat) = real.current_player() {
                let public = PublicState::new(&real);
                let legal = real.legal_actions();
                let hole = real.hole_cards(seat);
                let got = probs_of(&bp, &real, hole);
                assert!((got.total() - 1.0).abs() < 1e-9, "{:?}", got);
                for (i, &(a, p)) in got.as_slice().iter().enumerate() {
                    assert!(legal.allows(a), "{a:?} is not legal: {public:?}");
                    assert!(p > 0.0);
                    assert!(
                        got.as_slice()[i + 1..].iter().all(|(b, _)| *b != a),
                        "{a:?} twice"
                    );
                }
                // The same answers again, and from the range interface for other hands.
                assert_eq!(probs_of(&bp, &real, hole), got);
                let mut hands = vec![hole];
                while hands.len() < 6 {
                    let h = deal(&mut rng, 2);
                    if !h.iter().any(|c| real.board().contains(c)) {
                        hands.push([h[0], h[1]]);
                    }
                }
                let mut asked: Vec<Action> = got.as_slice().iter().map(|x| x.0).collect();
                if let Some(r) = legal.raise {
                    asked.push(Action::RaiseTo(r.min_to));
                }
                for action in asked {
                    let mut range = vec![0.0; hands.len()];
                    bp.action_prob_for_range(&public, action, &hands, &mut range);
                    for (h, &p) in hands.iter().zip(&range) {
                        let one = probs_of(&bp, &real, *h).prob(action);
                        assert!((one - p).abs() < 1e-12, "{action:?}: {one} against {p}");
                    }
                }
                checked += 1;
                let action = random_action(&real, &mut rng);
                real.apply(action).unwrap();
            }
        }
        assert!(checked > 600, "{checked}");
    }
}

#[test]
fn bets_between_two_menu_sizes_follow_the_pseudo_harmonic_mapping() {
    // Default menu, 20 big blinds: the small blind may open to 200, 250, 300 or all in.
    let solver = trained(20, Menus::standard(), 500);
    let mut bp = play(&solver);
    let tree = bp.game().tree().clone();
    let open = |to| tree.find(&[Action::RaiseTo(to)]).unwrap();
    let (at_250, at_300, all_in) = (open(250), open(300), open(2_000));
    let cards = deal(&mut Rng::new(3), 9);
    let board: [Card; 5] = cards[4..9].try_into().unwrap();
    let after = |to| {
        let mut s = real_hand(2_000, 0, hand_of(&cards, 0), hand_of(&cards, 1), board);
        s.apply(Action::RaiseTo(to)).unwrap();
        s
    };
    // On the menu: always the same size. All in: always all in.
    for seed in 0..200 {
        bp.set_translation_seed(seed);
        assert_eq!(
            bp.decision_point(&PublicState::new(&after(250))),
            Some(at_250)
        );
        assert_eq!(
            bp.decision_point(&PublicState::new(&after(300))),
            Some(at_300)
        );
        assert_eq!(
            bp.decision_point(&PublicState::new(&after(2_000))),
            Some(all_in)
        );
    }
    // An open to 275 is 0.875 of the pot after calling: between 250 (0.75) and 300 (1.0).
    let p = pseudo_harmonic(0.75, 1.0, 0.875);
    assert!((p - 7.0 / 15.0).abs() < 1e-12);
    let state = after(275);
    let n = 4_000;
    let mut lower = 0;
    for seed in 0..n {
        bp.set_translation_seed(seed);
        let public = PublicState::new(&state);
        let read = bp.decision_point(&public);
        assert_eq!(
            bp.decision_point(&public),
            read,
            "the same state, the same reading"
        );
        match read {
            Some(x) if x == at_250 => lower += 1,
            Some(x) if x == at_300 => {}
            other => panic!("read as {other:?}"),
        }
    }
    let share = lower as f64 / n as f64;
    let se = (p * (1.0 - p) / n as f64).sqrt();
    assert!((share - p).abs() < 4.0 * se, "{share} against {p} ± {se}");

    // A bet under the smallest size is read as the smallest, over the largest as all in.
    assert_eq!(
        bp.decision_point(&PublicState::new(&after(200))),
        Some(open(200))
    );
    assert_eq!(
        bp.decision_point(&PublicState::new(&after(1_999))),
        Some(all_in)
    );
}

#[test]
fn when_the_abstract_hand_is_over_the_blueprint_checks_or_calls() {
    let solver = trained(30, Menus::standard(), 500);
    let bp = play(&solver);
    let cards = deal(&mut Rng::new(5), 9);
    let board: [Card; 5] = cards[4..9].try_into().unwrap();
    let mut s = real_hand(3_000, 0, hand_of(&cards, 0), hand_of(&cards, 1), board);
    // Open 250, 3-bet 750, 4-bet 1,650, then a 5-bet to 2,600 that is not all in. The
    // menu only has all in there, so it is read as all in; the call then ends the abstract
    // hand, while the real one goes to the flop with 400 chips behind.
    for a in [
        Action::RaiseTo(250),
        Action::RaiseTo(750),
        Action::RaiseTo(1_650),
        Action::RaiseTo(2_600),
    ] {
        assert!(bp.decision_point(&PublicState::new(&s)).is_some());
        s.apply(a).unwrap();
    }
    assert!(bp.decision_point(&PublicState::new(&s)).is_some());
    s.apply(Action::Call).unwrap();
    assert_eq!(
        s.current_player(),
        Some(1),
        "the big blind acts first on the flop"
    );
    assert_eq!(bp.decision_point(&PublicState::new(&s)), None);
    bp.reset_counters();
    let got = probs_of(&bp, &s, s.hole_cards(1));
    assert_eq!(got.as_slice(), &[(Action::Check, 1.0)]);
    assert_eq!(bp.off_tree_share(), 1.0);
    s.apply(Action::RaiseTo(100)).unwrap();
    let got = probs_of(&bp, &s, s.hole_cards(0));
    assert_eq!(got.as_slice(), &[(Action::Call, 1.0)]);
}

#[test]
fn small_bets_can_be_read_as_a_check_or_call() {
    // Default menu, 20 big blinds. The small blind opens to 250 and the big blind calls:
    // 500 in the pot, and the smallest flop bet on the menu is a third of it.
    let solver = trained(20, Menus::standard(), 500);
    let bp = play(&solver);
    let tree = bp.game().tree().clone();
    let at = |line: &[Action]| tree.find(line).unwrap();
    let flop = [Action::RaiseTo(250), Action::Call];
    let smallest = tree
        .edges(at(&flop))
        .iter()
        .find_map(|e| match e.action {
            Action::RaiseTo(x) => Some(x),
            _ => None,
        })
        .unwrap();
    let cards = deal(&mut Rng::new(9), 9);
    let board: [Card; 5] = cards[4..9].try_into().unwrap();
    let mut s = real_hand(2_000, 0, hand_of(&cards, 0), hand_of(&cards, 1), board);
    for a in flop {
        s.apply(a).unwrap();
    }
    let size = pot_fraction(&s, smallest);
    let x = pot_fraction(&s, 100);
    assert!(x < size);
    let p = pseudo_harmonic(0.0, size, x);
    let line = |rest: &[Action]| [&flop[..], rest].concat();

    // The big blind bets 100 (the minimum), a fifth of the pot. By default it is the smallest bet.
    let mut lead = s.clone();
    lead.apply(Action::RaiseTo(100)).unwrap();
    let bet = at(&line(&[Action::RaiseTo(smallest)]));
    let checked = at(&line(&[Action::Check]));
    for seed in 0..50 {
        let bp = play(&solver).with_translation_seed(seed);
        assert_eq!(bp.decision_point(&PublicState::new(&lead)), Some(bet));
    }
    // Read as a check or call: a check with the mapping's probability, else the smallest.
    let n = 4_000;
    let mut as_check = 0;
    for seed in 0..n {
        let bp = play(&solver)
            .with_translation_seed(seed)
            .with_small_bets(SmallBets::CheckOrCall);
        match bp.decision_point(&PublicState::new(&lead)) {
            Some(x) if x == checked => {
                as_check += 1;
                // The button answers a real bet: call or raise, never check or fold.
                let got = probs_of(&bp, &lead, lead.hole_cards(0));
                let legal = lead.legal_actions();
                for &(a, _) in got.as_slice() {
                    assert!(matches!(a, Action::Call | Action::RaiseTo(_)), "{a:?}");
                    if let Action::RaiseTo(to) = a {
                        let r = legal.raise.unwrap();
                        assert!(r.min_to <= to && to <= r.max_to);
                    }
                }
                // A call closes the street: the turn, as after two checks.
                let mut called = lead.clone();
                called.apply(Action::Call).unwrap();
                let turn = at(&line(&[Action::Check, Action::Check]));
                assert_eq!(bp.decision_point(&PublicState::new(&called)), Some(turn));
            }
            Some(x) if x == bet => {}
            other => panic!("read as {other:?}"),
        }
    }
    let share = as_check as f64 / n as f64;
    let se = (p * (1.0 - p) / n as f64).sqrt();
    assert!((share - p).abs() < 4.0 * se, "{share} against {p} ± {se}");

    // The big blind checks and the button bets 100. Read as a check, the abstract flop is
    // over, but the real big blind faces a bet: it calls, then the turn is the turn after
    // two checks.
    let mut behind = s.clone();
    behind.apply(Action::Check).unwrap();
    behind.apply(Action::RaiseTo(100)).unwrap();
    let mut seen = false;
    for seed in 0..200 {
        let bp = play(&solver)
            .with_translation_seed(seed)
            .with_small_bets(SmallBets::CheckOrCall);
        let public = PublicState::new(&behind);
        if bp.decision_point(&public).is_some() {
            assert_eq!(
                bp.decision_point(&public),
                Some(at(&line(&[Action::Check, Action::RaiseTo(smallest)])))
            );
            continue;
        }
        seen = true;
        let got = probs_of(&bp, &behind, behind.hole_cards(1));
        assert_eq!(got.as_slice(), &[(Action::Call, 1.0)]);
        let mut range = [0.0; 3];
        let hands = [
            hand_of(&cards, 1),
            [cards[0], cards[2]],
            [cards[1], cards[3]],
        ];
        bp.action_prob_for_range(&public, Action::Call, &hands, &mut range);
        assert_eq!(range, [1.0; 3]);
        let mut called = behind.clone();
        called.apply(Action::Call).unwrap();
        let turn = at(&line(&[Action::Check, Action::Check]));
        assert_eq!(bp.decision_point(&PublicState::new(&called)), Some(turn));
        // A raise in answer instead can't be followed: check or call from there on.
        let mut raised = behind.clone();
        raised.apply(Action::RaiseTo(300)).unwrap();
        assert_eq!(bp.decision_point(&PublicState::new(&raised)), None);
    }
    assert!(seen, "some seed reads the bet as a check");
}

#[test]
fn a_range_update_reads_an_off_menu_raise_as_the_blueprint_does() {
    // 20 big blinds, default menu: the small blind may open to 200, 250, 300 or all in.
    let solver = trained(20, Menus::standard(), 500);
    let mut bp = play(&solver);
    let tree = bp.game().tree().clone();
    let open = |to| tree.find(&[Action::RaiseTo(to)]).unwrap();
    let (at_250, at_300) = (open(250), open(300));
    let mut rng = Rng::new(5);
    let cards = deal(&mut rng, 9);
    let board: [Card; 5] = cards[4..9].try_into().unwrap();
    let start = real_hand(2_000, 0, hand_of(&cards, 0), hand_of(&cards, 1), board);
    let public = PublicState::new(&start);
    let hands: Vec<[Card; 2]> = (0..40)
        .map(|_| {
            let c = deal(&mut rng, 2);
            [c[0], c[1]]
        })
        .collect();
    let exact = |bp: &Blueprint<Category>, to| {
        let mut out = vec![0.0; hands.len()];
        bp.action_prob_for_range(&public, Action::RaiseTo(to), &hands, &mut out);
        out
    };
    let read = |bp: &Blueprint<Category>, to| {
        let mut out = vec![0.0; hands.len()];
        bp.read_action_prob_for_range(&public, Action::RaiseTo(to), &hands, &mut out);
        out
    };
    // On the menu the two readings agree.
    for to in [200, 250, 300, 2_000] {
        assert_eq!(exact(&bp, to), read(&bp, to));
    }
    // Off the menu the blueprint never makes the raise itself, and the update reads it as
    // the menu raise the blueprint maps it to once it is in the history.
    let mut lower = 0;
    for seed in 0..60 {
        bp.set_translation_seed(seed);
        assert!(exact(&bp, 275).iter().all(|&p| p == 0.0));
        let mut after = start.clone();
        after.apply(Action::RaiseTo(275)).unwrap();
        let menu = match bp.decision_point(&PublicState::new(&after)) {
            Some(x) if x == at_250 => {
                lower += 1;
                250
            }
            Some(x) if x == at_300 => 300,
            other => panic!("read as {other:?}"),
        };
        assert_eq!(read(&bp, 275), exact(&bp, menu), "seed {seed}");
    }
    assert!(
        lower > 0 && lower < 60,
        "both readings happen: {lower} of 60"
    );
}
