//! LBR's two building blocks, checked by hand: the range it tracks with Bayes' rule, and the
//! value it gives each action (the paper's Figure 1).

use lbr::{
    card_mask, combo_cards, win_probability, ActionProbs, AlwaysCall, AlwaysFold, BetSize, Lbr,
    LbrConfig, PublicState, Range, Strategy, UniformRandom,
};
use nlhe::{parse_card, Action, Card, Config, Deal, State, Street};

fn cards(s: &str) -> Vec<Card> {
    s.split_whitespace()
        .map(|c| parse_card(c).unwrap_or_else(|| panic!("bad card {c}")))
        .collect()
}

fn hand(s: &str) -> [Card; 2] {
    cards(s).try_into().expect("two cards")
}

/// Heads-up with blinds 1 and 2 and the button on seat `button`.
fn deal(stacks: [u32; 2], button: usize, seat0: &str, seat1: &str, board: &str) -> State {
    let config = Config::new(&stacks, 1, 2, 0, button).unwrap();
    let board: [Card; 5] = cards(board).try_into().expect("five cards");
    State::new(
        &config,
        Deal::new(&[hand(seat0), hand(seat1)], board).unwrap(),
    )
    .unwrap()
}

/// Raises to 6 first in with aces always and with kings half the time; otherwise checks or
/// calls. It only looks at its own cards, as a real strategy would.
struct PremiumRaiser;

impl Strategy for PremiumRaiser {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        let legal = public.legal_actions();
        let passive = if legal.check {
            Action::Check
        } else {
            Action::Call
        };
        let pair_of = |rank: u8| hole[0] / 4 == rank && hole[1] / 4 == rank;
        let raise = if !public.history().is_empty() {
            0.0
        } else if pair_of(12) {
            1.0
        } else if pair_of(11) {
            0.5
        } else {
            0.0
        };
        if raise > 0.0 {
            out.push(Action::RaiseTo(6), raise);
        }
        if raise < 1.0 {
            out.push(passive, 1.0 - raise);
        }
    }
}

#[test]
fn bayes_rule_by_hand() {
    let config = LbrConfig::default();
    // LBR is seat 0 in the big blind; the opponent on the button acts first.
    let state = deal([400, 400], 1, "7c 2d", "As Ah", "Kh Th 7s 4c 2s");
    let aces = hand("Ac Ad");
    let kings = hand("Kc Kd");
    let other = hand("9c 8c");

    let mut lbr = Lbr::new(&config, &PremiumRaiser, 0, hand("7c 2d"), 0);
    // Before anything happens: 1,225 hands without our two cards, equally likely.
    assert_eq!(lbr.range().live().count(), 1225);
    assert!((lbr.range().weight(other) - 1.0 / 1225.0).abs() < 1e-15);
    assert_eq!(lbr.range().weight(hand("7c Ah")), 0.0);

    // A raise: 6 combinations of aces at 1 and 6 of kings at 1/2, so 9 in all.
    let mut after_raise = lbr.clone();
    after_raise.observe(&state, Action::RaiseTo(6));
    assert!((after_raise.range().weight(aces) - 1.0 / 9.0).abs() < 1e-12);
    assert!((after_raise.range().weight(kings) - 1.0 / 18.0).abs() < 1e-12);
    assert_eq!(after_raise.range().weight(other), 0.0);
    assert!((after_raise.range().total() - 1.0).abs() < 1e-12);

    // A call: no aces, kings at 1/2, the other 1,213 hands at 1.
    lbr.observe(&state, Action::Call);
    assert_eq!(lbr.range().weight(aces), 0.0);
    assert!((lbr.range().weight(kings) - 0.5 / 1216.0).abs() < 1e-12);
    assert!((lbr.range().weight(other) - 1.0 / 1216.0).abs() < 1e-12);

    // Our own cards count: holding an ace and a king leaves 3 combinations of each.
    let state = deal([400, 400], 1, "As Kd", "Ac Ah", "Kh Th 7s 4c 2s");
    let mut lbr = Lbr::new(&config, &PremiumRaiser, 0, hand("As Kd"), 0);
    lbr.observe(&state, Action::RaiseTo(6));
    assert!((lbr.range().weight(hand("Ac Ah")) - 2.0 / 9.0).abs() < 1e-12);
    assert!((lbr.range().weight(hand("Kc Kh")) - 1.0 / 9.0).abs() < 1e-12);
    assert_eq!(lbr.range().weight(hand("As Ac")), 0.0);
}

#[test]
fn the_board_removes_hands_and_an_impossible_action_changes_nothing() {
    let config = LbrConfig::fcpa(Street::Preflop).with_sampled_preflop(50);
    let mut state = deal([400, 400], 1, "7c 2d", "Kc Kd", "Kh Th 7s 4c 2s");
    let mut lbr = Lbr::new(&config, &PremiumRaiser, 0, hand("7c 2d"), 0);

    // The strategy never raises to 10, with any hand: the range stays as it was.
    let before = lbr.range().clone();
    lbr.observe(&state, Action::RaiseTo(10));
    assert_eq!(*lbr.range(), before);

    lbr.observe(&state, Action::Call);
    state.apply(Action::Call).unwrap();
    state.apply(Action::Check).unwrap();
    // The flop Kh Th 7s is out: LBR, first to act, drops every hand holding one of them.
    assert_eq!(state.street(), Street::Flop);
    lbr.act(&state);
    let flop = card_mask(&cards("Kh Th 7s"));
    for (i, _) in lbr.range().live() {
        assert_eq!(card_mask(&combo_cards(i)) & flop, 0);
    }
    assert_eq!(lbr.range().weight(hand("Kh Kd")), 0.0);
    // Kings without the king of hearts: 3 combinations, still at half weight.
    assert!(lbr.range().weight(hand("Kc Kd")) > 0.0);
    assert!(
        (lbr.range().weight(hand("Kc Kd")) / lbr.range().weight(hand("9c 8c")) - 0.5).abs() < 1e-12
    );
    assert_eq!(lbr.range().live().count(), 47 * 46 / 2 - 6);
}

/// To the river with `raise_to` each before the flop and checks after, big blind to act.
fn to_river(state: &mut State, raise_to: u32) {
    for action in [
        Action::RaiseTo(raise_to),
        Action::Call,
        Action::Check,
        Action::Check,
        Action::Check,
        Action::Check,
    ] {
        state.apply(action).unwrap();
    }
    assert_eq!(state.street(), Street::River);
}

#[test]
fn action_values_are_the_papers_formula() {
    // LBR on the button (seat 0), 200 in the pot and 300 behind on the river, checked to.
    // Pot-sized bet: 200. All in: 300.
    let board = "Kh Th 7s 4c 2s";
    let config = LbrConfig::fcpa(Street::River);
    for lbr_hand in ["Ks Qd", "9c 8c", "Ah Td", "7c 7d", "5h 3h"] {
        let mut state = deal([400, 400], 0, lbr_hand, "Jc Jd", board);
        to_river(&mut state, 100);
        let pot = 200.0;
        let mut range = Range::uniform();
        range.remove_cards(card_mask(&hand(lbr_hand)));
        let wp = win_probability(hand(lbr_hand), &cards(board), &range).unwrap();

        // (strategy, how often it folds to a bet that is not all in, and to an all-in)
        let opponents: [(&dyn Strategy, f64, f64); 3] = [
            (&AlwaysCall, 0.0, 0.0),
            (&AlwaysFold, 1.0, 1.0),
            (&UniformRandom::Kinds, 1.0 / 3.0, 0.5),
        ];
        for (opponent, fold_to_bet, fold_to_all_in) in opponents {
            let mut lbr = Lbr::new(&config, opponent, 0, hand(lbr_hand), 0);
            lbr.observe(&state, Action::Check);
            let mut after_check = state.clone();
            after_check.apply(Action::Check).unwrap();
            let seen = lbr.evaluate(&after_check);

            // These opponents ignore their cards, so the range never narrows and the win
            // probability after a bet is the same as before it.
            let value =
                |fp: f64, bet: f64| fp * pot + (1.0 - fp) * (wp * (pot + bet) - (1.0 - wp) * bet);
            let want = [
                (Action::Check, wp * pot),
                (Action::RaiseTo(200), value(fold_to_bet, 200.0)),
                (Action::RaiseTo(300), value(fold_to_all_in, 300.0)),
            ];
            assert!((seen.win_probability.unwrap() - wp).abs() < 1e-12);
            assert_eq!(seen.options.len(), 3);
            for ((action, got), (want_action, want_value)) in seen.options.iter().zip(want) {
                assert_eq!(*action, want_action);
                assert!(
                    (got - want_value).abs() < 1e-9,
                    "{lbr_hand} {action}: {got} against {want_value}"
                );
            }
            // The choice is the best of them, the first of equals.
            let mut best = want[0];
            for w in &want[1..] {
                if w.1 > best.1 + 1e-9 {
                    best = *w;
                }
            }
            assert_eq!(seen.action, best.0, "{lbr_hand}");
        }
    }
}

#[test]
fn facing_a_bet_it_calls_folds_or_raises_by_the_numbers() {
    // The big blind (LBR, seat 1) checks the river and the button bets 100 into 200.
    // Calling risks 100 to win 300: worth it above 25%.
    let board = "Kh Th 7s 4c 2s";
    let config = LbrConfig::fc(Street::River);
    for (lbr_hand, calls) in [
        ("Ks Qd", true),
        ("Ah Qd", true),
        ("5h 3h", false),
        ("6c 5c", false),
    ] {
        let mut state = deal([400, 400], 0, "Jc Jd", lbr_hand, board);
        to_river(&mut state, 100);
        let mut lbr = Lbr::new(&config, &AlwaysCall, 1, hand(lbr_hand), 0);
        state.apply(Action::Check).unwrap();
        lbr.observe(&state, Action::RaiseTo(100));
        state.apply(Action::RaiseTo(100)).unwrap();
        let seen = lbr.evaluate(&state);
        let wp = seen.win_probability.unwrap();
        assert_eq!(seen.options.len(), 1);
        assert!((seen.options[0].1 - (wp * 300.0 - (1.0 - wp) * 100.0)).abs() < 1e-9);
        assert_eq!(wp > 0.25, calls, "{lbr_hand} wins {wp}");
        assert_eq!(seen.action, if calls { Action::Call } else { Action::Fold });
    }

    // A raise is weighed the same way: call 100, then raise by the pot after the call
    // (400) to 500 in all, which is more than the 300 behind, so the only raise is all in.
    let config = LbrConfig::fcpa(Street::River);
    let mut state = deal([400, 400], 0, "Jc Jd", "Ks Kd", board);
    to_river(&mut state, 100);
    let mut lbr = Lbr::new(&config, &AlwaysCall, 1, hand("Ks Kd"), 0);
    state.apply(Action::Check).unwrap();
    lbr.observe(&state, Action::RaiseTo(100));
    state.apply(Action::RaiseTo(100)).unwrap();
    let seen = lbr.evaluate(&state);
    let wp = seen.win_probability.unwrap();
    assert_eq!(seen.options.len(), 2);
    assert_eq!(seen.options[1].0, Action::RaiseTo(300));
    // Pot 300, asked 100, raise 200 more: win 500 or lose 300.
    assert!((seen.options[1].1 - (wp * 500.0 - (1.0 - wp) * 300.0)).abs() < 1e-9);
    assert_eq!(seen.action, Action::RaiseTo(300));
}

#[test]
fn unequal_stacks_count_only_the_chips_that_can_be_matched() {
    let board = "Kh Th 7s 4c 2s";
    let config = LbrConfig::new(&[BetSize::AllIn], Street::River);

    // LBR (button, 300) against 120. Each puts in 20, then LBR moves all in for 280 on the
    // river. The opponent can call only 100, so LBR wins 140 or loses 100.
    let mut state = deal([300, 120], 0, "Ah Td", "Jc Jd", board);
    to_river(&mut state, 20);
    let mut lbr = Lbr::new(&config, &AlwaysCall, 0, hand("Ah Td"), 0);
    lbr.observe(&state, Action::Check);
    state.apply(Action::Check).unwrap();
    let seen = lbr.evaluate(&state);
    let wp = seen.win_probability.unwrap();
    assert_eq!(seen.options[1].0, Action::RaiseTo(280));
    assert!((seen.options[1].1 - (wp * 140.0 - (1.0 - wp) * 100.0)).abs() < 1e-9);

    // The other way round: LBR (big blind, 120) checks and the 300 stack bets 280. LBR
    // can call only 100, to win the 40 in the pot and 100 of the bet.
    let mut state = deal([300, 120], 0, "Jc Jd", "Ah Td", board);
    to_river(&mut state, 20);
    let mut lbr = Lbr::new(&config, &AlwaysCall, 1, hand("Ah Td"), 0);
    state.apply(Action::Check).unwrap();
    lbr.observe(&state, Action::RaiseTo(280));
    state.apply(Action::RaiseTo(280)).unwrap();
    let seen = lbr.evaluate(&state);
    let wp = seen.win_probability.unwrap();
    assert_eq!(
        seen.options,
        [(Action::Call, wp * 140.0 - (1.0 - wp) * 100.0)]
    );
}

#[test]
fn a_beaten_hand_checks_when_it_is_free_and_folds_when_it_is_not() {
    let board = "Kh Th 7s 4c 2s";
    let config = LbrConfig::fcpa(Street::River);
    // The opponent can only hold sets, and LBR has ace high: it never wins.
    let sets = Range::from_hands(&[hand("Kc Kd"), hand("Tc Td"), hand("7c 7d")]);
    let mut state = deal([400, 400], 0, "Kc Kd", "Ah Qd", board);
    to_river(&mut state, 100);
    let mut lbr = Lbr::with_range(&config, &AlwaysCall, 1, hand("Ah Qd"), sets, 0);
    let seen = lbr.evaluate(&state);
    assert_eq!(seen.win_probability, Some(0.0));
    assert_eq!(seen.action, Action::Check);
    state.apply(Action::Check).unwrap();
    lbr.observe(&state, Action::RaiseTo(100));
    state.apply(Action::RaiseTo(100)).unwrap();
    assert_eq!(lbr.act(&state), Action::Fold);

    // On a check-or-call street it never folds, whatever it holds.
    let config = LbrConfig::fcpa(Street::River);
    let mut state = deal([400, 400], 1, "7c 2d", "Kc Kd", board);
    let mut lbr = Lbr::new(&config, &AlwaysCall, 0, hand("7c 2d"), 0);
    lbr.observe(&state, Action::RaiseTo(400));
    state.apply(Action::RaiseTo(400)).unwrap();
    let seen = lbr.evaluate(&state);
    assert_eq!((seen.action, seen.win_probability), (Action::Call, None));
}
