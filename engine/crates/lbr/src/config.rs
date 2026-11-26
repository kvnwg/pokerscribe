//! LBR's settings: which bets it weighs on which streets.

use nlhe::Street;

/// A bet or raise LBR may consider.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum BetSize {
    /// A fraction of the pot. With nothing to call, the bet is the fraction times the pot.
    /// Facing a bet, LBR calls and raises by the fraction times the pot after its call (so
    /// `Pot(1.0)` is the usual pot-sized raise). A size below the minimum bet becomes the
    /// minimum bet and a size above the stack becomes all in, as in the paper.
    Pot(f64),
    /// The whole stack.
    AllIn,
}

/// What LBR does on one street.
#[derive(Clone, Debug, PartialEq)]
pub enum StreetPolicy {
    /// Always check or call: no folding, no betting. The range is still tracked.
    CheckCall,
    /// Local best response over fold, call and these bets. No bets gives fold or call only.
    Local { bets: Vec<BetSize> },
}

/// How LBR gets win probabilities before the flop. Only used when the preflop street is
/// [`StreetPolicy::Local`].
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PreflopEquity {
    /// Every board, as in the paper. Exact, but each of the 169 starting-hand classes costs
    /// about 2 billion evaluations the first time it comes up (kept for the process).
    Exhaustive,
    /// This many random boards per hand. Fast from the first hand, and the only practical
    /// choice in a debug build.
    Sampled { boards: u32 },
}

/// LBR's settings.
///
/// The paper names a setting by its bets (fc, fcpa, 56 bets) and by the rounds where LBR
/// thinks (1-4 is every street, 3-4 is the turn and river with check or call before).
/// [`LbrConfig::fcpa`] with [`Street::Turn`] is "fcpa, rounds 3-4".
#[derive(Clone, Debug, PartialEq)]
pub struct LbrConfig {
    /// One policy per street: preflop, flop, turn, river.
    pub streets: [StreetPolicy; 4],
    pub preflop_equity: PreflopEquity,
}

/// The paper's "fcpa" bets: pot and all in (fold and call are always there).
pub fn bets_fcpa() -> Vec<BetSize> {
    vec![BetSize::Pot(1.0), BetSize::AllIn]
}

/// The paper's "56 bets": all in and the 55 pot fractions `0.05 * 1.15^k` for k = 0 to 54
/// (5% of the pot up to about 95 pots).
pub fn bets_56() -> Vec<BetSize> {
    let mut bets: Vec<BetSize> = (0..55)
        .map(|k| BetSize::Pot(0.05 * 1.15f64.powi(k)))
        .collect();
    bets.push(BetSize::AllIn);
    bets
}

impl LbrConfig {
    /// Local best response with `bets` from street `first` on, and check or call before it.
    pub fn new(bets: &[BetSize], first: Street) -> LbrConfig {
        LbrConfig {
            streets: Street::ALL.map(|street| {
                if street < first {
                    StreetPolicy::CheckCall
                } else {
                    StreetPolicy::Local {
                        bets: bets.to_vec(),
                    }
                }
            }),
            preflop_equity: PreflopEquity::Exhaustive,
        }
    }

    /// Fold or call only ("fc").
    pub fn fc(first: Street) -> LbrConfig {
        LbrConfig::new(&[], first)
    }

    /// Fold, call, pot and all in ("fcpa").
    pub fn fcpa(first: Street) -> LbrConfig {
        LbrConfig::new(&bets_fcpa(), first)
    }

    /// Fold, call and the 56 bets of [`bets_56`].
    pub fn bets56(first: Street) -> LbrConfig {
        LbrConfig::new(&bets_56(), first)
    }

    /// The same settings with sampled win probabilities before the flop.
    pub fn with_sampled_preflop(mut self, boards: u32) -> LbrConfig {
        self.preflop_equity = PreflopEquity::Sampled { boards };
        self
    }

    /// The settings the paper ran against every bot (Table 3, leaving out "on-tree", which
    /// depends on the bot), with the paper's names. Report the largest win rate over them.
    pub fn paper_settings() -> Vec<(&'static str, LbrConfig)> {
        vec![
            ("fc, rounds 1-4", LbrConfig::fc(Street::Preflop)),
            ("fc, rounds 3-4", LbrConfig::fc(Street::Turn)),
            ("fcpa, rounds 3-4", LbrConfig::fcpa(Street::Turn)),
            ("56 bets, rounds 1-4", LbrConfig::bets56(Street::Preflop)),
            ("56 bets, rounds 3-4", LbrConfig::bets56(Street::Turn)),
        ]
    }
}

impl Default for LbrConfig {
    /// "fcpa, rounds 3-4": check or call before the turn, then fold, call, pot or all in.
    /// In the paper most of what LBR won from every bot came with this setting.
    fn default() -> LbrConfig {
        LbrConfig::fcpa(Street::Turn)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_56_bets_are_the_papers() {
        let bets = bets_56();
        assert_eq!(bets.len(), 56);
        assert_eq!(bets[0], BetSize::Pot(0.05));
        assert_eq!(bets[55], BetSize::AllIn);
        let BetSize::Pot(largest) = bets[54] else {
            panic!("the last pot fraction")
        };
        assert!((largest - 0.05 * 1.15f64.powf(54.0)).abs() < 1e-9);
        assert!((94.0..96.0).contains(&largest));
    }

    #[test]
    fn rounds_before_the_first_are_check_or_call() {
        let c = LbrConfig::fcpa(Street::Turn);
        assert_eq!(c.streets[0], StreetPolicy::CheckCall);
        assert_eq!(c.streets[1], StreetPolicy::CheckCall);
        assert_eq!(c.streets[2], StreetPolicy::Local { bets: bets_fcpa() });
        assert_eq!(c.streets[3], StreetPolicy::Local { bets: bets_fcpa() });
        assert_eq!(c, LbrConfig::default());
        let all = LbrConfig::fc(Street::Preflop);
        assert!(all
            .streets
            .iter()
            .all(|s| *s == StreetPolicy::Local { bets: vec![] }));
    }
}
