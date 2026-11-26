//! Suit isomorphism: one index for every set of hands that differ only by a relabelling of
//! the suits.
//!
//! The method is Kevin Waugh's ("A Fast and Optimal Hand Isomorphism Algorithm", 2013),
//! written from the paper:
//!
//! 1. Cards come in rounds (hole cards, then the board). Inside a round the order of the
//!    cards doesn't matter.
//! 2. For each suit, take the ranks it holds in each round. Number that list of rank sets:
//!    the first round's set by its place among sets of its size, the next round's set by its
//!    place among sets drawn from the ranks still unused in that suit, and so on.
//! 3. A suit's *shape* is how many cards it has in each round. Sort the four suits by shape,
//!    then by number. The four shapes together are the hand's *configuration*.
//! 4. Suits with the same shape are interchangeable, so their numbers are combined as a
//!    multiset. Groups with different shapes are combined as a mixed-radix number.
//! 5. The index is the configuration's offset plus that number.
//!
//! The index is perfect: every index in `0..size()` is used, and two hands share an index
//! exactly when one is a suit relabelling of the other.

use crate::deck::Deck;

/// At most this many rounds (hole cards, flop, turn, river).
pub const MAX_ROUNDS: usize = 4;
/// At most this many cards in a hand.
pub const MAX_CARDS: usize = 7;

const SUITS: usize = 4;
/// Bits of a suit's shape used per round: a suit holds at most 7 cards in a round.
const SHAPE_BITS: u32 = 3;
/// A suit's number sits in the low bits of its sort key, its shape above.
const NUMBER_BITS: u32 = 40;

/// `n` choose `k` for small `k`, exact while the result fits in a `u64`.
#[inline]
fn choose(n: u64, k: u32) -> u64 {
    if (k as u64) > n {
        return 0;
    }
    let mut r: u128 = 1;
    for i in 0..k as u128 {
        r = r * (n as u128 - i) / (i + 1);
    }
    r as u64
}

/// Tables over 13-bit rank sets, shared by every indexer.
struct SetTables {
    /// Place of a rank set among the sets with as many ranks, smallest number first.
    rank_of: [u16; 1 << 13],
    /// The rank sets of each size, smallest number first. The first `C(n, k)` use only the
    /// lowest `n` ranks.
    sets: [Vec<u16>; 8],
    binom: [[u32; 8]; 14],
}

fn set_tables() -> &'static SetTables {
    static TABLES: std::sync::OnceLock<SetTables> = std::sync::OnceLock::new();
    TABLES.get_or_init(|| {
        let mut rank_of = [0u16; 1 << 13];
        let mut sets: [Vec<u16>; 8] = Default::default();
        for mask in 0u16..(1 << 13) {
            let size = mask.count_ones() as usize;
            if size < 8 {
                rank_of[mask as usize] = sets[size].len() as u16;
                sets[size].push(mask);
            }
        }
        let mut binom = [[0u32; 8]; 14];
        for (n, row) in binom.iter_mut().enumerate() {
            for (k, cell) in row.iter_mut().enumerate() {
                *cell = choose(n as u64, k as u32) as u32;
            }
        }
        SetTables {
            rank_of,
            sets,
            binom,
        }
    })
}

/// The ranks of `set` renumbered after the ranks in `used` are taken out of the deck.
#[inline]
fn squeeze(set: u16, used: u16) -> u16 {
    let mut out = 0u16;
    let mut rest = set;
    while rest != 0 {
        let bit = rest & rest.wrapping_neg();
        out |= 1 << ((bit - 1) & !used).count_ones();
        rest ^= bit;
    }
    out
}

/// The inverse of [`squeeze`].
#[inline]
fn expand(squeezed: u16, used: u16) -> u16 {
    let mut out = 0u16;
    let mut free = !used;
    let mut rest = squeezed;
    while rest != 0 {
        let bit = free & free.wrapping_neg();
        if rest & 1 != 0 {
            out |= bit;
        }
        rest >>= 1;
        free ^= bit;
    }
    out
}

/// One way to split the rounds' cards over the four suits, suits sorted by shape.
#[derive(Clone, Debug)]
struct Config {
    /// The four shapes, largest first, packed 12 bits each.
    key: u64,
    /// First index of this configuration.
    offset: u64,
    /// `count[suit][round]`.
    count: [[u8; MAX_ROUNDS]; SUITS],
    /// For a suit that starts a group of equal shapes: how many suits are in the group.
    /// Zero for the other suits.
    group_len: [u8; SUITS],
    /// For a suit that starts a group: how many multisets the group has.
    group_size: [u64; SUITS],
}

/// Indexes hands of one shape of deal, for example 2 hole cards then 3 board cards.
///
/// Cards are numbered `rank * 4 + suit` as everywhere in the engine. A hand is passed as a
/// slice: the first round's cards, then the next round's, in any order inside a round.
pub struct HandIndexer {
    deck: Deck,
    rounds: Vec<u8>,
    cards: usize,
    configs: Vec<Config>,
    /// Open-addressed map from a configuration's key to its place in `configs`.
    slots: Vec<(u64, u16)>,
    slot_shift: u32,
    size: u64,
}

const HASH_MULT: u64 = 0x9E37_79B9_7F4A_7C15;
const EMPTY_SLOT: u16 = u16::MAX;

impl HandIndexer {
    /// An indexer for the full 52-card deck. `rounds` is the number of cards in each round:
    /// `[2]` for hole cards, `[2, 3]` for hole cards and a flop, `[2, 5]` for hole cards and
    /// a whole river board.
    pub fn new(rounds: &[u8]) -> HandIndexer {
        HandIndexer::with_deck(Deck::FULL, rounds)
    }

    /// An indexer for a deck of the top `deck.ranks()` ranks.
    pub fn with_deck(deck: Deck, rounds: &[u8]) -> HandIndexer {
        assert!(
            !rounds.is_empty() && rounds.len() <= MAX_ROUNDS,
            "between 1 and {MAX_ROUNDS} rounds"
        );
        let cards: usize = rounds.iter().map(|&n| n as usize).sum();
        assert!(
            rounds.iter().all(|&n| (1..=7).contains(&n)) && cards <= MAX_CARDS,
            "each round has 1 to 7 cards and a hand at most {MAX_CARDS}"
        );
        assert!(cards <= deck.len(), "more cards than the deck holds");

        let ranks = deck.ranks() as u64;
        let mut configs: Vec<Config> = Vec::new();
        let mut shapes = [[0u8; MAX_ROUNDS]; SUITS];
        let mut left = [0u8; MAX_ROUNDS];
        left[..rounds.len()].copy_from_slice(rounds);
        enumerate_configs(0, u64::MAX, &mut shapes, &mut left, rounds.len(), ranks, &mut configs);

        // Largest key first, so the most suited hands come first.
        configs.sort_by_key(|c| std::cmp::Reverse(c.key));
        let mut offset = 0u64;
        for c in &mut configs {
            c.offset = offset;
            let mut size = 1u64;
            for s in 0..SUITS {
                if c.group_len[s] > 0 {
                    size = size.checked_mul(c.group_size[s]).expect("index fits in a u64");
                }
            }
            offset = offset.checked_add(size).expect("index fits in a u64");
        }

        let slot_count = (configs.len() * 4).next_power_of_two().max(16);
        let slot_shift = 64 - slot_count.trailing_zeros();
        let mut slots = vec![(0u64, EMPTY_SLOT); slot_count];
        for (i, c) in configs.iter().enumerate() {
            let mut at = (c.key.wrapping_mul(HASH_MULT) >> slot_shift) as usize;
            while slots[at].1 != EMPTY_SLOT {
                at = (at + 1) & (slot_count - 1);
            }
            slots[at] = (c.key, i as u16);
        }

        HandIndexer {
            deck,
            rounds: rounds.to_vec(),
            cards,
            configs,
            slots,
            slot_shift,
            size: offset,
        }
    }

    /// Number of distinct hands up to suit relabelling: 169 for `[2]`, 1,286,792 for
    /// `[2, 3]`, 13,960,050 for `[2, 4]`, 123,156,254 for `[2, 5]`.
    pub fn size(&self) -> u64 {
        self.size
    }

    /// Cards in each round.
    pub fn rounds(&self) -> &[u8] {
        &self.rounds
    }

    /// Cards in a hand.
    pub fn cards(&self) -> usize {
        self.cards
    }

    /// The deck the hands are dealt from.
    pub fn deck(&self) -> Deck {
        self.deck
    }

    /// Number of suit configurations.
    pub fn configurations(&self) -> usize {
        self.configs.len()
    }

    #[inline]
    fn find_config(&self, key: u64) -> &Config {
        let mask = self.slots.len() - 1;
        let mut at = (key.wrapping_mul(HASH_MULT) >> self.slot_shift) as usize;
        loop {
            let (k, i) = self.slots[at];
            if k == key && i != EMPTY_SLOT {
                return &self.configs[i as usize];
            }
            assert!(i != EMPTY_SLOT, "not a hand of this indexer's shape");
            at = (at + 1) & mask;
        }
    }

    /// The index of a hand. The cards must be distinct, from this indexer's deck, and
    /// `cards.len()` must be [`HandIndexer::cards`].
    #[inline]
    pub fn index(&self, cards: &[u8]) -> u64 {
        assert_eq!(cards.len(), self.cards, "wrong number of cards");
        let t = set_tables();
        let low = self.deck.low_rank();
        let mut sets = [[0u16; MAX_ROUNDS]; SUITS];
        let mut at = 0;
        for (r, &n) in self.rounds.iter().enumerate() {
            for &c in &cards[at..at + n as usize] {
                debug_assert!(self.deck.contains(c), "card {c} is not in the deck");
                debug_assert!(
                    sets[(c & 3) as usize].iter().all(|s| s & (1 << ((c >> 2) - low)) == 0),
                    "card {c} twice"
                );
                sets[(c & 3) as usize][r] |= 1 << ((c >> 2) - low);
            }
            at += n as usize;
        }

        // Each suit's sort key: its shape, then its number.
        let mut keys = [0u64; SUITS];
        for s in 0..SUITS {
            let mut shape = 0u64;
            let mut number = 0u64;
            let mut radix = 1u64;
            let mut used = 0u16;
            let mut free = self.deck.ranks() as usize;
            for &set in &sets[s][..self.rounds.len()] {
                let n = set.count_ones() as usize;
                shape = (shape << SHAPE_BITS) | n as u64;
                if n > 0 {
                    let place = if used == 0 {
                        t.rank_of[set as usize]
                    } else {
                        t.rank_of[squeeze(set, used) as usize]
                    };
                    number += radix * place as u64;
                    radix *= t.binom[free][n] as u64;
                    used |= set;
                    free -= n;
                }
            }
            keys[s] = (shape << NUMBER_BITS) | number;
        }

        // Sort the four suits, largest key first.
        #[inline(always)]
        fn order(keys: &mut [u64; 4], a: usize, b: usize) {
            if keys[a] < keys[b] {
                keys.swap(a, b);
            }
        }
        order(&mut keys, 0, 1);
        order(&mut keys, 2, 3);
        order(&mut keys, 0, 2);
        order(&mut keys, 1, 3);
        order(&mut keys, 1, 2);

        let key = keys
            .iter()
            .fold(0u64, |k, &x| (k << (SHAPE_BITS * MAX_ROUNDS as u32)) | (x >> NUMBER_BITS));
        let config = self.find_config(key);

        const NUMBER_MASK: u64 = (1 << NUMBER_BITS) - 1;
        let mut index = 0u64;
        let mut radix = 1u64;
        let mut s = 0;
        while s < SUITS {
            let len = config.group_len[s] as usize;
            // The numbers of a group, smallest first, as a multiset.
            let mut place = 0u64;
            for j in 0..len {
                let number = keys[s + len - 1 - j] & NUMBER_MASK;
                place += choose(number + j as u64, j as u32 + 1);
            }
            index += radix * place;
            radix *= config.group_size[s];
            s += len;
        }
        config.offset + index
    }

    /// The configuration of an index and each sorted suit's number.
    #[inline]
    fn split(&self, index: u64) -> (&Config, [u64; SUITS]) {
        assert!(index < self.size, "index {index} out of range");
        let at = self.configs.partition_point(|c| c.offset <= index) - 1;
        let config = &self.configs[at];
        let mut rest = index - config.offset;
        let mut numbers = [0u64; SUITS];
        let mut s = 0;
        while s < SUITS {
            let len = config.group_len[s] as usize;
            let mut place = rest % config.group_size[s];
            rest /= config.group_size[s];
            for j in (0..len).rev() {
                // Largest b with C(b, j + 1) <= place.
                let b = if j == 0 {
                    place
                } else {
                    let (mut lo, mut hi) = (j as u64, j as u64 + 1);
                    while choose(hi, j as u32 + 1) <= place {
                        lo = hi;
                        hi *= 2;
                    }
                    while hi - lo > 1 {
                        let mid = lo + (hi - lo) / 2;
                        if choose(mid, j as u32 + 1) <= place {
                            lo = mid;
                        } else {
                            hi = mid;
                        }
                    }
                    lo
                };
                place -= choose(b, j as u32 + 1);
                numbers[s + len - 1 - j] = b - j as u64;
            }
            s += len;
        }
        (config, numbers)
    }

    /// The canonical hand of an index, written to `out` (length [`HandIndexer::cards`]):
    /// the first round's cards, then the next round's. `index(unindex(i)) == i`.
    pub fn unindex(&self, index: u64, out: &mut [u8]) {
        assert_eq!(out.len(), self.cards, "wrong number of cards");
        let t = set_tables();
        let (config, numbers) = self.split(index);
        let low = self.deck.low_rank();
        let mut next = [0usize; MAX_ROUNDS];
        let mut at = 0;
        for (r, &n) in self.rounds.iter().enumerate() {
            next[r] = at;
            at += n as usize;
        }
        for s in 0..SUITS {
            let mut number = numbers[s];
            let mut used = 0u16;
            let mut free = self.deck.ranks() as usize;
            for r in 0..self.rounds.len() {
                let n = config.count[s][r] as usize;
                if n == 0 {
                    continue;
                }
                let sets = t.binom[free][n] as u64;
                let mut set = expand(t.sets[n][(number % sets) as usize], used);
                number /= sets;
                used |= set;
                free -= n;
                while set != 0 {
                    let rank = set.trailing_zeros() as u8;
                    out[next[r]] = ((rank + low) << 2) | s as u8;
                    next[r] += 1;
                    set &= set - 1;
                }
            }
        }
    }

    /// How many different hands share this index: 24 divided by the number of suit
    /// relabellings that leave the canonical hand unchanged. For hole cards: 4 for a suited
    /// hand, 6 for a pair, 12 for an offsuit hand.
    pub fn multiplicity(&self, index: u64) -> u32 {
        let (config, numbers) = self.split(index);
        let mut same = 1u32;
        let mut s = 0;
        while s < SUITS {
            let len = config.group_len[s] as usize;
            let mut run = 1u32;
            for j in 1..len {
                if numbers[s + j] == numbers[s + j - 1] {
                    run += 1;
                    same *= run;
                } else {
                    run = 1;
                }
            }
            s += len;
        }
        24 / same
    }
}

/// Lists every way to give the four suits their shapes, with shapes never increasing from
/// one suit to the next. `left[r]` is how many of round `r`'s cards are still to place.
fn enumerate_configs(
    suit: usize,
    max_shape: u64,
    shapes: &mut [[u8; MAX_ROUNDS]; SUITS],
    left: &mut [u8; MAX_ROUNDS],
    rounds: usize,
    ranks: u64,
    out: &mut Vec<Config>,
) {
    if suit == SUITS {
        if left.iter().any(|&n| n != 0) {
            return;
        }
        let shape_of = |s: usize| {
            shapes[s][..rounds]
                .iter()
                .fold(0u64, |k, &n| (k << SHAPE_BITS) | n as u64)
        };
        let mut config = Config {
            key: (0..SUITS).fold(0u64, |k, s| {
                (k << (SHAPE_BITS * MAX_ROUNDS as u32)) | shape_of(s)
            }),
            offset: 0,
            count: *shapes,
            group_len: [0; SUITS],
            group_size: [0; SUITS],
        };
        let mut s = 0;
        while s < SUITS {
            let mut len = 1;
            while s + len < SUITS && shape_of(s + len) == shape_of(s) {
                len += 1;
            }
            // Numbers a suit of this shape can take.
            let mut numbers = 1u64;
            let mut free = ranks;
            for &n in &shapes[s][..rounds] {
                numbers *= choose(free, n as u32);
                free -= (n as u64).min(free);
            }
            if numbers == 0 {
                return; // more cards of one suit than the deck has ranks
            }
            config.group_len[s] = len as u8;
            config.group_size[s] = choose(numbers + len as u64 - 1, len as u32);
            s += len;
        }
        out.push(config);
        return;
    }
    // Every shape for this suit that fits in what is left, not above the previous suit's.
    let mut shape = [0u8; MAX_ROUNDS];
    loop {
        let key = shape[..rounds]
            .iter()
            .fold(0u64, |k, &n| (k << SHAPE_BITS) | n as u64);
        if key <= max_shape {
            shapes[suit] = shape;
            for r in 0..rounds {
                left[r] -= shape[r];
            }
            enumerate_configs(suit + 1, key, shapes, left, rounds, ranks, out);
            for r in 0..rounds {
                left[r] += shape[r];
            }
        }
        // Next shape, like an odometer.
        let mut r = 0;
        loop {
            if r == rounds {
                shapes[suit] = [0; MAX_ROUNDS];
                return;
            }
            if shape[r] < left[r] {
                shape[r] += 1;
                break;
            }
            shape[r] = 0;
            r += 1;
        }
    }
}

/// The 169 classes of hole cards, in the indexer's order, with their usual names.
pub struct Preflop {
    indexer: HandIndexer,
}

impl Default for Preflop {
    fn default() -> Preflop {
        Preflop::new()
    }
}

impl Preflop {
    /// Hole-card classes of the full deck.
    pub fn new() -> Preflop {
        Preflop::with_deck(Deck::FULL)
    }

    /// Hole-card classes of a smaller deck.
    pub fn with_deck(deck: Deck) -> Preflop {
        Preflop {
            indexer: HandIndexer::with_deck(deck, &[2]),
        }
    }

    /// Number of classes: 169 for the full deck.
    pub fn classes(&self) -> usize {
        self.indexer.size() as usize
    }

    /// The class of two hole cards.
    #[inline]
    pub fn class(&self, a: u8, b: u8) -> u16 {
        self.indexer.index(&[a, b]) as u16
    }

    /// A class's canonical hole cards.
    pub fn cards(&self, class: u16) -> [u8; 2] {
        let mut out = [0u8; 2];
        self.indexer.unindex(class as u64, &mut out);
        out
    }

    /// How many of the deck's hole-card combinations are in the class: 6 for a pair, 4 for
    /// a suited hand, 12 for an offsuit hand.
    pub fn combos(&self, class: u16) -> u32 {
        self.indexer.multiplicity(class as u64)
    }

    /// The usual name: "AA", "AKs", "72o".
    pub fn name(&self, class: u16) -> String {
        const RANKS: &[u8; 13] = b"23456789TJQKA";
        let [a, b] = self.cards(class);
        let (hi, lo) = if a >> 2 >= b >> 2 { (a, b) } else { (b, a) };
        let mut name = String::new();
        name.push(RANKS[(hi >> 2) as usize] as char);
        name.push(RANKS[(lo >> 2) as usize] as char);
        if hi >> 2 != lo >> 2 {
            name.push(if hi & 3 == lo & 3 { 's' } else { 'o' });
        }
        name
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn choose_is_pascal() {
        assert_eq!(choose(52, 2), 1326);
        assert_eq!(choose(13, 0), 1);
        assert_eq!(choose(3, 4), 0);
        assert_eq!(choose(36_039, 4), 36_039 * 36_038 / 2 * 36_037 / 3 * 36_036 / 4);
    }

    #[test]
    fn squeeze_and_expand_undo_each_other() {
        for used in [0u16, 0b1, 0b1010, 0b1_0000_0000_0001, 0b11_0110] {
            for set in 0u16..(1 << 13) {
                if set & used == 0 && set.count_ones() <= 5 {
                    let sq = squeeze(set, used);
                    assert_eq!(sq.count_ones(), set.count_ones());
                    assert_eq!(expand(sq, used), set);
                    assert!(sq < 1 << (13 - used.count_ones()));
                }
            }
        }
    }

    #[test]
    fn preflop_names_and_combos() {
        let p = Preflop::new();
        assert_eq!(p.classes(), 169);
        let mut names = std::collections::BTreeSet::new();
        let mut combos = 0;
        for class in 0..169 {
            let name = p.name(class);
            let expected = match name.len() {
                2 => 6,
                _ if name.ends_with('s') => 4,
                _ => 12,
            };
            assert_eq!(p.combos(class), expected, "{name}");
            combos += p.combos(class);
            names.insert(name);
        }
        assert_eq!(names.len(), 169);
        assert_eq!(combos, 1326);
        assert!(names.contains("AA") && names.contains("AKs") && names.contains("72o"));
        // Ah Kh and As Ks are the same class; Ah Ks is another.
        let card = |rank: u8, suit: u8| rank * 4 + suit;
        assert_eq!(p.class(card(12, 2), card(11, 2)), p.class(card(11, 3), card(12, 3)));
        assert_ne!(p.class(card(12, 2), card(11, 2)), p.class(card(12, 2), card(11, 3)));
        assert_eq!(p.name(p.class(card(12, 2), card(11, 3))), "AKo");
    }
}
