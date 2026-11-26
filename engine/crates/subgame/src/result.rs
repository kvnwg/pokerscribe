//! The RESULT format (`data/SPOT_FORMAT.md`): one solved spot as JSON Lines, a header and
//! then one line per decision node in the spot tree's order.
//!
//! Written here for this solver's answers, and read for any solver's (TexasSolver's answer
//! keys, plain or gzipped), so that their exploitability and values can be worked out on
//! this crate's own tree.

use std::collections::HashMap;
use std::fmt::Write as _;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Deserialize;
use serde_json::Value;

use crate::cards::Combo;
use crate::cfr::{Solution, SolveConfig, DCFR_ALPHA, DCFR_BETA, DCFR_GAMMA};
use crate::exploit::{exploitability, Strategy};
use crate::game::Game;
use crate::gz::gunzip;
use crate::pyfmt::{json_string, round6, round_to, write_rounded6};
use crate::spot::{Ordered, IP, OOP};
use crate::tree::{Action, NodeId};

pub const RESULT_FORMAT: &str = "pokerscribe-answer-key";
pub const RESULT_VERSION: u64 = 1;
pub const SOLVER_NAME: &str = "pokerscribe-subgame";
/// Probabilities are rounded to this many decimals (`pyfmt::round6`).
pub const DIGITS: usize = 6;

/// One node line of a RESULT.
#[derive(Clone, Debug, PartialEq)]
pub struct NodeRecord {
    pub node: String,
    pub actor: String,
    pub actions: Vec<String>,
    /// (combo, one probability per action in the order of `actions`), in the file's order.
    pub strategy: Vec<(String, Vec<f64>)>,
}

#[derive(Deserialize)]
struct RawNode {
    node: String,
    actor: String,
    actions: Vec<String>,
    strategy: Ordered<Ordered<f64>>,
}

/// A RESULT file: its header and its node lines.
#[derive(Clone, Debug)]
pub struct ResultFile {
    pub header: Value,
    pub nodes: Vec<NodeRecord>,
}

impl ResultFile {
    /// Reads `<id>.jsonl` or `<id>.jsonl.gz`.
    pub fn load(path: &Path) -> Result<ResultFile, String> {
        let bytes =
            std::fs::read(path).map_err(|e| format!("can't read {}: {e}", path.display()))?;
        let bytes = if path.extension().is_some_and(|e| e == "gz") {
            gunzip(&bytes).map_err(|e| format!("{}: {e}", path.display()))?
        } else {
            bytes
        };
        let text =
            String::from_utf8(bytes).map_err(|_| format!("{}: not UTF-8", path.display()))?;
        ResultFile::parse(&text).map_err(|e| format!("{}: {e}", path.display()))
    }

    pub fn parse(text: &str) -> Result<ResultFile, String> {
        let mut lines = text.lines().filter(|l| !l.trim().is_empty());
        let header: Value = match lines.next() {
            Some(line) => serde_json::from_str(line).map_err(|e| format!("bad header: {e}"))?,
            None => return Err("empty result".to_string()),
        };
        if header["kind"] != "header" {
            return Err("the first line must be the header".to_string());
        }
        if header["format"] != RESULT_FORMAT || header["version"] != RESULT_VERSION {
            return Err(format!(
                "not a {RESULT_FORMAT} version {RESULT_VERSION} result"
            ));
        }
        let mut nodes = Vec::new();
        for (i, line) in lines.enumerate() {
            let raw: RawNode =
                serde_json::from_str(line).map_err(|e| format!("line {}: {e}", i + 2))?;
            let mut strategy = Vec::with_capacity(raw.strategy.0.len());
            for (combo, row) in raw.strategy.0 {
                let mut probs = Vec::with_capacity(raw.actions.len());
                for action in &raw.actions {
                    match row.0.iter().find(|(a, _)| a == action) {
                        Some((_, p)) => probs.push(*p),
                        None => {
                            return Err(format!(
                                "{:?} {combo}: no probability for {action}",
                                raw.node
                            ))
                        }
                    }
                }
                if row.0.len() != raw.actions.len() {
                    return Err(format!(
                        "{:?} {combo}: not one probability per action",
                        raw.node
                    ));
                }
                strategy.push((combo, probs));
            }
            nodes.push(NodeRecord {
                node: raw.node,
                actor: raw.actor,
                actions: raw.actions,
                strategy,
            });
        }
        Ok(ResultFile { header, nodes })
    }
}

/// The node lines of a strategy, in the spot tree's order: every combo of the actor that
/// can be dealt at the node (its range, less the river card on a turn spot), probabilities
/// rounded to 6 decimals.
pub fn records(game: &Game, strategy: &Strategy) -> Vec<NodeRecord> {
    let tree = &game.tree;
    let names = [0, 1].map(|p| game.combos[p].iter().map(Combo::text).collect::<Vec<_>>());
    tree.decision_order
        .iter()
        .map(|&id| {
            let node = &tree.nodes[id];
            let player = node.player().expect("a decision node");
            let alive = node.runout.map(|r| &game.runouts[r].alive[player]);
            let rows = names[player]
                .iter()
                .enumerate()
                .filter(|(i, _)| alive.is_none_or(|a| a[*i] != 0.0))
                .map(|(i, name)| {
                    (
                        name.clone(),
                        strategy
                            .row(game, id, i)
                            .iter()
                            .map(|p| round6(*p))
                            .collect(),
                    )
                })
                .collect();
            NodeRecord {
                node: node.key.clone(),
                actor: tree.actor_name(id).to_string(),
                actions: node.actions().iter().map(Action::token).collect(),
                strategy: rows,
            }
        })
        .collect()
}

/// A saved answer as a strategy on this crate's tree of the spot. A combo the answer
/// leaves out at a node gets a uniform row; the count of those rows comes back too.
/// Probabilities under 0 count as 0 and each row is made to add up to 1, as
/// `tools/answer_keys/checks.py::river_strategy` does.
pub fn strategy_from_records(
    game: &Game,
    nodes: &[NodeRecord],
) -> Result<(Strategy, usize), String> {
    let tree = &game.tree;
    let mut strategy = Strategy::uniform(game);
    let mut seen = vec![false; tree.nodes.len()];
    let mut filled = 0;
    let index: [HashMap<Combo, usize>; 2] = [0, 1].map(|p| {
        game.combos[p]
            .iter()
            .enumerate()
            .map(|(i, c)| (*c, i))
            .collect()
    });
    for record in nodes {
        let id: NodeId = tree
            .decision(&record.node)
            .ok_or_else(|| format!("node {:?} isn't in the spot's tree", record.node))?;
        if std::mem::replace(&mut seen[id], true) {
            return Err(format!("node {:?} is there twice", record.node));
        }
        let node = &tree.nodes[id];
        let tokens: Vec<String> = node.actions().iter().map(Action::token).collect();
        if tokens != record.actions || tree.actor_name(id) != record.actor {
            return Err(format!(
                "{:?}: actions {:?} by {} differ from the spot's {:?} by {}",
                record.node,
                record.actions,
                record.actor,
                tokens,
                tree.actor_name(id)
            ));
        }
        let player = node.player().expect("a decision node");
        let k = tokens.len();
        let alive = node.runout.map(|r| &game.runouts[r].alive[player]);
        let mut given = vec![false; game.n(player)];
        for (combo, row) in &record.strategy {
            let i = Combo::parse(combo)
                .ok()
                .and_then(|c| index[player].get(&c).copied())
                .ok_or_else(|| {
                    format!(
                        "{:?}: {combo} isn't in the {} range",
                        record.node, record.actor
                    )
                })?;
            if row.len() != k {
                return Err(format!(
                    "{:?} {combo}: not one probability per action",
                    record.node
                ));
            }
            let total: f64 = row.iter().map(|p| p.max(0.0)).sum();
            let out = &mut strategy.probs[id][i * k..(i + 1) * k];
            if total > 0.0 {
                for (o, p) in out.iter_mut().zip(row) {
                    *o = p.max(0.0) / total;
                }
            }
            given[i] = true;
        }
        filled += (0..game.n(player))
            .filter(|&i| !given[i] && alive.is_none_or(|a| a[i] != 0.0))
            .count();
    }
    if let Some(&missing) = tree.decision_order.iter().find(|&&id| !seen[id]) {
        return Err(format!("no strategy at node {:?}", tree.nodes[missing].key));
    }
    Ok((strategy, filled))
}

/// The numbers of a header's "checks" block: an answer measured by this crate's exact best
/// response (`exploit.rs`), as `tools/answer_keys/checks.py::river_checks` measures a river
/// answer with `app/solver`'s. The two agree on every river answer key (the tests).
#[derive(Clone, Debug, PartialEq)]
pub struct Checks {
    /// Exploitability as a share of the pot.
    pub exploitability_pot: f64,
    /// Combos the answer leaves out at some node, given a uniform row.
    pub filled_rows: usize,
    /// Chips a hand each player wins when both follow the answer. They add up to the pot.
    pub values: [f64; 2],
    /// `[low, high]`: the spot's true value for OOP lies between pot - (IP's best response)
    /// and OOP's best response. The width is twice the exploitability in chips.
    pub oop_value_bounds: [f64; 2],
}

/// Measures an answer as it is written: the node lines are read back
/// ([`strategy_from_records`]), so the rounding to six decimals is part of what is checked.
pub fn checks(game: &Game, nodes: &[NodeRecord], parallel: bool) -> Result<Checks, String> {
    let (strategy, filled_rows) = strategy_from_records(game, nodes)?;
    let e = exploitability(game, &strategy, parallel);
    Ok(Checks {
        exploitability_pot: e.pot_share(),
        filled_rows,
        values: e.value,
        oop_value_bounds: [e.pot - e.best_response[IP], e.best_response[OOP]],
    })
}

/// What the header says about one solve.
pub struct SolveInfo<'a> {
    pub config: &'a SolveConfig,
    pub solution: &'a Solution,
    /// The answer measured as written ([`checks`]).
    pub checks: &'a Checks,
    /// The spot's expected checks that fail (`expected::check_expected`).
    pub expected_failures: &'a [String],
    /// `2026-11-26T12:00:00Z`; `None` for the time now.
    pub created: Option<String>,
}

/// The RESULT of a solve as JSON Lines text. `nodes` are the strategy's node lines
/// ([`records`]).
pub fn encode(game: &Game, info: &SolveInfo, nodes: &[NodeRecord]) -> String {
    let numbers: usize = nodes
        .iter()
        .map(|r| r.strategy.len() * r.actions.len())
        .sum();
    let mut out = String::with_capacity(4096 + 16 * numbers);
    out.push_str(&header(game, info, nodes.len()));
    out.push('\n');
    for record in nodes {
        write_node(record, &mut out);
        out.push('\n');
    }
    out
}

fn header(game: &Game, info: &SolveInfo, n_nodes: usize) -> String {
    let (config, solution, checks) = (info.config, info.solution, info.checks);
    let trace: Vec<Value> = solution
        .trace
        .iter()
        .map(|(i, pct)| serde_json::json!([i, round_to(*pct, 6)]))
        .collect();
    let created = info.created.clone().unwrap_or_else(now);
    let header = serde_json::json!({
        "format": RESULT_FORMAT,
        "version": RESULT_VERSION,
        "kind": "header",
        "label_source": "solver",
        "spot_id": game.spot.id,
        "spot_sha256": game.spot.sha256,
        "street": game.spot.street.name(),
        "solver": {
            "name": SOLVER_NAME,
            "version": env!("CARGO_PKG_VERSION"),
            "settings": {
                "method": "dcfr",
                "alpha": DCFR_ALPHA,
                "beta": DCFR_BETA,
                "gamma": DCFR_GAMMA,
                "accuracy_pct_of_pot": round_to(100.0 * config.target_exploitability, 6),
                "max_iterations": config.max_iterations,
                "time_ms": config.time_ms,
                "threads": config.threads,
            },
            "iterations": solution.iterations,
            "elapsed_s": round_to(solution.elapsed_ms / 1000.0, 6),
            "exploitability_pot": round_to(solution.exploitability, 8),
            "exploitability_trace": trace,
            "converged": solution.converged,
            "notes": [],
        },
        "checks": {
            "exploitability_pot": round_to(checks.exploitability_pot, 8),
            "filled_rows": checks.filled_rows,
            "values": {
                "oop": round_to(checks.values[OOP], 6),
                "ip": round_to(checks.values[IP], 6),
            },
            "oop_value_bounds": [
                round_to(checks.oop_value_bounds[0], 6),
                round_to(checks.oop_value_bounds[1], 6),
            ],
            "expected_failures": info.expected_failures,
        },
        "nodes": n_nodes,
        "created": created,
    });
    // Keys in the order of the format's example, whatever order the JSON map keeps.
    let mut out = String::new();
    write_ordered(
        &header,
        &[
            "format",
            "version",
            "kind",
            "label_source",
            "spot_id",
            "spot_sha256",
            "street",
            "solver",
            "checks",
            "nodes",
            "created",
        ],
        &mut out,
    );
    out
}

/// Writes an object with the listed keys first and in that order (other keys after, and
/// nested objects, in the map's own order).
fn write_ordered(value: &Value, first: &[&str], out: &mut String) {
    let Some(map) = value.as_object() else {
        out.push_str(&value.to_string());
        return;
    };
    out.push('{');
    let mut wrote = false;
    let keys = first
        .iter()
        .copied()
        .filter(|k| map.contains_key(*k))
        .chain(
            map.keys()
                .map(String::as_str)
                .filter(|k| !first.contains(k)),
        );
    for key in keys {
        if wrote {
            out.push(',');
        }
        wrote = true;
        json_string(key, out);
        out.push(':');
        match key {
            "solver" => write_ordered(
                &map[key],
                &[
                    "name",
                    "version",
                    "settings",
                    "iterations",
                    "elapsed_s",
                    "exploitability_pot",
                    "exploitability_trace",
                    "converged",
                    "notes",
                ],
                out,
            ),
            "checks" => write_ordered(
                &map[key],
                &[
                    "exploitability_pot",
                    "filled_rows",
                    "values",
                    "oop_value_bounds",
                    "expected_failures",
                ],
                out,
            ),
            "values" => write_ordered(&map[key], &["oop", "ip"], out),
            _ => out.push_str(&map[key].to_string()),
        }
    }
    out.push('}');
}

fn write_node(record: &NodeRecord, out: &mut String) {
    out.push_str("{\"kind\":\"node\",\"node\":");
    json_string(&record.node, out);
    out.push_str(",\"actor\":");
    json_string(&record.actor, out);
    out.push_str(",\"actions\":[");
    for (i, action) in record.actions.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        json_string(action, out);
    }
    out.push_str("],\"strategy\":{");
    for (i, (combo, row)) in record.strategy.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        json_string(combo, out);
        out.push_str(":{");
        for (a, (action, p)) in record.actions.iter().zip(row).enumerate() {
            if a > 0 {
                out.push(',');
            }
            json_string(action, out);
            out.push(':');
            write_rounded6(*p, out);
        }
        out.push('}');
    }
    out.push_str("}}");
}

/// The time now as `2026-11-26T12:00:00Z` (UTC).
pub fn now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    timestamp(secs)
}

fn timestamp(secs: u64) -> String {
    let (days, rest) = (secs / 86_400, secs % 86_400);
    // Days since 1970-01-01 to a date (Howard Hinnant's civil_from_days).
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    let mut out = String::new();
    let _ = write!(
        out,
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    );
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timestamps_are_utc_dates() {
        assert_eq!(timestamp(0), "1970-01-01T00:00:00Z");
        assert_eq!(timestamp(951_782_400), "2000-02-29T00:00:00Z");
        assert_eq!(timestamp(1_795_718_489), "2026-11-26T18:41:29Z");
    }

    #[test]
    fn a_result_line_is_read_in_the_nodes_action_order() {
        let text = concat!(
            r#"{"format":"pokerscribe-answer-key","version":1,"kind":"header","spot_id":"r01"}"#,
            "\n",
            r#"{"kind":"node","node":"x b33","actor":"oop","actions":["f","c","r116"],"#,
            r#""strategy":{"TsTh":{"c":0.75,"f":0.25,"r116":0.0},"9h9d":{"f":1.0,"c":0.0,"r116":0.0}}}"#,
            "\n"
        );
        let file = ResultFile::parse(text).unwrap();
        assert_eq!(file.header["spot_id"], "r01");
        assert_eq!(file.nodes.len(), 1);
        assert_eq!(file.nodes[0].actions, ["f", "c", "r116"]);
        assert_eq!(
            file.nodes[0].strategy[0],
            ("TsTh".to_string(), vec![0.25, 0.75, 0.0])
        );
        assert_eq!(file.nodes[0].strategy[1].0, "9h9d");
        assert!(ResultFile::parse("").is_err());
        assert!(ResultFile::parse(r#"{"kind":"node"}"#).is_err());
        let missing = text.replace(r#","r116":0.0}}}"#, "}}}");
        assert!(ResultFile::parse(&missing).unwrap_err().contains("r116"));
    }
}
