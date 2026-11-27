//! The strategy file: a trained blueprint's average strategy, compact and dense.
//!
//! Every information set of the abstract game is a decision point of the betting tree and
//! a bucket of its street, so the strategy is stored as one block per decision point,
//! `buckets x actions` probabilities each, in decision point order. No keys are stored:
//! the place of a probability says which information set and action it is for.
//!
//! | Bytes | What |
//! | --- | --- |
//! | 8 | The text `PSBLUEP` and a newline |
//! | 4 | Format version, now 1 |
//! | 4 | Length `H` of the header |
//! | `H` | The header as JSON ([`Header`]) |
//! | slots x 2 | Each probability times 65,535, rounded, as a little-endian `u16`. An information set's numbers sum to exactly 65,535, or are all 0 when training never reached it (it is then played uniformly) |
//! | 8 | XXH64 (seed 0) of every byte before it |

use std::fs;
use std::io::{self, Write};
use std::path::Path;

use abstract_game::{AbstractGame, BettingTree, Bucketer};
use abstraction::xxh64::Xxh64;
use cfr::{Game, Mccfr};
use serde::{Deserialize, Serialize};

use crate::buckets::TablesInfo;
use crate::spec::{describe_menu, Spec};

pub const MAGIC: &[u8; 8] = b"PSBLUEP\n";
pub const FORMAT_VERSION: u32 = 1;
/// What an information set's numbers sum to.
pub const ONE: u32 = u16::MAX as u32;

/// The game a strategy is for, as the header records it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct GameInfo {
    pub stack: u32,
    pub small_blind: u32,
    pub big_blind: u32,
    /// The menu in words ([`describe_menu`]).
    pub menu: String,
    pub decision_points: u64,
    pub actions: u64,
    /// Buckets on each street (0 for streets nobody acts on).
    pub buckets: [u64; 4],
}

impl GameInfo {
    pub fn of<B: Bucketer>(game: &AbstractGame<B>) -> GameInfo {
        let c = game.config();
        GameInfo {
            stack: c.stack,
            small_blind: c.small_blind,
            big_blind: c.big_blind,
            menu: describe_menu(&c.menus),
            decision_points: game.tree().len() as u64,
            actions: game.tree().num_actions() as u64,
            buckets: game.buckets(),
        }
    }
}

/// The JSON header of a strategy file.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Header {
    pub format: u32,
    /// The version of this crate that wrote the file.
    pub built_by: String,
    pub game: GameInfo,
    /// The run's settings, when it had a spec.
    pub spec: Option<Spec>,
    /// The bucket tables, when they came from the abstraction crate.
    pub tables: Option<TablesInfo>,
    /// Information sets in the game (decision points times their street's buckets).
    pub info_sets: u64,
    /// Information sets with a strategy: the rest were never reached in training.
    pub visited: u64,
    /// Probabilities stored.
    pub slots: u64,
    /// Training iterations behind the strategy.
    pub iterations: u64,
    /// Seconds of training behind it, over every session of the run.
    pub train_seconds: f64,
}

/// Where each decision point's block starts.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Layout {
    offsets: Vec<u64>,
    actions: Vec<u16>,
    streets: Vec<u8>,
    buckets: [u64; 4],
    info_sets: u64,
    slots: u64,
}

impl Layout {
    /// The layout for a tree and its buckets per street.
    pub fn new(tree: &BettingTree, buckets: [u64; 4]) -> Layout {
        let mut offsets = Vec::with_capacity(tree.len());
        let mut actions = Vec::with_capacity(tree.len());
        let mut streets = Vec::with_capacity(tree.len());
        let (mut slots, mut info_sets) = (0u64, 0u64);
        for id in 0..tree.len() as u32 {
            let n = tree.edges(id).len() as u64;
            let street = tree.node(id).street.index();
            let b = buckets[street];
            offsets.push(slots);
            actions.push(n as u16);
            streets.push(street as u8);
            slots += b * n;
            info_sets += b;
        }
        Layout {
            offsets,
            actions,
            streets,
            buckets,
            info_sets,
            slots,
        }
    }

    pub fn of<B: Bucketer>(game: &AbstractGame<B>) -> Layout {
        Layout::new(game.tree(), game.buckets())
    }

    /// The first slot of the information set at decision point `node` in `bucket`.
    #[inline]
    pub fn start(&self, node: u32, bucket: u64) -> usize {
        (self.offsets[node as usize] + bucket * self.actions[node as usize] as u64) as usize
    }

    /// Actions at decision point `node`.
    #[inline]
    pub fn actions(&self, node: u32) -> usize {
        self.actions[node as usize] as usize
    }

    pub fn buckets(&self) -> [u64; 4] {
        self.buckets
    }

    /// Decision points.
    pub fn len(&self) -> usize {
        self.offsets.len()
    }

    pub fn is_empty(&self) -> bool {
        self.offsets.is_empty()
    }

    /// Buckets at decision point `node`: its street's.
    #[inline]
    pub fn buckets_at(&self, node: u32) -> u64 {
        self.buckets[self.streets[node as usize] as usize]
    }

    pub fn info_sets(&self) -> u64 {
        self.info_sets
    }

    pub fn slots(&self) -> u64 {
        self.slots
    }
}

/// A strategy in memory: the header and the probabilities.
#[derive(Clone, Debug, PartialEq)]
pub struct StrategyFile {
    pub header: Header,
    pub probs: Vec<u16>,
}

/// Rounds weights to numbers that sum to exactly [`ONE`]. All zeros stay zeros.
pub fn quantize(weights: &[f64], out: &mut [u16]) {
    let sum: f64 = weights.iter().filter(|w| **w > 0.0).sum();
    if sum <= 0.0 || !sum.is_finite() {
        out.fill(0);
        return;
    }
    let mut total = 0i64;
    let mut best = 0;
    for (i, (o, &w)) in out.iter_mut().zip(weights).enumerate() {
        let q = if w > 0.0 {
            (w / sum * ONE as f64).round() as i64
        } else {
            0
        };
        *o = q as u16;
        total += q;
        if w > weights[best] {
            best = i;
        }
    }
    // Rounding can miss by a few units: the largest absorbs it.
    let fixed = out[best] as i64 + (ONE as i64 - total);
    out[best] = fixed.clamp(0, ONE as i64) as u16;
}

/// One information set's probabilities. Unreached ones are uniform.
#[inline]
pub fn decode(stored: &[u16], out: &mut [f64]) {
    let sum: u32 = stored.iter().map(|&q| q as u32).sum();
    if sum == 0 {
        out.fill(1.0 / out.len() as f64);
    } else {
        for (o, &q) in out.iter_mut().zip(stored) {
            *o = q as f64 / sum as f64;
        }
    }
}

/// What came out of a solver besides the strategy: each information set's visit weight
/// (its strategy sums added up), for measuring how much the strategy moved.
pub struct Export {
    pub file: StrategyFile,
    /// One weight per information set in layout order (decision point, then bucket).
    pub weights: Vec<f64>,
    /// Information sets reached only while their own player was traversing: they have
    /// no average strategy, so the current one (regret matching) was stored.
    pub from_regrets: u64,
}

impl StrategyFile {
    /// The average strategy of a trained solver. Information sets that have regrets but
    /// no strategy sums get their current strategy (regret matching) instead.
    ///
    /// The solver is read one information set at a time (`Mccfr::for_each_set`), so this
    /// needs the file and the weights on top of the solver's own memory, nothing more: for
    /// the Phase 6 game, 1.3 GB rather than the 10 GB or so that copying every regret and
    /// strategy sum first would take.
    pub fn from_solver<B: Bucketer + Sync>(
        solver: &Mccfr<AbstractGame<B>>,
        spec: Option<Spec>,
        tables: Option<TablesInfo>,
        train_seconds: f64,
    ) -> Export
    where
        AbstractGame<B>: Game,
    {
        let game = solver.game();
        let layout = Layout::of(game);
        let nodes = game.tree().len() as u64;
        let mut probs = vec![0u16; layout.slots as usize];
        let mut weights = vec![0.0f64; layout.info_sets as usize];
        let mut weight_index = Vec::with_capacity(nodes as usize);
        let mut at = 0u64;
        for id in 0..nodes as u32 {
            weight_index.push(at);
            at += layout.buckets[game.tree().node(id).street.index()];
        }
        let (mut visited, mut from_regrets) = (0u64, 0u64);
        let mut positive = Vec::new();
        solver.for_each_set(|key, regrets, sums| {
            let node = (key % nodes) as u32;
            let bucket = key / nodes;
            let street = game.tree().node(node).street;
            assert!(
                bucket < layout.buckets[street.index()],
                "bucket {bucket} on the {street:?} is outside the bucketer's count: the dense \
                 layout needs buckets numbered from 0"
            );
            assert_eq!(sums.len(), layout.actions(node));
            let start = layout.start(node, bucket);
            let out = &mut probs[start..start + sums.len()];
            let weight: f64 = sums.iter().sum();
            weights[(weight_index[node as usize] + bucket) as usize] = weight;
            if weight > 0.0 {
                quantize(sums, out);
            } else {
                positive.clear();
                positive.extend(regrets.iter().map(|&r| r.max(0.0)));
                if positive.iter().sum::<f64>() > 0.0 {
                    quantize(&positive, out);
                    from_regrets += 1;
                }
            }
            if out.iter().any(|&q| q > 0) {
                visited += 1;
            }
        });
        let header = Header {
            format: FORMAT_VERSION,
            built_by: format!("blueprint {}", env!("CARGO_PKG_VERSION")),
            game: GameInfo::of(game),
            spec,
            tables,
            info_sets: layout.info_sets,
            visited,
            slots: layout.slots,
            iterations: cfr::Solver::iterations(solver),
            train_seconds,
        };
        Export {
            file: StrategyFile { header, probs },
            weights,
            from_regrets,
        }
    }

    /// The file's bytes, checksum included.
    pub fn to_bytes(&self) -> Vec<u8> {
        let header = serde_json::to_vec(&self.header).expect("the header is valid JSON");
        let mut out = Vec::with_capacity(24 + header.len() + 2 * self.probs.len());
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&FORMAT_VERSION.to_le_bytes());
        out.extend_from_slice(&(header.len() as u32).to_le_bytes());
        out.extend_from_slice(&header);
        for &q in &self.probs {
            out.extend_from_slice(&q.to_le_bytes());
        }
        let mut hash = Xxh64::new(0);
        hash.update(&out);
        out.extend_from_slice(&hash.finish().to_le_bytes());
        out
    }

    /// Writes the file under a temporary name, then renames it: a stopped write never
    /// leaves half a file. Returns the size in bytes.
    pub fn save(&self, path: &Path) -> io::Result<u64> {
        let bytes = self.to_bytes();
        let tmp = path.with_extension("tmp");
        {
            let mut f = fs::File::create(&tmp)?;
            f.write_all(&bytes)?;
            f.sync_all()?;
        }
        fs::rename(&tmp, path)?;
        Ok(bytes.len() as u64)
    }

    /// Reads a file and checks it whole: magic, version, length, checksum.
    pub fn load(path: &Path) -> io::Result<StrategyFile> {
        StrategyFile::from_bytes(&fs::read(path)?)
    }

    pub fn from_bytes(bytes: &[u8]) -> io::Result<StrategyFile> {
        let bad = |m: String| io::Error::new(io::ErrorKind::InvalidData, m);
        if bytes.len() < 24 || &bytes[..8] != MAGIC {
            return Err(bad("not a blueprint strategy file".into()));
        }
        let version = u32::from_le_bytes(bytes[8..12].try_into().unwrap());
        if version != FORMAT_VERSION {
            return Err(bad(format!(
                "strategy file format {version}, this code reads {FORMAT_VERSION}"
            )));
        }
        let (body, tail) = bytes.split_at(bytes.len() - 8);
        let mut hash = Xxh64::new(0);
        hash.update(body);
        if hash.finish() != u64::from_le_bytes(tail.try_into().unwrap()) {
            return Err(bad(
                "the strategy file's checksum doesn't match: it is damaged".into(),
            ));
        }
        let h = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
        if 16 + h > body.len() {
            return Err(bad("the header runs past the end of the file".into()));
        }
        let header: Header =
            serde_json::from_slice(&bytes[16..16 + h]).map_err(|e| bad(e.to_string()))?;
        let data = &body[16 + h..];
        if data.len() as u64 != 2 * header.slots {
            return Err(bad(format!(
                "{} bytes of probabilities, the header says {} slots",
                data.len(),
                header.slots
            )));
        }
        let probs = data
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes([c[0], c[1]]))
            .collect();
        Ok(StrategyFile { header, probs })
    }

    /// Checks the strategy is for `game`: same chips, same betting tree, same buckets.
    pub fn check_game<B: Bucketer>(&self, game: &AbstractGame<B>) -> Result<Layout, String> {
        let want = GameInfo::of(game);
        if self.header.game != want {
            return Err(format!(
                "the strategy is for another game: file {:?}, game {:?}",
                self.header.game, want
            ));
        }
        let layout = Layout::of(game);
        if layout.slots != self.probs.len() as u64 {
            return Err(format!(
                "{} probabilities for a game with {} slots",
                self.probs.len(),
                layout.slots
            ));
        }
        Ok(layout)
    }

    /// How much the strategy moved from `before`, the same game's earlier strategy: the
    /// total variation distance (half the sum of the differences, 0 to 1) at each
    /// information set, averaged with `weights` (from [`Export`]). Unreached information
    /// sets count as uniform on both sides.
    pub fn change_from(&self, before: &StrategyFile, layout: &Layout, weights: &[f64]) -> f64 {
        assert_eq!(self.probs.len(), before.probs.len(), "the same game");
        let (mut moved, mut total) = (0.0, 0.0);
        let mut a = Vec::new();
        let mut b = Vec::new();
        let mut w = 0;
        for node in 0..layout.offsets.len() as u32 {
            let n = layout.actions(node);
            let buckets = layout.buckets_at(node);
            a.resize(n, 0.0);
            b.resize(n, 0.0);
            for bucket in 0..buckets {
                let s = layout.start(node, bucket);
                let weight = weights[w];
                w += 1;
                if weight <= 0.0 {
                    continue;
                }
                decode(&self.probs[s..s + n], &mut a);
                decode(&before.probs[s..s + n], &mut b);
                let tv: f64 = a.iter().zip(&b).map(|(x, y)| (x - y).abs()).sum::<f64>() / 2.0;
                moved += weight * tv;
                total += weight;
            }
        }
        if total > 0.0 {
            moved / total
        } else {
            0.0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quantized_numbers_sum_to_one() {
        let mut out = [0u16; 4];
        for w in [
            vec![1.0, 1.0, 1.0, 0.0],
            vec![0.1, 0.2, 0.3, 0.4],
            vec![1e-9, 5.0, 0.0, 1e-3],
            vec![2.0, 2.0, 2.0, 2.0],
        ] {
            quantize(&w, &mut out);
            assert_eq!(out.iter().map(|&q| q as u32).sum::<u32>(), ONE, "{w:?}");
        }
        quantize(&[0.0, 0.0, 0.0, 0.0], &mut out);
        assert_eq!(out, [0; 4]);
        let mut probs = [0.0; 4];
        decode(&out, &mut probs);
        assert_eq!(probs, [0.25; 4]);
        quantize(&[0.3, 0.7, 0.0, 0.0], &mut out);
        decode(&out, &mut probs);
        assert!((probs[0] - 0.3).abs() < 1e-4 && (probs[1] - 0.7).abs() < 1e-4);
    }
}
