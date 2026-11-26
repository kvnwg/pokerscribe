//! Earth mover's distance between histograms over the next street's buckets.
//!
//! The distance between two histograms is the least work that turns one into the other,
//! where moving a share `m` of the hands from bucket `i` to bucket `j` costs `m * d(i, j)`.
//! `d` is the *ground distance* between next-street buckets, a [`Metric`]:
//!
//! - [`Line`]: the buckets sit on a line (river buckets made from plain equity, or equity
//!   bins). The distance is exact and cheap: the area between the two cumulative curves.
//! - [`Matrix`]: any distances (river buckets made from OCHS vectors, turn buckets). An
//!   exact answer needs a transport problem solved for every pair, which is far too slow for
//!   k-means, so [`Matrix::greedy`] is the approximation of Ganzfried and Sandholm (2014,
//!   "Potential-aware imperfect-recall abstraction with earth mover's distance in
//!   imperfect-information games", Algorithm 2). It builds a real transport plan, so it is
//!   never below the true distance.
//!
//! k-means compares each hand with every centre. Most of those comparisons are skipped
//! with a lower bound: for any function `f` on the buckets with
//! `|f(i) - f(j)| <= d(i, j)`, the two histograms' averages of `f` differ by at most their
//! earth mover's distance. See [`Matrix::sketch`].

use rayon::prelude::*;

/// Ground distance between the buckets of the next street.
#[derive(Clone, Debug)]
pub enum Metric {
    Line(Line),
    Matrix(Matrix),
}

impl Metric {
    /// Number of buckets.
    pub fn k(&self) -> usize {
        match self {
            Metric::Line(l) => l.pos.len(),
            Metric::Matrix(m) => m.k,
        }
    }

    /// Ground distance between two buckets.
    pub fn distance(&self, i: usize, j: usize) -> f32 {
        match self {
            Metric::Line(l) => (l.pos[i] - l.pos[j]).abs(),
            Metric::Matrix(m) => m.d[i * m.k + j],
        }
    }
}

/// Buckets on a line, at `pos[i]`, in increasing order.
#[derive(Clone, Debug)]
pub struct Line {
    pub pos: Vec<f32>,
}

impl Line {
    pub fn new(pos: Vec<f32>) -> Line {
        assert!(pos.windows(2).all(|w| w[0] <= w[1]), "positions must not decrease");
        Line { pos }
    }

    /// The gap from bucket `i` to bucket `i + 1`.
    #[inline]
    pub fn gap(&self, i: usize) -> f32 {
        self.pos[i + 1] - self.pos[i]
    }

    /// Exact earth mover's distance between two histograms that each sum to 1.
    pub fn emd(&self, a: &[f32], b: &[f32]) -> f32 {
        let (mut ca, mut cb, mut total) = (0f64, 0f64, 0f64);
        for i in 0..self.pos.len().saturating_sub(1) {
            ca += a[i] as f64;
            cb += b[i] as f64;
            total += (ca - cb).abs() * self.gap(i) as f64;
        }
        total as f32
    }
}

/// How many extra anchor buckets the lower bound uses.
const ANCHORS: usize = 12;
/// Flow below this is rounding noise.
const FLOW_EPS: f32 = 1e-6;

/// Any ground distance, as a full table.
#[derive(Clone, Debug)]
pub struct Matrix {
    pub k: usize,
    /// `d[i * k + j]`, symmetric, zero on the diagonal, obeying the triangle inequality.
    pub d: Vec<f32>,
    /// Each bucket's point in a space of `embed_dim` dimensions, such that the straight-line
    /// distance between two buckets' points is at most `d`. Used for the lower bound.
    pub embed: Vec<f32>,
    pub embed_dim: usize,
    /// For bucket `i`, the buckets from nearest to farthest: `order[i * k + r]`.
    order: Vec<u16>,
    /// The matching distances: `sorted[i * k + r] = d(i, order[i * k + r])`.
    sorted: Vec<f32>,
    /// Anchor buckets: the distance to an anchor is a function that changes by at most `d`
    /// between two buckets.
    anchors: Vec<u16>,
}

/// Scratch space for [`Matrix::greedy`].
#[derive(Default)]
pub struct GreedyScratch {
    used: Vec<f32>,
    touched: Vec<u16>,
    need: Vec<f32>,
    active: Vec<u16>,
}

impl Matrix {
    /// `d` is `k * k` distances; `embed` is `k * embed_dim` coordinates (may be empty).
    /// Panics if `d` is not symmetric with a zero diagonal.
    pub fn new(k: usize, d: Vec<f32>, embed: Vec<f32>, embed_dim: usize) -> Matrix {
        assert!(k >= 1 && k <= u16::MAX as usize);
        assert_eq!(d.len(), k * k);
        assert_eq!(embed.len(), k * embed_dim);
        for i in 0..k {
            assert_eq!(d[i * k + i], 0.0, "distance from a bucket to itself");
            for j in 0..i {
                assert_eq!(d[i * k + j], d[j * k + i], "distances must be symmetric");
            }
        }
        let mut order = vec![0u16; k * k];
        let mut sorted = vec![0f32; k * k];
        order
            .par_chunks_mut(k)
            .zip(sorted.par_chunks_mut(k))
            .enumerate()
            .for_each(|(i, (order, sorted))| {
                let row = &d[i * k..(i + 1) * k];
                let mut by_distance: Vec<u16> = (0..k as u16).collect();
                // The bucket itself first, then by distance, then by number.
                by_distance.sort_by(|&a, &b| {
                    let key = |j: u16| (j as usize != i, row[j as usize], j);
                    key(a).partial_cmp(&key(b)).expect("distances are numbers")
                });
                for (r, &j) in by_distance.iter().enumerate() {
                    order[r] = j;
                    sorted[r] = row[j as usize];
                }
            });

        // Anchors: start from the bucket farthest from bucket 0, then keep taking the bucket
        // farthest from the anchors so far.
        let mut anchors: Vec<u16> = Vec::new();
        let mut nearest_anchor = d[..k].to_vec();
        while anchors.len() < ANCHORS.min(k) {
            let (far, &dist) = nearest_anchor
                .iter()
                .enumerate()
                .max_by(|a, b| a.1.partial_cmp(b.1).unwrap().then(b.0.cmp(&a.0)))
                .unwrap();
            if dist <= 0.0 && !anchors.is_empty() {
                break;
            }
            anchors.push(far as u16);
            for j in 0..k {
                let dj = d[far * k + j];
                if anchors.len() == 1 || dj < nearest_anchor[j] {
                    nearest_anchor[j] = dj;
                }
            }
        }
        Matrix {
            k,
            d,
            embed,
            embed_dim,
            order,
            sorted,
            anchors,
        }
    }

    /// Length of a [`Matrix::sketch`].
    pub fn sketch_len(&self) -> usize {
        self.embed_dim + self.anchors.len()
    }

    /// The numbers the lower bound compares, for a histogram given as `(bucket, share)`
    /// pairs: its average point in the embedding, then its average distance to each anchor.
    pub fn sketch(&self, entries: impl Iterator<Item = (usize, f32)> + Clone, out: &mut [f32]) {
        out.fill(0.0);
        let (coords, to_anchor) = out.split_at_mut(self.embed_dim);
        for (b, share) in entries {
            for (o, &x) in coords.iter_mut().zip(&self.embed[b * self.embed_dim..]) {
                *o += share * x;
            }
            for (o, &a) in to_anchor.iter_mut().zip(&self.anchors) {
                *o += share * self.d[a as usize * self.k + b];
            }
        }
    }

    /// A number that the earth mover's distance between two histograms can't be below,
    /// from their sketches.
    pub fn lower_bound(&self, a: &[f32], b: &[f32]) -> f32 {
        let mut straight = 0f32;
        for t in 0..self.embed_dim {
            straight += (a[t] - b[t]) * (a[t] - b[t]);
        }
        let mut bound = straight.sqrt();
        for t in self.embed_dim..a.len() {
            bound = bound.max((a[t] - b[t]).abs());
        }
        bound
    }

    /// Ganzfried and Sandholm's approximate earth mover's distance from a hand's histogram
    /// (`buckets[e]` holding a share `shares[e]`, all shares adding to 1) to a centre
    /// `mean` (a full histogram adding to 1).
    ///
    /// In round `r` each bucket of the hand that still has hands to place sends as many
    /// as fit to its `r`-th nearest bucket of the centre. Round 0 is the bucket itself, at
    /// no cost. The result is the cost of a real plan, so it is at least the true distance.
    ///
    /// Stops early and returns a number at or above `bound` once the cost reaches it.
    pub fn greedy(
        &self,
        buckets: &[u16],
        shares: &[f32],
        mean: &[f32],
        bound: f32,
        scratch: &mut GreedyScratch,
    ) -> f32 {
        let k = self.k;
        debug_assert_eq!(mean.len(), k);
        debug_assert_eq!(buckets.len(), shares.len());
        if scratch.used.len() != k {
            scratch.used.clear();
            scratch.used.resize(k, 0.0);
        }
        scratch.need.clear();
        scratch.need.extend_from_slice(shares);
        scratch.active.clear();
        scratch.active.extend(0..buckets.len() as u16);
        scratch.touched.clear();

        let mut total = 0f32;
        for r in 0..k {
            let mut kept = 0;
            for at in 0..scratch.active.len() {
                let e = scratch.active[at] as usize;
                let row = buckets[e] as usize * k + r;
                let j = self.order[row] as usize;
                let free = mean[j] - scratch.used[j];
                if free > FLOW_EPS {
                    let need = scratch.need[e];
                    let flow = free.min(need);
                    total += flow * self.sorted[row];
                    if scratch.used[j] == 0.0 {
                        scratch.touched.push(j as u16);
                    }
                    scratch.used[j] += flow;
                    scratch.need[e] = need - flow;
                    if need - flow <= FLOW_EPS {
                        continue;
                    }
                }
                scratch.active[kept] = e as u16;
                kept += 1;
            }
            scratch.active.truncate(kept);
            if kept == 0 || total >= bound {
                break;
            }
        }
        for &j in &scratch.touched {
            scratch.used[j as usize] = 0.0;
        }
        total
    }

    /// [`Matrix::greedy`] between two full histograms, the smaller of the two directions.
    pub fn greedy_between(&self, a: &[f32], b: &[f32], scratch: &mut GreedyScratch) -> f32 {
        let split = |h: &[f32]| -> (Vec<u16>, Vec<f32>) {
            h.iter()
                .enumerate()
                .filter(|(_, &x)| x > 0.0)
                .map(|(i, &x)| (i as u16, x))
                .unzip()
        };
        let (ab, ash) = split(a);
        let (bb, bsh) = split(b);
        let forward = self.greedy(&ab, &ash, b, f32::INFINITY, scratch);
        let backward = self.greedy(&bb, &bsh, a, f32::INFINITY, scratch);
        forward.min(backward)
    }
}

/// Replaces each distance by the shortest route between the two buckets through other
/// buckets, which makes the triangle inequality hold. Distances can only shrink.
///
/// The greedy distances between centres are upper bounds on the true distances, and the
/// true distances obey the triangle inequality, so the shortened distances are still upper
/// bounds and closer to the truth.
pub fn shortest_paths(d: &mut [f32], k: usize) {
    assert_eq!(d.len(), k * k);
    let mut via = vec![0f32; k];
    for m in 0..k {
        via.copy_from_slice(&d[m * k..(m + 1) * k]);
        d.par_chunks_mut(k).for_each(|row| {
            let to_m = row[m];
            for (x, &v) in row.iter_mut().zip(&via) {
                let through = to_m + v;
                if through < *x {
                    *x = through;
                }
            }
        });
    }
}

/// Exact earth mover's distance between two histograms of whole counts with the same
/// total, for any ground distance. The result is in ground-distance units per hand (the
/// total cost divided by the total count).
///
/// It solves the transport problem by sending flow along cheapest paths. It is slow, and
/// is here to check the fast distances in tests and to measure how far the greedy
/// distance is from the truth.
pub fn exact(a: &[u64], b: &[u64], d: impl Fn(usize, usize) -> f64) -> f64 {
    let total: u64 = a.iter().sum();
    assert_eq!(total, b.iter().sum::<u64>(), "the histograms must have the same total");
    if total == 0 {
        return 0.0;
    }
    let from: Vec<usize> = (0..a.len()).filter(|&i| a[i] > 0).collect();
    let to: Vec<usize> = (0..b.len()).filter(|&j| b[j] > 0).collect();
    let (n, m) = (from.len(), to.len());
    let mut supply: Vec<u64> = from.iter().map(|&i| a[i]).collect();
    let mut demand: Vec<u64> = to.iter().map(|&j| b[j]).collect();
    let cost: Vec<f64> = from
        .iter()
        .flat_map(|&i| to.iter().map(move |&j| (i, j)))
        .map(|(i, j)| d(i, j))
        .collect();
    let mut flow = vec![0u64; n * m];
    // Node potentials keep every usable edge's adjusted cost at zero or above. Nodes
    // 0..n are sources, n..n+m are sinks.
    let mut potential = vec![0f64; n + m];
    let mut work = 0f64;
    let mut left = total;
    while left > 0 {
        // Cheapest paths from every source that still has supply.
        let mut dist = vec![f64::INFINITY; n + m];
        let mut parent = vec![usize::MAX; n + m];
        let mut done = vec![false; n + m];
        for i in 0..n {
            if supply[i] > 0 {
                dist[i] = 0.0;
            }
        }
        let mut end = usize::MAX;
        loop {
            let mut u = usize::MAX;
            for v in 0..n + m {
                if !done[v] && dist[v].is_finite() && (u == usize::MAX || dist[v] < dist[u]) {
                    u = v;
                }
            }
            if u == usize::MAX {
                break;
            }
            done[u] = true;
            if u >= n && demand[u - n] > 0 {
                end = u;
                break;
            }
            if u < n {
                for j in 0..m {
                    let v = n + j;
                    let step = (cost[u * m + j] + potential[u] - potential[v]).max(0.0);
                    if !done[v] && dist[u] + step < dist[v] {
                        dist[v] = dist[u] + step;
                        parent[v] = u;
                    }
                }
            } else {
                let j = u - n;
                for i in 0..n {
                    if flow[i * m + j] > 0 {
                        let step = (-cost[i * m + j] + potential[u] - potential[i]).max(0.0);
                        if !done[i] && dist[u] + step < dist[i] {
                            dist[i] = dist[u] + step;
                            parent[i] = u;
                        }
                    }
                }
            }
        }
        assert!(end != usize::MAX, "no path left although hands remain");
        let reach = dist[end];
        for v in 0..n + m {
            potential[v] += dist[v].min(reach);
        }
        // How much fits along the path.
        let mut amount = demand[end - n];
        let mut v = end;
        while parent[v] != usize::MAX {
            let u = parent[v];
            if u >= n {
                amount = amount.min(flow[v * m + (u - n)]);
            }
            v = u;
        }
        amount = amount.min(supply[v]);
        // Send it.
        let mut v = end;
        while parent[v] != usize::MAX {
            let u = parent[v];
            if u < n {
                flow[u * m + (v - n)] += amount;
                work += amount as f64 * cost[u * m + (v - n)];
            } else {
                flow[v * m + (u - n)] -= amount;
                work -= amount as f64 * cost[v * m + (u - n)];
            }
            v = u;
        }
        supply[v] -= amount;
        demand[end - n] -= amount;
        left -= amount;
    }
    work / total as f64
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;

    fn random_counts(rng: &mut Rng, k: usize, total: u64, spread: usize) -> Vec<u64> {
        let mut h = vec![0u64; k];
        let centre = rng.below(k as u64) as usize;
        for _ in 0..total {
            let off = rng.below(spread as u64) as usize;
            h[(centre + off) % k] += 1;
        }
        h
    }

    fn shares(h: &[u64]) -> Vec<f32> {
        let total: u64 = h.iter().sum();
        h.iter().map(|&x| x as f32 / total as f32).collect()
    }

    /// Points in the plane with straight-line distances: a true metric that is not a line.
    fn plane_metric(rng: &mut Rng, k: usize) -> Matrix {
        let pts: Vec<(f32, f32)> = (0..k).map(|_| (rng.next_f64() as f32, rng.next_f64() as f32)).collect();
        let mut d = vec![0f32; k * k];
        for i in 0..k {
            for j in 0..i {
                let x = ((pts[i].0 - pts[j].0).powi(2) + (pts[i].1 - pts[j].1).powi(2)).sqrt();
                d[i * k + j] = x;
                d[j * k + i] = x;
            }
        }
        let embed = pts.iter().flat_map(|p| [p.0, p.1]).collect();
        Matrix::new(k, d, embed, 2)
    }

    #[test]
    fn exact_matches_small_cases_by_hand() {
        // One hand moved two buckets along a line with unit gaps costs 2, per 4 hands 0.5.
        let d = |i: usize, j: usize| (i as f64 - j as f64).abs();
        assert_eq!(exact(&[4, 0, 0], &[3, 0, 1], d), 0.5);
        assert_eq!(exact(&[1, 1, 1], &[1, 1, 1], d), 0.0);
        assert_eq!(exact(&[2, 0, 0], &[0, 0, 2], d), 2.0);
        // Crossing is never needed on a line: [1,0,1] to [0,2,0] costs 1 per hand.
        assert_eq!(exact(&[1, 0, 1], &[0, 2, 0], d), 1.0);
    }

    #[test]
    fn line_distance_equals_the_exact_distance() {
        let mut rng = Rng::new(11);
        for _ in 0..300 {
            let k = 2 + rng.below(30) as usize;
            let mut pos: Vec<f32> = (0..k).map(|_| rng.next_f64() as f32).collect();
            pos.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let line = Line::new(pos.clone());
            let a = random_counts(&mut rng, k, 46, k);
            let b = random_counts(&mut rng, k, 46, k);
            let fast = line.emd(&shares(&a), &shares(&b)) as f64;
            let slow = exact(&a, &b, |i, j| (pos[i] as f64 - pos[j] as f64).abs());
            assert!((fast - slow).abs() < 1e-5, "{fast} against {slow}");
        }
    }

    #[test]
    fn greedy_is_between_the_lower_bound_and_twice_sanity() {
        let mut rng = Rng::new(5);
        let mut scratch = GreedyScratch::default();
        let (mut sum_exact, mut sum_greedy) = (0.0, 0.0);
        for _ in 0..200 {
            let k = 5 + rng.below(40) as usize;
            let metric = plane_metric(&mut rng, k);
            let a = random_counts(&mut rng, k, 46, 1 + k / 3);
            let b = random_counts(&mut rng, k, 460, 1 + k / 2);
            let a10: Vec<u64> = a.iter().map(|x| x * 10).collect();
            let truth = exact(&a10, &b, |i, j| metric.d[i * k + j] as f64);
            let (sa, sb) = (shares(&a), shares(&b));
            let (buckets, hand): (Vec<u16>, Vec<f32>) = sa
                .iter()
                .enumerate()
                .filter(|(_, &x)| x > 0.0)
                .map(|(i, &x)| (i as u16, x))
                .unzip();
            let greedy = metric.greedy(&buckets, &hand, &sb, f32::INFINITY, &mut scratch) as f64;
            assert!(greedy >= truth - 1e-4, "greedy {greedy} below exact {truth}");
            let mut ska = vec![0f32; metric.sketch_len()];
            let mut skb = vec![0f32; metric.sketch_len()];
            metric.sketch(sa.iter().cloned().enumerate(), &mut ska);
            metric.sketch(sb.iter().cloned().enumerate(), &mut skb);
            let low = metric.lower_bound(&ska, &skb) as f64;
            assert!(low <= truth + 1e-4, "lower bound {low} above exact {truth}");
            // The early exit never reports less than the bound it was given.
            let cut = metric.greedy(&buckets, &hand, &sb, (greedy * 0.5) as f32, &mut scratch) as f64;
            assert!(cut >= greedy * 0.5 - 1e-6 || cut == greedy);
            sum_exact += truth;
            sum_greedy += greedy;
        }
        // On these random cases the greedy plan costs a little more than the best plan.
        assert!(sum_greedy < 1.5 * sum_exact, "greedy {sum_greedy} exact {sum_exact}");
    }

    #[test]
    fn greedy_is_zero_for_the_same_histogram_and_leaves_the_scratch_clean() {
        let mut rng = Rng::new(9);
        let metric = plane_metric(&mut rng, 20);
        let mut scratch = GreedyScratch::default();
        let h = shares(&random_counts(&mut rng, 20, 46, 8));
        assert_eq!(metric.greedy_between(&h, &h, &mut scratch), 0.0);
        assert!(scratch.used.iter().all(|&x| x == 0.0));
        let other = shares(&random_counts(&mut rng, 20, 46, 8));
        let once = metric.greedy_between(&h, &other, &mut scratch);
        let twice = metric.greedy_between(&h, &other, &mut scratch);
        assert_eq!(once, twice);
        assert!(once > 0.0);
    }

    #[test]
    fn shortest_paths_restore_the_triangle_inequality() {
        // 0 to 2 costs 10 directly but 2 through bucket 1.
        let mut d = vec![0.0, 1.0, 10.0, 1.0, 0.0, 1.0, 10.0, 1.0, 0.0];
        shortest_paths(&mut d, 3);
        assert_eq!(d, vec![0.0, 1.0, 2.0, 1.0, 0.0, 1.0, 2.0, 1.0, 0.0]);
    }

    #[test]
    fn neighbours_start_with_the_bucket_itself() {
        let mut rng = Rng::new(3);
        let m = plane_metric(&mut rng, 15);
        for i in 0..15 {
            assert_eq!(m.order[i * 15] as usize, i);
            assert!(m.sorted[i * 15..(i + 1) * 15].windows(2).all(|w| w[0] <= w[1]));
        }
        assert!(m.sketch_len() >= 3);
    }
}
