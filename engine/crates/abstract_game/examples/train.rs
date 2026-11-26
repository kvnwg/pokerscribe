//! Trains an abstract game with external-sampling Monte Carlo CFR for a while and reports
//! the speed and the memory, next to the counted size.
//!
//! ```text
//! cargo run --release -p abstract_game --example train -- <menu> <stack bb> <bands> <iterations> [threads] [float|int]
//! cargo run --release -p abstract_game --example train -- small 100 10 200000
//! cargo run --release -p abstract_game --example train -- standard 100 0 2000000 4 int
//! ```
//!
//! `menu` is push-fold, minimal, small, standard or wide. `bands` is the number of
//! hand-strength bands on each street after the flop ([`EquityBands`], with the 169
//! starting hands kept apart before it); 0 puts every hand in one bucket after the flop,
//! which costs nothing to compute and so shows the speed of the game alone. `threads`
//! (1 if left out) is the `cfr` crate's thread count, and `int` stores regrets as 32-bit
//! integers, one unit a chip.

use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use abstract_game::{
    preflop_class, AbstractGame, Bucketer, Card, EquityBands, GameConfig, Menus, Street,
    CHIPS_PER_BIG_BLIND,
};
use cfr::{Mccfr, MccfrConfig, Sampling, Solver};

/// Counts the bytes on the heap.
struct Counting;

static IN_USE: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        IN_USE.fetch_add(layout.size(), Ordering::Relaxed);
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        IN_USE.fetch_sub(layout.size(), Ordering::Relaxed);
        unsafe { System.dealloc(ptr, layout) }
    }
}

#[global_allocator]
static ALLOCATOR: Counting = Counting;

/// The 169 starting hands, then every hand alike.
struct StartingHandsOnly;

impl Bucketer for StartingHandsOnly {
    fn num_buckets(&self, street: Street) -> u64 {
        if street == Street::Preflop {
            169
        } else {
            1
        }
    }
    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
        if board.is_empty() {
            preflop_class(hole) as u64
        } else {
            0
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let arg = |i: usize, default: &str| args.get(i).cloned().unwrap_or(default.to_string());
    let menu = arg(0, "small");
    let stack: u32 = arg(1, "100").parse().expect("stack in big blinds");
    let bands: u32 = arg(2, "10").parse().expect("bands per street");
    let iterations: u64 = arg(3, "100000").parse().expect("iterations");
    let threads: usize = arg(4, "1").parse().expect("threads");
    let integers = match arg(5, "float").as_str() {
        "float" => false,
        "int" => true,
        other => panic!("regrets are float or int, not {other}"),
    };
    let menus = match menu.as_str() {
        "push-fold" => Menus::push_fold(),
        "minimal" => Menus::minimal(),
        "small" => Menus::small(),
        "standard" => Menus::standard(),
        "wide" => Menus::wide(),
        other => panic!("unknown menu {other}"),
    };
    // The solver's threads share the game, so the bucketer has to be `Sync`.
    let bucketer: Box<dyn Bucketer + Send + Sync> = if bands == 0 {
        Box::new(StartingHandsOnly)
    } else {
        Box::new(EquityBands::new([169, bands, bands, bands]))
    };

    let before = IN_USE.load(Ordering::Relaxed);
    let start = Instant::now();
    let game = AbstractGame::new(GameConfig::new(stack, menus), bucketer).expect("a game");
    let tree_bytes = IN_USE.load(Ordering::Relaxed) - before;
    let info_sets = game.info_sets();
    let regret_bytes = game.regret_bytes();
    println!(
        "{menu} menu, {stack} bb, buckets {:?}: {} decision points (tree built in {:.2} s, {:.1} MB), \
         {info_sets} information sets, {:.1} MB of regrets",
        game.buckets(),
        game.tree().len(),
        start.elapsed().as_secs_f64(),
        tree_bytes as f64 / 1e6,
        regret_bytes as f64 / 1e6,
    );

    let mut settings = MccfrConfig::new(Sampling::External, 1).threads(threads);
    if integers {
        // Payoffs are in big blinds, so this makes one unit of regret one chip.
        settings = settings.compact(CHIPS_PER_BIG_BLIND as f64);
    }
    let mut solver = Mccfr::new(game, settings);
    let start = Instant::now();
    solver.run(iterations);
    let seconds = start.elapsed().as_secs_f64();
    let reached = solver.info_sets();
    println!(
        "{iterations} iterations on {threads} thread(s), {} regrets, in {seconds:.1} s: \
         {:.0} iterations/s, {:.2} million nodes/s, {:.0} nodes per iteration",
        if integers { "integer" } else { "float" },
        iterations as f64 / seconds,
        solver.nodes_touched() as f64 / seconds / 1e6,
        solver.nodes_touched() as f64 / iterations as f64,
    );
    // The solver's own account: its arrays grow by doubling, so the heap also holds
    // pages that were reserved and never touched.
    let memory = solver.memory();
    println!(
        "{reached} information sets reached ({:.1}% of the count); solver memory {:.1} MB, \
         {:.0} bytes per information set reached: {:.1} regrets, {:.1} strategy sums, \
         {:.1} index",
        100.0 * reached as f64 / info_sets as f64,
        (memory.index_bytes + memory.regret_bytes + memory.strategy_bytes) as f64 / 1e6,
        memory.bytes_per_info_set(),
        memory.regret_bytes as f64 / reached as f64,
        memory.strategy_bytes as f64 / reached as f64,
        memory.index_bytes as f64 / reached as f64,
    );
}
