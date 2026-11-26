//! Information set index: maps an [`InfoKey`] to a dense index and to a slice
//! of the flat per-action arrays (regrets, strategy sums) solvers keep.

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};

use crate::game::InfoKey;

/// Hasher for `u64` keys: the murmur3 finalizer, so keys that differ only in
/// a few bits still spread over the table.
#[derive(Default, Clone, Copy)]
pub struct KeyHasher(u64);

impl Hasher for KeyHasher {
    #[inline]
    fn finish(&self) -> u64 {
        let mut z = self.0;
        z = (z ^ (z >> 33)).wrapping_mul(0xFF51_AFD7_ED55_8CCD);
        z = (z ^ (z >> 33)).wrapping_mul(0xC4CE_B9FE_1A85_EC53);
        z ^ (z >> 33)
    }
    #[inline]
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 = (self.0 ^ b as u64).wrapping_mul(0x100_0000_01B3);
        }
    }
    #[inline]
    fn write_u64(&mut self, x: u64) {
        self.0 ^= x;
    }
}

pub type KeyMap<V> = HashMap<InfoKey, V, BuildHasherDefault<KeyHasher>>;

/// One information set's place in the flat arrays.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InfoSet {
    /// First slot in the per-action arrays.
    pub offset: u32,
    pub num_actions: u32,
    /// The player who acts here.
    pub player: u32,
}

impl InfoSet {
    #[inline]
    pub fn range(&self) -> std::ops::Range<usize> {
        self.offset as usize..(self.offset + self.num_actions) as usize
    }
}

/// Dense information set table. Index `i` owns slots
/// `sets[i].offset .. sets[i].offset + sets[i].num_actions`.
#[derive(Clone, Debug, Default)]
pub struct InfoTable {
    index: KeyMap<u32>,
    sets: Vec<InfoSet>,
    keys: Vec<InfoKey>,
    slots: usize,
}

impl InfoTable {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_capacity(info_sets: usize) -> Self {
        InfoTable {
            index: KeyMap::with_capacity_and_hasher(info_sets, Default::default()),
            sets: Vec::with_capacity(info_sets),
            keys: Vec::with_capacity(info_sets),
            slots: 0,
        }
    }

    /// Number of information sets.
    #[inline]
    pub fn len(&self) -> usize {
        self.sets.len()
    }

    #[inline]
    pub fn is_empty(&self) -> bool {
        self.sets.is_empty()
    }

    /// Total number of (information set, action) slots.
    #[inline]
    pub fn slots(&self) -> usize {
        self.slots
    }

    #[inline]
    pub fn get(&self, key: InfoKey) -> Option<u32> {
        self.index.get(&key).copied()
    }

    #[inline]
    pub fn set(&self, idx: u32) -> InfoSet {
        self.sets[idx as usize]
    }

    #[inline]
    pub fn key(&self, idx: u32) -> InfoKey {
        self.keys[idx as usize]
    }

    pub fn sets(&self) -> &[InfoSet] {
        &self.sets
    }

    pub fn keys(&self) -> &[InfoKey] {
        &self.keys
    }

    /// Index of `key`, adding it if new. Returns `(index, was_new)`; when new,
    /// the caller must grow its per-action arrays to [`InfoTable::slots`].
    #[inline]
    pub fn get_or_insert(
        &mut self,
        key: InfoKey,
        num_actions: usize,
        player: usize,
    ) -> (u32, bool) {
        if let Some(&i) = self.index.get(&key) {
            debug_assert_eq!(
                self.sets[i as usize].num_actions as usize, num_actions,
                "information set {key:#x} seen with different action counts"
            );
            return (i, false);
        }
        let i = self.sets.len() as u32;
        self.sets.push(InfoSet {
            offset: u32::try_from(self.slots).expect("more than 2^32 action slots"),
            num_actions: num_actions as u32,
            player: player as u32,
        });
        self.keys.push(key);
        self.slots += num_actions;
        self.index.insert(key, i);
        (i, true)
    }
}
