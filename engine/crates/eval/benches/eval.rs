//! Throughput of the evaluator. Criterion prints elements (hands) per second.
//!
//! cargo bench -p eval

use criterion::{BatchSize, Criterion, Throughput, criterion_group, criterion_main};
use eval::{Card, Hand, eval5, eval6, eval7};
use std::hint::black_box;

const HANDS: usize = 1 << 16;

struct SplitMix64(u64);

impl SplitMix64 {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
}

fn random_hands<const N: usize>(seed: u64) -> Vec<[Card; N]> {
    let mut rng = SplitMix64(seed);
    (0..HANDS)
        .map(|_| {
            let mut deck: Vec<Card> = Card::all().collect();
            for i in 0..N {
                let j = i + (rng.next() % (52 - i) as u64) as usize;
                deck.swap(i, j);
            }
            deck[..N].try_into().unwrap()
        })
        .collect()
}

fn random(c: &mut Criterion) {
    let mut group = c.benchmark_group("random hands");
    group.throughput(Throughput::Elements(HANDS as u64));
    let h7 = random_hands::<7>(7);
    let h6 = random_hands::<6>(6);
    let h5 = random_hands::<5>(5);
    group.bench_function("eval7", |b| {
        b.iter(|| {
            h7.iter()
                .fold(0u32, |acc, h| acc + eval7(black_box(h)).value() as u32)
        })
    });
    group.bench_function("eval6", |b| {
        b.iter(|| {
            h6.iter()
                .fold(0u32, |acc, h| acc + eval6(black_box(h)).value() as u32)
        })
    });
    group.bench_function("eval5", |b| {
        b.iter(|| {
            h5.iter()
                .fold(0u32, |acc, h| acc + eval5(black_box(h)).value() as u32)
        })
    });
    group.finish();
}

/// Every 5-card board for one pair of hole cards (2,118,760 hands), the shape of an
/// equity calculation: the board is built one card at a time and shared.
#[allow(clippy::needless_range_loop)]
fn enumerate(c: &mut Criterion) {
    let mut group = c.benchmark_group("enumerate boards");
    group.throughput(Throughput::Elements(2_118_760));
    group.sample_size(20);
    let hole = Hand::from_cards(&eval::parse_cards("AhKd").unwrap());
    let rest: Vec<Card> = Card::all().filter(|&c| !hole.contains(c)).collect();
    group.bench_function("AhKd, all boards", |b| {
        b.iter_batched(
            || hole,
            |hole| {
                let n = rest.len();
                let mut sum = 0u64;
                for a in 0..n {
                    let ha = hole.add(rest[a]);
                    for b in a + 1..n {
                        let hb = ha.add(rest[b]);
                        for c in b + 1..n {
                            let hc = hb.add(rest[c]);
                            for d in c + 1..n {
                                let hd = hc.add(rest[d]);
                                for e in d + 1..n {
                                    sum += hd.add(rest[e]).eval7().value() as u64;
                                }
                            }
                        }
                    }
                }
                sum
            },
            BatchSize::SmallInput,
        )
    });
    group.finish();
}

criterion_group!(benches, random, enumerate);
criterion_main!(benches);
