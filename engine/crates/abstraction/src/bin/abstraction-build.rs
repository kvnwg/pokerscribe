//! Builds, inspects and checks the abstraction tables. See the crate's README.

use abstraction::builder::{self, HandEquity, NextEquity, NextLabels, Report, RiverEquity, Settings};
use abstraction::table::{Feature, Street, Table};
use abstraction::{checks, format_cards, parse_cards, Abstraction};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

const USAGE: &str = "\
abstraction-build build --out DIR [options]   build tables into DIR
abstraction-build info FILE...                print a table's header and check its checksum
abstraction-build check DIR                   load the tables in DIR and run the sanity checks
abstraction-build bucket DIR HOLE [BOARD]     the bucket of a hand, for example: AhKh QhJh2c
abstraction-build gap DIR [HANDS]             how far the fast earth mover's distance is from the
                                              exact one, on HANDS random turn hands (default 300)
abstraction-build stats DIR                   how much of the hands' equity, and of how much it can
                                              still change, the buckets in DIR tell apart

build options:
  --buckets N              buckets on each street (default 200)
  --flop N, --turn N, --river N
                           buckets on one street
  --streets LIST           which tables to build, in order (default river,turn,flop).
                           The turn needs river.abs in DIR, the flop needs turn.abs
  --river-feature NAME     ochs (default) or equity
  --opponent-clusters N    opponent groups for ochs (default 8)
  --turn-histogram NAME    buckets (default: over the river table's buckets) or equity
                           (over slices of river equity)
  --equity-bins N          slices for --turn-histogram equity (default 50)
  --seed N                 same seed and settings, same tables (default 1)
  --max-iters N            k-means iterations at most (default 50)
  --tolerance X            stop when under this share of hands change bucket (default 0.001)
  --restarts N             k-means runs, the best is kept (default 1)
  --river-train N, --turn-train N, --flop-train N
                           train the centres on N random hands, 0 for all of them
                           (default river 4000000, turn 2000000, flop 0)
  --river-init N, --turn-init N, --flop-init N
                           seed the centres from N of the training hands, 0 for all
                           (default river 400000, turn 200000, flop 200000)
  --ranks N                deck of the top N ranks (default 13, the real game)
  --threads N              worker threads (default: every core)
";

fn fail(message: &str) -> ! {
    eprintln!("abstraction-build: {message}");
    std::process::exit(2);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("build") => build(&args[1..]),
        Some("info") => info(&args[1..]),
        Some("check") => check(&args[1..]),
        Some("bucket") => bucket(&args[1..]),
        Some("gap") => gap(&args[1..]),
        Some("stats") => stats(&args[1..]),
        Some("--help") | Some("-h") | None => print!("{USAGE}"),
        Some(other) => fail(&format!("unknown command {other}\n\n{USAGE}")),
    }
}

fn number<T: std::str::FromStr>(name: &str, value: &str) -> T {
    value
        .replace('_', "")
        .parse()
        .unwrap_or_else(|_| fail(&format!("{name} needs a number, got {value}")))
}

fn build(args: &[String]) {
    let mut settings = Settings::new(200);
    let mut out: Option<PathBuf> = None;
    let mut streets = vec![Street::River, Street::Turn, Street::Flop];
    let mut threads = 0usize;
    let mut opponent_clusters = 8u8;
    let mut river_feature = "ochs".to_string();
    let mut turn_histogram = "buckets".to_string();
    let mut equity_bins = 50u16;

    let mut it = args.iter();
    while let Some(arg) = it.next() {
        let mut value = || it.next().unwrap_or_else(|| fail(&format!("{arg} needs a value"))).as_str();
        match arg.as_str() {
            "--out" => out = Some(PathBuf::from(value())),
            "--buckets" => {
                let n = number(arg, value());
                settings.flop.buckets = n;
                settings.turn.buckets = n;
                settings.river.buckets = n;
            }
            "--flop" => settings.flop.buckets = number(arg, value()),
            "--turn" => settings.turn.buckets = number(arg, value()),
            "--river" => settings.river.buckets = number(arg, value()),
            "--streets" => {
                streets = value()
                    .split(',')
                    .map(|s| match s.trim() {
                        "river" => Street::River,
                        "turn" => Street::Turn,
                        "flop" => Street::Flop,
                        other => fail(&format!("unknown street {other}")),
                    })
                    .collect()
            }
            "--river-feature" => river_feature = value().to_string(),
            "--opponent-clusters" => opponent_clusters = number(arg, value()),
            "--turn-histogram" => turn_histogram = value().to_string(),
            "--equity-bins" => equity_bins = number(arg, value()),
            "--seed" => settings.seed = number(arg, value()),
            "--max-iters" => {
                let n = number(arg, value());
                for s in [&mut settings.flop, &mut settings.turn, &mut settings.river] {
                    s.kmeans.max_iters = n;
                }
            }
            "--tolerance" => {
                let x = number(arg, value());
                for s in [&mut settings.flop, &mut settings.turn, &mut settings.river] {
                    s.kmeans.tolerance = x;
                }
            }
            "--restarts" => {
                let n = number(arg, value());
                for s in [&mut settings.flop, &mut settings.turn, &mut settings.river] {
                    s.kmeans.restarts = n;
                }
            }
            "--river-train" => settings.river.kmeans.train_samples = number(arg, value()),
            "--turn-train" => settings.turn.kmeans.train_samples = number(arg, value()),
            "--flop-train" => settings.flop.kmeans.train_samples = number(arg, value()),
            "--river-init" => settings.river.kmeans.init_samples = number(arg, value()),
            "--turn-init" => settings.turn.kmeans.init_samples = number(arg, value()),
            "--flop-init" => settings.flop.kmeans.init_samples = number(arg, value()),
            "--ranks" => settings.ranks = number(arg, value()),
            "--threads" => threads = number(arg, value()),
            other => fail(&format!("unknown option {other}\n\n{USAGE}")),
        }
    }
    settings.river.feature = match river_feature.as_str() {
        "ochs" => Feature::Ochs {
            clusters: opponent_clusters,
        },
        "equity" => Feature::Equity,
        other => fail(&format!("--river-feature is ochs or equity, not {other}")),
    };
    settings.turn.feature = match turn_histogram.as_str() {
        "buckets" => Feature::NextBuckets,
        "equity" => Feature::EquityBins { bins: equity_bins },
        other => fail(&format!("--turn-histogram is buckets or equity, not {other}")),
    };
    let out = out.unwrap_or_else(|| fail("build needs --out DIR"));
    if !(2..=13).contains(&settings.ranks) {
        fail("--ranks is 2 to 13");
    }
    if threads > 0 {
        rayon::ThreadPoolBuilder::new()
            .num_threads(threads)
            .build_global()
            .expect("the thread pool is set once");
    }
    std::fs::create_dir_all(&out).unwrap_or_else(|e| fail(&format!("{}: {e}", out.display())));
    let deck = settings.deck();
    let load = |street: Street| -> Table {
        let path = out.join(street.file_name());
        Table::load(&path).unwrap_or_else(|e| fail(&format!("{e}\nbuild the {} table first", street.name())))
    };

    let mut equity: Option<RiverEquity> = None;
    let mut turn_equity: Option<HandEquity> = None;
    let mut river: Option<Table> = None;
    let mut turn: Option<Table> = None;
    for street in streets {
        eprintln!(
            "{}: building, {} buckets, {} threads",
            street.name(),
            settings.street(street).buckets,
            rayon::current_num_threads()
        );
        let started = Instant::now();
        // Every street needs the exact river equities: for the river's features, and for
        // the average equity of the turn's and flop's buckets.
        let equity = equity.get_or_insert_with(|| builder::river_equity(deck));
        let (table, mut report) = match street {
            Street::River => builder::build_river(equity, &settings.river, settings.seed),
            Street::Turn => {
                let next = match settings.turn.feature {
                    Feature::EquityBins { bins } => NextLabels::EquityBins {
                        equity,
                        bins: bins as u32,
                    },
                    _ => NextLabels::Table(river.get_or_insert_with(|| load(Street::River))),
                };
                let (table, report, hand_equity) = builder::build_histogram_street(
                    deck,
                    Street::Turn,
                    &next,
                    &NextEquity::River(equity),
                    &settings.turn,
                    settings.seed,
                );
                turn_equity = Some(hand_equity);
                (table, report)
            }
            Street::Flop => {
                let turn = turn.get_or_insert_with(|| load(Street::Turn));
                let turn_equity = turn_equity
                    .get_or_insert_with(|| builder::hand_equity(deck, Street::Turn, &NextEquity::River(equity)));
                let (table, report, _) = builder::build_histogram_street(
                    deck,
                    Street::Flop,
                    &NextLabels::Table(turn),
                    &NextEquity::Later(turn_equity),
                    &settings.flop,
                    settings.seed,
                );
                (table, report)
            }
            Street::Preflop => unreachable!(),
        };
        // What came before the clustering (river equities, reading the next street's table,
        // the turn's equities for a flop built on its own) counts as making the features.
        report.features_seconds += started.elapsed().as_secs_f64() - report.total_seconds;
        let path = out.join(street.file_name());
        report.file_bytes = table.save(&path).unwrap_or_else(|e| fail(&format!("{}: {e}", path.display())));
        report.total_seconds = started.elapsed().as_secs_f64();
        report.peak_memory_mb = builder::peak_memory_bytes() as f64 / (1024.0 * 1024.0);
        print_report(&report, &path);
        log_report(&out, &report, &settings);
        match street {
            Street::River => river = Some(table),
            Street::Turn => turn = Some(table),
            _ => {}
        }
    }
}

fn print_report(r: &Report, path: &Path) {
    eprintln!(
        "{}: {} hands in {} buckets, {:.1} s (features {:.1}, seeding {:.1}, {} iterations {:.1}, all hands {:.1}, rest {:.1}), \
         peak memory {:.0} MB, {} bytes, checksum {}, cost {:.5}, full comparisons {:.1}%\n  wrote {}",
        r.street.name(),
        r.hands,
        r.buckets,
        r.total_seconds,
        r.features_seconds,
        r.seeding_seconds,
        r.iterations,
        r.iterating_seconds,
        r.assigning_seconds,
        r.finishing_seconds,
        r.peak_memory_mb,
        r.file_bytes,
        r.checksum,
        r.cost,
        r.full_comparisons * 100.0,
        path.display()
    );
}

/// Appends the report and the settings to `build_log.jsonl` in the output directory.
fn log_report(out: &Path, report: &Report, settings: &Settings) {
    let line = serde_json::json!({ "report": report, "settings": settings });
    let path = out.join("build_log.jsonl");
    let result = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .and_then(|mut f| writeln!(f, "{line}"));
    if let Err(e) = result {
        eprintln!("could not write {}: {e}", path.display());
    }
}

fn info(args: &[String]) {
    if args.is_empty() {
        fail("info needs a table file");
    }
    for arg in args {
        let path = Path::new(arg);
        let started = Instant::now();
        let table = Table::load(path).unwrap_or_else(|e| fail(&e.to_string()));
        let seconds = started.elapsed().as_secs_f64();
        let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
        println!("{arg}");
        println!("  {}", serde_json::to_string(table.header()).unwrap());
        println!(
            "  {} bytes, checksum {} ok, read and checked in {:.3} s",
            size,
            table.checksum(),
            seconds
        );
        if !table.header().opponent_clusters.is_empty() {
            let preflop = abstraction::Preflop::with_deck(abstraction::Deck::new(table.header().ranks));
            let groups = table.header().opponent_clusters.iter().max().map_or(0, |&g| g as usize + 1);
            for g in 0..groups {
                let mut names: Vec<(u8, u8, String)> = (0..preflop.classes() as u16)
                    .filter(|&c| table.header().opponent_clusters[c as usize] as usize == g)
                    .map(|c| {
                        let [a, b] = preflop.cards(c);
                        ((a >> 2).max(b >> 2), (a >> 2).min(b >> 2), preflop.name(c))
                    })
                    .collect();
                names.sort_by(|a, b| b.cmp(a));
                let names: Vec<String> = names.into_iter().map(|n| n.2).collect();
                println!("  opponent group {g} ({} classes): {}", names.len(), names.join(" "));
            }
        }
        let largest = table.sizes.iter().max().unwrap();
        let smallest = table.sizes.iter().min().unwrap();
        let total: u64 = table.sizes.iter().sum();
        println!(
            "  bucket sizes: smallest {:.3}%, largest {:.3}% of {} hands; bucket equity {:.3} to {:.3}",
            *smallest as f64 * 100.0 / total as f64,
            *largest as f64 * 100.0 / total as f64,
            total,
            table.equity.first().unwrap(),
            table.equity.last().unwrap()
        );
    }
}

fn check(args: &[String]) {
    let dir = Path::new(args.first().unwrap_or_else(|| fail("check needs the tables' directory")));
    let started = Instant::now();
    let abstraction = Abstraction::load(dir).unwrap_or_else(|e| fail(&e.to_string()));
    println!("loaded and checksums verified in {:.3} s", started.elapsed().as_secs_f64());
    let started = Instant::now();
    drop(Abstraction::load_unchecked(dir).unwrap_or_else(|e| fail(&e.to_string())));
    println!("loaded without checking in {:.3} s", started.elapsed().as_secs_f64());
    for street in [Street::Flop, Street::Turn, Street::River] {
        let table = abstraction.table(street).unwrap();
        println!(
            "{}: {} hands, {} buckets, checksum {}",
            street.name(),
            table.len(),
            table.buckets(),
            table.checksum()
        );
    }
    // Lookup speed: random hands, timed in bulk.
    {
        let mut rng = abstraction::rng::Rng::new(1);
        let deck: Vec<u8> = abstraction.deck().cards().collect();
        let hands: Vec<[u8; 7]> = (0..1_000_000)
            .map(|_| {
                let mut cards = deck.clone();
                for i in 0..7 {
                    let j = i + rng.below((cards.len() - i) as u64) as usize;
                    cards.swap(i, j);
                }
                cards[..7].try_into().unwrap()
            })
            .collect();
        for board in [3usize, 4, 5] {
            let started = Instant::now();
            let mut sum = 0u64;
            for hand in &hands {
                sum += abstraction.bucket(&hand[..2], &hand[2..2 + board]) as u64;
            }
            println!(
                "{}: {:.0} ns to look up a random hand's bucket (average bucket {:.1})",
                Street::from_board_cards(board).unwrap().name(),
                started.elapsed().as_nanos() as f64 / hands.len() as f64,
                sum as f64 / hands.len() as f64
            );
        }
    }
    let results = checks::run(&abstraction);
    let mut failed = 0;
    for r in &results {
        println!("{} {}: {}", if r.passed { "ok  " } else { "FAIL" }, r.name, r.detail);
        failed += !r.passed as usize;
    }
    println!("{} checks, {} failed", results.len(), failed);
    if failed > 0 {
        std::process::exit(1);
    }
}

fn bucket(args: &[String]) {
    if args.len() < 2 {
        fail("bucket needs the tables' directory and the hole cards");
    }
    let abstraction = Abstraction::load_unchecked(Path::new(&args[0])).unwrap_or_else(|e| fail(&e.to_string()));
    let hole = parse_cards(&args[1]).unwrap_or_else(|e| fail(&e));
    let board = parse_cards(&args[2..].join("")).unwrap_or_else(|e| fail(&e));
    if hole.len() != 2 || ![0, 3, 4, 5].contains(&board.len()) {
        fail("two hole cards and a board of 0, 3, 4 or 5 cards");
    }
    let street = Street::from_board_cards(board.len()).unwrap();
    let bucket = abstraction.bucket(&hole, &board);
    match abstraction.table(street) {
        None => println!(
            "{} preflop: class {} of 169 ({})",
            format_cards(&hole),
            bucket,
            abstraction.preflop().name(bucket)
        ),
        Some(table) => println!(
            "{} on {} ({}): bucket {} of {}, bucket equity {:.3}, {:.3}% of hands",
            format_cards(&hole),
            format_cards(&board),
            street.name(),
            bucket,
            table.buckets(),
            table.equity[bucket as usize],
            table.sizes[bucket as usize] as f64 * 100.0 / table.sizes.iter().sum::<u64>() as f64
        ),
    }
}

/// Measures the greedy earth mover's distance against the exact one on random turn hands:
/// each hand against its own bucket's centre and against another bucket's.
fn gap(args: &[String]) {
    use abstraction::emd::{self, GreedyScratch, Metric};
    use abstraction::rng::Rng;
    use abstraction::HandIndexer;
    let dir = Path::new(args.first().unwrap_or_else(|| fail("gap needs the tables' directory")));
    let hands: usize = args.get(1).map_or(300, |v| number("HANDS", v));
    let river = Table::load(&dir.join(Street::River.file_name())).unwrap_or_else(|e| fail(&e.to_string()));
    let turn = Table::load(&dir.join(Street::Turn.file_name())).unwrap_or_else(|e| fail(&e.to_string()));
    let deck = abstraction::Deck::new(river.header().ranks);
    let Some(Metric::Matrix(metric)) = river.ground_metric() else {
        fail("the river table's buckets are on a line: the distance used is already exact");
    };
    if turn.header().settings.feature != Feature::NextBuckets {
        fail("the turn table is not built over the river table's buckets");
    }
    let indexer = HandIndexer::with_deck(deck, &[2, 4]);
    let next_indexer = HandIndexer::with_deck(deck, &[2, 5]);
    let next = NextLabels::Table(&river);
    let outcomes = deck.len() - 6;
    let next_k = river.buckets();
    let k = turn.buckets();
    // Whole-number histograms with the same total for the exact solver.
    const SCALE: u64 = 1000;
    let total = outcomes as u64 * SCALE;
    let whole = |centre: &[f32]| -> Vec<u64> {
        let mut counts: Vec<u64> = centre.iter().map(|&x| (x as f64 * total as f64).floor() as u64).collect();
        let mut short = total - counts.iter().sum::<u64>();
        let mut order: Vec<usize> = (0..centre.len()).collect();
        order.sort_by(|&a, &b| {
            let frac = |i: usize| centre[i] as f64 * total as f64 - counts[i] as f64;
            frac(b).partial_cmp(&frac(a)).unwrap()
        });
        for &i in order.iter().cycle() {
            if short == 0 {
                break;
            }
            counts[i] += 1;
            short -= 1;
        }
        counts
    };
    let mut rng = Rng::new(7);
    let mut scratch = GreedyScratch::default();
    let mut row = vec![0u16; outcomes];
    // Sums for the hand's own centre and for another centre: greedy, exact, lower bound.
    let mut sums = [[0f64; 3]; 2];
    let mut worst = [1f64; 2];
    for _ in 0..hands {
        let index = rng.below(indexer.size());
        builder::histogram_row(deck, &indexer, &next_indexer, Some(&next), None, index, &mut row);
        let mut counts = vec![0u64; next_k];
        for &label in &row {
            counts[label as usize] += SCALE;
        }
        let (buckets, shares): (Vec<u16>, Vec<f32>) = counts
            .iter()
            .enumerate()
            .filter(|(_, &c)| c > 0)
            .map(|(b, &c)| (b as u16, c as f32 / total as f32))
            .unzip();
        let own = turn.bucket(index) as usize;
        let other = (own + 1 + rng.below(k as u64 - 1) as usize) % k;
        for (which, c) in [own, other].into_iter().enumerate() {
            let centre = &turn.centroids[c * next_k..(c + 1) * next_k];
            let greedy = metric.greedy(&buckets, &shares, centre, f32::INFINITY, &mut scratch) as f64;
            let exact = emd::exact(&counts, &whole(centre), |i, j| metric.d[i * next_k + j] as f64);
            let mut a = vec![0f32; metric.sketch_len()];
            let mut b = vec![0f32; metric.sketch_len()];
            metric.sketch(buckets.iter().map(|&x| x as usize).zip(shares.iter().cloned()), &mut a);
            metric.sketch(centre.iter().cloned().enumerate(), &mut b);
            let bound = metric.lower_bound(&a, &b) as f64;
            sums[which][0] += greedy;
            sums[which][1] += exact;
            sums[which][2] += bound;
            if exact > 1e-9 {
                worst[which] = worst[which].max(greedy / exact);
            }
        }
    }
    for (which, name) in ["its own bucket's centre", "another bucket's centre"].iter().enumerate() {
        let [greedy, exact, bound] = sums[which];
        println!(
            "{hands} turn hands against {name}: exact {:.4}, greedy {:.4} ({:+.1}%, worst hand {:+.1}%), lower bound {:.4} ({:.0}% of exact)",
            exact / hands as f64,
            greedy / hands as f64,
            (greedy / exact - 1.0) * 100.0,
            (worst[which] - 1.0) * 100.0,
            bound / hands as f64,
            bound / exact * 100.0
        );
    }
}

/// How much of the variation of `value` the buckets explain: 1 minus the variance inside
/// buckets over the total variance.
fn explained(value: &[f64], weight: &[u8], bucket: &(dyn Fn(usize) -> usize + Sync), k: usize) -> f64 {
    let mut sums = vec![[0f64; 3]; k]; // weight, sum, sum of squares
    for i in 0..value.len() {
        let (w, v) = (weight[i] as f64, value[i]);
        let s = &mut sums[bucket(i)];
        s[0] += w;
        s[1] += w * v;
        s[2] += w * v * v;
    }
    let all = sums.iter().fold([0f64; 3], |a, s| [a[0] + s[0], a[1] + s[1], a[2] + s[2]]);
    let total = all[2] - all[1] * all[1] / all[0];
    let inside: f64 = sums.iter().filter(|s| s[0] > 0.0).map(|s| s[2] - s[1] * s[1] / s[0]).sum();
    1.0 - inside / total
}

/// Buckets cut from `value` alone: `k` slices holding the same number of deals each.
fn slices(value: &[f64], weight: &[u8], k: usize) -> Vec<u16> {
    use rayon::prelude::*;
    let mut order: Vec<u32> = (0..value.len() as u32).collect();
    order.par_sort_unstable_by(|&a, &b| {
        value[a as usize].partial_cmp(&value[b as usize]).unwrap().then(a.cmp(&b))
    });
    let total: f64 = weight.iter().map(|&w| w as f64).sum();
    let mut bucket = vec![0u16; value.len()];
    let mut below = 0.0;
    for i in order {
        bucket[i as usize] = ((below / total * k as f64) as usize).min(k - 1) as u16;
        below += weight[i as usize] as f64;
    }
    bucket
}

/// For every canonical flop or turn hand: the mean and the standard deviation, over the
/// cards that can come, of `next_value` of the hand it becomes.
fn outlook(
    deck: abstraction::Deck,
    board: usize,
    next_value: &(dyn Fn(u64) -> f64 + Sync),
) -> (Vec<f64>, Vec<f64>, Vec<u8>) {
    use abstraction::HandIndexer;
    use rayon::prelude::*;
    let indexer = HandIndexer::with_deck(deck, &[2, board as u8]);
    let next = HandIndexer::with_deck(deck, &[2, board as u8 + 1]);
    let rows: Vec<(f64, f64, u8)> = (0..indexer.size())
        .into_par_iter()
        .map(|i| {
            let mut cards = [0u8; 7];
            indexer.unindex(i, &mut cards[..2 + board]);
            let (mut sum, mut squares, mut count) = (0.0, 0.0, 0.0);
            for c in deck.cards() {
                if cards[..2 + board].contains(&c) {
                    continue;
                }
                cards[2 + board] = c;
                let v = next_value(next.index(&cards[..3 + board]));
                sum += v;
                squares += v * v;
                count += 1.0;
            }
            let mean = sum / count;
            (mean, (squares / count - mean * mean).max(0.0).sqrt(), indexer.multiplicity(i) as u8)
        })
        .collect();
    (
        rows.iter().map(|r| r.0).collect(),
        rows.iter().map(|r| r.1).collect(),
        rows.iter().map(|r| r.2).collect(),
    )
}

/// Prints, for each street, how much of the hands' equity the buckets tell apart, and for
/// the flop and turn how much of the equity's spread over the next card (made hands
/// against draws). For comparison: the same number of buckets cut from the average equity
/// alone.
fn stats(args: &[String]) {
    use abstraction::HandIndexer;
    let dir = Path::new(args.first().unwrap_or_else(|| fail("stats needs the tables' directory")));
    let abstraction = Abstraction::load_unchecked(dir).unwrap_or_else(|e| fail(&e.to_string()));
    let deck = abstraction.deck();
    let equity = builder::river_equity(deck);

    let river = abstraction.table(Street::River).unwrap();
    let weights = builder::multiplicities(&HandIndexer::with_deck(deck, &[2, 5]));
    let values: Vec<f64> = equity.numerators.iter().map(|&q| q as f64 / equity.denominator as f64).collect();
    println!(
        "river: {} buckets explain {:.1}% of the equity",
        river.buckets(),
        explained(&values, &weights, &|i| river.bucket(i as u64) as usize, river.buckets()) * 100.0
    );
    drop(values);

    let (turn_mean, turn_spread, turn_weight) = outlook(deck, 4, &|i| equity.equity(i) as f64);
    let (flop_mean, flop_spread, flop_weight) = outlook(deck, 3, &|i| turn_mean[i as usize]);
    for (street, mean, spread, weight) in [
        (Street::Turn, &turn_mean, &turn_spread, &turn_weight),
        (Street::Flop, &flop_mean, &flop_spread, &flop_weight),
    ] {
        let table = abstraction.table(street).unwrap();
        let k = table.buckets();
        let bucket = |i: usize| table.bucket(i as u64) as usize;
        let cut = slices(mean, weight, k);
        println!(
            "{}: {k} buckets explain {:.1}% of the equity and {:.1}% of its spread over the next card; \
             {k} slices of the equity explain {:.1}% and {:.1}%",
            street.name(),
            explained(mean, weight, &bucket, k) * 100.0,
            explained(spread, weight, &bucket, k) * 100.0,
            explained(mean, weight, &|i| cut[i] as usize, k) * 100.0,
            explained(spread, weight, &|i| cut[i] as usize, k) * 100.0,
        );
    }
}
