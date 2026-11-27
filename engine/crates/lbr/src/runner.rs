//! Matches: LBR against a strategy over many hands, from both seats, on every core.

use std::fmt;

use nlhe::{Chips, Config, Deal, Rng, State};
use rayon::prelude::*;

use crate::config::LbrConfig;
use crate::player::Lbr;
use crate::public::PublicState;
use crate::ranker::EvalRanker;
use crate::strategy::{ActionProbs, Strategy};

/// The table and the length of a match. Stacks are reset every hand.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MatchConfig {
    /// Hands to play. Each deal is played twice, once with LBR in each seat, so an odd
    /// number is rounded up.
    pub hands: u64,
    /// The same seed gives the same cards, the same opponent actions and the same result,
    /// whatever the number of cores.
    pub seed: u64,
    pub small_blind: Chips,
    pub big_blind: Chips,
    /// Both players' stack at the start of every hand.
    pub stack: Chips,
}

impl MatchConfig {
    /// The table of the Annual Computer Poker Competition and of the paper: blinds 50 and
    /// 100, stacks of 20,000 (200 big blinds).
    pub fn acpc(hands: u64, seed: u64) -> MatchConfig {
        MatchConfig {
            hands,
            seed,
            small_blind: 50,
            big_blind: 100,
            stack: 20_000,
        }
    }
}

/// What LBR won. Positive means the strategy lost.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MatchResult {
    /// Hands played (twice the number of deals).
    pub hands: u64,
    /// LBR's win rate in big blinds per 100 hands. 100 bb/100 is 1,000 mBB per hand.
    pub bb_per_100: f64,
    /// The standard error of `bb_per_100`. Each deal's two hands (the same cards with the
    /// seats swapped) count as one observation, so the luck of the deal partly cancels.
    pub std_err: f64,
    /// LBR's win rate on the button (the small blind), in bb/100.
    pub button_bb_per_100: f64,
    /// LBR's win rate in the big blind, in bb/100.
    pub big_blind_bb_per_100: f64,
}

impl fmt::Display for MatchResult {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{:+.1} ± {:.1} bb/100 over {} hands (button {:+.1}, big blind {:+.1})",
            self.bb_per_100,
            self.std_err,
            self.hands,
            self.button_bb_per_100,
            self.big_blind_bb_per_100
        )
    }
}

/// SplitMix64's output step: turns a counter into an unrelated-looking seed.
fn mix(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// The seed of deal number `index` in a match with seed `seed`.
fn deal_seed(seed: u64, index: u64) -> u64 {
    mix(mix(seed).wrapping_add(index.wrapping_mul(0x9E37_79B9_7F4A_7C15)))
}

/// A uniform number in `[0, 1)`.
fn uniform(rng: &mut Rng) -> f64 {
    (rng.next_u64() >> 11) as f64 / (1u64 << 53) as f64
}

/// Plays one hand and returns the chips LBR won (negative for a loss).
///
/// The cards come from `seed` alone, and they stay with the positions: the big blind gets
/// the same two cards whoever sits there. Playing a seed with `lbr_on_button` true and then
/// false is one duplicate deal.
pub fn play_hand(
    opponent: &dyn Strategy,
    lbr_config: &LbrConfig,
    table: &MatchConfig,
    seed: u64,
    lbr_on_button: bool,
) -> i64 {
    // LBR is seat 0. Heads-up the button is the small blind.
    const LBR: usize = 0;
    const OPPONENT: usize = 1;
    let button = if lbr_on_button { LBR } else { OPPONENT };
    let config = Config::new(
        &[table.stack, table.stack],
        table.small_blind,
        table.big_blind,
        0,
        button,
    )
    .expect("a valid table");
    let mut state = State::new(&config, Deal::from_seed(seed, 2, button))
        .expect("a seeded deal is always valid");
    let mut lbr = Lbr::new(
        lbr_config,
        opponent,
        LBR,
        state.hole_cards(LBR),
        mix(seed ^ 0x4C42_5221),
    );
    let opponent_hole = state.hole_cards(OPPONENT);
    let mut rng = Rng::new(mix(seed ^ (0x4F50_5021 + button as u64)));
    let mut probs = ActionProbs::new();

    while let Some(seat) = state.current_player() {
        let action = if seat == LBR {
            lbr.act(&state)
        } else {
            probs.clear();
            opponent.action_probs(&PublicState::new(&state), opponent_hole, &mut probs);
            let action = probs
                .sample(uniform(&mut rng))
                .expect("the strategy gave no action a positive probability");
            lbr.observe(&state, action);
            action
        };
        if let Err(error) = state.apply(action) {
            let who = if seat == LBR { "LBR" } else { "the strategy" };
            panic!("{who} chose an illegal action: {error}");
        }
    }
    state.payouts(&EvalRanker).expect("the hand is over")[LBR]
}

/// Plays LBR against `opponent` and reports what LBR won.
///
/// Each deal is played twice with the seats swapped (a duplicate match), on all cores. The
/// result depends only on the arguments, not on the number of cores or the order the hands
/// finish in.
pub fn play_match(
    opponent: &dyn Strategy,
    lbr_config: &LbrConfig,
    table: &MatchConfig,
) -> MatchResult {
    let deals = table.hands.div_ceil(2);
    // Chips won per deal: (LBR on the button, LBR in the big blind).
    let won: Vec<(i64, i64)> = (0..deals)
        .into_par_iter()
        .map(|index| {
            let seed = deal_seed(table.seed, index);
            (
                play_hand(opponent, lbr_config, table, seed, true),
                play_hand(opponent, lbr_config, table, seed, false),
            )
        })
        .collect();

    let n = deals as f64;
    // One hand's worth of big blinds, times 100.
    let scale = 100.0 / table.big_blind as f64;
    let button: f64 = won.iter().map(|w| w.0 as f64).sum::<f64>() / n;
    let big_blind: f64 = won.iter().map(|w| w.1 as f64).sum::<f64>() / n;
    let mean = (button + big_blind) / 2.0;
    let squares: f64 = won
        .iter()
        .map(|w| ((w.0 + w.1) as f64 / 2.0 - mean).powi(2))
        .sum();
    let std_err = if deals > 1 {
        (squares / (n - 1.0) / n).sqrt()
    } else {
        f64::NAN
    };
    MatchResult {
        hands: 2 * deals,
        bb_per_100: mean * scale,
        std_err: std_err * scale,
        button_bb_per_100: button * scale,
        big_blind_bb_per_100: big_blind * scale,
    }
}
