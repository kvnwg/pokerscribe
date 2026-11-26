//! Prints the size of the abstract game for a grid of settings: the tables in README.md.
//!
//! ```text
//! cargo run --release -p abstract_game --example sizes
//! ```

use std::time::Instant;

use abstract_game::{GameConfig, Menus, TreeSize, LOSSLESS_BUCKETS};

/// Buckets per street as Pluribus had them: every starting hand, then 200 a street.
const PLURIBUS_LIKE: [u64; 4] = [169, 200, 200, 200];
/// A coarse grouping, the scale of [`abstract_game::EquityBands`] in tests.
const COARSE: [u64; 4] = [169, 10, 10, 10];

fn main() {
    let menus = [
        ("minimal", Menus::minimal()),
        ("small", Menus::small()),
        ("standard", Menus::standard()),
        ("wide", Menus::wide()),
    ];
    let stacks = [20, 50, 100, 200];

    println!("## The betting tree\n");
    println!("| Menu | Stack (bb) | Decision points | Preflop | Flop | Turn | River | Actions | Ways to end | Most actions | Longest hand |");
    println!("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");
    let mut sizes: Vec<(String, u32, TreeSize)> = Vec::new();
    let push_fold = GameConfig::push_fold(10).tree_size().unwrap();
    tree_row("push-or-fold", 10, &push_fold);
    sizes.push(("push-or-fold".into(), 10, push_fold));
    for (name, menu) in &menus {
        for &stack in &stacks {
            let start = Instant::now();
            let size = GameConfig::new(stack, menu.clone()).tree_size().unwrap();
            let took = start.elapsed().as_secs_f64();
            tree_row(name, stack, &size);
            if took > 1.0 {
                eprintln!("({name} at {stack} bb took {took:.1} s to count)");
            }
            sizes.push((name.to_string(), stack, size));
        }
    }

    let groupings = [COARSE, PLURIBUS_LIKE, LOSSLESS_BUCKETS];
    println!("\n## Information sets and regret memory\n");
    println!(
        "| Menu | Stack (bb) | 10 buckets a street | Regrets | 200 buckets a street | Regrets | No card abstraction | Regrets |"
    );
    println!("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");
    for (name, stack, size) in &sizes {
        let mut row = format!("| {name} | {stack} |");
        for buckets in groupings {
            // Push-or-fold never reaches the flop.
            let buckets = if size.decisions[1] == 0 {
                [buckets[0], 0, 0, 0]
            } else {
                buckets
            };
            row.push_str(&format!(
                " {} | {} |",
                count(size.info_sets(buckets)),
                bytes(size.regret_bytes(buckets, 8))
            ));
        }
        println!("{row}");
    }
}

fn tree_row(name: &str, stack: u32, size: &TreeSize) {
    println!(
        "| {name} | {stack} | {} | {} | {} | {} | {} | {} | {} | {} | {} |",
        count(size.decision_points()),
        count(size.decisions[0]),
        count(size.decisions[1]),
        count(size.decisions[2]),
        count(size.decisions[3]),
        count(size.actions.iter().sum()),
        count(size.terminals()),
        size.max_actions,
        size.longest,
    );
}

/// A count with thousands separators, or in scientific notation from a trillion up.
fn count(n: u128) -> String {
    if n >= 1_000_000_000_000 {
        return format!("{:.2e}", n as f64);
    }
    let digits = n.to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}

fn bytes(n: u128) -> String {
    const UNITS: [&str; 7] = ["B", "KB", "MB", "GB", "TB", "PB", "EB"];
    let mut x = n as f64;
    let mut unit = 0;
    while x >= 1024.0 && unit + 1 < UNITS.len() {
        x /= 1024.0;
        unit += 1;
    }
    if unit == 0 {
        format!("{n} B")
    } else if x >= 1024.0 {
        format!("{x:.2e} {}", UNITS[unit])
    } else {
        format!("{x:.1} {}", UNITS[unit])
    }
}
