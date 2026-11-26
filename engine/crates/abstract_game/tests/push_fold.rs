//! Heads-up push-or-fold with 10 big blinds: the abstract game (all in or fold, the 169
//! starting hands kept apart) trained with the cfr crate's external-sampling Monte Carlo
//! CFR, against `app/solver`'s `solve_push_fold`.
//!
//! The Python solution is in `fixtures/push_fold_10bb.txt`, written by
//! `fixtures/make_push_fold.py`. It works on exact all-in equities, so its answer has no
//! sampling noise; ours comes from dealt cards and has some. For each hand the fixture
//! also gives the margin: how many big blinds the better of the two actions gains over
//! the other against the equilibrium opponent. Where the margin is tiny the choice hardly
//! matters and a sampled solution can land on either side, so hands are compared from
//! `CLEAR` big blinds of margin up, and the cost of every difference is added up.
//!
//! ```text
//! cargo test --release -p abstract_game --test push_fold
//! cargo test --release -p abstract_game --test push_fold report -- --ignored --nocapture
//! ```

use abstract_game::{
    class_combos, class_from_name, class_name, raise_to, AbstractGame, GameConfig, Lossless, CALL,
    FOLD, PREFLOP_CLASSES,
};
use cfr::{Game, Mccfr, MccfrConfig, Node, Sampling, Solver};

/// Iterations of the test run (one traversal per player each).
const ITERATIONS: u64 = 40_000_000;
const SEED: u64 = 1;
/// A hand is compared when its two actions differ by at least this many big blinds.
const CLEAR: f64 = 0.05;
/// Jam and call shares must be within this of Python's (shares of the 1,326 hands).
const SHARE_TOLERANCE: f64 = 0.015;
/// Against Python's equilibrium, each seat may give up at most this many big blinds a hand.
const MAX_LOSS: f64 = 0.002;

type PerHand = [f64; PREFLOP_CLASSES];

/// The Python solution, per hand in chart order.
struct Reference {
    jam: PerHand,
    call: PerHand,
    jam_margin: PerHand,
    call_margin: PerHand,
    jam_weight: PerHand,
    call_weight: PerHand,
    jam_share: f64,
    call_share: f64,
}

fn reference() -> Reference {
    let text = include_str!("fixtures/push_fold_10bb.txt");
    let header = |name: &str| -> f64 {
        text.lines()
            .find_map(|l| l.strip_prefix(&format!("# {name} ")))
            .unwrap_or_else(|| panic!("no {name} in the fixture"))
            .parse()
            .unwrap()
    };
    let mut r = Reference {
        jam: [0.0; PREFLOP_CLASSES],
        call: [0.0; PREFLOP_CLASSES],
        jam_margin: [0.0; PREFLOP_CLASSES],
        call_margin: [0.0; PREFLOP_CLASSES],
        jam_weight: [0.0; PREFLOP_CLASSES],
        call_weight: [0.0; PREFLOP_CLASSES],
        jam_share: header("jam_share"),
        call_share: header("call_share"),
    };
    let mut hands = 0;
    for line in text.lines().filter(|l| !l.starts_with('#')) {
        let mut cols = line.split_whitespace();
        let class = class_from_name(cols.next().unwrap()).unwrap() as usize;
        // The fixture is in the same chart order as the crate's classes.
        assert_eq!(class, hands);
        let mut next = || cols.next().unwrap().parse::<f64>().unwrap();
        r.jam[class] = next();
        r.call[class] = next();
        r.jam_margin[class] = next();
        r.call_margin[class] = next();
        r.jam_weight[class] = next();
        r.call_weight[class] = next();
        hands += 1;
    }
    assert_eq!(hands, PREFLOP_CLASSES);
    r
}

fn game() -> AbstractGame<Lossless> {
    AbstractGame::new(GameConfig::push_fold(10), Lossless).unwrap()
}

/// How often each hand jams and calls in the solver's average strategy.
fn strategy(solver: &Mccfr<AbstractGame<Lossless>>) -> (PerHand, PerHand) {
    let game = solver.game();
    let policy = solver.average_policy();
    // Decision point 0 is the small blind's, 1 the big blind's after a jam.
    let second = |node: u32, class: usize| -> f64 {
        let probs = policy
            .get(game.info_key_of(node, class as u64))
            .unwrap_or_else(|| panic!("{} never reached", class_name(class as u8)));
        assert_eq!(probs.len(), 2);
        probs[1]
    };
    let mut jam = [0.0; PREFLOP_CLASSES];
    let mut call = [0.0; PREFLOP_CLASSES];
    for class in 0..PREFLOP_CLASSES {
        jam[class] = second(0, class);
        call[class] = second(1, class);
    }
    (jam, call)
}

/// One seat's comparison with Python.
struct Seat {
    /// Our share of the 1,326 hands played (jammed or called).
    share: f64,
    /// Hands with a clear margin, and those among them on the other side from Python.
    clear: usize,
    wrong: Vec<String>,
    /// Hands with a smaller margin on the other side from Python.
    close_and_different: Vec<String>,
    /// Big blinds a hand given up against Python's equilibrium by not playing each hand
    /// the better way.
    loss: f64,
}

fn compare(ours: &PerHand, theirs: &PerHand, margin: &PerHand, weight: &PerHand) -> Seat {
    let mut seat = Seat {
        share: 0.0,
        clear: 0,
        wrong: Vec::new(),
        close_and_different: Vec::new(),
        loss: 0.0,
    };
    for class in 0..PREFLOP_CLASSES {
        let name = class_name(class as u8);
        seat.share += ours[class] * class_combos(class as u8) as f64 / 1_326.0;
        let better = if margin[class] > 0.0 { 1.0 } else { 0.0 };
        seat.loss += weight[class] * margin[class].abs() * (ours[class] - better).abs();
        let differs = (ours[class] >= 0.5) != (theirs[class] >= 0.5);
        if margin[class].abs() >= CLEAR {
            seat.clear += 1;
            // Python plays a hand with a clear margin always or never.
            assert!(theirs[class] == better, "{name}: {}", theirs[class]);
            if differs {
                seat.wrong.push(format!(
                    "{name} ({:.2}, margin {:+.3})",
                    ours[class], margin[class]
                ));
            }
        } else if differs {
            seat.close_and_different.push(format!(
                "{name} ({:.2}, margin {:+.3})",
                ours[class], margin[class]
            ));
        }
    }
    seat
}

/// A 13 by 13 chart: `#` always, `+` mixed, `.` never, and a letter where the two sides
/// differ (`J` we play it and Python does not, `f` the other way round).
fn chart(ours: &PerHand, theirs: &PerHand) -> String {
    let mut out = String::from("    A K Q J T 9 8 7 6 5 4 3 2\n");
    for row in 0..13 {
        out.push_str(&format!("  {} ", b"AKQJT98765432"[row] as char));
        for col in 0..13 {
            let (o, t) = (ours[row * 13 + col], theirs[row * 13 + col]);
            let mark = match (o >= 0.5, t >= 0.5) {
                (true, false) => 'J',
                (false, true) => 'f',
                _ if o >= 0.99 => '#',
                _ if o <= 0.01 => '.',
                _ => '+',
            };
            out.push(mark);
            out.push(' ');
        }
        out.push('\n');
    }
    out
}

struct Run {
    jam: Seat,
    call: Seat,
    charts: String,
}

fn run(iterations: u64, seed: u64) -> Run {
    let r = reference();
    let mut solver = Mccfr::new(game(), MccfrConfig::new(Sampling::External, seed));
    solver.run(iterations);
    assert_eq!(solver.info_sets(), 338);
    let (jam, call) = strategy(&solver);
    Run {
        jam: compare(&jam, &r.jam, &r.jam_margin, &r.jam_weight),
        call: compare(&call, &r.call, &r.call_margin, &r.call_weight),
        charts: format!(
            "small blind jams (suited above the diagonal):\n{}big blind calls:\n{}",
            chart(&jam, &r.jam),
            chart(&call, &r.call)
        ),
    }
}

#[test]
fn the_game_is_push_or_fold() {
    let game = game();
    assert_eq!(game.tree().len(), 2);
    assert_eq!(game.info_sets(), 338);
    assert_eq!(game.regret_bytes(), 676 * 8);
    // Ten big blinds: the small blind folds or goes all in for 1,000 chips, the big blind
    // folds or calls.
    let card = |text: &str| nlhe::parse_card(text).unwrap();
    let hole = [[card("Ac"), card("Ad")], [card("2c"), card("3d")]];
    let board = ["Kc", "Qd", "9h", "7s", "4c"].map(card);
    let start = game.deal(hole, board).unwrap();
    let mut actions = Vec::new();
    game.legal_actions(&start, &mut actions);
    assert_eq!(actions, [FOLD, raise_to(1_000)]);
    let mut jammed = start;
    game.apply(&mut jammed, raise_to(1_000));
    assert_eq!(game.node(&jammed), Node::Player(1));
    actions.clear();
    game.legal_actions(&jammed, &mut actions);
    assert_eq!(actions, [FOLD, CALL]);
    // Payoffs in big blinds: fold loses the small blind, a jam that is folded to wins the
    // big blind, a called jam plays for the 10 big blind stacks.
    let mut folded = start;
    game.apply(&mut folded, FOLD);
    assert_eq!(
        (game.utility(&folded, 0), game.utility(&folded, 1)),
        (-0.5, 0.5)
    );
    let mut stolen = jammed;
    game.apply(&mut stolen, FOLD);
    assert_eq!(
        (game.utility(&stolen, 0), game.utility(&stolen, 1)),
        (1.0, -1.0)
    );
    let mut called = jammed;
    game.apply(&mut called, CALL);
    assert_eq!(game.node(&called), Node::Terminal);
    assert_eq!(
        (game.utility(&called, 0), game.utility(&called, 1)),
        (10.0, -10.0)
    );
}

#[test]
fn the_reference_is_the_python_solution() {
    let r = reference();
    // The numbers app/tests/test_solver_pushfold.py checks: about 58% of hands jam at 10
    // big blinds (The Mathematics of Poker), aces always play, 32o never calls.
    assert!((r.jam_share - 0.58).abs() < 0.01);
    assert!((r.call_share - 0.374).abs() < 0.01);
    let share = |p: &PerHand| -> f64 {
        (0..PREFLOP_CLASSES)
            .map(|c| p[c] * class_combos(c as u8) as f64 / 1_326.0)
            .sum()
    };
    assert!((share(&r.jam) - r.jam_share).abs() < 1e-8);
    assert!((share(&r.call) - r.call_share).abs() < 1e-8);
    assert_eq!((r.jam[0], r.call[0]), (1.0, 1.0));
    assert_eq!(r.call[class_from_name("32o").unwrap() as usize], 0.0);
    assert!((r.jam_weight.iter().sum::<f64>() - 1.0).abs() < 1e-8);
    // The big blind faces a jam as often as the small blind jams.
    assert!((r.call_weight.iter().sum::<f64>() - r.jam_share).abs() < 1e-6);
}

#[test]
#[cfg_attr(
    debug_assertions,
    ignore = "slow in a debug build: cargo test --release"
)]
fn trained_push_or_fold_matches_the_python_solver() {
    let r = reference();
    let run = run(ITERATIONS, SEED);
    println!("{}", run.charts);
    for (name, seat, share) in [
        ("jam", &run.jam, r.jam_share),
        ("call", &run.call, r.call_share),
    ] {
        println!(
            "{name}: share {:.4} (Python {share:.4}); {} of 169 hands have a margin of {CLEAR} or \
             more and {} of them differ; closer hands that differ: {:?}; loss {:.5} bb a hand",
            seat.share,
            seat.clear,
            seat.wrong.len(),
            seat.close_and_different,
            seat.loss
        );
        assert!(seat.wrong.is_empty(), "{name}: {:?}", seat.wrong);
        assert!(
            (seat.share - share).abs() < SHARE_TOLERANCE,
            "{name} share {}",
            seat.share
        );
        assert!(seat.loss < MAX_LOSS, "{name} loss {}", seat.loss);
    }
    // The comparison covers nearly every hand: 18 jams and 3 calls are closer than CLEAR.
    assert_eq!((run.jam.clear, run.call.clear), (151, 166));
}

/// Other seeds and run lengths, to see how much room the test has. `PF_ITERATIONS` and
/// `PF_SEEDS` (comma-separated) choose them.
#[test]
#[ignore = "a report, not a check: run with --ignored --nocapture"]
fn report() {
    let list = |name: &str, default: &str| -> Vec<u64> {
        std::env::var(name)
            .unwrap_or(default.to_string())
            .split(',')
            .map(|x| x.trim().parse().expect("a number"))
            .collect()
    };
    for iterations in list("PF_ITERATIONS", "5000000,20000000,40000000") {
        for seed in list("PF_SEEDS", "1,2,3,4") {
            let start = std::time::Instant::now();
            let run = run(iterations, seed);
            println!(
                "{iterations} iterations, seed {seed}, {:.1} s: jam share {:.4} wrong {:?} close {:?} loss {:.5}; \
                 call share {:.4} wrong {:?} close {:?} loss {:.5}",
                start.elapsed().as_secs_f64(),
                run.jam.share,
                run.jam.wrong,
                run.jam.close_and_different,
                run.jam.loss,
                run.call.share,
                run.call.wrong,
                run.call.close_and_different,
                run.call.loss,
            );
        }
    }
}
