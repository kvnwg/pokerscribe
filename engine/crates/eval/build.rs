//! Builds the lookup tables for the evaluator and writes them to `$OUT_DIR/tables.rs`.
//!
//! Method:
//! 1. List the 7,462 five-card equivalence classes, sort them by strength and number them
//!    1 (7-5-4-3-2 offsuit) to 7,462 (royal flush).
//! 2. Flush table: for every 13-bit rank mask with at least 5 ranks, the best 5-card flush
//!    or straight flush inside it. With 7 cards at most one suit can hold 5, and a hand
//!    with a flush cannot hold a full house or quads, so a flush never needs the rest.
//! 3. Rank tables: for every multiset of 5, 6 or 7 ranks (each rank at most 4 times), the
//!    best non-flush 5-card class inside it. A multiset is keyed by its base-5 count number
//!    `sum(count[r] * 5^r)`, which a hand builds by adding one number per card.
//! 4. Each rank table is stored through a perfect hash of that key (hash and displace):
//!    the top bits of `key * M` pick a bucket, and the bucket's displacement is XORed into
//!    other bits of the product to pick the slot. The builder searches the displacements,
//!    so every key gets its own slot.

use std::collections::HashMap;
use std::env;
use std::fmt::Write as _;
use std::fs;
use std::path::Path;

const HIGH_CARD: u8 = 0;
const PAIR: u8 = 1;
const TWO_PAIR: u8 = 2;
const TRIPS: u8 = 3;
const STRAIGHT: u8 = 4;
const FLUSH: u8 = 5;
const FULL_HOUSE: u8 = 6;
const QUADS: u8 = 7;
const STRAIGHT_FLUSH: u8 = 8;

/// Strength of a 5-card hand as (category, tiebreak ranks), compared lexicographically.
type Class = (u8, Vec<u8>);

/// Top rank of a straight in `mask`, if any. The wheel (A-2-3-4-5) counts as 5-high.
fn straight_top(mask: u16) -> Option<u8> {
    for top in (4..13u8).rev() {
        let need = 0x1fu16 << (top - 4);
        if mask & need == need {
            return Some(top);
        }
    }
    let wheel = (1u16 << 12) | 0xf;
    (mask & wheel == wheel).then_some(3)
}

/// Class of 5 ranks given as counts per rank; `flush` says all 5 share a suit.
fn classify(counts: &[u8; 13], flush: bool) -> Class {
    let mask = (0..13)
        .filter(|&r| counts[r] > 0)
        .fold(0u16, |m, r| m | 1 << r);
    let distinct = mask.count_ones();
    if distinct == 5 {
        if let Some(top) = straight_top(mask) {
            return (if flush { STRAIGHT_FLUSH } else { STRAIGHT }, vec![top]);
        }
        let ranks: Vec<u8> = (0..13u8)
            .rev()
            .filter(|&r| counts[r as usize] > 0)
            .collect();
        return (if flush { FLUSH } else { HIGH_CARD }, ranks);
    }
    assert!(!flush);
    // Group ranks by (count, rank), both descending.
    let mut groups: Vec<(u8, u8)> = (0..13u8)
        .filter(|&r| counts[r as usize] > 0)
        .map(|r| (counts[r as usize], r))
        .collect();
    groups.sort_by(|a, b| b.cmp(a));
    let shape: Vec<u8> = groups.iter().map(|g| g.0).collect();
    let category = match shape.as_slice() {
        [4, 1] => QUADS,
        [3, 2] => FULL_HOUSE,
        [3, 1, 1] => TRIPS,
        [2, 2, 1] => TWO_PAIR,
        [2, 1, 1, 1] => PAIR,
        other => panic!("impossible shape {other:?}"),
    };
    (category, groups.iter().map(|g| g.1).collect())
}

/// Calls `f` for every count vector over 13 ranks with each count <= 4 and total `n`.
fn for_each_multiset(n: u8, f: &mut impl FnMut(&[u8; 13])) {
    fn rec(rank: usize, left: u8, counts: &mut [u8; 13], f: &mut impl FnMut(&[u8; 13])) {
        if rank == 13 {
            if left == 0 {
                f(counts);
            }
            return;
        }
        for c in 0..=left.min(4) {
            counts[rank] = c;
            rec(rank + 1, left - c, counts, f);
        }
        counts[rank] = 0;
    }
    rec(0, n, &mut [0; 13], f);
}

fn quinary(counts: &[u8; 13]) -> u32 {
    counts.iter().rev().fold(0u32, |k, &c| k * 5 + c as u32)
}

struct Chd {
    mult: u64,
    bucket_bits: u32,
    slot_bits: u32,
    disp: Vec<u16>,
    values: Vec<u16>,
}

/// Slot-hash bits are taken from bit 24 of the product: they depend on every key bit,
/// and they never overlap the bucket bits at the top.
const SLOT_SHIFT: u32 = 24;

/// Hash-and-displace perfect hash over `entries` (key, value).
fn build_chd(entries: &[(u32, u16)], bucket_bits: u32, slot_bits: u32) -> Chd {
    assert!(slot_bits <= 16 && SLOT_SHIFT + slot_bits <= 64 - bucket_bits);
    let size = 1usize << slot_bits;
    assert!(entries.len() <= size);
    // Deterministic sequence of odd multipliers; the first one usually works.
    let mut seed = 0x9E37_79B9_7F4A_7C15u64;
    'attempt: for _ in 0..64 {
        seed = seed
            .wrapping_mul(0x5851_F42D_4C95_7F2D)
            .wrapping_add(0x1405_7B7E_F767_814F);
        let mult = seed | 1;
        let nb = 1usize << bucket_bits;
        let mut buckets: Vec<Vec<(u32, u16)>> = vec![Vec::new(); nb];
        for &(k, v) in entries {
            let x = (k as u64).wrapping_mul(mult);
            buckets[(x >> (64 - bucket_bits)) as usize].push((k, v));
        }
        let mut order: Vec<usize> = (0..nb).collect();
        order.sort_by_key(|&b| std::cmp::Reverse(buckets[b].len()));
        let mut used = vec![false; size];
        let mut values = vec![0u16; size];
        let mut disp = vec![0u16; nb];
        let slot_mask = (size - 1) as u64;
        for &b in &order {
            let items = &buckets[b];
            if items.is_empty() {
                break;
            }
            let hashes: Vec<usize> = items
                .iter()
                .map(|&(k, _)| (((k as u64).wrapping_mul(mult) >> SLOT_SHIFT) & slot_mask) as usize)
                .collect();
            let mut found = None;
            let mut slots = Vec::with_capacity(items.len());
            'd: for d in 0..size {
                slots.clear();
                for &h in &hashes {
                    let s = h ^ d;
                    if used[s] || slots.contains(&s) {
                        continue 'd;
                    }
                    slots.push(s);
                }
                found = Some(d);
                break;
            }
            let Some(d) = found else { continue 'attempt };
            disp[b] = d as u16;
            for (&s, &(_, v)) in slots.iter().zip(items) {
                used[s] = true;
                values[s] = v;
            }
        }
        return Chd {
            mult,
            bucket_bits,
            slot_bits,
            disp,
            values,
        };
    }
    panic!("no perfect hash found");
}

fn write_array<T: std::fmt::Display>(out: &mut String, name: &str, ty: &str, data: &[T]) {
    writeln!(out, "pub(crate) static {name}: [{ty}; {}] = [", data.len()).unwrap();
    for chunk in data.chunks(24) {
        let line: Vec<String> = chunk.iter().map(|v| v.to_string()).collect();
        writeln!(out, "    {},", line.join(", ")).unwrap();
    }
    writeln!(out, "];").unwrap();
}

fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    // 1. Number the five-card classes.
    let mut classes: Vec<Class> = Vec::new();
    for_each_multiset(5, &mut |c| {
        classes.push(classify(c, false));
        if c.iter().all(|&x| x <= 1) {
            classes.push(classify(c, true));
        }
    });
    classes.sort();
    classes.dedup();
    assert_eq!(classes.len(), 7462);
    let value_of: HashMap<Class, u16> = classes
        .iter()
        .enumerate()
        .map(|(i, c)| (c.clone(), i as u16 + 1))
        .collect();
    let mut category_start = [0u16; 10];
    for (i, c) in classes.iter().enumerate().rev() {
        category_start[c.0 as usize] = i as u16 + 1;
    }
    category_start[9] = 7463;

    // 2. Flush table.
    let mut flush = vec![0u16; 1 << 13];
    for mask in 0u32..(1 << 13) {
        if mask.count_ones() == 5 {
            let mut counts = [0u8; 13];
            for (r, c) in counts.iter_mut().enumerate() {
                *c = ((mask >> r) & 1) as u8;
            }
            flush[mask as usize] = value_of[&classify(&counts, true)];
        }
    }
    for mask in 0u32..(1 << 13) {
        // Masks are visited in increasing order, so every submask is already done.
        if mask.count_ones() > 5 {
            let best = (0..13)
                .filter(|r| mask >> r & 1 == 1)
                .map(|r| flush[(mask & !(1 << r)) as usize])
                .max()
                .unwrap();
            flush[mask as usize] = best;
        }
    }

    // 3. Rank tables for 5, 6 and 7 cards, each from the one below.
    let mut best: HashMap<[u8; 13], u16> = HashMap::new();
    for_each_multiset(5, &mut |c| {
        best.insert(*c, value_of[&classify(c, false)]);
    });
    let mut tables: Vec<Vec<(u32, u16)>> = Vec::new();
    tables.push(best.iter().map(|(c, &v)| (quinary(c), v)).collect());
    for n in 6..=7 {
        let mut next = HashMap::new();
        for_each_multiset(n, &mut |c| {
            let mut v = 0;
            for r in 0..13 {
                if c[r] > 0 {
                    let mut sub = *c;
                    sub[r] -= 1;
                    v = v.max(best[&sub]);
                }
            }
            next.insert(*c, v);
        });
        tables.push(next.iter().map(|(c, &v)| (quinary(c), v)).collect());
        best = next;
    }
    assert_eq!(
        tables.iter().map(Vec::len).collect::<Vec<_>>(),
        [6175, 18395, 49205]
    );

    // 4. Perfect hashes. Load factors 0.75, 0.56 and 0.75.
    let mut out = String::new();
    writeln!(out, "// Generated by build.rs. Do not edit.\n").unwrap();
    write_array(&mut out, "CATEGORY_START", "u16", &category_start);
    write_array(&mut out, "FLUSH", "u16", &flush);
    for ((n, entries), (bb, sb)) in (5..=7).zip(&tables).zip([(11, 13), (12, 15), (13, 16)]) {
        let mut sorted = entries.clone();
        sorted.sort();
        let chd = build_chd(&sorted, bb, sb);
        writeln!(out, "pub(crate) const MULT{n}: u64 = {:#x};", chd.mult).unwrap();
        writeln!(
            out,
            "pub(crate) const BUCKET_SHIFT{n}: u32 = {};",
            64 - chd.bucket_bits
        )
        .unwrap();
        writeln!(out, "pub(crate) const SLOT_SHIFT{n}: u32 = {SLOT_SHIFT};").unwrap();
        writeln!(
            out,
            "pub(crate) const SLOT_MASK{n}: u32 = {};",
            (1u32 << chd.slot_bits) - 1
        )
        .unwrap();
        write_array(&mut out, &format!("DISP{n}"), "u16", &chd.disp);
        write_array(&mut out, &format!("RANKS{n}"), "u16", &chd.values);
    }
    let path = Path::new(&env::var("OUT_DIR").unwrap()).join("tables.rs");
    fs::write(path, out).unwrap();
}
