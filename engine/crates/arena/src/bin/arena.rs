//! Runs a match between the built-in test agents and prints or saves the report.

use std::path::PathBuf;
use std::process::ExitCode;

use arena::{bots, run_match, MatchConfig};

const USAGE: &str = "\
arena --agents A,B[,C...] [--players N | --lineup I,J,...] [--deals N] [--seed N]
      [--plain] [--no-equity] [--max-runouts N | --exact-equity] [--shared-randomness]
      [--stack-bb N] [--blinds SB/BB] [--ante N] [--threads N] [--out FILE]

  --agents A,B       Agents by name. Built in: fold call raise minraise jam random tag tag-loose.
  --players N        Table size, 2 to 6 (default 2). The second agent sits in each seat
                     in turn, the first agent in all the others.
  --lineup I,J,...   The agent (a number, 0 for the first) at each place of the table,
                     for any other mix. Its length is the table size.
  --deals N          Deals (default 10000). With duplicate play each is played once per
                     rotation of the lineup.
  --seed N           The match seed (default 1). The same seed gives the same result.
  --plain            No duplicate play: each deal once, the lineup rotating by one seat a deal.
  --no-equity        Score the real chips when players are all in before the river.
  --max-runouts N    Average the all-in equity over at most N boards (default 10000: exact
                     on the flop and turn, 10000 random boards before the flop).
  --exact-equity     Average over every board, also before the flop (10 to 15 ms a hand).
  --shared-randomness  A seat gets the same random numbers in every replay of a deal.
  --stack-bb N       Starting stacks in big blinds (default 100).
  --blinds SB/BB     Blinds in chips (default 50/100).
  --ante N           Ante in chips (default 0).
  --threads N        Worker threads (default: every core).
  --out FILE         Save the report as JSON.";

fn usage(problem: &str) -> ExitCode {
    eprintln!("{problem}\n\n{USAGE}");
    ExitCode::from(2)
}

fn main() -> ExitCode {
    let mut names: Vec<String> = Vec::new();
    let mut players = 2usize;
    let mut lineup: Option<Vec<usize>> = None;
    let mut config = MatchConfig::heads_up(10_000, 1);
    let mut stack_bb = 100u32;
    let mut out: Option<PathBuf> = None;

    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        macro_rules! value {
            () => {
                match args.next() {
                    Some(v) => v,
                    None => return usage(&format!("{arg} needs a value")),
                }
            };
        }
        macro_rules! number {
            () => {{
                let v = value!();
                match v.parse() {
                    Ok(x) => x,
                    Err(_) => return usage(&format!("{arg}: {v:?} is not a number")),
                }
            }};
        }
        match arg.as_str() {
            "--agents" => names = value!().split(',').map(str::to_string).collect(),
            "--players" => players = number!(),
            "--lineup" => {
                let v = value!();
                match v.split(',').map(str::parse).collect() {
                    Ok(places) => lineup = Some(places),
                    Err(_) => return usage(&format!("--lineup: {v:?} is not a list of numbers")),
                }
            }
            "--deals" => config.deals = number!(),
            "--seed" => config.seed = number!(),
            "--plain" => config.duplicate = false,
            "--no-equity" => config.all_in_equity = false,
            "--max-runouts" => config.max_runouts = Some(number!()),
            "--exact-equity" => config.max_runouts = None,
            "--shared-randomness" => config.shared_randomness = true,
            "--stack-bb" => stack_bb = number!(),
            "--blinds" => {
                let v = value!();
                let parts: Vec<&str> = v.split('/').collect();
                match (
                    parts.len(),
                    parts[0].parse(),
                    parts.get(1).map(|p| p.parse()),
                ) {
                    (2, Ok(sb), Some(Ok(bb))) => {
                        config.small_blind = sb;
                        config.big_blind = bb;
                    }
                    _ => return usage(&format!("--blinds: {v:?} is not SB/BB")),
                }
            }
            "--ante" => config.ante = number!(),
            "--threads" => config.threads = number!(),
            "--out" => out = Some(PathBuf::from(value!())),
            "-h" | "--help" => {
                println!("{USAGE}");
                return ExitCode::SUCCESS;
            }
            other => return usage(&format!("unknown option {other}")),
        }
    }

    if names.is_empty() {
        return usage("--agents is needed");
    }
    let mut agents = Vec::new();
    for name in &names {
        match bots::builtin(name) {
            Some(agent) => agents.push(agent),
            None => {
                return usage(&format!(
                    "unknown agent {name:?}; built in: {}",
                    bots::BUILTIN.join(" ")
                ))
            }
        }
    }
    config.lineup = match lineup {
        Some(places) => places,
        None if agents.len() == 2 && (2..=6).contains(&players) => {
            MatchConfig::one_against_the_rest(players, 1, 1).lineup
        }
        None => return usage("give 2 agents and --players 2 to 6, or a --lineup"),
    };
    config.stack = match stack_bb.checked_mul(config.big_blind) {
        Some(stack) => stack,
        None => return usage("--stack-bb: the stack is too large"),
    };

    let report = match run_match(&config, &agents) {
        Ok(report) => report,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::FAILURE;
        }
    };
    println!("{}", report.summary());
    if let Some(path) = out {
        if let Err(e) = report.save(&path) {
            eprintln!("{}: {e}", path.display());
            return ExitCode::FAILURE;
        }
        println!("saved {}", path.display());
    }
    ExitCode::SUCCESS
}
