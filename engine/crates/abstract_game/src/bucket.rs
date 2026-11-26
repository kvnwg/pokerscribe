//! Card abstraction: a [`Bucketer`] puts a player's hole cards on a board into a bucket,
//! and the abstract game treats every hand in a bucket alike. The real hand grouping
//! (potential-aware clustering) lives in its own crate and plugs in through the trait.
//! Two simple bucketers ship here:
//!
//! - [`Lossless`]: one bucket for each hand that really differs. Hands that are the same
//!   up to renaming the suits share a bucket and nothing else does. For tiny games.
//! - [`EquityBands`]: a few bands of hand strength on each street. Quick and crude, for
//!   tests.

use std::rc::Rc;
use std::sync::Arc;

use nlhe::{Card, Street};

use crate::ranker::to_eval;

/// Groups hands into buckets, street by street.
pub trait Bucketer {
    /// How many buckets hands fall into on `street`, for size counts. Ids normally run
    /// from 0 to this number, but they do not have to: the game only needs two hands to
    /// get the same id exactly when they are in the same bucket.
    fn num_buckets(&self, street: Street) -> u64;

    /// The bucket of `hole` on `board`. The board has 0, 3, 4 or 5 cards, which says
    /// what street it is; its first three cards are the flop. The answer must not depend
    /// on the order of the two hole cards or of the three flop cards.
    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64;
}

macro_rules! forward {
    ($($t:ty),*) => {$(
        impl<B: Bucketer + ?Sized> Bucketer for $t {
            fn num_buckets(&self, street: Street) -> u64 {
                (**self).num_buckets(street)
            }
            fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
                (**self).bucket(hole, board)
            }
        }
    )*};
}
forward!(&B, Box<B>, Rc<B>, Arc<B>);

/// The street a board of this many cards belongs to.
pub fn street_of(board: &[Card]) -> Street {
    match board.len() {
        0 => Street::Preflop,
        3 => Street::Flop,
        4 => Street::Turn,
        5 => Street::River,
        n => panic!("a board has 0, 3, 4 or 5 cards, not {n}"),
    }
}

// ----- starting hands -----

/// Number of starting hand classes: 13 pairs, 78 suited and 78 offsuit hands.
pub const PREFLOP_CLASSES: usize = 169;

const RANK_NAMES: &[u8; 13] = b"AKQJT98765432";

/// The class of a starting hand, 0 to 168, in chart order: rows and columns run from ace
/// to two, pairs are on the diagonal, suited hands above it and offsuit hands below.
/// AA is 0, AKs 1, AKo 13 and 22 is 168. `app/solver/pushfold.py` uses the same order.
pub fn preflop_class(hole: [Card; 2]) -> u8 {
    let (a, b) = (hole[0] / 4, hole[1] / 4);
    let high = 12 - a.max(b);
    let low = 12 - a.min(b);
    if hole[0] % 4 == hole[1] % 4 {
        high * 13 + low
    } else {
        low * 13 + high
    }
}

/// The usual name of a class: `"AKs"`, `"T9o"`, `"77"`.
pub fn class_name(class: u8) -> String {
    let (row, col) = ((class / 13) as usize, (class % 13) as usize);
    let (high, low) = (row.min(col), row.max(col));
    let mut name = String::with_capacity(3);
    name.push(RANK_NAMES[high] as char);
    name.push(RANK_NAMES[low] as char);
    if row < col {
        name.push('s');
    } else if row > col {
        name.push('o');
    }
    name
}

/// The class with this name, the inverse of [`class_name`].
pub fn class_from_name(name: &str) -> Option<u8> {
    let b = name.as_bytes();
    let rank = |c: u8| RANK_NAMES.iter().position(|&r| r == c).map(|i| i as u8);
    let (high, low) = (rank(*b.first()?)?, rank(*b.get(1)?)?);
    match (b.len(), b.get(2)) {
        (2, _) if high == low => Some(high * 13 + low),
        (3, Some(b's')) if high < low => Some(high * 13 + low),
        (3, Some(b'o')) if high < low => Some(low * 13 + high),
        _ => None,
    }
}

/// How many of the 1,326 two-card hands are in a class: 6 for a pair, 4 suited, 12 offsuit.
pub fn class_combos(class: u8) -> u32 {
    let (row, col) = (class / 13, class % 13);
    match row.cmp(&col) {
        std::cmp::Ordering::Equal => 6,
        std::cmp::Ordering::Less => 4,
        std::cmp::Ordering::Greater => 12,
    }
}

// ----- lossless -----

/// How many hands really differ on each street once suits are interchangeable: starting
/// hands; hole cards with a flop; with a flop and a turn; with a flop, turn and river.
/// A test recounts all four with Burnside's lemma.
pub const LOSSLESS_BUCKETS: [u64; 4] = [169, 1_286_792, 55_190_538, 2_428_287_420];

/// No card abstraction: two hands share a bucket only when one becomes the other by
/// renaming suits (the hole cards, the flop, the turn card and the river card each
/// matching). Preflop the ids are the 169 classes of [`preflop_class`]. From the flop on
/// the id is a code for the hand's canonical form, so ids are exact but have gaps: they
/// run up to about 2.9e7 on the flop, 1.5e9 on the turn and 7.9e10 on the river.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Lossless;

/// The 24 ways to rename four suits.
const SUIT_PERMUTATIONS: [[u8; 4]; 24] = {
    let mut out = [[0u8; 4]; 24];
    let mut n = 0;
    let mut code = 0;
    while code < 256 {
        let p = [code & 3, (code >> 2) & 3, (code >> 4) & 3, (code >> 6) & 3];
        let mut seen = 0;
        let mut i = 0;
        while i < 4 {
            seen |= 1 << p[i];
            i += 1;
        }
        if seen == 0b1111 {
            out[n] = [p[0] as u8, p[1] as u8, p[2] as u8, p[3] as u8];
            n += 1;
        }
        code += 1;
    }
    assert!(n == 24);
    out
};

/// Number of ways to pick 3 cards of 52: the flop's part of a lossless id.
const FLOPS: u64 = 22_100;

/// A card with its suit renamed.
#[inline]
fn rename(card: Card, suits: &[u8; 4]) -> u64 {
    ((card & !3) | suits[(card & 3) as usize]) as u64
}

/// The code of one hand as it is dealt: its hole cards as a set, its flop as a set, then
/// the turn and the river.
fn lossless_code(hole: [Card; 2], board: &[Card], suits: &[u8; 4]) -> u64 {
    let (a, b) = (rename(hole[0], suits), rename(hole[1], suits));
    let (a, b) = (a.min(b), a.max(b));
    let mut flop = [
        rename(board[0], suits),
        rename(board[1], suits),
        rename(board[2], suits),
    ];
    flop.sort_unstable();
    let [x, y, z] = flop;
    // Combinations numbered in order: C(b, 2) + a, and C(z, 3) + C(y, 2) + x.
    let mut code = (b * (b - 1) / 2 + a) * FLOPS + z * (z - 1) * (z - 2) / 6 + y * (y - 1) / 2 + x;
    for &card in &board[3..] {
        code = code * 52 + rename(card, suits);
    }
    code
}

impl Bucketer for Lossless {
    fn num_buckets(&self, street: Street) -> u64 {
        LOSSLESS_BUCKETS[street.index()]
    }

    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
        if street_of(board) == Street::Preflop {
            return preflop_class(hole) as u64;
        }
        // The smallest code among the 24 renamings is the same for every hand that is
        // this hand with its suits renamed, and for no other.
        SUIT_PERMUTATIONS
            .iter()
            .map(|suits| lossless_code(hole, board, suits))
            .min()
            .expect("24 renamings")
    }
}

// ----- equity bands -----

/// Each starting hand's chance of beating a random hand all in before the flop (a split
/// counts half), from the exact table in `app/solver/data/preflop_equity.npz`.
#[rustfmt::skip]
pub const PREFLOP_STRENGTH: [f64; PREFLOP_CLASSES] = [
    // Made by tests/fixtures/make_push_fold.py --strength; chart order, AA first.
    0.85204, 0.67045, 0.66209, 0.65393, 0.64602, 0.62781, 0.61944, 0.60984, 0.59906, 0.59923, 0.59034, 0.58220, 0.57379,
    0.65320, 0.82396, 0.63400, 0.62567, 0.61789, 0.59988, 0.58312, 0.57538, 0.56641, 0.55793, 0.54885, 0.54055, 0.53212,
    0.64432, 0.61456, 0.79925, 0.60259, 0.59468, 0.57664, 0.56018, 0.54302, 0.53613, 0.52769, 0.51855, 0.51019, 0.50169,
    0.63563, 0.60569, 0.58135, 0.77469, 0.57528, 0.55662, 0.54016, 0.52325, 0.50606, 0.49987, 0.49070, 0.48232, 0.47378,
    0.62722, 0.59739, 0.57291, 0.55248, 0.75012, 0.54028, 0.52334, 0.50639, 0.48941, 0.47216, 0.46530, 0.45693, 0.44839,
    0.60773, 0.57812, 0.55360, 0.53251, 0.51532, 0.72057, 0.50801, 0.49118, 0.47428, 0.45722, 0.43862, 0.43264, 0.42415,
    0.59873, 0.56020, 0.53600, 0.51490, 0.49721, 0.48097, 0.69163, 0.47936, 0.46243, 0.44545, 0.42702, 0.40874, 0.40272,
    0.58841, 0.55187, 0.51766, 0.49682, 0.47908, 0.46298, 0.45051, 0.66236, 0.45372, 0.43676, 0.41849, 0.40036, 0.38156,
    0.57682, 0.54223, 0.51024, 0.47844, 0.46092, 0.44491, 0.43241, 0.42323, 0.63285, 0.43133, 0.41333, 0.39534, 0.37669,
    0.57697, 0.53314, 0.50120, 0.47181, 0.44251, 0.42669, 0.41428, 0.40512, 0.39944, 0.60325, 0.41453, 0.39693, 0.37849,
    0.56730, 0.52327, 0.49128, 0.46186, 0.43504, 0.40671, 0.39447, 0.38550, 0.38010, 0.38155, 0.57023, 0.38642, 0.36829,
    0.55845, 0.51426, 0.48219, 0.45276, 0.42595, 0.40020, 0.37484, 0.36602, 0.36078, 0.36265, 0.35146, 0.53693, 0.35984,
    0.54929, 0.50509, 0.47295, 0.44348, 0.41668, 0.39098, 0.36828, 0.34584, 0.34075, 0.34285, 0.33200, 0.32303, 0.50334,
];

/// A few bands of hand strength on each street: quick to compute and good enough to
/// test with, not a serious abstraction.
///
/// Before the flop the 169 starting hands are ranked by their chance against a random
/// hand ([`PREFLOP_STRENGTH`]) and cut into bands of as near as possible the same number
/// of classes; with 169 bands or more every class is its own bucket. From the flop on
/// the score is [`hand_strength`], the share of the other player's possible hands this
/// hand beats on the board as it stands, cut into equal bands. That score ignores cards
/// still to come, so a flush draw counts as the high card it is now.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EquityBands {
    bands: [u32; 4],
    preflop: [u8; PREFLOP_CLASSES],
}

impl EquityBands {
    /// `bands[s]` bands on street `s` (preflop, flop, turn, river), each at least 1.
    pub fn new(bands: [u32; 4]) -> EquityBands {
        assert!(bands.iter().all(|&n| n >= 1), "a street needs a band");
        let first = bands[0].min(PREFLOP_CLASSES as u32);
        let mut order: Vec<u8> = (0..PREFLOP_CLASSES as u8).collect();
        order.sort_by(|&a, &b| {
            PREFLOP_STRENGTH[a as usize]
                .total_cmp(&PREFLOP_STRENGTH[b as usize])
                .then(b.cmp(&a))
        });
        let mut preflop = [0u8; PREFLOP_CLASSES];
        for (place, &class) in order.iter().enumerate() {
            preflop[class as usize] = if first as usize == PREFLOP_CLASSES {
                class
            } else {
                (place * first as usize / PREFLOP_CLASSES) as u8
            };
        }
        EquityBands {
            bands: [first, bands[1], bands[2], bands[3]],
            preflop,
        }
    }

    /// The same number of bands on every street.
    pub fn uniform(bands: u32) -> EquityBands {
        EquityBands::new([bands; 4])
    }
}

/// The share of the other player's possible hole cards that `hole` beats on this board
/// of 3, 4 or 5 cards, a tie counting half. Cards still to come are ignored.
pub fn hand_strength(hole: [Card; 2], board: &[Card]) -> f64 {
    let mut used = 0u64;
    let mut table = eval::Hand::new();
    for &card in board {
        used |= 1 << card;
        table = table.add(to_eval(card));
    }
    used |= 1 << hole[0] | 1 << hole[1];
    let mine = table.add(to_eval(hole[0])).add(to_eval(hole[1])).eval();
    let (mut wins, mut ties, mut total) = (0u32, 0u32, 0u32);
    for a in 0..52u8 {
        if used >> a & 1 == 1 {
            continue;
        }
        let with_a = table.add(to_eval(a));
        for b in a + 1..52 {
            if used >> b & 1 == 1 {
                continue;
            }
            let theirs = with_a.add(to_eval(b)).eval();
            total += 1;
            wins += (mine > theirs) as u32;
            ties += (mine == theirs) as u32;
        }
    }
    (wins as f64 + 0.5 * ties as f64) / total as f64
}

impl Bucketer for EquityBands {
    fn num_buckets(&self, street: Street) -> u64 {
        self.bands[street.index()] as u64
    }

    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
        let street = street_of(board);
        if street == Street::Preflop {
            return self.preflop[preflop_class(hole) as usize] as u64;
        }
        let bands = self.bands[street.index()] as u64;
        ((hand_strength(hole, board) * bands as f64) as u64).min(bands - 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cfr::Rng;
    use nlhe::parse_card;
    use std::collections::{HashMap, HashSet};

    fn cards(text: &str) -> Vec<Card> {
        text.split_whitespace()
            .map(|c| parse_card(c).unwrap())
            .collect()
    }

    fn hole(text: &str) -> [Card; 2] {
        cards(text).try_into().unwrap()
    }

    /// `count` different cards, in random order.
    fn deal(rng: &mut Rng, count: usize) -> Vec<Card> {
        let mut deck: Vec<Card> = (0..52).collect();
        for i in 0..count {
            let j = i + rng.below(52 - i);
            deck.swap(i, j);
        }
        deck.truncate(count);
        deck
    }

    #[test]
    fn the_169_starting_hands() {
        assert_eq!(preflop_class(hole("As Ah")), 0);
        assert_eq!(preflop_class(hole("Kd Ad")), 1);
        assert_eq!(preflop_class(hole("Kd Ah")), 13);
        assert_eq!(preflop_class(hole("2c 2d")), 168);
        assert_eq!(class_name(1), "AKs");
        assert_eq!(class_name(13), "AKo");
        assert_eq!(class_name(preflop_class(hole("9h Td"))), "T9o");
        assert_eq!(class_name(preflop_class(hole("7s 2s"))), "72s");
        assert_eq!(class_from_name("32o"), Some(preflop_class(hole("3c 2d"))));
        for bad in ["", "A", "AKx", "KAs", "AAs", "AK", "1Ks"] {
            assert_eq!(class_from_name(bad), None, "{bad}");
        }

        // Every two-card hand falls in a class, each class with the right number of hands.
        let mut combos = [0u32; PREFLOP_CLASSES];
        for a in 0..52 {
            for b in a + 1..52 {
                let class = preflop_class([a, b]);
                assert_eq!(class, preflop_class([b, a]));
                assert_eq!(Lossless.bucket([a, b], &[]), class as u64);
                combos[class as usize] += 1;
            }
        }
        for class in 0..PREFLOP_CLASSES as u8 {
            assert_eq!(combos[class as usize], class_combos(class));
            assert_eq!(class_from_name(&class_name(class)), Some(class));
        }
        assert_eq!(combos.iter().sum::<u32>(), 1_326);
        assert_eq!(Lossless.num_buckets(Street::Preflop), 169);
    }

    #[test]
    fn suit_permutations_are_the_24() {
        let distinct: HashSet<[u8; 4]> = SUIT_PERMUTATIONS.into_iter().collect();
        assert_eq!(distinct.len(), 24);
        assert_eq!(SUIT_PERMUTATIONS[0], [3, 2, 1, 0]);
        assert!(SUIT_PERMUTATIONS.contains(&[0, 1, 2, 3]));
    }

    #[test]
    fn lossless_ignores_suit_names_and_card_order() {
        let mut rng = Rng::new(11);
        for round in 0..2_000 {
            let d = deal(&mut rng, 7);
            let n = [3, 4, 5][round % 3];
            let id = Lossless.bucket([d[0], d[1]], &d[2..2 + n]);
            // Renaming suits changes nothing.
            let suits = SUIT_PERMUTATIONS[rng.below(24)];
            let r: Vec<Card> = d.iter().map(|&c| rename(c, &suits) as Card).collect();
            assert_eq!(Lossless.bucket([r[0], r[1]], &r[2..2 + n]), id);
            // Nor does the order of the hole cards or of the flop.
            let mut board = d[2..2 + n].to_vec();
            board.swap(0, 2);
            board.swap(1, 2);
            assert_eq!(Lossless.bucket([d[1], d[0]], &board), id);
            // Ids stay inside the code space of their street.
            assert!(id < [29_304_600, 1_523_839_200, 79_239_638_400][n - 3]);
        }
    }

    #[test]
    fn lossless_separates_hands_that_differ() {
        let l = Lossless;
        let b = |h: &str, board: &str| l.bucket(hole(h), &cards(board));
        // The same up to suits.
        assert_eq!(b("As Ks", "Qs 7d 2c"), b("Ah Kh", "Qh 7c 2s"));
        assert_eq!(b("As Ad", "Ah 7c 7d"), b("Ac Ah", "As 7d 7h"));
        // A flush draw is not the same hand as no draw.
        assert_ne!(b("As Ks", "Qs 7s 2c"), b("As Ks", "Qs 7d 2c"));
        // Which card came on the turn matters: flop Q72 then a 9 is not flop Q97 then a 2.
        assert_ne!(b("As Ks", "Qs 7d 2c 9h"), b("As Ks", "Qs 7d 9h 2c"));
        // And likewise turn against river.
        assert_ne!(b("As Ks", "Qs 7d 2c 9h 3h"), b("As Ks", "Qs 7d 2c 3h 9h"));
        // Hole cards are not board cards.
        assert_ne!(b("As Ks", "Qs 7d 2c"), b("As Qs", "Ks 7d 2c"));

        // On random pairs of deals: same id exactly when some renaming of the suits turns
        // one into the other.
        let key = |h: [Card; 2], board: &[Card], suits: &[u8; 4]| {
            let r = |c: Card| rename(c, suits) as Card;
            let mut hole = [r(h[0]), r(h[1])];
            hole.sort_unstable();
            let mut flop = [r(board[0]), r(board[1]), r(board[2])];
            flop.sort_unstable();
            let rest: Vec<Card> = board[3..].iter().map(|&c| r(c)).collect();
            (hole, flop, rest)
        };
        let mut rng = Rng::new(5);
        let mut same = 0;
        for round in 0..20_000 {
            // Two ranks only, so that matching hands turn up often.
            let n = [3, 4][round % 2];
            let pick = |rng: &mut Rng| -> Vec<Card> {
                let mut d: Vec<Card> = Vec::new();
                while d.len() < 2 + n {
                    let c = (rng.below(2) * 4 + rng.below(4)) as Card;
                    if !d.contains(&c) {
                        d.push(c);
                    }
                }
                d
            };
            let (x, y) = (pick(&mut rng), pick(&mut rng));
            let plain = key([x[0], x[1]], &x[2..], &[0, 1, 2, 3]);
            let matches = SUIT_PERMUTATIONS
                .iter()
                .any(|s| key([y[0], y[1]], &y[2..], s) == plain);
            let ids = (
                l.bucket([x[0], x[1]], &x[2..]),
                l.bucket([y[0], y[1]], &y[2..]),
            );
            assert_eq!(ids.0 == ids.1, matches, "{x:?} {y:?}");
            same += matches as u32;
        }
        println!("{same} of 20,000 pairs match");
        assert!(
            same > 300,
            "only {same} matching pairs: the check is too weak"
        );
    }

    /// Burnside's lemma: the number of hands that differ up to suits is the average,
    /// over the 24 renamings, of the number of deals a renaming leaves unchanged. This
    /// counts those deals directly, without the canonical codes.
    #[test]
    fn lossless_counts_by_burnside() {
        let mut totals = [0u128; 4];
        for suits in &SUIT_PERMUTATIONS {
            let r = |c: u8| rename(c, suits) as u8;
            let fixed: Vec<u8> = (0..52).filter(|&c| r(c) == c).collect();
            // Sets of two and of three cards the renaming maps onto themselves, as masks.
            let mut pairs = Vec::new();
            let mut triples = Vec::new();
            for a in 0..52u8 {
                for b in a + 1..52 {
                    let set = 1u64 << a | 1 << b;
                    if 1u64 << r(a) | 1 << r(b) == set {
                        pairs.push(set);
                    }
                    for c in b + 1..52 {
                        let set = set | 1 << c;
                        if 1u64 << r(a) | 1 << r(b) | 1 << r(c) == set {
                            triples.push(set);
                        }
                    }
                }
            }
            let fixed_mask: u64 = fixed.iter().map(|&c| 1u64 << c).sum();
            totals[0] += pairs.len() as u128;
            for &hole in &pairs {
                for &flop in &triples {
                    if hole & flop != 0 {
                        continue;
                    }
                    // The turn and the river must each be a card the renaming keeps.
                    let free = (fixed_mask & !(hole | flop)).count_ones() as u128;
                    totals[1] += 1;
                    totals[2] += free;
                    totals[3] += free * free.saturating_sub(1);
                }
            }
        }
        for (street, total) in totals.iter().enumerate() {
            assert_eq!(total % 24, 0);
            assert_eq!(
                (total / 24) as u64,
                LOSSLESS_BUCKETS[street],
                "street {street}"
            );
        }
    }

    /// Every flop deal, through the canonical codes: 1,286,792 different ids, and each
    /// holds as many deals as Burnside's count says in total.
    #[test]
    #[cfg_attr(
        debug_assertions,
        ignore = "slow in a debug build: cargo test --release"
    )]
    fn lossless_flop_ids_counted_one_by_one() {
        let mut sizes: HashMap<u64, u32> = HashMap::with_capacity(1_300_000);
        let mut deals = 0u64;
        for a in 0..52u8 {
            for b in a + 1..52 {
                for x in 0..52u8 {
                    if x == a || x == b {
                        continue;
                    }
                    for y in x + 1..52 {
                        if y == a || y == b {
                            continue;
                        }
                        for z in y + 1..52 {
                            if z == a || z == b {
                                continue;
                            }
                            *sizes
                                .entry(Lossless.bucket([a, b], &[x, y, z]))
                                .or_default() += 1;
                            deals += 1;
                        }
                    }
                }
            }
        }
        assert_eq!(deals, 1_326 * 19_600);
        assert_eq!(sizes.len() as u64, LOSSLESS_BUCKETS[1]);
        // A hand has at most 24 suit-renamed copies, and the number divides 24.
        assert!(sizes.values().all(|&n| 24 % n == 0));
    }

    #[test]
    fn preflop_strength_matches_sampled_showdowns() {
        // The table came from Python. Check a spread of classes against showdowns dealt
        // and ranked here: each must sit within four standard errors.
        let mut rng = Rng::new(2026);
        for name in ["AA", "72o", "AKs", "JTs", "55", "K9o", "32o", "Q6s", "T8o"] {
            let class = class_from_name(name).unwrap();
            let (row, col) = (class / 13, class % 13);
            let (high, low) = (12 - row.min(col), 12 - row.max(col));
            let samples = 40_000;
            let mut score = 0.0;
            for _ in 0..samples {
                // Two cards of the class with random suits, then seven more cards.
                let suit = rng.below(4) as u8;
                let other = if row < col {
                    suit
                } else {
                    (suit + 1 + rng.below(3) as u8) % 4
                };
                let mine = [high * 4 + suit, low * 4 + other];
                assert_eq!(preflop_class(mine), class);
                let rest: Vec<Card> = deal(&mut rng, 9)
                    .into_iter()
                    .filter(|c| !mine.contains(c))
                    .take(7)
                    .collect();
                let board = rest[2..]
                    .iter()
                    .fold(eval::Hand::new(), |h, &c| h.add(to_eval(c)));
                let my_rank = board.add(to_eval(mine[0])).add(to_eval(mine[1])).eval7();
                let their_rank = board.add(to_eval(rest[0])).add(to_eval(rest[1])).eval7();
                score += match my_rank.cmp(&their_rank) {
                    std::cmp::Ordering::Greater => 1.0,
                    std::cmp::Ordering::Equal => 0.5,
                    std::cmp::Ordering::Less => 0.0,
                };
            }
            let mean = score / samples as f64;
            let error = 4.0 * (0.25 / samples as f64).sqrt() + 1e-5;
            let table = PREFLOP_STRENGTH[class as usize];
            assert!(
                (mean - table).abs() < error,
                "{name}: sampled {mean}, table {table}"
            );
        }
        // Aces are best, three-two offsuit is worst.
        let best = PREFLOP_STRENGTH.iter().cloned().fold(0.0, f64::max);
        let worst = PREFLOP_STRENGTH.iter().cloned().fold(1.0, f64::min);
        assert_eq!(best, PREFLOP_STRENGTH[0]);
        assert_eq!(
            worst,
            PREFLOP_STRENGTH[class_from_name("32o").unwrap() as usize]
        );
    }

    #[test]
    fn hand_strength_by_hand() {
        // The nuts beat everything.
        assert_eq!(hand_strength(hole("As Ks"), &cards("Qs Js Ts 2d 3c")), 1.0);
        // Playing the board: a royal flush on the table ties every hand.
        assert_eq!(hand_strength(hole("2c 3d"), &cards("As Ks Qs Js Ts")), 0.5);
        // Top set on a flop with no straight or flush: only one ace is left, so nobody
        // can match three aces.
        assert_eq!(hand_strength(hole("Ah Ad"), &cards("As 7c 2d")), 1.0);
        // Seven high with no pair on the river: loses to almost everything.
        assert!(hand_strength(hole("7c 2d"), &cards("As Ks 9h 5d 3c")) < 0.05);
        // By hand: on K K K K 2 the ace kicker plays. 45 cards are left, 3 of them aces.
        // Of the 990 other hands, the 3 x 42 + 3 = 129 that hold an ace tie and the other
        // 861 lose.
        let s = hand_strength(hole("Ac 3d"), &cards("Ks Kh Kd Kc 2h"));
        assert!((s - (861.0 + 0.5 * 129.0) / 990.0).abs() < 1e-12);
        // Order does not matter.
        assert_eq!(
            hand_strength(hole("Ah Kd"), &cards("Qs 7c 2d 9h")),
            hand_strength(hole("Kd Ah"), &cards("2d Qs 7c 9h"))
        );
    }

    #[test]
    fn equity_bands() {
        let bands = EquityBands::new([10, 6, 5, 4]);
        for (street, n) in Street::ALL.into_iter().zip([10, 6, 5, 4]) {
            assert_eq!(bands.num_buckets(street), n);
        }
        // Before the flop: bands hold 16 or 17 classes each, aces at the top, the worst
        // hands at the bottom, and a better hand is never in a lower band.
        let mut counts = [0; 10];
        for class in 0..PREFLOP_CLASSES {
            counts[bands.preflop[class] as usize] += 1;
        }
        assert!(counts.iter().all(|&c| c == 16 || c == 17), "{counts:?}");
        assert_eq!(bands.bucket(hole("As Ah"), &[]), 9);
        assert_eq!(bands.bucket(hole("3c 2d"), &[]), 0);
        for (a, strong) in PREFLOP_STRENGTH.iter().enumerate() {
            for (b, weak) in PREFLOP_STRENGTH.iter().enumerate() {
                if strong > weak {
                    assert!(bands.preflop[a] >= bands.preflop[b]);
                }
            }
        }
        // 169 bands or more: every class on its own.
        let all = EquityBands::uniform(500);
        assert_eq!(all.num_buckets(Street::Preflop), 169);
        assert_eq!(all.bucket(hole("Kd Ah"), &[]), 13);
        assert_eq!(all.num_buckets(Street::River), 500);

        // After the flop: the nuts in the top band, air in the bottom one, and every
        // id within range.
        assert_eq!(bands.bucket(hole("Ah Ad"), &cards("As 7c 2d")), 5);
        assert_eq!(bands.bucket(hole("As Ks"), &cards("Qs Js Ts 2d 3c")), 3);
        assert_eq!(bands.bucket(hole("7c 2d"), &cards("As Ks 9h 5d 3c")), 0);
        let mut rng = Rng::new(3);
        let mut seen = [[false; 10]; 4];
        for round in 0..3_000 {
            let d = deal(&mut rng, 7);
            let n = [0, 3, 4, 5][round % 4];
            let id = bands.bucket([d[0], d[1]], &d[2..2 + n]);
            let street = street_of(&d[2..2 + n]);
            assert!(id < bands.num_buckets(street));
            seen[street.index()][id as usize] = true;
            assert_eq!(id, bands.bucket([d[1], d[0]], &d[2..2 + n]));
        }
        // Every band is used.
        for (street, n) in [10, 6, 5, 4].into_iter().enumerate() {
            assert!(seen[street][..n].iter().all(|&s| s), "street {street}");
        }
        // Through a reference, a box and an Arc.
        let boxed: Box<dyn Bucketer> = Box::new(bands.clone());
        assert_eq!(boxed.num_buckets(Street::Flop), 6);
        fn aces<B: Bucketer>(bucketer: B) -> u64 {
            bucketer.bucket(hole("As Ah"), &[])
        }
        assert_eq!(aces(&bands), 9);
        assert_eq!(Arc::new(Lossless).bucket(hole("As Ah"), &[]), 0);
    }

    #[test]
    #[should_panic(expected = "0, 3, 4 or 5 cards")]
    fn a_board_of_two_cards_panics() {
        Lossless.bucket([0, 1], &[2, 3]);
    }
}
