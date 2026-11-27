//! The Phase 5 gate procedure: train each planned blueprint in doubling stages, measure
//! LBR after every stage on the same deals, stop a run when the last doubling no longer
//! moves LBR by much (and, if asked, no longer moves the strategy by much), then measure
//! the final strategy with every LBR setting.
//!
//! Everything runs in one process, so LBR's exact preflop table (about three minutes on
//! four cores) is built once. Every result is written as it comes, and a plan that is
//! started again picks up where it stopped: trained stages, LBR results and finished runs
//! are read back, not redone.
//!
//! In `plan.dir/<run name>/`: the run's own files ([`crate::Run`]), `strategy-<N>.bps`
//! after each stage, `stages.jsonl` (training), `lbr.jsonl` (LBR after each stage),
//! `final.jsonl` (the final measurement), `deals/` (every deal's result, for paired
//! comparisons), and `done.json` once the run is finished.

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use lbr::{LbrConfig, MatchConfig, Strategy};
use nlhe::Street;
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::file::{Layout, StrategyFile};
use crate::matches::{lbr_match, Deals};
use crate::play::{Blueprint, SmallBets};
use crate::spec::Spec;
use crate::train::{build_game, peak_resident_bytes, Run};
use crate::Buckets;

/// LBR settings by short name, with the paper's name: `fc14`, `fc34`, `fcpa14`, `fcpa34`,
/// `b56_14`, `b56_34` (fold and call; plus pot and all in; the 56 bets; thinking from the
/// preflop or from the turn).
pub fn lbr_setting(name: &str) -> Option<(&'static str, LbrConfig)> {
    Some(match name {
        "fcpa34" => ("fcpa, rounds 3-4", LbrConfig::fcpa(Street::Turn)),
        "fcpa14" => ("fcpa, rounds 1-4", LbrConfig::fcpa(Street::Preflop)),
        "fc34" => ("fc, rounds 3-4", LbrConfig::fc(Street::Turn)),
        "fc14" => ("fc, rounds 1-4", LbrConfig::fc(Street::Preflop)),
        "b56_34" => ("56 bets, rounds 3-4", LbrConfig::bets56(Street::Turn)),
        "b56_14" => ("56 bets, rounds 1-4", LbrConfig::bets56(Street::Preflop)),
        _ => return None,
    })
}

/// How LBR is run at one point of the plan.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LbrPlan {
    pub hands: u64,
    pub seed: u64,
    /// Short names ([`lbr_setting`]). After each stage the first one decides when to stop.
    pub settings: Vec<String>,
}

/// When a run has trained enough: the last doubling moved the stopping measure (up or
/// down) by less than `relative` of its value before, or by less than `sigmas` standard
/// errors of the difference (counted deal by deal); and, when `max_change` is given, the
/// average strategy moved by at most that much over the doubling
/// ([`StrategyFile::change_from`]: the share of play that changed, each information set
/// weighted by how often it is reached).
///
/// Both ways, because LBR can rise as a strategy converges: a coarse abstraction's
/// equilibrium can be more exploitable in the real game than a strategy on the way to it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct StopRule {
    pub relative: f64,
    pub sigmas: f64,
    #[serde(default)]
    pub max_change: Option<f64>,
}

/// The change recorded for `stage` in a run's `stages.jsonl`, if any.
fn recorded_change(dir: &Path, stage: u64) -> Option<f64> {
    let text = fs::read_to_string(dir.join("stages.jsonl")).ok()?;
    text.lines()
        .filter_map(|l| serde_json::from_str::<serde_json::Value>(l).ok())
        .filter(|v| v["stage"].as_u64() == Some(stage))
        .find_map(|v| v["change"].as_f64())
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PlannedRun {
    pub name: String,
    pub spec: Spec,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Plan {
    pub dir: PathBuf,
    /// Iterations of the first stage; each stage doubles them.
    pub first: u64,
    /// No stage beyond this many iterations.
    pub max: u64,
    pub save_every_minutes: Option<f64>,
    pub stage_lbr: LbrPlan,
    pub final_lbr: LbrPlan,
    pub stop: StopRule,
    pub runs: Vec<PlannedRun>,
    /// Other readings of raises under the menu's smallest ([`SmallBets`] by name) to measure
    /// the final strategy with as well, on the same deals. The stages and `done.json` use
    /// the default reading.
    #[serde(default)]
    pub final_readings: Vec<String>,
}

fn other(e: impl ToString) -> io::Error {
    io::Error::other(e.to_string())
}

fn append(path: &Path, line: &serde_json::Value) -> io::Result<()> {
    let mut f = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;
    writeln!(f, "{line}")?;
    println!("{line}");
    Ok(())
}

fn table(stack_bb: u32, plan: &LbrPlan) -> MatchConfig {
    MatchConfig {
        stack: stack_bb * 100,
        ..MatchConfig::acpc(plan.hands, plan.seed)
    }
}

/// Plays (or reads back) one LBR match and logs it, with `extra()` read after the match
/// (the blueprint's counters). Returns the deals.
#[allow(clippy::too_many_arguments)]
pub fn measured(
    strategy: &dyn Strategy,
    label: &str,
    stack_bb: u32,
    plan: &LbrPlan,
    setting: &str,
    deals_dir: &Path,
    log: &Path,
    extra: &dyn Fn() -> serde_json::Value,
) -> io::Result<Deals> {
    let (long, config) = lbr_setting(setting).ok_or_else(|| other(format!("setting {setting}")))?;
    fs::create_dir_all(deals_dir)?;
    let path = deals_dir.join(format!(
        "{label}.{setting}.s{}.h{}.deals",
        plan.seed, plan.hands
    ));
    if let Ok(deals) = Deals::load(&path) {
        return Ok(deals);
    }
    let start = Instant::now();
    let deals = lbr_match(strategy, &config, &table(stack_bb, plan));
    let seconds = start.elapsed().as_secs_f64();
    deals.save(&path)?;
    let r = deals.result();
    append(
        log,
        &json!({
            "label": label,
            "setting": setting,
            "setting_name": long,
            "stack_bb": stack_bb,
            "hands": r.hands,
            "seed": plan.seed,
            "bb_per_100": r.bb_per_100,
            "std_err": r.std_err,
            "button_bb_per_100": r.button_bb_per_100,
            "big_blind_bb_per_100": r.big_blind_bb_per_100,
            "seconds": seconds,
            "hands_per_second": r.hands as f64 / seconds,
            "deals_file": path,
            "extra": extra(),
        }),
    )?;
    Ok(deals)
}

/// Runs the whole plan.
pub fn run_plan(plan: &Plan) -> io::Result<()> {
    fs::create_dir_all(&plan.dir)?;
    fs::write(
        plan.dir.join("plan.json"),
        serde_json::to_string_pretty(plan).map_err(other)?,
    )?;
    for planned in &plan.runs {
        run_one(plan, planned)?;
        if cfr::signal::stop_requested() {
            return Ok(());
        }
    }
    Ok(())
}

fn run_one(plan: &Plan, planned: &PlannedRun) -> io::Result<()> {
    let dir = plan.dir.join(&planned.name);
    if dir.join("done.json").exists() {
        return Ok(());
    }
    let mut run = Run::open(planned.spec.clone(), &dir)?;
    let buckets: Arc<Buckets> = run.buckets.clone();
    let stack_bb = planned.spec.stack_bb;
    let deals_dir = dir.join("deals");
    let main = plan
        .stage_lbr
        .settings
        .first()
        .ok_or_else(|| other("stage_lbr needs a setting"))?
        .clone();
    let mut stage = plan.first;
    let mut previous: Option<(u64, Deals, StrategyFile)> = None;
    let (last, reason) = loop {
        let path = dir.join(format!("strategy-{stage}.bps"));
        let layout = Layout::of(run.solver.game());
        let file = if path.exists() {
            StrategyFile::load(&path)?
        } else {
            let at = cfr::Solver::iterations(&run.solver);
            if at > stage {
                return Err(other(format!(
                    "{}: the checkpoint is at {at} iterations, past stage {stage}",
                    dir.display()
                )));
            }
            let session = run.train(stage, plan.save_every_minutes)?;
            if session.stopped {
                return Ok(());
            }
            let export = run.export();
            let bytes = export.file.save(&path)?;
            let change = previous
                .as_ref()
                .map(|p| export.file.change_from(&p.2, &layout, &export.weights));
            append(
                &dir.join("stages.jsonl"),
                &json!({
                    "run": planned.name,
                    "stage": stage,
                    "session": session,
                    "train_seconds": run.train_seconds(),
                    "info_sets": export.file.header.info_sets,
                    "visited": export.file.header.visited,
                    "from_regrets": export.from_regrets,
                    "strategy_bytes": bytes,
                    "change": change,
                    "peak_resident_bytes": peak_resident_bytes(),
                }),
            )?;
            export.file
        };
        let game = build_game(&planned.spec, buckets.clone())?;
        let blueprint = Blueprint::new(game, file.clone()).map_err(other)?;
        let label = format!("{}-{}", planned.name, stage);
        let mut main_deals = None;
        for setting in &plan.stage_lbr.settings {
            blueprint.reset_counters();
            let deals = measured(
                &blueprint,
                &label,
                stack_bb,
                &plan.stage_lbr,
                setting,
                &deals_dir,
                &dir.join("lbr.jsonl"),
                &|| {
                    json!({
                        "run": planned.name,
                        "stage": stage,
                        "off_tree_share": blueprint.off_tree_share(),
                        "decisions": blueprint.decisions(),
                    })
                },
            )?;
            if *setting == main {
                main_deals = Some(deals);
            }
        }
        let now = main_deals.expect("the main setting was measured");
        let mut stop = None;
        if let Some((before, prev, _)) = &previous {
            let (diff, se) = prev.minus(&now).map_err(other)?;
            let level = prev.result().bb_per_100;
            let small = diff.abs() < plan.stop.relative * level.abs();
            let noise = diff.abs() < plan.stop.sigmas * se;
            let change = recorded_change(&dir, stage);
            let settled = match plan.stop.max_change {
                None => true,
                Some(m) => change.is_some_and(|c| c <= m),
            };
            let converged = (small || noise) && settled;
            append(
                &dir.join("progress.jsonl"),
                &json!({
                    "run": planned.name,
                    "from": before,
                    "to": stage,
                    "setting": main,
                    "before": level,
                    "after": now.result().bb_per_100,
                    "lowered_by": diff,
                    "std_err": se,
                    "lbr_flat": small || noise,
                    "change": change,
                    "settled": settled,
                    "converged": converged,
                }),
            )?;
            if converged {
                stop = Some("converged");
            }
        }
        if stop.is_none() && stage * 2 > plan.max {
            stop = Some("reached the largest stage");
        }
        if let Some(reason) = stop {
            break (stage, reason);
        }
        previous = Some((stage, now, file));
        stage *= 2;
    };

    // The final measurement: every setting of the plan on the last stage's strategy.
    let file = StrategyFile::load(&dir.join(format!("strategy-{last}.bps")))?;
    let game = build_game(&planned.spec, buckets.clone())?;
    let blueprint = Blueprint::new(game, file).map_err(other)?;
    let mut best: Option<(String, f64, f64)> = None;
    for setting in &plan.final_lbr.settings {
        blueprint.reset_counters();
        let d = measured(
            &blueprint,
            &format!("{}-final-{last}", planned.name),
            stack_bb,
            &plan.final_lbr,
            setting,
            &deals_dir,
            &dir.join("final.jsonl"),
            &|| {
                json!({
                    "run": planned.name,
                    "stage": last,
                    "off_tree_share": blueprint.off_tree_share(),
                    "decisions": blueprint.decisions(),
                })
            },
        )?;
        let r = d.result();
        if best.as_ref().is_none_or(|b| r.bb_per_100 > b.1) {
            best = Some((setting.clone(), r.bb_per_100, r.std_err));
        }
    }
    let best = best.ok_or_else(|| other("final_lbr needs a setting"))?;
    for reading in &plan.final_readings {
        let small_bets =
            SmallBets::parse(reading).ok_or_else(|| other(format!("reading {reading:?}")))?;
        let file = StrategyFile::load(&dir.join(format!("strategy-{last}.bps")))?;
        let game = build_game(&planned.spec, buckets.clone())?;
        let blueprint = Blueprint::new(game, file)
            .map_err(other)?
            .with_small_bets(small_bets);
        for setting in &plan.final_lbr.settings {
            blueprint.reset_counters();
            measured(
                &blueprint,
                &format!("{}-final-{last}-{reading}", planned.name),
                stack_bb,
                &plan.final_lbr,
                setting,
                &deals_dir,
                &dir.join("final.jsonl"),
                &|| {
                    json!({
                        "run": planned.name,
                        "stage": last,
                        "small_bets": reading,
                        "off_tree_share": blueprint.off_tree_share(),
                        "decisions": blueprint.decisions(),
                    })
                },
            )?;
        }
    }
    fs::write(
        dir.join("done.json"),
        serde_json::to_string_pretty(&json!({
            "run": planned.name,
            "stage": last,
            "reason": reason,
            "train_seconds": run.train_seconds(),
            "best_setting": best.0,
            "best_bb_per_100": best.1,
            "best_std_err": best.2,
        }))
        .map_err(other)?,
    )?;
    Ok(())
}
