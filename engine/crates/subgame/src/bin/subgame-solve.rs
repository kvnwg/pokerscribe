//! subgame-solve: solve one SPOT and write its RESULT (`data/SPOT_FORMAT.md`).
//!
//! ```text
//! subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.3]
//!               [--max-iterations N] [--time-ms N] [--threads N]
//! ```
//!
//! The solve stops at the first of: the target exploitability (percent of the pot)
//! reached, the iteration limit, or the time limit. The RESULT goes to `--out`, or to
//! standard output, as plain JSON Lines (a turn RESULT is 2.5 to 6 MB; gzip it afterwards to
//! store it as `<id>.jsonl.gz`). A one-line summary goes to standard error. Exit codes:
//! 0 solved, 1 the spot is bad or a file can't be read or written, 2 the command line is
//! wrong.

use std::path::PathBuf;
use std::process::ExitCode;

use subgame::expected::check_expected;
use subgame::result::{checks, encode, records, SolveInfo};
use subgame::{solve, Game, SolveConfig, Spot};

const USAGE: &str = "usage: subgame-solve <spot.json> [--out result.json] [--target-exploitability 0.3] \
[--max-iterations N] [--time-ms N] [--threads N]

  <spot.json>                   a SPOT (data/SPOT_FORMAT.md), river or turn
  --out FILE                    where to write the RESULT (default: standard output)
  --target-exploitability PCT   stop at or under this percent of the pot (default 0.3; 0 turns it off)
  --max-iterations N            stop after N iterations (default 10000)
  --time-ms N                   stop when the next iteration wouldn't fit in N milliseconds (default: no limit)
  --threads N                   threads for the river cards of a turn spot (default: every core; river spots use 1)

The solve stops at the first of the three limits it reaches.";

struct Args {
    spot: PathBuf,
    out: Option<PathBuf>,
    config: SolveConfig,
    threads_given: bool,
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut spot = None;
    let mut out = None;
    let mut config = SolveConfig::default();
    let mut threads_given = false;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        // "--flag value" or "--flag=value"
        let (flag, inline) = match arg.split_once('=') {
            Some((f, v)) if f.starts_with("--") => (f, Some(v.to_string())),
            _ => (arg, None),
        };
        let mut value = |name: &str| -> Result<String, String> {
            if let Some(v) = &inline {
                return Ok(v.clone());
            }
            i += 1;
            args.get(i)
                .cloned()
                .ok_or_else(|| format!("{name} needs a value"))
        };
        match flag {
            "--out" | "-o" => out = Some(PathBuf::from(value("--out")?)),
            "--target-exploitability" => {
                let text = value(flag)?;
                let pct: f64 = text
                    .parse()
                    .map_err(|_| format!("--target-exploitability: {text:?} isn't a number"))?;
                if !(pct.is_finite() && pct >= 0.0) {
                    return Err(
                        "--target-exploitability is a percent of the pot, 0 or more".to_string()
                    );
                }
                config.target_exploitability = pct / 100.0;
            }
            "--max-iterations" => {
                let text = value(flag)?;
                let n: u32 = text
                    .parse()
                    .map_err(|_| format!("--max-iterations: {text:?} isn't a whole number"))?;
                if n == 0 {
                    return Err("--max-iterations must be at least 1".to_string());
                }
                config.max_iterations = Some(n);
            }
            "--time-ms" => {
                let text = value(flag)?;
                let ms: f64 = text
                    .parse()
                    .map_err(|_| format!("--time-ms: {text:?} isn't a number"))?;
                if !(ms.is_finite() && ms > 0.0) {
                    return Err("--time-ms must be more than 0".to_string());
                }
                config.time_ms = Some(ms);
            }
            "--threads" => {
                let text = value(flag)?;
                let n: usize = text
                    .parse()
                    .map_err(|_| format!("--threads: {text:?} isn't a whole number"))?;
                if n == 0 {
                    return Err("--threads must be at least 1".to_string());
                }
                config.threads = n;
                threads_given = true;
            }
            _ if flag.starts_with('-') && flag.len() > 1 => {
                return Err(format!("unknown option {flag}"))
            }
            _ if spot.is_none() => spot = Some(PathBuf::from(arg)),
            _ => return Err(format!("only one spot at a time (got {arg:?} too)")),
        }
        i += 1;
    }
    let spot = spot.ok_or("no spot file given")?;
    if out
        .as_ref()
        .is_some_and(|o| o.extension().is_some_and(|e| e == "gz"))
    {
        return Err("--out: the RESULT is written as plain JSON Lines; write a .jsonl and gzip it afterwards".to_string());
    }
    Ok(Args {
        spot,
        out,
        config,
        threads_given,
    })
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "--help" || a == "-h") {
        println!("{USAGE}");
        return ExitCode::SUCCESS;
    }
    let Args {
        spot: path,
        out,
        mut config,
        threads_given,
    } = match parse_args(&args) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("subgame-solve: {e}\n\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    let game = match Spot::load(&path).and_then(Game::new) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("subgame-solve: {}: {e}", path.display());
            return ExitCode::from(1);
        }
    };
    if !game.is_turn() {
        config.threads = 1; // nothing to spread: a river tree has no river cards to deal
    } else if !threads_given {
        config.threads = std::thread::available_parallelism().map_or(1, |n| n.get());
    }

    let parallel = config.threads > 1;
    if parallel {
        // for the check of the written answer; the solve brings its own pool of this size
        let _ = rayon::ThreadPoolBuilder::new()
            .num_threads(config.threads)
            .build_global();
    }

    let solution = solve(&game, &config);
    let nodes = records(&game, &solution.strategy);
    let failures = check_expected(&game.spot, &nodes);
    let checked = match checks(&game, &nodes, parallel) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("subgame-solve: the answer can't be read back: {e}");
            return ExitCode::from(1);
        }
    };
    let text = encode(
        &game,
        &SolveInfo {
            config: &config,
            solution: &solution,
            checks: &checked,
            expected_failures: &failures,
            created: None,
        },
        &nodes,
    );
    let written = match &out {
        Some(file) => {
            std::fs::write(file, &text).map_err(|e| format!("can't write {}: {e}", file.display()))
        }
        None => {
            use std::io::Write;
            std::io::stdout()
                .lock()
                .write_all(text.as_bytes())
                .map_err(|e| format!("can't write the result: {e}"))
        }
    };
    if let Err(e) = written {
        eprintln!("subgame-solve: {e}");
        return ExitCode::from(1);
    }
    eprintln!(
        "{}: {} iterations in {:.1} ms, exploitability {:.3}% of the pot{}, EV oop {:.3} ip {:.3}",
        game.spot.id,
        solution.iterations,
        solution.elapsed_ms,
        100.0 * solution.exploitability,
        if solution.converged {
            ""
        } else {
            " (target not reached)"
        },
        solution.values[0],
        solution.values[1],
    );
    for failure in &failures {
        eprintln!("{}: expected check fails: {failure}", game.spot.id);
    }
    ExitCode::SUCCESS
}
