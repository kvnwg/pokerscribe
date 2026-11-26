//! Reading a SPOT (`data/SPOT_FORMAT.md`): one river or turn decision to solve.
//!
//! The checks are those of `tools/answer_keys/spots.py::validate_spot`, with two
//! differences. `range_text` isn't expanded and compared with `ranges` (`ranges` is the
//! range). And raise sizes under 0.5 are accepted: the format's min-raise rule covers them
//! (`validate_spot` refuses them only because TexasSolver may treat them differently).

use std::collections::HashSet;
use std::fmt;

use eval::Card;
use serde::de::{MapAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::Value;

use crate::cards::{parse_card, Combo};
use crate::pyfmt::canonical_json;
use crate::sha256::sha256_hex;

pub const OOP: usize = 0;
pub const IP: usize = 1;
pub const PLAYER_NAMES: [&str; 2] = ["oop", "ip"];
pub const SPOT_FORMAT: &str = "pokerscribe-spot";
pub const SPOT_VERSION: u64 = 1;

/// A spot that can't be read or doesn't follow the format.
#[derive(Clone, Debug, PartialEq)]
pub struct SpotError(pub String);

impl fmt::Display for SpotError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for SpotError {}

fn err<T>(message: impl Into<String>) -> Result<T, SpotError> {
    Err(SpotError(message.into()))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Street {
    Turn,
    River,
}

impl Street {
    pub fn name(self) -> &'static str {
        match self {
            Street::Turn => "turn",
            Street::River => "river",
        }
    }
}

/// The sizes one player may use on one street. `bets` are shares of the pot at the start
/// of the street, `raises` shares of the pot after calling; both sorted, each size once.
#[derive(Clone, Debug, PartialEq)]
pub struct BetSizes {
    pub bets: Vec<f64>,
    pub raises: Vec<f64>,
    pub allin: bool,
}

/// One "expected" check of a spot (the trivial spots have them).
#[derive(Clone, Debug, PartialEq, Deserialize)]
pub struct Expected {
    /// A regular expression matched against node keys (Python `re.search`).
    pub nodes: String,
    /// `"oop"`, `"ip"` or `"any"`.
    pub actor: String,
    /// The kind of action counted: `x`, `c`, `f`, `b` (any bet) or `r` (any raise).
    pub action: String,
    pub min: Option<f64>,
    pub max: Option<f64>,
    #[serde(default)]
    pub why: String,
}

/// A spot, checked and ready to solve.
#[derive(Clone, Debug)]
pub struct Spot {
    pub id: String,
    pub street: Street,
    /// 5 cards for a river spot, 4 for a turn spot.
    pub board: Vec<Card>,
    /// Chips in the middle when the spot starts.
    pub pot: f64,
    /// Chips behind for (oop, ip) when the spot starts.
    pub stacks: [f64; 2],
    /// Raises allowed after the first bet, on each street.
    pub max_raises: u32,
    /// Sizes for (oop, ip) on the street the spot starts on.
    pub sizes: [BetSizes; 2],
    /// Turn spots only: the river's sizes.
    pub river_sizes: Option<[BetSizes; 2]>,
    /// Each player's range as (combo, weight), in the order of the file.
    pub ranges: [Vec<(Combo, f64)>; 2],
    pub expected: Vec<Expected>,
    /// sha256 of the spot file's canonical JSON, as `spots.spot_hash`.
    pub sha256: String,
}

impl Spot {
    /// Only the smaller stack matters: nobody can win more than it.
    pub fn effective_stack(&self) -> f64 {
        self.stacks[0].min(self.stacks[1])
    }

    /// The sizes `player` may use on `street`.
    pub fn sizes_on(&self, street: Street, player: usize) -> &BetSizes {
        match (&self.river_sizes, self.street, street) {
            (Some(river), Street::Turn, Street::River) => &river[player],
            _ => &self.sizes[player],
        }
    }

    pub fn load(path: &std::path::Path) -> Result<Spot, SpotError> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| SpotError(format!("can't read {}: {e}", path.display())))?;
        Spot::from_json(&text)
    }

    pub fn from_json(text: &str) -> Result<Spot, SpotError> {
        let value: Value = serde_json::from_str(text)
            .map_err(|e| SpotError(format!("the spot isn't valid JSON: {e}")))?;
        let Some(obj) = value.as_object() else {
            return err("a spot is a JSON object");
        };
        if obj.get("format").and_then(Value::as_str) != Some(SPOT_FORMAT)
            || obj.get("version").and_then(Value::as_u64) != Some(SPOT_VERSION)
        {
            return err(format!("not a {SPOT_FORMAT} version {SPOT_VERSION} spot"));
        }
        for key in [
            "id",
            "street",
            "board",
            "pot",
            "stacks",
            "ranges",
            "sizes",
            "max_raises",
        ] {
            if !obj.contains_key(key) {
                return err(format!("missing {key:?}"));
            }
        }
        // Read a second time into typed fields: the ranges must keep the file's order,
        // which a `Value` doesn't promise.
        let raw: RawSpot =
            serde_json::from_str(text).map_err(|e| SpotError(format!("bad spot: {e}")))?;

        let street = match raw.street.as_str() {
            "turn" => Street::Turn,
            "river" => Street::River,
            other => {
                return err(format!(
                    "street must be \"turn\" or \"river\", not {other:?}"
                ))
            }
        };
        let mut board = Vec::new();
        for text in &raw.board {
            let card = parse_card(text).map_err(|e| SpotError(format!("board: {e}")))?;
            if board.contains(&card) {
                return err(format!("the board has {card} twice"));
            }
            board.push(card);
        }
        let need = if street == Street::Turn { 4 } else { 5 };
        if board.len() != need {
            return err(format!(
                "a {} spot needs {need} different board cards, got {}",
                street.name(),
                board.len()
            ));
        }
        if !(raw.pot.is_finite() && raw.pot > 0.0) {
            return err("pot must be more than 0");
        }
        if raw.stacks.len() != 2 || raw.stacks.iter().any(|s| !(s.is_finite() && *s > 0.0)) {
            return err("stacks are two amounts over 0: [oop, ip]");
        }
        let max_raises = match obj["max_raises"].as_u64() {
            Some(n) if n <= u32::MAX as u64 => n as u32,
            _ => return err("max_raises is a whole number, 0 or more"),
        };

        let mut ranges: [Vec<(Combo, f64)>; 2] = [Vec::new(), Vec::new()];
        for (p, name) in PLAYER_NAMES.iter().enumerate() {
            let listed = match p {
                OOP => &raw.ranges.oop.0,
                _ => &raw.ranges.ip.0,
            };
            let mut seen = HashSet::new();
            for (key, weight) in listed {
                let combo =
                    Combo::parse(key).map_err(|e| SpotError(format!("{name} range: {e}")))?;
                if combo.text() != *key {
                    return err(format!(
                        "{name} range: {key:?} isn't written canonically ({:?})",
                        combo.text()
                    ));
                }
                if board.contains(&combo.hi) || board.contains(&combo.lo) {
                    return err(format!("{name} range: {key} uses a board card"));
                }
                if !(weight.is_finite() && *weight > 0.0 && *weight <= 1.0) {
                    return err(format!(
                        "{name} range: {key}: weight must be over 0 and at most 1"
                    ));
                }
                if !seen.insert(combo) {
                    return err(format!("{name} range: {key} is listed twice"));
                }
                ranges[p].push((combo, *weight));
            }
            if ranges[p].is_empty() {
                return err(format!("the {name} range is empty"));
            }
        }

        let sizes = [
            bet_sizes(&raw.sizes.oop, "sizes.oop")?,
            bet_sizes(&raw.sizes.ip, "sizes.ip")?,
        ];
        let river_sizes = match (&raw.river_sizes, street) {
            (Some(r), Street::Turn) => Some([
                bet_sizes(&r.oop, "river_sizes.oop")?,
                bet_sizes(&r.ip, "river_sizes.ip")?,
            ]),
            (None, Street::Turn) => return err("a turn spot needs river_sizes"),
            (_, Street::River) => None,
        };

        for check in &raw.expected {
            if !["oop", "ip", "any"].contains(&check.actor.as_str())
                || !["x", "c", "f", "b", "r"].contains(&check.action.as_str())
            {
                return err(format!(
                    "bad expected check: actor {:?}, action {:?}",
                    check.actor, check.action
                ));
            }
            if check.min.is_none() && check.max.is_none() {
                return err("an expected check needs min or max");
            }
        }

        Ok(Spot {
            id: raw.id,
            street,
            board,
            pot: raw.pot,
            stacks: [raw.stacks[0], raw.stacks[1]],
            max_raises,
            sizes,
            river_sizes,
            ranges,
            expected: raw.expected,
            sha256: sha256_hex(canonical_json(&value).as_bytes()),
        })
    }
}

fn bet_sizes(raw: &RawSizes, what: &str) -> Result<BetSizes, SpotError> {
    let clean = |values: &[f64], name: &str| -> Result<Vec<f64>, SpotError> {
        if values.iter().any(|x| !(x.is_finite() && *x > 0.0)) {
            return err(format!(
                "{what}.{name}: sizes must be positive shares of the pot"
            ));
        }
        let mut out = values.to_vec();
        out.sort_by(|a, b| a.partial_cmp(b).unwrap());
        out.dedup();
        Ok(out)
    };
    Ok(BetSizes {
        bets: clean(&raw.bets, "bets")?,
        raises: clean(&raw.raises, "raises")?,
        allin: raw.allin,
    })
}

// ------------------------------------------------------------------ raw JSON

#[derive(Deserialize)]
struct RawSpot {
    id: String,
    street: String,
    board: Vec<String>,
    pot: f64,
    stacks: Vec<f64>,
    sizes: RawPlayers<RawSizes>,
    river_sizes: Option<RawPlayers<RawSizes>>,
    ranges: RawPlayers<Ordered<f64>>,
    #[serde(default)]
    expected: Vec<Expected>,
}

#[derive(Deserialize)]
struct RawPlayers<T> {
    oop: T,
    ip: T,
}

#[derive(Deserialize)]
struct RawSizes {
    #[serde(default)]
    bets: Vec<f64>,
    #[serde(default)]
    raises: Vec<f64>,
    #[serde(default)]
    allin: bool,
}

/// A JSON object read as (key, value) pairs in the order of the file.
#[derive(Clone, Debug, PartialEq)]
pub struct Ordered<T>(pub Vec<(String, T)>);

impl<'de, T: Deserialize<'de>> Deserialize<'de> for Ordered<T> {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V<T>(std::marker::PhantomData<T>);
        impl<'de, T: Deserialize<'de>> Visitor<'de> for V<T> {
            type Value = Ordered<T>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a JSON object")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Ordered<T>, A::Error> {
                let mut out = Vec::with_capacity(map.size_hint().unwrap_or(0));
                while let Some(entry) = map.next_entry::<String, T>()? {
                    out.push(entry);
                }
                Ok(Ordered(out))
            }
        }
        d.deserialize_map(V(std::marker::PhantomData))
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    pub(crate) const RIVER: &str = r#"{
      "format": "pokerscribe-spot", "version": 1, "id": "demo", "street": "river",
      "board": ["Ks", "7d", "2c", "4h", "9s"], "pot": 100, "stacks": [300, 250], "max_raises": 3,
      "sizes": {"oop": {"bets": [1.0, 0.5, 0.5], "raises": [0.5], "allin": true},
                "ip": {"bets": [0.33], "raises": []}},
      "ranges": {"oop": {"TsTh": 1.0, "AhKd": 0.5, "9h9d": 1.0}, "ip": {"AsKh": 1.0, "QsQh": 0.25}}
    }"#;

    fn with(change: impl Fn(&mut Value)) -> Result<Spot, SpotError> {
        let mut v: Value = serde_json::from_str(RIVER).unwrap();
        change(&mut v);
        Spot::from_json(&v.to_string())
    }

    #[test]
    fn a_spot_is_read() {
        let s = Spot::from_json(RIVER).unwrap();
        assert_eq!(s.id, "demo");
        assert_eq!(s.street, Street::River);
        assert_eq!(s.board.len(), 5);
        assert_eq!(s.effective_stack(), 250.0);
        assert_eq!(s.sizes[OOP].bets, vec![0.5, 1.0]); // sorted, each size once
        assert!(s.sizes[OOP].allin && !s.sizes[IP].allin);
        let names: Vec<String> = s.ranges[OOP].iter().map(|(c, _)| c.text()).collect();
        assert_eq!(names, ["TsTh", "AhKd", "9h9d"]); // the file's order
        assert_eq!(s.ranges[OOP][1].1, 0.5);
        assert_eq!(s.sha256.len(), 64);
    }

    #[test]
    fn bad_spots_are_refused_with_a_reason() {
        type Change = Box<dyn Fn(&mut Value)>;
        let cases: Vec<(Change, &str)> = vec![
            (
                Box::new(|v| v["format"] = "x".into()),
                "not a pokerscribe-spot",
            ),
            (
                Box::new(|v| v["version"] = 2.into()),
                "not a pokerscribe-spot",
            ),
            (
                Box::new(|v| {
                    v.as_object_mut().unwrap().remove("pot");
                }),
                "missing \"pot\"",
            ),
            (Box::new(|v| v["street"] = "flop".into()), "street must be"),
            (
                Box::new(|v| v["board"] = serde_json::json!(["Ks", "7d", "2c", "4h"])),
                "needs 5",
            ),
            (Box::new(|v| v["board"][4] = "Ks".into()), "twice"),
            (Box::new(|v| v["board"][4] = "1s".into()), "not a card"),
            (Box::new(|v| v["pot"] = 0.into()), "pot must be"),
            (
                Box::new(|v| v["stacks"] = serde_json::json!([100])),
                "stacks",
            ),
            (
                Box::new(|v| v["stacks"] = serde_json::json!([100, 0])),
                "stacks",
            ),
            (
                Box::new(|v| v["max_raises"] = serde_json::json!(-1)),
                "max_raises",
            ),
            (
                Box::new(|v| v["max_raises"] = serde_json::json!(1.5)),
                "max_raises",
            ),
            (
                Box::new(|v| v["ranges"]["ip"] = serde_json::json!({})),
                "ip range is empty",
            ),
            (
                Box::new(|v| v["ranges"]["ip"]["KhAs"] = 1.0.into()),
                "canonically",
            ),
            (
                Box::new(|v| v["ranges"]["ip"]["KsQs"] = 1.0.into()),
                "board card",
            ),
            (
                Box::new(|v| v["ranges"]["ip"]["AsKh"] = 1.5.into()),
                "weight",
            ),
            (Box::new(|v| v["ranges"]["ip"]["AsKh"] = 0.into()), "weight"),
            (
                Box::new(|v| v["ranges"]["ip"]["AsAs"] = 1.into()),
                "same card twice",
            ),
            (
                Box::new(|v| v["sizes"]["ip"]["bets"] = serde_json::json!([-0.5])),
                "positive",
            ),
            (Box::new(|v| v["street"] = "turn".into()), "needs 4"),
            (
                Box::new(|v| {
                    v["expected"] =
                        serde_json::json!([{"nodes": "^x$", "actor": "ip", "action": "x"}])
                }),
                "min or max",
            ),
            (
                Box::new(|v| {
                    v["expected"] = serde_json::json!([{"nodes": "^x$", "actor": "bb", "action": "x", "min": 1}])
                }),
                "bad expected check",
            ),
        ];
        for (change, want) in cases {
            let e = with(&*change).expect_err(want);
            assert!(e.0.contains(want), "{:?} should mention {want:?}", e.0);
        }
        assert!(Spot::from_json("{not json")
            .unwrap_err()
            .0
            .contains("valid JSON"));
        assert!(Spot::from_json("[]").unwrap_err().0.contains("JSON object"));
    }

    #[test]
    fn a_turn_spot_needs_river_sizes() {
        let turn = |v: &mut Value| {
            v["street"] = "turn".into();
            v["board"] = serde_json::json!(["Ks", "7d", "2c", "4h"]);
        };
        assert!(with(turn).unwrap_err().0.contains("river_sizes"));
        let s = with(|v| {
            turn(v);
            v["river_sizes"] = v["sizes"].clone();
        })
        .unwrap();
        assert_eq!(s.street, Street::Turn);
        assert_eq!(s.sizes_on(Street::River, IP).bets, vec![0.33]);
    }
}
