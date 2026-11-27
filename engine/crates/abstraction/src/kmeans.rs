//! k-means with k-means++ seeding, for hands described as vectors (the river) or as
//! histograms over the next street's buckets (the flop and turn).
//!
//! The same seed and settings give the same buckets on any machine and with any number of
//! threads:
//!
//! - the random numbers come from [`crate::rng::Rng`];
//! - cluster sums are whole numbers (hand counts times whole-number features), so the order
//!   in which threads add them up doesn't matter;
//! - sums of costs are taken over fixed-size blocks of hands and added in block order;
//! - ties go to the lower-numbered centre.

use crate::emd::{GreedyScratch, Line, Metric};
use crate::rng::Rng;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};

/// Hands per block when work is split across threads.
const BLOCK: usize = 2048;
/// Safety margin on lower bounds, against rounding.
const BOUND_MARGIN: f32 = 0.9995;

/// How to run k-means.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct KMeansSettings {
    /// Lloyd iterations at most.
    pub max_iters: usize,
    /// Stop when fewer than this share of the training hands change bucket.
    pub tolerance: f64,
    /// Train the centres on at most this many hands, picked at random; 0 means all of them.
    /// Every hand is then put in the bucket of its nearest centre.
    pub train_samples: usize,
    /// Seed the centres from at most this many of the training hands; 0 means all of them.
    pub init_samples: usize,
    /// Runs from different seeds; the run with the lowest cost is kept.
    pub restarts: usize,
}

impl Default for KMeansSettings {
    fn default() -> KMeansSettings {
        KMeansSettings {
            max_iters: 50,
            tolerance: 0.001,
            train_samples: 0,
            init_samples: 0,
            restarts: 1,
        }
    }
}

/// A set of hands k-means can cluster.
pub trait Space: Sync {
    /// Centres, prepared for fast comparison.
    type Centers: Sync;
    /// Scratch space, one per thread.
    type Scratch: Send;

    /// Number of hands.
    fn len(&self) -> usize;
    /// Whether there are no hands.
    fn is_empty(&self) -> bool {
        self.len() == 0
    }
    /// Length of a centre.
    fn dim(&self) -> usize;
    /// How many real hands hand `i` stands for.
    fn weight(&self, i: usize) -> u64;
    /// Adds hand `i`, times its weight, to `acc` (length `dim`). In whole numbers: 1.0 is
    /// [`Space::unit`].
    fn accumulate(&self, i: usize, acc: &mut [u64]);
    /// The whole number that stands for 1.0 in [`Space::accumulate`].
    fn unit(&self) -> f64;
    /// Prepares `k` centres given as `k * dim` numbers.
    fn centers(&self, centroids: &[f32], k: usize) -> Self::Centers;
    fn scratch(&self) -> Self::Scratch;
    /// The nearest centre to hand `i` and the cost of putting it there. `hint` is a centre
    /// likely to be near. Ties go to the lower-numbered centre.
    fn nearest(
        &self,
        centers: &Self::Centers,
        i: usize,
        hint: Option<u32>,
        scratch: &mut Self::Scratch,
    ) -> (u32, f32);
    /// The cost of hand `i` at centre `c`. May return any number at or above `bound` when
    /// the cost is at least `bound`.
    fn cost(
        &self,
        centers: &Self::Centers,
        c: usize,
        i: usize,
        bound: f32,
        scratch: &mut Self::Scratch,
    ) -> f32;
    /// The squared distance that goes with a cost, for k-means++ seeding. The cost itself
    /// when it already is a squared distance.
    fn squared_distance(&self, cost: f32) -> f64 {
        cost as f64
    }
}

/// The result of [`kmeans`].
#[derive(Clone, Debug)]
pub struct Clustering {
    /// Clusters in use. Below the number asked for only when there are fewer distinct hands.
    pub k: usize,
    /// The bucket of every hand.
    pub assignment: Vec<u16>,
    /// The mean of each bucket's hands, `k * dim` numbers.
    pub centroids: Vec<f32>,
    /// The number of real hands in each bucket.
    pub weights: Vec<u64>,
    /// The average cost of a real hand at its centre.
    pub cost: f64,
    /// Lloyd iterations of the run that was kept.
    pub iterations: usize,
    /// Hands the centres were trained on.
    pub trained_on: usize,
    /// Comparisons of a hand with a centre that were worked out in full, as a share of all
    /// the comparisons a plain k-means would make in the last pass.
    pub full_comparisons: f64,
    /// Seconds spent seeding, iterating and on the last pass over every hand.
    pub seconds: [f64; 3],
}

/// The mean of the hands in `ids` per cluster: sums of whole numbers, so exact.
fn cluster_sums<S: Space>(
    space: &S,
    ids: Option<&[u32]>,
    assignment: &[u32],
    k: usize,
) -> (Vec<u64>, Vec<u64>) {
    let dim = space.dim();
    let n = assignment.len();
    let pieces = (rayon::current_num_threads() * 4).max(1);
    let piece = n.div_ceil(pieces).max(1);
    (0..n.div_ceil(piece))
        .into_par_iter()
        .map(|p| {
            let mut sums = vec![0u64; k * dim];
            let mut weights = vec![0u64; k];
            for at in p * piece..((p + 1) * piece).min(n) {
                let i = ids.map_or(at, |ids| ids[at] as usize);
                let c = assignment[at] as usize;
                space.accumulate(i, &mut sums[c * dim..(c + 1) * dim]);
                weights[c] += space.weight(i);
            }
            (sums, weights)
        })
        .reduce(
            || (vec![0u64; k * dim], vec![0u64; k]),
            |mut a, b| {
                a.0.iter_mut().zip(&b.0).for_each(|(x, y)| *x += y);
                a.1.iter_mut().zip(&b.1).for_each(|(x, y)| *x += y);
                a
            },
        )
}

fn centroid_of<S: Space>(space: &S, i: usize) -> Vec<f32> {
    let mut acc = vec![0u64; space.dim()];
    space.accumulate(i, &mut acc);
    let scale = 1.0 / (space.weight(i) as f64 * space.unit());
    acc.iter().map(|&x| (x as f64 * scale) as f32).collect()
}

/// One pass: every hand in `ids` to its nearest centre. Returns the total weighted cost and
/// how many hands changed, and fills `costs` when given.
fn assign<S: Space>(
    space: &S,
    centers: &S::Centers,
    ids: Option<&[u32]>,
    assignment: &mut [u32],
    costs: Option<&mut [f32]>,
) -> (f64, usize) {
    let block = |b: usize, assignment: &mut [u32], mut costs: Option<&mut [f32]>| -> (f64, usize) {
        let mut scratch = space.scratch();
        let (mut total, mut changed) = (0f64, 0usize);
        for (off, slot) in assignment.iter_mut().enumerate() {
            let at = b * BLOCK + off;
            let i = ids.map_or(at, |ids| ids[at] as usize);
            let hint = (*slot != u32::MAX).then_some(*slot);
            let (c, cost) = space.nearest(centers, i, hint, &mut scratch);
            changed += (c != *slot) as usize;
            *slot = c;
            total += cost as f64 * space.weight(i) as f64;
            if let Some(costs) = costs.as_deref_mut() {
                costs[off] = cost;
            }
        }
        (total, changed)
    };
    let per_block: Vec<(f64, usize)> = match costs {
        Some(costs) => assignment
            .par_chunks_mut(BLOCK)
            .zip(costs.par_chunks_mut(BLOCK))
            .enumerate()
            .map(|(b, (a, c))| block(b, a, Some(c)))
            .collect(),
        None => assignment
            .par_chunks_mut(BLOCK)
            .enumerate()
            .map(|(b, a)| block(b, a, None))
            .collect(),
    };
    per_block
        .iter()
        .fold((0.0, 0), |acc, x| (acc.0 + x.0, acc.1 + x.1))
}

/// k-means++ seeding on the hands in `ids`: the first centre is a hand picked at random,
/// each later centre a hand picked with chances in proportion to its weight times its
/// squared distance to the nearest centre so far.
fn seed<S: Space>(space: &S, ids: &[u32], k: usize, rng: &mut Rng) -> Vec<f32> {
    let dim = space.dim();
    let n = ids.len();
    let mut centroids: Vec<f32> = Vec::with_capacity(k * dim);
    let mut nearest = vec![f32::INFINITY; n];
    let total_weight: u64 = ids.iter().map(|&i| space.weight(i as usize)).sum();
    // First centre: by weight.
    let mut pick = {
        let mut target = rng.below(total_weight.max(1));
        let mut chosen = 0;
        for (at, &i) in ids.iter().enumerate() {
            let w = space.weight(i as usize);
            if target < w {
                chosen = at;
                break;
            }
            target -= w;
        }
        chosen
    };
    for _ in 0..k {
        let centroid = centroid_of(space, ids[pick] as usize);
        let one = space.centers(&centroid, 1);
        centroids.extend_from_slice(&centroid);
        let sums: Vec<f64> = nearest
            .par_chunks_mut(BLOCK)
            .enumerate()
            .map(|(b, chunk)| {
                let mut scratch = space.scratch();
                let mut sum = 0f64;
                for (off, slot) in chunk.iter_mut().enumerate() {
                    let at = b * BLOCK + off;
                    let i = ids[at] as usize;
                    if at == pick {
                        *slot = 0.0;
                    } else if *slot > 0.0 {
                        let cost = space.cost(&one, 0, i, *slot, &mut scratch);
                        if cost < *slot {
                            *slot = cost;
                        }
                    }
                    sum += space.squared_distance(*slot) * space.weight(i) as f64;
                }
                sum
            })
            .collect();
        let total: f64 = sums.iter().sum();
        if centroids.len() == k * dim || total <= 0.0 {
            break; // enough centres, or every hand already sits on one
        }
        // Pick the block, then the hand inside it.
        let mut target = rng.next_f64() * total;
        let mut b = 0;
        while b + 1 < sums.len() && (target >= sums[b] || sums[b] <= 0.0) {
            target -= sums[b];
            b += 1;
        }
        // Rounding can carry the target past the last block with any cost left in it.
        while sums[b] <= 0.0 {
            b -= 1;
        }
        let start = b * BLOCK;
        let end = (start + BLOCK).min(n);
        let mut last_positive = start;
        pick = usize::MAX;
        for at in start..end {
            let share = space.squared_distance(nearest[at]) * space.weight(ids[at] as usize) as f64;
            if share > 0.0 {
                last_positive = at;
                if target < share {
                    pick = at;
                    break;
                }
                target -= share;
            }
        }
        if pick == usize::MAX {
            pick = last_positive;
        }
    }
    centroids
}

/// Runs k-means on `space` into at most `k` clusters.
pub fn kmeans<S: Space>(
    space: &S,
    k: usize,
    settings: &KMeansSettings,
    seed_value: u64,
) -> Clustering {
    let n = space.len();
    let dim = space.dim();
    assert!(n > 0, "nothing to cluster");
    assert!(
        k >= 1 && k <= u16::MAX as usize,
        "between 1 and 65,535 buckets"
    );
    assert!(n <= u32::MAX as usize, "at most 4 billion hands");
    let mut seconds = [0f64; 3];
    // Set ABSTRACTION_PROGRESS to see each iteration on standard error.
    let progress = std::env::var_os("ABSTRACTION_PROGRESS").is_some();

    let mut best: Option<(f64, Vec<f32>, usize, usize)> = None;
    let mut trained_on = n;
    for restart in 0..settings.restarts.max(1) {
        let mut rng = Rng::stream(seed_value, restart as u64);
        // The training hands: all of them, or a random sample, in increasing order.
        let ids: Vec<u32> = if settings.train_samples == 0 || settings.train_samples >= n {
            (0..n as u32).collect()
        } else {
            let mut ids: Vec<u32> = (0..settings.train_samples)
                .map(|_| rng.below(n as u64) as u32)
                .collect();
            ids.sort_unstable();
            ids.dedup();
            ids
        };
        trained_on = ids.len();

        let started = std::time::Instant::now();
        let seed_ids: Vec<u32> = if settings.init_samples == 0 || settings.init_samples >= ids.len()
        {
            Vec::new()
        } else {
            let step = ids.len() as f64 / settings.init_samples as f64;
            (0..settings.init_samples)
                .map(|j| ids[(j as f64 * step) as usize])
                .collect()
        };
        let mut centroids = seed(
            space,
            if seed_ids.is_empty() { &ids } else { &seed_ids },
            k,
            &mut rng,
        );
        let live = centroids.len() / dim;
        seconds[0] += started.elapsed().as_secs_f64();

        if progress {
            eprintln!(
                "  k-means run {restart}: {live} centres seeded, {:.1} s",
                started.elapsed().as_secs_f64()
            );
        }
        let train_weight: u64 = ids.iter().map(|&i| space.weight(i as usize)).sum();
        let started = std::time::Instant::now();
        let mut assignment = vec![u32::MAX; ids.len()];
        let mut costs = vec![0f32; ids.len()];
        let mut cost = f64::INFINITY;
        let mut iterations = 0;
        for _ in 0..settings.max_iters.max(1) {
            iterations += 1;
            let centers = space.centers(&centroids, live);
            let (total, changed) = assign(
                space,
                &centers,
                Some(&ids),
                &mut assignment,
                Some(&mut costs),
            );
            cost = total;
            let (sums, weights) = cluster_sums(space, Some(&ids), &assignment, live);
            let mut empty: Vec<usize> = Vec::new();
            for c in 0..live {
                if weights[c] == 0 {
                    empty.push(c);
                    continue;
                }
                let scale = 1.0 / (weights[c] as f64 * space.unit());
                for (x, &s) in centroids[c * dim..(c + 1) * dim]
                    .iter_mut()
                    .zip(&sums[c * dim..(c + 1) * dim])
                {
                    *x = (s as f64 * scale) as f32;
                }
            }
            // A centre that lost all its hands moves onto the hand that costs the most.
            let mut moved = false;
            if !empty.is_empty() {
                let mut order: Vec<u32> = (0..ids.len() as u32)
                    .filter(|&at| costs[at as usize] > 0.0)
                    .collect();
                order.sort_by(|&a, &b| {
                    costs[b as usize]
                        .partial_cmp(&costs[a as usize])
                        .unwrap()
                        .then(a.cmp(&b))
                });
                for (&c, &at) in empty.iter().zip(&order) {
                    let centroid = centroid_of(space, ids[at as usize] as usize);
                    centroids[c * dim..(c + 1) * dim].copy_from_slice(&centroid);
                    costs[at as usize] = 0.0;
                    moved = true;
                }
            }
            if progress {
                eprintln!(
                    "  k-means run {restart} iteration {iterations}: cost {:.6}, {:.3}% of hands moved, {} empty, {:.1} s",
                    cost / train_weight as f64,
                    changed as f64 * 100.0 / ids.len() as f64,
                    empty.len(),
                    started.elapsed().as_secs_f64()
                );
            }
            if !moved && (changed as f64) < settings.tolerance * ids.len() as f64 {
                break;
            }
        }
        seconds[1] += started.elapsed().as_secs_f64();
        if best.as_ref().is_none_or(|b| cost < b.0) {
            best = Some((cost, centroids, live, iterations));
        }
    }
    let (_, trained, live, iterations) = best.expect("at least one run");

    // Every hand to its nearest trained centre, then the true means of the buckets.
    let started = std::time::Instant::now();
    let centers = space.centers(&trained, live);
    let mut assignment = vec![u32::MAX; n];
    TRIED.store(0, std::sync::atomic::Ordering::Relaxed);
    FULL.store(0, std::sync::atomic::Ordering::Relaxed);
    let (total, _) = assign(space, &centers, None, &mut assignment, None);
    let (sums, weights) = cluster_sums(space, None, &assignment, live);
    let total_weight: u64 = weights.iter().sum();

    // Drop clusters without hands and renumber.
    let mut renumber = vec![u16::MAX; live];
    let mut centroids = Vec::with_capacity(live * dim);
    let mut kept_weights = Vec::with_capacity(live);
    for c in 0..live {
        if weights[c] == 0 {
            continue;
        }
        renumber[c] = kept_weights.len() as u16;
        let scale = 1.0 / (weights[c] as f64 * space.unit());
        centroids.extend(
            sums[c * dim..(c + 1) * dim]
                .iter()
                .map(|&s| (s as f64 * scale) as f32),
        );
        kept_weights.push(weights[c]);
    }
    let assignment: Vec<u16> = assignment
        .par_iter()
        .map(|&c| renumber[c as usize])
        .collect();
    seconds[2] = started.elapsed().as_secs_f64();

    Clustering {
        k: kept_weights.len(),
        assignment,
        centroids,
        weights: kept_weights,
        cost: total / total_weight as f64,
        iterations,
        trained_on,
        full_comparisons: match TRIED.load(std::sync::atomic::Ordering::Relaxed) {
            0 => 1.0,
            tried => FULL.load(std::sync::atomic::Ordering::Relaxed) as f64 / tried as f64,
        },
        seconds,
    }
}

/// Counters behind [`Clustering::full_comparisons`]: comparisons a plain k-means would
/// make, and those worked out in full. They are statistics only and never change a result.
static TRIED: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
static FULL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Renumbers buckets so that `key` increases with the bucket number (weakest hands in
/// bucket 0). Returns the new order: `order[new] = old`.
pub fn sort_buckets(clustering: &mut Clustering, dim: usize, key: &[f64]) -> Vec<usize> {
    let k = clustering.k;
    let mut order: Vec<usize> = (0..k).collect();
    order.sort_by(|&a, &b| key[a].partial_cmp(&key[b]).unwrap().then(a.cmp(&b)));
    let mut new_of = vec![0u16; k];
    for (new, &old) in order.iter().enumerate() {
        new_of[old] = new as u16;
    }
    clustering
        .assignment
        .par_iter_mut()
        .for_each(|a| *a = new_of[*a as usize]);
    let mut centroids = Vec::with_capacity(k * dim);
    for &old in &order {
        centroids.extend_from_slice(&clustering.centroids[old * dim..(old + 1) * dim]);
    }
    clustering.centroids = centroids;
    clustering.weights = order.iter().map(|&old| clustering.weights[old]).collect();
    order
}

// ---------------------------------------------------------------------------------------
// Vectors with straight-line distance (the river).
// ---------------------------------------------------------------------------------------

/// How many real hands each point stands for.
pub enum Weights<'a> {
    Small(&'a [u8]),
    Large(&'a [u64]),
}

/// Points with `dim` whole-number features each (`unit` standing for 1.0), compared by
/// squared straight-line distance.
pub struct VectorSpace<'a> {
    pub data: &'a [u16],
    pub dim: usize,
    pub unit: u32,
    pub weights: Weights<'a>,
}

/// Centres stored one coordinate after another, so the distances from one point to every
/// centre are computed a coordinate at a time over all the centres at once.
pub struct VectorCenters {
    k: usize,
    by_dim: Vec<f32>,
}

impl VectorSpace<'_> {
    #[inline]
    fn point(&self, i: usize, out: &mut [f32]) {
        let unit = self.unit as f32;
        for (o, &x) in out
            .iter_mut()
            .zip(&self.data[i * self.dim..(i + 1) * self.dim])
        {
            *o = x as f32 / unit;
        }
    }
}

impl Space for VectorSpace<'_> {
    type Centers = VectorCenters;
    type Scratch = (Vec<f32>, Vec<f32>);

    fn len(&self) -> usize {
        self.data.len() / self.dim
    }
    fn dim(&self) -> usize {
        self.dim
    }
    #[inline]
    fn weight(&self, i: usize) -> u64 {
        match self.weights {
            Weights::Small(w) => w[i] as u64,
            Weights::Large(w) => w[i],
        }
    }
    #[inline]
    fn accumulate(&self, i: usize, acc: &mut [u64]) {
        let w = self.weight(i);
        for (a, &x) in acc
            .iter_mut()
            .zip(&self.data[i * self.dim..(i + 1) * self.dim])
        {
            *a += w * x as u64;
        }
    }
    fn unit(&self) -> f64 {
        self.unit as f64
    }
    fn centers(&self, centroids: &[f32], k: usize) -> VectorCenters {
        let mut by_dim = vec![0f32; k * self.dim];
        for c in 0..k {
            for d in 0..self.dim {
                by_dim[d * k + c] = centroids[c * self.dim + d];
            }
        }
        VectorCenters { k, by_dim }
    }
    fn scratch(&self) -> Self::Scratch {
        (vec![0f32; self.dim], Vec::new())
    }
    #[inline]
    fn nearest(
        &self,
        centers: &VectorCenters,
        i: usize,
        _hint: Option<u32>,
        scratch: &mut Self::Scratch,
    ) -> (u32, f32) {
        let (point, dist) = scratch;
        let k = centers.k;
        self.point(i, point);
        dist.clear();
        dist.resize(k, 0.0);
        for (d, &x) in point.iter().enumerate() {
            for (acc, &c) in dist.iter_mut().zip(&centers.by_dim[d * k..(d + 1) * k]) {
                let t = x - c;
                *acc += t * t;
            }
        }
        let mut best = (0u32, f32::INFINITY);
        for (c, &x) in dist.iter().enumerate() {
            if x < best.1 {
                best = (c as u32, x);
            }
        }
        best
    }
    #[inline]
    fn cost(
        &self,
        centers: &VectorCenters,
        c: usize,
        i: usize,
        _bound: f32,
        scratch: &mut Self::Scratch,
    ) -> f32 {
        let point = &mut scratch.0;
        self.point(i, point);
        let mut total = 0f32;
        for (d, &x) in point.iter().enumerate() {
            let t = x - centers.by_dim[d * centers.k + c];
            total += t * t;
        }
        total
    }
}

// ---------------------------------------------------------------------------------------
// Histograms over the next street's buckets, with earth mover's distance (flop and turn).
// ---------------------------------------------------------------------------------------

/// Hands as histograms: for each hand, the next-street bucket it lands in for each card
/// that can come.
pub struct HistogramSpace<'a> {
    /// `outcomes` bucket numbers per hand, in increasing order.
    pub labels: &'a [u16],
    /// Cards that can come: 47 on the flop and 46 on the turn in the full deck.
    pub outcomes: usize,
    pub weights: &'a [u8],
    pub metric: &'a Metric,
}

/// Blocks the cumulative curve is summed over for the [`Line`] lower bound.
const LINE_BLOCKS: usize = 16;

pub enum HistogramCenters {
    Line {
        k: usize,
        /// Each centre's cumulative curve times the gaps, `k * (next_k - 1)` numbers.
        curves: Vec<f32>,
        /// Block sums of the curves, one block after another: `sketch[t * k + c]`.
        sketch: Vec<f32>,
        blocks: usize,
    },
    Matrix {
        k: usize,
        /// The centres themselves.
        means: Vec<f32>,
        /// Sketches, one number after another: `sketch[t * k + c]`.
        sketch: Vec<f32>,
    },
}

#[derive(Default)]
pub struct HistogramScratch {
    curve: Vec<f32>,
    sketch: Vec<f32>,
    bound: Vec<f32>,
    straight: Vec<f32>,
    buckets: Vec<u16>,
    shares: Vec<f32>,
    greedy: GreedyScratch,
}

/// Sum of absolute differences, in eight running sums so the compiler can use wide
/// registers and the result doesn't depend on whether it does.
#[inline]
fn l1(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = [0f32; 8];
    let (ca, cb) = (a.chunks_exact(8), b.chunks_exact(8));
    let (ra, rb) = (ca.remainder(), cb.remainder());
    for (x, y) in ca.zip(cb) {
        for l in 0..8 {
            acc[l] += (x[l] - y[l]).abs();
        }
    }
    let mut total =
        ((acc[0] + acc[4]) + (acc[1] + acc[5])) + ((acc[2] + acc[6]) + (acc[3] + acc[7]));
    for (x, y) in ra.iter().zip(rb) {
        total += (x - y).abs();
    }
    total
}

/// Block sums of a curve.
#[inline]
fn line_sketch(curve: &[f32], blocks: usize, out: &mut [f32]) {
    let len = curve.len().div_ceil(blocks).max(1);
    for (o, chunk) in out.iter_mut().zip(curve.chunks(len)) {
        *o = chunk.iter().sum();
    }
}

impl HistogramSpace<'_> {
    #[inline]
    fn row(&self, i: usize) -> &[u16] {
        &self.labels[i * self.outcomes..(i + 1) * self.outcomes]
    }

    /// The hand's cumulative curve times the gaps between buckets. The sum of absolute
    /// differences between two such curves is the earth mover's distance on a line.
    #[inline]
    fn curve(&self, line: &Line, i: usize, out: &mut Vec<f32>) {
        let row = self.row(i);
        let step = 1.0 / self.outcomes as f32;
        out.clear();
        let mut at = 0;
        for b in 0..line.pos.len() - 1 {
            while at < row.len() && row[at] as usize <= b {
                at += 1;
            }
            out.push(at as f32 * step * line.gap(b));
        }
    }

    /// The hand's histogram as buckets and shares.
    #[inline]
    fn entries(&self, i: usize, buckets: &mut Vec<u16>, shares: &mut Vec<f32>) {
        let step = 1.0 / self.outcomes as f32;
        buckets.clear();
        shares.clear();
        for &label in self.row(i) {
            if buckets.last() == Some(&label) {
                *shares.last_mut().unwrap() += step;
            } else {
                buckets.push(label);
                shares.push(step);
            }
        }
    }
}

impl Space for HistogramSpace<'_> {
    type Centers = HistogramCenters;
    type Scratch = HistogramScratch;

    fn len(&self) -> usize {
        self.weights.len()
    }
    fn dim(&self) -> usize {
        self.metric.k()
    }
    #[inline]
    fn weight(&self, i: usize) -> u64 {
        self.weights[i] as u64
    }
    #[inline]
    fn accumulate(&self, i: usize, acc: &mut [u64]) {
        let w = self.weights[i] as u64;
        for &label in self.row(i) {
            acc[label as usize] += w;
        }
    }
    fn unit(&self) -> f64 {
        self.outcomes as f64
    }

    fn centers(&self, centroids: &[f32], k: usize) -> HistogramCenters {
        let next_k = self.metric.k();
        match self.metric {
            Metric::Line(line) => {
                let width = next_k - 1;
                let mut curves = vec![0f32; k * width];
                let blocks = LINE_BLOCKS.min(width.max(1));
                let mut sketch = vec![0f32; blocks * k];
                let mut one = vec![0f32; blocks];
                for c in 0..k {
                    let mut running = 0f32;
                    for b in 0..width {
                        running += centroids[c * next_k + b];
                        curves[c * width + b] = running * line.gap(b);
                    }
                    line_sketch(&curves[c * width..(c + 1) * width], blocks, &mut one);
                    for t in 0..blocks {
                        sketch[t * k + c] = one[t];
                    }
                }
                HistogramCenters::Line {
                    k,
                    curves,
                    sketch,
                    blocks,
                }
            }
            Metric::Matrix(matrix) => {
                let len = matrix.sketch_len();
                let mut sketch = vec![0f32; len * k];
                let mut one = vec![0f32; len];
                for c in 0..k {
                    let mean = &centroids[c * next_k..(c + 1) * next_k];
                    matrix.sketch(mean.iter().cloned().enumerate(), &mut one);
                    for t in 0..len {
                        sketch[t * k + c] = one[t];
                    }
                }
                HistogramCenters::Matrix {
                    k,
                    means: centroids[..k * next_k].to_vec(),
                    sketch,
                }
            }
        }
    }

    fn scratch(&self) -> HistogramScratch {
        HistogramScratch::default()
    }

    fn nearest(
        &self,
        centers: &HistogramCenters,
        i: usize,
        hint: Option<u32>,
        s: &mut HistogramScratch,
    ) -> (u32, f32) {
        let mut full = 0u64;
        let (k, best) = match (centers, self.metric) {
            (
                HistogramCenters::Line {
                    k,
                    curves,
                    sketch,
                    blocks,
                },
                Metric::Line(line),
            ) => {
                let (k, blocks) = (*k, *blocks);
                let width = line.pos.len() - 1;
                self.curve(line, i, &mut s.curve);
                s.sketch.clear();
                s.sketch.resize(blocks, 0.0);
                line_sketch(&s.curve, blocks, &mut s.sketch);
                // Lower bound for every centre: the block sums can't differ by more than
                // the curves do.
                s.bound.clear();
                s.bound.resize(k, 0.0);
                for t in 0..blocks {
                    let x = s.sketch[t];
                    for (b, &c) in s.bound.iter_mut().zip(&sketch[t * k..(t + 1) * k]) {
                        *b += (x - c).abs();
                    }
                }
                let exact =
                    |c: usize, curve: &[f32]| l1(curve, &curves[c * width..(c + 1) * width]);
                let first = hint.map_or_else(|| argmin(&s.bound), |h| h as usize);
                let mut best = (first as u32, exact(first, &s.curve));
                full += 1;
                for c in 0..k {
                    if c == first || s.bound[c] * BOUND_MARGIN > best.1 {
                        continue;
                    }
                    let cost = exact(c, &s.curve);
                    full += 1;
                    if cost < best.1 || (cost == best.1 && (c as u32) < best.0) {
                        best = (c as u32, cost);
                    }
                }
                (k, best)
            }
            (HistogramCenters::Matrix { k, means, sketch }, Metric::Matrix(matrix)) => {
                let k = *k;
                let next_k = matrix.k;
                let len = matrix.sketch_len();
                self.entries(i, &mut s.buckets, &mut s.shares);
                s.sketch.clear();
                s.sketch.resize(len, 0.0);
                matrix.sketch(
                    s.buckets
                        .iter()
                        .map(|&b| b as usize)
                        .zip(s.shares.iter().cloned()),
                    &mut s.sketch,
                );
                // First lower bound, for every centre at once: the straight-line distance
                // between the average points (kept squared).
                s.straight.clear();
                s.straight.resize(k, 0.0);
                for t in 0..matrix.embed_dim {
                    let x = s.sketch[t];
                    for (b, &c) in s.straight.iter_mut().zip(&sketch[t * k..(t + 1) * k]) {
                        *b += (x - c) * (x - c);
                    }
                }
                // Second lower bound, only for the centres the first lets through: the
                // largest gap in average distance to an anchor.
                let anchors_rule_out = |c: usize, best: f32, point: &[f32]| {
                    (matrix.embed_dim..len)
                        .any(|t| (point[t] - sketch[t * k + c]).abs() * BOUND_MARGIN > best)
                };
                let first = hint.map_or_else(|| argmin(&s.straight), |h| h as usize);
                let mean = |c: usize| &means[c * next_k..(c + 1) * next_k];
                let mut best = (
                    first as u32,
                    matrix.greedy(
                        &s.buckets,
                        &s.shares,
                        mean(first),
                        f32::INFINITY,
                        &mut s.greedy,
                    ),
                );
                full += 1;
                let margin_squared = BOUND_MARGIN * BOUND_MARGIN;
                for c in 0..k {
                    if c == first
                        || s.straight[c] * margin_squared > best.1 * best.1
                        || anchors_rule_out(c, best.1, &s.sketch)
                    {
                        continue;
                    }
                    // A cost above the best so far can't win, so the greedy plan may stop
                    // there. Just above, so that an equal cost is still seen as a tie.
                    let stop = best.1 * 1.000_001 + f32::MIN_POSITIVE;
                    let cost = matrix.greedy(&s.buckets, &s.shares, mean(c), stop, &mut s.greedy);
                    full += 1;
                    if cost < best.1 || (cost == best.1 && (c as u32) < best.0) {
                        best = (c as u32, cost);
                    }
                }
                (k, best)
            }
            _ => unreachable!("centres made for another metric"),
        };
        TRIED.fetch_add(k as u64, std::sync::atomic::Ordering::Relaxed);
        FULL.fetch_add(full, std::sync::atomic::Ordering::Relaxed);
        best
    }

    fn cost(
        &self,
        centers: &HistogramCenters,
        c: usize,
        i: usize,
        bound: f32,
        s: &mut HistogramScratch,
    ) -> f32 {
        match (centers, self.metric) {
            (HistogramCenters::Line { curves, .. }, Metric::Line(line)) => {
                let width = line.pos.len() - 1;
                self.curve(line, i, &mut s.curve);
                l1(&s.curve, &curves[c * width..(c + 1) * width])
            }
            (HistogramCenters::Matrix { k, means, sketch }, Metric::Matrix(matrix)) => {
                let len = matrix.sketch_len();
                self.entries(i, &mut s.buckets, &mut s.shares);
                s.sketch.clear();
                s.sketch.resize(len, 0.0);
                matrix.sketch(
                    s.buckets
                        .iter()
                        .map(|&b| b as usize)
                        .zip(s.shares.iter().cloned()),
                    &mut s.sketch,
                );
                s.straight.clear();
                s.straight.extend((0..len).map(|t| sketch[t * k + c]));
                if matrix.lower_bound(&s.sketch, &s.straight) * BOUND_MARGIN >= bound {
                    return bound;
                }
                let mean = &means[c * matrix.k..(c + 1) * matrix.k];
                matrix.greedy(&s.buckets, &s.shares, mean, bound, &mut s.greedy)
            }
            _ => unreachable!("centres made for another metric"),
        }
    }

    fn squared_distance(&self, cost: f32) -> f64 {
        cost as f64 * cost as f64
    }
}

#[inline]
fn argmin(values: &[f32]) -> usize {
    let mut best = 0;
    for (i, &x) in values.iter().enumerate() {
        if x < values[best] {
            best = i;
        }
    }
    best
}

/// The distance between every two centres under the metric their histograms are over:
/// the ground distance for the street before. Exact for a [`Line`]. For a [`Matrix`] it is
/// the greedy distance in both directions, the smaller kept, then shortened by
/// [`crate::emd::shortest_paths`] so that it obeys the triangle inequality.
pub fn centroid_distances(metric: &Metric, centroids: &[f32], k: usize) -> Vec<f32> {
    let next_k = metric.k();
    let mean = |c: usize| &centroids[c * next_k..(c + 1) * next_k];
    let mut d = vec![0f32; k * k];
    d.par_chunks_mut(k).enumerate().for_each(|(i, row)| {
        let mut scratch = GreedyScratch::default();
        for (j, x) in row.iter_mut().enumerate().take(i) {
            *x = match metric {
                Metric::Line(line) => line.emd(mean(i), mean(j)),
                Metric::Matrix(matrix) => matrix.greedy_between(mean(i), mean(j), &mut scratch),
            };
        }
    });
    for i in 0..k {
        for j in 0..i {
            d[j * k + i] = d[i * k + j];
        }
    }
    if matches!(metric, Metric::Matrix(_)) {
        crate::emd::shortest_paths(&mut d, k);
        // Shortening works row by row in single precision; make the table exactly symmetric.
        for i in 0..k {
            for j in 0..i {
                let x = d[i * k + j].min(d[j * k + i]);
                d[i * k + j] = x;
                d[j * k + i] = x;
            }
        }
    }
    d
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::emd::Matrix;

    fn blobs(rng: &mut Rng, centres: &[(f64, f64)], per: usize, spread: f64) -> Vec<u16> {
        let mut data = Vec::new();
        for &(x, y) in centres {
            for _ in 0..per {
                let dx = (rng.next_f64() - 0.5) * spread;
                let dy = (rng.next_f64() - 0.5) * spread;
                data.push(((x + dx) * 10_000.0) as u16);
                data.push(((y + dy) * 10_000.0) as u16);
            }
        }
        data
    }

    #[test]
    fn finds_well_separated_blobs() {
        let mut rng = Rng::new(1);
        let centres = [(0.1, 0.1), (0.9, 0.1), (0.5, 0.9), (0.1, 0.9), (0.5, 0.5)];
        let data = blobs(&mut rng, &centres, 200, 0.1);
        let weights = vec![1u8; data.len() / 2];
        let space = VectorSpace {
            data: &data,
            dim: 2,
            unit: 10_000,
            weights: Weights::Small(&weights),
        };
        let out = kmeans(&space, 5, &KMeansSettings::default(), 42);
        assert_eq!(out.k, 5);
        // Each blob is one bucket.
        for blob in 0..5 {
            let first = out.assignment[blob * 200];
            assert!(out.assignment[blob * 200..(blob + 1) * 200]
                .iter()
                .all(|&a| a == first));
        }
        assert_eq!(out.weights, vec![200; 5]);
        assert!(out.cost < 0.01);
        // Each centre is near a blob's middle.
        for c in 0..5 {
            let (x, y) = (out.centroids[c * 2] as f64, out.centroids[c * 2 + 1] as f64);
            assert!(centres
                .iter()
                .any(|&(cx, cy)| (x - cx).abs() < 0.02 && (y - cy).abs() < 0.02));
        }
    }

    #[test]
    fn fewer_distinct_points_than_buckets() {
        let data: Vec<u16> = [5u16, 5, 5, 9, 9, 1].to_vec();
        let weights = vec![1u8; 6];
        let space = VectorSpace {
            data: &data,
            dim: 1,
            unit: 10,
            weights: Weights::Small(&weights),
        };
        let out = kmeans(&space, 10, &KMeansSettings::default(), 3);
        assert_eq!(out.k, 3);
        assert!(out.cost < 1e-12);
        assert_eq!(out.assignment[0], out.assignment[1]);
        assert_ne!(out.assignment[0], out.assignment[3]);
    }

    #[test]
    fn weights_pull_the_centre() {
        // Two points, one counted three times: the single centre sits at the weighted mean.
        let data = vec![0u16, 100];
        let weights = vec![1u64, 3];
        let space = VectorSpace {
            data: &data,
            dim: 1,
            unit: 100,
            weights: Weights::Large(&weights),
        };
        let out = kmeans(&space, 1, &KMeansSettings::default(), 0);
        assert_eq!(out.centroids, vec![0.75]);
        assert_eq!(out.weights, vec![4]);
    }

    fn histogram_hands(rng: &mut Rng, n: usize, next_k: usize, outcomes: usize) -> Vec<u16> {
        // Hands of a few kinds: each kind draws its outcomes from its own narrow range.
        let mut labels = Vec::with_capacity(n * outcomes);
        for i in 0..n {
            let kind = i % 6;
            let base = kind * next_k / 6;
            let mut row: Vec<u16> = (0..outcomes)
                .map(|_| (base + rng.below((next_k / 8) as u64) as usize) as u16)
                .collect();
            if kind == 5 {
                // A drawing hand: mostly low, sometimes the top bucket.
                for x in row.iter_mut().take(outcomes / 5) {
                    *x = next_k as u16 - 1;
                }
                for x in row.iter_mut().skip(outcomes / 5) {
                    *x %= (next_k / 8) as u16;
                }
            }
            row.sort_unstable();
            labels.extend(row);
        }
        labels
    }

    /// With bounds or without, every hand must land on the same centre at the same cost.
    #[test]
    fn bounds_never_change_the_nearest_centre() {
        let mut rng = Rng::new(8);
        let (next_k, outcomes, n, k) = (40, 46, 3000, 25);
        let labels = histogram_hands(&mut rng, n, next_k, outcomes);
        let weights = vec![1u8; n];
        let pos: Vec<f32> = (0..next_k)
            .map(|i| (i as f32 / next_k as f32).powf(1.5))
            .collect();
        let pts: Vec<(f32, f32)> = (0..next_k)
            .map(|_| (rng.next_f64() as f32, rng.next_f64() as f32))
            .collect();
        let mut d = vec![0f32; next_k * next_k];
        for i in 0..next_k {
            for j in 0..i {
                let x = ((pts[i].0 - pts[j].0).powi(2) + (pts[i].1 - pts[j].1).powi(2)).sqrt();
                d[i * next_k + j] = x;
                d[j * next_k + i] = x;
            }
        }
        let embed: Vec<f32> = pts.iter().flat_map(|p| [p.0, p.1]).collect();
        for metric in [
            Metric::Line(Line::new(pos)),
            Metric::Matrix(Matrix::new(next_k, d.clone(), embed, 2)),
            Metric::Matrix(Matrix::new(next_k, d, Vec::new(), 0)),
        ] {
            let space = HistogramSpace {
                labels: &labels,
                outcomes,
                weights: &weights,
                metric: &metric,
            };
            let mut centroids = Vec::new();
            for c in 0..k {
                centroids.extend(centroid_of(&space, c * 97 % n));
            }
            let centers = space.centers(&centroids, k);
            let mut scratch = space.scratch();
            for i in 0..n {
                let (c, cost) = space.nearest(&centers, i, None, &mut scratch);
                let hinted = space.nearest(&centers, i, Some((i % k) as u32), &mut scratch);
                assert_eq!((c, cost), hinted, "hand {i}");
                let mut plain = (0u32, f32::INFINITY);
                for other in 0..k {
                    let x = space.cost(&centers, other, i, f32::INFINITY, &mut scratch);
                    if x < plain.1 {
                        plain = (other as u32, x);
                    }
                }
                assert_eq!((c, cost), plain, "hand {i}");
            }
        }
    }

    #[test]
    fn histograms_cluster_by_kind_and_the_draw_stands_apart() {
        let mut rng = Rng::new(21);
        let (next_k, outcomes, n) = (48, 46, 1200);
        let labels = histogram_hands(&mut rng, n, next_k, outcomes);
        let weights = vec![1u8; n];
        let metric = Metric::Line(Line::new(
            (0..next_k)
                .map(|i| i as f32 / (next_k - 1) as f32)
                .collect(),
        ));
        let space = HistogramSpace {
            labels: &labels,
            outcomes,
            weights: &weights,
            metric: &metric,
        };
        let out = kmeans(&space, 6, &KMeansSettings::default(), 7);
        assert_eq!(out.k, 6);
        for kind in 0..6 {
            let first = out.assignment[kind];
            assert!(
                (0..n)
                    .filter(|i| i % 6 == kind)
                    .all(|i| out.assignment[i] == first),
                "kind {kind}"
            );
        }
        // The draw (kind 5) has about the same average as kind 1 but is its own bucket.
        assert_ne!(out.assignment[5], out.assignment[1]);
        // Centres are histograms.
        for c in 0..6 {
            let sum: f32 = out.centroids[c * next_k..(c + 1) * next_k].iter().sum();
            assert!((sum - 1.0).abs() < 1e-4);
        }
        let d = centroid_distances(&metric, &out.centroids, out.k);
        for i in 0..6 {
            assert_eq!(d[i * 6 + i], 0.0);
            for j in 0..6 {
                assert_eq!(d[i * 6 + j], d[j * 6 + i]);
                assert!(i == j || d[i * 6 + j] > 0.0);
            }
        }
    }

    #[test]
    fn same_seed_same_buckets_with_one_thread_or_many() {
        let mut rng = Rng::new(77);
        let (next_k, outcomes, n) = (30, 46, 9000);
        let labels = histogram_hands(&mut rng, n, next_k, outcomes);
        let weights: Vec<u8> = (0..n).map(|i| [4u8, 12, 24][i % 3]).collect();
        let metric = Metric::Line(Line::new((0..next_k).map(|i| i as f32 / 29.0).collect()));
        let space = HistogramSpace {
            labels: &labels,
            outcomes,
            weights: &weights,
            metric: &metric,
        };
        let settings = KMeansSettings {
            train_samples: 4000,
            ..KMeansSettings::default()
        };
        let run = |threads: usize, seed: u64| {
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(threads)
                .build()
                .unwrap();
            pool.install(|| kmeans(&space, 12, &settings, seed))
        };
        let a = run(1, 5);
        let b = run(4, 5);
        let c = run(3, 5);
        assert_eq!(a.assignment, b.assignment);
        assert_eq!(a.centroids, b.centroids);
        assert_eq!(a.assignment, c.assignment);
        assert_eq!(a.cost, b.cost);
        assert!(a.trained_on <= 4000);
        // Another seed gives other buckets.
        let other = run(4, 6);
        assert_ne!(a.assignment, other.assignment);
    }
}
