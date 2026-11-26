//! Mapping a bet that is not in the menu onto the sizes that are: the pseudo-harmonic
//! mapping of Ganzfried and Sandholm, "Action Translation in Extensive-Form Games with
//! Large Action Spaces: Axioms, Paradoxes, and the Pseudo-Harmonic Mapping" (IJCAI 2013).
//!
//! Sizes are shares of the pot. A bet of `x` between two menu sizes `a < x < b` is read
//! as `a` with probability
//!
//! ```text
//! f(x) = (b - x)(1 + a) / ((b - a)(1 + x))
//! ```
//!
//! and as `b` otherwise. The formula comes from the calling frequency that makes a bluff
//! of size `x` break even, `1 / (1 + x)`: `f` is the weight that puts that frequency for
//! `x` between the ones for `a` and `b`,
//! `f / (1 + a) + (1 - f) / (1 + b) = 1 / (1 + x)`.

/// The probability that a bet of `x` is read as the smaller size `a` rather than the
/// larger size `b`, with `0 <= a < b` and all three as shares of the pot. A bet at or
/// below `a` gives 1, at or above `b` gives 0.
pub fn pseudo_harmonic(a: f64, b: f64, x: f64) -> f64 {
    assert!(
        a >= 0.0 && a < b,
        "pseudo-harmonic mapping needs 0 <= a < b, got {a} and {b}"
    );
    if x <= a {
        1.0
    } else if x >= b {
        0.0
    } else {
        (b - x) * (1.0 + a) / ((b - a) * (1.0 + x))
    }
}

/// The bet size between `a` and `b` that is read as either with probability one half.
pub fn midpoint(a: f64, b: f64) -> f64 {
    (a + b + 2.0 * a * b) / (a + b + 2.0)
}

/// Where a bet falls on a menu: the menu sizes on either side of it (indices into the
/// menu) and the probability of the smaller one. An exact size, and a bet outside the
/// menu's range, has `lower == upper` and probability 1.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Mapping {
    pub lower: usize,
    pub upper: usize,
    pub p_lower: f64,
}

impl Mapping {
    /// The randomised mapping the paper recommends: `u` is a uniform draw from 0 to 1.
    pub fn pick(&self, u: f64) -> usize {
        if u < self.p_lower {
            self.lower
        } else {
            self.upper
        }
    }

    /// The more likely of the two sizes (the smaller one on a tie).
    pub fn nearest(&self) -> usize {
        if self.p_lower >= 0.5 {
            self.lower
        } else {
            self.upper
        }
    }

    /// The probability that the bet is read as menu size `index`.
    pub fn probability(&self, index: usize) -> f64 {
        if index == self.lower {
            self.p_lower
        } else if index == self.upper {
            1.0 - self.p_lower
        } else {
            0.0
        }
    }
}

/// Maps a bet of `x` onto `sizes`, the menu's sizes in increasing order (shares of the
/// pot, at least one). A size on the menu maps to itself. A bet below the smallest size
/// maps to the smallest and one above the largest to the largest. To let small bets be
/// read as a check or call, as the paper allows, put 0 first in the menu.
pub fn map_size(sizes: &[f64], x: f64) -> Mapping {
    assert!(!sizes.is_empty(), "the menu has no sizes");
    debug_assert!(
        sizes.windows(2).all(|w| w[0] < w[1]),
        "menu sizes must increase"
    );
    let upper = sizes.partition_point(|&s| s < x);
    if upper == sizes.len() {
        let last = sizes.len() - 1;
        return Mapping {
            lower: last,
            upper: last,
            p_lower: 1.0,
        };
    }
    if upper == 0 || sizes[upper] == x {
        return Mapping {
            lower: upper,
            upper,
            p_lower: 1.0,
        };
    }
    Mapping {
        lower: upper - 1,
        upper,
        p_lower: pseudo_harmonic(sizes[upper - 1], sizes[upper], x),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MENUS: [&[f64]; 4] = [
        &[0.33, 0.75, 1.5, 19.5],
        &[0.0, 0.5, 1.0, 2.0],
        &[1.0],
        &[
            0.1, 0.25, 0.33, 0.5, 0.66, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 40.0,
        ],
    ];

    fn close(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-12
    }

    #[test]
    fn exact_sizes_map_to_themselves() {
        for menu in MENUS {
            for (i, &size) in menu.iter().enumerate() {
                let m = map_size(menu, size);
                assert_eq!((m.lower, m.upper, m.p_lower), (i, i, 1.0), "{size}");
                assert_eq!(m.nearest(), i);
                assert_eq!(m.pick(0.0), i);
                assert_eq!(m.pick(0.999_999), i);
                assert_eq!(m.probability(i), 1.0);
            }
        }
        // The same at the two ends of the formula.
        assert_eq!(pseudo_harmonic(0.5, 1.0, 0.5), 1.0);
        assert_eq!(pseudo_harmonic(0.5, 1.0, 1.0), 0.0);
    }

    #[test]
    fn hand_worked_examples() {
        // Half pot or pot, facing three quarters: (0.25 x 1.5) / (0.5 x 1.75) = 3/7.
        assert!(close(pseudo_harmonic(0.5, 1.0, 0.75), 3.0 / 7.0));
        // Pot or twice the pot, facing one and a half: (0.5 x 2) / (1 x 2.5) = 2/5.
        assert!(close(pseudo_harmonic(1.0, 2.0, 1.5), 0.4));
        // Check or pot, facing half pot: (0.5 x 1) / (1 x 1.5) = 1/3.
        assert!(close(pseudo_harmonic(0.0, 1.0, 0.5), 1.0 / 3.0));
        // Check or pot, facing a tenth of the pot: 0.9 / 1.1 = 9/11.
        assert!(close(pseudo_harmonic(0.0, 1.0, 0.1), 9.0 / 11.0));
        // A third or three quarters, facing half pot: (0.25 x 4/3) / (5/12 x 1.5) = 8/15.
        assert!(close(pseudo_harmonic(1.0 / 3.0, 0.75, 0.5), 8.0 / 15.0));
        // Pot or ten times the pot, facing three times: (7 x 2) / (9 x 4) = 7/18. The
        // arithmetic middle, 5.5, is far closer to the big bet: (4.5 x 2) / (9 x 6.5).
        assert!(close(pseudo_harmonic(1.0, 10.0, 3.0), 7.0 / 18.0));
        assert!(close(pseudo_harmonic(1.0, 10.0, 5.5), 2.0 / 13.0));

        // Through a menu: the bet lands between the right neighbours.
        let m = map_size(&[0.5, 1.0, 2.0], 1.5);
        assert_eq!((m.lower, m.upper), (1, 2));
        assert!(close(m.p_lower, 0.4));
        assert!(close(m.probability(1), 0.4) && close(m.probability(2), 0.6));
        assert_eq!(m.probability(0), 0.0);
        assert_eq!(m.nearest(), 2);
        assert_eq!((m.pick(0.39), m.pick(0.41)), (1, 2));
    }

    #[test]
    fn a_coin_flip_at_the_midpoint() {
        // Check or pot: a third of the pot is the even point, well under half pot.
        assert!(close(midpoint(0.0, 1.0), 1.0 / 3.0));
        for (a, b) in [
            (0.0, 1.0),
            (0.5, 1.0),
            (0.33, 0.75),
            (1.0, 10.0),
            (2.0, 40.0),
        ] {
            let x = midpoint(a, b);
            assert!(a < x && x < b);
            assert!(close(pseudo_harmonic(a, b, x), 0.5), "{a} {b}");
            // Never above the arithmetic middle.
            assert!(x <= (a + b) / 2.0);
        }
    }

    #[test]
    fn monotone() {
        // Between two sizes the probability of the smaller one falls from 1 to 0.
        for (a, b) in [
            (0.0, 1.0),
            (0.5, 1.0),
            (0.33, 0.75),
            (1.0, 10.0),
            (2.0, 40.0),
        ] {
            let mut last = 1.0;
            for i in 0..=1_000 {
                let x = a + (b - a) * i as f64 / 1_000.0;
                let p = pseudo_harmonic(a, b, x);
                assert!((0.0..=1.0).contains(&p));
                assert!(p <= last, "{a} {b} {x}: {p} after {last}");
                if i > 0 && i < 1_000 {
                    assert!(p < last, "strictly falling inside the interval");
                }
                last = p;
            }
            assert_eq!(last, 0.0);
        }
        // Across a whole menu a bigger bet never maps to a smaller size on average.
        for menu in MENUS {
            let top = menu[menu.len() - 1] * 1.2 + 0.1;
            let mut last = -1.0;
            for i in 0..=20_000 {
                let x = top * i as f64 / 20_000.0;
                let m = map_size(menu, x);
                assert!(m.lower <= m.upper && m.upper < menu.len());
                let mean = mean_index(&m);
                assert!(mean >= last, "{menu:?} at {x}");
                last = mean;
            }
            assert_eq!(last, (menu.len() - 1) as f64);
        }
    }

    fn mean_index(m: &Mapping) -> f64 {
        m.lower as f64 * m.p_lower + m.upper as f64 * (1.0 - m.p_lower)
    }

    #[test]
    fn no_jump_at_a_menu_size() {
        // Just under and just over a menu size, the bet is read as that size almost surely.
        for menu in MENUS {
            for (i, &size) in menu.iter().enumerate() {
                for x in [size - 1e-9, size + 1e-9] {
                    if x >= 0.0 {
                        let mean = mean_index(&map_size(menu, x));
                        assert!((mean - i as f64).abs() < 1e-6, "{menu:?} at {x}");
                    }
                }
            }
        }
    }

    #[test]
    fn outside_the_menu() {
        let menu = [0.5, 1.0, 2.0];
        assert_eq!(
            map_size(&menu, 0.2),
            Mapping {
                lower: 0,
                upper: 0,
                p_lower: 1.0
            }
        );
        assert_eq!(
            map_size(&menu, 7.0),
            Mapping {
                lower: 2,
                upper: 2,
                p_lower: 1.0
            }
        );
        // With 0 on the menu a small bet is read as a check some of the time.
        let m = map_size(&[0.0, 0.5, 1.0, 2.0], 0.2);
        assert_eq!((m.lower, m.upper), (0, 1));
        assert!(close(m.p_lower, 0.3 / (0.5 * 1.2)));
    }

    #[test]
    fn keeps_the_break_even_calling_frequency() {
        // The defining property: the calling frequency 1 / (1 + x) that makes a bluff of
        // x break even is the same mix of the frequencies for a and b.
        for (a, b) in [
            (0.0, 1.0),
            (0.5, 1.0),
            (0.33, 0.75),
            (1.0, 10.0),
            (2.0, 40.0),
        ] {
            for i in 1..100 {
                let x = a + (b - a) * i as f64 / 100.0;
                let f = pseudo_harmonic(a, b, x);
                let mixed = f / (1.0 + a) + (1.0 - f) / (1.0 + b);
                assert!(close(mixed, 1.0 / (1.0 + x)), "{a} {b} {x}");
            }
        }
    }

    #[test]
    fn robust_to_small_changes() {
        // Moving a menu size a little moves the probability a little (the paper's
        // action and boundary robustness), including when the bet sits next to a size.
        let eps = 1e-6;
        for (a, b, x) in [(0.5, 1.0, 0.75), (0.0, 1.0, 1e-3), (1.0, 10.0, 9.999)] {
            let p = pseudo_harmonic(a, b, x);
            assert!((pseudo_harmonic(a + eps, b, x.max(a + eps)) - p).abs() < 1e-4);
            assert!((pseudo_harmonic(a, b - eps, x.min(b - eps)) - p).abs() < 1e-4);
        }
    }

    #[test]
    #[should_panic(expected = "needs 0 <= a < b")]
    fn sizes_out_of_order_panic() {
        pseudo_harmonic(1.0, 0.5, 0.75);
    }
}
