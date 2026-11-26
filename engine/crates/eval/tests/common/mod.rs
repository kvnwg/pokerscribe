//! Helpers shared by the integration tests.
#![allow(dead_code)]

use eval::{Card, HandRank, eval5};

/// SplitMix64 (Steele, Lea, Flood 2014), the generator tools/reference/eval_fixtures.py uses.
pub struct SplitMix64(pub u64);

impl SplitMix64 {
    pub fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// `n` distinct cards: partial Fisher-Yates on a fresh sorted deck.
    pub fn deal(&mut self, n: usize) -> Vec<Card> {
        let mut deck: Vec<u8> = (0..52).collect();
        for i in 0..n {
            let j = i + (self.next() % (52 - i) as u64) as usize;
            deck.swap(i, j);
        }
        deck[..n]
            .iter()
            .map(|&i| Card::from_index(i).unwrap())
            .collect()
    }
}

/// A slow, plain evaluator kept apart from the crate's tables: category 0..8 then the
/// ranks that break ties, compared as a tuple.
pub fn naive5(cards: &[Card; 5]) -> (u8, Vec<u8>) {
    let mut ranks: Vec<u8> = cards.iter().map(|c| c.rank()).collect();
    ranks.sort_unstable_by(|a, b| b.cmp(a));
    let flush = cards.iter().all(|c| c.suit() == cards[0].suit());
    let distinct = {
        let mut d = ranks.clone();
        d.dedup();
        d
    };
    let straight_top = if distinct.len() == 5 && ranks[0] - ranks[4] == 4 {
        Some(ranks[0])
    } else if ranks == [12, 3, 2, 1, 0] {
        Some(3)
    } else {
        None
    };
    if let Some(top) = straight_top {
        return (if flush { 8 } else { 4 }, vec![top]);
    }
    if flush {
        return (5, ranks);
    }
    // Ranks ordered by how often they appear, then by rank.
    let mut by_count: Vec<(usize, u8)> = distinct
        .iter()
        .map(|&r| (ranks.iter().filter(|&&x| x == r).count(), r))
        .collect();
    by_count.sort_unstable_by(|a, b| b.cmp(a));
    let counts: Vec<usize> = by_count.iter().map(|x| x.0).collect();
    let category = match counts.as_slice() {
        [4, 1] => 7,
        [3, 2] => 6,
        [3, 1, 1] => 3,
        [2, 2, 1] => 2,
        [2, 1, 1, 1] => 1,
        _ => 0,
    };
    (category, by_count.iter().map(|x| x.1).collect())
}

/// Best `eval5` over every 5-card subset.
pub fn best_of_subsets(cards: &[Card]) -> HandRank {
    let n = cards.len();
    let mut best = None;
    for mask in 0u32..(1 << n) {
        if mask.count_ones() == 5 {
            let five: Vec<Card> = (0..n)
                .filter(|i| mask >> i & 1 == 1)
                .map(|i| cards[i])
                .collect();
            let r = eval5(&five.try_into().unwrap());
            best = best.max(Some(r));
        }
    }
    best.unwrap()
}
