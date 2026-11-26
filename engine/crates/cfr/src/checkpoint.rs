//! Saving a Monte Carlo CFR run and picking it up again.
//!
//! A checkpoint holds everything the run is: the settings, the iteration
//! count, every thread's random generator and counters, and each information
//! set's key, regrets and strategy sums, as raw bits. A run on one thread
//! that is saved, loaded and continued ends bit for bit where the same run
//! would have ended without stopping.
//!
//! [`Mccfr::save`] never damages the checkpoint that is already there. It
//! writes the new one to `<path>.tmp`, flushes it to the disk, and only then
//! renames it over `<path>`, which the file system does in one step. Kill
//! the process at any moment and `<path>` is either the old checkpoint or
//! the new one, whole.
//!
//! [`Mccfr::train`] runs with saves along the way: every so many minutes,
//! at the end, and when a stop is asked for ([`crate::signal`]).
//!
//! # File format (version 1, little-endian)
//!
//! ```text
//! "PSCFRCK1"                                  8 bytes
//! version                                     u32
//! sampling 0 external, 1 outcome              u8, then epsilon f64
//! seed                                        u64
//! linear weighting                            u8 (0 or 1), interval u64, until u64
//! pruning                                     u8 (0 or 1), warm-up u64, threshold f64, probability f64
//! regret floor                                u8 (0 or 1), f64
//! regret storage 0 f64, 1 i32                 u8, then scale f64
//! threads                                     u32
//! players of the game                         u32
//! iteration                                   u64
//! thread states                               u32 count, then for each: generator 4 x u64,
//!                                             nodes touched, pruned traversals, pruned actions (u64 each)
//! counts                                      information sets u64, slots u64
//! information sets                            for each: key u64, first slot u64, actions u16, player u8
//! regrets                                     slots x f64 or i32
//! strategy sums                               slots x f64
//! "END_CFR!"                                  8 bytes
//! checksum of everything above                u64
//! ```
//!
//! An information set owns `actions` slots from its first slot on, in both
//! arrays. The arrays are written whole and in order, so saving and loading
//! read memory front to back and go about as fast as the disk does. Slots
//! no information set owns (a few at the end of a block of memory, when the
//! next set didn't fit) are zero.

use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use crate::game::Game;
use crate::mccfr::{
    LinearWeighting, Mccfr, MccfrConfig, MccfrStats, Pause, Pruning, Sampling, Worker,
};
use crate::rng::Rng;
use crate::shared::{Entry, SharedTable};
use crate::signal;
use crate::store::{Cursor, RegretStorage};

const MAGIC: &[u8; 8] = b"PSCFRCK1";
const END: &[u8; 8] = b"END_CFR!";
const VERSION: u32 = 1;
const BUFFER: usize = 1 << 20;
/// Bytes of an information set's record.
const RECORD: usize = 19;

/// A 64-bit checksum taken eight bytes at a time. Each step is a bijection
/// of the running value, so changing any one word always changes the result.
#[derive(Default)]
struct Checksum {
    h: u64,
    tail: [u8; 8],
    tail_len: usize,
    total: u64,
}

impl Checksum {
    #[inline]
    fn word(&mut self, w: u64) {
        self.h = (self.h ^ w).wrapping_mul(0x9E37_79B9_7F4A_7C15);
        self.h ^= self.h >> 32;
    }

    fn update(&mut self, mut bytes: &[u8]) {
        self.total += bytes.len() as u64;
        if self.tail_len > 0 {
            let take = (8 - self.tail_len).min(bytes.len());
            self.tail[self.tail_len..self.tail_len + take].copy_from_slice(&bytes[..take]);
            self.tail_len += take;
            bytes = &bytes[take..];
            if self.tail_len < 8 {
                return;
            }
            self.word(u64::from_le_bytes(self.tail));
            self.tail_len = 0;
        }
        let mut chunks = bytes.chunks_exact(8);
        for chunk in &mut chunks {
            self.word(u64::from_le_bytes(chunk.try_into().unwrap()));
        }
        let rest = chunks.remainder();
        self.tail[..rest.len()].copy_from_slice(rest);
        self.tail_len = rest.len();
    }

    fn finish(&self) -> u64 {
        let mut end = Checksum {
            h: self.h,
            ..Checksum::default()
        };
        let mut tail = [0u8; 8];
        tail[..self.tail_len].copy_from_slice(&self.tail[..self.tail_len]);
        end.word(u64::from_le_bytes(tail));
        end.word(self.total);
        end.h
    }
}

struct Out<W: Write> {
    file: BufWriter<W>,
    sum: Checksum,
}

impl<W: Write> Out<W> {
    fn bytes(&mut self, b: &[u8]) -> io::Result<()> {
        self.sum.update(b);
        self.file.write_all(b)
    }
    fn u8(&mut self, x: u8) -> io::Result<()> {
        self.bytes(&[x])
    }
    fn u32(&mut self, x: u32) -> io::Result<()> {
        self.bytes(&x.to_le_bytes())
    }
    fn u64(&mut self, x: u64) -> io::Result<()> {
        self.bytes(&x.to_le_bytes())
    }
    fn f64(&mut self, x: f64) -> io::Result<()> {
        self.u64(x.to_bits())
    }
    /// A present-or-absent setting: a flag, then its numbers either way, so
    /// every checkpoint's header has the same layout.
    fn flag(&mut self, present: bool) -> io::Result<()> {
        self.u8(present as u8)
    }
}

struct In<R: Read> {
    file: R,
    sum: Checksum,
}

fn bad(what: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, what.into())
}

impl<R: Read> In<R> {
    fn bytes(&mut self, b: &mut [u8]) -> io::Result<()> {
        self.file.read_exact(b).map_err(|e| {
            if e.kind() == io::ErrorKind::UnexpectedEof {
                bad("the checkpoint is cut short")
            } else {
                e
            }
        })?;
        self.sum.update(b);
        Ok(())
    }
    fn u8(&mut self) -> io::Result<u8> {
        let mut b = [0; 1];
        self.bytes(&mut b)?;
        Ok(b[0])
    }
    fn u32(&mut self) -> io::Result<u32> {
        let mut b = [0; 4];
        self.bytes(&mut b)?;
        Ok(u32::from_le_bytes(b))
    }
    fn u64(&mut self) -> io::Result<u64> {
        let mut b = [0; 8];
        self.bytes(&mut b)?;
        Ok(u64::from_le_bytes(b))
    }
    fn f64(&mut self) -> io::Result<f64> {
        Ok(f64::from_bits(self.u64()?))
    }
    fn flag(&mut self) -> io::Result<bool> {
        match self.u8()? {
            0 => Ok(false),
            1 => Ok(true),
            x => Err(bad(format!("a flag is {x}, not 0 or 1"))),
        }
    }
}

fn tmp_path(path: &Path) -> PathBuf {
    let mut name = path.file_name().unwrap_or_default().to_os_string();
    name.push(".tmp");
    path.with_file_name(name)
}

impl<G: Game> Mccfr<G> {
    /// Saves the whole run to `path`, replacing what is there in one step
    /// (see the module text). Call it between iterations, which is the only
    /// time `&self` can be had.
    pub fn save(&self, path: impl AsRef<Path>) -> io::Result<()> {
        let path = path.as_ref();
        let tmp = tmp_path(path);
        if let Err(e) = self.write_checkpoint(&tmp) {
            let _ = fs::remove_file(&tmp);
            return Err(e);
        }
        fs::rename(&tmp, path)?;
        // The rename itself must reach the disk too. Not every system lets a
        // directory be opened and synced; the checkpoint is whole either way.
        if let Some(dir) = path.parent() {
            let dir = if dir.as_os_str().is_empty() {
                Path::new(".")
            } else {
                dir
            };
            if let Ok(d) = File::open(dir) {
                let _ = d.sync_all();
            }
        }
        Ok(())
    }

    fn write_checkpoint(&self, path: &Path) -> io::Result<()> {
        let file = File::create(path)?;
        let mut out = Out {
            file: BufWriter::with_capacity(BUFFER, file),
            sum: Checksum::default(),
        };
        let cfg = &self.core.cfg;
        out.bytes(MAGIC)?;
        out.u32(VERSION)?;
        match cfg.sampling {
            Sampling::External => {
                out.u8(0)?;
                out.f64(0.0)?;
            }
            Sampling::Outcome { epsilon } => {
                out.u8(1)?;
                out.f64(epsilon)?;
            }
        }
        out.u64(cfg.seed)?;
        let linear = cfg.linear.unwrap_or(LinearWeighting {
            interval: 0,
            until: 0,
        });
        out.flag(cfg.linear.is_some())?;
        out.u64(linear.interval)?;
        out.u64(linear.until)?;
        let pruning = cfg.pruning.unwrap_or(Pruning {
            warmup: 0,
            threshold: 0.0,
            probability: 0.0,
        });
        out.flag(cfg.pruning.is_some())?;
        out.u64(pruning.warmup)?;
        out.f64(pruning.threshold)?;
        out.f64(pruning.probability)?;
        out.flag(cfg.regret_floor.is_some())?;
        out.f64(cfg.regret_floor.unwrap_or(0.0))?;
        match cfg.storage {
            RegretStorage::F64 => {
                out.u8(0)?;
                out.f64(0.0)?;
            }
            RegretStorage::I32 { scale } => {
                out.u8(1)?;
                out.f64(scale)?;
            }
        }
        out.u32(cfg.threads as u32)?;
        out.u32(self.core.game.num_players() as u32)?;
        out.u64(self.iteration)?;
        out.u32(self.workers.len() as u32)?;
        for w in &self.workers {
            for word in w.rng.state() {
                out.u64(word)?;
            }
            out.u64(w.stats.nodes_touched)?;
            out.u64(w.stats.pruned_traversals)?;
            out.u64(w.stats.pruned_actions)?;
        }
        let used = self.core.table.used_slots();
        out.u64(self.core.table.len() as u64)?;
        out.u64(used as u64)?;
        let mut records = Vec::with_capacity(BUFFER + RECORD);
        let mut failed = None;
        let mut written = 0usize;
        self.core.table.for_each(|e| {
            records.extend_from_slice(&e.key.to_le_bytes());
            records.extend_from_slice(&(e.offset as u64).to_le_bytes());
            records.extend_from_slice(&(e.num_actions as u16).to_le_bytes());
            records.push(e.player as u8);
            written += 1;
            if records.len() >= BUFFER && failed.is_none() {
                failed = out.bytes(&records).err();
                records.clear();
            }
        });
        if let Some(err) = failed {
            return Err(err);
        }
        out.bytes(&records)?;
        debug_assert_eq!(written, self.core.table.len());
        self.core.regret.dump(used, |bytes| out.bytes(bytes))?;
        self.core.sums.dump(used, |bytes| out.bytes(bytes))?;
        out.bytes(END)?;
        let sum = out.sum.finish();
        out.file.write_all(&sum.to_le_bytes())?;
        out.file.flush()?;
        out.file.get_ref().sync_all()
    }

    /// Loads the run saved at `path`, ready to continue. `game` must be the
    /// game the run was started on: a checkpoint holds keys, not rules. The
    /// thread count is the saved one; change it with [`Mccfr::set_threads`].
    ///
    /// A file that is cut short, altered, or not a checkpoint gives an
    /// `InvalidData` error and no solver.
    pub fn resume(game: G, path: impl AsRef<Path>) -> io::Result<Self> {
        let file = File::open(path.as_ref())?;
        let size = file.metadata()?.len();
        let mut inp = In {
            file: BufReader::with_capacity(BUFFER, file),
            sum: Checksum::default(),
        };
        let mut magic = [0; 8];
        inp.bytes(&mut magic)?;
        if &magic != MAGIC {
            return Err(bad("not a cfr checkpoint"));
        }
        let version = inp.u32()?;
        if version != VERSION {
            return Err(bad(format!(
                "checkpoint version {version}, this build reads version {VERSION}"
            )));
        }
        let (tag, epsilon) = (inp.u8()?, inp.f64()?);
        let sampling = match tag {
            0 => Sampling::External,
            1 if epsilon > 0.0 && epsilon <= 1.0 => Sampling::Outcome { epsilon },
            _ => return Err(bad("unknown sampling")),
        };
        let seed = inp.u64()?;
        let (has, interval, until) = (inp.flag()?, inp.u64()?, inp.u64()?);
        if has && interval == 0 {
            return Err(bad("a linear weighting interval of 0"));
        }
        let linear = has.then_some(LinearWeighting { interval, until });
        let (has, warmup, threshold, probability) =
            (inp.flag()?, inp.u64()?, inp.f64()?, inp.f64()?);
        if has && !(sampling == Sampling::External && (0.0..=1.0).contains(&probability)) {
            return Err(bad("pruning settings that make no sense"));
        }
        let pruning = has.then_some(Pruning {
            warmup,
            threshold,
            probability,
        });
        let (has, floor) = (inp.flag()?, inp.f64()?);
        let regret_floor = has.then_some(floor);
        let (tag, scale) = (inp.u8()?, inp.f64()?);
        let storage = match tag {
            0 => RegretStorage::F64,
            1 if scale.is_finite() && scale > 0.0 => RegretStorage::I32 { scale },
            _ => return Err(bad("unknown regret storage")),
        };
        let threads = inp.u32()? as usize;
        if threads == 0 || (threads > 1 && sampling != Sampling::External) {
            return Err(bad("a thread count that makes no sense"));
        }
        let cfg = MccfrConfig {
            sampling,
            seed,
            linear,
            pruning,
            regret_floor,
            storage,
            threads,
        };
        let players = inp.u32()? as usize;
        if players != game.num_players() {
            return Err(bad(format!(
                "the checkpoint is of a game with {players} players, this game has {}",
                game.num_players()
            )));
        }
        let iteration = inp.u64()?;
        let saved_workers = inp.u32()? as usize;
        if saved_workers != threads {
            return Err(bad("thread states that don't match the thread count"));
        }
        let mut workers = Vec::with_capacity(threads);
        for _ in 0..saved_workers {
            let state = [inp.u64()?, inp.u64()?, inp.u64()?, inp.u64()?];
            if state == [0; 4] {
                return Err(bad("a random generator with no state"));
            }
            let mut w = Worker::new(Rng::from_state(state));
            w.stats = MccfrStats {
                nodes_touched: inp.u64()?,
                pruned_traversals: inp.u64()?,
                pruned_actions: inp.u64()?,
            };
            workers.push(w);
        }
        let (info_sets, used) = (inp.u64()?, inp.u64()?);
        let per_slot = match storage {
            RegretStorage::F64 => 16,
            RegretStorage::I32 { .. } => 12,
        };
        // Counts the file can't hold are a damaged file, not a reason to
        // reserve memory.
        if info_sets.saturating_mul(RECORD as u64) > size
            || used.saturating_mul(per_slot) > size
            || used > 1 << 40
        {
            return Err(bad("more information sets than the file can hold"));
        }
        let used = used as usize;
        let mut solver =
            Mccfr::from_parts(game, cfg, SharedTable::with_capacity(info_sets as usize));
        solver.workers = workers;
        solver.iteration = iteration;
        let mut records = vec![0u8; BUFFER / RECORD * RECORD];
        let mut left = info_sets as usize;
        let mut owned = 0usize;
        while left > 0 {
            let n = left.min(records.len() / RECORD);
            inp.bytes(&mut records[..n * RECORD])?;
            for r in records[..n * RECORD].chunks_exact(RECORD) {
                let e = Entry {
                    key: u64::from_le_bytes(r[0..8].try_into().unwrap()),
                    offset: u64::from_le_bytes(r[8..16].try_into().unwrap()) as usize,
                    num_actions: u16::from_le_bytes(r[16..18].try_into().unwrap()) as usize,
                    player: r[18] as usize,
                };
                // Inside the arrays and inside one block of memory. Two sets
                // on the same slots would be a file `save` never writes, and
                // the checksum at the end answers for that.
                if e.player >= players
                    || e.offset >= used
                    || e.num_actions > used - e.offset
                    || !Cursor::fits(e.offset, e.num_actions)
                {
                    return Err(bad(format!("information set {:#x} is damaged", e.key)));
                }
                owned += e.num_actions;
                if !solver.core.table.restore(e) {
                    return Err(bad(format!("information set {:#x} is there twice", e.key)));
                }
            }
            left -= n;
        }
        if owned > used {
            return Err(bad("information sets that share slots"));
        }
        solver.core.table.restore_used(used);
        solver.core.regret.load(used, |bytes| inp.bytes(bytes))?;
        solver.core.sums.load(used, |bytes| inp.bytes(bytes))?;
        let mut end = [0; 8];
        inp.bytes(&mut end)?;
        if &end != END {
            return Err(bad("the checkpoint doesn't end where it should"));
        }
        let expected = inp.sum.finish();
        let mut stored = [0; 8];
        inp.file
            .read_exact(&mut stored)
            .map_err(|_| bad("the checkpoint is cut short"))?;
        if u64::from_le_bytes(stored) != expected {
            return Err(bad(
                "the checkpoint's checksum doesn't match: the file is damaged",
            ));
        }
        if inp.file.read(&mut [0u8; 1])? != 0 {
            return Err(bad("bytes after the end of the checkpoint"));
        }
        solver.core.table.collect();
        Ok(solver)
    }
}

/// Where and how often [`Mccfr::train`] saves.
#[derive(Clone, Debug, PartialEq)]
pub struct Checkpoints {
    path: PathBuf,
    every: Option<Duration>,
}

impl Checkpoints {
    /// Save to `path` when training ends or is asked to stop.
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Checkpoints {
            path: path.into(),
            every: None,
        }
    }

    /// Also save every `minutes` minutes (fractions allowed), counted from
    /// the end of the save before.
    pub fn every_minutes(self, minutes: f64) -> Self {
        assert!(
            minutes.is_finite() && minutes > 0.0,
            "save every so many minutes: more than 0"
        );
        self.every(Duration::from_secs_f64(minutes * 60.0))
    }

    /// The same, as a [`Duration`].
    pub fn every(mut self, interval: Duration) -> Self {
        self.every = Some(interval);
        self
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn interval(&self) -> Option<Duration> {
        self.every
    }
}

/// Why [`Mccfr::train`] returned.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stop {
    /// It reached the iteration asked for.
    Finished,
    /// A stop was asked for: a watched signal, or [`signal::request_stop`].
    Requested,
}

/// What a call to [`Mccfr::train`] did.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TrainReport {
    pub stop: Stop,
    /// Checkpoints written, the last one included.
    pub saves: u32,
    /// How long the slowest of them took. On a Spot machine this has to
    /// stay well under the 30 seconds between SIGTERM and the shutdown.
    pub longest_save: Duration,
}

impl<G: Game + Sync> Mccfr<G> {
    /// Runs until `until` iterations have been done in all (not `until`
    /// more), saving to `checkpoints` on the way if given: every
    /// [`Checkpoints::every_minutes`], at the end, and when a stop is asked
    /// for, after which it returns at once with [`Stop::Requested`].
    ///
    /// For a machine that can be taken away, call
    /// [`signal::watch_sigterm`] first, then:
    ///
    /// ```no_run
    /// # use cfr::{signal, Checkpoints, Mccfr, MccfrConfig, Sampling, Stop};
    /// # fn run<G: cfr::Game + Sync + Copy>(game: G) -> std::io::Result<()> {
    /// signal::watch_sigterm()?;
    /// let saves = Checkpoints::new("blueprint.ckpt").every_minutes(10.0);
    /// let mut solver = match Mccfr::resume(game, saves.path()) {
    ///     Ok(solver) => solver,
    ///     Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
    ///         Mccfr::new(game, MccfrConfig::new(Sampling::External, 1).threads(64))
    ///     }
    ///     Err(e) => return Err(e),
    /// };
    /// if solver.train(1_000_000_000, Some(&saves))?.stop == Stop::Requested {
    ///     // SIGTERM: the state is on disk. Exit; the next start resumes.
    /// }
    /// # Ok(()) }
    /// ```
    ///
    /// A save that fails returns the error; the run in memory is untouched
    /// and `train` can be called again.
    pub fn train(
        &mut self,
        until: u64,
        checkpoints: Option<&Checkpoints>,
    ) -> io::Result<TrainReport> {
        let mut saves = 0;
        let mut longest_save = Duration::ZERO;
        loop {
            let done = self.iteration >= until;
            let asked = signal::stop_requested();
            if !done && !asked {
                let pause = Pause {
                    deadline: checkpoints
                        .and_then(|c| c.every)
                        .map(|every| Instant::now() + every),
                };
                self.advance(until, Some(&pause));
                self.core.table.collect();
            }
            let done = self.iteration >= until;
            let asked = signal::stop_requested();
            // Here for one of three reasons: finished, asked to stop, or a
            // save is due. Each of them saves.
            if let Some(c) = checkpoints {
                let start = Instant::now();
                self.save(&c.path)?;
                saves += 1;
                longest_save = longest_save.max(start.elapsed());
            }
            if done || asked {
                return Ok(TrainReport {
                    stop: if done {
                        Stop::Finished
                    } else {
                        Stop::Requested
                    },
                    saves,
                    longest_save,
                });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_checksum_does_not_depend_on_how_the_bytes_arrive() {
        let data: Vec<u8> = (0..1000u32).map(|i| (i * 7 + 3) as u8).collect();
        let mut whole = Checksum::default();
        whole.update(&data);
        for step in [1, 3, 8, 13, 64, 999] {
            let mut parts = Checksum::default();
            data.chunks(step).for_each(|c| parts.update(c));
            assert_eq!(parts.finish(), whole.finish(), "pieces of {step}");
        }
        let mut changed = data.clone();
        changed[517] ^= 1;
        let mut other = Checksum::default();
        other.update(&changed);
        assert_ne!(other.finish(), whole.finish());
        // A missing zero byte at the end changes it too.
        let mut longer = Checksum::default();
        longer.update(&[data.as_slice(), &[0]].concat());
        assert_ne!(longer.finish(), whole.finish());
    }

    #[test]
    fn the_temporary_file_sits_next_to_the_checkpoint() {
        assert_eq!(
            tmp_path(Path::new("/a/b/run.ckpt")),
            Path::new("/a/b/run.ckpt.tmp")
        );
        assert_eq!(tmp_path(Path::new("run")), Path::new("run.tmp"));
    }
}
