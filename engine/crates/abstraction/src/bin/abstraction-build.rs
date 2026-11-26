//! Builds, inspects and checks the abstraction tables. See the crate's README.

use abstraction::builder::{self, NextLabels, Report, RiverEquity, Settings};
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
                           (default river 400000, turn 200000, flop 0)
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
        let (table, mut report) = match street {
            Street::River => {
                let equity = equity.get_or_insert_with(|| builder::river_equity(deck));
                eprintln!("river: equities done after {:.1} s", started.elapsed().as_secs_f64());
                builder::build_river(equity, &settings.river, settings.seed)
            }
            Street::Turn => match settings.turn.feature {
                Feature::EquityBins { bins } => {
                    let equity = equity.get_or_insert_with(|| builder::river_equity(deck));
                    let next = NextLabels::EquityBins {
                        equity,
                        bins: bins as u32,
                    };
                    builder::build_histogram_street(deck, Street::Turn, &next, &settings.turn, settings.seed)
                }
                _ => {
                    let river = river.get_or_insert_with(|| load(Street::River));
                    let next = NextLabels::Table(river);
                    builder::build_histogram_street(deck, Street::Turn, &next, &settings.turn, settings.seed)
                }
            },
            Street::Flop => {
                let turn = turn.get_or_insert_with(|| load(Street::Turn));
                let next = NextLabels::Table(turn);
                builder::build_histogram_street(deck, Street::Flop, &next, &settings.flop, settings.seed)
            }
            Street::Preflop => unreachable!(),
        };
        // What came before the clustering (river equities, reading the next street's table)
        // counts as making the features.
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
        println!("  {}", serde_json::to_string(&table.header).unwrap());
        println!(
            "  {} bytes, checksum {} ok, read and checked in {:.3} s",
            size,
            table.checksum(),
            seconds
        );
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
