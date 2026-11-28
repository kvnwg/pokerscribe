//! The leaf tables built in parts, as a job that can stop and go on: on a rented machine
//! through `tools/cloud` (its trainer contract), or on any computer with `search leaf`.
//!
//! The turn starts are split into runs of `part_nodes` (in table order), and each run is
//! one part: [`crate::leaf::build_part`] walks every deal for its nodes only. A finished
//! part is written to the job's folder as `part-<k>.leafpart` (a header with the build's
//! fingerprint and a checksum, then its values), whole and then renamed, and the checkpoint
//! `leaf.ckpt` records which parts are done. When every part is there they are put
//! together into the table file (`out`, by default `<strategy file name>.leaf`), the same
//! tables bit for bit as a build in one piece (`crate::leaf::build`).
//!
//! - **Memory** is one part's: the sums of `part_nodes` nodes (8 bytes for each lane and
//!   every pair of flop buckets) and its values, about 0.9 GB at 256 nodes, 7 lanes and 200
//!   buckets (2 GB at 16 lanes), plus the blueprint. In one piece the Phase 6 game's build
//!   would need 29 GB (67 GB at 16 lanes).
//! - **A stop** (SIGTERM, or Ctrl-C with `search leaf`) gives up the part being built and
//!   exits; the next start goes on from the parts on the disk. At most one part's work is
//!   lost.
//! - **On a new machine** `tools/cloud` puts back the checkpoint and every part (they are
//!   artifacts, `*.leafpart`) before the job starts. A part the checkpoint lists but the
//!   disk lacks (its upload was cut off) is built again; a part on the disk is used only if
//!   its header matches this build and its values match their checksum.
//! - **A changed build** (another strategy file, other deals, seed, lanes or part size) is
//!   refused on `--resume`: the checkpoint's fingerprint must match.
//!
//! The config file (`--config`) is JSON:
//!
//! ```json
//! {"strategy": "/opt/pscloud/bundle/files/strategy-512000000.bps",
//!  "tables": "/opt/pscloud/bundle/files/k200",
//!  "deals": 16000000, "seed": 7, "lanes": 16, "part_nodes": 256}
//! ```
//!
//! `tables` (the bucket tables; by default the folder the strategy file names), `lanes`
//! (7, Modicum's, the default; or 16, both players choosing: `crate::leaf`), `part_nodes`
//! (default 256) and `out` (the table file's name in the job's folder) can be left out.

use std::fs;
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use abstract_game::Bucketer;
use nlhe::Street;
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::leaf::{
    self, build_part, cell_deals, fnv, write_header, BuildConfig, Header, BIAS, FNV_START,
    PRIOR_DEALS,
};

/// The checkpoint's name in the job's folder (it matches `tools/cloud`'s `*.ckpt`).
pub const CHECKPOINT: &str = "leaf.ckpt";
const PART_MAGIC: &[u8; 8] = b"PSLEAFP1";
/// Turn starts per part by default: about 0.9 GB of memory at 200 buckets, and about 4
/// minutes a part for the Phase 6 game on 64 cores.
pub const PART_NODES: usize = 256;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct JobConfig {
    /// The strategy file the tables are for.
    pub strategy: PathBuf,
    /// The bucket tables it was trained with (default: the folder the file names).
    #[serde(default)]
    pub tables: Option<PathBuf>,
    pub deals: u64,
    pub seed: u64,
    /// [`leaf::MODICUM_LANES`] (the default) or [`leaf::BOTH_LANES`].
    #[serde(default = "modicum_lanes")]
    pub lanes: usize,
    #[serde(default = "part_nodes")]
    pub part_nodes: usize,
    /// The table file's name in the job's folder (default `<strategy file name>.leaf`).
    #[serde(default)]
    pub out: Option<String>,
}

fn part_nodes() -> usize {
    PART_NODES
}

fn modicum_lanes() -> usize {
    leaf::MODICUM_LANES
}

impl JobConfig {
    pub fn out_name(&self) -> String {
        self.out.clone().unwrap_or_else(|| {
            let name = self
                .strategy
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_else(|| "strategy".into());
            format!("{name}.leaf")
        })
    }

    pub fn check(&self) -> Result<(), String> {
        if self.deals == 0 {
            return Err("deals must be more than 0".into());
        }
        if self.part_nodes == 0 {
            return Err("part_nodes must be more than 0".into());
        }
        if self.lanes != leaf::MODICUM_LANES && self.lanes != leaf::BOTH_LANES {
            return Err(format!(
                "lanes {}: {} or {}",
                self.lanes,
                leaf::MODICUM_LANES,
                leaf::BOTH_LANES
            ));
        }
        let out = self.out_name();
        if out.contains('/') || !out.ends_with(".leaf") {
            return Err(format!("out {out:?}: a file name ending in .leaf"));
        }
        Ok(())
    }
}

/// The checkpoint: what the build is, and which parts were done when it was written.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Checkpoint {
    pub fingerprint: String,
    pub parts: usize,
    pub done: Vec<usize>,
    pub deals: u64,
    pub seed: u64,
    pub part_nodes: usize,
    pub nodes: usize,
    pub strategy_hash: String,
}

/// A part file's header.
#[derive(Clone, Debug, Serialize, Deserialize)]
struct PartHeader {
    fingerprint: String,
    part: usize,
    /// The part's first node, as an index into the table's node list, and how many.
    first: usize,
    nodes: usize,
    values: usize,
    /// FNV-1a of the values' bytes.
    checksum: String,
    /// Deals per cell, summarized and hashed (the same in every part).
    cell_deals: [u64; 3],
    count_hash: String,
    seconds: f64,
}

/// How a run of the job ended.
#[derive(Debug, PartialEq)]
pub enum JobEnd {
    /// Every part is built and the table file is written.
    Done(PathBuf),
    /// A stop was asked for; the parts done are on the disk.
    Stopped,
}

/// The fingerprint of a build: everything its values depend on.
fn fingerprint(strategy_hash: &str, config: &JobConfig, nodes: &[u32], buckets: usize) -> String {
    let id = json!({
        "format": 1,
        "strategy_hash": strategy_hash,
        "deals": config.deals,
        "seed": config.seed,
        "part_nodes": config.part_nodes,
        "nodes": nodes,
        "buckets": buckets,
        "lanes": config.lanes,
        "bias": BIAS,
        "prior_deals": PRIOR_DEALS,
    });
    format!("{:016x}", fnv(FNV_START, id.to_string().as_bytes()))
}

pub fn part_name(k: usize) -> String {
    format!("part-{k:05}.leafpart")
}

/// Writes `dir/name` whole: to a hidden temporary name (which `tools/cloud` never uploads),
/// synced, then renamed. On an error the temporary file is removed.
pub fn write_atomic(
    dir: &Path,
    name: &str,
    write: impl FnOnce(&mut BufWriter<fs::File>) -> io::Result<()>,
) -> io::Result<()> {
    let tmp = dir.join(format!(".{name}.tmp"));
    let written = (|| {
        let mut f = BufWriter::new(fs::File::create(&tmp)?);
        write(&mut f)?;
        f.flush()?;
        f.get_ref().sync_all()
    })();
    if let Err(e) = written {
        let _ = fs::remove_file(&tmp);
        return Err(e);
    }
    fs::rename(&tmp, dir.join(name))
}

fn f32_bytes(values: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(values.len() * 4);
    for x in values {
        out.extend_from_slice(&x.to_le_bytes());
    }
    out
}

fn count_hash(count: &[u64]) -> String {
    let mut h = FNV_START;
    for c in count {
        h = fnv(h, &c.to_le_bytes());
    }
    format!("{h:016x}")
}

fn write_part(dir: &Path, header: &PartHeader, bytes: &[u8]) -> io::Result<()> {
    write_atomic(dir, &part_name(header.part), |f| {
        f.write_all(PART_MAGIC)?;
        let h = serde_json::to_vec(header)?;
        f.write_all(&(h.len() as u64).to_le_bytes())?;
        f.write_all(&h)?;
        f.write_all(bytes)
    })
}

/// A part file's header and where its values start, if it is a part file at all.
fn read_part_header(path: &Path) -> io::Result<(PartHeader, u64)> {
    let bad = |m: &str| io::Error::new(io::ErrorKind::InvalidData, m.to_string());
    let mut f = BufReader::new(fs::File::open(path)?);
    let mut magic = [0u8; 8];
    f.read_exact(&mut magic)?;
    if &magic != PART_MAGIC {
        return Err(bad("not a leaf table part"));
    }
    let mut len = [0u8; 8];
    f.read_exact(&mut len)?;
    let len = u64::from_le_bytes(len);
    if len > 1 << 20 {
        return Err(bad("a part header too long"));
    }
    let mut h = vec![0u8; len as usize];
    f.read_exact(&mut h)?;
    let header: PartHeader = serde_json::from_slice(&h)?;
    Ok((header, 16 + len))
}

/// Whether `dir/part-<k>` is part `k` of this build, whole: its header and size match and
/// its values match their checksum.
fn part_is_good(dir: &Path, k: usize, fp: &str, first: usize, nodes: usize, values: usize) -> bool {
    let path = dir.join(part_name(k));
    let Ok((h, at)) = read_part_header(&path) else {
        return false;
    };
    if h.fingerprint != fp
        || h.part != k
        || h.first != first
        || h.nodes != nodes
        || h.values != values
    {
        return false;
    }
    let Ok(meta) = fs::metadata(&path) else {
        return false;
    };
    if meta.len() != at + 4 * values as u64 {
        return false;
    }
    let Ok(mut f) = fs::File::open(&path) else {
        return false;
    };
    let mut skip = vec![0u8; at as usize];
    if f.read_exact(&mut skip).is_err() {
        return false;
    }
    let mut buf = vec![0u8; 1 << 20];
    let mut sum = FNV_START;
    loop {
        match f.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => sum = fnv(sum, &buf[..n]),
            Err(_) => return false,
        }
    }
    format!("{sum:016x}") == h.checksum
}

/// Runs the job in `dir` for `bp` (loaded from `config.strategy`). `resume` is the trainer
/// contract's `--resume`: the checkpoint must then be there and be this build's. `stop` is
/// asked between blocks of deals. `say` gets one JSON line per event and progress report.
pub fn run<B: Bucketer + Sync>(
    bp: &blueprint::play::Blueprint<B>,
    config: &JobConfig,
    dir: &Path,
    resume: bool,
    stop: &dyn Fn() -> bool,
    say: &mut dyn FnMut(serde_json::Value),
) -> Result<JobEnd, String> {
    run_with_state(bp, config, dir, CHECKPOINT, resume, stop, say)
}

/// [`run`], with the record of the parts done in `dir/<state>` rather than `leaf.ckpt`: the
/// plan job ([`crate::plan_job`]) keeps one checkpoint of its own, so the leaf job's record
/// must not look like one to `tools/cloud`.
pub fn run_with_state<B: Bucketer + Sync>(
    bp: &blueprint::play::Blueprint<B>,
    config: &JobConfig,
    dir: &Path,
    state: &str,
    resume: bool,
    stop: &dyn Fn() -> bool,
    say: &mut dyn FnMut(serde_json::Value),
) -> Result<JobEnd, String> {
    config.check()?;
    fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    let started = Instant::now();
    let strategy_hash = leaf::file_hash(&config.strategy)
        .map_err(|e| format!("{}: {e}", config.strategy.display()))?;
    let nodes = leaf::turn_starts(bp);
    if nodes.is_empty() {
        return Err("the blueprint has no turn starts".into());
    }
    let nb = bp.game().bucketer().num_buckets(Street::Flop) as usize;
    let cells = nb * nb;
    let fp = fingerprint(&strategy_hash, config, &nodes, nb);
    let parts = nodes.len().div_ceil(config.part_nodes);
    let range = |k: usize| {
        let first = k * config.part_nodes;
        (first, (first + config.part_nodes).min(nodes.len()))
    };
    let ckpt_path = dir.join(state);
    let listed: Vec<usize> = if ckpt_path.exists() {
        if !resume {
            return Err(format!(
                "{} is there: start with --resume to go on from it",
                ckpt_path.display()
            ));
        }
        let text = fs::read_to_string(&ckpt_path).map_err(|e| format!("{state}: {e}"))?;
        let c: Checkpoint = serde_json::from_str(&text).map_err(|e| format!("{state}: {e}"))?;
        if c.fingerprint != fp {
            return Err(format!(
                "{state} is for another build (fingerprint {}, this one {fp}): another \
                 strategy file, other deals, seed, lanes or part size",
                c.fingerprint
            ));
        }
        c.done
    } else {
        if resume {
            return Err(format!(
                "--resume, but {} is not there",
                ckpt_path.display()
            ));
        }
        Vec::new()
    };
    // The parts already on the disk, checked.
    let mut done = vec![false; parts];
    for (k, d) in done.iter_mut().enumerate() {
        let (a, b) = range(k);
        *d = part_is_good(dir, k, &fp, a, b - a, (b - a) * config.lanes * cells);
    }
    let rebuilt: Vec<usize> = listed
        .iter()
        .copied()
        .filter(|&k| k < parts && !done[k])
        .collect();
    let save_checkpoint = |done: &[bool]| -> Result<(), String> {
        let c = Checkpoint {
            fingerprint: fp.clone(),
            parts,
            done: (0..parts).filter(|&k| done[k]).collect(),
            deals: config.deals,
            seed: config.seed,
            part_nodes: config.part_nodes,
            nodes: nodes.len(),
            strategy_hash: strategy_hash.clone(),
        };
        let text = serde_json::to_vec_pretty(&c).map_err(|e| e.to_string())?;
        write_atomic(dir, state, |f| f.write_all(&text)).map_err(|e| format!("{state}: {e}"))
    };
    save_checkpoint(&done)?;
    let target = parts as u64 * config.deals;
    let have = done.iter().filter(|&&d| d).count();
    say(json!({
        "event": if resume { "resumed" } else { "started" },
        "iterations": have as u64 * config.deals,
        "target_iterations": target,
        "parts": parts,
        "parts_done": have,
        "parts_listed_but_missing": rebuilt,
        "turn_starts": nodes.len(),
        "buckets": nb,
        "deals": config.deals,
        "seed": config.seed,
        "part_nodes": config.part_nodes,
        "fingerprint": fp,
        "threads": rayon::current_num_threads(),
    }));
    let block = BuildConfig {
        deals: config.deals,
        seed: config.seed,
        lanes: config.lanes,
        ..Default::default()
    };
    for k in 0..parts {
        if done[k] {
            continue;
        }
        let (a, b) = range(k);
        let base = done.iter().filter(|&&d| d).count() as u64 * config.deals;
        let mut last = Instant::now();
        let part = build_part(bp, &nodes[a..b], &block, stop, |deals| {
            if last.elapsed().as_secs_f64() >= 60.0 {
                last = Instant::now();
                say(json!({"iterations": base + deals, "target_iterations": target, "part": k}));
            }
        });
        let Some(part) = part else {
            save_checkpoint(&done)?;
            say(json!({
                "event": "saved on SIGTERM",
                "iterations": base,
                "target_iterations": target,
                "parts_done": done.iter().filter(|&&d| d).count(),
                "parts": parts,
            }));
            return Ok(JobEnd::Stopped);
        };
        let bytes = f32_bytes(&part.q);
        let header = PartHeader {
            fingerprint: fp.clone(),
            part: k,
            first: a,
            nodes: b - a,
            values: part.q.len(),
            checksum: format!("{:016x}", fnv(FNV_START, &bytes)),
            cell_deals: cell_deals(&part.count),
            count_hash: count_hash(&part.count),
            seconds: part.seconds,
        };
        write_part(dir, &header, &bytes).map_err(|e| format!("{}: {e}", part_name(k)))?;
        done[k] = true;
        save_checkpoint(&done)?;
        let have = done.iter().filter(|&&d| d).count();
        say(json!({
            "iterations": have as u64 * config.deals,
            "target_iterations": target,
            "part": k,
            "parts_done": have,
            "parts": parts,
            "part_seconds": part.seconds,
            "node_deals_per_second": (b - a) as f64 * config.deals as f64 / part.seconds,
            "resident_bytes": blueprint::resident_bytes(),
            "peak_resident_bytes": blueprint::peak_resident_bytes(),
        }));
    }
    let out = assemble(dir, config, &nodes, nb, &strategy_hash, parts, &range)?;
    let bytes = fs::metadata(&out).map(|m| m.len()).unwrap_or(0);
    say(json!({
        "event": "done",
        "iterations": target,
        "target_iterations": target,
        "tables": out,
        "tables_bytes": bytes,
        "seconds": started.elapsed().as_secs_f64(),
        "peak_resident_bytes": blueprint::peak_resident_bytes(),
    }));
    Ok(JobEnd::Done(out))
}

/// Puts the parts together into the table file, streaming (never more than a slice of it
/// in memory), whole and then renamed.
fn assemble(
    dir: &Path,
    config: &JobConfig,
    nodes: &[u32],
    nb: usize,
    strategy_hash: &str,
    parts: usize,
    range: &dyn Fn(usize) -> (usize, usize),
) -> Result<PathBuf, String> {
    let mut headers = Vec::with_capacity(parts);
    for k in 0..parts {
        let (h, at) = read_part_header(&dir.join(part_name(k)))
            .map_err(|e| format!("{}: {e}", part_name(k)))?;
        let (a, b) = range(k);
        if h.first != a || h.nodes != b - a {
            return Err(format!(
                "{}: nodes {}..{}, not {a}..{b}",
                part_name(k),
                h.first,
                h.first + h.nodes
            ));
        }
        headers.push((h, at));
    }
    let first = &headers[0].0;
    if headers
        .iter()
        .any(|(h, _)| h.count_hash != first.count_hash)
    {
        return Err("the parts counted the deals per cell differently".into());
    }
    let header = Header {
        nodes: nodes.to_vec(),
        buckets: nb,
        lanes: config.lanes,
        deals: config.deals,
        seed: config.seed,
        bias: BIAS,
        prior_deals: PRIOR_DEALS,
        strategy: config.strategy.display().to_string(),
        strategy_hash: strategy_hash.to_string(),
        cell_deals: first.cell_deals,
        seconds: headers.iter().map(|(h, _)| h.seconds).sum(),
    };
    let name = config.out_name();
    write_atomic(dir, &name, |f| {
        write_header(f, &header)?;
        let mut buf = vec![0u8; 1 << 20];
        for (k, (h, at)) in headers.iter().enumerate() {
            let mut p = fs::File::open(dir.join(part_name(k)))?;
            let mut skip = vec![0u8; *at as usize];
            p.read_exact(&mut skip)?;
            let mut left = 4 * h.values as u64;
            let mut sum = FNV_START;
            while left > 0 {
                let n = (buf.len() as u64).min(left) as usize;
                p.read_exact(&mut buf[..n])?;
                sum = fnv(sum, &buf[..n]);
                f.write_all(&buf[..n])?;
                left -= n as u64;
            }
            // The parts are read once more here, so a part damaged on the disk since it was
            // written (or checked on a resume) stops the file from being written.
            if format!("{sum:016x}") != h.checksum {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("{}: its checksum doesn't match", part_name(k)),
                ));
            }
        }
        Ok(())
    })
    .map_err(|e| format!("{name}: {e}"))?;
    Ok(dir.join(name))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn part(dir: &Path, k: usize, first: usize, values: &[f32]) {
        let bytes = f32_bytes(values);
        let header = PartHeader {
            fingerprint: "f".into(),
            part: k,
            first,
            nodes: 1,
            values: values.len(),
            checksum: format!("{:016x}", fnv(FNV_START, &bytes)),
            cell_deals: [1, 1, 1],
            count_hash: "c".into(),
            seconds: 0.0,
        };
        write_part(dir, &header, &bytes).unwrap();
    }

    #[test]
    fn a_part_damaged_after_it_was_written_stops_the_table_file() {
        let dir = std::env::temp_dir().join(format!("leaf-job-assemble-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let config = JobConfig {
            strategy: PathBuf::from("s.bps"),
            tables: None,
            deals: 1,
            seed: 1,
            lanes: leaf::MODICUM_LANES,
            part_nodes: 1,
            out: None,
        };
        let range = |k: usize| (k, k + 1);
        // One bucket: a node's values are its 7 lanes.
        let a: Vec<f32> = (0..leaf::MODICUM_LANES).map(|i| i as f32).collect();
        let b: Vec<f32> = (0..leaf::MODICUM_LANES).map(|i| 0.5 + i as f32).collect();
        part(&dir, 0, 0, &a);
        part(&dir, 1, 1, &b);
        let out = assemble(&dir, &config, &[10, 20], 1, "h", 2, &range).unwrap();
        let tables = leaf::LeafTables::load(&out).unwrap();
        assert_eq!(tables.values(), [a, b].concat().as_slice());

        // A table file with a byte too many is refused.
        let mut longer = fs::read(&out).unwrap();
        longer.push(0);
        let longer_path = dir.join("longer.leaf");
        fs::write(&longer_path, longer).unwrap();
        assert!(leaf::LeafTables::load(&longer_path).is_err());
        fs::remove_file(&longer_path).unwrap();
        fs::remove_file(&out).unwrap();

        // One value of part 1 changed on the disk: the file is not written, nor left half done.
        let path = dir.join(part_name(1));
        let mut bytes = fs::read(&path).unwrap();
        let last = bytes.len() - 1;
        bytes[last] ^= 1;
        fs::write(&path, bytes).unwrap();
        let err = assemble(&dir, &config, &[10, 20], 1, "h", 2, &range).unwrap_err();
        assert!(
            err.contains("part-00001") && err.contains("checksum"),
            "{err}"
        );
        assert!(!out.exists());
        assert_eq!(
            fs::read_dir(&dir).unwrap().count(),
            2,
            "only the two parts are left"
        );
        fs::remove_dir_all(&dir).unwrap();
    }
}
