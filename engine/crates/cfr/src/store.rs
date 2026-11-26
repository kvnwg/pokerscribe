//! Per-action arrays that many threads read and write at once, without
//! locks: regrets and strategy sums.
//!
//! Two things make that possible.
//!
//! - Every slot is an atomic. Threads load and store with `Relaxed` ordering,
//!   which on x86-64 and AArch64 is a plain move, so one thread pays nothing
//!   for it. An update is a load, some arithmetic and a store, and nothing
//!   stops another thread from storing in between: now and then an update is
//!   lost. Monte Carlo CFR tolerates that (Pluribus trained this way). With
//!   one thread nothing is ever lost and a run is exact.
//! - The arrays grow in segments that never move. Segment k holds
//!   4096 * 2^k slots and is allocated, zeroed, the first time a slot in it
//!   is needed; earlier segments stay where they are, so a thread can keep
//!   using a slice while another thread makes the array longer. An
//!   information set's slots are always inside one segment.

use std::io;
use std::sync::atomic::{AtomicI32, AtomicU64, AtomicUsize, Ordering};
use std::sync::OnceLock;

/// log2 of the first segment's length.
const BASE_BITS: u32 = 12;
/// Segments 0..40 hold 4096 * (2^40 - 1) slots, far more than any machine.
const SEGMENTS: usize = 40;

/// Which segment a slot is in, and where in it.
#[inline]
fn locate(slot: usize) -> (usize, usize) {
    let x = (slot >> BASE_BITS) + 1;
    let k = (usize::BITS - 1 - x.leading_zeros()) as usize;
    (k, slot - (((1usize << k) - 1) << BASE_BITS))
}

#[inline]
fn segment_start(k: usize) -> usize {
    ((1usize << k) - 1) << BASE_BITS
}

#[inline]
fn segment_len(k: usize) -> usize {
    1usize << (k as u32 + BASE_BITS)
}

/// A cell that is all zero bits when new, so a segment can come straight
/// from the allocator's zeroed pages.
pub(crate) trait Cell: Sized + Send + Sync {
    fn zeroed(len: usize) -> Box<[Self]>;
}

macro_rules! zeroed_cell {
    ($atomic:ty, $plain:ty) => {
        impl Cell for $atomic {
            fn zeroed(len: usize) -> Box<[Self]> {
                const {
                    assert!(std::mem::size_of::<$atomic>() == std::mem::size_of::<$plain>());
                    assert!(std::mem::align_of::<$atomic>() == std::mem::align_of::<$plain>());
                }
                // `vec![0; n]` asks the allocator for zeroed memory, which for
                // a big segment is untouched pages from the system: nothing
                // is written until a slot is used.
                let plain: Box<[$plain]> = vec![0; len].into_boxed_slice();
                // SAFETY: the atomic has the same size, alignment (checked
                // above) and bit validity as the plain integer, and the box
                // is uniquely owned.
                unsafe { Box::from_raw(Box::into_raw(plain) as *mut [$atomic]) }
            }
        }
    };
}

zeroed_cell!(AtomicU64, u64);
zeroed_cell!(AtomicI32, i32);

/// A cell that can be written to a checkpoint and read back, as its
/// little-endian bytes.
pub(crate) trait Raw: Cell {
    const BYTES: usize;
    fn put(&self, out: &mut [u8]);
    fn set(&mut self, raw: &[u8]);
}

impl Raw for AtomicU64 {
    const BYTES: usize = 8;
    #[inline]
    fn put(&self, out: &mut [u8]) {
        out.copy_from_slice(&self.load(Ordering::Relaxed).to_le_bytes());
    }
    #[inline]
    fn set(&mut self, raw: &[u8]) {
        *self.get_mut() = u64::from_le_bytes(raw.try_into().unwrap());
    }
}

impl Raw for AtomicI32 {
    const BYTES: usize = 4;
    #[inline]
    fn put(&self, out: &mut [u8]) {
        out.copy_from_slice(&self.load(Ordering::Relaxed).to_le_bytes());
    }
    #[inline]
    fn set(&mut self, raw: &[u8]) {
        *self.get_mut() = i32::from_le_bytes(raw.try_into().unwrap());
    }
}

/// Cells converted per call to the checkpoint's writer or reader.
const RAW_CHUNK: usize = 1 << 14;

/// A growable array of cells whose elements never move.
pub(crate) struct Segments<T> {
    segments: [OnceLock<Box<[T]>>; SEGMENTS],
}

impl<T: Cell> Segments<T> {
    pub fn new() -> Self {
        Segments {
            segments: [const { OnceLock::new() }; SEGMENTS],
        }
    }

    /// Makes sure the segment holding `slot` exists.
    #[inline]
    pub fn ensure(&self, slot: usize) {
        let (k, _) = locate(slot);
        if self.segments[k].get().is_none() {
            self.segments[k].get_or_init(|| T::zeroed(segment_len(k)));
        }
    }

    /// The `n` cells from `offset`. They must have been handed out by a
    /// [`Cursor`], which keeps them inside one segment, and `ensure`d.
    #[inline]
    pub fn slice(&self, offset: usize, n: usize) -> &[T] {
        let (k, i) = locate(offset);
        let segment = self.segments[k]
            .get()
            .expect("slots used before their segment was allocated");
        &segment[i..i + n]
    }

    /// Every allocated cell below `used`, a segment at a time, for the passes
    /// that touch the whole array while no other thread is running.
    pub fn for_each_mut(&mut self, used: usize, mut f: impl FnMut(&mut [T])) {
        for (k, segment) in self.segments.iter_mut().enumerate() {
            let start = segment_start(k);
            if start >= used {
                break;
            }
            if let Some(cells) = segment.get_mut() {
                let end = (used - start).min(cells.len());
                f(&mut cells[..end]);
            }
        }
    }

    /// The first `used` cells in order, as bytes, a block at a time: the
    /// array as a checkpoint stores it. Memory is read front to back, so
    /// this runs at the speed of the disk, not of cache misses.
    pub fn dump(
        &self,
        used: usize,
        mut write: impl FnMut(&[u8]) -> io::Result<()>,
    ) -> io::Result<()>
    where
        T: Raw,
    {
        let mut buffer = vec![0u8; RAW_CHUNK * T::BYTES];
        for (k, segment) in self.segments.iter().enumerate() {
            let start = segment_start(k);
            if start >= used {
                break;
            }
            let len = (used - start).min(segment_len(k));
            match segment.get() {
                Some(cells) => {
                    for part in cells[..len].chunks(RAW_CHUNK) {
                        let bytes = &mut buffer[..part.len() * T::BYTES];
                        for (cell, out) in part.iter().zip(bytes.chunks_exact_mut(T::BYTES)) {
                            cell.put(out);
                        }
                        write(bytes)?;
                    }
                }
                // Never the case below `used`; zeros keep the layout if it were.
                None => {
                    buffer.fill(0);
                    let mut left = len;
                    while left > 0 {
                        let n = left.min(RAW_CHUNK);
                        write(&buffer[..n * T::BYTES])?;
                        left -= n;
                    }
                }
            }
        }
        Ok(())
    }

    /// The opposite of [`Segments::dump`]: allocates what `used` cells need
    /// and fills them from `read`, which must fill each buffer it is given.
    pub fn load(
        &mut self,
        used: usize,
        mut read: impl FnMut(&mut [u8]) -> io::Result<()>,
    ) -> io::Result<()>
    where
        T: Raw,
    {
        let mut buffer = vec![0u8; RAW_CHUNK * T::BYTES];
        for (k, segment) in self.segments.iter_mut().enumerate() {
            let start = segment_start(k);
            if start >= used {
                break;
            }
            let len = (used - start).min(segment_len(k));
            segment.get_or_init(|| T::zeroed(segment_len(k)));
            let cells = segment.get_mut().expect("just allocated");
            for part in cells[..len].chunks_mut(RAW_CHUNK) {
                let bytes = &mut buffer[..part.len() * T::BYTES];
                read(bytes)?;
                for (cell, raw) in part.iter_mut().zip(bytes.chunks_exact(T::BYTES)) {
                    cell.set(raw);
                }
            }
        }
        Ok(())
    }

    /// Bytes of address space the segments take. Pages no slot has touched
    /// yet cost no memory.
    pub fn allocated_bytes(&self) -> usize {
        self.segments
            .iter()
            .filter_map(|s| s.get())
            .map(|s| std::mem::size_of_val::<[T]>(s))
            .sum()
    }
}

/// Hands out slots: `take(n)` gives `n` consecutive slots in one segment.
pub(crate) struct Cursor(AtomicUsize);

impl Cursor {
    pub fn new() -> Self {
        Cursor(AtomicUsize::new(0))
    }

    /// One past the last slot handed out.
    #[inline]
    pub fn used(&self) -> usize {
        self.0.load(Ordering::Acquire)
    }

    /// Continues after `used` slots (a loaded checkpoint).
    pub fn restore(&mut self, used: usize) {
        *self.0.get_mut() = used;
    }

    /// Whether `n` slots from `offset` are a range `take` could have given.
    pub fn fits(offset: usize, n: usize) -> bool {
        n > 0 && n <= segment_len(0) && locate(offset).1 + n <= segment_len(locate(offset).0)
    }

    /// The first of `n` fresh consecutive slots. When they would cross into
    /// the next segment, the rest of this one is left unused.
    pub fn take(&self, n: usize) -> usize {
        assert!(
            n > 0 && n <= segment_len(0),
            "an information set has 1 to 4096 actions"
        );
        let mut current = self.0.load(Ordering::Relaxed);
        loop {
            let (k, i) = locate(current);
            let offset = if i + n <= segment_len(k) {
                current
            } else {
                segment_start(k + 1)
            };
            match self.0.compare_exchange_weak(
                current,
                offset + n,
                Ordering::AcqRel,
                Ordering::Relaxed,
            ) {
                Ok(_) => return offset,
                Err(seen) => current = seen,
            }
        }
    }
}

/// How regrets are stored.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum RegretStorage {
    /// 64-bit floats, 8 bytes a slot. Exact; the default.
    F64,
    /// 32-bit integers, 4 bytes a slot, as Pluribus stored them. A regret r
    /// is kept as `round(r * scale)` and never leaves the range of an `i32`:
    /// it stops at [`MccfrConfig::regret_floor`](crate::MccfrConfig) times
    /// `scale` if a floor is set, at -2^31 otherwise, and at 2^31 - 1 above.
    /// Pick `scale` so that one typical regret update is many units (a game
    /// with payoffs in whole chips can use 1, as Pluribus did; Kuhn and Leduc,
    /// whose payoffs are a few units, want about 1000) and so that regrets
    /// times `scale` stay well under two billion.
    I32 { scale: f64 },
}

/// The regret array in either storage.
pub(crate) enum Regrets {
    F64 {
        cells: Segments<AtomicU64>,
        floor: Option<f64>,
    },
    I32 {
        cells: Segments<AtomicI32>,
        scale: f64,
        floor: i32,
    },
}

impl Regrets {
    pub fn new(storage: RegretStorage, floor: Option<f64>) -> Self {
        match storage {
            RegretStorage::F64 => Regrets::F64 {
                cells: Segments::new(),
                floor,
            },
            RegretStorage::I32 { scale } => {
                assert!(
                    scale.is_finite() && scale > 0.0,
                    "the regret scale must be positive"
                );
                let floor = match floor {
                    Some(f) => (f * scale).round().clamp(i32::MIN as f64, 0.0) as i32,
                    None => i32::MIN,
                };
                Regrets::I32 {
                    cells: Segments::new(),
                    scale,
                    floor,
                }
            }
        }
    }

    #[inline]
    pub fn ensure(&self, slot: usize) {
        match self {
            Regrets::F64 { cells, .. } => cells.ensure(slot),
            Regrets::I32 { cells, .. } => cells.ensure(slot),
        }
    }

    /// Regret matching over the `out.len()` slots from `offset`:
    /// probabilities in proportion to positive regret, uniform when none is
    /// positive. The arithmetic is [`crate::policy::regret_matching`]'s.
    #[inline]
    pub fn matching(&self, offset: usize, out: &mut [f64]) {
        let mut sum = 0.0;
        match self {
            Regrets::F64 { cells, .. } => {
                let cells = cells.slice(offset, out.len());
                for (o, c) in out.iter_mut().zip(cells) {
                    let r = f64::from_bits(c.load(Ordering::Relaxed));
                    let x = if r > 0.0 { r } else { 0.0 };
                    *o = x;
                    sum += x;
                }
            }
            Regrets::I32 { cells, .. } => {
                let cells = cells.slice(offset, out.len());
                for (o, c) in out.iter_mut().zip(cells) {
                    let x = c.load(Ordering::Relaxed).max(0) as f64;
                    *o = x;
                    sum += x;
                }
            }
        }
        if sum > 0.0 {
            out.iter_mut().for_each(|x| *x /= sum);
        } else {
            let p = 1.0 / out.len() as f64;
            out.fill(p);
        }
    }

    /// The regret in one slot, in the game's units.
    #[inline]
    pub fn get(&self, slot: usize) -> f64 {
        match self {
            Regrets::F64 { cells, .. } => {
                f64::from_bits(cells.slice(slot, 1)[0].load(Ordering::Relaxed))
            }
            Regrets::I32 { cells, scale, .. } => {
                cells.slice(slot, 1)[0].load(Ordering::Relaxed) as f64 / scale
            }
        }
    }

    /// Adds `delta` (in the game's units) to one slot, keeping the floor.
    #[inline]
    pub fn add(&self, slot: usize, delta: f64) {
        match self {
            Regrets::F64 { cells, floor } => {
                let cell = &cells.slice(slot, 1)[0];
                let mut r = f64::from_bits(cell.load(Ordering::Relaxed)) + delta;
                if let Some(floor) = *floor {
                    if r < floor {
                        r = floor;
                    }
                }
                cell.store(r.to_bits(), Ordering::Relaxed);
            }
            Regrets::I32 {
                cells,
                scale,
                floor,
            } => {
                let cell = &cells.slice(slot, 1)[0];
                // `as i64` saturates, and maps NaN to 0.
                let step = (delta * scale).round() as i64;
                let r = (cell.load(Ordering::Relaxed) as i64).saturating_add(step);
                cell.store(
                    r.clamp(*floor as i64, i32::MAX as i64) as i32,
                    Ordering::Relaxed,
                );
            }
        }
    }

    /// Adds `values[i] - value` to slot `offset + i` for every explored
    /// action: the regret update of one node, with one look-up of the slots.
    #[inline]
    pub fn update(&self, offset: usize, values: &[f64], value: f64, explored: &[bool]) {
        match self {
            Regrets::F64 { cells, floor } => {
                let cells = cells.slice(offset, values.len());
                for ((cell, &u), &seen) in cells.iter().zip(values).zip(explored) {
                    if !seen {
                        continue;
                    }
                    let mut r = f64::from_bits(cell.load(Ordering::Relaxed)) + (u - value);
                    if let Some(floor) = *floor {
                        if r < floor {
                            r = floor;
                        }
                    }
                    cell.store(r.to_bits(), Ordering::Relaxed);
                }
            }
            Regrets::I32 {
                cells,
                scale,
                floor,
            } => {
                let cells = cells.slice(offset, values.len());
                for ((cell, &u), &seen) in cells.iter().zip(values).zip(explored) {
                    if !seen {
                        continue;
                    }
                    let step = ((u - value) * scale).round() as i64;
                    let r = (cell.load(Ordering::Relaxed) as i64).saturating_add(step);
                    cell.store(
                        r.clamp(*floor as i64, i32::MAX as i64) as i32,
                        Ordering::Relaxed,
                    );
                }
            }
        }
    }

    /// Multiplies every regret below `used` by `factor`. Needs the solver to
    /// itself: no traversal may be running.
    pub fn scale_all(&mut self, used: usize, factor: f64) {
        match self {
            Regrets::F64 { cells, .. } => cells.for_each_mut(used, |segment| {
                for c in segment {
                    let x = c.get_mut();
                    *x = (f64::from_bits(*x) * factor).to_bits();
                }
            }),
            Regrets::I32 { cells, .. } => cells.for_each_mut(used, |segment| {
                for c in segment {
                    let x = c.get_mut();
                    *x = (*x as f64 * factor).round() as i32;
                }
            }),
        }
    }

    /// Every slot below `used` as bytes, in order (8 a slot as floats, 4 as
    /// integers): what a checkpoint stores.
    pub fn dump(&self, used: usize, write: impl FnMut(&[u8]) -> io::Result<()>) -> io::Result<()> {
        match self {
            Regrets::F64 { cells, .. } => cells.dump(used, write),
            Regrets::I32 { cells, .. } => cells.dump(used, write),
        }
    }

    /// The opposite of [`Regrets::dump`].
    pub fn load(
        &mut self,
        used: usize,
        read: impl FnMut(&mut [u8]) -> io::Result<()>,
    ) -> io::Result<()> {
        match self {
            Regrets::F64 { cells, .. } => cells.load(used, read),
            Regrets::I32 { cells, .. } => cells.load(used, read),
        }
    }

    /// Bytes one slot takes.
    pub fn bytes_per_slot(&self) -> usize {
        match self {
            Regrets::F64 { .. } => 8,
            Regrets::I32 { .. } => 4,
        }
    }

    pub fn allocated_bytes(&self) -> usize {
        match self {
            Regrets::F64 { cells, .. } => cells.allocated_bytes(),
            Regrets::I32 { cells, .. } => cells.allocated_bytes(),
        }
    }
}

/// The strategy sums: always 64-bit floats.
pub(crate) struct Sums(Segments<AtomicU64>);

impl Sums {
    pub fn new() -> Self {
        Sums(Segments::new())
    }

    #[inline]
    pub fn ensure(&self, slot: usize) {
        self.0.ensure(slot);
    }

    /// Adds `weight * probs[i]` to slot `offset + i`.
    #[inline]
    pub fn add(&self, offset: usize, probs: &[f64], weight: f64) {
        for (c, &p) in self.0.slice(offset, probs.len()).iter().zip(probs) {
            let x = f64::from_bits(c.load(Ordering::Relaxed)) + weight * p;
            c.store(x.to_bits(), Ordering::Relaxed);
        }
    }

    /// Adds `probs[i]` to slot `offset + i`.
    #[inline]
    pub fn add_plain(&self, offset: usize, probs: &[f64]) {
        for (c, &p) in self.0.slice(offset, probs.len()).iter().zip(probs) {
            let x = f64::from_bits(c.load(Ordering::Relaxed)) + p;
            c.store(x.to_bits(), Ordering::Relaxed);
        }
    }

    #[inline]
    pub fn get(&self, slot: usize) -> f64 {
        f64::from_bits(self.0.slice(slot, 1)[0].load(Ordering::Relaxed))
    }

    pub fn scale_all(&mut self, used: usize, factor: f64) {
        self.0.for_each_mut(used, |segment| {
            for c in segment {
                let x = c.get_mut();
                *x = (f64::from_bits(*x) * factor).to_bits();
            }
        });
    }

    pub fn dump(&self, used: usize, write: impl FnMut(&[u8]) -> io::Result<()>) -> io::Result<()> {
        self.0.dump(used, write)
    }

    pub fn load(
        &mut self,
        used: usize,
        read: impl FnMut(&mut [u8]) -> io::Result<()>,
    ) -> io::Result<()> {
        self.0.load(used, read)
    }

    pub fn allocated_bytes(&self) -> usize {
        self.0.allocated_bytes()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slots_map_to_segments_that_double() {
        assert_eq!(locate(0), (0, 0));
        assert_eq!(locate(4095), (0, 4095));
        assert_eq!(locate(4096), (1, 0));
        assert_eq!(locate(4096 + 8191), (1, 8191));
        assert_eq!(locate(4096 + 8192), (2, 0));
        for k in 0..20 {
            assert_eq!(locate(segment_start(k)), (k, 0));
            assert_eq!(
                locate(segment_start(k) + segment_len(k) - 1),
                (k, segment_len(k) - 1)
            );
            assert_eq!(segment_start(k) + segment_len(k), segment_start(k + 1));
        }
    }

    #[test]
    fn an_information_set_never_straddles_two_segments() {
        let cursor = Cursor::new();
        assert_eq!(cursor.take(4000), 0);
        // 96 slots are left in the first segment: 100 don't fit.
        assert_eq!(cursor.take(100), 4096);
        assert_eq!(cursor.take(3), 4196);
        assert_eq!(cursor.used(), 4199);
        let cells: Segments<AtomicU64> = Segments::new();
        cells.ensure(4096);
        assert_eq!(cells.slice(4096, 100).len(), 100);
        assert_eq!(cells.allocated_bytes(), 8192 * 8);
    }

    #[test]
    fn integer_regrets_round_scale_and_stop_at_the_floor() {
        let r = Regrets::new(RegretStorage::I32 { scale: 100.0 }, Some(-5.0));
        r.ensure(0);
        r.add(0, 1.234);
        assert_eq!(r.get(0), 1.23);
        r.add(0, -100.0);
        assert_eq!(r.get(0), -5.0);
        r.add(1, 1e12);
        assert_eq!(r.get(1), i32::MAX as f64 / 100.0);
        r.add(2, f64::NAN);
        assert_eq!(r.get(2), 0.0);
        let mut probs = [0.0; 3];
        r.matching(0, &mut probs);
        assert_eq!(probs, [0.0, 1.0, 0.0]);
        let no_floor = Regrets::new(RegretStorage::I32 { scale: 1.0 }, None);
        no_floor.ensure(0);
        no_floor.add(0, -1e12);
        assert_eq!(no_floor.get(0), i32::MIN as f64);
        no_floor.add(0, -1.0);
        assert_eq!(no_floor.get(0), i32::MIN as f64);
    }

    #[test]
    fn float_regrets_match_plain_regret_matching() {
        let r = Regrets::new(RegretStorage::F64, None);
        r.ensure(0);
        for (i, x) in [0.3, -2.0, 1.7, 0.0].into_iter().enumerate() {
            r.add(i, x);
        }
        let (mut ours, mut plain) = ([0.0; 4], [0.0; 4]);
        r.matching(0, &mut ours);
        crate::policy::regret_matching(&[0.3, -2.0, 1.7, 0.0], &mut plain);
        assert_eq!(ours, plain);
        let mut r = r;
        r.scale_all(4, 0.5);
        assert_eq!(r.get(2), 0.85);
        let mut raw = Vec::new();
        r.dump(4, |bytes| {
            raw.extend_from_slice(bytes);
            Ok(())
        })
        .unwrap();
        assert_eq!(raw.len(), 32);
        let mut copy = Regrets::new(RegretStorage::F64, None);
        let mut at = 0;
        copy.load(4, |bytes| {
            bytes.copy_from_slice(&raw[at..at + bytes.len()]);
            at += bytes.len();
            Ok(())
        })
        .unwrap();
        for i in 0..4 {
            assert_eq!(copy.get(i).to_bits(), r.get(i).to_bits());
        }
    }

    #[test]
    fn a_dump_crosses_segments_and_loads_back() {
        let cells: Segments<AtomicI32> = Segments::new();
        let used = 4096 + 8192 + 100;
        for slot in [0, 4096, 4096 + 8192] {
            cells.ensure(slot);
        }
        for slot in (0..used).step_by(7) {
            cells.slice(slot, 1)[0].store(slot as i32 - 5_000, Ordering::Relaxed);
        }
        let mut raw = Vec::new();
        cells
            .dump(used, |bytes| {
                raw.extend_from_slice(bytes);
                Ok(())
            })
            .unwrap();
        assert_eq!(raw.len(), used * 4);
        let mut back: Segments<AtomicI32> = Segments::new();
        let mut at = 0;
        back.load(used, |bytes| {
            bytes.copy_from_slice(&raw[at..at + bytes.len()]);
            at += bytes.len();
            Ok(())
        })
        .unwrap();
        for slot in 0..used {
            let want = if slot % 7 == 0 {
                slot as i32 - 5_000
            } else {
                0
            };
            assert_eq!(back.slice(slot, 1)[0].load(Ordering::Relaxed), want);
        }
        assert!(Cursor::fits(4000, 96) && !Cursor::fits(4000, 97) && !Cursor::fits(0, 0));
    }
}
