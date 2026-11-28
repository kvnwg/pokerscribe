//! Leaf values for the depth-limited flop: what the rest of the hand is worth when the flop
//! ends with chips behind, for each pair of flop buckets and each pair of continuation
//! strategies.
//!
//! A leaf of the flop is the start of the turn. The blueprint reads it as one of its
//! decision points (an abstract turn-start node `d`). From there the hand is played out in
//! the abstract game: both players follow the blueprint, or one of them follows a biased
//! version of it (Modicum's continuation strategies, Brown, Sandholm and Amos 2018): at
//! every decision of the rest of the hand the probability of folding, of checking or
//! calling, or of betting or raising (all sizes together) is multiplied by [`BIAS`] and the
//! strategy renormalized. Seven lanes:
//!
//! - 0: both play the blueprint;
//! - 1, 2, 3: the small blind (in position) is biased toward folding, calling, raising;
//! - 4, 5, 6: the big blind (out of position) is biased the same three ways.
//!
//! The value of a lane is the big blind's share of the pot at `d`: `(net + C) / P`, with
//! `net` what the big blind wins over the whole hand, `C` what it had put in at `d` and `P`
//! the pot at `d`. A share scales with the pot, so a real flop whose pot differs from the
//! abstract line's (an off-menu bet) uses the same table. It can be below 0 or above 1: the
//! later bets are in it.
//!
//! The tables are Monte Carlo averages over random deals (two hands, a flop, a turn and a
//! river), by the two hands' flop buckets (the blueprint's own 200 flop buckets): for each
//! deal the abstract subtree under every `d` is walked exactly, every action of both
//! players weighted by its probability, with the turn and river buckets of the deal. A cell
//! with few deals is pulled toward an additive fit of its row and column (a pseudo-count
//! of [`PRIOR_DEALS`] deals). The deal stream is fixed by the seed, and every cell adds its
//! deals in the stream's order, so a build gives the same tables on any number of threads.
//!
//! A build can be split into parts, each a run of the turn starts ([`build_part`]): a part
//! walks every deal for its nodes only, so its memory is the part's, and the parts put
//! together are the whole build's tables bit for bit (`crate::leaf_job` runs them as a
//! resumable job).

use std::collections::HashMap;
use std::io::{self, Read, Write};
use std::path::Path;

use abstract_game::{Bucketer, Next};
use nlhe::{Action, Card, Config, State, Street};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};

use crate::cards::{eval_card, mix};

/// Lanes in a table: the blueprint, then three biased lanes for each player.
pub const TABLE_LANES: usize = 7;
/// How much a biased lane multiplies the favoured kind of action by.
pub const BIAS: f64 = 5.0;
/// Pseudo-count of the prior for sparse cells.
pub const PRIOR_DEALS: f64 = 3.0;

const MAGIC: &[u8; 8] = b"PSLEAF1\n";
const MAX_EDGES: usize = 16;

/// The lanes a chooser picks among in the flop solver, in the solver's lane order
/// (blueprint, fold-, call-, raise-biased): the big blind's lanes or the small blind's.
pub fn chooser_lanes(chooser_is_big_blind: bool) -> [usize; 4] {
    if chooser_is_big_blind {
        [0, 4, 5, 6]
    } else {
        [0, 1, 2, 3]
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Header {
    /// Abstract turn-start decision points, in table order.
    pub nodes: Vec<u32>,
    /// Flop buckets (both players use the same table).
    pub buckets: usize,
    pub deals: u64,
    pub seed: u64,
    pub bias: f64,
    pub prior_deals: f64,
    /// The strategy file the tables were built from, and a hash of its bytes.
    pub strategy: String,
    pub strategy_hash: String,
    /// Deals per cell: the fewest, the median and the most.
    pub cell_deals: [u64; 3],
    pub seconds: f64,
}

/// The leaf tables of one blueprint.
pub struct LeafTables {
    pub header: Header,
    index: HashMap<u32, usize>,
    /// `q[((node * TABLE_LANES + lane) * buckets + bb) * buckets + sb]`.
    q: Vec<f32>,
}

impl LeafTables {
    /// The big blind's pot share at abstract node `node` in `lane`, for big blind flop
    /// bucket `bb` against small blind flop bucket `sb`; `None` when the node has no table.
    pub fn table(&self, node: u32, lane: usize) -> Option<&[f32]> {
        let &i = self.index.get(&node)?;
        let b = self.header.buckets;
        let start = (i * TABLE_LANES + lane) * b * b;
        Some(&self.q[start..start + b * b])
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        let mut f = io::BufWriter::new(std::fs::File::create(path)?);
        write_header(&mut f, &self.header)?;
        write_f32s(&mut f, &self.q)?;
        f.flush()
    }

    /// The tables as one slice, `[node][lane][big blind bucket][small blind bucket]`.
    pub fn values(&self) -> &[f32] {
        &self.q
    }

    /// The header of a table file, without its values.
    pub fn read_header(path: &Path) -> io::Result<Header> {
        let mut f = io::BufReader::new(std::fs::File::open(path)?);
        read_header_from(&mut f)
    }

    pub fn load(path: &Path) -> io::Result<LeafTables> {
        let mut f = io::BufReader::new(std::fs::File::open(path)?);
        let header = read_header_from(&mut f)?;
        let b = header.buckets;
        let n = header.nodes.len() * TABLE_LANES * b * b;
        // Read in slices straight into the table: a 200bb table is 9.7 GB, so a second copy
        // of it as bytes would double the memory a load needs.
        let mut q = Vec::with_capacity(n);
        let mut buf = vec![0u8; (16 << 20).min(n * 4)];
        let mut left = n * 4;
        while left > 0 {
            let k = left.min(buf.len());
            f.read_exact(&mut buf[..k])?;
            q.extend(
                buf[..k]
                    .chunks_exact(4)
                    .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]])),
            );
            left -= k;
        }
        if f.read(&mut [0u8; 1])? != 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "the file is longer than its header says",
            ));
        }
        let index = header
            .nodes
            .iter()
            .enumerate()
            .map(|(i, &n)| (n, i))
            .collect();
        Ok(LeafTables { header, index, q })
    }
}

fn read_header_from(f: &mut impl Read) -> io::Result<Header> {
    let bad = |m: &str| io::Error::new(io::ErrorKind::InvalidData, m.to_string());
    let mut magic = [0u8; 8];
    f.read_exact(&mut magic)?;
    if &magic != MAGIC {
        return Err(bad("not a leaf table file"));
    }
    let mut len = [0u8; 8];
    f.read_exact(&mut len)?;
    let len = u64::from_le_bytes(len);
    if len > 1 << 30 {
        return Err(bad("a leaf table header too long"));
    }
    let mut header = vec![0u8; len as usize];
    f.read_exact(&mut header)?;
    Ok(serde_json::from_slice(&header)?)
}

/// The start of a table file: the magic and the header (the values follow it).
pub fn write_header(f: &mut impl Write, header: &Header) -> io::Result<()> {
    f.write_all(MAGIC)?;
    let header = serde_json::to_vec(header)?;
    f.write_all(&(header.len() as u64).to_le_bytes())?;
    f.write_all(&header)
}

/// Values as little-endian f32, the table file's format.
pub fn write_f32s(f: &mut impl Write, values: &[f32]) -> io::Result<()> {
    let mut buf = Vec::with_capacity(1 << 20);
    for chunk in values.chunks(1 << 18) {
        buf.clear();
        for x in chunk {
            buf.extend_from_slice(&x.to_le_bytes());
        }
        f.write_all(&buf)?;
    }
    Ok(())
}

/// FNV-1a over bytes, continuing from `h` (start from [`FNV_START`]).
pub fn fnv(mut h: u64, bytes: &[u8]) -> u64 {
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    h
}

pub const FNV_START: u64 = 0xcbf2_9ce4_8422_2325;

/// FNV-1a over a file's bytes, as hex: ties a table file to its strategy file. Read in
/// slices, so hashing a 0.5 GB strategy file doesn't hold it all in memory.
pub fn file_hash(path: &Path) -> io::Result<String> {
    let mut f = std::fs::File::open(path)?;
    let mut buf = vec![0u8; 1 << 20];
    let mut h = FNV_START;
    loop {
        let k = f.read(&mut buf)?;
        if k == 0 {
            break;
        }
        h = fnv(h, &buf[..k]);
    }
    Ok(format!("{h:016x}"))
}

/// The abstract decision points where a turn starts (reached from the flop with chips
/// behind), in id order.
pub fn turn_starts<B>(bp: &blueprint::play::Blueprint<B>) -> Vec<u32>
where
    B: Bucketer,
{
    turn_starts_in(bp.game().tree())
}

/// The turn starts of any abstract betting tree (for sizing the tables of a bigger game).
pub fn turn_starts_in(tree: &abstract_game::tree::BettingTree) -> Vec<u32> {
    let mut out = Vec::new();
    for id in 0..tree.len() as u32 {
        if tree.node(id).street != Street::Flop {
            continue;
        }
        for e in tree.edges(id) {
            if let Next::Decision(n) = e.next() {
                if tree.node(n).street == Street::Turn {
                    out.push(n);
                }
            }
        }
    }
    out.sort_unstable();
    out.dedup();
    out
}

/// One random deal and its buckets: `[flop, turn, river][small blind, big blind]`, and the
/// showdown result as an abstract `Payoff` row (0 small blind wins, 1 tie, 2 big blind).
#[derive(Clone, Copy, Debug)]
struct Deal {
    buckets: [[u64; 2]; 3],
    result: usize,
}

fn deal<B: Bucketer>(bucketer: &B, seed: u64, index: u64) -> Deal {
    let mut cards: [Card; 52] = std::array::from_fn(|i| i as Card);
    let mut h = mix(seed ^ mix(index.wrapping_add(0x9E37_79B9_7F4A_7C15)));
    for i in 0..9 {
        h = mix(h.wrapping_add(i as u64));
        let j = i + (h % (52 - i) as u64) as usize;
        cards.swap(i, j);
    }
    let sb = [cards[0], cards[1]];
    let bb = [cards[2], cards[3]];
    let board = &cards[4..9];
    let mut buckets = [[0u64; 2]; 3];
    for (s, len) in [3usize, 4, 5].into_iter().enumerate() {
        buckets[s] = [
            bucketer.bucket(sb, &board[..len]),
            bucketer.bucket(bb, &board[..len]),
        ];
    }
    let full = eval::Hand::from_cards(&board.iter().map(|&c| eval_card(c)).collect::<Vec<_>>());
    let v = |h: [Card; 2]| {
        full.add(eval_card(h[0]))
            .add(eval_card(h[1]))
            .eval7()
            .value()
    };
    let (s, b) = (v(sb), v(bb));
    let result = match s.cmp(&b) {
        std::cmp::Ordering::Greater => 0,
        std::cmp::Ordering::Equal => 1,
        std::cmp::Ordering::Less => 2,
    };
    Deal { buckets, result }
}

/// The kind an action is biased as: 0 fold, 1 check or call, 2 bet or raise.
fn kind(a: Action) -> usize {
    match a {
        Action::Fold => 0,
        Action::Check | Action::Call => 1,
        Action::RaiseTo(_) => 2,
    }
}

/// The bias a lane puts on `player` (0 small blind, 1 big blind): the kind favoured, or
/// `None` for the blueprint.
fn lane_bias(lane: usize, player: usize) -> Option<usize> {
    match (lane, player) {
        (1..=3, 0) => Some(lane - 1),
        (4..=6, 1) => Some(lane - 4),
        _ => None,
    }
}

/// `probs` biased toward `kind` (multiplied by [`BIAS`], renormalized).
pub fn biased(probs: &[f64], kinds: &[usize], favoured: usize, out: &mut [f64]) {
    let mut total = 0.0;
    for ((o, &p), &k) in out.iter_mut().zip(probs).zip(kinds) {
        *o = if k == favoured { p * BIAS } else { p };
        total += *o;
    }
    if total > 0.0 {
        out.iter_mut().for_each(|o| *o /= total);
    }
}

struct Walker<'a, B> {
    bp: &'a blueprint::play::Blueprint<B>,
}

impl<B: Bucketer> Walker<'_, B> {
    /// The big blind's net chips over the hand, in each lane, from decision point `node`.
    fn walk(&self, node: u32, d: &Deal, out: &mut [f64; TABLE_LANES]) {
        let tree = self.bp.game().tree();
        let n = tree.node(node);
        let player = n.player as usize;
        let street = match n.street {
            Street::Turn => 1,
            Street::River => 2,
            s => panic!("a leaf subtree has no {s:?} decisions"),
        };
        let edges = tree.edges(node);
        let k = edges.len();
        assert!(k <= MAX_EDGES, "too many actions at a decision point");
        let mut probs = [0f64; MAX_EDGES];
        self.bp
            .strategy_into(node, d.buckets[street][player], &mut probs[..k]);
        let mut kinds = [0usize; MAX_EDGES];
        for (k, e) in kinds.iter_mut().zip(edges) {
            *k = kind(e.action);
        }
        let mut child = [[0f64; TABLE_LANES]; MAX_EDGES];
        for (a, e) in edges.iter().enumerate() {
            if probs[a] == 0.0 {
                continue; // no lane ever takes it
            }
            match e.next() {
                Next::Decision(c) => self.walk(c, d, &mut child[a]),
                Next::End(p) => child[a] = [tree.payoff(p).chips[d.result][1] as f64; TABLE_LANES],
            }
        }
        let mut biased_probs = [[0f64; MAX_EDGES]; 3];
        for (f, slot) in biased_probs.iter_mut().enumerate() {
            biased(&probs[..k], &kinds[..k], f, &mut slot[..k]);
        }
        for (lane, o) in out.iter_mut().enumerate() {
            let w = match lane_bias(lane, player) {
                Some(f) => &biased_probs[f][..k],
                None => &probs[..k],
            };
            *o = (0..k).map(|a| w[a] * child[a][lane]).sum();
        }
    }
}

/// The big blind's chips in and the pot at an abstract decision point.
fn committed_and_pot<B: Bucketer>(bp: &blueprint::play::Blueprint<B>, node: u32) -> (f64, f64) {
    let c = bp.game().config();
    let rules = Config::new(&[c.stack, c.stack], c.small_blind, c.big_blind, 0, 0)
        .expect("the blueprint's table is valid");
    let mut s = State::from_seed(&rules, 0);
    for a in bp.game().tree().line(node) {
        s.apply(a).expect("the tree holds legal lines");
    }
    let bb = s.big_blind_seat();
    (s.committed()[bb] as f64, s.pot() as f64)
}

/// Settings for [`build`].
#[derive(Clone, Debug)]
pub struct BuildConfig {
    pub deals: u64,
    pub seed: u64,
    /// Deals generated (in parallel) before the nodes walk them (in parallel).
    pub block: u64,
}

impl Default for BuildConfig {
    fn default() -> Self {
        BuildConfig {
            deals: 4_000_000,
            seed: 7,
            block: 1 << 16,
        }
    }
}

/// One part of a build: the tables of a run of turn starts, and the deals per cell (the
/// same for every part, since every part walks every deal).
pub struct Part {
    /// `[node][lane][big blind bucket][small blind bucket]`, for the part's nodes in order.
    pub q: Vec<f32>,
    /// Deals per cell, `[big blind bucket][small blind bucket]`.
    pub count: Vec<u64>,
    pub seconds: f64,
}

/// Cell ranges a block is split into for the walk. Any split gives the same sums: a cell
/// is in one range only and adds its deals in the stream's order.
const SLICES: usize = 64;

/// Builds the tables of `nodes` (turn starts of `bp`, in table order) over the deals of
/// `config`. `stop` is asked between blocks of deals; when it says yes the part is given up
/// (`None`). `progress` gets the deals done after each block.
pub fn build_part<B: Bucketer + Sync>(
    bp: &blueprint::play::Blueprint<B>,
    nodes: &[u32],
    config: &BuildConfig,
    stop: &dyn Fn() -> bool,
    mut progress: impl FnMut(u64),
) -> Option<Part> {
    let start = std::time::Instant::now();
    let bucketer = bp.game().bucketer();
    let nb = bucketer.num_buckets(Street::Flop) as usize;
    let cells = nb * nb;
    let at: Vec<(f64, f64)> = nodes.iter().map(|&n| committed_and_pot(bp, n)).collect();
    // sums[node][cell][lane]: a cell's lanes side by side, so a range of cells is one slice.
    let mut sums: Vec<Vec<f64>> = vec![vec![0.0; cells * TABLE_LANES]; nodes.len()];
    let mut count = vec![0u64; cells];
    let walker = Walker { bp };
    // The cell ranges of the walk.
    let bounds: Vec<usize> = (0..=SLICES).map(|i| i * cells / SLICES).collect();
    let mut done = 0u64;
    while done < config.deals {
        if stop() {
            return None;
        }
        let n = config.block.min(config.deals - done);
        let deals: Vec<Deal> = (done..done + n)
            .into_par_iter()
            .map(|i| deal(bucketer, config.seed, i))
            .collect();
        // The block's deals by cell, and within a cell in the stream's order.
        let mut order: Vec<(u32, u32)> = deals
            .iter()
            .enumerate()
            .map(|(i, d)| {
                let [b_sb, b_bb] = d.buckets[0];
                assert!(
                    (b_sb as usize) < nb && (b_bb as usize) < nb,
                    "flop bucket out of range"
                );
                ((b_bb as usize * nb + b_sb as usize) as u32, i as u32)
            })
            .collect();
        order.sort_unstable();
        for &(cell, _) in &order {
            count[cell as usize] += 1;
        }
        // Where each cell range starts in `order`.
        let firsts: Vec<usize> = bounds
            .iter()
            .map(|&c| order.partition_point(|&(cell, _)| (cell as usize) < c))
            .collect();
        // One piece of work per node and cell range, each with its own slice of the sums.
        let mut work = Vec::with_capacity(nodes.len() * SLICES);
        for (i, sum) in sums.iter_mut().enumerate() {
            let mut rest = &mut sum[..];
            for r in 0..SLICES {
                let width = (bounds[r + 1] - bounds[r]) * TABLE_LANES;
                let (piece, tail) = rest.split_at_mut(width);
                rest = tail;
                if firsts[r] < firsts[r + 1] {
                    work.push((i, r, piece));
                }
            }
        }
        work.into_par_iter().for_each(|(i, r, piece)| {
            let (c, p) = at[i];
            let mut v = [0f64; TABLE_LANES];
            for &(cell, k) in &order[firsts[r]..firsts[r + 1]] {
                walker.walk(nodes[i], &deals[k as usize], &mut v);
                let at = (cell as usize - bounds[r]) * TABLE_LANES;
                for (lane, x) in v.iter().enumerate() {
                    piece[at + lane] += (x + c) / p;
                }
            }
        });
        done += n;
        progress(done);
    }
    let mut q = vec![0f32; nodes.len() * TABLE_LANES * cells];
    let mut lane_sum = vec![0f64; cells];
    for (i, sum) in sums.iter().enumerate() {
        for lane in 0..TABLE_LANES {
            for (cell, s) in lane_sum.iter_mut().enumerate() {
                *s = sum[cell * TABLE_LANES + lane];
            }
            let out =
                &mut q[(i * TABLE_LANES + lane) * cells..(i * TABLE_LANES + lane + 1) * cells];
            shrink(&lane_sum, &count, nb, out);
        }
    }
    Some(Part {
        q,
        count,
        seconds: start.elapsed().as_secs_f64(),
    })
}

/// Deals per cell: the fewest, the median and the most.
pub fn cell_deals(count: &[u64]) -> [u64; 3] {
    let mut sorted = count.to_vec();
    sorted.sort_unstable();
    let n = sorted.len();
    [sorted[0], sorted[n / 2], sorted[n - 1]]
}

/// Builds the tables of `bp` (made from `strategy`, hashed into the header) in one part,
/// held in memory. `crate::leaf_job` builds the same tables in parts.
pub fn build<B: Bucketer + Sync>(
    bp: &blueprint::play::Blueprint<B>,
    strategy: &Path,
    config: &BuildConfig,
    progress: impl FnMut(u64),
) -> io::Result<LeafTables> {
    let nodes = turn_starts(bp);
    let part = build_part(bp, &nodes, config, &|| false, progress).expect("never stopped");
    let header = Header {
        nodes: nodes.clone(),
        buckets: bp.game().bucketer().num_buckets(Street::Flop) as usize,
        deals: config.deals,
        seed: config.seed,
        bias: BIAS,
        prior_deals: PRIOR_DEALS,
        strategy: strategy.display().to_string(),
        strategy_hash: file_hash(strategy)?,
        cell_deals: cell_deals(&part.count),
        seconds: part.seconds,
    };
    Ok(LeafTables::new(header, part.q))
}

impl LeafTables {
    /// Tables from a header and their values (`[node][lane][bb][sb]`, in the header's node
    /// order).
    pub fn new(header: Header, q: Vec<f32>) -> LeafTables {
        let b = header.buckets;
        assert_eq!(q.len(), header.nodes.len() * TABLE_LANES * b * b);
        let index = header
            .nodes
            .iter()
            .enumerate()
            .map(|(i, &n)| (n, i))
            .collect();
        LeafTables { header, index, q }
    }
}

/// The sequential build the parallel one must match bit for bit: every node walks every
/// deal in the stream's order (the build as it was before parts). For tests.
#[doc(hidden)]
pub fn build_reference<B: Bucketer>(
    bp: &blueprint::play::Blueprint<B>,
    nodes: &[u32],
    config: &BuildConfig,
) -> Vec<f32> {
    let bucketer = bp.game().bucketer();
    let nb = bucketer.num_buckets(Street::Flop) as usize;
    let cells = nb * nb;
    let walker = Walker { bp };
    let at: Vec<(f64, f64)> = nodes.iter().map(|&n| committed_and_pot(bp, n)).collect();
    let mut count = vec![0u64; cells];
    let mut sums = vec![vec![0.0; TABLE_LANES * cells]; nodes.len()];
    for i in 0..config.deals {
        let d = deal(bucketer, config.seed, i);
        let [b_sb, b_bb] = d.buckets[0];
        let cell = b_bb as usize * nb + b_sb as usize;
        count[cell] += 1;
        for (k, &node) in nodes.iter().enumerate() {
            let (c, p) = at[k];
            let mut v = [0f64; TABLE_LANES];
            walker.walk(node, &d, &mut v);
            for (lane, x) in v.iter().enumerate() {
                sums[k][lane * cells + cell] += (x + c) / p;
            }
        }
    }
    let mut q = vec![0f32; nodes.len() * TABLE_LANES * cells];
    for (k, sum) in sums.iter().enumerate() {
        for lane in 0..TABLE_LANES {
            let out =
                &mut q[(k * TABLE_LANES + lane) * cells..(k * TABLE_LANES + lane + 1) * cells];
            shrink(&sum[lane * cells..(lane + 1) * cells], &count, nb, out);
        }
    }
    q
}

/// Cell means pulled toward the additive fit `row + column - all` by [`PRIOR_DEALS`].
fn shrink(sum: &[f64], count: &[u64], nb: usize, out: &mut [f32]) {
    let mut row = vec![(0.0, 0.0); nb];
    let mut col = vec![(0.0, 0.0); nb];
    let (mut all, mut all_n) = (0.0, 0.0);
    for i in 0..nb {
        for j in 0..nb {
            let (s, n) = (sum[i * nb + j], count[i * nb + j] as f64);
            row[i].0 += s;
            row[i].1 += n;
            col[j].0 += s;
            col[j].1 += n;
            all += s;
            all_n += n;
        }
    }
    let mean = |(s, n): (f64, f64), fallback: f64| if n > 0.0 { s / n } else { fallback };
    let grand = mean((all, all_n), 0.5);
    for i in 0..nb {
        let r = mean(row[i], grand);
        for j in 0..nb {
            let c = mean(col[j], grand);
            let prior = r + c - grand;
            let (s, n) = (sum[i * nb + j], count[i * nb + j] as f64);
            out[i * nb + j] = ((s + PRIOR_DEALS * prior) / (n + PRIOR_DEALS)) as f32;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bias_multiplies_and_renormalizes() {
        let probs = [0.2, 0.5, 0.2, 0.1];
        let kinds = [0, 1, 2, 2];
        let mut out = [0.0; 4];
        biased(&probs, &kinds, 2, &mut out);
        let total = 0.2 + 0.5 + 1.0 + 0.5;
        let want = [0.2 / total, 0.5 / total, 1.0 / total, 0.5 / total];
        for (a, b) in out.iter().zip(want) {
            assert!((a - b).abs() < 1e-12);
        }
        // A kind with no action changes nothing.
        biased(&[0.4, 0.6], &[1, 2], 0, &mut out[..2]);
        assert!((out[0] - 0.4).abs() < 1e-12 && (out[1] - 0.6).abs() < 1e-12);
    }

    #[test]
    fn lanes_bias_the_right_player() {
        assert_eq!(lane_bias(0, 0), None);
        assert_eq!(lane_bias(0, 1), None);
        assert_eq!(lane_bias(1, 0), Some(0));
        assert_eq!(lane_bias(3, 0), Some(2));
        assert_eq!(lane_bias(3, 1), None);
        assert_eq!(lane_bias(4, 1), Some(0));
        assert_eq!(lane_bias(6, 1), Some(2));
        assert_eq!(lane_bias(6, 0), None);
        assert_eq!(chooser_lanes(true), [0, 4, 5, 6]);
        assert_eq!(chooser_lanes(false), [0, 1, 2, 3]);
    }

    #[test]
    fn shrink_keeps_full_cells_and_fills_empty_ones() {
        // 2 x 2: three cells with many deals, one empty.
        let count = [1000, 1000, 1000, 0];
        let sum = [100.0, 300.0, 500.0, 0.0]; // means 0.1, 0.3, 0.5, -
        let mut out = [0f32; 4];
        shrink(&sum, &count, 2, &mut out);
        assert!((out[0] - 0.1).abs() < 1e-3);
        assert!((out[1] - 0.3).abs() < 1e-3);
        assert!((out[2] - 0.5).abs() < 1e-3);
        // Row 1 mean 0.5, column 1 mean 0.3, all 0.3: prior 0.5.
        assert!((out[3] - 0.5).abs() < 1e-6);
    }
}
