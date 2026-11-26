//! Whole matches: the four properties the arena is for, and the bookkeeping around them.

// Loops over seat numbers read better than iterator chains over several arrays at once.
#![allow(clippy::needless_range_loop)]

use std::sync::{Arc, Mutex};

use arena::bots::{self, AlwaysCall, AlwaysFold, RandomBot, TightAggressive};
use arena::{
    position_name, run_match, run_match_scored, Agent, HandRecord, MatchConfig, MatchReport,
    Player, Scorer, View,
};
use nlhe::{Action, Card};

fn agents(names: &[&str]) -> Vec<Agent> {
    names.iter().map(|n| bots::builtin(n).unwrap()).collect()
}

/// The result of the second agent: the one a default lineup moves through every seat.
fn second(report: &MatchReport) -> &arena::AgentResult {
    report.result_of(1).unwrap()
}

fn show(label: &str, report: &MatchReport) {
    let r = second(report);
    println!(
        "{label}: {} {:+.2} bb/100, SE {:.2}, z {:+.1} ({} hands)",
        r.agent,
        r.bb_per_100,
        r.se.unwrap(),
        r.z().unwrap_or(0.0),
        report.hands
    );
}

// ----- 1. identical agents give 0 within the standard error -----

#[test]
fn identical_agents_give_zero_within_the_standard_error() {
    // Heads-up and six-max, plain and duplicate, over several seeds. The two agents are
    // separate copies of the same bot with their own random numbers.
    for seed in [1, 2, 3] {
        for (names, players, deals) in [
            (["random", "random"], 2, 3_000),
            (["tag", "tag"], 2, 2_000),
            (["random", "random"], 6, 600),
            (["tag", "tag"], 6, 300),
        ] {
            for duplicate in [false, true] {
                let config = MatchConfig {
                    duplicate,
                    ..MatchConfig::one_against_the_rest(players, deals, seed)
                };
                let report = run_match(&config, &agents(&names)).unwrap();
                let r = second(&report);
                let se = r.se.unwrap();
                show(
                    &format!("{players} players, duplicate {duplicate}, seed {seed}"),
                    &report,
                );
                assert!(se > 0.0);
                assert!(
                    r.bb_per_100.abs() < 3.0 * se,
                    "{} bb/100 is not 0 within 3 standard errors of {se}",
                    r.bb_per_100
                );
            }
        }
    }
}

#[test]
fn identical_agents_without_randomness_give_exactly_zero_in_duplicate() {
    // Bots that make no random choice play the two replays of a deal the same way, so
    // what one copy wins in a seat the other wins there too.
    for names in [["call", "call"], ["raise", "raise"], ["fold", "fold"]] {
        let report = run_match(&MatchConfig::heads_up(500, 9), &agents(&names)).unwrap();
        for r in &report.results {
            assert!(r.bb_per_100.abs() < 1e-9 && r.se.unwrap() < 1e-9, "{r:?}");
            assert_eq!(r.actual_bb_per_100, 0.0);
        }
    }
    // With shared randomness the same holds for bots that do make random choices.
    let config = MatchConfig {
        shared_randomness: true,
        ..MatchConfig::one_against_the_rest(6, 200, 9)
    };
    for names in [["random", "random"], ["tag", "tag"]] {
        let report = run_match(&config, &agents(&names)).unwrap();
        for r in &report.results {
            assert!(r.bb_per_100.abs() < 1e-9 && r.se.unwrap() < 1e-9, "{r:?}");
        }
    }
}

// ----- 2. a clearly better bot beats a clearly worse one -----

#[test]
fn a_better_bot_beats_a_worse_one() {
    for (names, players, deals) in [
        (["fold", "call"], 2, 500),
        (["call", "tag"], 2, 2_000),
        (["random", "tag"], 2, 3_000),
        (["fold", "tag"], 6, 300),
        (["call", "tag"], 6, 400),
    ] {
        let config = MatchConfig::one_against_the_rest(players, deals, 4);
        let report = run_match(&config, &agents(&names)).unwrap();
        show(
            &format!("{} against {} at {players}", names[1], names[0]),
            &report,
        );
        let better = second(&report);
        let worse = report.result_of(0).unwrap();
        assert!(
            better.z().unwrap() > 4.0,
            "{} does not beat {} by 4 standard errors: {better:?}",
            names[1],
            names[0]
        );
        assert!(worse.bb_per_100 < 0.0);
        // No rake: what one side wins the other loses, per seat it holds.
        let total = better.bb_per_100 * better.seats as f64 + worse.bb_per_100 * worse.seats as f64;
        assert!(total.abs() < 1e-6, "{total}");
    }
}

// ----- 3. duplicate and all-in equity cut the standard error -----

#[test]
fn duplicate_and_all_in_equity_cut_the_standard_error() {
    // A new version against the last one: tag-loose against tag. Same number of hands
    // played each way.
    for (players, hands, at_least) in [(2u64, 16_000u64, 1.6), (6, 12_000, 1.3)] {
        let duplicate = MatchConfig::one_against_the_rest(players as usize, hands / players, 12);
        let plain = MatchConfig {
            deals: hands,
            ..duplicate.clone()
        }
        .plain();
        let bots = agents(&["tag", "tag-loose"]);
        let p = run_match(&plain, &bots).unwrap();
        let d = run_match(&duplicate, &bots).unwrap();
        assert_eq!((p.hands, d.hands), (hands, hands));
        let (plain_se, se) = (second(&p).se.unwrap(), second(&d).se.unwrap());
        println!(
            "{players} players, {hands} hands: plain SE {plain_se:.2}, duplicate + all-in equity \
             SE {se:.2}, {:.2} times smaller (as good as {:.1} times the hands)",
            plain_se / se,
            (plain_se / se).powi(2)
        );
        assert!(
            plain_se > at_least * se,
            "plain {plain_se} against {se} with duplicate and all-in equity"
        );
        // The duplicate run's own estimate of the plain standard error agrees.
        let estimate = second(&d).plain_se.unwrap();
        assert!(
            (estimate / plain_se - 1.0).abs() < 0.15,
            "{estimate} against {plain_se}"
        );
        // And both runs measure the same win rate.
        let gap = second(&p).bb_per_100 - second(&d).bb_per_100;
        assert!(
            gap.abs() < 3.5 * (plain_se * plain_se + se * se).sqrt(),
            "{gap}"
        );
    }
}

#[test]
fn all_in_equity_alone_cuts_the_standard_error_and_keeps_the_mean() {
    // A match with many all-ins: the pot-raiser against the random bot, plain play.
    let config = MatchConfig {
        duplicate: false,
        ..MatchConfig::heads_up(20_000, 3)
    };
    let report = run_match(&config, &agents(&["random", "raise"])).unwrap();
    let r = second(&report);
    let (se, actual_se) = (r.se.unwrap(), r.actual_se.unwrap());
    println!(
        "all-in equity alone: SE {actual_se:.2} to {se:.2}, {} of {} hands adjusted",
        report.adjusted_hands, report.hands
    );
    assert!(report.adjusted_hands > report.hands / 20);
    assert!(se < 0.85 * actual_se, "{se} against {actual_se}");
    assert_eq!(
        r.plain_se, r.actual_se,
        "plain play: every hand is its own sample"
    );
    // The adjusted and the real win rate are two measures of the same thing.
    assert!((r.bb_per_100 - r.actual_bb_per_100).abs() < 3.0 * actual_se);
}

// ----- 4. the same seed gives the same result -----

#[test]
fn the_same_seed_gives_the_same_result() {
    let bots = agents(&["random", "tag", "raise"]);
    let config = MatchConfig::new(&[0, 1, 2, 0, 1, 2], 250, 77);
    let first = run_match(&config, &bots).unwrap();
    let again = run_match(&config, &bots).unwrap();
    assert_eq!(first.results, again.results);
    assert_eq!(first.adjusted_hands, again.adjusted_hands);

    // The number of threads changes nothing, to the last bit.
    for threads in [1, 2, 3] {
        let report = run_match(
            &MatchConfig {
                threads,
                ..config.clone()
            },
            &bots,
        )
        .unwrap();
        assert_eq!(report.results, first.results, "{threads} threads");
        assert_eq!(report.timing.threads, threads);
    }

    // Another seed is another match.
    let other = run_match(
        &MatchConfig {
            seed: 78,
            ..config.clone()
        },
        &bots,
    )
    .unwrap();
    assert_ne!(other.results, first.results);

    // More deals with the same seed start with the same deals.
    let agents = agents(&["call", "tag"]);
    let short = run_match(&MatchConfig::heads_up(32, 5), &agents).unwrap();
    let long = run_match(&MatchConfig::heads_up(64, 5), &agents).unwrap();
    assert_ne!(short.results, long.results);
    let recorded = |deals| {
        let log = Arc::new(Mutex::new(Vec::new()));
        let config = MatchConfig {
            threads: 1,
            ..MatchConfig::heads_up(deals, 5)
        };
        run_match(&config, &[recorder(0, &log), recorder(1, &log)]).unwrap();
        let log = log.lock().unwrap().clone();
        log
    };
    assert_eq!(recorded(40)[..], recorded(80)[..160]);
}

// ----- seats and rotations -----

/// What the recorders write: (agent, seat, hole cards) at the start of each hand.
type Log = Arc<Mutex<Vec<(usize, usize, [Card; 2])>>>;

/// Checks or calls, and writes down where it sits and what it holds.
#[derive(Clone)]
struct Recorder {
    agent: usize,
    log: Log,
}

impl Player for Recorder {
    fn begin_hand(&mut self, view: &View<'_>) {
        self.log
            .lock()
            .unwrap()
            .push((self.agent, view.seat(), view.hole()));
    }
    fn act(&mut self, view: &View<'_>) -> Action {
        view.check_or_call()
    }
}

fn recorder(agent: usize, log: &Log) -> Agent {
    let player = Recorder {
        agent,
        log: Arc::clone(log),
    };
    Agent::of(format!("recorder {agent}"), player)
}

/// Plays a match of recorders on one thread and returns, per hand, the agent and the
/// hole cards in each seat.
fn seatings(config: &MatchConfig, agents: usize) -> Vec<Vec<(usize, [Card; 2])>> {
    let log = Arc::new(Mutex::new(Vec::new()));
    let list: Vec<Agent> = (0..agents).map(|a| recorder(a, &log)).collect();
    let config = MatchConfig {
        threads: 1,
        ..config.clone()
    };
    let report = run_match(&config, &list).unwrap();
    let n = config.players();
    let log = log.lock().unwrap();
    assert_eq!(log.len() as u64, report.hands * n as u64);
    log.chunks(n)
        .map(|hand| {
            let mut seats = vec![(0, [0; 2]); n];
            for &(agent, seat, hole) in hand {
                seats[seat] = (agent, hole);
            }
            seats
        })
        .collect()
}

#[test]
fn heads_up_duplicate_plays_each_deal_twice_with_the_seats_swapped() {
    let hands = seatings(&MatchConfig::heads_up(20, 1), 2);
    assert_eq!(hands.len(), 40);
    for pair in hands.chunks(2) {
        let cards = |hand: &[(usize, [Card; 2])]| [hand[0].1, hand[1].1];
        assert_eq!(
            cards(&pair[0]),
            cards(&pair[1]),
            "the same cards in the same seats"
        );
        assert_eq!([pair[0][0].0, pair[0][1].0], [0, 1]);
        assert_eq!([pair[1][0].0, pair[1][1].0], [1, 0]);
    }
    // Different deals have different cards.
    assert_ne!(hands[0][0].1, hands[2][0].1);
}

#[test]
fn six_max_duplicate_seats_b_in_every_seat_in_turn() {
    let config = MatchConfig::one_against_the_rest(6, 10, 1);
    assert_eq!(config.lineup, [1, 0, 0, 0, 0, 0]);
    let hands = seatings(&config, 2);
    assert_eq!(hands.len(), 60);
    for deal in hands.chunks(6) {
        for (replay, hand) in deal.iter().enumerate() {
            for seat in 0..6 {
                assert_eq!(
                    hand[seat].0,
                    (seat == replay) as usize,
                    "b sits in seat {replay}"
                );
                assert_eq!(
                    hand[seat].1, deal[0][seat].1,
                    "the cards stay in their seats"
                );
            }
        }
    }
}

#[test]
fn any_mix_of_agents_visits_every_seat() {
    // Three agents at six seats, two places each: three different rotations.
    let config = MatchConfig::new(&[0, 1, 2, 0, 1, 2], 8, 1);
    assert_eq!(config.replays(), 3);
    let hands = seatings(&config, 3);
    assert_eq!(hands.len(), 24);
    for deal in hands.chunks(3) {
        for seat in 0..6 {
            let mut who: Vec<usize> = deal.iter().map(|hand| hand[seat].0).collect();
            who.sort_unstable();
            assert_eq!(
                who,
                [0, 1, 2],
                "every agent sits in seat {seat} once a deal"
            );
        }
    }

    // Six different agents: six rotations. A five-seat table with a 2-2-1 mix: five.
    assert_eq!(MatchConfig::new(&[0, 1, 2, 3, 4, 5], 1, 1).replays(), 6);
    let five = MatchConfig::new(&[0, 0, 1, 1, 2], 4, 1);
    assert_eq!(five.replays(), 5);
    let hands = seatings(&five, 3);
    for deal in hands.chunks(5) {
        for agent in 0..3 {
            let seats: usize = deal
                .iter()
                .map(|hand| hand.iter().filter(|s| s.0 == agent).count())
                .sum();
            assert_eq!(seats, [10, 10, 5][agent]);
        }
    }

    // One agent in every place: nothing to rotate.
    assert_eq!(MatchConfig::new(&[0, 0, 0], 1, 1).replays(), 1);
}

#[test]
fn plain_play_moves_the_lineup_one_seat_a_deal() {
    let config = MatchConfig::one_against_the_rest(6, 12, 1).plain();
    let hands = seatings(&config, 2);
    assert_eq!(hands.len(), 12);
    for (deal, hand) in hands.iter().enumerate() {
        for seat in 0..6 {
            assert_eq!(hand[seat].0, (seat == deal % 6) as usize);
        }
    }
}

// ----- the report -----

#[test]
fn the_report_adds_up() {
    let bots = agents(&["call", "tag"]);
    let config = MatchConfig::one_against_the_rest(6, 300, 21);
    let report = run_match(&config, &bots).unwrap();
    assert_eq!(
        (report.players, report.deals, report.replays_per_deal),
        (6, 300, 6)
    );
    assert_eq!(report.hands, 1_800);
    assert_eq!(report.agents, ["call", "tag"]);
    assert_eq!(report.scoring, "all-in equity (at most 10000 boards)");
    let (call, tag) = (
        report.result("call").unwrap(),
        report.result("tag").unwrap(),
    );
    assert_eq!((call.seats, call.hands), (5, 9_000));
    assert_eq!((tag.seats, tag.hands), (1, 1_800));
    assert_eq!(call.illegal_actions + tag.illegal_actions, 0);

    // Per seat: every seat is listed with its name and its hands, and the seats average
    // to the overall result.
    for r in [call, tag] {
        assert_eq!(r.by_seat.len(), 6);
        let mut mean = 0.0;
        for (seat, s) in r.by_seat.iter().enumerate() {
            assert_eq!(
                (s.seat, s.position.as_str()),
                (seat, position_name(6, seat))
            );
            assert_eq!(s.hands, r.hands / 6);
            assert!(s.se.unwrap() > 0.0);
            mean += s.bb_per_100 / 6.0;
        }
        assert!(
            (mean - r.bb_per_100).abs() < 1e-6,
            "{mean} against {}",
            r.bb_per_100
        );
    }
    // No rake: over the whole table the chips won and lost cancel.
    assert!((tag.bb_per_100 + 5.0 * call.bb_per_100).abs() < 1e-6);
    assert!((tag.actual_bb_per_100 + 5.0 * call.actual_bb_per_100).abs() < 1e-6);
    let names: Vec<&str> = (0..6).map(|s| position_name(6, s)).collect();
    assert_eq!(names, ["BTN", "SB", "BB", "UTG", "HJ", "CO"]);
    assert_eq!([position_name(2, 0), position_name(2, 1)], ["BTN/SB", "BB"]);
    assert_eq!(position_name(5, 3), "UTG");
    assert_eq!(position_name(4, 3), "CO");

    // The text table names every agent.
    let text = report.summary();
    assert!(
        text.contains("tag") && text.contains("call") && text.contains("bb/100"),
        "{text}"
    );
}

#[test]
fn the_report_saves_to_json_and_loads_back() {
    let report = run_match(&MatchConfig::heads_up(200, 3), &agents(&["random", "tag"])).unwrap();
    let dir = std::env::temp_dir().join(format!("arena-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("match.json");
    report.save(&path).unwrap();
    let text = std::fs::read_to_string(&path).unwrap();
    let loaded = MatchReport::load(&path).unwrap();
    std::fs::remove_dir_all(&dir).unwrap();

    // The file is plain JSON with the fields a reader needs.
    let json: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(json["format"], "pokerscribe-arena/1");
    assert_eq!(json["config"]["seed"], 3);
    assert_eq!(json["config"]["duplicate"], true);
    assert_eq!(json["hands"], 400);
    let tag = &json["results"][1];
    assert_eq!(tag["agent"], "tag");
    for field in [
        "bb_per_100",
        "se",
        "actual_bb_per_100",
        "actual_se",
        "plain_se",
    ] {
        assert!(tag[field].is_number(), "{field}");
    }
    assert_eq!(tag["by_seat"][0]["position"], "BTN/SB");
    assert_eq!(tag["by_seat"][1]["position"], "BB");
    assert!(json["timing"]["hands_per_second"].as_f64().unwrap() > 0.0);

    // Loading gives the report back (numbers to within rounding of the text).
    assert_eq!(loaded.config, report.config);
    assert_eq!(loaded.agents, report.agents);
    assert_eq!(loaded.results.len(), report.results.len());
    for (a, b) in loaded.results.iter().zip(&report.results) {
        assert_eq!((a.index, &a.agent, a.hands), (b.index, &b.agent, b.hands));
        assert!((a.bb_per_100 - b.bb_per_100).abs() < 1e-9);
        assert!((a.se.unwrap() - b.se.unwrap()).abs() < 1e-9);
    }
}

#[test]
fn bad_settings_are_refused() {
    let bots = agents(&["call", "tag"]);
    let run = |change: fn(&mut MatchConfig)| {
        let mut config = MatchConfig::heads_up(10, 1);
        change(&mut config);
        run_match(&config, &bots)
            .map(|_| ())
            .map_err(|e| e.to_string())
    };
    assert!(run(|_| ()).is_ok());
    assert!(run(|c| c.lineup = vec![0]).is_err());
    assert!(run(|c| c.lineup = vec![0; 7]).is_err());
    assert!(run(|c| c.lineup = vec![0, 2]).is_err());
    assert!(run(|c| c.deals = 0).is_err());
    assert!(run(|c| c.stack = 0).is_err());
    assert!(run(|c| c.big_blind = 0).is_err());
    assert!(run(|c| c.max_runouts = Some(0)).is_err());
    // One deal is a match, with no standard error yet.
    let one = run_match(&MatchConfig::heads_up(1, 1), &bots).unwrap();
    assert_eq!(one.results[0].se, None);
}

// ----- players -----

#[test]
fn an_illegal_action_becomes_a_check_or_a_fold_and_is_counted() {
    // A raise to 1 chip is never legal at 50/100, so this player ends up checking when
    // it can and folding when it cannot: the same as the always-fold bot.
    let broken = Agent::new("broken", || Box::new(|_: &View<'_>| Action::RaiseTo(1)));
    let config = MatchConfig::heads_up(300, 6);
    let call = bots::builtin("call").unwrap();
    let with_broken = run_match(&config, &[call.clone(), broken]).unwrap();
    let with_fold = run_match(&config, &[call, bots::builtin("fold").unwrap()]).unwrap();
    let (b, f) = (second(&with_broken), second(&with_fold));
    assert!(b.illegal_actions > 300, "{}", b.illegal_actions);
    assert_eq!(f.illegal_actions, 0);
    assert_eq!((b.bb_per_100, b.se), (f.bb_per_100, f.se));
    assert_eq!(with_broken.result_of(0).unwrap().illegal_actions, 0);
}

#[test]
fn the_test_bots_only_make_legal_actions() {
    let names = bots::BUILTIN;
    let all = agents(&names);
    // Every bot against every other at a six-seat table, short and deep.
    for stack in [300, 10_000] {
        for first in 0..names.len() {
            let lineup: Vec<usize> = (0..6).map(|j| (first + j) % names.len()).collect();
            let config = MatchConfig {
                stack,
                ..MatchConfig::new(&lineup, 60, first as u64)
            };
            let report = run_match(&config, &all).unwrap();
            for r in &report.results {
                assert_eq!(r.illegal_actions, 0, "{} with stacks of {stack}", r.agent);
            }
        }
    }
}

/// Checks what a player is shown, from inside a match.
#[derive(Clone, Default)]
struct Witness {
    hands: Arc<Mutex<(u32, u32)>>,
}

impl Player for Witness {
    fn begin_hand(&mut self, view: &View<'_>) {
        assert!(!view.is_over() && view.net().is_none());
        assert!(view.history().is_empty() && view.board().is_empty());
        assert_eq!(view.pot(), 150, "the blinds are posted");
    }

    fn act(&mut self, view: &View<'_>) -> Action {
        let me = view.seat();
        let legal = view.legal();
        assert!(legal.check || legal.call.is_some());
        assert_eq!(view.shown(me), Some(view.hole()));
        for seat in (0..view.num_players()).filter(|&s| s != me) {
            assert_eq!(view.shown(seat), None, "no other cards before a showdown");
        }
        assert_eq!(view.board().len(), view.street().board_len());
        assert_eq!(view.pot(), view.committed().iter().sum::<u32>());
        assert_eq!(view.to_call() == 0, legal.check);
        assert_eq!(legal.call, (view.to_call() > 0).then_some(view.to_call()));
        // The same decision always draws the same random numbers.
        assert_eq!(view.rng().next_u64(), view.rng().next_u64());
        assert_eq!(view.pick(&[0.0, 3.0, 0.0]), 1);
        assert_eq!(view.pick(&[0.2, 0.5, 0.3]), view.pick(&[0.2, 0.5, 0.3]));
        // The table and the history rebuild the public state.
        let config = view.config();
        assert_eq!(config.stacks(), view.starting_stacks());
        assert_eq!(config.button(), 0);
        // Another seat's eyes, with cards of our choosing.
        let other = view.imagine((me + 1) % view.num_players(), [0, 1]);
        assert_eq!((other.hole(), other.pot()), ([0, 1], view.pot()));
        assert_eq!(other.legal(), Default::default(), "it is not their turn");
        view.check_or_call()
    }

    fn end_hand(&mut self, view: &View<'_>) {
        assert!(view.is_over());
        let net = view.net().unwrap();
        let me = view.seat();
        let folded = (0..view.num_players())
            .filter(|&s| view.is_folded(s))
            .count();
        let showdown = view.num_players() - folded >= 2;
        for seat in (0..view.num_players()).filter(|&s| s != me) {
            assert_eq!(
                view.shown(seat).is_some(),
                showdown && !view.is_folded(seat)
            );
        }
        // Nobody can lose more than a stack or win more than everyone else's.
        assert!((-10_000..=30_000).contains(&net), "{net}");
        if view.is_folded(me) {
            assert_eq!(net, -(view.committed()[me] as i64));
        }
        let mut hands = self.hands.lock().unwrap();
        hands.0 += 1;
        hands.1 += showdown as u32;
    }
}

#[test]
fn a_player_sees_its_own_cards_and_only_public_things() {
    let witness = Witness::default();
    let seen = Arc::clone(&witness.hands);
    let list = [
        Agent::of("witness", witness),
        Agent::of("tag", TightAggressive::default()),
        Agent::of("random", RandomBot),
    ];
    let config = MatchConfig {
        threads: 1,
        ..MatchConfig::new(&[0, 1, 2, 2], 100, 8)
    };
    let report = run_match(&config, &list).unwrap();
    let (hands, showdowns) = *seen.lock().unwrap();
    assert_eq!(hands as u64, report.hands);
    assert!(showdowns > 20 && showdowns < hands);
    assert!(format!("{:?}", list[0]).contains("witness"));
}

#[test]
fn players_can_be_structs_or_closures() {
    let list = [
        Agent::of("struct", AlwaysCall),
        Agent::new("closure", || {
            Box::new(|view: &View<'_>| view.check_or_fold())
        }),
        Agent::of("fold", AlwaysFold),
    ];
    // The closure plays as the always-fold bot does.
    let a = run_match(&MatchConfig::new(&[0, 1], 100, 2), &list).unwrap();
    let b = run_match(&MatchConfig::new(&[0, 2], 100, 2), &list).unwrap();
    assert_eq!(a.results[1].bb_per_100, b.results[1].bb_per_100);
    assert!(a.results[0].bb_per_100 > 0.0);
}

#[test]
fn pick_follows_the_weights() {
    // Over many hands a 1 : 3 pick comes out near 25% and 75%.
    let counts = Arc::new(Mutex::new([0u32; 2]));
    let seen = Arc::clone(&counts);
    let picker = Agent::new("picker", move || {
        let counts = Arc::clone(&counts);
        Box::new(move |view: &View<'_>| {
            counts.lock().unwrap()[view.pick(&[1.0, 3.0])] += 1;
            view.check_or_fold()
        })
    });
    run_match(&MatchConfig::heads_up(4_000, 3), &[picker.clone(), picker]).unwrap();
    let [a, b] = *seen.lock().unwrap();
    let share = a as f64 / (a + b) as f64;
    assert!(a + b >= 8_000 && (share - 0.25).abs() < 0.02, "{a} and {b}");
}

// ----- the scorer hook -----

/// A scorer that gives every seat half its real result: not a sound adjustment, only a
/// check that a custom scorer is what the report is built from.
struct Half;

impl Scorer for Half {
    fn name(&self) -> String {
        "half".to_string()
    }
    fn score(&self, hand: &HandRecord<'_>, scores: &mut [f64]) {
        assert_eq!(hand.agents.len(), scores.len());
        assert!(hand.state.is_terminal());
        for (score, &chips) in scores.iter_mut().zip(hand.payouts) {
            assert_eq!(*score, chips as f64, "scores arrive holding the real chips");
            *score = chips as f64 / 2.0;
        }
    }
}

#[test]
fn a_custom_scorer_is_the_hook_for_aivat() {
    let bots = agents(&["call", "tag"]);
    let config = MatchConfig::heads_up(300, 15);
    let report = run_match_scored(&config, &bots, &Half).unwrap();
    assert_eq!(report.scoring, "half");
    let tag = second(&report);
    assert!((tag.bb_per_100 - tag.actual_bb_per_100 / 2.0).abs() < 1e-9);
    assert!((tag.se.unwrap() - tag.actual_se.unwrap() / 2.0).abs() < 1e-9);
}
