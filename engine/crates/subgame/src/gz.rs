//! Reading gzip (RFC 1952, DEFLATE RFC 1951), for the turn answer keys, which are saved
//! as `.jsonl.gz`. Decompression only, with the CRC and length checked.

use std::fmt;

#[derive(Clone, Debug, PartialEq)]
pub struct GzError(pub String);

impl fmt::Display for GzError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "gzip: {}", self.0)
    }
}

impl std::error::Error for GzError {}

fn bad<T>(message: &str) -> Result<T, GzError> {
    Err(GzError(message.to_string()))
}

struct Bits<'a> {
    data: &'a [u8],
    pos: usize,
    buffer: u64,
    count: u32,
}

impl<'a> Bits<'a> {
    fn refill(&mut self) {
        while self.count <= 56 && self.pos < self.data.len() {
            self.buffer |= (self.data[self.pos] as u64) << self.count;
            self.pos += 1;
            self.count += 8;
        }
    }

    fn take(&mut self, n: u32) -> Result<u32, GzError> {
        if n == 0 {
            return Ok(0);
        }
        if self.count < n {
            self.refill();
            if self.count < n {
                return bad("the data ends early");
            }
        }
        let v = (self.buffer & ((1u64 << n) - 1)) as u32;
        self.buffer >>= n;
        self.count -= n;
        Ok(v)
    }

    /// Drops the bits left in the current byte and gives back the byte position.
    fn align(&mut self) -> usize {
        let drop = self.count % 8;
        self.buffer >>= drop;
        self.count -= drop;
        self.pos - (self.count / 8) as usize
    }
}

/// A canonical Huffman code: how many codes there are of each length, and the symbols in
/// code order.
struct Huffman {
    counts: [u16; 16],
    symbols: Vec<u16>,
}

impl Huffman {
    fn new(lengths: &[u8]) -> Result<Huffman, GzError> {
        let mut counts = [0u16; 16];
        for &l in lengths {
            counts[l as usize] += 1;
        }
        counts[0] = 0;
        let mut left = 1i32;
        for count in &counts[1..] {
            left = (left << 1) - *count as i32;
            if left < 0 {
                return bad("a code has too many symbols");
            }
        }
        let mut offsets = [0u16; 16];
        for l in 1..15 {
            offsets[l + 1] = offsets[l] + counts[l];
        }
        let mut symbols = vec![0u16; lengths.len()];
        for (symbol, &l) in lengths.iter().enumerate() {
            if l != 0 {
                symbols[offsets[l as usize] as usize] = symbol as u16;
                offsets[l as usize] += 1;
            }
        }
        Ok(Huffman { counts, symbols })
    }

    fn decode(&self, bits: &mut Bits) -> Result<u16, GzError> {
        let (mut code, mut first, mut index) = (0i32, 0i32, 0i32);
        for len in 1..16 {
            code |= bits.take(1)? as i32;
            let count = self.counts[len] as i32;
            if code - count < first {
                return Ok(self.symbols[(index + (code - first)) as usize]);
            }
            index += count;
            first = (first + count) << 1;
            code <<= 1;
        }
        bad("a code isn't in the table")
    }
}

const LENGTH_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131,
    163, 195, 227, 258,
];
const LENGTH_EXTRA: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DIST_BASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
    2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
const DIST_EXTRA: [u8; 30] = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13,
    13,
];
const CODE_ORDER: [usize; 19] = [
    16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15,
];

fn block(bits: &mut Bits, lit: &Huffman, dist: &Huffman, out: &mut Vec<u8>) -> Result<(), GzError> {
    loop {
        let symbol = lit.decode(bits)? as usize;
        match symbol {
            0..=255 => out.push(symbol as u8),
            256 => return Ok(()),
            257..=285 => {
                let i = symbol - 257;
                let len = LENGTH_BASE[i] as usize + bits.take(LENGTH_EXTRA[i] as u32)? as usize;
                let d = dist.decode(bits)? as usize;
                if d >= 30 {
                    return bad("a distance code is out of range");
                }
                let back = DIST_BASE[d] as usize + bits.take(DIST_EXTRA[d] as u32)? as usize;
                if back > out.len() {
                    return bad("a copy reaches before the start");
                }
                let from = out.len() - back;
                for k in 0..len {
                    out.push(out[from + k]);
                }
            }
            _ => return bad("a length code is out of range"),
        }
    }
}

/// Inflates a raw DEFLATE stream. Returns the output and how many input bytes it used.
fn inflate(data: &[u8]) -> Result<(Vec<u8>, usize), GzError> {
    let mut bits = Bits {
        data,
        pos: 0,
        buffer: 0,
        count: 0,
    };
    let mut out = Vec::with_capacity(data.len() * 8);
    loop {
        let last = bits.take(1)? == 1;
        match bits.take(2)? {
            0 => {
                let at = bits.align();
                bits.count = 0;
                bits.buffer = 0;
                if at + 4 > data.len() {
                    return bad("the data ends early");
                }
                let len = u16::from_le_bytes([data[at], data[at + 1]]) as usize;
                let not = u16::from_le_bytes([data[at + 2], data[at + 3]]) as usize;
                if len != (!not & 0xffff) || at + 4 + len > data.len() {
                    return bad("a stored block is damaged");
                }
                out.extend_from_slice(&data[at + 4..at + 4 + len]);
                bits.pos = at + 4 + len;
            }
            1 => {
                let mut lengths = [8u8; 288];
                lengths[144..256].fill(9);
                lengths[256..280].fill(7);
                block(
                    &mut bits,
                    &Huffman::new(&lengths)?,
                    &Huffman::new(&[5u8; 30])?,
                    &mut out,
                )?;
            }
            2 => {
                let n_lit = bits.take(5)? as usize + 257;
                let n_dist = bits.take(5)? as usize + 1;
                let n_code = bits.take(4)? as usize + 4;
                if n_lit > 286 || n_dist > 30 {
                    return bad("too many codes");
                }
                let mut code_lengths = [0u8; 19];
                for &slot in &CODE_ORDER[..n_code] {
                    code_lengths[slot] = bits.take(3)? as u8;
                }
                let code = Huffman::new(&code_lengths)?;
                let mut lengths = vec![0u8; n_lit + n_dist];
                let mut i = 0;
                while i < lengths.len() {
                    let symbol = code.decode(&mut bits)?;
                    let (value, repeat) = match symbol {
                        0..=15 => (symbol as u8, 1),
                        16 if i == 0 => return bad("a repeat has nothing to repeat"),
                        16 => (lengths[i - 1], 3 + bits.take(2)? as usize),
                        17 => (0, 3 + bits.take(3)? as usize),
                        _ => (0, 11 + bits.take(7)? as usize),
                    };
                    if i + repeat > lengths.len() {
                        return bad("too many code lengths");
                    }
                    lengths[i..i + repeat].fill(value);
                    i += repeat;
                }
                let lit = Huffman::new(&lengths[..n_lit])?;
                let dist = Huffman::new(&lengths[n_lit..])?;
                block(&mut bits, &lit, &dist, &mut out)?;
            }
            _ => return bad("an unknown block type"),
        }
        if last {
            return Ok((out, bits.align()));
        }
    }
}

fn crc32(data: &[u8]) -> u32 {
    let mut table = [0u32; 256];
    for (i, entry) in table.iter_mut().enumerate() {
        let mut c = i as u32;
        for _ in 0..8 {
            c = if c & 1 != 0 {
                0xedb88320 ^ (c >> 1)
            } else {
                c >> 1
            };
        }
        *entry = c;
    }
    !data.iter().fold(!0u32, |c, &b| {
        table[((c ^ b as u32) & 0xff) as usize] ^ (c >> 8)
    })
}

/// Decompresses one gzip file.
pub fn gunzip(data: &[u8]) -> Result<Vec<u8>, GzError> {
    if data.len() < 18 || data[0] != 0x1f || data[1] != 0x8b || data[2] != 8 {
        return bad("not a gzip file");
    }
    let flags = data[3];
    let mut at = 10;
    if flags & 4 != 0 {
        if at + 2 > data.len() {
            return bad("the header ends early");
        }
        at += 2 + u16::from_le_bytes([data[at], data[at + 1]]) as usize;
    }
    for bit in [8, 16] {
        // file name, comment: zero-terminated
        if flags & bit != 0 {
            while at < data.len() && data[at] != 0 {
                at += 1;
            }
            at += 1;
        }
    }
    if flags & 2 != 0 {
        at += 2;
    }
    if at >= data.len() {
        return bad("the header ends early");
    }
    let (out, used) = inflate(&data[at..])?;
    let end = at + used;
    if end + 8 > data.len() {
        return bad("the checksum is missing");
    }
    let crc = u32::from_le_bytes([data[end], data[end + 1], data[end + 2], data[end + 3]]);
    let size = u32::from_le_bytes([data[end + 4], data[end + 5], data[end + 6], data[end + 7]]);
    if crc != crc32(&out) || size != out.len() as u32 {
        return bad("the checksum doesn't match");
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_small_file_made_by_python_gzip_is_read() {
        // python3 -c "import gzip; print(gzip.compress(b'abcabcabcabc hello hello hello\n', mtime=0).hex())"
        let data: [u8; 34] = [
            0x1f, 0x8b, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0xff, 0x4b, 0x4c, 0x4a, 0x4e,
            0x84, 0x21, 0x85, 0x8c, 0xd4, 0x9c, 0x9c, 0x7c, 0x64, 0x92, 0x0b, 0x00, 0x9e, 0xec,
            0x5b, 0xd9, 0x1f, 0x00, 0x00, 0x00,
        ];
        assert_eq!(gunzip(&data).unwrap(), b"abcabcabcabc hello hello hello\n");
        assert!(gunzip(&data[..20]).is_err());
        let mut damaged = data;
        damaged[27] ^= 1;
        assert!(gunzip(&damaged).unwrap_err().0.contains("checksum"));
        assert!(gunzip(b"not gzip at all, just text").is_err());
    }

    #[test]
    fn a_stored_block_is_read() {
        let body = b"stored block";
        let mut stored = vec![0x1f, 0x8b, 8, 0, 0, 0, 0, 0, 0, 0xff, 0x01];
        stored.extend_from_slice(&(body.len() as u16).to_le_bytes());
        stored.extend_from_slice(&(!(body.len() as u16)).to_le_bytes());
        stored.extend_from_slice(body);
        stored.extend_from_slice(&crc32(body).to_le_bytes());
        stored.extend_from_slice(&(body.len() as u32).to_le_bytes());
        assert_eq!(gunzip(&stored).unwrap(), body);
    }

    #[test]
    fn crc32_of_a_known_string() {
        assert_eq!(crc32(b"123456789"), 0xcbf43926);
    }
}
