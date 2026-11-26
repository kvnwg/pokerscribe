//! Hand-made checks of each rule, plus invariants over many random hands.

use nlhe::ranker::{category, rank5};
use nlhe::{
    parse_card, Action, ActionError, BruteForceRanker, Card, Config, Deal, HandRanker, RaiseRange,
    Rng, State, Street, MAX_PLAYERS,
};

fn cards(s: &str) -> Vec<Card> {
    s.as_bytes()
        .chunks(2)
        .map(|c| parse_card(std::str::from_utf8(c).unwrap()).unwrap())
        .collect()
}

fn deal(holes: &[&str], board: &str) -> Deal {
    let hole: Vec<[Card; 2]> = holes.iter().map(|h| cards(h).try_into().unwrap()).collect();
    Deal::new(&hole, cards(board).try_into().unwrap()).unwrap()
}

fn state(stacks: &[u32], sb: u32, bb: u32, ante: u32, button: usize, d: Deal) -> State {
    State::new(&Config::new(stacks, sb, bb, ante, button).unwrap(), d).unwrap()
}

fn play(s: &mut State, actions: &[Action]) {
    for &a in actions {
        s.apply(a).unwrap_or_else(|e| {
            panic!(
                "{e} (seat {:?}, {:?})",
                s.current_player(),
                s.legal_actions()
            )
        });
    }
}

/// Hole cards for `n` seats that cannot beat or spoil a broadway board.
const LOW: [&str; 6] = ["2c3d", "2d3h", "2h3s", "4c5d", "4d5h", "4h5s"];
/// A broadway straight with at most two cards of a suit: everyone plays the board.
const BROADWAY: &str = "AcKdQhJsTc";

use Action::{Call, Check, Fold, RaiseTo};

// ----- the ranker -----

#[test]
fn ranker_counts_every_five_card_hand() {
    let mut counts = [0u32; 9];
    let mut c = [0u8; 5];
    for a in 0..52 {
        c[0] = a;
        for b in a + 1..52 {
            c[1] = b;
            for d in b + 1..52 {
                c[2] = d;
                for e in d + 1..52 {
                    c[3] = e;
                    for f in e + 1..52 {
                        c[4] = f;
                        counts[category(rank5(c)) as usize] += 1;
                    }
                }
            }
        }
    }
    // high card, pair, two pair, trips, straight, flush, full house, quads, straight flush
    assert_eq!(
        counts,
        [1_302_540, 1_098_240, 123_552, 54_912, 10_200, 5_108, 3_744, 624, 40]
    );
}

#[test]
fn ranker_orders_hands() {
    let r = |s: &str| BruteForceRanker.rank7(&cards(s).try_into().unwrap());
    // the wheel is the lowest straight
    assert!(r("Ah2c3d4h5s9cKd") < r("2c3d4h5s6h9cKd"));
    // a straight flush beats quads
    assert!(r("9h8h7h6h5hAsAd") > r("AcAhAsAdKd2c3c"));
    // kickers count, suits do not
    assert!(r("AhKd9c7s4h3c2d") > r("AhQd9c7s4h3c2d"));
    assert_eq!(r("AhKd9c7s4h3c2d"), r("AsKc9d7h4c3d2h"));
    // the best five of seven: two pair with the best kicker
    assert_eq!(r("KhKd5c5sAh2c2d"), r("KcKs5h5dAd3c3d"));
    // trips over two pair, full house over flush
    assert!(r("7c7d7h2s9dKcQh") > r("AcAdKhKs9d3c2h"));
    assert!(r("2c2d2h3s3dKcQh") > r("AhKhQh9h2hJc3d"));
}

// ----- order of play -----

#[test]
fn heads_up_button_posts_small_blind_and_acts_first_preflop_only() {
    let mut s = state(
        &[100, 100],
        1,
        2,
        0,
        0,
        deal(&["AsAh", "KsKh"], "2c7d9hJsQc"),
    );
    assert_eq!((s.small_blind_seat(), s.big_blind_seat()), (0, 1));
    assert_eq!(s.bets(), &[1, 2]);
    assert_eq!(s.current_player(), Some(0));
    play(&mut s, &[Call]);
    // the big blind has the option
    let legal = s.legal_actions();
    assert!(legal.check && !legal.fold && legal.call.is_none());
    assert_eq!(
        legal.raise,
        Some(RaiseRange {
            min_to: 4,
            max_to: 100
        })
    );
    play(&mut s, &[Check]);
    assert_eq!(s.street(), Street::Flop);
    assert_eq!(s.board().len(), 3);
    assert_eq!(s.current_player(), Some(1)); // the big blind acts first after the flop
}

#[test]
fn six_max_order() {
    let mut s = State::from_seed(&Config::new(&[200; 6], 1, 2, 0, 3).unwrap(), 1);
    assert_eq!((s.small_blind_seat(), s.big_blind_seat()), (4, 5));
    assert_eq!(s.current_player(), Some(0)); // after the big blind
    play(&mut s, &[Fold, Call, Call, Call, Call, Check]); // seats 0 to 3, then 4 completes and 5 checks
    assert_eq!(s.street(), Street::Flop);
    assert_eq!(s.current_player(), Some(4)); // the small blind is first after the flop
    play(&mut s, &[Check, Check, Check, Check, Check]);
    assert_eq!(s.street(), Street::Turn);
    assert_eq!(s.pot(), 10);
}

#[test]
fn folding_is_not_offered_when_checking_is_free() {
    let mut s = state(
        &[100, 100],
        1,
        2,
        0,
        0,
        deal(&["AsAh", "KsKh"], "2c7d9hJsQc"),
    );
    play(&mut s, &[Call]);
    let before = s.clone();
    assert_eq!(s.apply(Fold), Err(ActionError::Illegal(Fold)));
    assert_eq!(s.apply(RaiseTo(3)), Err(ActionError::Illegal(RaiseTo(3))));
    assert_eq!(s.apply(Call), Err(ActionError::Illegal(Call)));
    assert_eq!(s, before);
}

// ----- raise sizes and reopening -----

#[test]
fn minimum_raise_is_the_last_full_raise() {
    let mut s = State::from_seed(&Config::new(&[500; 3], 1, 2, 0, 0).unwrap(), 2);
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 4,
            max_to: 500
        })
    );
    play(&mut s, &[RaiseTo(7)]); // a raise of 5
    assert_eq!(s.legal_actions().raise.unwrap().min_to, 12);
    play(&mut s, &[RaiseTo(20)]); // a raise of 13
    assert_eq!(s.legal_actions().raise.unwrap().min_to, 33);
    assert_eq!(s.apply(RaiseTo(32)), Err(ActionError::Illegal(RaiseTo(32))));
    play(&mut s, &[Call, Call]);
    // a new street starts again from the big blind
    assert_eq!(s.street(), Street::Flop);
    assert_eq!(s.legal_actions().raise.unwrap().min_to, 2);
}

#[test]
fn short_all_in_raise_does_not_reopen_for_the_raiser() {
    // seat 0 button, seat 1 small blind with 8 chips, seat 2 big blind
    let mut s = State::from_seed(&Config::new(&[100, 8, 100], 1, 2, 0, 0).unwrap(), 3);
    play(&mut s, &[RaiseTo(6)]); // a full raise of 4
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 8,
            max_to: 8
        })
    );
    play(&mut s, &[RaiseTo(8)]); // all in, 2 more: not a full raise
                                 // the big blind has not acted, so it may raise, by at least the last full raise
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 12,
            max_to: 100
        })
    );
    play(&mut s, &[Call]);
    let legal = s.legal_actions();
    assert_eq!(s.current_player(), Some(0));
    assert_eq!((legal.fold, legal.call, legal.raise), (true, Some(2), None));
}

#[test]
fn short_all_ins_that_add_up_to_a_full_raise_reopen() {
    // Seat 2 raises to 6 (a full raise of 4). Seats 3, 4, 5 go all in for 9, 12 and 14:
    // each is short, but 9 and 12 together raise seat 2's bet by 6. The small blind folds,
    // the big blind calls, and seat 2 faces 8 more: more than a full raise since it acted.
    // (PokerKit 0.7.8 refuses the raise here; the fixtures flag this case "A".)
    let mut s = State::from_seed(
        &Config::new(&[200, 200, 200, 9, 12, 14], 1, 2, 0, 5).unwrap(),
        4,
    );
    play(
        &mut s,
        &[RaiseTo(6), RaiseTo(9), RaiseTo(12), RaiseTo(14), Fold, Call],
    );
    assert_eq!(s.current_player(), Some(2));
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 18,
            max_to: 200
        })
    );
}

#[test]
fn limper_cannot_reraise_a_short_all_in() {
    // seat 3 button with 3 chips, seat 0 small blind, seat 1 big blind, seat 2 limps
    // (PokerKit 0.7.8 lets the limper raise; the fixtures flag this case "D".)
    let mut s = State::from_seed(&Config::new(&[100, 100, 100, 3], 1, 2, 0, 3).unwrap(), 5);
    play(&mut s, &[Call, RaiseTo(3)]);
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 5,
            max_to: 100
        })
    ); // small blind
    play(&mut s, &[Call]);
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 5,
            max_to: 100
        })
    ); // big blind
    play(&mut s, &[Call]);
    assert_eq!(s.current_player(), Some(2));
    assert_eq!(s.legal_actions().raise, None);
    assert_eq!(s.legal_actions().call, Some(1));
}

#[test]
fn checker_cannot_raise_an_all_in_bet_below_the_big_blind() {
    // seat 0 button, seat 1 small blind, seat 2 big blind with 3 chips
    let mut s = State::from_seed(&Config::new(&[100, 100, 3], 1, 2, 0, 0).unwrap(), 6);
    play(&mut s, &[Call, Call, Check]);
    play(&mut s, &[Check]); // seat 1
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 1,
            max_to: 1
        })
    );
    play(&mut s, &[RaiseTo(1)]); // seat 2 bets its last chip
    assert_eq!(
        s.legal_actions().raise,
        Some(RaiseRange {
            min_to: 3,
            max_to: 98
        })
    ); // seat 0 has not acted
    play(&mut s, &[Call]);
    assert_eq!(s.current_player(), Some(1));
    assert_eq!(s.legal_actions().raise, None);
}

#[test]
fn no_raise_when_nobody_can_answer() {
    let mut s = State::from_seed(&Config::new(&[100, 50], 1, 2, 0, 0).unwrap(), 7);
    play(&mut s, &[Call, RaiseTo(50)]);
    let legal = s.legal_actions();
    assert_eq!(
        (legal.fold, legal.call, legal.raise),
        (true, Some(48), None)
    );
}

// ----- pots and payouts -----

#[test]
fn side_pots() {
    // seat 0 button 30 chips, seat 1 small blind 10, seat 2 big blind 20; all in preflop
    let d = deal(&["KsKh", "AsAh", "2c7d"], "3c8d9hJs4c");
    let mut s = state(&[30, 10, 20], 1, 2, 0, 0, d);
    play(&mut s, &[RaiseTo(30), Call, Call]);
    assert!(s.is_terminal());
    assert_eq!(s.street(), Street::River);
    assert_eq!(s.board().len(), 5);
    // the 10 of seat 0's bet that nobody could match went back
    assert_eq!(s.stacks(), &[10, 0, 0]);
    assert_eq!(s.committed(), &[20, 10, 20]);
    let pots: Vec<(u32, u8)> = s
        .pots()
        .as_slice()
        .iter()
        .map(|p| (p.amount, p.eligible))
        .collect();
    assert_eq!(pots, [(30, 0b111), (20, 0b101)]);
    let r = BruteForceRanker;
    assert_eq!(&s.final_stacks(&r).unwrap()[..3], &[30, 30, 0]);
    assert_eq!(&s.payouts(&r).unwrap()[..3], &[0, 20, -20]);
}

#[test]
fn uncalled_bet_goes_back() {
    let d = deal(&["2c2d", "AsAh"], "3c8d9hJs4c");
    let mut s = state(&[100, 40], 1, 2, 0, 0, d);
    play(&mut s, &[RaiseTo(100), Call]);
    assert_eq!(s.stacks(), &[60, 0]);
    assert_eq!(s.committed(), &[40, 40]);
    assert_eq!(&s.final_stacks(&BruteForceRanker).unwrap()[..2], &[60, 80]);

    let mut s = state(&[100, 40], 1, 2, 0, 0, d);
    play(&mut s, &[RaiseTo(10), Fold]);
    assert!(s.is_terminal());
    assert_eq!(s.street(), Street::Preflop);
    assert_eq!(&s.payouts(&BruteForceRanker).unwrap()[..2], &[2, -2]);
}

#[test]
fn odd_chips_go_to_the_first_winner_after_the_button() {
    // Four seats, blinds 2/3, button seat 0. Everyone but the small blind sees a broadway
    // board: a three-way tie for 11 chips. 11 = 3 * 3 + 2: both odd chips go to the big
    // blind (seat 2), the first winner after the button (seat 1 folded).
    let d = deal(&LOW[..4], BROADWAY);
    let mut s = state(&[100; 4], 2, 3, 0, 0, d);
    play(&mut s, &[Call, Call, Fold, Check]); // seat 3, seat 0, seat 1 folds, seat 2
    for _ in 0..9 {
        play(&mut s, &[Check]);
    }
    assert!(s.is_terminal());
    assert_eq!(s.pot(), 11);
    assert_eq!(&s.payouts(&BruteForceRanker).unwrap()[..4], &[0, -2, 2, 0]);
}

#[test]
fn ante_dead_money_and_short_antes() {
    // ante 2; seat 2 has 1 chip and is all in on its ante, so it can win only 1 from each
    let d = deal(&["KsKh", "QsQh", "AsAh"], "3c8d9hJs4c");
    let mut s = state(&[100, 100, 1], 1, 2, 2, 2, d); // button seat 2, blinds seats 0 and 1
    assert_eq!(s.stacks(), &[97, 96, 0]);
    assert_eq!(s.current_player(), Some(0)); // seat 2 cannot act, the small blind is next
    play(&mut s, &[Call, Check]);
    for _ in 0..6 {
        play(&mut s, &[Check]);
    }
    let pots: Vec<(u32, u8)> = s
        .pots()
        .as_slice()
        .iter()
        .map(|p| (p.amount, p.eligible))
        .collect();
    assert_eq!(pots, [(3, 0b111), (6, 0b011)]);
    // seat 2's aces win 3; seat 0's kings win the other 6
    assert_eq!(&s.payouts(&BruteForceRanker).unwrap()[..3], &[2, -4, 2]);
}

#[test]
fn everyone_all_in_from_the_blinds_runs_out() {
    let d = deal(&["KsKh", "AsAh"], "3c8d9hJs4c");
    let s = state(&[1, 2], 1, 2, 0, 0, d);
    assert!(s.is_terminal());
    assert_eq!(s.current_player(), None);
    assert_eq!(s.legal_actions(), Default::default());
    assert_eq!(&s.final_stacks(&BruteForceRanker).unwrap()[..2], &[0, 3]);
}

// ----- deals, history, cloning -----

#[test]
fn seeded_deals_are_deterministic() {
    let a = Deal::from_seed(42, 6, 0);
    assert_eq!(a, Deal::from_seed(42, 6, 0));
    assert_ne!(a, Deal::from_seed(43, 6, 0));
    let mut seen = 0u64;
    for &c in a.hole[..6].iter().flatten().chain(a.board.iter()) {
        assert!(c < 52 && seen & (1 << c) == 0);
        seen |= 1 << c;
    }
    let mut r = Rng::new(9);
    let first: Vec<u64> = (0..4).map(|_| r.next_u64()).collect();
    let mut r = Rng::new(9);
    assert_eq!(first, (0..4).map(|_| r.next_u64()).collect::<Vec<_>>());
}

#[test]
fn bad_deals_are_refused() {
    let config = Config::new(&[10, 10], 1, 2, 0, 0).unwrap();
    let mut d = deal(&["AsAh", "KsKh"], "3c8d9hJs4c");
    d.board[0] = d.hole[0][0];
    assert!(State::new(&config, d).is_err());
    assert!(Config::new(&[10], 1, 2, 0, 0).is_err());
    assert!(Config::new(&[10, 0], 1, 2, 0, 0).is_err());
    assert!(Config::new(&[10, 10], 3, 2, 0, 0).is_err());
    assert!(Config::new(&[10, 10], 1, 2, 0, 2).is_err());
}

#[test]
fn history_survives_long_hands_and_clones() {
    let mut s = State::from_seed(&Config::new(&[100_000, 100_000], 1, 2, 0, 0).unwrap(), 8);
    let mut to = 4;
    for _ in 0..50 {
        play(&mut s, &[RaiseTo(to)]);
        to += 2;
    }
    let copy = s.clone();
    play(&mut s, &[Call]);
    assert_eq!(copy.history().len(), 50);
    assert_eq!(s.history().len(), 51);
    assert_eq!(s.history()[0].action, RaiseTo(4));
    assert_eq!(s.history()[0].added, 3);
    assert_eq!(s.history()[50].action, Call);
    assert_eq!(s.history()[50].added, 2);
    assert_eq!(s.history()[50].seat, 0);
}

#[test]
fn state_is_small() {
    let size = std::mem::size_of::<State>();
    println!("State is {size} bytes");
    assert!(size <= 512, "State grew to {size} bytes");
}

// ----- random hands -----

fn random_action(s: &State, rng: &mut Rng) -> Action {
    let legal = s.legal_actions();
    let mut options = Vec::new();
    if legal.fold {
        options.push(Fold);
    }
    if legal.check {
        options.push(Check);
    }
    if legal.call.is_some() {
        options.push(Call);
    }
    if let Some(r) = legal.raise {
        options.push(RaiseTo(r.min_to));
        options.push(RaiseTo(r.max_to));
        options.push(RaiseTo(
            r.min_to + rng.below((r.max_to - r.min_to) as u64 + 1) as u32,
        ));
    }
    options[rng.below(options.len() as u64) as usize]
}

#[test]
fn random_hands_keep_every_chip() {
    let mut rng = Rng::new(2026);
    for hand in 0..20_000u64 {
        let n = 2 + rng.below(5) as usize;
        let bb = 1 + rng.below(10) as u32;
        let sb = rng.below(bb as u64 + 1) as u32;
        let ante = if rng.below(2) == 0 {
            0
        } else {
            rng.below(bb as u64 + 1) as u32
        };
        let stacks: Vec<u32> = (0..n)
            .map(|_| 1 + rng.below(60 * bb as u64) as u32)
            .collect();
        let total: u32 = stacks.iter().sum();
        let config = Config::new(&stacks, sb, bb, ante, rng.below(n as u64) as usize).unwrap();
        let mut s = State::from_seed(&config, hand);
        let mut steps = 0;
        while let Some(seat) = s.current_player() {
            assert!(!s.is_folded(seat) && s.stacks()[seat] > 0);
            assert_eq!(s.stacks().iter().sum::<u32>() + s.pot(), total);
            let a = random_action(&s, &mut rng);
            let before = s.clone();
            s.apply(a).unwrap();
            assert_ne!(s, before);
            steps += 1;
            assert!(steps < 10_000);
        }
        let fin = s.final_stacks(&BruteForceRanker).unwrap();
        assert_eq!(fin[..n].iter().sum::<u32>(), total);
        assert_eq!(fin[n..], [0; MAX_PLAYERS][n..]);
        assert_eq!(s.payouts(&BruteForceRanker).unwrap().iter().sum::<i64>(), 0);
        assert_eq!(s.history().len(), steps);
    }
}
