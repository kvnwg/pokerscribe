//! Simple agents for testing the arena. None of them is meant to play well.
//!
//! | Name | Agent |
//! | --- | --- |
//! | `fold` | [`AlwaysFold`]: checks when it is free, folds to any bet |
//! | `call` | [`AlwaysCall`]: checks or calls, never raises |
//! | `raise` | [`AlwaysRaise`] by the pot |
//! | `minraise` | [`AlwaysRaise`] by the minimum |
//! | `jam` | [`AlwaysRaise`] all in |
//! | `random` | [`RandomBot`]: fold, call or raise with equal chances |
//! | `tag` | [`TightAggressive`]: few hands, played hard |
//! | `tag-loose` | the same, one point looser before the flop (a "next version" to compare) |

use eval::Hand;
use nlhe::{Action, Card, Chips, Street};

use crate::player::{Agent, Player, View};
use crate::ranker::to_eval;

/// The names [`builtin`] knows.
pub const BUILTIN: [&str; 8] = [
    "fold",
    "call",
    "raise",
    "minraise",
    "jam",
    "random",
    "tag",
    "tag-loose",
];

/// A test agent by name (see the table above).
pub fn builtin(name: &str) -> Option<Agent> {
    Some(match name {
        "fold" => Agent::of(name, AlwaysFold),
        "call" => Agent::of(name, AlwaysCall),
        "raise" => Agent::of(name, AlwaysRaise(RaiseSize::Pot)),
        "minraise" => Agent::of(name, AlwaysRaise(RaiseSize::Min)),
        "jam" => Agent::of(name, AlwaysRaise(RaiseSize::AllIn)),
        "random" => Agent::of(name, RandomBot),
        "tag" => Agent::of(name, TightAggressive::default()),
        "tag-loose" => Agent::of(name, TightAggressive { looseness: 1.0 }),
        _ => return None,
    })
}

/// Checks when it is free, folds to any bet.
#[derive(Clone, Copy, Debug, Default)]
pub struct AlwaysFold;

impl Player for AlwaysFold {
    fn act(&mut self, view: &View<'_>) -> Action {
        view.check_or_fold()
    }
}

/// Checks or calls, never raises.
#[derive(Clone, Copy, Debug, Default)]
pub struct AlwaysCall;

impl Player for AlwaysCall {
    fn act(&mut self, view: &View<'_>) -> Action {
        view.check_or_call()
    }
}

/// How much [`AlwaysRaise`] raises.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RaiseSize {
    /// The minimum raise.
    Min,
    /// The size of the pot.
    Pot,
    /// Everything.
    AllIn,
}

/// Bets or raises whenever it may, and calls when raising is closed.
#[derive(Clone, Copy, Debug)]
pub struct AlwaysRaise(pub RaiseSize);

impl Player for AlwaysRaise {
    fn act(&mut self, view: &View<'_>) -> Action {
        match self.0 {
            RaiseSize::Min => view.raise_to(0),
            RaiseSize::Pot => view.raise_pot(1.0),
            RaiseSize::AllIn => view.raise_to(Chips::MAX),
        }
    }
}

/// Picks one of fold (when there is a bet), check or call, and raise (when allowed)
/// with equal chances. A raise goes to an amount drawn evenly between the minimum and
/// a pot-sized raise.
#[derive(Clone, Copy, Debug, Default)]
pub struct RandomBot;

impl Player for RandomBot {
    fn act(&mut self, view: &View<'_>) -> Action {
        let legal = view.legal();
        let mut rng = view.rng();
        let mut options = [view.check_or_call(); 3];
        let mut count = 1;
        if legal.fold {
            options[count] = Action::Fold;
            count += 1;
        }
        if let Some(range) = legal.raise {
            let pot_sized = view
                .max_bet()
                .saturating_add(view.pot())
                .saturating_add(view.to_call())
                .clamp(range.min_to, range.max_to);
            let to = range.min_to + rng.below((pot_sized - range.min_to) as u64 + 1) as Chips;
            options[count] = Action::RaiseTo(to);
            count += 1;
        }
        options[rng.below(count as u64) as usize]
    }
}

/// A tight-aggressive rule bot.
///
/// Before the flop it scores its two cards with the Chen formula and needs a better
/// score the more players are still to act: it opens for 2.5 big blinds, re-raises its
/// best hands and folds the rest. After the flop it looks at how many of the other
/// possible hands it beats right now: it bets or raises strong hands, calls when the
/// price is right for its strength, and folds otherwise. After raising before the flop
/// it bets half the pot on the flop every other time against one opponent, whatever it
/// holds.
#[derive(Clone, Copy, Debug, Default)]
pub struct TightAggressive {
    /// Added to the hand score before the flop: positive plays more hands.
    pub looseness: f32,
}

impl Player for TightAggressive {
    fn act(&mut self, view: &View<'_>) -> Action {
        if view.street() == Street::Preflop {
            self.preflop(view)
        } else {
            self.postflop(view)
        }
    }
}

impl TightAggressive {
    fn preflop(&self, view: &View<'_>) -> Action {
        let score = chen(view.hole()) + self.looseness;
        let seat = view.seat();
        let n = view.num_players();
        let big_blind = view.big_blind();
        let stack = view.stacks()[seat] as f32;
        let to_call = view.to_call() as f32;
        let history = view.history();
        let raises = history
            .iter()
            .filter(|m| matches!(m.action, Action::RaiseTo(_)))
            .count();

        if raises == 0 {
            // Nobody has raised: open, or raise the limpers.
            let behind = (view.big_blind_seat() + n - seat) % n;
            let needed = if behind == 0 {
                8.0
            } else {
                5.0 + 0.8 * behind as f32
            };
            if score >= needed {
                let limpers = history.iter().filter(|m| m.action == Action::Call).count();
                return view.raise_to(big_blind * 5 / 2 + big_blind * limpers as Chips);
            }
            return view.check_or_fold();
        }
        if raises == 1 && to_call <= 0.25 * stack {
            // One raise at a normal price.
            if score >= 11.0 {
                return view.raise_to(view.max_bet().saturating_mul(3));
            }
            let needed = if seat == view.big_blind_seat() {
                7.0
            } else {
                8.0
            };
            return if score >= needed {
                view.check_or_call()
            } else {
                view.check_or_fold()
            };
        }
        // A re-raise, or a bet that is a large part of the stack.
        if score >= 14.0 {
            return view.raise_to(Chips::MAX);
        }
        if score >= 12.0 && to_call <= 0.4 * stack {
            return view.check_or_call();
        }
        view.check_or_fold()
    }

    fn postflop(&self, view: &View<'_>) -> Action {
        let seat = view.seat();
        let opponents = (0..view.num_players())
            .filter(|&s| s != seat && !view.is_folded(s))
            .count() as i32;
        // The chance to be ahead of every opponent, if their hands were random.
        let strength = hand_strength(view.hole(), view.board()).powi(opponents.max(1));
        let to_call = view.to_call();

        if to_call == 0 {
            if strength >= 0.80 {
                return view.raise_pot(0.75);
            }
            let raised_preflop = view
                .history()
                .iter()
                .rfind(|m| m.street == Street::Preflop && matches!(m.action, Action::RaiseTo(_)))
                .is_some_and(|m| m.seat as usize == seat);
            if view.street() == Street::Flop
                && opponents == 1
                && raised_preflop
                && view.rng().below(2) == 0
            {
                return view.raise_pot(0.5);
            }
            return view.check_or_call();
        }
        let price = to_call as f32 / (view.pot() + to_call) as f32;
        if strength >= 0.93 {
            return view.raise_pot(1.0);
        }
        if strength >= 0.45 + price {
            return view.check_or_call();
        }
        view.check_or_fold()
    }
}

/// The Chen formula: a quick score of two hole cards, from -1 (7-2 offsuit) to 20 (aces).
pub fn chen(hole: [Card; 2]) -> f32 {
    let (a, b) = (hole[0] / 4, hole[1] / 4);
    let (high, low) = (a.max(b), a.min(b));
    let points = |rank: u8| match rank {
        12 => 10.0,
        11 => 8.0,
        10 => 7.0,
        9 => 6.0,
        r => (r + 2) as f32 / 2.0,
    };
    if high == low {
        return (2.0 * points(high)).max(5.0);
    }
    let mut score = points(high);
    if hole[0] % 4 == hole[1] % 4 {
        score += 2.0;
    }
    let gap = high - low - 1;
    score -= match gap {
        0 => 0.0,
        1 => 1.0,
        2 => 2.0,
        3 => 4.0,
        _ => 5.0,
    };
    // A straight bonus for close cards below a queen.
    if gap <= 1 && high < 10 {
        score += 1.0;
    }
    score.ceil()
}

/// The share of the other possible hole cards that this hand beats on the board as it
/// is (3 to 5 cards); ties count half. Cards to come are not looked at.
pub fn hand_strength(hole: [Card; 2], board: &[Card]) -> f32 {
    assert!(
        (3..=5).contains(&board.len()),
        "needs a flop, turn or river"
    );
    let mut used = 0u64;
    let mut base = Hand::new();
    for &c in board {
        used |= 1 << c;
        base = base.add(to_eval(c));
    }
    used |= 1 << hole[0] | 1 << hole[1];
    let mine = base.add(to_eval(hole[0])).add(to_eval(hole[1])).eval();
    let (mut ahead, mut tied, mut total) = (0u32, 0u32, 0u32);
    for a in 0..52u8 {
        if used & (1 << a) != 0 {
            continue;
        }
        let with_a = base.add(to_eval(a));
        for b in a + 1..52 {
            if used & (1 << b) != 0 {
                continue;
            }
            let theirs = with_a.add(to_eval(b)).eval();
            total += 1;
            if mine > theirs {
                ahead += 1;
            } else if mine == theirs {
                tied += 1;
            }
        }
    }
    (ahead as f32 + 0.5 * tied as f32) / total as f32
}
