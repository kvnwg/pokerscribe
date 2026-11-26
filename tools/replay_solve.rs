// A stand-in for the program `subgame-solve` that does no solving. It exists to time what
// calling the program costs apart from the solving: starting a native program, handing it
// a SPOT file and getting a RESULT file back. tools/rust_solver_overhead.py compiles it
// with `rustc -O` and runs it; nothing else uses it. Standard library only.
//
//     replay-solve <spot.json> --out <result>     (the other flags of subgame-solve are ignored)
//
// It reads the whole SPOT, then writes the RESULT named in the environment variable
// POKERSCRIBE_REPLAY_RESULT (one that the timing tool solved beforehand). With no arguments
// it exits at once, to time the start-up alone.
//
// It does not parse or write JSON, so the real program's time for that is not counted.

use std::io::Write;
use std::{env, fs, process};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        return;
    }
    let out = args
        .iter()
        .position(|a| a == "--out")
        .and_then(|i| args.get(i + 1));
    let spot = fs::read(&args[1]).unwrap_or_else(|e| fail(&format!("{}: {e}", args[1])));
    // Look at every byte, as a parser would.
    let seen = spot.iter().fold(0u64, |sum, &b| sum.wrapping_add(b as u64));
    let prepared = env::var("POKERSCRIBE_REPLAY_RESULT")
        .unwrap_or_else(|_| fail("POKERSCRIBE_REPLAY_RESULT is not set"));
    let result = fs::read(&prepared).unwrap_or_else(|e| fail(&format!("{prepared}: {e}")));
    let written = match out {
        Some(path) => fs::write(path, &result),
        None => std::io::stdout().write_all(&result),
    };
    if let Err(e) = written {
        fail(&format!("could not write the result: {e}"));
    }
    std::hint::black_box(seen);
}

fn fail(message: &str) -> ! {
    eprintln!("replay-solve: {message}");
    process::exit(1)
}
