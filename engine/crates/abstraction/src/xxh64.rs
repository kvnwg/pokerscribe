//! XXH64, the 64-bit xxHash, used as the table files' checksum. It is fast enough (several
//! GB a second) that checking a river table on load costs little.

const P1: u64 = 0x9E37_79B1_85EB_CA87;
const P2: u64 = 0xC2B2_AE3D_27D4_EB4F;
const P3: u64 = 0x1656_67B1_9E37_79F9;
const P4: u64 = 0x85EB_CA77_C2B2_AE63;
const P5: u64 = 0x27D4_EB2F_1656_67C5;

#[inline(always)]
fn round(acc: u64, input: u64) -> u64 {
    acc.wrapping_add(input.wrapping_mul(P2))
        .rotate_left(31)
        .wrapping_mul(P1)
}

#[inline(always)]
fn merge(h: u64, v: u64) -> u64 {
    (h ^ round(0, v)).wrapping_mul(P1).wrapping_add(P4)
}

#[inline(always)]
fn read64(b: &[u8]) -> u64 {
    u64::from_le_bytes(b[..8].try_into().unwrap())
}

/// A running XXH64 over data fed in pieces.
#[derive(Clone)]
pub struct Xxh64 {
    v: [u64; 4],
    buf: [u8; 32],
    buf_len: usize,
    total: u64,
    seed: u64,
}

impl Xxh64 {
    pub fn new(seed: u64) -> Xxh64 {
        Xxh64 {
            v: [
                seed.wrapping_add(P1).wrapping_add(P2),
                seed.wrapping_add(P2),
                seed,
                seed.wrapping_sub(P1),
            ],
            buf: [0; 32],
            buf_len: 0,
            total: 0,
            seed,
        }
    }

    #[inline(always)]
    fn stripe(v: &mut [u64; 4], s: &[u8]) {
        v[0] = round(v[0], read64(&s[0..]));
        v[1] = round(v[1], read64(&s[8..]));
        v[2] = round(v[2], read64(&s[16..]));
        v[3] = round(v[3], read64(&s[24..]));
    }

    pub fn update(&mut self, mut data: &[u8]) {
        self.total += data.len() as u64;
        if self.buf_len > 0 {
            let take = (32 - self.buf_len).min(data.len());
            self.buf[self.buf_len..self.buf_len + take].copy_from_slice(&data[..take]);
            self.buf_len += take;
            data = &data[take..];
            if self.buf_len < 32 {
                return;
            }
            let buf = self.buf;
            Self::stripe(&mut self.v, &buf);
            self.buf_len = 0;
        }
        let mut chunks = data.chunks_exact(32);
        let mut v = self.v;
        for s in &mut chunks {
            Self::stripe(&mut v, s);
        }
        self.v = v;
        let rest = chunks.remainder();
        self.buf[..rest.len()].copy_from_slice(rest);
        self.buf_len = rest.len();
    }

    pub fn finish(&self) -> u64 {
        let mut h = if self.total >= 32 {
            let [a, b, c, d] = self.v;
            let h = a
                .rotate_left(1)
                .wrapping_add(b.rotate_left(7))
                .wrapping_add(c.rotate_left(12))
                .wrapping_add(d.rotate_left(18));
            merge(merge(merge(merge(h, a), b), c), d)
        } else {
            self.seed.wrapping_add(P5)
        };
        h = h.wrapping_add(self.total);
        let mut rest = &self.buf[..self.buf_len];
        while rest.len() >= 8 {
            h = (h ^ round(0, read64(rest)))
                .rotate_left(27)
                .wrapping_mul(P1)
                .wrapping_add(P4);
            rest = &rest[8..];
        }
        if rest.len() >= 4 {
            let x = u32::from_le_bytes(rest[..4].try_into().unwrap()) as u64;
            h = (h ^ x.wrapping_mul(P1))
                .rotate_left(23)
                .wrapping_mul(P2)
                .wrapping_add(P3);
            rest = &rest[4..];
        }
        for &b in rest {
            h = (h ^ (b as u64).wrapping_mul(P5))
                .rotate_left(11)
                .wrapping_mul(P1);
        }
        h ^= h >> 33;
        h = h.wrapping_mul(P2);
        h ^= h >> 29;
        h = h.wrapping_mul(P3);
        h ^ (h >> 32)
    }
}

/// XXH64 of `data` with seed 0.
pub fn xxh64(data: &[u8]) -> u64 {
    let mut h = Xxh64::new(0);
    h.update(data);
    h.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Reference values from the `xxhash` Python package (xxhash.xxh64_hexdigest).
    #[test]
    fn matches_the_reference_implementation() {
        assert_eq!(xxh64(b""), 0xEF46_DB37_51D8_E999);
        assert_eq!(xxh64(b"a"), 0xD24E_C4F1_A98C_6E5B);
        assert_eq!(xxh64(b"abc"), 0x44BC_2CF5_AD77_0999);
        let text = b"The quick brown fox jumps over the lazy dog";
        assert_eq!(xxh64(text), 0x0B24_2D36_1FDA_71BC);
        let long: Vec<u8> = (0..1000u32).map(|i| (i * 7 + 3) as u8).collect();
        assert_eq!(xxh64(&long), LONG_REFERENCE);
        let mut seeded = Xxh64::new(42);
        seeded.update(text);
        assert_eq!(seeded.finish(), SEEDED_REFERENCE);
    }

    const LONG_REFERENCE: u64 = 0x5F23_5FA0_33F1_A3FB;
    const SEEDED_REFERENCE: u64 = 0xAA9F_288A_8BAA_3D3F;

    #[test]
    fn pieces_give_the_same_hash_as_one_call() {
        let data: Vec<u8> = (0..5000u32)
            .map(|i| (i.wrapping_mul(2654435761) >> 13) as u8)
            .collect();
        let whole = xxh64(&data);
        for step in [1usize, 3, 31, 32, 33, 100, 4999] {
            let mut h = Xxh64::new(0);
            for piece in data.chunks(step) {
                h.update(piece);
            }
            assert_eq!(h.finish(), whole, "step {step}");
        }
    }
}
