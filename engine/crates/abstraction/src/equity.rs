//! River showdowns: on one board, every pair of hole cards against every hand the opponent
//! can still hold.
//!
//! The hands are sorted by strength once. Walking up the sorted list with running counts
//! gives each hand its wins and ties in one pass; the counts are kept per card so the
//! opponent hands that share a card with ours are taken out again.
//!
//! The opponent's hands can be split into groups (the opponent clusters of OCHS). Then the
//! pass keeps one set of counts per group and gives the equity against each group.

use crate::deck::Deck;
use eval::{Card, Hand};

/// The showdown results of one board. Reused from board to board, so nothing is allocated
/// in the loop over boards.
pub struct Showdown {
    deck: Deck,
    groups: usize,
    /// The hole-card combinations of the last board, as card numbers `[a, b]` with `a < b`.
    combos: Vec<[u8; 2]>,
    /// Strength shifted left 16 bits, plus the combination's place in `combos`.
    sorted: Vec<u32>,
    group_of: Vec<u8>,
    /// `num[combo * groups + g]`: twice the wins plus the ties against group `g`.
    num: Vec<u16>,
    /// `den[combo * groups + g]`: twice the number of group `g` hands the opponent can hold.
    den: Vec<u16>,
    below: Vec<u32>,
    below_card: Vec<u32>,
    equal: Vec<u32>,
    equal_card: Vec<u32>,
    total: Vec<u32>,
    total_card: Vec<u32>,
}

impl Showdown {
    /// `groups` is the number of opponent groups: 1 for plain equity.
    pub fn new(deck: Deck, groups: usize) -> Showdown {
        assert!((1..=255).contains(&groups));
        Showdown {
            deck,
            groups,
            combos: Vec::new(),
            sorted: Vec::new(),
            group_of: Vec::new(),
            num: Vec::new(),
            den: Vec::new(),
            below: vec![0; groups],
            below_card: vec![0; groups * 52],
            equal: vec![0; groups],
            equal_card: vec![0; groups * 52],
            total: vec![0; groups],
            total_card: vec![0; groups * 52],
        }
    }

    /// Number of hole-card combinations on a river board: 1,081 in the full deck.
    pub fn combos_per_board(deck: Deck) -> usize {
        let n = deck.len() - 5;
        n * (n - 1) / 2
    }

    /// Twice the number of hands the opponent can hold when we hold two cards: the
    /// denominator of the plain equity, 1,980 in the full deck.
    pub fn equity_denominator(deck: Deck) -> u32 {
        let n = (deck.len() - 7) as u32;
        n * (n - 1)
    }

    /// Scores every hole-card combination on `board`. `group` gives the opponent group of
    /// two hole cards as `group[a * 52 + b]` with `a < b`; `None` puts every hand in group 0.
    pub fn run(&mut self, board: &[u8; 5], group: Option<&[u8]>) {
        let groups = self.groups;
        let mut on_board = 0u64;
        let mut board_hand = Hand::new();
        for &c in board {
            debug_assert!(self.deck.contains(c) && on_board & (1 << c) == 0);
            on_board |= 1 << c;
            board_hand = board_hand.add(Card::from_index(c).expect("card number under 52"));
        }

        self.combos.clear();
        self.sorted.clear();
        self.group_of.clear();
        self.total.fill(0);
        self.total_card.fill(0);
        for a in self.deck.cards() {
            if on_board & (1 << a) != 0 {
                continue;
            }
            let with_a = board_hand.add(Card::from_index(a).unwrap());
            for b in a + 1..52 {
                if on_board & (1 << b) != 0 {
                    continue;
                }
                let strength = with_a.add(Card::from_index(b).unwrap()).eval7().value();
                let g = match group {
                    Some(table) => table[a as usize * 52 + b as usize] as usize,
                    None => 0,
                };
                debug_assert!(g < groups);
                self.sorted.push((strength as u32) << 16 | self.combos.len() as u32);
                self.combos.push([a, b]);
                self.group_of.push(g as u8);
                self.total[g] += 1;
                self.total_card[g * 52 + a as usize] += 1;
                self.total_card[g * 52 + b as usize] += 1;
            }
        }
        self.sorted.sort_unstable();
        self.num.clear();
        self.num.resize(self.combos.len() * groups, 0);
        self.den.clear();
        self.den.resize(self.combos.len() * groups, 0);
        self.below.fill(0);
        self.below_card.fill(0);

        let mut start = 0;
        while start < self.sorted.len() {
            let strength = self.sorted[start] >> 16;
            let mut end = start + 1;
            while end < self.sorted.len() && self.sorted[end] >> 16 == strength {
                end += 1;
            }
            // Count the hands of this strength.
            for &key in &self.sorted[start..end] {
                let i = (key & 0xffff) as usize;
                let [a, b] = self.combos[i];
                let g = self.group_of[i] as usize;
                self.equal[g] += 1;
                self.equal_card[g * 52 + a as usize] += 1;
                self.equal_card[g * 52 + b as usize] += 1;
            }
            // Each of them beats what is below and ties what is equal, less the hands that
            // share a card with it. The hand itself is in both of its cards' counts and is
            // the only one, so it is added back once.
            for &key in &self.sorted[start..end] {
                let i = (key & 0xffff) as usize;
                let [a, b] = self.combos[i];
                let own = self.group_of[i] as usize;
                for g in 0..groups {
                    let (ga, gb) = (g * 52 + a as usize, g * 52 + b as usize);
                    let me = (g == own) as u32;
                    let wins = self.below[g] - self.below_card[ga] - self.below_card[gb];
                    let ties = self.equal[g] + me - self.equal_card[ga] - self.equal_card[gb];
                    let all = self.total[g] + me - self.total_card[ga] - self.total_card[gb];
                    self.num[i * groups + g] = (2 * wins + ties) as u16;
                    self.den[i * groups + g] = (2 * all) as u16;
                }
            }
            // Move them below.
            for &key in &self.sorted[start..end] {
                let i = (key & 0xffff) as usize;
                let [a, b] = self.combos[i];
                let g = self.group_of[i] as usize;
                self.below[g] += 1;
                self.below_card[g * 52 + a as usize] += 1;
                self.below_card[g * 52 + b as usize] += 1;
                self.equal[g] = 0;
                self.equal_card[g * 52 + a as usize] = 0;
                self.equal_card[g * 52 + b as usize] = 0;
            }
            start = end;
        }
    }

    /// The hole-card combinations of the last board.
    pub fn combos(&self) -> &[[u8; 2]] {
        &self.combos
    }

    /// Twice the wins plus the ties of combination `i` against every hand the opponent can
    /// hold. Divide by [`Showdown::equity_denominator`] for the equity.
    #[inline]
    pub fn equity_numerator(&self, i: usize) -> u16 {
        self.num[i * self.groups..(i + 1) * self.groups].iter().sum()
    }

    /// Combination `i` against group `g`: twice the wins plus the ties, and twice the number
    /// of hands. The second number is 0 when the opponent can't hold any hand of the group.
    #[inline]
    pub fn against_group(&self, i: usize, g: usize) -> (u16, u16) {
        (self.num[i * self.groups + g], self.den[i * self.groups + g])
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::deck::parse_cards;

    /// Equity by comparing with every opponent hand one at a time.
    fn slow_equity(board: &[u8], hole: [u8; 2], keep: impl Fn(u8, u8) -> bool) -> (u32, u32) {
        let hand = |a: u8, b: u8| {
            let mut h = Hand::new();
            for &c in board.iter().chain([a, b].iter()) {
                h = h.add(Card::from_index(c).unwrap());
            }
            h.eval7()
        };
        let mine = hand(hole[0], hole[1]);
        let (mut num, mut den) = (0, 0);
        for a in 0..52u8 {
            for b in a + 1..52 {
                if board.contains(&a) || board.contains(&b) || hole.contains(&a) || hole.contains(&b) {
                    continue;
                }
                if !keep(a, b) {
                    continue;
                }
                let theirs = hand(a, b);
                den += 2;
                num += match mine.cmp(&theirs) {
                    std::cmp::Ordering::Greater => 2,
                    std::cmp::Ordering::Equal => 1,
                    std::cmp::Ordering::Less => 0,
                };
            }
        }
        (num, den)
    }

    #[test]
    fn matches_one_at_a_time_counting() {
        // Three groups: pairs, suited hands, the rest.
        let group_of = |a: u8, b: u8| -> u8 {
            if a >> 2 == b >> 2 {
                0
            } else if a & 3 == b & 3 {
                1
            } else {
                2
            }
        };
        let mut table = vec![0u8; 52 * 52];
        for a in 0..52u8 {
            for b in a + 1..52 {
                table[a as usize * 52 + b as usize] = group_of(a, b);
            }
        }
        let mut plain = Showdown::new(Deck::FULL, 1);
        let mut grouped = Showdown::new(Deck::FULL, 3);
        for text in ["AhKhQhJh2c", "Ks9d7h4c2s", "8s8d8h3c3d", "AsKsQsJsTs", "2c3d4h5s7c"] {
            let board: [u8; 5] = parse_cards(text).unwrap().try_into().unwrap();
            plain.run(&board, None);
            grouped.run(&board, Some(&table));
            assert_eq!(plain.combos().len(), 1081);
            for (i, &hole) in plain.combos().iter().enumerate() {
                let (num, den) = slow_equity(&board, hole, |_, _| true);
                assert_eq!(den, 1980);
                assert_eq!(plain.equity_numerator(i) as u32, num, "{text} {hole:?}");
                assert_eq!(grouped.equity_numerator(i) as u32, num, "{text} {hole:?}");
                if i % 7 == 0 {
                    for g in 0..3u8 {
                        let (num, den) = slow_equity(&board, hole, |a, b| group_of(a, b) == g);
                        let got = grouped.against_group(i, g as usize);
                        assert_eq!((got.0 as u32, got.1 as u32), (num, den), "{text} {hole:?} group {g}");
                    }
                }
            }
        }
    }

    #[test]
    fn a_royal_flush_on_the_board_ties_everyone() {
        let board: [u8; 5] = parse_cards("AsKsQsJsTs").unwrap().try_into().unwrap();
        let mut s = Showdown::new(Deck::FULL, 1);
        s.run(&board, None);
        for i in 0..s.combos().len() {
            assert_eq!(s.equity_numerator(i), 990);
        }
    }

    #[test]
    fn small_deck_denominator() {
        let deck = Deck::new(6);
        assert_eq!(Showdown::combos_per_board(deck), 19 * 18 / 2);
        assert_eq!(Showdown::equity_denominator(deck), 17 * 16);
        let board: [u8; 5] = parse_cards("AsKd9h9cTs").unwrap().try_into().unwrap();
        let mut s = Showdown::new(deck, 1);
        s.run(&board, None);
        assert_eq!(s.combos().len(), 171);
        assert!(s.combos().iter().all(|c| c[0] >= 28 && c[1] >= 28));
        let total: u32 = (0..171).map(|i| s.equity_numerator(i) as u32).sum();
        // Every pair of hands that can meet shares 2 points.
        let meetings = 171 * (17 * 16 / 2) / 2;
        assert_eq!(total, 2 * meetings);
    }
}
