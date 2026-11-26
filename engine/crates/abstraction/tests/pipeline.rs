//! The whole build on small decks, where it takes a second or two: that the buckets group
//! hands sensibly, that the same seed gives the same tables, and that tables come back from
//! disk as they were written.
//!
//! The decks are the top 5 ranks (tens to aces, 20 cards) and the top 6 (nines to aces,
//! 24 cards). The real deck's tables are checked by `tests/real_deck.rs`.
//!
//! Three of these tests take a minute in a debug build and run only with `--release`.

use abstraction::builder::{self, NextEquity, NextLabels, RiverEquity, Settings};
use abstraction::kmeans::KMeansSettings;
use abstraction::rng::Rng;
use abstraction::table::{Feature, StreetSettings};
use abstraction::{parse_cards, Abstraction, Deck, HandIndexer, Street, Table};
use std::path::PathBuf;

fn small(ranks: u8, buckets: u32) -> Settings {
    let mut s = Settings::new(buckets);
    s.ranks = ranks;
    s
}

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/small")
}

/// `n` choose `k`.
fn choose(n: u64, k: u64) -> u64 {
    (0..k).fold(1, |r, i| r * (n - i) / (i + 1))
}

/// A canonical hand's cards.
fn hand_of(indexer: &HandIndexer, index: u64) -> Vec<u8> {
    let mut cards = vec![0u8; indexer.cards()];
    indexer.unindex(index, &mut cards);
    cards
}

/// The mean and the spread (standard deviation) of a turn or flop hand's equity one card
/// later, from exact river equities. For the flop the "equity one card later" of a turn
/// hand is its mean river equity.
struct Outlook {
    mean: Vec<f64>,
    spread: Vec<f64>,
    weight: Vec<f64>,
}

fn outlook(deck: Deck, board: usize, next_value: &dyn Fn(u64) -> f64) -> Outlook {
    let indexer = HandIndexer::with_deck(deck, &[2, board as u8]);
    let next = HandIndexer::with_deck(deck, &[2, board as u8 + 1]);
    let n = indexer.size();
    let mut out = Outlook {
        mean: Vec::new(),
        spread: Vec::new(),
        weight: Vec::new(),
    };
    for i in 0..n {
        let mut cards = hand_of(&indexer, i);
        cards.push(0);
        let (mut sum, mut squares, mut count) = (0.0, 0.0, 0.0);
        for c in deck.cards() {
            if cards[..2 + board].contains(&c) {
                continue;
            }
            cards[2 + board] = c;
            let v = next_value(next.index(&cards));
            sum += v;
            squares += v * v;
            count += 1.0;
        }
        let mean = sum / count;
        out.mean.push(mean);
        out.spread.push((squares / count - mean * mean).max(0.0).sqrt());
        out.weight.push(indexer.multiplicity(i) as f64);
    }
    out
}

/// How much of the variation of `value` the buckets explain: 1 minus the variance inside
/// buckets over the total variance.
fn explained(value: &[f64], weight: &[f64], bucket: &dyn Fn(usize) -> usize, k: usize) -> f64 {
    let mut sums = vec![(0.0, 0.0, 0.0); k]; // weight, sum, sum of squares
    let mut all = (0.0, 0.0, 0.0);
    for i in 0..value.len() {
        let (w, v) = (weight[i], value[i]);
        let s = &mut sums[bucket(i)];
        s.0 += w;
        s.1 += w * v;
        s.2 += w * v * v;
        all.0 += w;
        all.1 += w * v;
        all.2 += w * v * v;
    }
    let total = all.2 - all.1 * all.1 / all.0;
    let inside: f64 = sums.iter().filter(|s| s.0 > 0.0).map(|s| s.2 - s.1 * s.1 / s.0).sum();
    1.0 - inside / total
}

/// Buckets made from the mean alone: `k` slices holding the same number of hands each.
fn slices_by_mean(mean: &[f64], weight: &[f64], k: usize) -> Vec<usize> {
    let mut order: Vec<usize> = (0..mean.len()).collect();
    order.sort_by(|&a, &b| mean[a].partial_cmp(&mean[b]).unwrap().then(a.cmp(&b)));
    let total: f64 = weight.iter().sum();
    let mut bucket = vec![0usize; mean.len()];
    let mut below = 0.0;
    for i in order {
        bucket[i] = ((below / total * k as f64) as usize).min(k - 1);
        below += weight[i];
    }
    bucket
}

#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn same_seed_same_tables_whatever_the_thread_count() {
    let settings = small(5, 10);
    let build = |threads: usize, settings: &Settings| {
        let pool = rayon::ThreadPoolBuilder::new().num_threads(threads).build().unwrap();
        let (tables, _) = pool.install(|| builder::build_all(settings));
        tables.map(|t| t.to_bytes())
    };
    let one = build(1, &settings);
    let four = build(4, &settings);
    let again = build(4, &settings);
    assert!(one == four, "1 thread and 4 threads gave different tables");
    assert!(four == again, "two runs gave different tables");

    let mut other = settings.clone();
    other.seed = 2;
    let other = build(4, &other);
    for street in 0..3 {
        assert!(other[street] != four[street], "another seed gave the same table");
    }
}

/// The river on the 24-card deck, with both kinds of feature.
#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn river_buckets_follow_equity() {
    let deck = Deck::new(6);
    let equity = builder::river_equity(deck);
    let indexer = HandIndexer::with_deck(deck, &[2, 5]);
    assert_eq!(equity.numerators.len() as u64, indexer.size());
    let weights = builder::multiplicities(&indexer);
    let raw_hands = choose(24, 2) * choose(22, 5);

    for feature in [Feature::Ochs { clusters: 8 }, Feature::Equity] {
        let settings = StreetSettings {
            buckets: 30,
            feature: feature.clone(),
            kmeans: KMeansSettings::default(),
        };
        let (table, report) = builder::build_river(&equity, &settings, 3);
        assert_eq!(table.buckets(), 30, "{feature:?}");
        assert_eq!(report.buckets, 30);
        assert_eq!(table.sizes.iter().sum::<u64>(), raw_hands);
        assert!(table.equity.windows(2).all(|w| w[0] <= w[1]), "buckets are numbered by equity");

        // A hand's equity is close to its bucket's, and the best and worst hands sit in
        // the best and worst buckets.
        let (mut squares, mut total) = (0.0, 0.0);
        for i in 0..indexer.size() {
            let own = equity.equity(i) as f64;
            let bucket = table.equity[table.bucket(i) as usize] as f64;
            let w = weights[i as usize] as f64;
            squares += w * (own - bucket) * (own - bucket);
            total += w;
            if own >= 0.99 {
                assert!(bucket >= 0.9, "{feature:?}: a hand with equity {own} is in a bucket with {bucket}");
            }
            if own <= 0.01 {
                assert!(bucket <= 0.1, "{feature:?}: a hand with equity {own} is in a bucket with {bucket}");
            }
        }
        let rms = (squares / total).sqrt();
        let limit = if feature == Feature::Equity { 0.02 } else { 0.08 };
        assert!(rms < limit, "{feature:?}: equity is {rms} from the bucket's on average");

        // The nuts and the near-nuts share a bucket; air sits far below.
        let bucket = |hole: &str, board: &str| {
            let mut cards = parse_cards(hole).unwrap();
            cards.extend(parse_cards(board).unwrap());
            table.bucket(indexer.index(&cards))
        };
        let board = "AhKhQh9c9d";
        let royal = bucket("JhTh", board);
        let quads = bucket("9h9s", board);
        let aces_full = bucket("AsAd", board);
        let air = bucket("JcTd", "AsAhKsKhQd"); // plays the board, and so does everyone
        let weak = bucket("TcTd", "AhKhQh9c9d"); // two pair, tens and nines
        assert_eq!(royal as usize, table.buckets() - 1, "{feature:?}: the royal flush is in the top bucket");
        if feature == Feature::Equity {
            // With one number per hand and 30 buckets, the top bucket is the hands that
            // never lose; quads lose to the royal flush and are one bucket down.
            assert!(royal - quads <= 1, "{feature:?}: quads next to the royal flush");
        } else {
            assert_eq!(royal, quads, "{feature:?}: the nuts and the near-nuts share a bucket");
        }
        assert!(table.equity[quads as usize] > 0.9, "{feature:?}");
        assert!(table.equity[aces_full as usize] > 0.9, "{feature:?}");
        assert!(table.equity[weak as usize] < 0.5, "{feature:?}");
        assert!(weak < royal && air < royal);
        // The same hand in other suits is the same hand.
        assert_eq!(royal, bucket("JsTs", "AsKsQs9h9c"));
    }
}

/// The average earth mover's distance from a hand's histogram to the mean histogram of its
/// bucket, for any way of putting the street's hands in `k` buckets. This is what k-means
/// makes small.
fn histogram_cost(deck: Deck, street: Street, next: &Table, bucket: &dyn Fn(usize) -> usize, k: usize) -> f64 {
    use abstraction::emd::{GreedyScratch, Metric};
    let board = street.board_cards() as u8;
    let indexer = HandIndexer::with_deck(deck, &[2, board]);
    let next_indexer = HandIndexer::with_deck(deck, &[2, board + 1]);
    let labels = NextLabels::Table(next);
    let metric = labels.metric();
    let (outcomes, next_k) = (deck.len() - 2 - board as usize, next.buckets());
    let n = indexer.size() as usize;
    let mut rows = vec![0u16; n * outcomes];
    let mut means = vec![0f64; k * next_k];
    let mut weights = vec![0f64; k];
    for i in 0..n {
        let row = &mut rows[i * outcomes..(i + 1) * outcomes];
        builder::histogram_row(deck, &indexer, &next_indexer, Some(&labels), None, i as u64, row);
        let w = indexer.multiplicity(i as u64) as f64;
        for &label in row.iter() {
            means[bucket(i) * next_k + label as usize] += w / outcomes as f64;
        }
        weights[bucket(i)] += w;
    }
    let means: Vec<f32> = (0..k * next_k).map(|x| (means[x] / weights[x / next_k]) as f32).collect();
    let mut scratch = GreedyScratch::default();
    let (mut total, mut weight) = (0.0, 0.0);
    for i in 0..n {
        let mut hand = vec![0f32; next_k];
        for &label in &rows[i * outcomes..(i + 1) * outcomes] {
            hand[label as usize] += 1.0 / outcomes as f32;
        }
        let mean = &means[bucket(i) * next_k..(bucket(i) + 1) * next_k];
        let distance = match &metric {
            Metric::Line(line) => line.emd(&hand, mean),
            Metric::Matrix(matrix) => {
                let (buckets, shares): (Vec<u16>, Vec<f32>) =
                    hand.iter().enumerate().filter(|(_, &x)| x > 0.0).map(|(b, &x)| (b as u16, x)).unzip();
                matrix.greedy(&buckets, &shares, mean, f32::INFINITY, &mut scratch)
            }
        };
        let w = indexer.multiplicity(i as u64) as f64;
        total += w * distance as f64;
        weight += w;
    }
    total / weight
}

/// The turn and flop on the 24-card deck, for both kinds of river buckets.
///
/// A bucket should say how good its hands are on average and how much that can still change
/// (made hands against draws). Buckets cut from the average alone, the same number of them,
/// can't say the second thing. And the buckets must do what k-means is for: hands sit
/// closer to their bucket's mean histogram than they do in buckets cut from the average.
#[test]
#[cfg_attr(debug_assertions, ignore = "slow in a debug build: run with --release")]
fn turn_and_flop_buckets_follow_equity_and_potential() {
    let deck = Deck::new(6);
    let equity = builder::river_equity(deck);
    let turn_outlook = outlook(deck, 4, &|river_index| equity.equity(river_index) as f64);
    let flop_outlook = outlook(deck, 3, &|turn_index| turn_outlook.mean[turn_index as usize]);

    for river_feature in [Feature::Ochs { clusters: 8 }, Feature::Equity] {
        let mut settings = small(6, 30);
        settings.river.feature = river_feature.clone();
        let ([flop, turn, river], _) = builder::build_all(&settings);
        assert_eq!(river.buckets(), 30);
        let plain = river_feature == Feature::Equity;
        for (table, next, look, street) in
            [(&turn, &river, &turn_outlook, Street::Turn), (&flop, &turn, &flop_outlook, Street::Flop)]
        {
            let name = format!("{river_feature:?} {}", street.name());
            let k = table.buckets();
            assert_eq!(k, 30);
            assert!(table.equity.windows(2).all(|w| w[0] <= w[1]));
            let bucket = |i: usize| table.bucket(i as u64) as usize;
            let by_mean = slices_by_mean(&look.mean, &look.weight, k);

            let mean = explained(&look.mean, &look.weight, &bucket, k);
            let spread = explained(&look.spread, &look.weight, &bucket, k);
            let spread_by_mean = explained(&look.spread, &look.weight, &|i| by_mean[i], k);
            let cost = histogram_cost(deck, street, next, &bucket, k);
            let cost_by_mean = histogram_cost(deck, street, next, &|i| by_mean[i], k);
            println!(
                "{name}: buckets explain {mean:.3} of the mean and {spread:.3} of the spread (slices of the mean: \
                 {spread_by_mean:.3}); distance to the bucket's mean histogram {cost:.4} (slices of the mean: {cost_by_mean:.4})"
            );
            assert!((cost - table.header().cost).abs() < 0.02 * cost, "{name}: {cost} against {}", table.header().cost);
            assert!(cost < 0.85 * cost_by_mean, "{name}: cost {cost}, slices of the mean {cost_by_mean}");
            if plain {
                // Everything is measured in equity, so the buckets should explain nearly
                // all of the average and most of the spread.
                assert!(mean > 0.95, "{name}: buckets explain only {mean} of the mean equity");
                assert!(spread > spread_by_mean + 0.15, "{name}: spread {spread} against {spread_by_mean}");
            } else {
                // OCHS buckets also tell apart which opponent hands are beaten, so less of
                // their detail goes to equity.
                assert!(mean > 0.85, "{name}: buckets explain only {mean} of the mean equity");
                assert!(spread > spread_by_mean - 0.02, "{name}: spread {spread} against {spread_by_mean}");
            }

            // The bucket's size is the number of deals in it, and its stored equity the
            // average of its hands' equity.
            let mut sums = vec![(0.0, 0.0); k];
            for i in 0..look.mean.len() {
                sums[bucket(i)].0 += look.weight[i];
                sums[bucket(i)].1 += look.weight[i] * look.mean[i];
            }
            let mut worst: f64 = 0.0;
            for (b, s) in sums.iter().enumerate() {
                worst = worst.max((s.1 / s.0 - table.equity[b] as f64).abs());
                assert_eq!(s.0 as u64, table.sizes[b]);
            }
            assert!(worst < 1e-6, "{name}: bucket equity off by {worst}");
        }
    }
}

/// The turn can also be clustered over slices of river equity (Johanson et al.'s
/// distribution-aware way), and the river by plain equity. Both run on the exact
/// earth mover's distance on a line.
#[test]
fn the_other_methods_build_too() {
    let deck = Deck::new(5);
    let equity: RiverEquity = builder::river_equity(deck);
    let kmeans = KMeansSettings::default();
    let river_settings = StreetSettings {
        buckets: 12,
        feature: Feature::Equity,
        kmeans: kmeans.clone(),
    };
    let (river, _) = builder::build_river(&equity, &river_settings, 1);
    assert!(river.buckets() <= 12 && river.buckets() >= 8);
    let turn_settings = |feature| StreetSettings {
        buckets: 12,
        feature,
        kmeans: kmeans.clone(),
    };
    let river_equity = NextEquity::River(&equity);
    let (over_bins, _, turn_equity) = builder::build_histogram_street(
        deck,
        Street::Turn,
        &NextLabels::EquityBins {
            equity: &equity,
            bins: 20,
        },
        &river_equity,
        &turn_settings(Feature::EquityBins { bins: 20 }),
        1,
    );
    let (over_buckets, report, same_equity) = builder::build_histogram_street(
        deck,
        Street::Turn,
        &NextLabels::Table(&river),
        &river_equity,
        &turn_settings(Feature::NextBuckets),
        1,
    );
    assert_eq!(turn_equity.sums, same_equity.sums);
    assert_eq!(turn_equity.sums, builder::hand_equity(deck, Street::Turn, &river_equity).sums);
    assert_eq!(turn_equity.denominator, 14 * equity.denominator as u64);
    for turn in [&over_bins, &over_buckets] {
        assert_eq!(turn.buckets(), 12);
        assert_eq!(turn.sizes.iter().sum::<u64>(), choose(20, 2) * choose(18, 4));
        assert!(turn.ground_metric().is_some());
    }
    assert!(over_bins.header().built_from.contains("20 slices"));
    assert!(over_buckets.header().built_from.contains(&river.checksum()));
    // On a line the lower bound rules out most comparisons.
    assert!(report.full_comparisons < 0.8, "{}", report.full_comparisons);
    let flop_settings = turn_settings(Feature::NextBuckets);
    let (flop, _, flop_equity) = builder::build_histogram_street(
        deck,
        Street::Flop,
        &NextLabels::Table(&over_bins),
        &NextEquity::Later(&turn_equity),
        &flop_settings,
        1,
    );
    // Over every flop hand, the average equity against a random hand is one half.
    let flop_indexer = HandIndexer::with_deck(deck, &[2, 3]);
    let (mut total, mut deals) = (0.0, 0.0);
    for i in 0..flop_indexer.size() {
        let w = flop_indexer.multiplicity(i) as f64;
        total += w * flop_equity.equity(i);
        deals += w;
    }
    assert!((total / deals - 0.5).abs() < 1e-9, "{}", total / deals);
    assert_eq!(flop.sizes.iter().sum::<u64>(), choose(20, 2) * choose(18, 3));
    assert!(flop.ground_metric().is_none());
}

#[test]
fn tables_save_load_and_look_up() {
    let settings = small(5, 10);
    let ([flop, turn, river], reports) = builder::build_all(&settings);
    let dir = std::env::temp_dir().join(format!("abstraction-pipeline-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let mut sizes = Vec::new();
    for table in [&flop, &turn, &river] {
        sizes.push(table.save(&dir.join(table.header().street.file_name())).unwrap());
    }
    // One byte per hand under 257 buckets, plus the header and the centres.
    assert!(sizes[2] > river.len() && sizes[2] < river.len() + 20_000);
    assert_eq!(reports[2].checksum, river.checksum());

    let loaded = Abstraction::load(&dir).unwrap();
    assert_eq!(loaded.deck(), Deck::new(5));
    assert_eq!(loaded.buckets(Street::Preflop), 5 + 10 + 10);
    for (street, table) in [(Street::Flop, &flop), (Street::Turn, &turn), (Street::River, &river)] {
        let back = loaded.table(street).unwrap();
        assert_eq!(back.header(), table.header());
        assert_eq!(back.to_bytes(), table.to_bytes());
        assert_eq!(loaded.buckets(street), table.buckets());
    }

    // Random hands: the bucket is the table's entry for the hand's index, and the same in
    // any suits and any order of the cards.
    let mut rng = Rng::new(4);
    for _ in 0..3000 {
        let mut cards: Vec<u8> = Deck::new(5).cards().collect();
        for i in 0..7 {
            let j = i + rng.below((cards.len() - i) as u64) as usize;
            cards.swap(i, j);
        }
        for board in [0usize, 3, 4, 5] {
            let (hole, rest) = cards[..2 + board].split_at(2);
            let bucket = loaded.bucket(hole, rest);
            assert!((bucket as usize) < loaded.buckets(Street::from_board_cards(board).unwrap()));
            let rotate = |c: &u8| (c & !3) | ((c & 3) + 1) % 4;
            let mut hole2: Vec<u8> = hole.iter().map(rotate).collect();
            let mut rest2: Vec<u8> = rest.iter().map(rotate).collect();
            hole2.reverse();
            rest2.reverse();
            assert_eq!(loaded.bucket(&hole2, &rest2), bucket);
            if board > 0 {
                let table = loaded.table(Street::from_board_cards(board).unwrap()).unwrap();
                assert_eq!(table.bucket(loaded.index(hole, rest)), bucket);
            } else {
                assert_eq!(bucket, loaded.preflop().class(hole[0], hole[1]));
            }
        }
    }

    // Tables for other streets or decks are refused.
    let other_deck = builder::build_all(&small(4, 4)).0;
    let [f4, t4, r4] = other_deck;
    assert!(Abstraction::from_tables(turn.clone(), turn.clone(), river.clone()).is_err());
    assert!(Abstraction::from_tables(flop.clone(), turn.clone(), r4.clone()).is_err());
    assert!(Abstraction::from_tables(f4, t4, r4).is_ok());

    // A damaged file is refused.
    let path = dir.join(Street::Turn.file_name());
    let mut bytes = std::fs::read(&path).unwrap();
    let at = bytes.len() / 2;
    bytes[at] ^= 1;
    std::fs::write(&path, &bytes).unwrap();
    let error = Abstraction::load(&dir).err().expect("a damaged table").to_string();
    assert!(error.contains("checksum"), "{error}");
    std::fs::remove_dir_all(&dir).unwrap();
}

/// The small tables in `tests/fixtures/small` (20-card deck, 12 buckets) load, and building
/// again from the settings in their headers gives the same files byte for byte. This fails
/// when a change to the code changes the buckets: then rebuild the fixtures (see the
/// README) and say so in the commit, because every table built before is stale too.
#[test]
fn fixture_tables_rebuild_exactly() {
    let dir = fixtures();
    let stored = Abstraction::load(&dir).expect("fixture tables load");
    let header = |street| stored.table(street).unwrap().header().clone();
    let settings = Settings {
        ranks: header(Street::River).ranks,
        seed: header(Street::River).seed,
        flop: header(Street::Flop).settings,
        turn: header(Street::Turn).settings,
        river: header(Street::River).settings,
    };
    assert_eq!(settings.ranks, 5);
    let ([flop, turn, river], _) = builder::build_all(&settings);
    for table in [flop, turn, river] {
        let street = table.header().street;
        let on_disk = std::fs::read(dir.join(street.file_name())).unwrap();
        assert!(
            table.to_bytes() == on_disk,
            "the rebuilt {} table differs from tests/fixtures/small/{}",
            street.name(),
            street.file_name()
        );
        assert_eq!(&Table::read_header(&dir.join(street.file_name())).unwrap(), table.header());
    }
    // The turn was built from this river and the flop from this turn.
    let river_checksum = stored.table(Street::River).unwrap().checksum();
    assert!(header(Street::Turn).built_from.contains(&river_checksum));
    let turn_checksum = stored.table(Street::Turn).unwrap().checksum();
    assert!(header(Street::Flop).built_from.contains(&turn_checksum));
}
