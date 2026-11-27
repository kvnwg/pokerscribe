//! Training a blueprint: external-sampling MCCFR from the cfr crate on the abstract game
//! with the abstraction crate's buckets, with checkpoints so a run can be stopped and
//! resumed (on the same machine or a bigger one).
//!
//! A run lives in a directory:
//!
//! | File | What |
//! | --- | --- |
//! | `spec.json` | The [`Spec`]. A resumed run must be given the same one (threads may differ) |
//! | `checkpoint.ckpt` | The cfr crate's checkpoint: every regret and strategy sum |
//! | `log.jsonl` | One line per training session: iterations, seconds, speed, memory |

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use abstract_game::AbstractGame;
use cfr::{Checkpoints, Mccfr, Solver, Stop};
use serde::{Deserialize, Serialize};

use crate::buckets::Buckets;
use crate::file::{Export, StrategyFile};
use crate::spec::Spec;

/// The game a blueprint trains on.
pub type BlueprintGame = AbstractGame<Arc<Buckets>>;

/// One training session, as `log.jsonl` records it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Session {
    /// Iterations at the start and the end of the session.
    pub from: u64,
    pub to: u64,
    pub seconds: f64,
    pub threads: usize,
    pub iterations_per_second: f64,
    /// Game states visited per second, over every thread.
    pub nodes_per_second: f64,
    /// Information sets met so far, and the memory the tables take for them.
    pub info_sets: usize,
    pub slots: usize,
    pub bytes_per_info_set: f64,
    pub table_bytes: usize,
    /// The resident memory of the whole process (bucket tables included), from
    /// `/proc/self/status`, when the system offers it.
    pub resident_bytes: Option<u64>,
    pub saves: u32,
    pub longest_save_seconds: f64,
    /// True when a stop was asked for (SIGTERM) before `to` was reached.
    pub stopped: bool,
}

/// A run: its spec, its tables and the solver.
pub struct Run {
    pub spec: Spec,
    pub buckets: Arc<Buckets>,
    pub solver: Mccfr<BlueprintGame>,
    dir: PathBuf,
    sessions: Vec<Session>,
}

fn bad(m: String) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, m)
}

/// The resident memory of this process in bytes (Linux), or `None`.
pub fn resident_bytes() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    let line = status.lines().find(|l| l.starts_with("VmRSS:"))?;
    let kb: u64 = line.split_whitespace().nth(1)?.parse().ok()?;
    Some(kb * 1024)
}

/// The highest resident memory of this process so far, in bytes (Linux), or `None`.
pub fn peak_resident_bytes() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    let line = status.lines().find(|l| l.starts_with("VmHWM:"))?;
    let kb: u64 = line.split_whitespace().nth(1)?.parse().ok()?;
    Some(kb * 1024)
}

/// Builds the game of a spec with tables already loaded.
pub fn build_game(spec: &Spec, buckets: Arc<Buckets>) -> io::Result<BlueprintGame> {
    let config = spec.game_config().map_err(bad)?;
    AbstractGame::new(config, buckets).map_err(|e| bad(e.to_string()))
}

impl Run {
    pub fn checkpoint_path(dir: &Path) -> PathBuf {
        dir.join("checkpoint.ckpt")
    }

    /// Opens the run in `dir`: resumes its checkpoint if there is one (the spec must be the
    /// one it was started with, apart from the thread count), else starts it.
    pub fn open(spec: Spec, dir: &Path) -> io::Result<Run> {
        let buckets = Arc::new(Buckets::load(&spec.abstraction)?);
        Run::open_with(spec, dir, buckets)
    }

    /// As [`Run::open`] with tables already loaded.
    pub fn open_with(spec: Spec, dir: &Path, buckets: Arc<Buckets>) -> io::Result<Run> {
        fs::create_dir_all(dir)?;
        let spec_path = dir.join("spec.json");
        if spec_path.exists() {
            let saved = Spec::from_json(&fs::read_to_string(&spec_path)?).map_err(bad)?;
            let mut a = saved.clone();
            let mut b = spec.clone();
            a.training.threads = 0;
            b.training.threads = 0;
            if a != b {
                return Err(bad(format!(
                    "{} holds another run: its spec is\n{}",
                    dir.display(),
                    saved.to_json()
                )));
            }
        }
        fs::write(&spec_path, spec.to_json())?;
        let game = build_game(&spec, buckets.clone())?;
        let mut solver = match Mccfr::resume(game, Run::checkpoint_path(dir)) {
            Ok(solver) => solver,
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                let game = build_game(&spec, buckets.clone())?;
                Mccfr::new(game, spec.training.mccfr_config())
            }
            Err(e) => return Err(e),
        };
        if solver.config().threads != spec.training.threads {
            solver.set_threads(spec.training.threads);
        }
        let sessions = match fs::read_to_string(dir.join("log.jsonl")) {
            Ok(text) => text
                .lines()
                .filter(|l| !l.trim().is_empty())
                .map(|l| serde_json::from_str(l).map_err(|e| bad(e.to_string())))
                .collect::<io::Result<Vec<Session>>>()?,
            Err(e) if e.kind() == io::ErrorKind::NotFound => Vec::new(),
            Err(e) => return Err(e),
        };
        Ok(Run {
            spec,
            buckets,
            solver,
            dir: dir.to_path_buf(),
            sessions,
        })
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    pub fn sessions(&self) -> &[Session] {
        &self.sessions
    }

    /// Seconds of training over every session so far.
    pub fn train_seconds(&self) -> f64 {
        self.sessions.iter().map(|s| s.seconds).sum()
    }

    /// Trains until `until` iterations in all, saving every `every_minutes` if given and at
    /// the end, and appends the session to `log.jsonl`. A SIGTERM (once
    /// `cfr::signal::watch_sigterm` is on) saves and returns early with `stopped` set.
    pub fn train(&mut self, until: u64, every_minutes: Option<f64>) -> io::Result<Session> {
        let mut saves = Checkpoints::new(Run::checkpoint_path(&self.dir));
        if let Some(m) = every_minutes {
            saves = saves.every_minutes(m);
        }
        let from = self.solver.iterations();
        let nodes_before = self.solver.nodes_touched();
        let start = Instant::now();
        let report = self.solver.train(until, Some(&saves))?;
        let seconds = start.elapsed().as_secs_f64();
        let done = self.solver.iterations() - from;
        let save_seconds = report.longest_save.as_secs_f64() * report.saves as f64;
        // Speed over the training only: the saves are left out (an upper bound on what
        // they took, since only the longest is known).
        let busy = (seconds - save_seconds).max(seconds * 0.5).max(1e-9);
        let memory = self.solver.memory();
        let session = Session {
            from,
            to: self.solver.iterations(),
            seconds,
            threads: self.solver.config().threads,
            iterations_per_second: done as f64 / busy,
            nodes_per_second: (self.solver.nodes_touched() - nodes_before) as f64 / busy,
            info_sets: memory.info_sets,
            slots: memory.slots,
            bytes_per_info_set: memory.bytes_per_info_set(),
            table_bytes: memory.index_bytes + memory.regret_bytes + memory.strategy_bytes,
            resident_bytes: resident_bytes(),
            saves: report.saves,
            longest_save_seconds: report.longest_save.as_secs_f64(),
            stopped: report.stop == Stop::Requested,
        };
        let mut log = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.dir.join("log.jsonl"))?;
        writeln!(
            log,
            "{}",
            serde_json::to_string(&session).expect("valid JSON")
        )?;
        self.sessions.push(session.clone());
        Ok(session)
    }

    /// The average strategy as a strategy file, with each information set's visit weight.
    pub fn export(&self) -> Export {
        StrategyFile::from_solver(
            &self.solver,
            Some(self.spec.clone()),
            Some(self.buckets.info().clone()),
            self.train_seconds(),
        )
    }
}
