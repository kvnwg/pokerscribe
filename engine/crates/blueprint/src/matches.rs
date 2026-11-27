//! LBR matches that keep every deal's result, for paired comparisons.
//!
//! `lbr::play_match` returns totals. The gate compares strategies (and checkpoints of one
//! strategy) on the same deals, and the luck of the cards then mostly cancels in the
//! difference: its standard error is far smaller than the two results' own. This module
//! plays the same duplicate match with `lbr::play_hand` and keeps what LBR won on each
//! deal from each seat, so the difference can be measured deal by deal.

use std::fs;
use std::io;
use std::path::Path;

use lbr::{play_hand, LbrConfig, MatchConfig, MatchResult, Strategy};
use rayon::prelude::*;

/// SplitMix64's output step.
fn mix(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// The seed of deal `index` of a match with seed `seed`.
pub fn deal_seed(seed: u64, index: u64) -> u64 {
    mix(mix(seed ^ 0x424C_5545).wrapping_add(index.wrapping_mul(0x9E37_79B9_7F4A_7C15)))
}

/// What LBR won on every deal: `[on the button, in the big blind]`, in chips.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Deals {
    pub seed: u64,
    pub big_blind: u32,
    pub won: Vec<[i32; 2]>,
}

const MAGIC: &[u8; 8] = b"PSDEALS\n";

impl Deals {
    /// The match's result, as `lbr::play_match` reports it.
    pub fn result(&self) -> MatchResult {
        let n = self.won.len() as f64;
        let scale = 100.0 / self.big_blind as f64;
        let button = self.won.iter().map(|w| w[0] as f64).sum::<f64>() / n;
        let big_blind = self.won.iter().map(|w| w[1] as f64).sum::<f64>() / n;
        let mean = (button + big_blind) / 2.0;
        let squares: f64 = self
            .won
            .iter()
            .map(|w| ((w[0] + w[1]) as f64 / 2.0 - mean).powi(2))
            .sum();
        MatchResult {
            hands: 2 * self.won.len() as u64,
            bb_per_100: mean * scale,
            std_err: (squares / (n - 1.0) / n).sqrt() * scale,
            button_bb_per_100: button * scale,
            big_blind_bb_per_100: big_blind * scale,
        }
    }

    /// `self` minus `other` on the same deals, in bb/100, with the standard error of the
    /// difference counted deal by deal.
    pub fn minus(&self, other: &Deals) -> Result<(f64, f64), String> {
        if self.seed != other.seed || self.won.len() != other.won.len() {
            return Err("the two matches were not played on the same deals".into());
        }
        if self.big_blind != other.big_blind {
            return Err("the two matches have different blinds".into());
        }
        let n = self.won.len() as f64;
        let d: Vec<f64> = self
            .won
            .iter()
            .zip(&other.won)
            .map(|(a, b)| ((a[0] + a[1]) - (b[0] + b[1])) as f64 / 2.0)
            .collect();
        let mean = d.iter().sum::<f64>() / n;
        let var = d.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n - 1.0);
        let scale = 100.0 / self.big_blind as f64;
        Ok((mean * scale, (var / n).sqrt() * scale))
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        let mut out = Vec::with_capacity(28 + 8 * self.won.len());
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&self.seed.to_le_bytes());
        out.extend_from_slice(&self.big_blind.to_le_bytes());
        out.extend_from_slice(&(self.won.len() as u64).to_le_bytes());
        for w in &self.won {
            out.extend_from_slice(&w[0].to_le_bytes());
            out.extend_from_slice(&w[1].to_le_bytes());
        }
        fs::write(path, out)
    }

    pub fn load(path: &Path) -> io::Result<Deals> {
        let b = fs::read(path)?;
        let bad = |m: &str| io::Error::new(io::ErrorKind::InvalidData, m.to_string());
        if b.len() < 28 || &b[..8] != MAGIC {
            return Err(bad("not a deals file"));
        }
        let seed = u64::from_le_bytes(b[8..16].try_into().unwrap());
        let big_blind = u32::from_le_bytes(b[16..20].try_into().unwrap());
        let n = u64::from_le_bytes(b[20..28].try_into().unwrap()) as usize;
        if b.len() != 28 + 8 * n {
            return Err(bad("a deals file of the wrong length"));
        }
        let won = b[28..]
            .chunks_exact(8)
            .map(|c| {
                [
                    i32::from_le_bytes(c[..4].try_into().unwrap()),
                    i32::from_le_bytes(c[4..].try_into().unwrap()),
                ]
            })
            .collect();
        Ok(Deals {
            seed,
            big_blind,
            won,
        })
    }
}

/// LBR against `opponent`: each deal played from both seats, on all cores. The same
/// `table` (seed included) gives the same deals whatever the strategy, so two matches can
/// be compared deal by deal ([`Deals::minus`]).
pub fn lbr_match(opponent: &dyn Strategy, lbr_config: &LbrConfig, table: &MatchConfig) -> Deals {
    let deals = table.hands.div_ceil(2);
    let won = (0..deals)
        .into_par_iter()
        .map(|i| {
            let seed = deal_seed(table.seed, i);
            let a = play_hand(opponent, lbr_config, table, seed, true);
            let b = play_hand(opponent, lbr_config, table, seed, false);
            [a as i32, b as i32]
        })
        .collect();
    Deals {
        seed: table.seed,
        big_blind: table.big_blind,
        won,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lbr::{AlwaysCall, AlwaysFold};

    #[test]
    fn the_same_numbers_as_lbr_and_a_paired_difference() {
        let table = MatchConfig {
            stack: 2_000,
            ..MatchConfig::acpc(400, 5)
        };
        let config = LbrConfig::default();
        let fold = lbr_match(&AlwaysFold, &config, &table);
        assert_eq!(fold.result().bb_per_100, 75.0);
        let call = lbr_match(&AlwaysCall, &config, &table);
        assert_eq!(call.won.len(), 200);
        let r = call.result();
        assert!(r.bb_per_100 > 100.0, "{r}");
        let (d, se) = call.minus(&fold).unwrap();
        assert!((d - (r.bb_per_100 - 75.0)).abs() < 1e-9);
        assert!(se > 0.0);
        assert_eq!(call.minus(&call).unwrap(), (0.0, 0.0));
        let path = std::env::temp_dir().join(format!("deals-{}.bin", std::process::id()));
        call.save(&path).unwrap();
        assert_eq!(Deals::load(&path).unwrap(), call);
        std::fs::remove_file(&path).unwrap();
        let other = lbr_match(&AlwaysCall, &config, &MatchConfig { seed: 6, ..table });
        assert!(call.minus(&other).is_err());
    }
}
