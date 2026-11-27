//! Win probabilities: the chance of beating each hand the opponent could hold when the rest
//! of the board is dealt and nobody bets again (the paper's `WpRollout`).

use std::sync::OnceLock;

use eval::Hand;
use nlhe::{Card, Rng};
use rayon::prelude::*;

use crate::range::{card_mask, combo_cards, combo_index, Range, NUM_COMBOS};
use crate::ranker::ecard;

/// For each of the 1,326 opposing hands (by [`combo_index`]): the probability that our hand
/// beats it at showdown, a tie counting as half a win. Hands sharing a card with ours or with
/// the board get 0.
pub type EquityTable = [f64; NUM_COMBOS];

/// Compares our hand with every hand made of two of `rest` on one complete board and adds 2
/// for a win and 1 for a tie. `rest` is in rising order and holds neither our cards nor the
/// board's.
#[inline]
fn tally(board: Hand, hero: [eval::Card; 2], rest: &[Card], wins2: &mut [u32; NUM_COMBOS]) {
    let hero_rank = board.add(hero[0]).add(hero[1]).eval7();
    debug_assert!(rest.len() <= 45);
    let mut six = [board; 45];
    for (slot, &c) in six.iter_mut().zip(rest) {
        *slot = board.add(ecard(c));
    }
    for i in 1..rest.len() {
        let hi = rest[i] as usize;
        let hi_card = ecard(rest[i]);
        let row = &mut wins2[hi * (hi - 1) / 2..][..hi];
        for j in 0..i {
            let rank = six[j].add(hi_card).eval7();
            row[rest[j] as usize] += 2 * (hero_rank > rank) as u32 + (hero_rank == rank) as u32;
        }
    }
}

/// The cards of `unseen` that are not in `picked`, in the same order.
#[inline]
fn without(unseen: &[Card], picked: u64, out: &mut [Card; 52]) -> usize {
    let mut n = 0;
    for &c in unseen {
        if picked & (1 << c) == 0 {
            out[n] = c;
            n += 1;
        }
    }
    n
}

/// Deals every set of `k` more board cards from `unseen[start..]` and tallies each board.
fn enumerate(
    unseen: &[Card],
    k: usize,
    start: usize,
    board: Hand,
    picked: u64,
    hero: [eval::Card; 2],
    wins2: &mut [u32; NUM_COMBOS],
) {
    if k == 0 {
        let mut rest = [0; 52];
        let n = without(unseen, picked, &mut rest);
        tally(board, hero, &rest[..n], wins2);
        return;
    }
    for i in start..=unseen.len() - k {
        let c = unseen[i];
        enumerate(
            unseen,
            k - 1,
            i + 1,
            board.add(ecard(c)),
            picked | 1 << c,
            hero,
            wins2,
        );
    }
}

fn binomial(n: u64, k: u64) -> u64 {
    (0..k).fold(1, |acc, i| acc * (n - i) / (i + 1))
}

/// The cards not in `dead`, in rising order.
fn unseen_cards(dead: u64) -> Vec<Card> {
    (0..52).filter(|&c| dead & (1 << c) == 0).collect()
}

/// Exact equities by dealing every possible rest of the board (none on the river, 46 rivers
/// on the turn, 1,081 turn and river pairs on the flop, 2,118,760 boards before the flop).
fn enumerate_equities(hole: [Card; 2], board: &[Card], out: &mut EquityTable) {
    let dead = card_mask(&hole) | card_mask(board);
    assert_eq!(
        dead.count_ones() as usize,
        2 + board.len(),
        "the hole cards and the board share a card"
    );
    let unseen = unseen_cards(dead);
    let to_come = 5 - board.len();
    let hero = [ecard(hole[0]), ecard(hole[1])];
    let start = board.iter().fold(Hand::new(), |h, &c| h.add(ecard(c)));
    let mut wins2 = [0u32; NUM_COMBOS];
    enumerate(&unseen, to_come, 0, start, 0, hero, &mut wins2);

    // Every opposing hand meets the same number of boards: those without its two cards.
    let boards = binomial(unseen.len() as u64 - 2, to_come as u64);
    let scale = 1.0 / (2.0 * boards as f64);
    out.fill(0.0);
    for (i, slot) in out.iter_mut().enumerate() {
        let [a, b] = combo_cards(i);
        if dead & (1 << a | 1 << b) == 0 {
            *slot = wins2[i] as f64 * scale;
        }
    }
}

/// Equities on the flop, turn or river (`board` has 3, 4 or 5 cards), exact: every way to
/// finish the board is dealt.
///
/// On the flop that is 1,081 boards times 990 hands, about a million evaluations.
pub fn showdown_equities(hole: [Card; 2], board: &[Card], out: &mut EquityTable) {
    assert!(
        (3..=5).contains(&board.len()),
        "a board of {} cards; before the flop use preflop_equities",
        board.len()
    );
    enumerate_equities(hole, board, out);
}

// ----- before the flop -----

/// One table per starting-hand class (13 pairs, 78 suited, 78 offsuit), filled on first use.
static PREFLOP: [OnceLock<Box<EquityTable>>; 169] = [const { OnceLock::new() }; 169];

/// A hole-card class with one hand standing for it, and the suit change that turns the
/// given hand into that one.
struct Canonical {
    class: usize,
    hole: [Card; 2],
    suit_map: [u8; 4],
}

fn canonical(hole: [Card; 2]) -> Canonical {
    // Higher rank first; for a pair, lower suit first.
    let (a, b) = if hole[0] / 4 > hole[1] / 4 || (hole[0] / 4 == hole[1] / 4 && hole[0] < hole[1]) {
        (hole[0], hole[1])
    } else {
        (hole[1], hole[0])
    };
    let (hi, lo) = ((a / 4) as usize, (b / 4) as usize);
    let (suit_a, suit_b) = ((a % 4) as usize, (b % 4) as usize);
    let suited = suit_a == suit_b;
    let class = if hi == lo {
        hi
    } else {
        13 + if suited { 0 } else { 78 } + hi * (hi - 1) / 2 + lo
    };
    let mut suit_map = [u8::MAX; 4];
    suit_map[suit_a] = 0;
    let mut next = 1;
    if !suited {
        suit_map[suit_b] = 1;
        next = 2;
    }
    for slot in &mut suit_map {
        if *slot == u8::MAX {
            *slot = next;
            next += 1;
        }
    }
    Canonical {
        class,
        hole: [a / 4 * 4, b / 4 * 4 + !suited as u8],
        suit_map,
    }
}

/// Equities before the flop, exact: all 2,118,760 boards are dealt against all 1,225 hands.
///
/// That is about 2 billion evaluations (several seconds in a release build, minutes in a
/// debug build), so the result is kept per starting-hand class for the life of the process
/// and other hands of the class are read off it by renaming suits. A whole match touches
/// all 169 classes: about a quarter of an hour of CPU time, once. See
/// [`warm_preflop_table`] and [`preflop_equities_sampled`].
pub fn preflop_equities(hole: [Card; 2], out: &mut EquityTable) {
    let canon = canonical(hole);
    let table = PREFLOP[canon.class].get_or_init(|| {
        let mut table = Box::new([0.0; NUM_COMBOS]);
        enumerate_equities(canon.hole, &[], &mut table);
        table
    });
    let dead = card_mask(&hole);
    let rename = |c: Card| c / 4 * 4 + canon.suit_map[(c % 4) as usize];
    out.fill(0.0);
    for (i, slot) in out.iter_mut().enumerate() {
        let [a, b] = combo_cards(i);
        if dead & (1 << a | 1 << b) == 0 {
            *slot = table[combo_index(rename(a), rename(b))];
        }
    }
}

/// Fills the exact preflop table for all 169 starting-hand classes on all cores, so a match
/// that plays local best response before the flop does not stall on first use.
pub fn warm_preflop_table() {
    let mut class_hands = Vec::with_capacity(169);
    for hi in 0..13u8 {
        class_hands.push([hi * 4, hi * 4 + 1]);
        for lo in 0..hi {
            class_hands.push([hi * 4, lo * 4]);
            class_hands.push([hi * 4, lo * 4 + 1]);
        }
    }
    class_hands.into_par_iter().for_each(|hole| {
        preflop_equities(hole, &mut [0.0; NUM_COMBOS]);
    });
}

/// Equities before the flop from `boards` random boards in place of all of them.
///
/// Each board is tallied against all 990 hands it leaves room for, so 1,000 boards cost
/// about a million evaluations and give the win probability against a wide range to within
/// about 1.5 points (one standard error). Hands no sampled board left room for get 0.5.
pub fn preflop_equities_sampled(
    hole: [Card; 2],
    boards: u32,
    rng: &mut Rng,
    out: &mut EquityTable,
) {
    let dead = card_mask(&hole);
    assert_eq!(dead.count_ones(), 2, "the hole cards are the same card");
    let unseen = unseen_cards(dead);
    let hero = [ecard(hole[0]), ecard(hole[1])];
    let mut wins2 = [0u32; NUM_COMBOS];
    let mut seen = [0u32; NUM_COMBOS];
    let mut rest = [0; 52];
    for _ in 0..boards {
        let mut deck = [0; 50];
        deck.copy_from_slice(&unseen);
        let mut board = Hand::new();
        let mut picked = 0u64;
        for i in 0..5 {
            let j = i + rng.below(50 - i as u64) as usize;
            deck.swap(i, j);
            board = board.add(ecard(deck[i]));
            picked |= 1 << deck[i];
        }
        let n = without(&unseen, picked, &mut rest);
        tally(board, hero, &rest[..n], &mut wins2);
        for i in 1..n {
            let hi = rest[i] as usize;
            let row = &mut seen[hi * (hi - 1) / 2..][..hi];
            for &lo in &rest[..i] {
                row[lo as usize] += 1;
            }
        }
    }
    out.fill(0.0);
    for (i, slot) in out.iter_mut().enumerate() {
        let [a, b] = combo_cards(i);
        if dead & (1 << a | 1 << b) == 0 {
            *slot = if seen[i] > 0 {
                wins2[i] as f64 / (2.0 * seen[i] as f64)
            } else {
                0.5
            };
        }
    }
}

/// The probability that `hole` wins at showdown against `range` once the board is complete,
/// a tie counting as half: every way to finish the board is dealt (exact on every street,
/// see [`preflop_equities`] for the cost before the flop).
///
/// Hands of the range that share a card with `hole` or `board` are left out. Returns `None`
/// when no hand is left.
pub fn win_probability(hole: [Card; 2], board: &[Card], range: &Range) -> Option<f64> {
    let mut equities = [0.0; NUM_COMBOS];
    if board.is_empty() {
        preflop_equities(hole, &mut equities);
    } else {
        showdown_equities(hole, board, &mut equities);
    }
    let dead = card_mask(&hole) | card_mask(board);
    let (mut total, mut won) = (0.0, 0.0);
    for (i, w) in range.live() {
        let [a, b] = combo_cards(i);
        if dead & (1 << a | 1 << b) == 0 {
            total += w;
            won += w * equities[i];
        }
    }
    (total > 0.0).then(|| won / total)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classes_cover_169_and_renaming_suits_gives_the_class_hand() {
        let mut seen = [0u32; 169];
        for b in 0..52u8 {
            for a in 0..b {
                let c = canonical([a, b]);
                seen[c.class] += 1;
                let rename = |x: Card| x / 4 * 4 + c.suit_map[(x % 4) as usize];
                let mut renamed = [rename(a), rename(b)];
                let mut class_hand = c.hole;
                renamed.sort_unstable();
                class_hand.sort_unstable();
                assert_eq!(renamed, class_hand);
                let mut suits = c.suit_map;
                suits.sort_unstable();
                assert_eq!(suits, [0, 1, 2, 3]);
                // The same class whichever card comes first.
                assert_eq!(canonical([b, a]).class, c.class);
                assert_eq!(canonical([b, a]).suit_map, c.suit_map);
            }
        }
        for (class, &n) in seen.iter().enumerate() {
            let want = if class < 13 {
                6
            } else if class < 91 {
                4
            } else {
                12
            };
            assert_eq!(n, want, "class {class}");
        }
    }

    #[test]
    fn binomials() {
        assert_eq!(binomial(45, 2), 990);
        assert_eq!(binomial(44, 1), 44);
        assert_eq!(binomial(43, 0), 1);
        assert_eq!(binomial(48, 5), 1_712_304);
    }
}
