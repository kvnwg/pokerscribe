//! The showdown pots and the all-in equity, checked against the nlhe engine itself.

// Loops over seat numbers read better than iterator chains over several arrays at once.
#![allow(clippy::needless_range_loop)]

use arena::{all_in_equity, all_in_runout, AllInEquity, EvalRanker, HandRecord, Pots, Scorer};
use nlhe::{
    parse_card, Action, BruteForceRanker, Card, Config, Deal, HandRanker, Rng, State, MAX_PLAYERS,
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

fn play(state: &mut State, actions: &[Action]) {
    for &a in actions {
        state.apply(a).unwrap();
    }
}

/// A random table: 2 to 6 players, stacks from 1 to 120 big blinds, sometimes an ante.
fn random_table(rng: &mut Rng) -> Config {
    let n = 2 + rng.below(5) as usize;
    let stacks: Vec<u32> = (0..n).map(|_| 1 + rng.below(240) as u32).collect();
    let ante = if rng.below(4) == 0 { 1 } else { 0 };
    Config::new(&stacks, 1, 2, ante, rng.below(n as u64) as usize).unwrap()
}

/// Plays a hand with random actions. `jam` is the chance in 100 that a raise is all in,
/// and no all-in is made before `jam_from` board cards are up.
fn random_hand(config: &Config, seed: u64, rng: &mut Rng, jam: u64, jam_from: usize) -> State {
    let mut state = State::from_seed(config, seed);
    while state.current_player().is_some() {
        let legal = state.legal_actions();
        let roll = rng.below(100);
        let may_jam = state.board().len() >= jam_from;
        let action = match legal.raise {
            Some(range) if may_jam && roll < jam => Action::RaiseTo(range.max_to),
            Some(range) if roll < jam + 15 => Action::RaiseTo(range.min_to),
            _ if legal.fold && roll >= 85 => Action::Fold,
            _ if legal.check => Action::Check,
            _ => Action::Call,
        };
        state.apply(action).unwrap();
    }
    state
}

fn ranks(state: &State, ranker: &impl HandRanker) -> [u32; MAX_PLAYERS] {
    let mut out = [0; MAX_PLAYERS];
    let board = state.deal().board;
    for seat in 0..state.num_players() {
        if !state.is_folded(seat) {
            let [a, b] = state.hole_cards(seat);
            out[seat] = ranker.rank7(&[a, b, board[0], board[1], board[2], board[3], board[4]]);
        }
    }
    out
}

#[test]
fn the_eval_ranker_orders_hands_like_the_brute_force_one() {
    let mut rng = Rng::new(11);
    let mut deck: [Card; 52] = std::array::from_fn(|i| i as Card);
    for _ in 0..3_000 {
        rng.shuffle(&mut deck);
        let a: [Card; 7] = deck[..7].try_into().unwrap();
        let b: [Card; 7] = [deck[7], deck[8], a[2], a[3], a[4], a[5], a[6]];
        assert_eq!(
            EvalRanker.rank7(&a).cmp(&EvalRanker.rank7(&b)),
            BruteForceRanker.rank7(&a).cmp(&BruteForceRanker.rank7(&b)),
        );
    }
}

#[test]
fn pots_pay_every_showdown_like_the_engine() {
    let mut rng = Rng::new(2026);
    let (mut showdowns, mut side_pots, mut odd_chips) = (0, 0, 0);
    for seed in 0..20_000 {
        let config = random_table(&mut rng);
        let state = random_hand(&config, seed, &mut rng, 30, 0);
        let n = state.num_players();
        let pots = Pots::of(&state);
        let won = pots.winnings(&ranks(&state, &EvalRanker));
        let expected = state.final_stacks(&EvalRanker).unwrap();
        for seat in 0..n {
            assert_eq!(
                state.stacks()[seat] + won[seat],
                expected[seat],
                "seed {seed}, seat {seat}: {:?}",
                state.history()
            );
        }
        assert_eq!(pots.total(), state.pot());
        if state.active_mask().count_ones() >= 2 {
            showdowns += 1;
            side_pots += (state.pots().as_slice().len() > 1) as u32;
            let winners = won[..n].iter().filter(|&&w| w > 0).count() as u32;
            odd_chips += (winners > 1 && !state.pot().is_multiple_of(winners)) as u32;
        }
    }
    // The check means little unless the hard cases came up.
    assert!(
        showdowns > 5_000 && side_pots > 1_000 && odd_chips > 100,
        "{showdowns} showdowns, {side_pots} with side pots, {odd_chips} with odd chips"
    );
}

/// The expected result per seat by brute force: the same betting replayed in the engine
/// on every board that could still come, paid by the engine with the slow ranker.
fn replayed_equity(state: &State, known: usize) -> [f64; MAX_PLAYERS] {
    let n = state.num_players();
    let config = Config::new(
        state.starting_stacks(),
        state.small_blind(),
        state.big_blind(),
        state.ante(),
        state.button(),
    )
    .unwrap();
    let original = *state.deal();
    let used: Vec<Card> = original.hole[..n]
        .iter()
        .flatten()
        .chain(&original.board[..known])
        .copied()
        .collect();
    let stub: Vec<Card> = (0..52).filter(|c| !used.contains(c)).collect();
    let mut total = [0.0; MAX_PLAYERS];
    let mut boards = 0.0;
    let mut finish = |rest: &[Card]| {
        let mut board = original.board;
        board[known..].copy_from_slice(rest);
        let mut replay =
            State::new(&config, Deal::new(&original.hole[..n], board).unwrap()).unwrap();
        for m in state.history() {
            replay.apply(m.action).unwrap();
        }
        let payouts = replay.payouts(&BruteForceRanker).unwrap();
        for seat in 0..n {
            total[seat] += payouts[seat] as f64;
        }
        boards += 1.0;
    };
    match 5 - known {
        1 => stub.iter().for_each(|&a| finish(&[a])),
        2 => {
            for (i, &a) in stub.iter().enumerate() {
                for &b in &stub[i + 1..] {
                    finish(&[a, b]);
                }
            }
        }
        other => panic!("{other} cards to come is too many to replay"),
    }
    total.map(|t| t / boards)
}

#[test]
fn all_in_equity_equals_replaying_every_board() {
    let mut rng = Rng::new(7);
    let (mut flops, mut turns, mut side_pots, mut folded) = (0, 0, 0, 0);
    let mut seed = 0;
    while flops < 12 || turns < 60 {
        seed += 1;
        let config = random_table(&mut rng);
        let state = random_hand(&config, seed, &mut rng, 35, 3);
        let Some(known) = all_in_runout(&state) else {
            assert_eq!(all_in_equity(&state, None), None);
            continue;
        };
        match known {
            3 if flops < 12 => flops += 1,
            4 if turns < 60 => turns += 1,
            _ => continue,
        }
        let n = state.num_players();
        side_pots += (state.pots().as_slice().len() > 1) as u32;
        folded += (state.active_mask().count_ones() < n as u32) as u32;
        let fast = all_in_equity(&state, None).unwrap();
        let slow = replayed_equity(&state, known);
        for seat in 0..n {
            assert!(
                (fast[seat] - slow[seat]).abs() < 1e-9,
                "seed {seed}, seat {seat}: {} against {} by replay",
                fast[seat],
                slow[seat]
            );
        }
        assert!(
            fast[..n].iter().sum::<f64>().abs() < 1e-9,
            "scores add up to 0"
        );
    }
    assert!(
        side_pots >= 10 && folded >= 10,
        "{side_pots} hands with side pots, {folded} with folded players"
    );
}

#[test]
fn folded_cards_are_out_of_the_deck() {
    // Seat 2 folds two kings before the flop. Seats 0 and 1 get all in on the turn with
    // aces against kings: the kings have no card left to catch.
    let config = Config::new(&[200, 200, 200], 1, 2, 0, 0).unwrap();
    let d = deal(&["AsAh", "KsKh", "KdKc"], "2c7d9h3sJd");
    let mut state = State::new(&config, d).unwrap();
    use Action::{Call, Check, Fold, RaiseTo};
    play(&mut state, &[RaiseTo(6), Call, Fold]); // the button raises, the big blind folds
    play(&mut state, &[Check, Check]); // flop
    play(&mut state, &[RaiseTo(194), Call]); // turn
    assert_eq!(all_in_runout(&state), Some(4));
    let expected = all_in_equity(&state, None).unwrap();
    assert_eq!(expected[..3], [202.0, -200.0, -2.0]);
}

#[test]
fn no_adjustment_without_cards_to_come() {
    let config = Config::new(&[200, 200], 1, 2, 0, 0).unwrap();
    let d = deal(&["AsAh", "KsKh"], "2c7d9h3sJd");
    use Action::{Call, Check, Fold, RaiseTo};

    // All in on the river: the cards are already out.
    let mut river = State::new(&config, d).unwrap();
    play(&mut river, &[Call, Check, Check, Check, Check, Check]);
    play(&mut river, &[RaiseTo(198), Call]);
    assert!(river.is_terminal());
    assert_eq!(all_in_runout(&river), None);

    // Everyone folds to an all-in before the flop: no showdown.
    let mut folded = State::new(&config, d).unwrap();
    play(&mut folded, &[RaiseTo(200), Fold]);
    assert_eq!(all_in_runout(&folded), None);

    // A hand still being played.
    assert_eq!(all_in_runout(&State::new(&config, d).unwrap()), None);

    // Called all in before the flop: five cards to come.
    let mut preflop = State::new(&config, d).unwrap();
    play(&mut preflop, &[RaiseTo(200), Call]);
    assert_eq!(all_in_runout(&preflop), Some(0));
}

#[test]
fn blinds_that_put_everyone_all_in_count_as_a_runout() {
    // Both stacks are smaller than their blinds: no decision is ever made.
    let config = Config::new(&[1, 2], 1, 2, 0, 0).unwrap();
    let state = State::new(&config, deal(&["AsAh", "KsKh"], "2c7d9h3sJd")).unwrap();
    assert!(state.is_terminal() && state.history().is_empty());
    assert_eq!(all_in_runout(&state), Some(0));
    let expected = all_in_equity(&state, Some((2_000, 1))).unwrap();
    assert!(expected[0] > 0.5 && (expected[0] + expected[1]).abs() < 1e-9);
}

/// Heads-up before the flop, all in for 100 each: seat 0's expected result.
fn preflop(holes: [&str; 2], sample: Option<(u32, u64)>) -> f64 {
    let config = Config::new(&[100, 100], 1, 2, 0, 0).unwrap();
    let mut state = State::new(&config, deal(&holes, "2c7d9h3sJd")).unwrap();
    play(&mut state, &[Action::RaiseTo(100), Action::Call]);
    let expected = all_in_equity(&state, sample).unwrap();
    assert!((expected[0] + expected[1]).abs() < 1e-9);
    expected[0]
}

#[test]
fn preflop_equity_over_every_board() {
    // Mirror-image hands split every board or win equally often: exactly even.
    assert_eq!(preflop(["AsKh", "AhKs"], None), 0.0);

    // Aces against kings, against a count written the long way round.
    let hero = cards("AsAh");
    let villain = cards("KdKc");
    let deck: Vec<eval::Card> = (0..52u8)
        .filter(|c| !hero.contains(c) && !villain.contains(c))
        .map(|c| eval::Card::from_index(c).unwrap())
        .collect();
    let hand = |hole: &[Card], board: [eval::Card; 5]| {
        let [a, b] = [hole[0], hole[1]].map(|c| eval::Card::from_index(c).unwrap());
        eval::eval7(&[a, b, board[0], board[1], board[2], board[3], board[4]])
    };
    let (mut wins, mut ties, mut boards) = (0u64, 0u64, 0u64);
    for a in 0..deck.len() {
        for b in a + 1..deck.len() {
            for c in b + 1..deck.len() {
                for d in c + 1..deck.len() {
                    for e in d + 1..deck.len() {
                        let board = [deck[a], deck[b], deck[c], deck[d], deck[e]];
                        let (mine, theirs) = (hand(&hero, board), hand(&villain, board));
                        boards += 1;
                        wins += (mine > theirs) as u64;
                        ties += (mine == theirs) as u64;
                    }
                }
            }
        }
    }
    assert_eq!(boards, 1_712_304);
    // Winning takes the other 100, a tie nothing, losing costs 100.
    let losses = boards - wins - ties;
    let by_hand = 100.0 * (wins as f64 - losses as f64) / boards as f64;
    let exact = preflop(["AsAh", "KdKc"], None);
    assert!((exact - by_hand).abs() < 1e-9, "{exact} against {by_hand}");
    // Aces win about 81% of the time against kings.
    assert!((60.0..66.0).contains(&exact), "{exact}");
}

#[test]
fn sampled_equity_is_close_repeatable_and_seeded() {
    let exact = preflop(["AsAh", "KdKc"], None);
    let a = preflop(["AsAh", "KdKc"], Some((10_000, 1)));
    let b = preflop(["AsAh", "KdKc"], Some((10_000, 1)));
    let c = preflop(["AsAh", "KdKc"], Some((10_000, 2)));
    assert_eq!(a, b, "the same seed draws the same boards");
    assert_ne!(a, c, "another seed draws other boards");
    // One board swings +-100 around the mean with a deviation near 78, so the mean of
    // 10,000 has a standard error near 0.8.
    assert!(
        (a - exact).abs() < 3.0 && (c - exact).abs() < 3.0,
        "{a} {c}"
    );

    // The average of many samples closes in on the exact value: no bias.
    let seeds = 400;
    let mean = (0..seeds)
        .map(|s| preflop(["AsAh", "KdKc"], Some((500, 100 + s))))
        .sum::<f64>()
        / seeds as f64;
    // 200,000 boards in all: standard error near 0.18.
    assert!((mean - exact).abs() < 0.6, "{mean}");

    // A cap above the number of boards changes nothing: the flop is always exact.
    let config = Config::new(&[100, 100], 1, 2, 0, 0).unwrap();
    let mut state = State::new(&config, deal(&["AsAh", "KdKc"], "2c7d9h3sJd")).unwrap();
    play(&mut state, &[Action::Call, Action::Check]);
    play(&mut state, &[Action::RaiseTo(98), Action::Call]);
    assert_eq!(all_in_runout(&state), Some(3));
    assert_eq!(
        all_in_equity(&state, Some((10_000, 5))),
        all_in_equity(&state, None)
    );
}

#[test]
fn the_scorer_leaves_other_hands_alone_and_reuses_a_deal() {
    let config = Config::new(&[100, 100], 1, 2, 0, 0).unwrap();
    let d = deal(&["AsAh", "KdKc"], "2c7d9h3sJd");
    let scorer = AllInEquity {
        max_runouts: Some(1_000),
    };
    let score = |state: &State, seed: u64| {
        let payouts = state.payouts(&EvalRanker).unwrap();
        let mut scores = [payouts[0] as f64, payouts[1] as f64];
        let record = HandRecord {
            deal: 0,
            replay: 0,
            seed,
            agents: &[0, 1],
            state,
            payouts: &payouts[..2],
        };
        scorer.score(&record, &mut scores);
        scores
    };

    let mut folded = State::new(&config, d).unwrap();
    play(&mut folded, &[Action::Fold]);
    assert_eq!(score(&folded, 1), [-1.0, 1.0]);

    // The same all-in reached two ways (as in the two replays of a deal) scores the same,
    // and what is remembered for one deal is not used for another seed or other chips.
    let mut jam = State::new(&config, d).unwrap();
    play(&mut jam, &[Action::RaiseTo(100), Action::Call]);
    let mut limp_jam = State::new(&config, d).unwrap();
    play(
        &mut limp_jam,
        &[Action::Call, Action::RaiseTo(100), Action::Call],
    );
    let first = score(&jam, 1);
    assert_eq!(score(&limp_jam, 1), first);
    assert_eq!(first, all_in_equity(&jam, Some((1_000, 1))).unwrap()[..2]);
    assert_eq!(
        score(&jam, 2),
        all_in_equity(&jam, Some((1_000, 2))).unwrap()[..2]
    );
    let short = Config::new(&[100, 60], 1, 2, 0, 0).unwrap();
    let mut smaller = State::new(&short, d).unwrap();
    play(&mut smaller, &[Action::RaiseTo(100), Action::Call]);
    assert_eq!(
        score(&smaller, 1),
        all_in_equity(&smaller, Some((1_000, 1))).unwrap()[..2]
    );
    assert_ne!(score(&smaller, 1), first);
}
