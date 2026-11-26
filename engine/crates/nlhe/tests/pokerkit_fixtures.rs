//! Replays the hands from tools/reference/nlhe_fixtures.py (PokerKit 0.7.8) and checks,
//! at every step, whose turn it is, the street, every stack, the legal actions and the
//! raise range, and at the end the final stacks. See that script for the line format.
//!
//! PokerKit's player 0 is the seat after the button. Each hand here puts the button on a
//! different seat (hand index mod players), so the seat arithmetic is tested too.
//!
//! Showdowns are ranked by `BruteForceRanker`, and again by `EvalRanker` (the eval crate's
//! evaluator, feature `eval`): PokerKit's final stacks must come out with either.

#[cfg(feature = "eval")]
use nlhe::EvalRanker;
use nlhe::{Action, BruteForceRanker, Card, Chips, Config, Deal, HandRanker, RaiseRange, State};

const FIXTURES: &str = include_str!("fixtures/pokerkit_nlhe.txt");

struct Step {
    player: usize,
    street: usize,
    /// Every player's chips behind, PokerKit order.
    stacks: Vec<Chips>,
    fold: bool,
    call: Chips,
    raise: Option<RaiseRange>,
    flag: char,
    action: Action,
}

struct Hand {
    n: usize,
    sb: Chips,
    bb: Chips,
    ante: Chips,
    stacks: Vec<Chips>,
    cards: Vec<Card>,
    steps: Vec<Step>,
    final_stacks: Vec<Chips>,
    /// (amount, PokerKit players) for each pot when a showdown starts.
    pots: Option<Vec<(Chips, Vec<usize>)>>,
}

fn numbers<T: std::str::FromStr>(field: &str) -> Vec<T>
where
    T::Err: std::fmt::Debug,
{
    field
        .split_whitespace()
        .map(|x| x.parse().unwrap())
        .collect()
}

fn parse_hand(line: &str) -> Hand {
    let fields: Vec<&str> = line.split(" | ").collect();
    assert_eq!(fields.len(), 6, "bad line: {line}");
    let head: Vec<Chips> = numbers(fields[0]);
    let steps = fields[3]
        .split_whitespace()
        .map(|s| {
            let p: Vec<&str> = s.split(',').collect();
            assert_eq!(p.len(), 9, "bad step {s}");
            let raise = match (p[5], p[6]) {
                ("-", "-") => None,
                (lo, hi) => Some(RaiseRange {
                    min_to: lo.parse().unwrap(),
                    max_to: hi.parse().unwrap(),
                }),
            };
            let action = match p[8] {
                "f" => Action::Fold,
                "k" => Action::Check,
                "c" => Action::Call,
                r => Action::RaiseTo(r.strip_prefix('r').expect("action").parse().unwrap()),
            };
            Step {
                player: p[0].parse().unwrap(),
                street: p[1].parse().unwrap(),
                stacks: p[2].split('/').map(|x| x.parse().unwrap()).collect(),
                fold: p[3] == "1",
                call: p[4].parse().unwrap(),
                raise,
                flag: p[7].chars().next().unwrap(),
                action,
            }
        })
        .collect();
    Hand {
        n: head[0] as usize,
        sb: head[1],
        bb: head[2],
        ante: head[3],
        stacks: numbers(fields[1]),
        cards: numbers(fields[2]),
        steps,
        final_stacks: numbers(fields[4]),
        pots: (fields[5] != "-").then(|| {
            fields[5]
                .split_whitespace()
                .map(|pot| {
                    let (amount, players) = pot.split_once(':').unwrap();
                    (
                        amount.parse().unwrap(),
                        players.split('.').map(|p| p.parse().unwrap()).collect(),
                    )
                })
                .collect()
        }),
    }
}

/// Plays one fixture hand with the button on `button`, ranking the showdown with `ranker`.
/// Returns a description of the first difference, if any.
fn replay<R: HandRanker>(hand: &Hand, button: usize, ranker: &R) -> Result<(), String> {
    let n = hand.n;
    let seat = |p: usize| (button + 1 + p) % n;
    let mut stacks = vec![0; n];
    let mut hole = vec![[0; 2]; n];
    for p in 0..n {
        stacks[seat(p)] = hand.stacks[p];
        hole[seat(p)] = [hand.cards[2 * p], hand.cards[2 * p + 1]];
    }
    let b = &hand.cards[2 * n..2 * n + 5];
    let config =
        Config::new(&stacks, hand.sb, hand.bb, hand.ante, button).map_err(|e| e.to_string())?;
    let deal = Deal::new(&hole, [b[0], b[1], b[2], b[3], b[4]]).map_err(|e| e.to_string())?;
    let mut state = State::new(&config, deal).map_err(|e| e.to_string())?;

    for (k, step) in hand.steps.iter().enumerate() {
        let want_seat = seat(step.player);
        if state.current_player() != Some(want_seat) {
            return Err(format!(
                "step {k}: to act {:?}, want seat {want_seat}",
                state.current_player()
            ));
        }
        if state.street().index() != step.street {
            return Err(format!(
                "step {k}: street {:?}, want {}",
                state.street(),
                step.street
            ));
        }
        let behind: Vec<Chips> = (0..n)
            .map(|s| step.stacks[(s + n - button - 1) % n])
            .collect();
        if state.stacks() != &behind[..] {
            return Err(format!(
                "step {k}: stacks {:?}, want {:?}",
                state.stacks(),
                behind
            ));
        }
        let legal = state.legal_actions();
        let want_call = (step.call > 0).then_some(step.call);
        if legal.fold != step.fold || legal.check != (step.call == 0) || legal.call != want_call {
            return Err(format!(
                "step {k}: fold/check/call {}/{}/{:?}, want {}/{}/{:?}",
                legal.fold,
                legal.check,
                legal.call,
                step.fold,
                step.call == 0,
                want_call
            ));
        }
        if legal.raise != step.raise {
            return Err(format!(
                "step {k}: raise {:?}, want {:?} (flag {})",
                legal.raise, step.raise, step.flag
            ));
        }
        state
            .apply(step.action)
            .map_err(|e| format!("step {k}: {e}"))?;
    }
    if !state.is_terminal() {
        return Err(format!(
            "hand not over after the fixture's actions; seat {:?} to act",
            state.current_player()
        ));
    }
    if state.history().len() != hand.steps.len() {
        return Err("history length differs".into());
    }
    if let Some(want_pots) = &hand.pots {
        let got: Vec<(Chips, u8)> = state
            .pots()
            .as_slice()
            .iter()
            .map(|p| (p.amount, p.eligible))
            .collect();
        let want: Vec<(Chips, u8)> = want_pots
            .iter()
            .map(|(a, ps)| (*a, ps.iter().fold(0u8, |m, &p| m | 1 << seat(p))))
            .collect();
        if got != want {
            return Err(format!(
                "showdown pots {got:?}, want {want:?} (amount, seat mask)"
            ));
        }
    } else if state.active_mask().count_ones() != 1 {
        return Err("PokerKit had no showdown".into());
    }
    let fin = state.final_stacks(ranker).unwrap();
    let want: Vec<Chips> = (0..n)
        .map(|s| hand.final_stacks[(s + n - button - 1) % n])
        .collect();
    if fin[..n] != want[..] {
        return Err(format!("final stacks {:?}, want {:?}", &fin[..n], want));
    }
    Ok(())
}

/// Replays every hand with the button on its own seat (hand index mod players).
fn check_every_hand<R: HandRanker>(ranker: &R) {
    let mut hands = 0;
    let mut steps = 0;
    let mut showdowns = 0;
    let mut flags = [0usize; 2];
    let mut players = [0usize; 7];
    let mut failures = Vec::new();
    for (line_no, line) in FIXTURES.lines().enumerate() {
        if line.starts_with('#') || line.is_empty() {
            continue;
        }
        let hand = parse_hand(line);
        let button = hands % hand.n;
        hands += 1;
        steps += hand.steps.len();
        showdowns += hand.pots.is_some() as usize;
        players[hand.n] += 1;
        for s in &hand.steps {
            match s.flag {
                'D' => flags[0] += 1,
                'A' => flags[1] += 1,
                _ => {}
            }
        }
        if let Err(e) = replay(&hand, button, ranker) {
            failures.push(format!("line {}: {e}", line_no + 1));
        }
    }
    println!(
        "{hands} hands, {steps} decisions, {showdowns} showdowns, players {:?}, \
         reopening flags D={} A={}",
        &players[2..],
        flags[0],
        flags[1]
    );
    assert_eq!(hands, 10_000);
    assert!(players[2] > 0 && players[6] > 0);
    assert!(showdowns > 5_000, "most hands should reach a showdown");
    assert!(
        flags[0] > 0 && flags[1] > 0,
        "the fixtures should exercise both reopening cases"
    );
    assert!(
        failures.is_empty(),
        "{} of {hands} hands differ:\n{}",
        failures.len(),
        failures[..failures.len().min(20)].join("\n")
    );
}

/// The same hands with the button on every other seat.
fn check_every_button<R: HandRanker>(ranker: &R) {
    let mut failures = Vec::new();
    for (k, line) in FIXTURES
        .lines()
        .filter(|l| !l.starts_with('#') && !l.is_empty())
        .enumerate()
    {
        let hand = parse_hand(line);
        for button in 0..hand.n {
            if button == k % hand.n {
                continue;
            }
            if let Err(e) = replay(&hand, button, ranker) {
                failures.push(format!("hand {k} button {button}: {e}"));
            }
        }
    }
    assert!(
        failures.is_empty(),
        "{} differ:\n{}",
        failures.len(),
        failures[..failures.len().min(20)].join("\n")
    );
}

#[test]
fn every_pokerkit_hand_matches() {
    check_every_hand(&BruteForceRanker);
}

#[test]
fn every_hand_matches_with_the_button_anywhere() {
    check_every_button(&BruteForceRanker);
}

#[cfg(feature = "eval")]
#[test]
fn every_pokerkit_hand_matches_with_the_eval_ranker() {
    check_every_hand(&EvalRanker);
}

#[cfg(feature = "eval")]
#[test]
fn every_hand_matches_with_the_button_anywhere_with_the_eval_ranker() {
    check_every_button(&EvalRanker);
}
