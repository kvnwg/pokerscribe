//! Speed per thread count and memory per information set.
//!
//!     cargo run --release -p cfr --example scale
//!     cargo run --release -p cfr --example scale -- leduc3 2000000
//!
//! Optional: a part (kuhn3, leduc, leduc3, wide, memory, checkpoint; default
//! all) and the iterations per run. For 1, 2, 4 and every core: external
//! sampling from scratch for that many iterations, with the time, the speed
//! and how far the average strategy is from equilibrium at the end. Then
//! what the tables take with regrets as floats and as 32-bit integers, and
//! how long a checkpoint of the biggest game takes to save and to load.
//!
//! Kuhn and Leduc are so small that every thread writes the same few cache
//! lines all the time, which is the worst case for sharing. `wide` is the
//! other end: Leduc's betting with a deck of 300 different cards, millions
//! of information sets, where two traversals rarely meet below the first
//! few decisions. A blueprint is far bigger still.

use std::time::Instant;

use cfr::{nash_conv, Action, Game, InfoKey, Mccfr, MccfrConfig, Node, Rng, Sampling, Solver};
use toygames::{Kuhn, Leduc};

/// Two betting rounds with a public card between them, as in Leduc (ante 1,
/// bets of 2 then 4, two raises a round), but every card of the deck is
/// different and the best hand is an arbitrary function of the private and
/// the public card. Not a game anyone plays: a tree with many information
/// sets, to time the solver on.
#[derive(Clone, Copy)]
struct Wide {
    cards: u32,
}

const NO_CARD: u32 = u32::MAX;

#[derive(Clone, Copy)]
struct WideState {
    private: [u32; 2],
    public: u32,
    /// Chips each player has put in.
    paid: [u32; 2],
    /// The actions so far, two bits each after a leading 1.
    history: u32,
    round: u8,
    raises: u8,
    /// Actions taken in this round.
    acted: u8,
    to_act: u8,
    folded: u8,
    over: bool,
}

impl Wide {
    fn strength(&self, private: u32, public: u32) -> u32 {
        (private.wrapping_mul(2_654_435_761) ^ public.wrapping_mul(40_503)) % 1_000
    }

    fn facing_bet(s: &WideState) -> bool {
        s.paid[0] != s.paid[1]
    }
}

impl Game for Wide {
    type State = WideState;

    fn num_players(&self) -> usize {
        2
    }

    fn root(&self) -> WideState {
        WideState {
            private: [NO_CARD; 2],
            public: NO_CARD,
            paid: [1, 1],
            history: 1,
            round: 0,
            raises: 0,
            acted: 0,
            to_act: 0,
            folded: 2,
            over: false,
        }
    }

    fn node(&self, s: &WideState) -> Node {
        if s.over {
            Node::Terminal
        } else if s.private[1] == NO_CARD || (s.round == 1 && s.public == NO_CARD) {
            Node::Chance
        } else {
            Node::Player(s.to_act as usize)
        }
    }

    fn chance_outcomes(&self, s: &WideState, out: &mut Vec<(Action, f64)>) {
        let taken = [s.private[0], s.private[1]];
        let left = self.cards - taken.iter().filter(|&&c| c != NO_CARD).count() as u32;
        let p = 1.0 / left as f64;
        out.extend(
            (0..self.cards)
                .filter(|c| !taken.contains(c))
                .map(|c| (c, p)),
        );
    }

    fn sample_chance(&self, s: &WideState, rng: &mut Rng, _: &mut Vec<(Action, f64)>) -> Action {
        loop {
            let c = rng.below(self.cards as usize) as u32;
            if c != s.private[0] && c != s.private[1] {
                return c;
            }
        }
    }

    fn legal_actions(&self, s: &WideState, out: &mut Vec<Action>) {
        // 0 folds or checks, 1 calls or bets, 2 raises.
        out.push(0);
        out.push(1);
        if Wide::facing_bet(s) && s.raises < 2 {
            out.push(2);
        }
    }

    fn apply(&self, s: &mut WideState, action: Action) {
        if s.private[0] == NO_CARD {
            s.private[0] = action;
            return;
        }
        if s.private[1] == NO_CARD {
            s.private[1] = action;
            return;
        }
        if s.round == 1 && s.public == NO_CARD {
            s.public = action;
            return;
        }
        let me = s.to_act as usize;
        let bet = if s.round == 0 { 2 } else { 4 };
        let facing = Wide::facing_bet(s);
        s.history = s.history << 2 | action;
        s.acted += 1;
        s.to_act ^= 1;
        let closes = match (facing, action) {
            (true, 0) => {
                s.folded = me as u8;
                s.over = true;
                return;
            }
            (true, 1) => {
                s.paid[me] = s.paid[me ^ 1];
                true
            }
            (true, _) => {
                s.paid[me] = s.paid[me ^ 1] + bet;
                s.raises += 1;
                false
            }
            (false, 0) => s.acted == 2,
            (false, _) => {
                s.paid[me] += bet;
                s.raises += 1;
                false
            }
        };
        if closes {
            if s.round == 1 {
                s.over = true;
            } else {
                s.round = 1;
                s.raises = 0;
                s.acted = 0;
                s.to_act = 0;
            }
        }
    }

    fn info_key(&self, s: &WideState) -> InfoKey {
        let me = s.to_act as u64;
        let public = if s.public == NO_CARD {
            0
        } else {
            s.public as u64 + 1
        };
        me | (s.private[s.to_act as usize] as u64) << 1 | public << 21 | (s.history as u64) << 41
    }

    fn utility(&self, s: &WideState, player: usize) -> f64 {
        let winner = if s.folded < 2 {
            Some(s.folded as usize ^ 1)
        } else {
            let a = self.strength(s.private[0], s.public);
            let b = self.strength(s.private[1], s.public);
            (a != b).then_some((b > a) as usize)
        };
        match winner {
            Some(w) if w == player => s.paid[player ^ 1] as f64,
            Some(_) => -(s.paid[player] as f64),
            None => 0.0,
        }
    }
}

fn thread_counts() -> Vec<usize> {
    let all = std::thread::available_parallelism().map_or(1, |n| n.get());
    let mut counts = vec![1, 2, 4, all];
    counts.retain(|&c| c <= all.max(4));
    counts.sort_unstable();
    counts.dedup();
    counts
}

fn speed<G: Game + Copy + Sync>(label: &str, game: G, iterations: u64, exact: bool) {
    println!("\n{label}: external sampling, {iterations} iterations from scratch");
    println!(
        "  threads |  seconds | iterations/s | M nodes/s | speed-up | exploitability | info sets"
    );
    let mut base = 0.0;
    for threads in thread_counts() {
        let cfg = MccfrConfig::new(Sampling::External, 1).threads(threads);
        let mut solver = Mccfr::new(game, cfg);
        let t0 = Instant::now();
        solver.run(iterations);
        let secs = t0.elapsed().as_secs_f64();
        let rate = iterations as f64 / secs;
        if threads == 1 {
            base = rate;
        }
        let expl = if exact {
            format!(
                "{:.2e}",
                nash_conv(&game, &solver.average_policy()) / game.num_players() as f64
            )
        } else {
            "-".to_string()
        };
        println!(
            "  {threads:7} | {secs:8.2} | {rate:12.0} | {:9.1} | {:7.2}x | {expl:>14} | {}",
            solver.nodes_touched() as f64 / secs / 1e6,
            rate / base,
            solver.info_sets(),
        );
    }
}

fn memory<G: Game + Copy + Sync>(label: &str, game: G, iterations: u64) {
    println!("\n{label}: memory after {iterations} iterations");
    println!(
        "  regrets | info sets |   slots | index B/set | regrets B/set | sums B/set | total B/set | B/slot"
    );
    let es = MccfrConfig::new(Sampling::External, 1);
    for (name, cfg) in [("f64", es), ("i32", es.compact(1_000.0))] {
        let mut solver = Mccfr::new(game, cfg);
        solver.run(iterations);
        let m = solver.memory();
        let per = |bytes: usize| bytes as f64 / m.info_sets as f64;
        println!(
            "  {name:7} | {:9} | {:7} | {:11.1} | {:13.1} | {:10.1} | {:11.1} | {:6.1}",
            m.info_sets,
            m.slots,
            per(m.index_bytes),
            per(m.regret_bytes),
            per(m.strategy_bytes),
            m.bytes_per_info_set(),
            (m.regret_bytes + m.strategy_bytes) as f64 / m.slots as f64,
        );
    }
}

fn checkpoint<G: Game + Copy + Sync>(label: &str, game: G, iterations: u64) {
    println!("\n{label}: checkpoint after {iterations} iterations (4 threads)");
    println!("  regrets | info sets |  file MB | save s | save MB/s | load s | load MB/s");
    let es = MccfrConfig::new(Sampling::External, 1).threads(4);
    let path = std::env::temp_dir().join(format!("cfr-scale-{}.ckpt", std::process::id()));
    for (name, cfg) in [("f64", es), ("i32", es.compact(1_000.0))] {
        let mut solver = Mccfr::new(game, cfg);
        solver.run(iterations);
        let t0 = Instant::now();
        solver.save(&path).expect("save");
        let save = t0.elapsed().as_secs_f64();
        let mb = std::fs::metadata(&path).expect("checkpoint").len() as f64 / 1e6;
        let t0 = Instant::now();
        let back = Mccfr::resume(game, &path).expect("load");
        let load = t0.elapsed().as_secs_f64();
        assert_eq!(back.info_sets(), solver.info_sets());
        println!(
            "  {name:7} | {:9} | {mb:8.1} | {save:6.2} | {:9.0} | {load:6.2} | {:9.0}",
            solver.info_sets(),
            mb / save,
            mb / load,
        );
    }
    let _ = std::fs::remove_file(&path);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let only = args.first().map(String::as_str);
    let iterations: Option<u64> = args.get(1).map(|s| s.parse().expect("iterations"));
    println!(
        "{} cores",
        std::thread::available_parallelism().map_or(1, |n| n.get())
    );
    if only.is_none_or(|g| g == "kuhn3") {
        speed(
            "Kuhn, 3 players (48 information sets)",
            Kuhn::new(3),
            iterations.unwrap_or(4_000_000),
            true,
        );
    }
    if only.is_none_or(|g| g == "leduc") {
        speed(
            "Leduc, 2 players (936 information sets)",
            Leduc::new(2),
            iterations.unwrap_or(4_000_000),
            true,
        );
    }
    if only.is_none_or(|g| g == "leduc3") {
        speed(
            "Leduc, 3 players",
            Leduc::new(3),
            iterations.unwrap_or(4_000_000),
            false,
        );
    }
    let wide = Wide { cards: 300 };
    if only.is_none_or(|g| g == "wide") {
        speed(
            "Wide, 300 cards (2.7 million information sets by the end)",
            wide,
            iterations.unwrap_or(8_000_000),
            false,
        );
    }
    if only.is_none() || only == Some("memory") {
        memory("Kuhn, 3 players", Kuhn::new(3), 200_000);
        memory("Leduc, 2 players", Leduc::new(2), 1_000_000);
        memory("Leduc, 3 players", Leduc::new(3), 4_000_000);
        memory("Wide, 300 cards", wide, 8_000_000);
    }
    if only.is_none() || only == Some("checkpoint") {
        checkpoint("Wide, 300 cards", wide, 8_000_000);
    }
}
