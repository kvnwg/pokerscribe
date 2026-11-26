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

    /// The generator's four words of state, to save in a checkpoint.
    pub fn state(&self) -> [u64; 4] {
        self.s
    }

    /// A generator that continues exactly where the one that gave `state`
    /// stopped. An all-zero state is not a state of this generator: it would
    /// only ever give zeros.
    pub fn from_state(state: [u64; 4]) -> Self {
        assert!(state != [0; 4], "xoshiro256++ has no all-zero state");
        Rng { s: state }
    }

    /// Moves 2^128 draws ahead (xoshiro256's jump). The generator for thread
    /// i is the seed's generator jumped i times, so the threads' streams
    /// can't overlap however long a run is.
    pub fn jump(&mut self) {
        const JUMP: [u64; 4] = [
            0x180E_C6D3_3CFD_0ABA,
            0xD5A6_1266_F0C9_392C,
            0xA958_2618_E03F_C9AA,
            0x39AB_DC45_29B1_661C,
        ];
        let mut s = [0u64; 4];
        for word in JUMP {
            for bit in 0..64 {
                if word & (1 << bit) != 0 {
                    for (acc, x) in s.iter_mut().zip(self.s) {
                        *acc ^= x;
                    }
                }
                self.next_u64();
            }
        }
        self.s = s;
    }

    /// The generator of thread `thread` for a seed: thread 0's is
    /// `Rng::new(seed)`.
    pub fn for_thread(seed: u64, thread: usize) -> Self {
        let mut rng = Rng::new(seed);
        for _ in 0..thread {
            rng.jump();
        }
        rng
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
    fn a_saved_state_continues_the_stream_and_threads_get_their_own() {
        let mut a = Rng::new(9);
        for _ in 0..10 {
            a.next_u64();
        }
        let mut b = Rng::from_state(a.state());
        for _ in 0..100 {
            assert_eq!(a.next_u64(), b.next_u64());
        }
        assert_eq!(Rng::for_thread(9, 0).state(), Rng::new(9).state());
        let states: Vec<[u64; 4]> = (0..4).map(|t| Rng::for_thread(9, t).state()).collect();
        for i in 0..4 {
            for j in 0..i {
                assert_ne!(states[i], states[j]);
            }
        }
        // Jumping is a fixed map of the state, not a draw.
        assert_eq!(Rng::for_thread(9, 3).state(), states[3]);
    }

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
