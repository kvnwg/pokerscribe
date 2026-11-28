//! The runs Phase 7 is made of, shared by the `search` commands and the plan job
//! ([`crate::plan_job`]): a match of the search agent in the arena, LBR against an agent,
//! and the decision-time bench.

use std::sync::Arc;
use std::time::Instant;

use abstract_game::Bucketer;
use arena::{run_match, MatchConfig, MatchReport};
use blueprint::play::Blueprint;
use blueprint::{lbr_match, Deals};
use lbr::{ActionProbs, PublicState, Strategy};
use nlhe::{Card, Config, Deal, State, Street};
use serde_json::{json, Map, Value};

use crate::cards::mix;
use crate::play::strategy_agent;
use crate::SearchAgent;

/// A shared strategy, as the arena and LBR take one.
pub struct Dyn(pub Arc<dyn Strategy + Send + Sync>);

impl Strategy for Dyn {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        self.0.action_probs(public, hole, out)
    }
    fn action_prob_for_range(
        &self,
        public: &PublicState<'_>,
        action: nlhe::Action,
        hands: &[[Card; 2]],
        out: &mut [f64],
    ) {
        self.0.action_prob_for_range(public, action, hands, out)
    }
}

/// `deals` duplicate deals (each played twice, the seats swapped) scored by all-in equity,
/// between `a` and `b` under their names, at `stack` chips (blinds 50 and 100). `threads`
/// 0 plays on every thread of the current pool.
pub fn head_to_head(
    a: (&str, Arc<dyn Strategy + Send + Sync>),
    b: (&str, Arc<dyn Strategy + Send + Sync>),
    stack: u32,
    deals: u64,
    seed: u64,
    threads: usize,
) -> Result<MatchReport, String> {
    let agents = [
        strategy_agent(a.0, Arc::new(Dyn(a.1))),
        strategy_agent(b.0, Arc::new(Dyn(b.1))),
    ];
    let mut config = MatchConfig::heads_up(deals, seed);
    config.stack = stack;
    config.threads = threads;
    run_match(&config, &agents).map_err(|e| e.to_string())
}

/// LBR (`setting`, such as `fcpa14` or `b56_14`) against `agent` for `hands` hands from
/// `seed`, on every thread of the current pool: the deals (both seats of each) and a
/// summary. With `searcher` (the same agent, its records kept) the summary counts its
/// solves and re-solves by street.
pub fn lbr_run<B: Bucketer + Sync + Send>(
    name: &str,
    agent: Arc<dyn Strategy + Send + Sync>,
    searcher: Option<&SearchAgent<B>>,
    setting: &str,
    stack: u32,
    hands: u64,
    seed: u64,
) -> Result<(Deals, Value), String> {
    let (paper, lbr_config) = blueprint::gate::lbr_setting(setting)
        .ok_or_else(|| format!("no LBR setting {setting:?}"))?;
    let table = lbr::MatchConfig {
        stack,
        ..lbr::MatchConfig::acpc(hands, seed)
    };
    let t0 = Instant::now();
    let deals = lbr_match(&Dyn(agent), &lbr_config, &table);
    let seconds = t0.elapsed().as_secs_f64();
    let r = deals.result();
    let mut solves = Map::new();
    if let Some(a) = searcher {
        let records = a.take_records();
        for street in [Street::Flop, Street::Turn, Street::River] {
            let of: Vec<_> = records.iter().filter(|r| r.street == street).collect();
            let mut ms: Vec<f64> = of.iter().map(|r| r.ms).collect();
            solves.insert(
                street_name(street).into(),
                json!({"solves": of.len(), "resolves": of.iter().filter(|r| r.resolve).count(),
                       "solve_ms_p50": percentile(&mut ms, 0.5), "solve_ms_p95": percentile(&mut ms, 0.95),
                       "solve_ms_max": percentile(&mut ms, 1.0)}),
            );
        }
    }
    let summary = json!({"agent": name, "setting": setting, "paper": paper, "hands": r.hands,
                         "seed": seed, "lbr_bb_per_100": r.bb_per_100, "se": r.std_err,
                         "seconds": seconds, "solves": solves});
    Ok((deals, summary))
}

/// LBR's result against `a` minus its result against `b`, deal by deal (the same deals).
pub fn compare(a: &Deals, b: &Deals) -> Result<Value, String> {
    let (diff, se) = a.minus(b)?;
    let (ra, rb) = (a.result(), b.result());
    Ok(json!({"a_bb_per_100": ra.bb_per_100, "a_se": ra.std_err,
              "b_bb_per_100": rb.bb_per_100, "b_se": rb.std_err, "a_minus_b": diff, "se": se,
              "z": if se > 0.0 { diff / se } else { 0.0 }}))
}

/// Plays `hands` hands of the search agent (seat 0) against its blueprint, the button
/// alternating, calling `look` after every decision of the search agent with its time in
/// ms. Returns the search agent's chips won and its decisions.
pub fn play_hands<B: Bucketer + Sync + Send>(
    agent: &SearchAgent<B>,
    hands: u64,
    seed: u64,
    mut look: impl FnMut(&State, usize, f64),
) -> (f64, u64) {
    let bp: &Blueprint<B> = &agent.bp;
    let c = bp.game().config();
    let mut won = 0.0;
    let mut decisions = 0;
    for h in 0..hands {
        let s = mix(seed ^ mix(h));
        let config = Config::new(
            &[c.stack, c.stack],
            c.small_blind,
            c.big_blind,
            0,
            (h % 2) as usize,
        )
        .unwrap();
        let mut cards: Vec<Card> = (0..52).collect();
        let mut x = s;
        for i in 0..9 {
            x = mix(x.wrapping_add(i as u64 + 1));
            let j = i + (x % (52 - i as u64)) as usize;
            cards.swap(i, j);
        }
        let deal = Deal::new(
            &[[cards[0], cards[1]], [cards[2], cards[3]]],
            [cards[4], cards[5], cards[6], cards[7], cards[8]],
        )
        .unwrap();
        let mut state = State::new(&config, deal).unwrap();
        let mut probs = ActionProbs::new();
        let mut step = 0u64;
        while !state.is_terminal() {
            let seat = state.current_player().unwrap();
            let public = PublicState::new(&state);
            let hole = state.hole_cards(seat);
            probs.clear();
            if seat == 0 {
                let t0 = Instant::now();
                agent.action_probs(&public, hole, &mut probs);
                let ms = t0.elapsed().as_secs_f64() * 1000.0;
                look(&state, seat, ms);
                decisions += 1;
            } else {
                bp.action_probs(&public, hole, &mut probs);
            }
            step += 1;
            let u = (mix(s ^ (step << 8)) >> 11) as f64 / (1u64 << 53) as f64;
            let a = probs.sample(u).expect("some action");
            state.apply(a).expect("a legal action");
        }
        let payouts = state.payouts(&lbr::EvalRanker).expect("the hand is over");
        won += payouts[0] as f64;
    }
    (won, decisions)
}

/// The value at share `p` of the sorted values (`p` 1 the largest); NaN for none.
pub fn percentile(v: &mut [f64], p: f64) -> f64 {
    if v.is_empty() {
        return f64::NAN;
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let i = ((v.len() as f64 - 1.0) * p).round() as usize;
    v[i]
}

pub fn street_name(s: Street) -> &'static str {
    match s {
        Street::Preflop => "preflop",
        Street::Flop => "flop",
        Street::Turn => "turn",
        Street::River => "river",
    }
}

/// Decision time per street: `hands` hands of `agent` against its blueprint
/// ([`play_hands`]), one decision at a time, on the current pool. The agent's records are
/// kept for the run (its solves' times, iterations and sizes).
pub fn bench<B: Bucketer + Sync + Send>(
    agent: &mut SearchAgent<B>,
    hands: u64,
    seed: u64,
) -> Value {
    agent.keep_records = true;
    let mut by_street: std::collections::HashMap<&'static str, Vec<f64>> = Default::default();
    let t0 = Instant::now();
    let (_, decisions) = play_hands(agent, hands, seed, |state, _, ms| {
        by_street
            .entry(street_name(state.street()))
            .or_default()
            .push(ms);
    });
    let records = agent.take_records();
    let mut out = Map::new();
    for s in ["preflop", "flop", "turn", "river"] {
        let mut v = by_street.remove(s).unwrap_or_default();
        let n = v.len();
        let (p50, p95, max) = (
            percentile(&mut v, 0.5),
            percentile(&mut v, 0.95),
            percentile(&mut v, 1.0),
        );
        let of: Vec<_> = records
            .iter()
            .filter(|r| street_name(r.street) == s)
            .collect();
        let mut solves: Vec<f64> = of.iter().map(|r| r.ms).collect();
        let (s50, s95, smax) = (
            percentile(&mut solves, 0.5),
            percentile(&mut solves, 0.95),
            percentile(&mut solves, 1.0),
        );
        let mean = |f: &dyn Fn(&crate::SolveRecord) -> f64| {
            if of.is_empty() {
                f64::NAN
            } else {
                of.iter().map(|r| f(r)).sum::<f64>() / of.len() as f64
            }
        };
        out.insert(
            s.into(),
            json!({"decisions": n, "decision_ms_p50": p50, "decision_ms_p95": p95, "decision_ms_max": max,
                   "solves": of.len(), "resolves": of.iter().filter(|r| r.resolve).count(),
                   "solve_ms_p50": s50, "solve_ms_p95": s95, "solve_ms_max": smax,
                   "mean_iterations": mean(&|r| r.iterations as f64),
                   "mean_exploitability": mean(&|r| r.exploitability),
                   "mean_combos": mean(&|r| (r.combos[0] + r.combos[1]) as f64 / 2.0),
                   "mean_solver_nodes": mean(&|r| r.solver_nodes as f64)}),
        );
    }
    out.insert("hands".into(), json!(hands));
    out.insert("seed".into(), json!(seed));
    out.insert("decisions".into(), json!(decisions));
    out.insert("threads".into(), json!(rayon::current_num_threads()));
    out.insert("seconds".into(), json!(t0.elapsed().as_secs_f64()));
    Value::Object(out)
}
