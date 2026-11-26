//! Numbers and JSON written the way Python writes them.
//!
//! The spot's hash is the sha256 of `json.dumps(spot, sort_keys=True, separators=(",", ":"))`
//! (`tools/answer_keys/spots.py`), amounts are rounded with Python's `round(x, 2)`
//! (`app/solver/tree.py`), and RESULT probabilities with `round(p, 6)`. To give the same
//! bytes this module repeats those three small pieces of Python.

use serde_json::Value;

/// Python's `round(x, digits)` for a float: the nearest decimal with that many places to
/// the exact binary value, ties to even. Rust's `{:.N}` formatting rounds the same way.
pub fn round_to(x: f64, digits: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.digits$}").parse().unwrap_or(x)
}

/// `round(p, 6)` for a probability, quickly: the same number as [`round_to`]`(p, 6)`, which
/// is only asked when `p` is so close to halfway between two steps that the quick way
/// could round it the other way.
pub fn round6(p: f64) -> f64 {
    let x = p * 1e6;
    if !(0.0..=1e9).contains(&x) || ((x - x.floor()) - 0.5).abs() < 1e-5 {
        return round_to(p, 6);
    }
    x.round() / 1e6
}

/// Writes a number that [`round6`] made as Python's `repr` would: `0.0`, `1.0`, `0.25`,
/// `0.000123`, `5e-06`.
pub fn write_rounded6(p: f64, out: &mut String) {
    let micro = (p * 1e6).round();
    if !(0.0..=1e9).contains(&micro) || micro / 1e6 != p {
        out.push_str(&float_repr(p)); // not a multiple of a millionth after all
        return;
    }
    let micro = micro as u64;
    let (whole, part) = (micro / 1_000_000, micro % 1_000_000);
    if (1..100).contains(&micro) {
        // under 1e-4 Python switches to an exponent
        match (micro / 10, micro % 10) {
            (0, d) => out.push_str(&format!("{d}e-06")),
            (d, 0) => out.push_str(&format!("{d}e-05")),
            (d, e) => out.push_str(&format!("{d}.{e}e-05")),
        }
        return;
    }
    let mut digits = [b'0'; 6];
    let mut rest = part;
    for d in digits.iter_mut().rev() {
        *d = b'0' + (rest % 10) as u8;
        rest /= 10;
    }
    let keep = digits.iter().rposition(|d| *d != b'0').map_or(1, |i| i + 1);
    if whole < 10 {
        out.push((b'0' + whole as u8) as char);
    } else {
        out.push_str(&whole.to_string());
    }
    out.push('.');
    for d in &digits[..keep] {
        out.push(*d as char);
    }
}

/// Python's `repr(float)`: the shortest digits that read back the same, positional from
/// 1e-4 up to 1e16 and with an exponent outside (`100.0`, `0.33`, `1e-05`, `1e+16`).
pub fn float_repr(x: f64) -> String {
    if x.is_nan() {
        return "NaN".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0" } else { "0.0" }.to_string();
    }
    // Rust's `{:e}` gives the shortest round-trip digits: "1.5e-7", "1e2".
    let sci = format!("{:e}", x.abs());
    let (mantissa, exp) = sci.split_once('e').expect("{:e} always has an exponent");
    let exp: i32 = exp.parse().expect("exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let n = digits.len() as i32;
    let mut out = String::new();
    if x < 0.0 {
        out.push('-');
    }
    if (-4..16).contains(&exp) {
        if exp < 0 {
            out.push_str("0.");
            for _ in 0..(-exp - 1) {
                out.push('0');
            }
            out.push_str(&digits);
        } else if n <= exp + 1 {
            out.push_str(&digits);
            for _ in 0..(exp + 1 - n) {
                out.push('0');
            }
            out.push_str(".0");
        } else {
            out.push_str(&digits[..(exp + 1) as usize]);
            out.push('.');
            out.push_str(&digits[(exp + 1) as usize..]);
        }
    } else {
        out.push_str(&digits[..1]);
        if n > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if exp < 0 { '-' } else { '+' });
        out.push_str(&format!("{:02}", exp.abs()));
    }
    out
}

/// A JSON string as Python writes it with `ensure_ascii=True`.
pub fn json_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e && (c as u32) != 0x7f => {
                if (c as u32) < 0x80 {
                    out.push_str(&format!("\\u{:04x}", c as u32));
                } else {
                    let mut units = [0u16; 2];
                    for u in c.encode_utf16(&mut units) {
                        out.push_str(&format!("\\u{:04x}", u));
                    }
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// `json.dumps(value, sort_keys=True, separators=(",", ":"))`.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_canonical(value, &mut out);
    out
}

fn write_canonical(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                out.push_str(&i.to_string());
            } else if let Some(u) = n.as_u64() {
                out.push_str(&u.to_string());
            } else {
                out.push_str(&float_repr(n.as_f64().unwrap_or(f64::NAN)));
            }
        }
        Value::String(s) => json_string(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            // Sorted by key whatever order the map keeps (Python sorts by code point,
            // which is byte order in UTF-8).
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                json_string(key, out);
                out.push(':');
                write_canonical(&map[*key], out);
            }
            out.push('}');
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rounding_matches_python_round() {
        // (x, round(x, 2)) from Python 3.
        for (x, want) in [
            (0.125, 0.12),
            (0.375, 0.38),
            (2.675, 2.67),
            (1.005, 1.0),
            (0.045, 0.04),
            (33.0, 33.0),
            (116.00000000000001, 116.0),
            (282.0, 282.0),
            (33.335, 33.34),
            (33.345, 33.34),
            (0.5, 0.5),
            (299.995, 300.0),
            (1e-9, 0.0),
        ] {
            assert_eq!(round_to(x, 2), want, "round({x}, 2)");
        }
        assert_eq!(round_to(0.0000005, 6), 0.0); // 5e-07 is just under the tie
        assert_eq!(round_to(0.0000015, 6), 0.000002);
        assert_eq!(round_to(0.9999995, 6), 1.0);
        assert_eq!(round_to(0.33333333, 6), 0.333333);
    }

    #[test]
    fn the_quick_rounding_and_printing_agree_with_the_exact_ones() {
        let mut values: Vec<f64> = (0..=2000).map(|m| m as f64 / 1e6).collect();
        values.extend((0..=1000).map(|m| 1.0 - m as f64 / 1e6));
        values.extend([
            0.0000005, 0.0000015, 0.0000025, 0.9999995, 0.1234565, 0.1234575, 0.5, 1.0, 0.0,
        ]);
        values.extend([
            1.0 / 3.0,
            2.0 / 3.0,
            0.1 + 0.2,
            1e-7,
            4.9e-7,
            5.1e-7,
            0.00009949,
            0.0000995,
            0.00010049,
        ]);
        let mut x: u64 = 0x2545F4914F6CDD1D;
        for _ in 0..200_000 {
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            values.push((x >> 11) as f64 / (1u64 << 53) as f64);
        }
        for p in values {
            let exact = round_to(p, 6);
            assert_eq!(round6(p), exact, "round6({p:?})");
            let mut text = String::new();
            write_rounded6(exact, &mut text);
            assert_eq!(text, float_repr(exact), "printing {exact:?}");
        }
        // anything else still prints, the slow way
        let mut text = String::new();
        write_rounded6(0.1234567, &mut text);
        assert_eq!(text, "0.1234567");
    }

    #[test]
    fn floats_print_as_python_repr() {
        for (x, want) in [
            (100.0, "100.0"),
            (1.0, "1.0"),
            (0.0, "0.0"),
            (0.33, "0.33"),
            (0.5, "0.5"),
            (1.25, "1.25"),
            (3.0, "3.0"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (0.000003, "3e-06"),
            (1.5e-7, "1.5e-07"),
            (1e15, "1000000000000000.0"),
            (1e16, "1e+16"),
            (1.2345e22, "1.2345e+22"),
            (-2.5, "-2.5"),
            (0.1 + 0.2, "0.30000000000000004"),
            (123456.789, "123456.789"),
            (0.999999, "0.999999"),
        ] {
            assert_eq!(float_repr(x), want);
        }
    }

    #[test]
    fn canonical_json_matches_json_dumps() {
        // The input has "e acute" and "u umlaut" as real characters and one control character.
        let text = "{\"b\": [1, 2.0, 0.33, true, null], \"a\": {\"z\": \"x\\ny\", \"\u{e9}\": \"\u{fc}\\\"\\\\ \\u0001\"}, \"pot\": 100}";
        let v: Value = serde_json::from_str(text).unwrap();
        // json.dumps(json.loads(text), sort_keys=True, separators=(",", ":")) in Python 3:
        let want = concat!(
            r#"{"a":{"z":"x\ny","\"#,
            r#"u00e9":"\"#,
            r#"u00fc\"\\ \"#,
            r#"u0001"},"b":[1,2.0,0.33,true,null],"pot":100}"#
        );
        assert_eq!(canonical_json(&v), want);
    }
}
