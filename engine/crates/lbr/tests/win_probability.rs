//! The win probability LBR uses equals plain enumeration: every opposing hand in the range,
//! every way to finish the board, ranked by the rules engine's own brute-force ranker (a
//! different evaluator from the one LBR uses).

use lbr::{
    card_mask, combo_cards, combo_index, preflop_equities, preflop_equities_sampled,
    showdown_equities, win_probability, Range, NUM_COMBOS,
};
use nlhe::{parse_card, BruteForceRanker, Card, HandRanker, Rng};

fn cards(s: &str) -> Vec<Card> {
    s.split_whitespace()
        .map(|c| parse_card(c).unwrap_or_else(|| panic!("bad card {c}")))
        .collect()
}

fn hand(s: &str) -> [Card; 2] {
    cards(s).try_into().expect("two cards")
}

/// Calls `visit` with every way to pick `k` of `deck[start..]`, added to `picked`.
fn each_choice(
    deck: &[Card],
    k: usize,
    start: usize,
    picked: &mut Vec<Card>,
    visit: &mut dyn FnMut(&[Card]),
) {
    if k == 0 {
        visit(picked);
        return;
    }
    for i in start..=deck.len() - k {
        picked.push(deck[i]);
        each_choice(deck, k - 1, i + 1, picked, visit);
        picked.pop();
    }
}

fn seven(hole: [Card; 2], board: &[Card]) -> [Card; 7] {
    [
        hole[0], hole[1], board[0], board[1], board[2], board[3], board[4],
    ]
}

/// The chance that `hero` beats `villain` over every way to finish `board`, a tie counting
/// half. Slow and plain.
fn brute_equity(hero: [Card; 2], villain: [Card; 2], board: &[Card]) -> f64 {
    let dead = card_mask(&hero) | card_mask(&villain) | card_mask(board);
    let deck: Vec<Card> = (0..52).filter(|&c| dead & (1 << c) == 0).collect();
    let (mut score, mut boards) = (0.0, 0u32);
    let mut full = board.to_vec();
    each_choice(&deck, 5 - board.len(), 0, &mut Vec::new(), &mut |extra| {
        full.truncate(board.len());
        full.extend_from_slice(extra);
        let ours = BruteForceRanker.rank7(&seven(hero, &full));
        let theirs = BruteForceRanker.rank7(&seven(villain, &full));
        score += match ours.cmp(&theirs) {
            std::cmp::Ordering::Greater => 1.0,
            std::cmp::Ordering::Equal => 0.5,
            std::cmp::Ordering::Less => 0.0,
        };
        boards += 1;
    });
    score / boards as f64
}

/// The win probability against a weighted list of hands, by plain enumeration. Hands that
/// share a card with ours or the board cannot be held and are left out.
fn brute_win_probability(hero: [Card; 2], board: &[Card], range: &[([Card; 2], f64)]) -> f64 {
    let dead = card_mask(&hero) | card_mask(board);
    let (mut total, mut won) = (0.0, 0.0);
    for &(villain, weight) in range {
        if card_mask(&villain) & dead == 0 {
            total += weight;
            won += weight * brute_equity(hero, villain, board);
        }
    }
    won / total
}

fn to_range(hands: &[([Card; 2], f64)]) -> Range {
    let mut range = Range::empty();
    for &(h, w) in hands {
        range.set(h, w);
    }
    range
}

#[test]
fn small_ranges_by_hand() {
    // (our hand, board, the opponent's range with weights)
    let cases = [
        // River: we hold top pair. One hand beats us, one ties, two lose, and As Ac cannot
        // be held (we have the As).
        (
            "As Kd",
            "Ks 9h 6d 4c 2s",
            vec![
                ("9c 9d", 1.0),
                ("Ah Kc", 2.0),
                ("Qh Jh", 0.5),
                ("Kh Tc", 1.5),
                ("As Ac", 9.0),
            ],
        ),
        // Turn: a flush draw and a gutshot against made hands and a better draw.
        (
            "Ah 5h",
            "Kh Th 7s 4c",
            vec![
                ("Kd Qd", 1.0),
                ("7d 7c", 0.25),
                ("Qh Jh", 3.0),
                ("9s 8s", 1.0),
                ("Td 9d", 2.0),
            ],
        ),
        // Flop: an overpair against sets, draws and overcards.
        (
            "Qs Qc",
            "Jh 8h 3d",
            vec![
                ("8s 8c", 1.0),
                ("Ah Kh", 2.0),
                ("Ts 9s", 1.5),
                ("Ad Jd", 1.0),
                ("Kd Qd", 0.5),
            ],
        ),
        // Flop, paired board: quads, full houses and split pots are possible.
        (
            "7d 7h",
            "7s 2c 2d",
            vec![
                ("2h 2s", 1.0),
                ("Ac 2h", 1.0),
                ("Ks Kd", 2.0),
                ("7c 2s", 1.0),
            ],
        ),
    ];
    for (hero, board, range) in cases {
        let hero = hand(hero);
        let board = cards(board);
        let range: Vec<([Card; 2], f64)> = range.iter().map(|&(h, w)| (hand(h), w)).collect();
        let want = brute_win_probability(hero, &board, &range);
        let got = win_probability(hero, &board, &to_range(&range)).unwrap();
        assert!(
            (got - want).abs() < 1e-12,
            "{hero:?} on {board:?}: {got} against {want}"
        );
    }
}

#[test]
fn the_river_case_worked_out_on_paper() {
    // As Kd on Ks 9h 6d 4c 2s: a pair of kings, ace kicker. 9c 9d (a set) wins, Ah Kc ties,
    // Qh Jh and Kh Tc lose. Weights 1, 2, 0.5, 1.5: (2 * 0.5 + 0.5 + 1.5) / 5 = 0.6.
    let range = to_range(&[
        (hand("9c 9d"), 1.0),
        (hand("Ah Kc"), 2.0),
        (hand("Qh Jh"), 0.5),
        (hand("Kh Tc"), 1.5),
    ]);
    let wp = win_probability(hand("As Kd"), &cards("Ks 9h 6d 4c 2s"), &range).unwrap();
    assert!((wp - 0.6).abs() < 1e-15, "{wp}");
    // No hand left in the range: no answer.
    let blocked = to_range(&[(hand("As Ac"), 1.0), (hand("Ks Qs"), 1.0)]);
    assert_eq!(
        win_probability(hand("As Kd"), &cards("Ks 9h 6d 4c 2s"), &blocked),
        None
    );
}

#[test]
fn random_small_ranges_on_every_street() {
    let mut rng = Rng::new(7_2026);
    // Brute force is slow on the flop (990 boards per hand), so fewer cases there.
    for (board_len, cases, range_size) in [(5, 40, 30), (4, 12, 12), (3, 4, 5)] {
        for _ in 0..cases {
            let mut deck: [Card; 52] = std::array::from_fn(|i| i as Card);
            rng.shuffle(&mut deck);
            let hero = [deck[0], deck[1]];
            let board = &deck[2..2 + board_len];
            // Hands drawn from the whole deck, so some share a card with ours or the board.
            let range: Vec<([Card; 2], f64)> = (0..range_size)
                .map(|_| {
                    let a = rng.below(52) as Card;
                    let b = (a + 1 + rng.below(51) as Card) % 52;
                    ([a, b], 0.25 + rng.below(8) as f64 * 0.25)
                })
                .collect();
            // The same hand drawn twice keeps its last weight, in both calculations.
            let range: Vec<([Card; 2], f64)> = {
                let r = to_range(&range);
                r.live().map(|(i, w)| (combo_cards(i), w)).collect()
            };
            let dead = card_mask(&hero) | card_mask(board);
            if range.iter().all(|(h, _)| card_mask(h) & dead != 0) {
                continue;
            }
            let want = brute_win_probability(hero, board, &range);
            let got = win_probability(hero, board, &to_range(&range)).unwrap();
            assert!(
                (got - want).abs() < 1e-12,
                "{hero:?} on {board:?}: {got} against {want}"
            );
        }
    }
}

#[test]
fn every_hand_on_the_turn_and_river() {
    // The whole table of equities, not just a weighted sum: each of the 1,326 entries.
    for (hero, board) in [("Jc Td", "9h 8s 2c Kd 3h"), ("6s 6d", "Ah 6h 5h Qc")] {
        let hero = hand(hero);
        let board = cards(board);
        let mut table = [0.0; NUM_COMBOS];
        showdown_equities(hero, &board, &mut table);
        let dead = card_mask(&hero) | card_mask(&board);
        let mut live = 0;
        for (i, &got) in table.iter().enumerate() {
            let villain = combo_cards(i);
            if card_mask(&villain) & dead != 0 {
                assert_eq!(got, 0.0, "{villain:?} cannot be held");
                continue;
            }
            live += 1;
            let want = brute_equity(hero, villain, &board);
            assert!(
                (got - want).abs() < 1e-12,
                "{hero:?} against {villain:?}: {got} against {want}"
            );
        }
        let unseen = 50 - board.len();
        assert_eq!(live, unseen * (unseen - 1) / 2);
    }
}

// ----- before the flop -----

/// Exact preflop equity of one hand against another over all 1,712,304 boards, with the
/// fast evaluator (the brute-force ranker would take minutes).
fn exact_preflop(hero: [Card; 2], villain: [Card; 2]) -> f64 {
    let to = |c: Card| eval::Card::from_index(c).unwrap();
    let dead = card_mask(&hero) | card_mask(&villain);
    let deck: Vec<eval::Card> = (0..52).filter(|&c| dead & (1 << c) == 0).map(to).collect();
    let ours = eval::Hand::new().add(to(hero[0])).add(to(hero[1]));
    let theirs = eval::Hand::new().add(to(villain[0])).add(to(villain[1]));
    let (mut score2, mut boards) = (0u64, 0u64);
    let n = deck.len();
    for a in 0..n {
        for b in a + 1..n {
            for c in b + 1..n {
                for d in c + 1..n {
                    for e in d + 1..n {
                        let add = |h: eval::Hand| {
                            h.add(deck[a])
                                .add(deck[b])
                                .add(deck[c])
                                .add(deck[d])
                                .add(deck[e])
                        };
                        let (x, y) = (add(ours).eval7(), add(theirs).eval7());
                        score2 += 2 * (x > y) as u64 + (x == y) as u64;
                        boards += 1;
                    }
                }
            }
        }
    }
    assert_eq!(boards, 1_712_304);
    score2 as f64 / (2.0 * boards as f64)
}

#[test]
fn sampled_preflop_is_close_to_exact() {
    let boards = 4_000;
    for (hero, villain) in [("As Ah", "Ks Kh"), ("7h 2c", "Ah Kh")] {
        let (hero, villain) = (hand(hero), hand(villain));
        let exact = exact_preflop(hero, villain);
        let mut table = [0.0; NUM_COMBOS];
        preflop_equities_sampled(hero, boards, &mut Rng::new(11), &mut table);
        let got = table[combo_index(villain[0], villain[1])];
        // About 82% of sampled boards avoid the opponent's two cards.
        let std_err = (exact * (1.0 - exact) / (0.82 * boards as f64)).sqrt();
        assert!(
            (got - exact).abs() < 4.0 * std_err,
            "{hero:?} against {villain:?}: sampled {got}, exact {exact}"
        );
        // Hands holding one of our cards cannot be held.
        assert_eq!(table[combo_index(hero[0], 0)], 0.0);
    }
    // Against the whole range the error is far smaller than against one hand.
    let hero = hand("Ad Ac");
    let mut table = [0.0; NUM_COMBOS];
    preflop_equities_sampled(hero, boards, &mut Rng::new(12), &mut table);
    let mut range = Range::uniform();
    range.remove_cards(card_mask(&hero));
    let wp: f64 = range.live().map(|(i, w)| w * table[i]).sum::<f64>() / range.total();
    assert!(
        (wp - 0.852).abs() < 0.02,
        "aces against a random hand: {wp}"
    );
}

/// Minutes in a debug build (4 billion evaluations): run with
/// `cargo test --release -p lbr -- --ignored`.
#[test]
#[ignore = "slow in a debug build; run with --release -- --ignored"]
fn exact_preflop_table_matches_enumeration() {
    // Two classes, with our suits in an order that makes the table rename them.
    for (hero, villains) in [
        (
            "Ks Kh",
            vec![
                "As Ah", "Ad Kd", "Kc Qs", "7s 6s", "7h 6h", "7d 6d", "2c 2d", "Qh Js",
            ],
        ),
        (
            "2s 7d",
            vec![
                "7s 2d", "As Ks", "Ad Kd", "Ah Kh", "9d 8d", "9s 8s", "7c 7h", "2d 2h",
            ],
        ),
    ] {
        let hero = hand(hero);
        let mut table = [0.0; NUM_COMBOS];
        preflop_equities(hero, &mut table);
        for villain in villains {
            let villain = hand(villain);
            let got = table[combo_index(villain[0], villain[1])];
            let want = exact_preflop(hero, villain);
            assert!(
                (got - want).abs() < 1e-12,
                "{hero:?} against {villain:?}: {got} against {want}"
            );
        }
        assert_eq!(table[combo_index(hero[0], 0)], 0.0);
        // The other way round is the same hand.
        let mut swapped = [0.0; NUM_COMBOS];
        preflop_equities([hero[1], hero[0]], &mut swapped);
        assert_eq!(table, swapped);
    }
    // Against a random hand: the well-known numbers, 82.40% for kings and 34.58% for 7-2
    // offsuit.
    for (hero, known) in [("Ks Kh", 0.8240), ("2s 7d", 0.3458)] {
        let wp = win_probability(hand(hero), &[], &Range::uniform()).unwrap();
        println!("{hero} against a random hand: {wp:.6}");
        assert!((wp - known).abs() < 5e-4, "{hero}: {wp}");
    }
}
