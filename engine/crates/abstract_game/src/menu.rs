//! Bet-size menus: which bets and raises the abstract game offers, as settings.
//!
//! A menu is a list of [`Size`]s for each street and each number of raises already made
//! on that street. [`Menus::actions`] turns it into real `nlhe` actions at a real state:
//! sizes become whole chips, are pushed into the legal raise range, and sizes that land on
//! the same amount are merged.

use std::fmt;

use nlhe::{Action, Chips, State, Street};

/// One bet or raise size.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Size {
    /// A share of the pot: the raise adds this share of the pot as it would stand after
    /// calling. `Pot(1.0)` is a pot-sized bet or raise; `Pot(0.33)` a third of the pot.
    Pot(f64),
    /// Raise to this multiple of the bet being faced. Before any raise preflop the bet
    /// faced is the big blind, so `Times(2.5)` opens to 2.5 big blinds, and facing that
    /// open `Times(3.0)` re-raises to 7.5. Skipped when there is no bet to multiply (the
    /// first bet on the flop, turn or river).
    Times(f64),
    /// The whole stack.
    AllIn,
}

impl fmt::Display for Size {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Size::Pot(x) => write!(f, "{x} pot"),
            Size::Times(x) => write!(f, "{x}x"),
            Size::AllIn => write!(f, "all in"),
        }
    }
}

/// The most sizes one list may hold.
pub const MAX_SIZES: usize = 64;

/// The bet sizes offered in every spot of the game.
#[derive(Clone, Debug, PartialEq)]
pub struct Menus {
    /// `streets[s][k]` lists the sizes offered on street `s` (preflop, flop, turn, river)
    /// once `k` raises have been made on that street. The blinds are not raises, so
    /// preflop `k = 0` is an open (or a raise over a limp), `k = 1` a 3-bet and `k = 2` a
    /// 4-bet; after the flop `k = 0` is the first bet and `k = 1` the first raise. Counts
    /// past the end use the last list. An empty list means no raise is offered there, and
    /// no lists at all means nobody may bet on that street.
    pub streets: [Vec<Vec<Size>>; 4],
    /// Whether the small blind may just call before the flop (limp). Push-or-fold turns
    /// it off. The call stays when no raise is offered, so there is always a way to
    /// continue.
    pub limp: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum MenuError {
    /// A size that is not a positive, finite number (a `Times` must be above 1).
    BadSize {
        street: Street,
        raises: usize,
        size: Size,
    },
    /// More than [`MAX_SIZES`] sizes in one list.
    TooManySizes { street: Street, raises: usize },
}

impl fmt::Display for MenuError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MenuError::BadSize {
                street,
                raises,
                size,
            } => write!(
                f,
                "{street:?} after {raises} raises: {size:?} is not a usable size"
            ),
            MenuError::TooManySizes { street, raises } => write!(
                f,
                "{street:?} after {raises} raises: more than {MAX_SIZES} sizes"
            ),
        }
    }
}

impl std::error::Error for MenuError {}

impl Default for Menus {
    fn default() -> Menus {
        Menus::standard()
    }
}

impl Menus {
    /// All in or fold: the small blind jams or folds, the big blind calls or folds.
    pub fn push_fold() -> Menus {
        Menus {
            streets: [vec![vec![Size::AllIn]], vec![], vec![], vec![]],
            limp: false,
        }
    }

    /// One size in every spot: the smallest game that still plays every street.
    /// Open to 2.5 big blinds, 3-bet to three times that, 4-bet all in; after the flop
    /// bet three quarters of the pot, raise all in.
    pub fn minimal() -> Menus {
        use Size::*;
        let later = vec![vec![Pot(0.75)], vec![AllIn]];
        Menus {
            streets: [
                vec![vec![Times(2.5)], vec![Times(3.0)], vec![AllIn]],
                later.clone(),
                later.clone(),
                later,
            ],
            limp: true,
        }
    }

    /// Two sizes plus all in for the first bet, less after it.
    pub fn small() -> Menus {
        use Size::*;
        let later = vec![vec![Pot(0.5), Pot(1.0), AllIn], vec![Pot(1.0), AllIn]];
        Menus {
            streets: [
                vec![
                    vec![Times(2.5), AllIn],
                    vec![Times(3.0), AllIn],
                    vec![AllIn],
                ],
                later.clone(),
                later.clone(),
                later,
            ],
            limp: true,
        }
    }

    /// The default. Preflop: three opens, two 3-bets and two 4-bets, each with all in,
    /// then all in only. After the flop: a third, three quarters and one and a half
    /// times the pot plus all in for the first bet, three quarters of the pot or all in
    /// for the first raise, then all in only.
    pub fn standard() -> Menus {
        use Size::*;
        let later = vec![
            vec![Pot(0.33), Pot(0.75), Pot(1.5), AllIn],
            vec![Pot(0.75), AllIn],
            vec![AllIn],
        ];
        Menus {
            streets: [
                vec![
                    vec![Times(2.0), Times(2.5), Times(3.0), AllIn],
                    vec![Times(3.0), Times(4.0), AllIn],
                    vec![Times(2.2), Times(2.75), AllIn],
                    vec![AllIn],
                ],
                later.clone(),
                later.clone(),
                later,
            ],
            limp: true,
        }
    }

    /// A menu on the scale Pluribus used: up to 14 sizes for the first bet on the flop,
    /// fewer later in the hand and after each raise. Far too big to train as it is; it is
    /// here to show what such a menu costs.
    pub fn wide() -> Menus {
        use Size::*;
        let later = vec![
            vec![
                Pot(0.25),
                Pot(0.5),
                Pot(0.75),
                Pot(1.0),
                Pot(1.5),
                Pot(2.0),
                AllIn,
            ],
            vec![Pot(0.5), Pot(1.0), AllIn],
            vec![Pot(1.0), AllIn],
            vec![AllIn],
        ];
        Menus {
            streets: [
                vec![
                    vec![
                        Times(2.0),
                        Times(2.25),
                        Times(2.5),
                        Times(2.75),
                        Times(3.0),
                        Times(3.5),
                        Times(4.0),
                        Times(5.0),
                        AllIn,
                    ],
                    vec![
                        Times(2.5),
                        Times(3.0),
                        Times(3.5),
                        Times(4.0),
                        Times(5.0),
                        AllIn,
                    ],
                    vec![Times(2.0), Times(2.25), Times(2.5), Times(3.0), AllIn],
                    vec![Times(2.0), Times(2.5), AllIn],
                    vec![AllIn],
                ],
                vec![
                    vec![
                        Pot(0.1),
                        Pot(0.25),
                        Pot(0.33),
                        Pot(0.5),
                        Pot(0.66),
                        Pot(0.75),
                        Pot(1.0),
                        Pot(1.25),
                        Pot(1.5),
                        Pot(2.0),
                        Pot(3.0),
                        Pot(4.0),
                        Pot(6.0),
                        AllIn,
                    ],
                    vec![Pot(0.5), Pot(0.75), Pot(1.0), Pot(1.5), AllIn],
                    vec![Pot(0.75), Pot(1.5), AllIn],
                    vec![AllIn],
                ],
                later.clone(),
                later,
            ],
            limp: true,
        }
    }

    /// Checks every size is a positive, finite number.
    pub fn validate(&self) -> Result<(), MenuError> {
        for (s, levels) in self.streets.iter().enumerate() {
            let street = Street::ALL[s];
            for (raises, sizes) in levels.iter().enumerate() {
                if sizes.len() > MAX_SIZES {
                    return Err(MenuError::TooManySizes { street, raises });
                }
                for &size in sizes {
                    let ok = match size {
                        Size::Pot(x) => x.is_finite() && x > 0.0,
                        Size::Times(x) => x.is_finite() && x > 1.0,
                        Size::AllIn => true,
                    };
                    if !ok {
                        return Err(MenuError::BadSize {
                            street,
                            raises,
                            size,
                        });
                    }
                }
            }
        }
        Ok(())
    }

    /// The sizes offered on `street` after `raises` raises on it.
    pub fn sizes(&self, street: Street, raises: usize) -> &[Size] {
        let levels = &self.streets[street.index()];
        match levels.len() {
            0 => &[],
            n => &levels[raises.min(n - 1)],
        }
    }

    /// The longest list of sizes anywhere in the menu.
    pub fn most_sizes(&self) -> usize {
        self.streets
            .iter()
            .flatten()
            .map(|sizes| sizes.len())
            .max()
            .unwrap_or(0)
    }

    /// The abstract game's actions for the player to act in `state`, appended to `out`:
    /// fold (when there is a bet to call), check or call, then the menu's raises from the
    /// smallest to the largest. Nothing is appended once the hand is over.
    ///
    /// Each size becomes a whole number of chips. One below the minimum raise becomes the
    /// minimum raise, one above the stack becomes all in, and sizes that land on the same
    /// amount are offered once. Every action is legal in `state`.
    pub fn actions(&self, state: &State, out: &mut Vec<Action>) {
        let Some(seat) = state.current_player() else {
            return;
        };
        let legal = state.legal_actions();
        let mut raises = [0 as Chips; MAX_SIZES];
        let mut n = 0;
        if let Some(range) = legal.raise {
            let max_bet = state.max_bet();
            let to_call = max_bet - state.bets()[seat];
            let pot_after_call = (state.pot() + to_call) as f64;
            for &size in self.sizes(state.street(), raises_this_street(state)) {
                let target = match size {
                    Size::Pot(share) => max_bet as f64 + share * pot_after_call,
                    Size::Times(_) if max_bet == 0 => continue,
                    Size::Times(times) => times * max_bet as f64,
                    Size::AllIn => range.max_to as f64,
                };
                let to = target
                    .round()
                    .clamp(range.min_to as f64, range.max_to as f64)
                    as Chips;
                if n < MAX_SIZES && !raises[..n].contains(&to) {
                    raises[n] = to;
                    n += 1;
                }
            }
            raises[..n].sort_unstable();
        }
        // Heads-up, the first decision before the flop is the small blind's: calling
        // there is the limp.
        let limp = state.street() == Street::Preflop && state.history().is_empty();
        if legal.fold {
            out.push(Action::Fold);
        }
        if legal.check {
            out.push(Action::Check);
        }
        if legal.call.is_some() && (self.limp || !limp || n == 0) {
            out.push(Action::Call);
        }
        out.extend(raises[..n].iter().map(|&to| Action::RaiseTo(to)));
    }
}

/// How many bets and raises have been made on the street `state` is on.
pub fn raises_this_street(state: &State) -> usize {
    let street = state.street();
    state
        .history()
        .iter()
        .rev()
        .take_while(|m| m.street == street)
        .filter(|m| matches!(m.action, Action::RaiseTo(_)))
        .count()
}

/// The size of a raise to `to` chips as a share of the pot, the way [`Size::Pot`] counts
/// it: what the raise adds beyond the call, over the pot after calling.
pub fn pot_fraction(state: &State, to: Chips) -> f64 {
    let seat = state.current_player().unwrap_or(0);
    let max_bet = state.max_bet();
    let to_call = max_bet - state.bets()[seat];
    (to as f64 - max_bet as f64) / (state.pot() + to_call) as f64
}

#[cfg(test)]
mod tests {
    use super::*;
    use nlhe::Config;

    fn hand(stack: Chips) -> State {
        let config = Config::new(&[stack, stack], 50, 100, 0, 0).unwrap();
        State::from_seed(&config, 1)
    }

    fn actions(menus: &Menus, state: &State) -> Vec<Action> {
        let mut out = Vec::new();
        menus.actions(state, &mut out);
        out
    }

    use Action::{Call, Check, Fold, RaiseTo};

    #[test]
    fn standard_menu_before_the_flop() {
        let m = Menus::standard();
        let mut s = hand(10_000);
        // Opens of 2, 2.5 and 3 big blinds, or all in.
        assert_eq!(
            actions(&m, &s),
            [
                Fold,
                Call,
                RaiseTo(200),
                RaiseTo(250),
                RaiseTo(300),
                RaiseTo(10_000)
            ]
        );
        s.apply(RaiseTo(250)).unwrap();
        // 3-bets to 3 and 4 times the open.
        assert_eq!(
            actions(&m, &s),
            [Fold, Call, RaiseTo(750), RaiseTo(1_000), RaiseTo(10_000)]
        );
        s.apply(RaiseTo(1_000)).unwrap();
        // 4-bets to 2.2 and 2.75 times the 3-bet.
        assert_eq!(
            actions(&m, &s),
            [Fold, Call, RaiseTo(2_200), RaiseTo(2_750), RaiseTo(10_000)]
        );
        s.apply(RaiseTo(2_200)).unwrap();
        // Then all in only.
        assert_eq!(actions(&m, &s), [Fold, Call, RaiseTo(10_000)]);
        s.apply(RaiseTo(10_000)).unwrap();
        assert_eq!(actions(&m, &s), [Fold, Call]);
    }

    #[test]
    fn a_raise_over_a_limp_uses_the_opening_sizes() {
        let m = Menus::standard();
        let mut s = hand(10_000);
        s.apply(Call).unwrap();
        assert_eq!(
            actions(&m, &s),
            [
                Check,
                RaiseTo(200),
                RaiseTo(250),
                RaiseTo(300),
                RaiseTo(10_000)
            ]
        );
    }

    #[test]
    fn standard_menu_after_the_flop() {
        let m = Menus::standard();
        let mut s = hand(10_000);
        s.apply(RaiseTo(250)).unwrap();
        s.apply(Call).unwrap();
        // Pot 500: a third is 165, three quarters 375, one and a half times 750.
        assert_eq!(s.street(), Street::Flop);
        assert_eq!(
            actions(&m, &s),
            [
                Check,
                RaiseTo(165),
                RaiseTo(375),
                RaiseTo(750),
                RaiseTo(9_750)
            ]
        );
        s.apply(RaiseTo(375)).unwrap();
        // Facing 375 into 500: the pot after calling is 1,250, three quarters of it is
        // 937.5, so the raise goes to 375 + 938.
        assert_eq!(
            actions(&m, &s),
            [Fold, Call, RaiseTo(1_313), RaiseTo(9_750)]
        );
        s.apply(RaiseTo(1_313)).unwrap();
        assert_eq!(actions(&m, &s), [Fold, Call, RaiseTo(9_750)]);
    }

    #[test]
    fn a_size_below_the_minimum_bet_becomes_the_minimum_bet() {
        let m = Menus::standard();
        let mut s = hand(10_000);
        s.apply(Call).unwrap();
        s.apply(Check).unwrap();
        // Limped pot of 200: a third of it is 66, less than the big blind.
        assert_eq!(
            actions(&m, &s),
            [
                Check,
                RaiseTo(100),
                RaiseTo(150),
                RaiseTo(300),
                RaiseTo(9_900)
            ]
        );
        s.apply(RaiseTo(150)).unwrap();
        // Pot after calling 500: 150 + 375.
        assert_eq!(actions(&m, &s), [Fold, Call, RaiseTo(525), RaiseTo(9_900)]);
    }

    #[test]
    fn sizes_that_land_on_the_same_amount_are_offered_once() {
        let m = Menus::standard();
        // 3 big blinds: the largest open is the whole stack.
        let s = hand(300);
        assert_eq!(
            actions(&m, &s),
            [Fold, Call, RaiseTo(200), RaiseTo(250), RaiseTo(300)]
        );
        // 1.6 big blinds: no full raise fits, every size is all in.
        let s = hand(160);
        assert_eq!(actions(&m, &s), [Fold, Call, RaiseTo(160)]);
    }

    #[test]
    fn push_or_fold() {
        let m = Menus::push_fold();
        let mut s = hand(1_000);
        assert_eq!(actions(&m, &s), [Fold, RaiseTo(1_000)]);
        s.apply(RaiseTo(1_000)).unwrap();
        assert_eq!(actions(&m, &s), [Fold, Call]);
        s.apply(Call).unwrap();
        assert!(s.is_terminal());
        assert!(actions(&m, &s).is_empty());
        // A stack too short to raise keeps the call, so the small blind can still play.
        let s = hand(100);
        assert_eq!(actions(&m, &s), [Fold, Call]);
    }

    #[test]
    fn levels_and_empty_menus() {
        let mut m = Menus::minimal();
        assert_eq!(m.sizes(Street::Preflop, 0), [Size::Times(2.5)]);
        assert_eq!(m.sizes(Street::Preflop, 7), [Size::AllIn]);
        assert_eq!(m.most_sizes(), 1);
        assert_eq!(Menus::wide().most_sizes(), 14);
        // No lists on the flop: check or nothing.
        m.streets[1].clear();
        let mut s = hand(10_000);
        s.apply(Call).unwrap();
        s.apply(Check).unwrap();
        assert_eq!(actions(&m, &s), [Check]);
        // A multiple of the bet faced needs a bet to multiply.
        m.streets[1] = vec![vec![Size::Times(3.0)]];
        assert_eq!(actions(&m, &s), [Check]);
    }

    #[test]
    fn pot_fraction_inverts_the_pot_size() {
        let mut s = hand(10_000);
        s.apply(RaiseTo(250)).unwrap();
        s.apply(Call).unwrap();
        assert_eq!(pot_fraction(&s, 375), 0.75);
        s.apply(RaiseTo(375)).unwrap();
        assert_eq!(pot_fraction(&s, 375 + 1_250), 1.0);
        assert_eq!(raises_this_street(&s), 1);
    }

    #[test]
    fn bad_sizes_are_rejected() {
        for m in [
            Menus::push_fold(),
            Menus::minimal(),
            Menus::small(),
            Menus::standard(),
            Menus::wide(),
        ] {
            assert_eq!(m.validate(), Ok(()));
        }
        let mut m = Menus::minimal();
        m.streets[2][0][0] = Size::Pot(-1.0);
        assert!(matches!(
            m.validate(),
            Err(MenuError::BadSize {
                street: Street::Turn,
                raises: 0,
                ..
            })
        ));
        m.streets[2][0][0] = Size::Times(1.0);
        assert!(m.validate().is_err());
        m.streets[2][0] = vec![Size::AllIn; MAX_SIZES + 1];
        assert!(matches!(m.validate(), Err(MenuError::TooManySizes { .. })));
    }
}
