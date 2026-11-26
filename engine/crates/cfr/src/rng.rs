//! A small deterministic random number generator (xoshiro256++ seeded with
//! SplitMix64). It is in this crate so results never change with a
//! dependency's version: the same seed gives the same run on every machine.

#[derive(Clone, Debug)]
pub struct Rng {
    s: [u64; 4],
}

#[inline]
fn splitmix64(x: &mut u64) -> u64 {
    *x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        let mut x = seed;
        let s = [
            splitmix64(&mut x),
            splitmix64(&mut x),
            splitmix64(&mut x),
            splitmix64(&mut x),
        ];
        Rng { s }
    }

    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        let s = &mut self.s;
        let result = s[0].wrapping_add(s[3]).rotate_left(23).wrapping_add(s[0]);
        let t = s[1] << 17;
        s[2] ^= s[0];
        s[3] ^= s[1];
        s[1] ^= s[2];
        s[0] ^= s[3];
        s[2] ^= t;
        s[3] = s[3].rotate_left(45);
        result
    }

    /// Uniform in [0, 1).
    #[inline]
    pub fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }

    /// Uniform in 0..n (n > 0).
    #[inline]
    pub fn below(&mut self, n: usize) -> usize {
        ((self.next_u64() as u128 * n as u128) >> 64) as usize
    }

    /// Index drawn from a probability vector summing to about 1.
    #[inline]
    pub fn sample(&mut self, probs: &[f64]) -> usize {
        let mut x = self.next_f64();
        for (i, &p) in probs.iter().enumerate() {
            if x < p {
                return i;
            }
            x -= p;
        }
        // Rounding left x just above the total: take the last action with
        // positive probability.
        probs
            .iter()
            .rposition(|&p| p > 0.0)
            .unwrap_or(probs.len() - 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deterministic_and_roughly_uniform() {
        let mut a = Rng::new(7);
        let mut b = Rng::new(7);
        for _ in 0..100 {
            assert_eq!(a.next_u64(), b.next_u64());
        }
        let mut counts = [0usize; 4];
        for _ in 0..40_000 {
            counts[a.sample(&[0.1, 0.2, 0.3, 0.4])] += 1;
        }
        for (i, &c) in counts.iter().enumerate() {
            let expected = 40_000.0 * 0.1 * (i + 1) as f64;
            assert!((c as f64 - expected).abs() < 400.0, "{counts:?}");
        }
    }
}
