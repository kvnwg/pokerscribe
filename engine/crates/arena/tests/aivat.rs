//! AIVAT: the corrections average 0 (by every card and by the deal), the value estimate
//! pays like the engine, and in matches AIVAT agrees with the main figure, gives about 0
//! for identical agents and narrows the standard error, more so with the answers of a
//! known strategy, and wrong answers do no harm.

// Loops over seat numbers read better than iterator chains over several arrays at once.
#![allow(clippy::needless_range_loop)]

use arena::aivat::checkdown;
use arena::bots::MixedBot;
use arena::{
    bots, run_match, run_match_scored, Agent, Aivat, AllInEquity, Decisions, EvalRanker, Facing,
    HandRecord, MatchConfig, MatchReport, Player, Scorer, Stakes, View,
};
use nlhe::{Action, Card, Config, Deal, Rng, State, MAX_PLAYERS};

/// A random table: 2 to 6 players, stacks from 1 to 120 big blinds, sometimes an ante.
fn random_table(rng: &mut Rng) -> Config {
    let n = 2 + rng.below(5) as usize;
    let stacks: Vec<u32> = (0..n).map(|_| 1 + rng.below(240) as u32).collect();
    let ante = if rng.below(4) == 0 { 1 } else { 0 };
    Config::new(&stacks, 1, 2, ante, rng.below(n as u64) as usize).unwrap()
}

/// Random actions until `stop` says so or the hand is over.
fn random_play(state: &mut State, rng: &mut Rng, stop: impl Fn(&State) -> bool) {
    while state.current_player().is_some() && !stop(state) {
        let legal = state.legal_actions();
        let roll = rng.below(100);
        let action = match legal.raise {
            Some(range) if roll < 10 => Action::RaiseTo(range.max_to),
            Some(range) if roll < 30 => Action::RaiseTo(range.min_to),
            _ if legal.fold && roll >= 85 => Action::Fold,
            _ if legal.check => Action::Check,
            _ => Action::Call,
        };
        state.apply(action).unwrap();
    }
}

/// The same deal with board card `index` replaced by `card` (and the cards after it by
/// any others not in use: the check-down value doesn't look at cards not yet face up).
fn with_card(deal: &Deal, n: usize, index: usize, card: Card) -> Deal {
    let mut used = 0u64;
    for seat in 0..n {
        for c in deal.hole[seat] {
            used |= 1 << c;
        }
    }
    let mut board = deal.board;
    for &c in &board[..index] {
        used |= 1 << c;
    }
    board[index] = card;
    used |= 1 << card;
    for slot in board.iter_mut().skip(index + 1) {
        let free = (0..52u8).find(|&c| used & (1 << c) == 0).unwrap();
        *slot = free;
        used |= 1 << free;
    }
    let hole: Vec<[Card; 2]> = deal.hole[..n].to_vec();
    Deal::new(&hole, board).unwrap()
}

fn unseen(deal: &Deal, n: usize, known: usize) -> Vec<Card> {
    let mut used = 0u64;
    for seat in 0..n {
        for c in deal.hole[seat] {
            used |= 1 << c;
        }
    }
    for &c in &deal.board[..known] {
        used |= 1 << c;
    }
    (0..52u8).filter(|&c| used & (1 << c) == 0).collect()
}

#[test]
fn a_card_correction_averages_zero_over_every_card_that_can_come() {
    // At the end of the flop's or the turn's betting, the check-down value averaged over
    // every next card is the value before it, exactly: the chance correction averages 0.
    let mut rng = Rng::new(17);
    let mut checked = [0; 2];
    for seed in 0..300 {
        let config = random_table(&mut rng);
        let n = config.num_players();
        let mut state = State::from_seed(&config, seed);
        let street = 1 + rng.below(2) as usize; // flop or turn
        let known = [3, 4][street - 1];
        random_play(&mut state, &mut rng, |s| s.street().board_len() > known);
        if state.active_mask().count_ones() < 2 || state.street().board_len() <= known {
            continue;
        }
        // The chips when the street's betting ended.
        let stakes = Stakes::of(&state);
        let deal = *state.deal();
        let before = checkdown(&deal, n, known, &stakes, None);
        let cards = unseen(&deal, n, known);
        let mut average = [0.0; MAX_PLAYERS];
        for &c in &cards {
            let after = checkdown(&with_card(&deal, n, known, c), n, known + 1, &stakes, None);
            for seat in 0..n {
                average[seat] += after[seat] / cards.len() as f64;
            }
        }
        for seat in 0..n {
            assert!(
                (average[seat] - before[seat]).abs() < 1e-6,
                "seed {seed}, seat {seat}: {} against {}",
                average[seat],
                before[seat]
            );
        }
        assert!(
            before[..n].iter().sum::<f64>().abs() < 1e-6,
            "the values add up to 0"
        );
        checked[street - 1] += 1;
    }
    assert!(checked[0] > 30 && checked[1] > 30, "{checked:?}");
}

#[test]
fn the_flop_correction_averages_zero_and_the_sample_before_it_has_no_bias() {
    // Heads-up, 2,000 chips each, 300 in: the average over every flop of the flop's
    // check-down value is the exact value before the flop, and the sampled value before
    // the flop is that within its spread.
    let config = Config::new(&[2_000, 2_000], 50, 100, 0, 0).unwrap();
    let mut state = State::from_seed(&config, 4);
    state.apply(Action::RaiseTo(300)).unwrap();
    state.apply(Action::Call).unwrap();
    assert_eq!(state.street().board_len(), 3);
    let stakes = Stakes::of(&state);
    let deal = *state.deal();
    let exact = checkdown(&deal, 2, 0, &stakes, None);
    let flops = unseen(&deal, 2, 0);
    let (mut sum, mut count) = (0.0, 0);
    for i in 0..flops.len() {
        for j in i + 1..flops.len() {
            for k in j + 1..flops.len() {
                let d = with_card(
                    &with_card(&with_card(&deal, 2, 0, flops[i]), 2, 1, flops[j]),
                    2,
                    2,
                    flops[k],
                );
                sum += checkdown(&d, 2, 3, &stakes, None)[0];
                count += 1;
            }
        }
    }
    assert_eq!(count, 17_296);
    assert!((sum / count as f64 - exact[0]).abs() < 1e-6);
    // 2,000 boards: the spread of the estimate is about 300 / sqrt(2,000) chips.
    let samples: Vec<f64> = (0..40)
        .map(|s| checkdown(&deal, 2, 0, &stakes, Some((2_000, 1000 + s)))[0])
        .collect();
    let mean = samples.iter().sum::<f64>() / 40.0;
    let sd = (samples.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / 39.0).sqrt();
    assert!(sd > 0.0 && sd < 12.0, "sd {sd}");
    assert!(
        (mean - exact[0]).abs() < 4.0 * sd / 40f64.sqrt(),
        "{mean} against {}",
        exact[0]
    );
}

#[test]
fn the_check_down_value_on_the_river_pays_like_the_engine() {
    // Every showdown: side pots, dead money of folded seats, ties (split exactly, so off by
    // a few chips at most where the engine gives the odd chips of a pot to one seat).
    let mut rng = Rng::new(2027);
    let mut showdowns = 0;
    for seed in 0..5_000 {
        let config = random_table(&mut rng);
        let n = config.num_players();
        let mut state = State::from_seed(&config, seed);
        random_play(&mut state, &mut rng, |_| false);
        if state.active_mask().count_ones() < 2 {
            continue;
        }
        showdowns += 1;
        let paid = state.payouts(&EvalRanker).unwrap();
        let value = checkdown(state.deal(), n, 5, &Stakes::of(&state), None);
        for seat in 0..n {
            assert!(
                (value[seat] - paid[seat] as f64).abs() < n as f64,
                "seed {seed}, seat {seat}: {} against {}",
                value[seat],
                paid[seat]
            );
        }
    }
    assert!(showdowns > 1_000);
}

#[test]
fn a_bet_still_to_be_answered_is_valued_as_the_rule_says() {
    // Heads-up at the start: the small blind (50) faces the big blind (100).
    let config = Config::new(&[2_000, 2_000], 50, 100, 0, 0).unwrap();
    let state = State::from_seed(&config, 1);
    let root = Stakes::of(&state);
    // A check-down where one seat always has the best hand: it takes from the other up to
    // what it put in itself, and an unmatched bet goes back. Easy to follow by hand.
    let wins = |winner: usize, s: &Stakes| {
        let c = &s.committed;
        let won = c[1 - winner].min(c[winner]) as f64;
        let mut v = [0.0; MAX_PLAYERS];
        v[winner] = won;
        v[1 - winner] = -won;
        v
    };
    let seat0_wins = |s: &Stakes| wins(0, s);
    let seat1_wins = |s: &Stakes| wins(1, s);
    let with = |facing| Aivat {
        facing,
        ..Aivat::default()
    };
    // Minimum defense: the small blind calls 50 into 100 two times in three.
    let v = with(Facing::MinimumDefense).value(&root, seat0_wins);
    assert!(
        (v[0] - (2.0 / 3.0 * 100.0 + 1.0 / 3.0 * -50.0)).abs() < 1e-9,
        "{v:?}"
    );
    assert!((v[0] + v[1]).abs() < 1e-9);
    let v = with(Facing::Called).value(&root, seat0_wins);
    assert!((v[0] - 100.0).abs() < 1e-9);
    // Taken back: only 50 each is checked down.
    let v = with(Facing::TakenBack).value(&root, seat0_wins);
    assert!((v[0] - 50.0).abs() < 1e-9);
    // A bluff that never wins is worth as much as giving up, with minimum defense: seat 1
    // bets 300 into 200 on a later street and seat 0 calls 200 / 500 of the time.
    let mut s = Stakes {
        n: 2,
        committed: [0; MAX_PLAYERS],
        behind: [0; MAX_PLAYERS],
        active: 0b11,
    };
    s.committed[..2].copy_from_slice(&[100, 400]);
    s.behind[..2].copy_from_slice(&[1_900, 1_600]);
    // Seat 1 bluffs (seat 0 wins the showdown): +100 when seat 0 folds, -400 when it calls.
    let bluff = with(Facing::MinimumDefense).value(&s, seat0_wins);
    assert!((bluff[1] - (0.6 * 100.0 + 0.4 * -400.0)).abs() < 1e-9);
    assert!(
        (bluff[1] - -100.0).abs() < 1e-9,
        "the same as checking and losing 100"
    );
    let value_bet = with(Facing::MinimumDefense).value(&s, seat1_wins);
    assert!((value_bet[1] - (0.6 * 100.0 + 0.4 * 400.0)).abs() < 1e-9);
    // Taken back, the bet is worth nothing either way: 100 each is checked down.
    assert!((with(Facing::TakenBack).value(&s, seat0_wins)[1] - -100.0).abs() < 1e-9);
}

#[test]
fn the_deal_correction_averages_zero() {
    // The value at the start of a hand, averaged over many deals, against the even shares
    // the deal correction subtracts: heads-up, three-handed and six-max.
    for (n, stacks) in [(2usize, 2_000u32), (3, 10_000), (6, 10_000)] {
        let config = Config::new(&vec![stacks; n], 50, 100, 0, 0).unwrap();
        let aivat = Aivat::default();
        let deals = 6_000;
        let mut sum = [0.0; MAX_PLAYERS];
        let mut sum_sq = [0.0; MAX_PLAYERS];
        let mut even = [0.0; MAX_PLAYERS];
        for d in 0..deals {
            let state = State::from_seed(&config, 50_000 + d);
            let stakes = Stakes::of(&state);
            let v = aivat.value(&stakes, |s| {
                checkdown(state.deal(), n, 0, s, Some((300, d)))
            });
            even = aivat.value(&stakes, Stakes::even_shares);
            for seat in 0..n {
                sum[seat] += v[seat];
                sum_sq[seat] += v[seat] * v[seat];
            }
        }
        for seat in 0..n {
            let mean = sum[seat] / deals as f64;
            let se = ((sum_sq[seat] / deals as f64 - mean * mean) / deals as f64).sqrt();
            assert!(
                (mean - even[seat]).abs() < 4.0 * se + 1e-9,
                "{n} players, seat {seat}: {mean} against {} (SE {se})",
                even[seat]
            );
        }
        // The small blind is valued below its 50: it may fold to the big blind.
        let sb = config.num_players().min(2) - 1;
        let state = State::from_seed(&config, 1);
        assert!(
            even[state.small_blind_seat()] < 0.0,
            "{n} players: {even:?} (seat {sb})"
        );
    }
}

/// Plays `deals` deals of `a` against `b`, with AIVAT.
fn aivat_match(agents: &[Agent], deals: u64, seed: u64, players: usize) -> MatchReport {
    let mut config = if players == 2 {
        MatchConfig::heads_up(deals, seed)
    } else {
        MatchConfig::one_against_the_rest(players, deals, seed)
    }
    .with_aivat();
    config.stack = 2_000;
    run_match(&config, agents).unwrap()
}

#[test]
fn identical_agents_give_zero_with_aivat() {
    let mixed = bots::builtin("mixed").unwrap();
    let mut worst: f64 = 0.0;
    for (players, deals) in [(2, 4_000), (3, 1_500)] {
        for seed in 1..=3 {
            for duplicate in [true, false] {
                let mut config = if players == 2 {
                    MatchConfig::heads_up(deals, seed)
                } else {
                    MatchConfig::one_against_the_rest(players, deals, seed)
                }
                .with_aivat();
                config.stack = 2_000;
                config.duplicate = duplicate;
                let report = run_match(&config, &[mixed.clone(), mixed.clone()]).unwrap();
                for r in &report.results {
                    let a = r.aivat.as_ref().unwrap();
                    let z = a.bb_per_100 / a.se.unwrap();
                    worst = worst.max(z.abs());
                    assert!(
                        z.abs() < 3.0,
                        "{players} players, seed {seed}: {}",
                        report.summary()
                    );
                    let d = a.minus_main / a.minus_main_se.unwrap();
                    assert!(
                        d.abs() < 3.0,
                        "{players} players, seed {seed}: {}",
                        report.summary()
                    );
                }
            }
        }
    }
    assert!(worst > 0.0);
    // With shared randomness two copies play every replay alike: 0 up to rounding, as the
    // main figure is.
    let mut config = MatchConfig::heads_up(500, 9).with_aivat();
    config.shared_randomness = true;
    let report = run_match(&config, &[mixed.clone(), mixed]).unwrap();
    for r in &report.results {
        assert!(r.bb_per_100.abs() < 1e-9);
        assert!(r.aivat.as_ref().unwrap().bb_per_100.abs() < 1e-9);
    }
}

#[test]
fn aivat_agrees_with_the_main_figure_and_narrows_it() {
    let names = [
        ("mixed", "mixed-loose", 2),
        ("tag", "mixed", 2),
        ("mixed", "random", 2),
        ("tag-loose", "tag", 2),
        ("mixed", "mixed-loose", 6),
    ];
    for (a, b, players) in names {
        let agents = [bots::builtin(a).unwrap(), bots::builtin(b).unwrap()];
        let deals = if players == 2 { 6_000 } else { 1_000 };
        let report = aivat_match(&agents, deals, 77, players);
        let mut total = 0.0;
        for r in &report.results {
            let x = r.aivat.as_ref().unwrap();
            let d = x.minus_main / x.minus_main_se.unwrap();
            assert!(d.abs() < 3.5, "{a} against {b}: {}", report.summary());
            total += x.bb_per_100 * r.seats as f64;
            assert_eq!(x.unexplained_decisions, 0);
        }
        assert!(total.abs() < 1e-6, "no rake: the AIVAT results add up to 0");
        // The chances of `mixed` are known: every one of its decisions is corrected. Those
        // of the rule bots are not.
        for r in &report.results {
            let x = r.aivat.as_ref().unwrap();
            if r.agent.starts_with("mixed") {
                assert!(x.corrected_decisions > 0 && x.unknown_decisions == 0);
            } else {
                assert!(x.corrected_decisions == 0 && x.unknown_decisions > 0);
            }
        }
        if players == 2 && a.starts_with("mixed") {
            let x = report.results[0].aivat.as_ref().unwrap();
            assert!(
                x.se_ratio.unwrap() < 0.95,
                "{a} against {b}: {}",
                report.summary()
            );
        }
    }
}

/// Reports chances, but plays something else: always the first legal action of its list
/// when the list has two, or an action not in the list.
#[derive(Clone, Default)]
struct Liar {
    chances: Vec<(Action, f64)>,
}

impl Player for Liar {
    fn act(&mut self, view: &View<'_>) -> Action {
        self.chances = vec![(Action::Fold, 1.0), (Action::RaiseTo(1), 1.0)];
        view.check_or_call()
    }
    fn probabilities(&self) -> Option<&[(Action, f64)]> {
        Some(&self.chances)
    }
}

#[test]
fn chances_that_cannot_be_right_are_not_used_and_are_counted() {
    let agents = [
        Agent::of("liar", Liar::default()),
        bots::builtin("mixed").unwrap(),
    ];
    let report = aivat_match(&agents, 300, 5, 2);
    let liar = report.result("liar").unwrap().aivat.as_ref().unwrap();
    assert_eq!(liar.corrected_decisions, 0);
    assert!(liar.unexplained_decisions > 0);
    assert!(
        report.summary().contains("unexplained"),
        "{}",
        report.summary()
    );
}

#[test]
fn aivat_repeats_on_any_number_of_threads_and_saves_to_json() {
    let agents = [
        bots::builtin("mixed").unwrap(),
        bots::builtin("tag").unwrap(),
    ];
    let mut config = MatchConfig::heads_up(700, 3).with_aivat();
    let mut reports = Vec::new();
    for threads in [1, 2, 3] {
        config.threads = threads;
        let mut r = run_match(&config, &agents).unwrap();
        r.timing.threads = 0;
        r.timing.seconds = 0.0;
        r.timing.hands_per_second = 0.0;
        r.config.threads = 0;
        reports.push(r);
    }
    assert_eq!(reports[0], reports[1]);
    assert_eq!(reports[0], reports[2]);
    // serde_json reads floats back to within a unit or so of the last digit.
    let back = MatchReport::from_json(&reports[0].to_json()).unwrap();
    for (x, y) in back.results.iter().zip(&reports[0].results) {
        let (a, b) = (x.aivat.as_ref().unwrap(), y.aivat.as_ref().unwrap());
        assert!((a.bb_per_100 - b.bb_per_100).abs() < 1e-9);
        assert!((a.se.unwrap() - b.se.unwrap()).abs() < 1e-9);
        assert!((a.minus_main - b.minus_main).abs() < 1e-9);
        assert_eq!(a.corrected_decisions, b.corrected_decisions);
    }
    assert_eq!(back.config, reports[0].config);
    assert!(reports[0]
        .aivat_scoring
        .as_deref()
        .unwrap()
        .starts_with("AIVAT"));
    // Without AIVAT the fields are empty, and a report from before AIVAT still loads.
    config.aivat = None;
    let plain = run_match(&config, &agents).unwrap();
    assert!(plain.results.iter().all(|r| r.aivat.is_none()));
    let mut json: serde_json::Value = serde_json::from_str(&plain.to_json()).unwrap();
    json.as_object_mut().unwrap().remove("aivat_scoring");
    json["config"].as_object_mut().unwrap().remove("aivat");
    for r in json["results"].as_array_mut().unwrap() {
        r.as_object_mut().unwrap().remove("aivat");
    }
    let old = MatchReport::from_json(&json.to_string()).unwrap();
    assert_eq!(old.config.aivat, None);
    assert!(
        MatchConfig::heads_up(1, 1).aivat.is_none(),
        "off unless asked for"
    );
}

/// `mixed`, reporting its chances, with what it would play elsewhere either not given
/// (`answers: None`) or given wrong: the same chances for every action it could take.
#[derive(Clone)]
struct Answering {
    bot: MixedBot,
    answers: Option<f64>,
}

impl Answering {
    fn agent(name: &str, answers: Option<f64>) -> Agent {
        let bot = MixedBot::new(1.0);
        Agent::of(name, Answering { bot, answers })
    }
}

impl Player for Answering {
    fn act(&mut self, view: &View<'_>) -> Action {
        self.bot.act(view)
    }
    fn probabilities(&self) -> Option<&[(Action, f64)]> {
        self.bot.probabilities()
    }
    fn chances_at(&self, view: &View<'_>, out: &mut Vec<(Action, f64)>) -> bool {
        let Some(raise) = self.answers else {
            return false;
        };
        out.push((view.check_or_call(), 1.0));
        if view.legal().fold {
            out.push((Action::Fold, 1.0));
        }
        if view.legal().raise.is_some() {
            out.push((view.raise_pot(raise), 1.0));
        }
        true
    }
}

#[test]
fn answers_narrow_aivat_and_wrong_answers_do_no_harm() {
    // `mixed` says what it would play anywhere. With its answers AIVAT is more precise
    // than without them (AIVAT as the main scorer of a match asks no player).
    let agents = [
        bots::builtin("mixed").unwrap(),
        bots::builtin("mixed-loose").unwrap(),
    ];
    let config = MatchConfig::heads_up(6_000, 21).with_aivat();
    let with = run_match(&config, &agents).unwrap();
    let without = run_match_scored(&config, &agents, &Aivat::default()).unwrap();
    for (x, y) in with.results.iter().zip(&without.results) {
        let a = x.aivat.as_ref().unwrap();
        assert!(
            a.se.unwrap() < y.se.unwrap(),
            "{}\n{}",
            with.summary(),
            without.summary()
        );
        let d = a.minus_main / a.minus_main_se.unwrap();
        assert!(d.abs() < 3.5, "{}", with.summary());
    }
    // Wrong answers cost precision, never correctness: AIVAT still agrees with the main
    // figure, and gives about 0 between identical agents.
    for seed in [22, 23] {
        let agents = [
            Answering::agent("wrong", Some(2.0)),
            bots::builtin("mixed-loose").unwrap(),
        ];
        let report = aivat_match(&agents, 4_000, seed, 2);
        for r in &report.results {
            let a = r.aivat.as_ref().unwrap();
            let d = a.minus_main / a.minus_main_se.unwrap();
            assert!(d.abs() < 3.5, "{}", report.summary());
        }
        let twins = [
            Answering::agent("wrong", Some(0.5)),
            Answering::agent("wrong too", Some(0.5)),
        ];
        let report = aivat_match(&twins, 4_000, seed, 2);
        for r in &report.results {
            let a = r.aivat.as_ref().unwrap();
            assert!(
                (a.bb_per_100 / a.se.unwrap()).abs() < 3.0,
                "{}",
                report.summary()
            );
        }
    }
}

#[test]
fn aivat_is_a_scorer_too_and_its_scores_add_up_to_zero() {
    // As the main scorer of a match it gives the same figure as next to it, when no
    // player says what it would play elsewhere (the scorer can't ask).
    let agents = [
        Answering::agent("mixed", None),
        bots::builtin("call").unwrap(),
    ];
    let config = MatchConfig::heads_up(400, 8).with_aivat();
    let beside = run_match(&config, &agents).unwrap();
    let alone = run_match_scored(&config, &agents, &Aivat::default()).unwrap();
    for (x, y) in beside.results.iter().zip(&alone.results) {
        let a = x.aivat.as_ref().unwrap();
        assert!((a.bb_per_100 - y.bb_per_100).abs() < 1e-9);
        assert_eq!(a.se, y.se);
    }
    // One hand at a time: the AIVAT scores add up to 0, a fold before the flop by a player
    // whose chances are unknown keeps its payout less the deal's luck.
    let config = Config::new(&[2_000, 2_000], 50, 100, 0, 0).unwrap();
    let mut state = State::from_seed(&config, 3);
    state.apply(Action::Fold).unwrap();
    let payouts = state.payouts(&EvalRanker).unwrap();
    let decisions = {
        let mut d = Decisions::new();
        d.push(None);
        d
    };
    let record = HandRecord {
        deal: 0,
        replay: 0,
        seed: 1,
        agents: &[0, 1],
        state: &state,
        payouts: &payouts[..2],
        decisions: &decisions,
    };
    let scored = Aivat::default().score_hand(&record);
    assert!((scored.scores[0] + scored.scores[1]).abs() < 1e-9);
    assert_eq!(scored.unknown[0], 1);
    let mut main = [payouts[0] as f64, payouts[1] as f64];
    AllInEquity::default().score(&record, &mut main);
    assert_eq!(main, [-50.0, 50.0]);
}
