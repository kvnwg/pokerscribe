//! Showdown equity on the flop: for every pair of combos (one out of position, one in
//! position), the chance the first wins plus half the chance of a tie, over every turn and
//! river that neither holds. Exact: all 1,176 runouts of the 49 cards left, each pair of
//! hands that share no card meeting on exactly C(45, 2) = 990 of them. Used for the flop's
//! all-in calls, and for checked-down values where the blueprint can't follow the hand.

use eval::Hand;
use nlhe::Card;
use rayon::prelude::*;

use crate::cards::{combo_cards, eval_card};

/// Runouts a pair of disjoint hands meets on the flop: C(45, 2).
pub const RUNOUTS_PER_PAIR: f64 = 990.0;

/// `w[i * n_ip + j]`: out-of-position combo `i` against in-position combo `j` (0 when they
/// share a card).
pub struct Equity {
    pub n: [usize; 2],
    pub w: Vec<f32>,
}

/// The equity table for `combos[0]` against `combos[1]` (lbr combo indices) on a flop.
pub fn flop_equity(flop: &[Card], combos: [&[usize]; 2]) -> Equity {
    assert_eq!(flop.len(), 3, "a flop has three cards");
    let board = Hand::from_cards(&flop.iter().map(|&c| eval_card(c)).collect::<Vec<_>>());
    let dead: u64 = flop.iter().fold(0, |m, &c| m | 1 << c);
    let left: Vec<Card> = (0..52).filter(|&c| dead & (1 << c) == 0).collect();
    let mut runouts = Vec::with_capacity(left.len() * (left.len() - 1) / 2);
    for (i, &a) in left.iter().enumerate() {
        for &b in &left[i + 1..] {
            runouts.push((a, b));
        }
    }
    let cards = combos.map(|list| {
        list.iter()
            .map(|&c| {
                let [a, b] = combo_cards(c);
                (a, b, (1u64 << a) | (1u64 << b))
            })
            .collect::<Vec<_>>()
    });
    let (n0, n1) = (cards[0].len(), cards[1].len());
    let chunk = runouts
        .len()
        .div_ceil(rayon::current_num_threads().max(1) * 4);
    let total: Vec<u32> = runouts
        .par_chunks(chunk.max(1))
        .map(|part| {
            let mut acc = vec![0u16; n0 * n1];
            let mut r0 = vec![0u16; n0];
            let mut r1 = vec![0u16; n1];
            let mut m1 = vec![0u16; n1];
            for &(t, r) in part {
                let full = board.add(eval_card(t)).add(eval_card(r));
                let mask = (1u64 << t) | (1u64 << r);
                for (k, &(a, b, m)) in cards[1].iter().enumerate() {
                    if m & mask == 0 {
                        r1[k] = full.add(eval_card(a)).add(eval_card(b)).eval7().value();
                        m1[k] = u16::MAX;
                    } else {
                        r1[k] = 0;
                        m1[k] = 0;
                    }
                }
                for (k, &(a, b, m)) in cards[0].iter().enumerate() {
                    r0[k] = if m & mask == 0 {
                        full.add(eval_card(a)).add(eval_card(b)).eval7().value()
                    } else {
                        0
                    };
                }
                for (i, &ri) in r0.iter().enumerate() {
                    if ri == 0 {
                        continue;
                    }
                    let row = &mut acc[i * n1..(i + 1) * n1];
                    for ((x, &rj), &mj) in row.iter_mut().zip(&r1).zip(&m1) {
                        let score = 2 * (ri > rj) as u16 + (ri == rj) as u16;
                        *x += score & mj;
                    }
                }
            }
            acc.into_iter().map(u32::from).collect::<Vec<u32>>()
        })
        .reduce(
            || vec![0u32; n0 * n1],
            |mut a, b| {
                a.iter_mut().zip(&b).for_each(|(x, y)| *x += y);
                a
            },
        );
    let mut w = vec![0f32; n0 * n1];
    for i in 0..n0 {
        for j in 0..n1 {
            if cards[0][i].2 & cards[1][j].2 == 0 {
                w[i * n1 + j] = (total[i * n1 + j] as f64 / (2.0 * RUNOUTS_PER_PAIR)) as f32;
            }
        }
    }
    Equity { n: [n0, n1], w }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cards::combo_index;
    use nlhe::parse_card;

    fn c(s: &str) -> Card {
        parse_card(s).unwrap()
    }

    #[test]
    fn equity_against_plain_enumeration() {
        let flop = [c("Kh"), c("7d"), c("2c")];
        let a = [
            combo_index(c("Ah"), c("Ad")),
            combo_index(c("7h"), c("7s")),
            combo_index(c("Qh"), c("Jh")),
            combo_index(c("Kd"), c("Kh")), // blocked by the flop's Kh: never asked here
        ];
        let b = [
            combo_index(c("Ks"), c("Qs")),
            combo_index(c("Ac"), c("Ah")),
            combo_index(c("9h"), c("8h")),
        ];
        let e = flop_equity(&flop, [&a[..3], &b[..]]);
        for (i, &x) in a[..3].iter().enumerate() {
            for (j, &y) in b.iter().enumerate() {
                let [p, q] = combo_cards(x);
                let [r, s] = combo_cards(y);
                let dead: u64 = [p, q, r, s, flop[0], flop[1], flop[2]]
                    .iter()
                    .fold(0, |m, &c| m | 1 << c);
                if (1u64 << p | 1u64 << q) & (1u64 << r | 1u64 << s) != 0 {
                    assert_eq!(e.w[i * 3 + j], 0.0);
                    continue;
                }
                let (mut win, mut n) = (0.0, 0.0);
                for t in 0..52u8 {
                    for u in t + 1..52u8 {
                        if dead & (1 << t | 1 << u) != 0 {
                            continue;
                        }
                        let board: Vec<eval::Card> =
                            flop.iter().chain(&[t, u]).map(|&c| eval_card(c)).collect();
                        let h = Hand::from_cards(&board);
                        let s0 = h.add(eval_card(p)).add(eval_card(q)).eval7().value();
                        let s1 = h.add(eval_card(r)).add(eval_card(s)).eval7().value();
                        win += if s0 > s1 {
                            1.0
                        } else if s0 == s1 {
                            0.5
                        } else {
                            0.0
                        };
                        n += 1.0;
                    }
                }
                assert_eq!(n, RUNOUTS_PER_PAIR);
                assert!((e.w[i * 3 + j] as f64 - win / n).abs() < 1e-6);
            }
        }
    }
}
