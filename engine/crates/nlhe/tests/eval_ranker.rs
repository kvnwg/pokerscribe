//! `EvalRanker` (the eval crate's table evaluator) against `BruteForceRanker`, the slow
//! reference that is simple enough to check by reading.
//!
//! 100,000 random showdowns with 2 to 6 players. In each one the two rankers must put the
//! hands in the same order with the same category, and the engine must pay out the same
//! chips with either. The PokerKit hands are replayed with both rankers in
//! `pokerkit_fixtures.rs`.
#![cfg(feature = "eval")]

use nlhe::ranker::category;
use nlhe::{
    card_string, Action, BruteForceRanker, Card, Chips, Config, Deal, EvalRanker, HandRanker, Rng,
    State,
};

const SHOWDOWNS: u64 = 100_000;

fn seven(deal: &Deal, seat: usize) -> [Card; 7] {
    let [a, b] = deal.hole[seat];
    let d = deal.board;
    [a, b, d[0], d[1], d[2], d[3], d[4]]
}

fn show(cards: &[Card]) -> String {
    cards.iter().map(|&c| card_string(c)).collect()
}

/// The category (0 = high card ... 8 = straight flush) of an `EvalRanker` value.
fn eval_category(value: u32) -> u32 {
    eval::HandRank::from_value(value as u16)
        .expect("an eval rank is in 1..=7462")
        .category() as u32
}

/// The brute-force values of one showdown, worked out once and handed to the engine, so
/// that the slow ranker runs once per hand and not again for the payouts.
struct Known(Vec<([Card; 7], u32)>);

impl HandRanker for Known {
    fn rank7(&self, cards: &[Card; 7]) -> u32 {
        let found = self.0.iter().find(|(known, _)| known == cards);
        found
            .expect("the engine ranks only the hands of this deal")
            .1
    }
}

#[derive(Default)]
struct Tally {
    /// (brute force, eval) for every hand.
    seen: Vec<(u32, u32)>,
    tables: [usize; 7],
    hands: usize,
    split_pots: usize,
    side_pots: usize,
}

/// Showdown number `k`: a random table, stacks and cards, all from `k`.
fn check_showdown(k: u64, tally: &mut Tally) {
    let mut rng = Rng::new(0x5EED_E7A1 + k);
    let n = 2 + rng.below(5) as usize;
    let button = rng.below(n as u64) as usize;
    let stacks: Vec<Chips> = (0..n).map(|_| 1 + rng.below(300) as Chips).collect();
    let ante = rng.below(3) as Chips;
    let config = Config::new(&stacks, 1, 2, ante, button).unwrap();
    let mut state = State::from_seed(&config, rng.next_u64());
    tally.tables[n] += 1;

    // The same order, hand against hand, and the same category.
    let deal = *state.deal();
    let slow: Vec<u32> = (0..n)
        .map(|s| BruteForceRanker.rank7(&seven(&deal, s)))
        .collect();
    let fast: Vec<u32> = (0..n).map(|s| EvalRanker.rank7(&seven(&deal, s))).collect();
    for i in 0..n {
        assert_eq!(
            category(slow[i]),
            eval_category(fast[i]),
            "showdown {k}: category of {} on {}",
            show(&deal.hole[i]),
            show(&deal.board)
        );
        for j in i + 1..n {
            assert_eq!(
                slow[i].cmp(&slow[j]),
                fast[i].cmp(&fast[j]),
                "showdown {k}: {} against {} on {}",
                show(&deal.hole[i]),
                show(&deal.hole[j]),
                show(&deal.board)
            );
        }
    }
    tally.hands += n;
    tally
        .seen
        .extend(slow.iter().copied().zip(fast.iter().copied()));

    // The same chips. Everyone raises all in or calls, so nobody folds, every hand is
    // shown down and unequal stacks make side pots.
    while state.current_player().is_some() {
        let legal = state.legal_actions();
        let action = match (legal.raise, legal.call) {
            (Some(range), _) => Action::RaiseTo(range.max_to),
            (None, Some(_)) => Action::Call,
            (None, None) => Action::Check,
        };
        state.apply(action).unwrap();
    }
    assert_eq!(state.active_mask().count_ones() as usize, n);
    let known = Known((0..n).map(|s| (seven(&deal, s), slow[s])).collect());
    assert_eq!(
        state.final_stacks(&known),
        state.final_stacks(&EvalRanker),
        "showdown {k}: final stacks, holes {:?}, board {}",
        deal.hole[..n].iter().map(|h| show(h)).collect::<Vec<_>>(),
        show(&deal.board)
    );
    assert_eq!(state.payouts(&known), state.payouts(&EvalRanker));
    tally.side_pots += (state.pots().as_slice().len() > 1) as usize;
    let best = slow.iter().max().unwrap();
    tally.split_pots += (slow.iter().filter(|&r| r == best).count() > 1) as usize;
}

#[test]
fn agrees_with_brute_force_on_100_000_random_showdowns() {
    // Each showdown depends only on its number, so the work can be shared between threads
    // without changing what is tested.
    let threads = std::thread::available_parallelism().map_or(1, |n| n.get()) as u64;
    let parts: Vec<Tally> = std::thread::scope(|scope| {
        let workers: Vec<_> = (0..threads)
            .map(|t| {
                scope.spawn(move || {
                    let mut tally = Tally::default();
                    for k in (t..SHOWDOWNS).step_by(threads as usize) {
                        check_showdown(k, &mut tally);
                    }
                    tally
                })
            })
            .collect();
        workers
            .into_iter()
            .map(|w| {
                w.join()
                    .expect("a showdown differs (see the message above)")
            })
            .collect()
    });
    let mut all = Tally::default();
    for part in parts {
        all.seen.extend(part.seen);
        all.hands += part.hands;
        all.split_pots += part.split_pots;
        all.side_pots += part.side_pots;
        for (total, n) in all.tables.iter_mut().zip(part.tables) {
            *total += n;
        }
    }

    // One order across all the showdowns too: sorted by the brute-force value, the eval
    // value goes up exactly when the brute-force value does.
    all.seen.sort_unstable();
    all.seen.dedup();
    for pair in all.seen.windows(2) {
        assert!(
            pair[0].0 < pair[1].0 && pair[0].1 < pair[1].1,
            "the rankers order two hands differently: (brute force, eval) {:?} and {:?}",
            pair[0],
            pair[1]
        );
    }

    println!(
        "{SHOWDOWNS} showdowns, {} hands, players {:?}, {} different ranks, \
         {} with tied best hands, {} with side pots",
        all.hands,
        &all.tables[2..],
        all.seen.len(),
        all.split_pots,
        all.side_pots
    );
    assert_eq!(all.tables.iter().sum::<usize>() as u64, SHOWDOWNS);
    assert!(all.tables[2..].iter().all(|&t| t > 10_000));
    assert!(
        all.seen.len() > 4_000,
        "most of the 4,824 seven-card ranks should come up"
    );
    assert!(all.split_pots > 1_000 && all.side_pots > 30_000);
}

#[test]
fn eval_ranker_values_are_the_eval_crates() {
    let hand = |s: &str| -> [Card; 7] {
        let cards: Vec<Card> = s
            .split_whitespace()
            .map(|c| nlhe::parse_card(c).unwrap())
            .collect();
        cards.try_into().unwrap()
    };
    // 1 is the worst hand of all, 7,462 a royal flush.
    assert_eq!(EvalRanker.rank7(&hand("Ah Kh Qh Jh Th 2c 3d")), 7462);
    assert_eq!(
        eval_category(EvalRanker.rank7(&hand("Ah Kh Qh Jh Th 2c 3d"))),
        8
    );
    // The worst seven cards: no pair, no straight, no flush, nine high at best.
    assert_eq!(
        eval_category(EvalRanker.rank7(&hand("2c 3d 4h 5s 7c 8d 9h"))),
        0
    );
    // Kickers that do not play make a tie.
    assert_eq!(
        EvalRanker.rank7(&hand("Ac Ad Kh Ks Qc 2d 3h")),
        EvalRanker.rank7(&hand("Ah As Kc Kd Qc 4d 5h"))
    );
    // Works through a reference too, as the engine takes `&R`.
    let by_ref: &dyn HandRanker = &EvalRanker;
    assert!(
        by_ref.rank7(&hand("2c 2d 2h 2s 3c 4d 5h")) > by_ref.rank7(&hand("Ac Ad Ah Ks Kc 4d 5h"))
    );
}

#[test]
#[should_panic(expected = "0..52")]
fn eval_ranker_refuses_a_card_that_is_not_a_card() {
    EvalRanker.rank7(&[0, 1, 2, 3, 4, 5, 52]);
}
