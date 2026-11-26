//! The information set index several threads share: key to (first slot,
//! action count, player).
//!
//! Looking up a key that is already there takes no lock: it reads a pointer
//! and probes an open-addressing table of atomics. Only adding a key locks,
//! and only one of 1024 shards, picked by the key's hash. So once a run has
//! met most of its information sets, threads never wait for each other here.
//!
//! How that stays sound:
//!
//! - An entry is two words, key and value. The writer (holding the shard's
//!   lock) stores the key, then the value with `Release`. A value is never
//!   zero once set and never changes. A reader loads the value with
//!   `Acquire`: zero means "nothing here yet", anything else means the key
//!   next to it is complete.
//! - A shard's table doubles when it is three quarters full. The new table is
//!   published through an atomic pointer; the old one is kept, not freed,
//!   because a reader may still be probing it. A reader on an old table can
//!   only miss a key added since, and a miss falls back to the locked path,
//!   which looks again in the current table. Old tables are freed by
//!   [`SharedTable::collect`], which needs `&mut self`: no reader can exist
//!   then.

use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicU64, AtomicUsize, Ordering};
use std::sync::Mutex;

use crate::game::InfoKey;
use crate::store::Cursor;

const SHARD_BITS: u32 = 10;
const SHARDS: usize = 1 << SHARD_BITS;
/// Cells in a shard's first table.
const FIRST_CELLS: usize = 4;

const OFFSET_BITS: u32 = 40;
const ACTION_BITS: u32 = 16;
const PLAYER_BITS: u32 = 7;
const OCCUPIED: u64 = 1 << 63;

/// One information set's place in the per-action arrays.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Entry {
    pub key: InfoKey,
    pub offset: usize,
    pub num_actions: usize,
    pub player: usize,
}

#[inline]
fn pack(offset: usize, num_actions: usize, player: usize) -> u64 {
    assert!(
        (offset as u64) < 1 << OFFSET_BITS,
        "more than 2^40 action slots"
    );
    assert!(
        num_actions < 1 << ACTION_BITS,
        "more than 65535 actions at one information set"
    );
    assert!(player < 1 << PLAYER_BITS, "more than 127 players");
    OCCUPIED
        | (player as u64) << (OFFSET_BITS + ACTION_BITS)
        | (num_actions as u64) << OFFSET_BITS
        | offset as u64
}

#[inline]
fn unpack(key: InfoKey, value: u64) -> Entry {
    Entry {
        key,
        offset: (value & ((1 << OFFSET_BITS) - 1)) as usize,
        num_actions: ((value >> OFFSET_BITS) & ((1 << ACTION_BITS) - 1)) as usize,
        player: ((value >> (OFFSET_BITS + ACTION_BITS)) & ((1 << PLAYER_BITS) - 1)) as usize,
    }
}

/// The murmur3 finalizer: keys that differ in a few bits spread over shards
/// and cells alike.
#[inline]
fn mix(key: InfoKey) -> u64 {
    let mut z = key;
    z = (z ^ (z >> 33)).wrapping_mul(0xFF51_AFD7_ED55_8CCD);
    z = (z ^ (z >> 33)).wrapping_mul(0xC4CE_B9FE_1A85_EC53);
    z ^ (z >> 33)
}

/// One open-addressing table: `[key, value]` cells, linear probing.
struct Cells {
    mask: usize,
    cells: Box<[[AtomicU64; 2]]>,
}

impl Cells {
    fn new(len: usize) -> Box<Cells> {
        debug_assert!(len.is_power_of_two());
        Box::new(Cells {
            mask: len - 1,
            cells: (0..len)
                .map(|_| [AtomicU64::new(0), AtomicU64::new(0)])
                .collect(),
        })
    }

    #[inline]
    fn find(&self, key: InfoKey, hash: u64) -> Option<u64> {
        let mut i = hash as usize & self.mask;
        loop {
            let cell = &self.cells[i];
            let value = cell[1].load(Ordering::Acquire);
            if value == 0 {
                return None;
            }
            if cell[0].load(Ordering::Relaxed) == key {
                return Some(value);
            }
            i = (i + 1) & self.mask;
        }
    }

    /// Puts a key that is not there into the first free cell. Only the
    /// shard's lock holder calls this, and the table is never full.
    fn put(&self, key: InfoKey, hash: u64, value: u64) {
        let mut i = hash as usize & self.mask;
        while self.cells[i][1].load(Ordering::Relaxed) != 0 {
            i = (i + 1) & self.mask;
        }
        self.cells[i][0].store(key, Ordering::Relaxed);
        self.cells[i][1].store(value, Ordering::Release);
    }

    fn entries(&self) -> impl Iterator<Item = Entry> + '_ {
        self.cells.iter().filter_map(|cell| {
            let value = cell[1].load(Ordering::Acquire);
            (value != 0).then(|| unpack(cell[0].load(Ordering::Relaxed), value))
        })
    }
}

/// What a shard's lock guards: how full the live table is, and the tables it
/// has outgrown.
struct ShardState {
    count: usize,
    /// Boxed on purpose: a reader may still hold the address of a retired
    /// table, so it has to stay where it was allocated.
    #[allow(clippy::vec_box)]
    retired: Vec<Box<Cells>>,
}

#[repr(align(64))]
struct Shard {
    /// The live table. Owned by the shard: set once in `new`, replaced only
    /// under `state`'s lock, freed in `drop`.
    live: AtomicPtr<Cells>,
    state: Mutex<ShardState>,
}

impl Shard {
    fn new(cells: usize) -> Self {
        Shard {
            live: AtomicPtr::new(Box::into_raw(Cells::new(cells))),
            state: Mutex::new(ShardState {
                count: 0,
                retired: Vec::new(),
            }),
        }
    }

    #[inline]
    fn cells(&self) -> &Cells {
        // SAFETY: `live` always points to a table this shard owns. A table
        // is freed only in `collect` or `drop`, both of which take `&mut`,
        // so it outlives this `&self` borrow.
        unsafe { &*self.live.load(Ordering::Acquire) }
    }
}

impl Drop for Shard {
    fn drop(&mut self) {
        // SAFETY: `live` came from `Box::into_raw` and nothing else frees it.
        drop(unsafe { Box::from_raw(*self.live.get_mut()) });
    }
}

pub(crate) struct SharedTable {
    shards: Box<[Shard]>,
    cursor: Cursor,
    len: AtomicUsize,
    /// Some shard holds a table it has outgrown.
    garbage: AtomicBool,
}

impl SharedTable {
    pub fn new() -> Self {
        Self::with_capacity(0)
    }

    /// A table whose shards start big enough for `info_sets` keys spread
    /// evenly, so they don't have to grow on the way there.
    pub fn with_capacity(info_sets: usize) -> Self {
        // Twice the average, rounded up to a power of two: a shard is then
        // at most half full on average, with room for the unlucky ones.
        let per_shard = ((info_sets / SHARDS + 1) * 2).next_power_of_two();
        let cells = if info_sets == 0 {
            FIRST_CELLS
        } else {
            per_shard.max(FIRST_CELLS)
        };
        SharedTable {
            shards: (0..SHARDS).map(|_| Shard::new(cells)).collect(),
            cursor: Cursor::new(),
            len: AtomicUsize::new(0),
            garbage: AtomicBool::new(false),
        }
    }

    /// Number of information sets.
    #[inline]
    pub fn len(&self) -> usize {
        self.len.load(Ordering::Acquire)
    }

    /// One past the last slot handed out. Slots can be skipped at the end of
    /// a segment, so this can be more than the slots in use.
    #[inline]
    pub fn used_slots(&self) -> usize {
        self.cursor.used()
    }

    #[inline]
    fn shard(&self, hash: u64) -> &Shard {
        &self.shards[(hash >> (64 - SHARD_BITS)) as usize]
    }

    #[cfg(test)]
    pub fn get(&self, key: InfoKey) -> Option<Entry> {
        let hash = mix(key);
        self.shard(hash)
            .cells()
            .find(key, hash)
            .map(|v| unpack(key, v))
    }

    /// The first slot of `key`, adding the key if it is new. `prepare` is
    /// called with a new key's first slot before any other thread can see
    /// the key: it must make the slots usable (allocate their segments).
    #[inline]
    pub fn get_or_insert(
        &self,
        key: InfoKey,
        num_actions: usize,
        player: usize,
        prepare: impl FnOnce(usize),
    ) -> usize {
        let hash = mix(key);
        let shard = self.shard(hash);
        if let Some(value) = shard.cells().find(key, hash) {
            let entry = unpack(key, value);
            debug_assert_eq!(
                entry.num_actions, num_actions,
                "information set {key:#x} seen with different action counts"
            );
            return entry.offset;
        }
        self.insert(shard, key, hash, num_actions, player, prepare)
    }

    #[cold]
    fn insert(
        &self,
        shard: &Shard,
        key: InfoKey,
        hash: u64,
        num_actions: usize,
        player: usize,
        prepare: impl FnOnce(usize),
    ) -> usize {
        let mut state = shard.state.lock().unwrap_or_else(|e| e.into_inner());
        // Another thread may have added the key, or grown the table, since
        // the lock-free look.
        let mut cells = shard.cells();
        if let Some(value) = cells.find(key, hash) {
            return unpack(key, value).offset;
        }
        if (state.count + 1) * 4 > (cells.mask + 1) * 3 {
            let bigger = Cells::new((cells.mask + 1) * 2);
            for e in cells.entries() {
                bigger.put(e.key, mix(e.key), pack(e.offset, e.num_actions, e.player));
            }
            let old = shard.live.swap(Box::into_raw(bigger), Ordering::AcqRel);
            // SAFETY: `old` was the live table, owned by the shard. Readers
            // may still hold it, so it is kept until `collect`.
            state.retired.push(unsafe { Box::from_raw(old) });
            self.garbage.store(true, Ordering::Relaxed);
            cells = shard.cells();
        }
        let offset = self.cursor.take(num_actions);
        prepare(offset);
        cells.put(key, hash, pack(offset, num_actions, player));
        state.count += 1;
        self.len.fetch_add(1, Ordering::AcqRel);
        offset
    }

    /// Puts back an information set of a loaded checkpoint, at the slots it
    /// had. False if the key is already there.
    pub fn restore(&mut self, e: Entry) -> bool {
        let hash = mix(e.key);
        let shard = self.shard(hash);
        let mut state = shard.state.lock().unwrap_or_else(|p| p.into_inner());
        let mut cells = shard.cells();
        if cells.find(e.key, hash).is_some() {
            return false;
        }
        if (state.count + 1) * 4 > (cells.mask + 1) * 3 {
            let bigger = Cells::new((cells.mask + 1) * 2);
            for old in cells.entries() {
                bigger.put(
                    old.key,
                    mix(old.key),
                    pack(old.offset, old.num_actions, old.player),
                );
            }
            let old = shard.live.swap(Box::into_raw(bigger), Ordering::AcqRel);
            // SAFETY: as in `insert`.
            state.retired.push(unsafe { Box::from_raw(old) });
            self.garbage.store(true, Ordering::Relaxed);
            cells = shard.cells();
        }
        cells.put(e.key, hash, pack(e.offset, e.num_actions, e.player));
        state.count += 1;
        self.len.fetch_add(1, Ordering::AcqRel);
        true
    }

    /// Continues handing out slots after `used` (a loaded checkpoint).
    pub fn restore_used(&mut self, used: usize) {
        self.cursor.restore(used);
    }

    /// Frees the tables the shards have outgrown. `&mut self`: no thread is
    /// reading.
    #[inline]
    pub fn collect(&mut self) {
        if !*self.garbage.get_mut() {
            return;
        }
        *self.garbage.get_mut() = false;
        for shard in self.shards.iter_mut() {
            let state = shard.state.get_mut().unwrap_or_else(|e| e.into_inner());
            if !state.retired.is_empty() {
                state.retired = Vec::new();
            }
        }
    }

    /// Every information set, in no particular order. Meant for when no
    /// thread is adding keys; a key added meanwhile may or may not show up.
    pub fn for_each(&self, mut f: impl FnMut(Entry)) {
        for shard in self.shards.iter() {
            shard.cells().entries().for_each(&mut f);
        }
    }

    /// Every information set in key order.
    pub fn sorted(&self) -> Vec<Entry> {
        let mut all = Vec::with_capacity(self.len());
        self.for_each(|e| all.push(e));
        all.sort_unstable_by_key(|e| e.key);
        all
    }

    /// Bytes the index itself takes (not the per-action arrays).
    pub fn index_bytes(&self) -> usize {
        let cells: usize = self.shards.iter().map(|s| s.cells().mask + 1).sum();
        cells * std::mem::size_of::<[AtomicU64; 2]>() + SHARDS * std::mem::size_of::<Shard>()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn keys_keep_their_slots_while_shards_grow() {
        let mut table = SharedTable::new();
        let mut offsets = HashMap::new();
        for key in 0..50_000u64 {
            let n = 1 + (key % 5) as usize;
            let offset =
                table.get_or_insert(key.wrapping_mul(0x9E37), n, (key % 3) as usize, |_| {});
            offsets.insert(key, offset);
        }
        assert_eq!(table.len(), 50_000);
        for key in 0..50_000u64 {
            let e = table.get(key.wrapping_mul(0x9E37)).unwrap();
            assert_eq!(e.offset, offsets[&key]);
            assert_eq!(e.num_actions, 1 + (key % 5) as usize);
            assert_eq!(e.player, (key % 3) as usize);
            // Asking again changes nothing.
            assert_eq!(
                table.get_or_insert(key.wrapping_mul(0x9E37), e.num_actions, e.player, |_| {
                    panic!("not new")
                }),
                e.offset
            );
        }
        assert!(table.get(u64::MAX).is_none());
        let sorted = table.sorted();
        assert!(sorted.windows(2).all(|w| w[0].key < w[1].key));
        // No two information sets share a slot.
        let mut ranges: Vec<(usize, usize)> =
            sorted.iter().map(|e| (e.offset, e.num_actions)).collect();
        ranges.sort_unstable();
        assert!(ranges.windows(2).all(|w| w[0].0 + w[0].1 <= w[1].0));
        assert!(table.used_slots() >= ranges.iter().map(|r| r.1).sum::<usize>());
        table.collect();
        assert_eq!(table.get(7 * 0x9E37).unwrap().offset, offsets[&7]);
    }

    #[test]
    fn a_table_sized_ahead_does_not_grow() {
        let table = SharedTable::with_capacity(100_000);
        let before = table.index_bytes();
        for key in 0..100_000u64 {
            table.get_or_insert(mix(key), 2, 0, |_| {});
        }
        assert_eq!(table.index_bytes(), before);
    }

    #[test]
    fn threads_adding_the_same_keys_agree_on_every_slot() {
        let table = SharedTable::new();
        let per_thread: Vec<Vec<(u64, usize)>> = std::thread::scope(|scope| {
            let handles: Vec<_> = (0..8u64)
                .map(|t| {
                    let table = &table;
                    scope.spawn(move || {
                        let mut seen = Vec::new();
                        // Each thread walks the same 20,000 keys from its own start.
                        for i in 0..20_000u64 {
                            let key = (i + t * 2_500) % 20_000;
                            let n = 1 + (key % 4) as usize;
                            let offset = table.get_or_insert(key, n, 0, |_| {});
                            // A second look sees the same slot, whoever added it.
                            assert_eq!(table.get(key).unwrap().offset, offset);
                            seen.push((key, offset));
                        }
                        seen
                    })
                })
                .collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });
        assert_eq!(table.len(), 20_000);
        let mut slot_of = HashMap::new();
        for (key, offset) in per_thread.into_iter().flatten() {
            assert_eq!(*slot_of.entry(key).or_insert(offset), offset);
        }
        let mut ranges: Vec<(usize, usize)> = table
            .sorted()
            .iter()
            .map(|e| (e.offset, e.num_actions))
            .collect();
        ranges.sort_unstable();
        assert!(ranges.windows(2).all(|w| w[0].0 + w[0].1 <= w[1].0));
    }
}
