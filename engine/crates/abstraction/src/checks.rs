//! Sanity checks on built tables: that the buckets group hands sensibly.
//!
//! The first checks hold for any deck. The rest name real hands and run only on the
//! 52-card deck. They are written to hold from 50 to 1,000 buckets a street, so they speak
//! of a bucket's equity and spread, not of bucket numbers.

use crate::deck::parse_cards;
use crate::rng::Rng;
use crate::table::{Feature, Street, Table};
use crate::Abstraction;

/// One check's outcome.
#[derive(Clone, Debug)]
pub struct CheckResult {
    pub name: String,
    pub passed: bool,
    pub detail: String,
}

fn result(name: impl Into<String>, passed: bool, detail: impl Into<String>) -> CheckResult {
    CheckResult {
        name: name.into(),
        passed,
        detail: detail.into(),
    }
}

fn choose(n: u64, k: u64) -> u64 {
    (0..k).fold(1, |r, i| r * (n - i) / (i + 1))
}

/// A view of one hand's bucket.
struct Seen {
    bucket: usize,
    /// The bucket's average showdown equity.
    equity: f32,
    /// How much the hands of the bucket still move: the standard deviation of the next
    /// street's bucket equity over the bucket's centre. 0 on the river.
    spread: f32,
    /// The share of the bucket's centre that lands in next-street buckets with an equity of
    /// 0.9 or more: how often its hands become very strong.
    strong_next: f32,
}

/// The equities of what a turn or flop table's centres are histograms over.
fn next_equities(abstraction: &Abstraction, street: Street) -> Option<Vec<f32>> {
    match street {
        Street::Flop => Some(abstraction.table(Street::Turn)?.equity.clone()),
        Street::Turn => match abstraction.table(Street::Turn)?.header().settings.feature {
            Feature::EquityBins { bins } => {
                Some((0..bins).map(|b| (b as f32 + 0.5) / bins as f32).collect())
            }
            _ => Some(abstraction.table(Street::River)?.equity.clone()),
        },
        _ => None,
    }
}

fn see(abstraction: &Abstraction, hole: &str, board: &str) -> Seen {
    let hole = parse_cards(hole).expect("hole cards");
    let board = parse_cards(board).expect("board");
    let street = Street::from_board_cards(board.len()).expect("a flop, turn or river");
    let table: &Table = abstraction.table(street).expect("a table");
    let bucket = abstraction.bucket(&hole, &board) as usize;
    let (mut spread, mut strong_next) = (0.0, 0.0);
    if let Some(next) = next_equities(abstraction, street) {
        let dim = table.header().centroid_dim as usize;
        let centre = &table.centroids[bucket * dim..(bucket + 1) * dim];
        let mean: f64 = centre
            .iter()
            .zip(&next)
            .map(|(&s, &e)| s as f64 * e as f64)
            .sum();
        let variance: f64 = centre
            .iter()
            .zip(&next)
            .map(|(&s, &e)| s as f64 * (e as f64 - mean) * (e as f64 - mean))
            .sum();
        spread = variance.sqrt() as f32;
        strong_next = centre
            .iter()
            .zip(&next)
            .filter(|(_, &e)| e >= 0.9)
            .map(|(&s, _)| s)
            .sum();
    }
    Seen {
        bucket,
        equity: table.equity[bucket],
        spread,
        strong_next,
    }
}

/// Runs every check that applies to the abstraction's deck.
pub fn run(abstraction: &Abstraction) -> Vec<CheckResult> {
    let mut out = general(abstraction);
    if abstraction.deck().ranks() == 13 {
        out.extend(real_deck(abstraction));
    }
    out
}

/// Checks that hold for any deck.
pub fn general(abstraction: &Abstraction) -> Vec<CheckResult> {
    let mut out = Vec::new();
    let deck = abstraction.deck();
    let n = deck.len() as u64;
    for street in [Street::Flop, Street::Turn, Street::River] {
        let table = abstraction.table(street).unwrap();
        let k = table.buckets();
        out.push(result(
            format!("{}: buckets are numbered by equity", street.name()),
            table.equity.windows(2).all(|w| w[0] <= w[1]),
            format!(
                "bucket 0 has equity {:.3}, bucket {} has {:.3}",
                table.equity[0],
                k - 1,
                table.equity[k - 1]
            ),
        ));
        let deals = choose(n, 2) * choose(n - 2, street.board_cards() as u64);
        let total: u64 = table.sizes.iter().sum();
        let smallest = *table.sizes.iter().min().unwrap();
        let largest = *table.sizes.iter().max().unwrap();
        out.push(result(
            format!(
                "{}: every deal is in a bucket and no bucket is empty",
                street.name()
            ),
            total == deals && smallest > 0,
            format!(
                "{total} deals in {k} buckets; the smallest holds {:.3}%, the largest {:.3}%",
                smallest as f64 * 100.0 / total as f64,
                largest as f64 * 100.0 / total as f64
            ),
        ));
    }

    // The same hand in other suits, with the cards in another order, has the same bucket.
    let mut rng = Rng::new(20_261_126);
    let mut differing = 0;
    let trials = 2_000;
    for _ in 0..trials {
        let mut cards: Vec<u8> = deck.cards().collect();
        for i in 0..7 {
            let j = i + rng.below((cards.len() - i) as u64) as usize;
            cards.swap(i, j);
        }
        let shift = 1 + rng.below(3) as u8;
        let swap = rng.below(2) == 1;
        let relabel = |c: &u8| {
            let suit = (c & 3) + shift;
            let suit = if swap { suit ^ 1 } else { suit };
            (c & !3) | (suit & 3)
        };
        for board in [0usize, 3, 4, 5] {
            let (hole, rest) = cards[..2 + board].split_at(2);
            let mut hole2: Vec<u8> = hole.iter().map(relabel).collect();
            let mut rest2: Vec<u8> = rest.iter().map(relabel).collect();
            hole2.reverse();
            rest2.reverse();
            differing +=
                (abstraction.bucket(hole, rest) != abstraction.bucket(&hole2, &rest2)) as usize;
        }
    }
    out.push(result(
        "the suits' names and the cards' order don't matter",
        differing == 0,
        format!("{trials} random hands on each street, {differing} changed bucket when relabelled"),
    ));
    out
}

/// Checks on named hands of the real deck.
pub fn real_deck(a: &Abstraction) -> Vec<CheckResult> {
    let mut out = Vec::new();

    // River. On Ks 9d 7h 4c 2s no straight or flush is possible: a set of kings is the
    // nuts, a set of nines loses only to it, a set of sevens only to those two.
    let board = "Ks9d7h4c2s";
    let nuts = see(a, "KhKd", board);
    let second = see(a, "9h9c", board);
    let third = see(a, "7s7c", board);
    let top = a.buckets(Street::River) - 1;
    out.push(result(
        "river: the nuts are in the top bucket",
        nuts.bucket == top && nuts.equity >= 0.95,
        format!(
            "KhKd on {board}: bucket {} of {}, equity {:.3}",
            nuts.bucket,
            top + 1,
            nuts.equity
        ),
    ));
    out.push(result(
        "river: the near-nuts sit with the nuts or just below",
        second.equity >= 0.93
            && third.equity >= 0.93
            && second.bucket * 20 >= top * 19
            && third.bucket * 20 >= top * 19,
        format!(
            "9h9c: bucket {}, equity {:.3}; 7s7c: bucket {}, equity {:.3} (nuts: bucket {})",
            second.bucket, second.equity, third.bucket, third.equity, nuts.bucket
        ),
    ));
    // The nut flush and the second nut flush lose to almost nothing either.
    let flush_board = "AhJh8h4c2d";
    let nut_flush = see(a, "KhQh", flush_board);
    let second_flush = see(a, "QhTh", flush_board);
    // With many buckets cut from equity alone the top ones are thin, and the two flushes can
    // be a bucket or two apart; they must still both be at the very top.
    let together = nut_flush.bucket == second_flush.bucket
        || (nut_flush.bucket > second_flush.bucket && second_flush.bucket * 50 >= top * 49);
    out.push(result(
        "river: the nut flush and the second nut flush sit together at the top",
        together && nut_flush.equity >= 0.95 && second_flush.equity >= 0.95,
        format!(
            "KhQh on {flush_board}: bucket {}; QhTh: bucket {}, equity {:.3}",
            nut_flush.bucket, second_flush.bucket, second_flush.equity
        ),
    ));
    let air = see(a, "5h3d", board);
    let also_air = see(a, "6h5d", board);
    out.push(result(
        "river: air sits apart, at the bottom",
        air.equity <= 0.06 && also_air.equity <= 0.06 && air.bucket * 20 <= top,
        format!(
            "5h3d on {board}: bucket {}, equity {:.3}; 6h5d: bucket {}, equity {:.3}",
            air.bucket, air.equity, also_air.bucket, also_air.equity
        ),
    ));
    let middle = see(a, "AcQd", board);
    let top_pair = see(a, "KcQc", board);
    out.push(result(
        "river: stronger hands are in higher buckets",
        air.bucket < middle.bucket
            && middle.bucket < top_pair.bucket
            && top_pair.bucket < second.bucket
            && second.bucket <= nuts.bucket,
        format!(
            "5h3d {} < AcQd {} < KcQc {} < 9h9c {} <= KhKd {}",
            air.bucket, middle.bucket, top_pair.bucket, second.bucket, nuts.bucket
        ),
    ));
    // A royal flush on the board: every hand ties.
    let chop = "AsKsQsJsTs";
    let chops = [
        see(a, "2c3d", chop),
        see(a, "AhAd", chop),
        see(a, "7c7d", chop),
    ];
    out.push(result(
        "river: with a royal flush on the board every hand is in one bucket",
        chops.iter().all(|s| s.bucket == chops[0].bucket)
            && (0.4..=0.65).contains(&chops[0].equity),
        format!("bucket {}, equity {:.3}", chops[0].bucket, chops[0].equity),
    ));
    // Aces and kings with a queen on the board: low hole cards don't play.
    let plays = "AsAdKsKdQh";
    let (low, other_low) = (see(a, "7c2d", plays), see(a, "8c3d", plays));
    let straight = see(a, "JcTd", plays);
    out.push(result(
        "river: hole cards that don't play share a bucket, a straight is above them",
        low.bucket == other_low.bucket && straight.bucket > low.bucket,
        format!(
            "7c2d and 8c3d on {plays}: buckets {} and {}; JcTd: bucket {}",
            low.bucket, other_low.bucket, straight.bucket
        ),
    ));

    // Turn, on Ah Kh 9c 2s.
    let turn = "AhKh9c2s";
    let set = see(a, "2c2d", turn);
    let two_pair = see(a, "AsKd", turn);
    let nothing = see(a, "6c5c", turn);
    out.push(result(
        "turn: a set and top two pair are near the top, air near the bottom",
        set.equity >= 0.9 && two_pair.equity >= 0.9 && nothing.equity <= 0.2,
        format!(
            "2c2d on {turn}: bucket {}, equity {:.3}; AsKd: bucket {}, equity {:.3}; 6c5c: bucket {}, equity {:.3}",
            set.bucket, set.equity, two_pair.bucket, two_pair.equity, nothing.bucket, nothing.equity
        ),
    ));
    // A flush draw is weak now and very strong on 9 river cards of 46. A weak hand with no
    // draw of about the same equity never is. They must not share a bucket, and the draw's
    // bucket must show the difference.
    let draw = see(a, "5h4h", turn);
    let made = see(a, "Jc6d", turn);
    out.push(result(
        "turn: a flush draw is apart from a no-draw hand of like equity",
        draw.bucket != made.bucket && draw.strong_next >= 0.08 && made.strong_next <= 0.03 && draw.spread > 1.3 * made.spread,
        format!(
            "5h4h on {turn}: bucket {}, equity {:.3}, very strong on {:.0}% of rivers, spread {:.3}; \
             Jc6d: bucket {}, equity {:.3}, very strong on {:.0}%, spread {:.3}",
            draw.bucket,
            draw.equity,
            draw.strong_next * 100.0,
            draw.spread,
            made.bucket,
            made.equity,
            made.strong_next * 100.0,
            made.spread
        ),
    ));

    // Flop, on 9h 8h 2c.
    let flop = "9h8h2c";
    let top_set = see(a, "9c9d", flop);
    let overpair = see(a, "AcAd", flop);
    let junk = see(a, "5c4c", flop);
    out.push(result(
        "flop: a set and an overpair are near the top, air near the bottom",
        top_set.equity >= 0.85 && overpair.equity >= 0.8 && junk.equity <= 0.3 && junk.bucket < overpair.bucket,
        format!(
            "9c9d on {flop}: bucket {}, equity {:.3}; AcAd: bucket {}, equity {:.3}; 5c4c: bucket {}, equity {:.3}",
            top_set.bucket, top_set.equity, overpair.bucket, overpair.equity, junk.bucket, junk.equity
        ),
    ));
    // 7h6h has a flush draw and a straight draw; 3c3d is a small pair. Both are middling
    // hands now with very different futures, and the draw's bucket must show that.
    let combo_draw = see(a, "7h6h", flop);
    let small_pair = see(a, "3c3d", flop);
    out.push(result(
        "flop: a combination draw is apart from a small pair",
        combo_draw.bucket != small_pair.bucket && combo_draw.spread > 1.3 * small_pair.spread,
        format!(
            "7h6h on {flop}: bucket {}, equity {:.3}, spread {:.3}; 3c3d: bucket {}, equity {:.3}, spread {:.3}",
            combo_draw.bucket, combo_draw.equity, combo_draw.spread, small_pair.bucket, small_pair.equity, small_pair.spread
        ),
    ));
    // Two nut flush draws with two overcards are the same kind of hand.
    let (akh, aqh) = (see(a, "AhKh", flop), see(a, "AhQh", flop));
    out.push(result(
        "flop: two nut flush draws with overcards are in the same bucket or next to it",
        (akh.equity - aqh.equity).abs() <= 0.03 && (akh.spread - aqh.spread).abs() <= 0.03,
        format!(
            "AhKh on {flop}: bucket {}, equity {:.3}, spread {:.3}; AhQh: bucket {}, equity {:.3}, spread {:.3}",
            akh.bucket, akh.equity, akh.spread, aqh.bucket, aqh.equity, aqh.spread
        ),
    ));
    out
}
