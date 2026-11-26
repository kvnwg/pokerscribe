//! Building the tables, from the river back to the flop.
//!
//! - River: every canonical hand's equity against the opponent's possible hands, either as
//!   one number or as OCHS (the equity against each of a few groups of opponent hole cards),
//!   then k-means with straight-line distance.
//! - Turn: for every canonical hand, the histogram of river buckets over the 46 river cards,
//!   then k-means with earth mover's distance. The ground distance between two river buckets
//!   is the distance between their centres.
//! - Flop: the same over the 47 turn cards and the turn's buckets. The ground distance
//!   between two turn buckets is the earth mover's distance between their centres.
//! - Preflop: nothing to build, the 169 classes are used as they are.

use crate::deck::Deck;
use crate::emd::{Line, Matrix, Metric};
use crate::equity::Showdown;
use crate::isomorphism::{HandIndexer, Preflop};
use crate::kmeans::{
    centroid_distances, kmeans, sort_buckets, Clustering, HistogramSpace, KMeansSettings, VectorSpace, Weights,
};
use crate::rng::Rng;
use crate::table::{Feature, Header, MetricData, MetricKind, Street, StreetSettings, Table};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU16, Ordering::Relaxed};
use std::time::Instant;

/// Slices of equity used to describe a class of hole cards when grouping the opponent's
/// hands for OCHS.
pub const CLASS_EQUITY_BINS: usize = 50;
/// The whole number that stands for an equity of 1.0 in the OCHS features.
pub const OCHS_UNIT: u32 = 65_535;

/// Settings for all three tables.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Settings {
    /// Ranks in the deck: 13 for the real game.
    pub ranks: u8,
    /// The same seed and settings give the same tables.
    pub seed: u64,
    pub flop: StreetSettings,
    pub turn: StreetSettings,
    pub river: StreetSettings,
}

impl Settings {
    /// The default method with `buckets` buckets on each street: OCHS with 8 opponent
    /// groups on the river, potential-aware histograms on the turn and flop.
    pub fn new(buckets: u32) -> Settings {
        Settings {
            ranks: 13,
            seed: 1,
            flop: StreetSettings {
                buckets,
                feature: Feature::NextBuckets,
                kmeans: KMeansSettings::default(),
            },
            turn: StreetSettings {
                buckets,
                feature: Feature::NextBuckets,
                kmeans: KMeansSettings {
                    train_samples: 2_000_000,
                    init_samples: 200_000,
                    ..KMeansSettings::default()
                },
            },
            river: StreetSettings {
                buckets,
                feature: Feature::Ochs { clusters: 8 },
                kmeans: KMeansSettings {
                    train_samples: 4_000_000,
                    init_samples: 400_000,
                    ..KMeansSettings::default()
                },
            },
        }
    }

    pub fn street(&self, street: Street) -> &StreetSettings {
        match street {
            Street::Flop => &self.flop,
            Street::Turn => &self.turn,
            Street::River => &self.river,
            Street::Preflop => panic!("the preflop has no table"),
        }
    }

    pub fn deck(&self) -> Deck {
        Deck::new(self.ranks)
    }
}

/// What one street's build did and how long it took. Not stored in the table, so that the
/// same seed gives the same file.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Report {
    pub street: Street,
    pub hands: u64,
    pub buckets_asked: u32,
    pub buckets: u32,
    pub threads: usize,
    /// Seconds making what is clustered: equities and OCHS vectors, or histograms.
    pub features_seconds: f64,
    /// Seconds picking the first centres.
    pub seeding_seconds: f64,
    /// Seconds in Lloyd iterations on the training hands.
    pub iterating_seconds: f64,
    /// Seconds putting every hand in its bucket.
    pub assigning_seconds: f64,
    /// Seconds on the rest: bucket order, distances between buckets.
    pub finishing_seconds: f64,
    pub total_seconds: f64,
    pub iterations: u32,
    pub trained_on: u64,
    pub cost: f64,
    /// Share of hand-to-centre comparisons worked out in full in the last pass; the rest
    /// were ruled out by a lower bound.
    pub full_comparisons: f64,
    /// The file's size, filled in when the table is saved.
    pub file_bytes: u64,
    /// The process's peak memory so far in megabytes (Linux only, else 0).
    pub peak_memory_mb: f64,
    pub checksum: String,
}

/// The process's peak resident memory in bytes, from `/proc/self/status`. 0 where that file
/// doesn't exist (macOS).
pub fn peak_memory_bytes() -> u64 {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|s| {
            s.lines()
                .find(|l| l.starts_with("VmHWM:"))
                .and_then(|l| l.split_whitespace().nth(1).and_then(|kb| kb.parse::<u64>().ok()))
        })
        .map_or(0, |kb| kb * 1024)
}

/// A separate seed for each use of the build's seed.
fn sub_seed(seed: u64, tag: u64) -> u64 {
    Rng::stream(seed, tag).next_u64()
}

/// How many real hands each canonical hand stands for.
pub fn multiplicities(indexer: &HandIndexer) -> Vec<u8> {
    (0..indexer.size())
        .into_par_iter()
        .map(|i| indexer.multiplicity(i) as u8)
        .collect()
}

/// The opponent group (or anything else) of two hole cards, as a table read with
/// `table[a * 52 + b]` for `a < b`.
fn hole_table(deck: Deck, of_class: impl Fn(u16) -> u8) -> Vec<u8> {
    let preflop = Preflop::with_deck(deck);
    let mut table = vec![0u8; 52 * 52];
    for a in deck.cards() {
        for b in a + 1..52 {
            table[a as usize * 52 + b as usize] = of_class(preflop.class(a, b));
        }
    }
    table
}

/// Every canonical river hand's equity against a random hand, kept exactly.
pub struct RiverEquity {
    pub deck: Deck,
    /// Twice the wins plus the ties, for each canonical river hand.
    pub numerators: Vec<u16>,
    /// What to divide the numerators by: 1,980 in the full deck.
    pub denominator: u32,
    /// For each class of hole cards, how many deals fall in each slice of river equity:
    /// `class_histogram[class * CLASS_EQUITY_BINS + bin]`.
    pub class_histogram: Vec<u64>,
}

impl RiverEquity {
    /// The equity of a canonical river hand, 0 to 1.
    #[inline]
    pub fn equity(&self, index: u64) -> f32 {
        self.numerators[index as usize] as f32 / self.denominator as f32
    }

    /// The slice of equity, out of `bins`, that a numerator falls in.
    #[inline]
    pub fn bin(&self, numerator: u16, bins: u32) -> u16 {
        (numerator as u32 * bins / (self.denominator + 1)) as u16
    }
}

/// Runs `visit(showdown, board, board multiplicity)` for one board of every suit class, in
/// parallel. `groups` is the number of opponent groups the showdowns are split into.
fn for_each_board<T: Send>(
    deck: Deck,
    groups: usize,
    hole_groups: Option<&[u8]>,
    init: impl Fn() -> T + Sync + Send,
    visit: impl Fn(&mut T, &Showdown, &[u8; 5], u64) + Sync + Send,
    merge: impl Fn(T, T) -> T + Sync + Send,
) -> T {
    let boards = HandIndexer::with_deck(deck, &[5]);
    (0..boards.size())
        .into_par_iter()
        .fold(
            || (Showdown::new(deck, groups), init()),
            |(mut showdown, mut state), b| {
                let mut board = [0u8; 5];
                boards.unindex(b, &mut board);
                showdown.run(&board, hole_groups);
                visit(&mut state, &showdown, &board, boards.multiplicity(b) as u64);
                (showdown, state)
            },
        )
        .map(|(_, state)| state)
        .reduce(&init, &merge)
}

fn atomic_array(len: usize, value: u16) -> Vec<AtomicU16> {
    (0..len).into_par_iter().map(|_| AtomicU16::new(value)).collect()
}

fn plain_array(atomics: Vec<AtomicU16>) -> Vec<u16> {
    atomics.into_iter().map(AtomicU16::into_inner).collect()
}

/// Works out the equity of every canonical river hand: one board of each suit class, all
/// hole cards on it.
pub fn river_equity(deck: Deck) -> RiverEquity {
    let hands = HandIndexer::with_deck(deck, &[2, 5]);
    let classes = Preflop::with_deck(deck).classes();
    let class_of = {
        let preflop = Preflop::with_deck(deck);
        let mut table = vec![0u16; 52 * 52];
        for a in deck.cards() {
            for b in a + 1..52 {
                table[a as usize * 52 + b as usize] = preflop.class(a, b);
            }
        }
        table
    };
    let denominator = Showdown::equity_denominator(deck);
    let out = atomic_array(hands.size() as usize, u16::MAX);
    let class_histogram = for_each_board(
        deck,
        1,
        None,
        || vec![0u64; classes * CLASS_EQUITY_BINS],
        |histogram, showdown, board, multiplicity| {
            let mut cards = [0u8; 7];
            cards[2..].copy_from_slice(board);
            for (i, &[a, b]) in showdown.combos().iter().enumerate() {
                cards[0] = a;
                cards[1] = b;
                let numerator = showdown.equity_numerator(i);
                // Boards of different classes never give the same canonical hand, so no
                // two threads write the same entry.
                out[hands.index(&cards) as usize].store(numerator, Relaxed);
                let bin = numerator as usize * CLASS_EQUITY_BINS / (denominator as usize + 1);
                let class = class_of[a as usize * 52 + b as usize] as usize;
                histogram[class * CLASS_EQUITY_BINS + bin] += multiplicity;
            }
        },
        |mut a, b| {
            a.iter_mut().zip(&b).for_each(|(x, y)| *x += y);
            a
        },
    );
    let numerators = plain_array(out);
    assert!(
        numerators.par_iter().all(|&q| q as u32 <= denominator),
        "a canonical river hand was not reached"
    );
    RiverEquity {
        deck,
        numerators,
        denominator,
        class_histogram,
    }
}

/// Groups the classes of hole cards into `clusters` opponent groups for OCHS, by the
/// distribution of their river equity (k-means with earth mover's distance, as in Johanson
/// et al. 2013). Returns each class's group; group 0 holds the weakest hands.
pub fn opponent_clusters(equity: &RiverEquity, clusters: usize, seed: u64) -> Vec<u8> {
    const SAMPLES: usize = 512;
    let preflop = Preflop::with_deck(equity.deck);
    let classes = preflop.classes();
    // Each class as SAMPLES evenly spaced points of its equity distribution.
    let mut labels = Vec::with_capacity(classes * SAMPLES);
    for class in 0..classes {
        let row = &equity.class_histogram[class * CLASS_EQUITY_BINS..(class + 1) * CLASS_EQUITY_BINS];
        let total: u64 = row.iter().sum();
        let (mut bin, mut below) = (0usize, 0u64);
        for j in 0..SAMPLES {
            let target = ((2 * j as u128 + 1) * total as u128 / (2 * SAMPLES as u128)) as u64;
            while bin + 1 < CLASS_EQUITY_BINS && below + row[bin] <= target {
                below += row[bin];
                bin += 1;
            }
            labels.push(bin as u16);
        }
    }
    let weights: Vec<u8> = (0..classes).map(|c| preflop.combos(c as u16) as u8).collect();
    let pos: Vec<f32> = (0..CLASS_EQUITY_BINS)
        .map(|b| (b as f32 + 0.5) / CLASS_EQUITY_BINS as f32)
        .collect();
    let metric = Metric::Line(Line::new(pos.clone()));
    let space = HistogramSpace {
        labels: &labels,
        outcomes: SAMPLES,
        weights: &weights,
        metric: &metric,
    };
    let settings = KMeansSettings {
        max_iters: 200,
        tolerance: 0.0,
        restarts: 32,
        ..KMeansSettings::default()
    };
    let mut clustering = kmeans(&space, clusters.min(classes), &settings, seed);
    let mean_equity: Vec<f64> = (0..clustering.k)
        .map(|c| {
            clustering.centroids[c * CLASS_EQUITY_BINS..(c + 1) * CLASS_EQUITY_BINS]
                .iter()
                .zip(&pos)
                .map(|(&share, &p)| share as f64 * p as f64)
                .sum()
        })
        .collect();
    sort_buckets(&mut clustering, CLASS_EQUITY_BINS, &mean_equity);
    clustering.assignment.iter().map(|&c| c as u8).collect()
}

/// The OCHS vector of every canonical river hand: its equity against each opponent group,
/// `clusters` numbers per hand with [`OCHS_UNIT`] standing for 1.0. Where the board and the
/// hand leave the opponent no hand of a group, the equity against a random hand is used.
pub fn river_ochs(equity: &RiverEquity, class_cluster: &[u8], clusters: usize) -> Vec<u16> {
    let deck = equity.deck;
    let hands = HandIndexer::with_deck(deck, &[2, 5]);
    let groups = hole_table(deck, |class| class_cluster[class as usize]);
    let out = atomic_array(hands.size() as usize * clusters, 0);
    let denominator = equity.denominator;
    for_each_board(
        deck,
        clusters,
        Some(&groups),
        || (),
        |_, showdown, board, _| {
            let mut cards = [0u8; 7];
            cards[2..].copy_from_slice(board);
            for (i, &[a, b]) in showdown.combos().iter().enumerate() {
                cards[0] = a;
                cards[1] = b;
                let at = hands.index(&cards) as usize * clusters;
                let plain = showdown.equity_numerator(i) as u32;
                for g in 0..clusters {
                    let (num, den) = showdown.against_group(i, g);
                    let (num, den) = if den == 0 { (plain, denominator) } else { (num as u32, den as u32) };
                    let value = (num * OCHS_UNIT + den / 2) / den;
                    out[at + g].store(value as u16, Relaxed);
                }
            }
        },
        |_, _| (),
    );
    plain_array(out)
}

fn empty_header(deck: Deck, street: Street, settings: &StreetSettings, seed: u64, clustering: &Clustering) -> Header {
    Header {
        format: 0,
        built_by: String::new(),
        street,
        ranks: deck.ranks(),
        hands: 0,
        buckets: 0,
        bytes_per_bucket: 0,
        centroid_dim: 0,
        metric: MetricKind::None,
        embed_dim: 0,
        seed,
        settings: settings.clone(),
        built_from: String::new(),
        opponent_clusters: Vec::new(),
        iterations: clustering.iterations as u32,
        trained_on: clustering.trained_on as u64,
        cost: clustering.cost,
    }
}

fn report(
    street: Street,
    settings: &StreetSettings,
    table: &Table,
    clustering: &Clustering,
    features_seconds: f64,
    started: Instant,
) -> Report {
    let total = started.elapsed().as_secs_f64();
    let [seeding, iterating, assigning] = clustering.seconds;
    Report {
        street,
        hands: table.len(),
        buckets_asked: settings.buckets,
        buckets: table.buckets() as u32,
        threads: rayon::current_num_threads(),
        features_seconds,
        seeding_seconds: seeding,
        iterating_seconds: iterating,
        assigning_seconds: assigning,
        finishing_seconds: (total - features_seconds - seeding - iterating - assigning).max(0.0),
        total_seconds: total,
        iterations: clustering.iterations as u32,
        trained_on: clustering.trained_on as u64,
        cost: clustering.cost,
        full_comparisons: clustering.full_comparisons,
        file_bytes: 0,
        peak_memory_mb: peak_memory_bytes() as f64 / (1024.0 * 1024.0),
        checksum: table.checksum(),
    }
}

/// Builds the river table.
pub fn build_river(equity: &RiverEquity, settings: &StreetSettings, seed: u64) -> (Table, Report) {
    let started = Instant::now();
    let deck = equity.deck;
    let indexer = HandIndexer::with_deck(deck, &[2, 5]);
    let hands = indexer.size() as usize;
    let weights = multiplicities(&indexer);
    let k = settings.buckets as usize;

    // Twice-wins-plus-ties, times the hands it stands for, summed per bucket: exact.
    let equity_of_buckets = |assignment: &[u16], k: usize, sizes: &[u64]| -> Vec<f64> {
        let sums = (0..hands)
            .into_par_iter()
            .fold(
                || vec![0u64; k],
                |mut acc, i| {
                    acc[assignment[i] as usize] += weights[i] as u64 * equity.numerators[i] as u64;
                    acc
                },
            )
            .reduce(
                || vec![0u64; k],
                |mut a, b| {
                    a.iter_mut().zip(&b).for_each(|(x, y)| *x += y);
                    a
                },
            );
        (0..k)
            .map(|c| sums[c] as f64 / (sizes[c] as f64 * equity.denominator as f64))
            .collect()
    };

    let (clustering, bucket_equity, metric, opponent, features_seconds) = match settings.feature {
        Feature::Equity => {
            // Hands with the same equity are the same point: cluster the distinct values.
            let per_value = (0..hands)
                .into_par_iter()
                .fold(
                    || vec![0u64; equity.denominator as usize + 1],
                    |mut acc, i| {
                        acc[equity.numerators[i] as usize] += weights[i] as u64;
                        acc
                    },
                )
                .reduce(
                    || vec![0u64; equity.denominator as usize + 1],
                    |mut a, b| {
                        a.iter_mut().zip(&b).for_each(|(x, y)| *x += y);
                        a
                    },
                );
            let values: Vec<u16> = (0..per_value.len()).filter(|&q| per_value[q] > 0).map(|q| q as u16).collect();
            let value_weights: Vec<u64> = values.iter().map(|&q| per_value[q as usize]).collect();
            let features_seconds = started.elapsed().as_secs_f64();
            let space = VectorSpace {
                data: &values,
                dim: 1,
                unit: equity.denominator,
                weights: Weights::Large(&value_weights),
            };
            let mut small = kmeans(&space, k, &settings.kmeans, sub_seed(seed, 5));
            let key: Vec<f64> = small.centroids.iter().map(|&x| x as f64).collect();
            sort_buckets(&mut small, 1, &key);
            let mut bucket_of_value = vec![0u16; per_value.len()];
            for (at, &q) in values.iter().enumerate() {
                bucket_of_value[q as usize] = small.assignment[at];
            }
            let assignment: Vec<u16> = equity.numerators.par_iter().map(|&q| bucket_of_value[q as usize]).collect();
            let bucket_equity = equity_of_buckets(&assignment, small.k, &small.weights);
            let pos: Vec<f32> = bucket_equity.iter().map(|&e| e as f32).collect();
            let clustering = Clustering { assignment, ..small };
            (clustering, bucket_equity, MetricData::Line { pos }, Vec::new(), features_seconds)
        }
        Feature::Ochs { clusters } => {
            let class_cluster = opponent_clusters(equity, clusters as usize, sub_seed(seed, 4));
            let dim = class_cluster.iter().map(|&c| c as usize + 1).max().unwrap_or(1);
            let features = river_ochs(equity, &class_cluster, dim);
            let features_seconds = started.elapsed().as_secs_f64();
            let space = VectorSpace {
                data: &features,
                dim,
                unit: OCHS_UNIT,
                weights: Weights::Small(&weights),
            };
            let mut clustering = kmeans(&space, k, &settings.kmeans, sub_seed(seed, 5));
            drop(features);
            let k = clustering.k;
            let bucket_equity = equity_of_buckets(&clustering.assignment, k, &clustering.weights);
            let order = sort_buckets(&mut clustering, dim, &bucket_equity);
            let bucket_equity: Vec<f64> = order.iter().map(|&old| bucket_equity[old]).collect();
            // The ground distance between two river buckets: the straight-line distance
            // between their centres.
            let mut d = vec![0f32; k * k];
            for i in 0..k {
                for j in 0..i {
                    let sum: f64 = (0..dim)
                        .map(|t| {
                            let x = clustering.centroids[i * dim + t] as f64 - clustering.centroids[j * dim + t] as f64;
                            x * x
                        })
                        .sum();
                    d[i * k + j] = sum.sqrt() as f32;
                    d[j * k + i] = d[i * k + j];
                }
            }
            let metric = MetricData::Matrix {
                d,
                embed: clustering.centroids.clone(),
            };
            (clustering, bucket_equity, metric, class_cluster, features_seconds)
        }
        _ => panic!("the river is clustered by equity or OCHS"),
    };

    let mut header = empty_header(deck, Street::River, settings, seed, &clustering);
    header.built_from = "showdown equity".into();
    header.opponent_clusters = opponent;
    let table = Table::new(
        header,
        &clustering.assignment,
        clustering.weights.clone(),
        bucket_equity.iter().map(|&e| e as f32).collect(),
        clustering.centroids.clone(),
        metric,
    );
    let report = report(Street::River, settings, &table, &clustering, features_seconds, started);
    (table, report)
}

/// What a turn or flop hand's histogram is over.
pub enum NextLabels<'a> {
    /// The buckets of the next street's table.
    Table(&'a Table),
    /// Equal slices of river equity (turn only).
    EquityBins { equity: &'a RiverEquity, bins: u32 },
}

impl NextLabels<'_> {
    fn k(&self) -> usize {
        match self {
            NextLabels::Table(t) => t.buckets(),
            NextLabels::EquityBins { bins, .. } => *bins as usize,
        }
    }

    #[inline]
    fn label(&self, index: u64) -> u16 {
        match self {
            NextLabels::Table(t) => t.bucket(index),
            NextLabels::EquityBins { equity, bins } => equity.bin(equity.numerators[index as usize], *bins),
        }
    }

    fn metric(&self) -> Metric {
        match self {
            NextLabels::Table(t) => t
                .ground_metric()
                .expect("the next street's table has no distances between its buckets"),
            NextLabels::EquityBins { bins, .. } => {
                Metric::Line(Line::new((0..*bins).map(|b| (b as f32 + 0.5) / *bins as f32).collect()))
            }
        }
    }

    fn equity(&self) -> Vec<f32> {
        match self {
            NextLabels::Table(t) => t.equity.clone(),
            NextLabels::EquityBins { bins, .. } => (0..*bins).map(|b| (b as f32 + 0.5) / *bins as f32).collect(),
        }
    }

    fn source(&self) -> String {
        match self {
            NextLabels::Table(t) => format!("{} table {}", t.header.street.name(), t.checksum()),
            NextLabels::EquityBins { bins, .. } => format!("{bins} slices of river equity"),
        }
    }
}

/// Builds the turn or flop table from the next street's labels.
pub fn build_histogram_street(
    deck: Deck,
    street: Street,
    next: &NextLabels,
    settings: &StreetSettings,
    seed: u64,
) -> (Table, Report) {
    assert!(matches!(street, Street::Flop | Street::Turn));
    let started = Instant::now();
    let board = street.board_cards();
    let indexer = HandIndexer::with_deck(deck, &[2, board as u8]);
    let next_indexer = HandIndexer::with_deck(deck, &[2, board as u8 + 1]);
    if let NextLabels::Table(t) = next {
        assert_eq!(t.len(), next_indexer.size(), "the next street's table is for another deck or street");
    }
    let hands = indexer.size() as usize;
    let outcomes = deck.len() - 2 - board;
    let metric = next.metric();
    let next_k = next.k();
    let next_equity = next.equity();

    // The histogram of every canonical hand: the label of each card that can come.
    let mut labels = vec![0u16; hands * outcomes];
    let mut weights = vec![0u8; hands];
    labels
        .par_chunks_mut(outcomes)
        .zip(weights.par_iter_mut())
        .enumerate()
        .for_each(|(i, (row, weight))| {
            let mut hand = [0u8; 7];
            indexer.unindex(i as u64, &mut hand[..2 + board]);
            let used = hand[..2 + board].iter().fold(0u64, |m, &c| m | 1 << c);
            let mut at = 0;
            for c in deck.cards() {
                if used & (1 << c) == 0 {
                    hand[2 + board] = c;
                    row[at] = next.label(next_indexer.index(&hand[..3 + board]));
                    at += 1;
                }
            }
            row.sort_unstable();
            *weight = indexer.multiplicity(i as u64) as u8;
        });
    let features_seconds = started.elapsed().as_secs_f64();

    let space = HistogramSpace {
        labels: &labels,
        outcomes,
        weights: &weights,
        metric: &metric,
    };
    let tag = if street == Street::Turn { 6 } else { 7 };
    let mut clustering = kmeans(&space, settings.buckets as usize, &settings.kmeans, sub_seed(seed, tag));
    drop(labels);
    let k = clustering.k;

    // A bucket's equity: its centre's shares times the next street's bucket equities.
    let bucket_equity: Vec<f64> = (0..k)
        .map(|c| {
            clustering.centroids[c * next_k..(c + 1) * next_k]
                .iter()
                .zip(&next_equity)
                .map(|(&share, &e)| share as f64 * e as f64)
                .sum()
        })
        .collect();
    let order = sort_buckets(&mut clustering, next_k, &bucket_equity);
    let bucket_equity: Vec<f32> = order.iter().map(|&old| bucket_equity[old] as f32).collect();

    // The flop's buckets are the last to be clustered over, so only the turn needs the
    // distances between its buckets.
    let metric_data = if street == Street::Turn {
        let d = centroid_distances(&metric, &clustering.centroids, k);
        // Each bucket's point for the lower bound: the average, over its centre, of the
        // next street's points.
        let (next_embed, dim): (Vec<f32>, usize) = match &metric {
            Metric::Line(line) => (line.pos.clone(), 1),
            Metric::Matrix(Matrix { embed, embed_dim, .. }) => (embed.clone(), *embed_dim),
        };
        let mut embed = vec![0f32; k * dim];
        for c in 0..k {
            for t in 0..dim {
                embed[c * dim + t] = (0..next_k)
                    .map(|j| clustering.centroids[c * next_k + j] as f64 * next_embed[j * dim + t] as f64)
                    .sum::<f64>() as f32;
            }
        }
        MetricData::Matrix { d, embed }
    } else {
        MetricData::None
    };

    let mut header = empty_header(deck, street, settings, seed, &clustering);
    header.built_from = next.source();
    let table = Table::new(
        header,
        &clustering.assignment,
        clustering.weights.clone(),
        bucket_equity,
        clustering.centroids.clone(),
        metric_data,
    );
    let report = report(street, settings, &table, &clustering, features_seconds, started);
    (table, report)
}

/// Builds all three tables in memory: river, turn, flop. For small decks and tests; the
/// command-line tool builds the real tables one street at a time and saves each.
pub fn build_all(settings: &Settings) -> ([Table; 3], [Report; 3]) {
    let deck = settings.deck();
    let equity = river_equity(deck);
    let (river, river_report) = build_river(&equity, &settings.river, settings.seed);
    let (turn, turn_report) = {
        let next = match settings.turn.feature {
            Feature::NextBuckets => NextLabels::Table(&river),
            Feature::EquityBins { bins } => NextLabels::EquityBins {
                equity: &equity,
                bins: bins as u32,
            },
            _ => panic!("the turn is clustered over river buckets or slices of river equity"),
        };
        build_histogram_street(deck, Street::Turn, &next, &settings.turn, settings.seed)
    };
    assert!(
        settings.flop.feature == Feature::NextBuckets,
        "the flop is clustered over turn buckets"
    );
    let (flop, flop_report) =
        build_histogram_street(deck, Street::Flop, &NextLabels::Table(&turn), &settings.flop, settings.seed);
    ([flop, turn, river], [flop_report, turn_report, river_report])
}
