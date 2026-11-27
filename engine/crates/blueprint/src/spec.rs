//! What a blueprint run is: the game (stack depth, bet menu, bucket tables) and how it is
//! trained. Written as JSON next to every checkpoint and in every strategy file's header.

use std::path::PathBuf;

use abstract_game::{GameConfig, Menus, Size};
use cfr::{MccfrConfig, Sampling};
use serde::{Deserialize, Serialize};

/// The menus this crate knows by name: `abstract_game`'s five ready-made ones and `rich`.
pub const MENU_NAMES: [&str; 6] = ["push_fold", "minimal", "small", "standard", "wide", "rich"];

/// A menu by name. `rich` is the default menu after the flop with the wide menu's
/// preflop (8 opens, 5 3-bets, 4 4-bets, 2 5-bets, each with all in): the kind of game
/// the Phase 6 run is planned for.
pub fn menu(name: &str) -> Option<Menus> {
    Some(match name {
        "push_fold" => Menus::push_fold(),
        "minimal" => Menus::minimal(),
        "small" => Menus::small(),
        "standard" => Menus::standard(),
        "wide" => Menus::wide(),
        "rich" => {
            let mut menus = Menus::standard();
            menus.streets[0] = Menus::wide().streets[0].clone();
            menus
        }
        _ => return None,
    })
}

/// A menu as one line of text, for headers and logs.
pub fn describe_menu(menus: &Menus) -> String {
    let street = |levels: &Vec<Vec<Size>>| {
        levels
            .iter()
            .map(|sizes| {
                if sizes.is_empty() {
                    "none".to_string()
                } else {
                    sizes
                        .iter()
                        .map(|s| s.to_string())
                        .collect::<Vec<_>>()
                        .join(", ")
                }
            })
            .collect::<Vec<_>>()
            .join(" | ")
    };
    let names = ["preflop", "flop", "turn", "river"];
    let parts: Vec<String> = menus
        .streets
        .iter()
        .zip(names)
        .map(|(levels, name)| format!("{name}: {}", street(levels)))
        .collect();
    format!("{}; limp {}", parts.join("; "), menus.limp)
}

/// Pluribus-style negative-regret pruning, in big blinds.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct PruneSettings {
    pub warmup: u64,
    pub threshold: f64,
    pub probability: f64,
}

/// How the blueprint is trained: external-sampling MCCFR from the cfr crate.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Training {
    pub seed: u64,
    /// Threads that traverse at once (1 is deterministic).
    pub threads: usize,
    /// Integer regrets with this many units per big blind (100 is one unit a chip at the
    /// default blinds), or `None` for 64-bit floats.
    pub compact_scale: Option<f64>,
    /// Regrets never fall below this many big blinds.
    pub regret_floor: Option<f64>,
    /// Linear weighting: every `interval` iterations up to iteration `until`, regrets and
    /// strategy sums are multiplied by k / (k + 1).
    pub linear: Option<[u64; 2]>,
    pub pruning: Option<PruneSettings>,
}

impl Default for Training {
    /// Four threads, integer regrets one unit a chip with Pluribus's floor (310 million
    /// chips, 3.1 million big blinds), no linear weighting, no pruning.
    fn default() -> Training {
        Training {
            seed: 1,
            threads: 4,
            compact_scale: Some(100.0),
            regret_floor: Some(-3.1e6),
            linear: None,
            pruning: None,
        }
    }
}

impl Training {
    /// The cfr crate's settings for this training.
    pub fn mccfr_config(&self) -> MccfrConfig {
        let mut cfg = MccfrConfig::new(Sampling::External, self.seed).threads(self.threads);
        if let Some(scale) = self.compact_scale {
            cfg = cfg.compact(scale);
        }
        if let Some(floor) = self.regret_floor {
            cfg = cfg.regret_floor(floor);
        }
        if let Some([interval, until]) = self.linear {
            cfg = cfg.linear(interval, until);
        }
        if let Some(p) = self.pruning {
            cfg = cfg.pruning(p.warmup, p.threshold, p.probability);
        }
        cfg
    }
}

/// One blueprint: the game and its training.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Spec {
    /// Each player's stack in big blinds, before the blinds. Blinds are 50 and 100 chips.
    pub stack_bb: u32,
    /// A name from [`MENU_NAMES`].
    pub menu: String,
    /// The directory of bucket tables (`flop.abs`, `turn.abs`, `river.abs`).
    pub abstraction: PathBuf,
    pub training: Training,
}

impl Spec {
    /// The abstract game's settings, or an error naming the unknown menu.
    pub fn game_config(&self) -> Result<GameConfig, String> {
        let menus = menu(&self.menu).ok_or_else(|| {
            format!(
                "unknown menu {:?}: one of {}",
                self.menu,
                MENU_NAMES.join(", ")
            )
        })?;
        Ok(GameConfig::new(self.stack_bb, menus))
    }

    /// Reads a spec from JSON text.
    pub fn from_json(text: &str) -> Result<Spec, String> {
        serde_json::from_str(text).map_err(|e| e.to_string())
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).expect("a spec is always valid JSON")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_named_menu_is_valid() {
        for name in MENU_NAMES {
            let m = menu(name).unwrap();
            m.validate().unwrap();
            assert!(!describe_menu(&m).is_empty());
        }
        assert!(menu("huge").is_none());
        let rich = menu("rich").unwrap();
        assert_eq!(rich.streets[0], Menus::wide().streets[0]);
        assert_eq!(rich.streets[1..], Menus::standard().streets[1..]);
    }

    #[test]
    fn a_spec_survives_json() {
        let spec = Spec {
            stack_bb: 20,
            menu: "small".into(),
            abstraction: "/tmp/k50".into(),
            training: Training {
                linear: Some([1000, 100_000]),
                pruning: Some(PruneSettings {
                    warmup: 10,
                    threshold: -1e4,
                    probability: 0.95,
                }),
                ..Training::default()
            },
        };
        assert_eq!(Spec::from_json(&spec.to_json()).unwrap(), spec);
        assert!(spec.game_config().is_ok());
        let bad = Spec {
            menu: "huge".into(),
            ..spec
        };
        assert!(bad.game_config().unwrap_err().contains("unknown menu"));
        let cfg = Training::default().mccfr_config();
        assert_eq!(cfg.threads, 4);
        assert_eq!(cfg.regret_floor, Some(-3.1e6));
    }
}
