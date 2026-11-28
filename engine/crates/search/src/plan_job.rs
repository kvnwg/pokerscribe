//! Phase 7's runs as one job on a rented machine, under the `tools/cloud` trainer contract
//! (`search --config F --checkpoint-dir D [--resume]`), in the order pre-registered in
//! `docs/research/experiments.md` ("Phase 7: the plan at 200 big blinds"):
//!
//! 1. **leaf**: the leaf tables ([`crate::leaf_job`]), in parts, then the table file.
//! 2. **bench**: decision time per street, one decision at a time on `bench.threads`
//!    threads (`bench.json`), against the bounds (`bounds.json`). A street over its bound
//!    ends the job there, before any match (`end.json`).
//! 3. **pilot**: the gate agent against the blueprint (`pilot.json`), for its sd a deal.
//! 4. **size**: N from the pilot's sd by the size rule (`size.json`).
//! 5. **gate**: the gate match, N deals in chunks (`match-NN.json`, chunk k on seed
//!    `gate.seed + k`), then its reading (`gate.json`).
//! 6. **variants**: the reported A/B matches against the blueprint, each with its own
//!    settings and seeds (`variant-NAME-NN.json`, then `variant-NAME.json`).
//! 7. **lbr**: LBR against the blueprint and against the gate agent on the same deals
//!    (`lbr-WHO-SETTING-K.json` and `.deals`, `compare-SETTING-K.json`).
//! 8. **repeat**: the gate match again on fresh seeds (`repeat-NN.json`, `repeat.json`),
//!    only after a pass.
//!
//! Then `end.json`, and the job exits 0.
//!
//! Every result is a file in the job's folder, written whole and then renamed; they are
//! `tools/cloud` artifacts (`*.json`, `*.deals` and the leaf table parts, `*.leafpart`), so
//! a new machine gets them back. Each step skips the results already there. A stop
//! (SIGTERM) gives up the run being played (the leaf part, the bench, or a chunk) and exits
//! at once; the next start plays it again from its start, with the same seed. The
//! checkpoint (`plan.ckpt`) holds the plan's fingerprint: another plan or strategy file is
//! refused on `--resume`.
//!
//! The leaf table file (`<strategy file name>.leaf`) is not an artifact: a new machine puts
//! it together again from the parts (the leaf job does that when every part is there).
//!
//! The config file is JSON, every field required except `tables` and `leaf.part_nodes`:
//!
//! ```json
//! {"strategy": "/opt/pscloud/bundle/files/strategy-512000000.bps",
//!  "tables": "/opt/pscloud/bundle/files/k200",
//!  "leaf": {"deals": 16000000, "seed": 7, "lanes": 16, "part_nodes": 256},
//!  "agent": {"leaf_choice": "both", "play": "average"},
//!  "bench": {"hands": 200, "seed": 7581, "threads": 4,
//!            "bound_ms": {"flop": 40000, "turn": 65000, "river": 2000}},
//!  "pilot": {"deals": 2000, "seed": 7501},
//!  "size": {"edge_bb_per_100": 10, "z": 2.5, "step": 2000, "min": 4000, "max": 40000},
//!  "gate": {"chunk": 2000, "seed": 7600, "pass_z": 2.5},
//!  "variants": [{"name": "modicum", "agent": {"leaf_choice": "opponent", "play": "average"},
//!                "chunks": 4, "seed": 7800}],
//!  "lbr": {"hands": 1000, "chunks": 2,
//!          "settings": [{"name": "fcpa14", "seed": 7560}, {"name": "b56_14", "seed": 7570}]},
//!  "repeat": {"seed": 7700}}
//! ```

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, RecvTimeoutError};
use std::sync::Arc;
use std::time::Duration;

use abstract_game::Bucketer;
use blueprint::play::Blueprint;
use blueprint::Deals;
use lbr::Strategy;
use nlhe::Street;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::leaf::{self, fnv, LeafTables, FNV_START};
use crate::leaf_job::{self, write_atomic, JobConfig, JobEnd};
use crate::runs;
use crate::solve::{check_lanes, play_named, LeafChoice, Settings};
use crate::SearchAgent;

/// The job's checkpoint (it matches `tools/cloud`'s `*.ckpt`).
pub const CHECKPOINT: &str = "plan.ckpt";
/// The leaf job's record of its parts, inside the plan's folder (not a checkpoint).
pub const LEAF_STATE: &str = "leaf.state";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanConfig {
    pub strategy: PathBuf,
    /// The bucket tables (default: the folder the strategy file names).
    #[serde(default)]
    pub tables: Option<PathBuf>,
    pub leaf: LeafPlan,
    /// The gate agent: the one judged.
    pub agent: AgentPlan,
    pub bench: BenchPlan,
    pub pilot: MatchPlan,
    pub size: SizeRule,
    pub gate: GatePlan,
    #[serde(default)]
    pub variants: Vec<VariantPlan>,
    pub lbr: LbrPlan,
    pub repeat: RepeatPlan,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LeafPlan {
    pub deals: u64,
    pub seed: u64,
    pub lanes: usize,
    #[serde(default = "part_nodes")]
    pub part_nodes: usize,
}

fn part_nodes() -> usize {
    leaf_job::PART_NODES
}

/// Search settings: `leaf_choice` opponent or both, `play` average or final, and the
/// iteration caps and prune when given (the rest, and those left out, are
/// [`Settings::default`]).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentPlan {
    pub leaf_choice: String,
    pub play: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flop_iterations: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub turn_iterations: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub river_iterations: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prune: Option<f64>,
}

impl AgentPlan {
    pub fn settings(&self) -> Result<Settings, String> {
        let leaf_choice = LeafChoice::named(&self.leaf_choice)
            .ok_or_else(|| format!("leaf_choice {:?}: opponent or both", self.leaf_choice))?;
        let play = play_named(&self.play)
            .ok_or_else(|| format!("play {:?}: average or final", self.play))?;
        let d = Settings::default();
        Ok(Settings {
            leaf_choice,
            play,
            flop_iterations: self.flop_iterations.unwrap_or(d.flop_iterations),
            turn_iterations: self.turn_iterations.unwrap_or(d.turn_iterations),
            river_iterations: self.river_iterations.unwrap_or(d.river_iterations),
            prune: self.prune.unwrap_or(d.prune),
            ..d
        })
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BenchPlan {
    pub hands: u64,
    pub seed: u64,
    pub threads: usize,
    /// The slowest decision allowed on each street, in ms.
    pub bound_ms: Bounds,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bounds {
    pub flop: f64,
    pub turn: f64,
    pub river: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MatchPlan {
    pub deals: u64,
    pub seed: u64,
}

/// N = (z * sd / edge)^2 deals, rounded up to a multiple of `step`, within `min` and `max`:
/// the deals a result of `z` standard errors needs at an edge of `edge_bb_per_100`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SizeRule {
    pub edge_bb_per_100: f64,
    pub z: f64,
    pub step: u64,
    pub min: u64,
    pub max: u64,
}

impl SizeRule {
    pub fn deals_for(&self, sd: f64) -> u64 {
        let n = (self.z * sd / self.edge_bb_per_100).powi(2);
        let n = (n / self.step as f64).ceil() as u64 * self.step;
        n.clamp(self.min, self.max)
    }
}

/// The gate match: chunks of `chunk` deals, chunk k (from 1) on seed `seed + k`; it
/// passes at a pooled z of `pass_z` or more.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GatePlan {
    pub chunk: u64,
    pub seed: u64,
    pub pass_z: f64,
}

/// A reported match against the blueprint: `chunks` chunks of the gate's size, chunk k on
/// seed `seed + k`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VariantPlan {
    pub name: String,
    pub agent: AgentPlan,
    pub chunks: u64,
    pub seed: u64,
}

/// LBR against both agents: for each setting, `chunks` runs of `hands` hands, run k on
/// seed `seed + k`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LbrPlan {
    pub hands: u64,
    pub chunks: u64,
    pub settings: Vec<LbrSettingPlan>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LbrSettingPlan {
    pub name: String,
    pub seed: u64,
}

/// The repeat: the gate's chunks again, chunk k on seed `seed + k`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RepeatPlan {
    pub seed: u64,
}

impl PlanConfig {
    /// The plan read from JSON, checked.
    pub fn from_json(text: &str) -> Result<PlanConfig, String> {
        let c: PlanConfig = serde_json::from_str(text).map_err(|e| e.to_string())?;
        c.check()?;
        Ok(c)
    }

    /// A plan whose runs can all be played, on seeds no two matches share.
    pub fn check(&self) -> Result<(), String> {
        if self.leaf.lanes != leaf::MODICUM_LANES && self.leaf.lanes != leaf::BOTH_LANES {
            return Err(format!(
                "leaf.lanes: {} or {}",
                leaf::MODICUM_LANES,
                leaf::BOTH_LANES
            ));
        }
        if self.leaf.deals == 0 || self.leaf.part_nodes == 0 {
            return Err("leaf.deals and leaf.part_nodes: above 0".into());
        }
        for (what, a) in std::iter::once(("agent", &self.agent))
            .chain(self.variants.iter().map(|v| ("a variant", &v.agent)))
        {
            let s = a.settings().map_err(|e| format!("{what}: {e}"))?;
            check_lanes(self.leaf.lanes, s.leaf_choice).map_err(|e| format!("{what}: {e}"))?;
        }
        let b = &self.bench;
        if b.hands == 0 || b.threads == 0 {
            return Err("bench.hands and bench.threads: above 0".into());
        }
        if [b.bound_ms.flop, b.bound_ms.turn, b.bound_ms.river]
            .iter()
            .any(|&x| x.is_nan() || x <= 0.0)
        {
            return Err("bench.bound_ms: above 0 on every street".into());
        }
        let z = &self.size;
        if !(z.edge_bb_per_100 > 0.0 && z.z > 0.0) || z.step == 0 || z.min > z.max {
            return Err("size: edge and z above 0, a step, min <= max".into());
        }
        if !z.min.is_multiple_of(z.step) || !z.max.is_multiple_of(z.step) {
            return Err("size: min and max are multiples of step".into());
        }
        let g = &self.gate;
        if g.chunk == 0 || !z.step.is_multiple_of(g.chunk) {
            return Err("gate.chunk: above 0, and size.step a multiple of it".into());
        }
        if self.pilot.deals < 2 {
            return Err("pilot.deals: 2 or more (an sd needs two)".into());
        }
        let mut names: Vec<&str> = Vec::new();
        for v in &self.variants {
            let ok = !v.name.is_empty()
                && v.name
                    .chars()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
            if !ok || names.contains(&v.name.as_str()) {
                return Err(format!("variant name {:?}: new, a-z, 0-9 and _", v.name));
            }
            if v.chunks == 0 {
                return Err(format!("variant {}: chunks above 0", v.name));
            }
            names.push(&v.name);
        }
        let l = &self.lbr;
        if l.hands == 0 || l.chunks == 0 {
            return Err("lbr.hands and lbr.chunks: above 0".into());
        }
        for s in &l.settings {
            blueprint::gate::lbr_setting(&s.name)
                .ok_or_else(|| format!("lbr setting {:?} is not known", s.name))?;
        }
        // The match seeds: the pilot's, then each chunked match's range.
        let most = z.max / g.chunk;
        let mut ranges: Vec<(String, u64, u64)> = vec![
            ("pilot".into(), self.pilot.seed, self.pilot.seed),
            ("gate".into(), g.seed + 1, g.seed + most),
            (
                "repeat".into(),
                self.repeat.seed + 1,
                self.repeat.seed + most,
            ),
        ];
        for v in &self.variants {
            ranges.push((format!("variant {}", v.name), v.seed + 1, v.seed + v.chunks));
        }
        for (i, a) in ranges.iter().enumerate() {
            for b in &ranges[i + 1..] {
                if a.1 <= b.2 && b.1 <= a.2 {
                    return Err(format!("the {} and {} matches share seeds", a.0, b.0));
                }
            }
        }
        Ok(())
    }

    fn leaf_job(&self) -> JobConfig {
        JobConfig {
            strategy: self.strategy.clone(),
            tables: self.tables.clone(),
            deals: self.leaf.deals,
            seed: self.leaf.seed,
            lanes: self.leaf.lanes,
            part_nodes: self.leaf.part_nodes,
            out: None,
        }
    }
}

/// The job's checkpoint: which plan it is for, and the step it was at.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Checkpoint {
    pub fingerprint: String,
    pub step: String,
}

#[derive(Clone, Debug, PartialEq)]
pub enum PlanEnd {
    /// Every step is played (or the bench ended the plan): `end.json`.
    Done(Value),
    /// A stop was asked for; the results done are on the disk.
    Stopped,
}

fn fingerprint(config: &PlanConfig, strategy_hash: &str) -> String {
    let text = serde_json::to_string(config).expect("a plan serializes");
    let h = fnv(fnv(FNV_START, text.as_bytes()), strategy_hash.as_bytes());
    format!("{h:016x}")
}

/// Runs `f` on its own thread and waits for it, asking `stop` four times a second. `None`
/// when a stop came first (the thread is left behind: the caller exits); an error when `f`
/// panicked.
fn unit<T: Send + 'static>(
    stop: &dyn Fn() -> bool,
    f: impl FnOnce() -> T + Send + 'static,
) -> Result<Option<T>, String> {
    let (tx, rx) = channel();
    std::thread::spawn(move || {
        let _ = tx.send(f());
    });
    loop {
        match rx.recv_timeout(Duration::from_millis(250)) {
            Ok(v) => return Ok(Some(v)),
            Err(RecvTimeoutError::Timeout) => {
                if stop() {
                    return Ok(None);
                }
            }
            Err(RecvTimeoutError::Disconnected) => return Err("a run panicked".into()),
        }
    }
}

fn write_json(dir: &Path, name: &str, v: &Value) -> Result<(), String> {
    let text = serde_json::to_vec_pretty(v).map_err(|e| e.to_string())?;
    write_atomic(dir, name, |f| f.write_all(&text)).map_err(|e| format!("{name}: {e}"))
}

/// A result file, when it is there and reads as JSON.
fn read_json(dir: &Path, name: &str) -> Option<Value> {
    let text = fs::read(dir.join(name)).ok()?;
    serde_json::from_slice(&text).ok()
}

/// One agent's line of a match report.
fn agent_of<'a>(report: &'a Value, name: &str) -> Result<&'a Value, String> {
    report["results"]
        .as_array()
        .and_then(|r| r.iter().find(|a| a["agent"] == name))
        .ok_or_else(|| format!("a match report without {name}"))
}

/// The search agent's result over match reports (independent chunks), pooled: the mean
/// weighted by deals, its standard error, z, illegal actions of both agents and hours.
pub fn pool(reports: &[Value]) -> Result<Value, String> {
    let (mut total, mut sum, mut var, mut illegal, mut seconds) = (0u64, 0.0, 0.0, 0u64, 0.0);
    let mut seeds = Vec::new();
    for r in reports {
        let s = agent_of(r, "search")?;
        let n = r["deals"].as_u64().ok_or("a report without deals")?;
        let mean = s["bb_per_100"]
            .as_f64()
            .ok_or("a result without bb_per_100")?;
        let se = s["se"].as_f64().ok_or("a result without se")?;
        total += n;
        sum += mean * n as f64;
        var += (se * n as f64).powi(2);
        illegal += s["illegal_actions"].as_u64().unwrap_or(0)
            + agent_of(r, "blueprint")?["illegal_actions"]
                .as_u64()
                .unwrap_or(0);
        seconds += r["timing"]["seconds"].as_f64().unwrap_or(0.0);
        seeds.push(r["config"]["seed"].clone());
    }
    if total == 0 {
        return Err("no deals to pool".into());
    }
    let mean = sum / total as f64;
    let se = var.sqrt() / total as f64;
    Ok(
        json!({"deals": total, "hands": 2 * total, "bb_per_100": mean, "se": se,
              "z": if se > 0.0 { mean / se } else { 0.0 }, "illegal_actions": illegal,
              "hours": seconds / 3600.0, "seeds": seeds}),
    )
}

/// The bench's slowest decision per street against the bounds.
pub fn bounds(bench: &Value, b: &Bounds) -> Value {
    let mut streets = serde_json::Map::new();
    let mut over = Vec::new();
    for (street, limit) in [("flop", b.flop), ("turn", b.turn), ("river", b.river)] {
        let x = &bench[street];
        let decisions = x["decisions"].as_u64().unwrap_or(0);
        let slowest = x["decision_ms_max"].as_f64().filter(|_| decisions > 0);
        let within = slowest.is_none_or(|ms| ms <= limit);
        if !within {
            over.push(street);
        }
        streets.insert(
            street.into(),
            json!({"decisions": decisions, "max_ms": slowest, "bound_ms": limit, "within": within}),
        );
    }
    json!({"streets": streets, "bounded": over.is_empty(), "over": over})
}

/// N from the pilot, by the size rule.
pub fn size(pilot: &Value, config: &PlanConfig) -> Result<Value, String> {
    let deals = pilot["deals"].as_u64().ok_or("a pilot without deals")?;
    let s = agent_of(pilot, "search")?;
    let se = s["se"].as_f64().ok_or("a pilot without an SE")?;
    let sd = se * (deals as f64).sqrt();
    let n = config.size.deals_for(sd);
    let chunks = n / config.gate.chunk;
    let per_deal = pilot["timing"]["seconds"].as_f64().unwrap_or(0.0) / deals as f64;
    Ok(json!({
        "pilot_deals": deals, "pilot_seed": pilot["config"]["seed"],
        "pilot_bb_per_100": s["bb_per_100"], "pilot_se": se, "sd_per_deal": sd,
        "illegal_actions": s["illegal_actions"],
        "deals": n, "chunk": config.gate.chunk, "chunks": chunks, "hands": 2 * n,
        "edge_seen_at_z": config.size.z * sd / (n as f64).sqrt(),
        "seconds_per_deal": per_deal, "hours": n as f64 * per_deal / 3600.0,
        "seeds": (1..=chunks).map(|k| config.gate.seed + k).collect::<Vec<_>>(),
    }))
}

struct Job<'a, B> {
    bp: Arc<Blueprint<B>>,
    config: &'a PlanConfig,
    dir: &'a Path,
    stop: &'a dyn Fn() -> bool,
    say: &'a mut dyn FnMut(Value),
    fingerprint: String,
    table_path: PathBuf,
    tables: Option<Arc<LeafTables>>,
}

impl<B: Bucketer + Send + Sync + 'static> Job<'_, B> {
    fn checkpoint(&self, step: &str) -> Result<(), String> {
        let c = Checkpoint {
            fingerprint: self.fingerprint.clone(),
            step: step.into(),
        };
        write_json(self.dir, CHECKPOINT, &serde_json::to_value(c).unwrap())
    }

    fn stopped(&mut self, step: &str) -> Result<PlanEnd, String> {
        (self.say)(json!({"event": "saved on SIGTERM", "step": step}));
        Ok(PlanEnd::Stopped)
    }

    /// The leaf tables, loaded once (`None`: a stop came first).
    fn tables(&mut self) -> Result<Option<Arc<LeafTables>>, String> {
        if self.tables.is_none() {
            let path = self.table_path.clone();
            (self.say)(json!({"event": "loading the leaf tables", "file": path}));
            let loaded = unit(self.stop, move || {
                LeafTables::load(&path).map_err(|e| format!("{}: {e}", path.display()))
            })?;
            let Some(t) = loaded else { return Ok(None) };
            self.tables = Some(Arc::new(t?));
            (self.say)(json!({"event": "loaded the leaf tables",
                              "resident_bytes": blueprint::resident_bytes()}));
        }
        Ok(self.tables.clone())
    }

    fn agent(&mut self, settings: &Settings) -> Result<Option<SearchAgent<B>>, String> {
        let Some(tables) = self.tables()? else {
            return Ok(None);
        };
        Ok(Some(SearchAgent::new(
            Arc::clone(&self.bp),
            Some(tables),
            settings.clone(),
        )))
    }

    /// One match of the search agent with `settings` against the blueprint, as `name`
    /// (`None`: a stop came first). A result already there is read, not played again.
    fn play(
        &mut self,
        name: &str,
        settings: &Settings,
        deals: u64,
        seed: u64,
    ) -> Result<Option<Value>, String> {
        if let Some(v) = read_json(self.dir, name) {
            return Ok(Some(v));
        }
        let Some(searcher) = self.agent(settings)? else {
            return Ok(None);
        };
        let bp = Arc::clone(&self.bp);
        let stack = bp.game().config().stack;
        let report = unit(self.stop, move || {
            let opponent = bp as Arc<dyn Strategy + Send + Sync>;
            runs::head_to_head(
                ("search", Arc::new(searcher)),
                ("blueprint", opponent),
                stack,
                deals,
                seed,
                0,
            )
        })?;
        let Some(report) = report else {
            return Ok(None);
        };
        let v = serde_json::to_value(report?).map_err(|e| e.to_string())?;
        write_json(self.dir, name, &v)?;
        Ok(Some(v))
    }

    /// `chunks` chunks of a match (`PREFIX-NN.json`, chunk k on seed `seed + k`), then
    /// their pooled result (`None`: a stop came first).
    fn chunked(
        &mut self,
        step: &str,
        prefix: &str,
        settings: &Settings,
        chunks: u64,
        seed: u64,
    ) -> Result<Option<Value>, String> {
        let chunk = self.config.gate.chunk;
        let mut reports = Vec::new();
        for k in 1..=chunks {
            let name = format!("{prefix}-{k:02}.json");
            let Some(r) = self.play(&name, settings, chunk, seed + k)? else {
                return Ok(None);
            };
            let s = agent_of(&r, "search")?;
            (self.say)(json!({"step": step, "file": name, "iterations": k * chunk,
                              "target_iterations": chunks * chunk,
                              "bb_per_100": s["bb_per_100"], "se": s["se"],
                              "peak_resident_bytes": blueprint::peak_resident_bytes()}));
            reports.push(r);
        }
        pool(&reports).map(Some)
    }

    /// One LBR run against `who` (`blueprint` or `search`, the gate agent), written as
    /// `lbr-WHO-SETTING-K.json` and `.deals` (`None`: a stop came first).
    fn lbr(&mut self, who: &str, setting: &str, k: u64, seed: u64) -> Result<Option<()>, String> {
        let stem = format!("lbr-{who}-{setting}-{k}");
        let (json_name, deals_name) = (format!("{stem}.json"), format!("{stem}.deals"));
        if read_json(self.dir, &json_name).is_some() && self.dir.join(&deals_name).exists() {
            return Ok(Some(()));
        }
        let searcher = if who == "search" {
            let Some(mut a) = self.agent(&self.config.agent.settings()?)? else {
                return Ok(None);
            };
            a.keep_records = true;
            Some(Arc::new(a))
        } else {
            None
        };
        let bp = Arc::clone(&self.bp);
        let stack = bp.game().config().stack;
        let (who_s, setting_s, hands) =
            (who.to_string(), setting.to_string(), self.config.lbr.hands);
        let run = unit(self.stop, move || {
            let agent: Arc<dyn Strategy + Send + Sync> = match &searcher {
                Some(a) => Arc::clone(a) as Arc<dyn Strategy + Send + Sync>,
                None => bp as Arc<dyn Strategy + Send + Sync>,
            };
            runs::lbr_run(
                &who_s,
                agent,
                searcher.as_deref(),
                &setting_s,
                stack,
                hands,
                seed,
            )
        })?;
        let Some(run) = run else {
            return Ok(None);
        };
        let (deals, summary) = run?;
        let tmp = self.dir.join(format!(".{deals_name}.tmp"));
        deals
            .save(&tmp)
            .and_then(|_| fs::rename(&tmp, self.dir.join(&deals_name)))
            .map_err(|e| format!("{deals_name}: {e}"))?;
        write_json(self.dir, &json_name, &summary)?;
        Ok(Some(()))
    }

    fn end(&mut self, v: Value) -> Result<PlanEnd, String> {
        write_json(self.dir, "end.json", &v)?;
        self.checkpoint("done")?;
        (self.say)(json!({"event": "done", "end": v["end"]}));
        Ok(PlanEnd::Done(v))
    }
}

/// Whether `path` is the table file of the leaf build `job` (its header matches): then the
/// leaf step is done.
fn table_is_built<B: Bucketer>(
    path: &Path,
    job: &JobConfig,
    hash: &str,
    bp: &Blueprint<B>,
) -> bool {
    let Ok(h) = LeafTables::read_header(path) else {
        return false;
    };
    h.lanes == job.lanes
        && h.deals == job.deals
        && h.seed == job.seed
        && h.strategy_hash == hash
        && h.buckets == bp.game().bucketer().num_buckets(Street::Flop) as usize
        && h.nodes == leaf::turn_starts(bp)
}

/// Runs the plan in `dir` for `bp` (loaded from `config.strategy`). `resume` is the trainer
/// contract's `--resume`: the checkpoint must then be there and be this plan's. `stop` is
/// asked while each run plays. `say` gets one JSON line per event and result.
pub fn run<B: Bucketer + Send + Sync + 'static>(
    bp: Arc<Blueprint<B>>,
    config: &PlanConfig,
    dir: &Path,
    resume: bool,
    stop: &dyn Fn() -> bool,
    say: &mut dyn FnMut(Value),
) -> Result<PlanEnd, String> {
    config.check()?;
    fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    let hash = leaf::file_hash(&config.strategy)
        .map_err(|e| format!("{}: {e}", config.strategy.display()))?;
    let fp = fingerprint(config, &hash);
    let ckpt = dir.join(CHECKPOINT);
    match (ckpt.exists(), resume) {
        (true, false) => {
            return Err(format!(
                "{} is there: start with --resume to go on from it",
                ckpt.display()
            ))
        }
        (false, true) => return Err(format!("--resume, but {} is not there", ckpt.display())),
        (true, true) => {
            let text = fs::read_to_string(&ckpt).map_err(|e| format!("{CHECKPOINT}: {e}"))?;
            let c: Checkpoint =
                serde_json::from_str(&text).map_err(|e| format!("{CHECKPOINT}: {e}"))?;
            if c.fingerprint != fp {
                return Err(format!(
                    "{CHECKPOINT} is for another plan (fingerprint {}, this one {fp}): another \
                     config or strategy file",
                    c.fingerprint
                ));
            }
        }
        (false, false) => {}
    }
    let leaf_job = config.leaf_job();
    let mut job = Job {
        table_path: dir.join(leaf_job.out_name()),
        bp,
        config,
        dir,
        stop,
        say,
        fingerprint: fp.clone(),
        tables: None,
    };
    if resume {
        if let Some(end) = read_json(dir, "end.json") {
            return Ok(PlanEnd::Done(end));
        }
    }
    job.checkpoint("leaf")?;
    (job.say)(
        json!({"event": if resume { "resumed" } else { "started" }, "fingerprint": fp,
                     "threads": rayon::current_num_threads()}),
    );

    // 1. The leaf tables.
    if !table_is_built(&job.table_path, &leaf_job, &hash, &job.bp) {
        let resume_leaf = dir.join(LEAF_STATE).exists();
        // The build's lines carry the step, and its own start and end are named as the
        // build's, so that the plan's first and last lines stay the only "started",
        // "resumed" and "done".
        let say = &mut *job.say;
        let mut leaf_say = |mut v: Value| {
            let renamed = match v["event"].as_str() {
                Some("started") => Some("leaf build started"),
                Some("resumed") => Some("leaf build resumed"),
                Some("done") => Some("leaf tables built"),
                _ => None,
            };
            if let Some(name) = renamed {
                v["event"] = json!(name);
            }
            v["step"] = json!("leaf");
            say(v)
        };
        let end = leaf_job::run_with_state(
            &job.bp,
            &leaf_job,
            dir,
            LEAF_STATE,
            resume_leaf,
            job.stop,
            &mut leaf_say,
        )?;
        if end == JobEnd::Stopped {
            return Ok(PlanEnd::Stopped);
        }
    }

    // 2. Decision time, against the bounds.
    job.checkpoint("bench")?;
    let gate_settings = config.agent.settings()?;
    if read_json(dir, "bench.json").is_none() {
        let Some(tables) = job.tables()? else {
            return job.stopped("bench");
        };
        let b = config.bench.clone();
        let bp = Arc::clone(&job.bp);
        let settings = Settings {
            turn_threads: b.threads,
            ..gate_settings.clone()
        };
        (job.say)(json!({"event": "bench", "hands": b.hands, "threads": b.threads}));
        let bench = unit(job.stop, move || {
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(b.threads)
                .build()
                .map_err(|e| e.to_string())?;
            let mut agent = SearchAgent::new(bp, Some(tables), settings);
            Ok::<_, String>(pool.install(|| runs::bench(&mut agent, b.hands, b.seed)))
        })?;
        let Some(bench) = bench else {
            return job.stopped("bench");
        };
        write_json(dir, "bench.json", &bench?)?;
    }
    let bench = read_json(dir, "bench.json").ok_or("bench.json does not read")?;
    let bounds = bounds(&bench, &config.bench.bound_ms);
    write_json(dir, "bounds.json", &bounds)?;
    (job.say)(json!({"step": "bench", "bounds": bounds}));
    if bounds["bounded"] != true {
        return job.end(
            json!({"end": "a street is over its bound: no match was played",
                              "bounds": bounds}),
        );
    }

    // 3 and 4. The pilot, and N.
    job.checkpoint("pilot")?;
    let Some(pilot) = job.play(
        "pilot.json",
        &gate_settings,
        config.pilot.deals,
        config.pilot.seed,
    )?
    else {
        return job.stopped("pilot");
    };
    let size = size(&pilot, config)?;
    write_json(dir, "size.json", &size)?;
    (job.say)(
        json!({"step": "size", "deals": size["deals"], "chunks": size["chunks"],
                     "sd_per_deal": size["sd_per_deal"]}),
    );
    let chunks = size["chunks"].as_u64().unwrap();

    // 5. The gate match.
    job.checkpoint("gate")?;
    let Some(mut gate) = job.chunked("gate", "match", &gate_settings, chunks, config.gate.seed)?
    else {
        return job.stopped("gate");
    };
    let z = gate["z"].as_f64().unwrap_or(0.0);
    let passes = z >= config.gate.pass_z;
    gate["pass_z"] = json!(config.gate.pass_z);
    gate["passes"] = json!(passes);
    write_json(dir, "gate.json", &gate)?;
    (job.say)(
        json!({"step": "gate", "bb_per_100": gate["bb_per_100"], "se": gate["se"],
                     "z": z, "passes": passes}),
    );

    // 6. The variants, reported.
    job.checkpoint("variants")?;
    let mut variants = serde_json::Map::new();
    for v in &config.variants {
        let settings = v.agent.settings()?;
        let prefix = format!("variant-{}", v.name);
        let Some(mut r) = job.chunked("variants", &prefix, &settings, v.chunks, v.seed)? else {
            return job.stopped("variants");
        };
        let (m, se) = (r["bb_per_100"].as_f64().unwrap(), r["se"].as_f64().unwrap());
        let (gm, gse) = (
            gate["bb_per_100"].as_f64().unwrap(),
            gate["se"].as_f64().unwrap(),
        );
        let dse = (se * se + gse * gse).sqrt();
        r["agent"] = serde_json::to_value(&v.agent).unwrap();
        r["minus_gate_agent"] = json!({"bb_per_100": m - gm, "se": dse,
                                       "z": if dse > 0.0 { (m - gm) / dse } else { 0.0 },
                                       "paired": false});
        write_json(dir, &format!("{prefix}.json"), &r)?;
        variants.insert(v.name.clone(), r);
    }

    // 7. LBR against both agents, the same deals for both.
    job.checkpoint("lbr")?;
    let mut lbr = serde_json::Map::new();
    for s in &config.lbr.settings {
        let mut rows = Vec::new();
        for k in 1..=config.lbr.chunks {
            for who in ["blueprint", "search"] {
                if job.lbr(who, &s.name, k, s.seed + k)?.is_none() {
                    return job.stopped("lbr");
                }
            }
            let load = |who: &str| {
                let f = format!("lbr-{who}-{}-{k}.deals", s.name);
                Deals::load(&dir.join(&f)).map_err(|e| format!("{f}: {e}"))
            };
            let c = runs::compare(&load("search")?, &load("blueprint")?)?;
            write_json(dir, &format!("compare-{}-{k}.json", s.name), &c)?;
            (job.say)(json!({"step": "lbr", "setting": s.name, "run": k,
                             "iterations": k, "target_iterations": config.lbr.chunks,
                             "search_minus_blueprint": c["a_minus_b"], "se": c["se"]}));
            rows.push(c);
        }
        lbr.insert(s.name.clone(), Value::Array(rows));
    }

    // 8. The repeat, after a pass.
    let mut repeat = Value::Null;
    if passes {
        job.checkpoint("repeat")?;
        let Some(r) = job.chunked(
            "repeat",
            "repeat",
            &gate_settings,
            chunks,
            config.repeat.seed,
        )?
        else {
            return job.stopped("repeat");
        };
        write_json(dir, "repeat.json", &r)?;
        repeat = r;
    }
    job.end(
        json!({"end": "every step is played", "gate": gate, "repeat": repeat,
                   "variants": variants, "lbr": lbr, "bounds": bounds, "size": size}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plan() -> PlanConfig {
        PlanConfig::from_json(
            r#"{"strategy": "s.bps",
                "leaf": {"deals": 16000000, "seed": 7, "lanes": 16},
                "agent": {"leaf_choice": "both", "play": "average"},
                "bench": {"hands": 200, "seed": 7581, "threads": 4,
                          "bound_ms": {"flop": 40000, "turn": 65000, "river": 2000}},
                "pilot": {"deals": 2000, "seed": 7501},
                "size": {"edge_bb_per_100": 10, "z": 2.5, "step": 2000, "min": 4000, "max": 40000},
                "gate": {"chunk": 2000, "seed": 7600, "pass_z": 2.5},
                "variants": [{"name": "modicum", "agent": {"leaf_choice": "opponent", "play": "average"},
                              "chunks": 4, "seed": 7800}],
                "lbr": {"hands": 1000, "chunks": 2,
                        "settings": [{"name": "fcpa14", "seed": 7560}, {"name": "b56_14", "seed": 7570}]},
                "repeat": {"seed": 7700}}"#,
        )
        .unwrap()
    }

    /// The plan pre-registered for the run (`docs/research/runs/phase7/phase7.json`) reads
    /// and can be played.
    #[test]
    fn the_registered_plan_reads() {
        let p = PlanConfig::from_json(include_str!(
            "../../../../docs/research/runs/phase7/phase7.json"
        ))
        .unwrap();
        assert_eq!(p.leaf.lanes, leaf::BOTH_LANES);
        assert_eq!(p.agent.settings().unwrap().leaf_choice, LeafChoice::Both);
        let d = Settings::default();
        let s = p.agent.settings().unwrap();
        assert_eq!(
            (
                s.flop_iterations,
                s.turn_iterations,
                s.river_iterations,
                s.prune
            ),
            (
                d.flop_iterations,
                d.turn_iterations,
                d.river_iterations,
                d.prune
            )
        );
        assert_eq!(
            (p.gate.seed, p.repeat.seed, p.pilot.seed),
            (7600, 7700, 7501)
        );
        assert_eq!(p.size.deals_for(800.0), 40_000);
    }

    #[test]
    fn the_size_rule_rounds_up_within_its_limits() {
        let r = plan().size;
        // (2.5 x 800 / 10)^2 = 40,000; 600 gives 22,500, up to 24,000.
        assert_eq!(r.deals_for(800.0), 40_000);
        assert_eq!(r.deals_for(600.0), 24_000);
        assert_eq!(r.deals_for(1_000.0), 40_000);
        assert_eq!(r.deals_for(100.0), 4_000);
    }

    #[test]
    fn chunks_pool_by_deals() {
        let chunk = |mean: f64, se: f64, deals: u64, seed: u64| {
            json!({"deals": deals, "config": {"seed": seed}, "timing": {"seconds": 3600.0},
                   "results": [{"agent": "search", "bb_per_100": mean, "se": se, "illegal_actions": 0},
                               {"agent": "blueprint", "bb_per_100": -mean, "se": se, "illegal_actions": 1}]})
        };
        let p = pool(&[chunk(10.0, 20.0, 2000, 7601), chunk(4.0, 20.0, 2000, 7602)]).unwrap();
        assert_eq!(p["deals"], 4000);
        assert!((p["bb_per_100"].as_f64().unwrap() - 7.0).abs() < 1e-12);
        let se = p["se"].as_f64().unwrap();
        assert!((se - 20.0 / 2f64.sqrt()).abs() < 1e-9, "{se}");
        assert_eq!(p["illegal_actions"], 2);
        assert_eq!(p["hours"], 2.0);
        assert_eq!(p["seeds"], json!([7601, 7602]));
    }

    #[test]
    fn a_plan_that_cannot_be_played_is_refused() {
        assert!(plan().check().is_ok());
        let mut p = plan();
        p.leaf.lanes = 7;
        assert!(p.check().unwrap_err().contains("needs 16"));
        let mut p = plan();
        p.repeat.seed = 7605; // inside the gate's seeds
        assert!(p.check().unwrap_err().contains("share seeds"));
        let mut p = plan();
        p.variants[0].seed = 7500; // its first chunk is the pilot's seed
        assert!(p.check().unwrap_err().contains("share seeds"));
        let mut p = plan();
        p.gate.chunk = 3000; // the step is not a multiple of it
        assert!(p.check().is_err());
        let mut p = plan();
        p.agent.play = "last".into();
        assert!(p.check().is_err());
        let mut p = plan();
        p.lbr.settings[0].name = "fcpa99".into();
        assert!(p.check().is_err());
        let unknown = serde_json::to_string(&plan())
            .unwrap()
            .replacen("{", "{\"extra\": 1, ", 1);
        assert!(PlanConfig::from_json(&unknown).is_err());
    }

    #[test]
    fn the_bounds_name_the_streets_over() {
        let b = plan().bench.bound_ms;
        let bench = json!({"flop": {"decisions": 3, "decision_ms_max": 41000.0},
                           "turn": {"decisions": 2, "decision_ms_max": 1000.0},
                           "river": {"decisions": 0, "decision_ms_max": null}});
        let r = bounds(&bench, &b);
        assert_eq!(r["bounded"], false);
        assert_eq!(r["over"], json!(["flop"]));
        assert_eq!(r["streets"]["river"]["within"], true);
    }
}
