//! The "expected" checks of a spot (`data/SPOT_FORMAT.md`, "Expected checks"), as
//! `tools/answer_keys/checks.py::check_expected` runs them.
//!
//! Each check names nodes by a regular expression. The `regex` crate isn't a dependency,
//! so a small matcher is here. It knows what node keys need: literals, `.`, classes like
//! `[0-9.]`, the escapes `\d \w \s` and escaped literals, `^` and `$`, and `* + ?` after
//! one item. Groups and `|` aren't supported; a check that uses them is reported as failed.

use crate::result::NodeRecord;
use crate::spot::{Expected, Spot};

#[derive(Clone, Debug, PartialEq)]
enum Item {
    Any,
    Literal(char),
    Class {
        negated: bool,
        ranges: Vec<(char, char)>,
    },
    Start,
    End,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Repeat {
    One,
    ZeroOrOne,
    ZeroOrMore,
    OneOrMore,
}

/// A compiled pattern, matched anywhere in the text like Python's `re.search`.
#[derive(Clone, Debug, PartialEq)]
pub struct Pattern(Vec<(Item, Repeat)>);

fn escape(c: char) -> Item {
    match c {
        'd' => Item::Class {
            negated: false,
            ranges: vec![('0', '9')],
        },
        'w' => Item::Class {
            negated: false,
            ranges: vec![('a', 'z'), ('A', 'Z'), ('0', '9'), ('_', '_')],
        },
        's' => Item::Class {
            negated: false,
            ranges: vec![(' ', ' '), ('\t', '\r')],
        },
        c => Item::Literal(c),
    }
}

impl Pattern {
    pub fn new(pattern: &str) -> Result<Pattern, String> {
        let chars: Vec<char> = pattern.chars().collect();
        let mut items: Vec<(Item, Repeat)> = Vec::new();
        let mut i = 0;
        while i < chars.len() {
            let item = match chars[i] {
                '^' => Item::Start,
                '$' => Item::End,
                '.' => Item::Any,
                '\\' => {
                    i += 1;
                    escape(*chars.get(i).ok_or("the pattern ends with a backslash")?)
                }
                '[' => {
                    i += 1;
                    let negated = chars.get(i) == Some(&'^');
                    if negated {
                        i += 1;
                    }
                    let mut ranges = Vec::new();
                    let mut first = true;
                    loop {
                        let c = *chars.get(i).ok_or("a [ is never closed")?;
                        if c == ']' && !first {
                            break;
                        }
                        first = false;
                        let lo = if c == '\\' {
                            i += 1;
                            match escape(*chars.get(i).ok_or("the pattern ends with a backslash")?)
                            {
                                Item::Literal(c) => c,
                                Item::Class { ranges: more, .. } => {
                                    ranges.extend(more);
                                    i += 1;
                                    continue;
                                }
                                _ => unreachable!(),
                            }
                        } else {
                            c
                        };
                        if chars.get(i + 1) == Some(&'-')
                            && chars.get(i + 2).is_some_and(|c| *c != ']')
                        {
                            ranges.push((lo, chars[i + 2]));
                            i += 3;
                        } else {
                            ranges.push((lo, lo));
                            i += 1;
                        }
                    }
                    Item::Class { negated, ranges }
                }
                '*' | '+' | '?' => {
                    let repeat = match chars[i] {
                        '*' => Repeat::ZeroOrMore,
                        '+' => Repeat::OneOrMore,
                        _ => Repeat::ZeroOrOne,
                    };
                    match items.last_mut() {
                        Some((item, r))
                            if *r == Repeat::One && !matches!(item, Item::Start | Item::End) =>
                        {
                            *r = repeat
                        }
                        _ => return Err(format!("nothing to repeat at {:?}", chars[i])),
                    }
                    i += 1;
                    continue;
                }
                c @ ('(' | ')' | '|' | '{' | '}') => {
                    return Err(format!("{c:?} isn't supported in a node pattern"));
                }
                c => Item::Literal(c),
            };
            items.push((item, Repeat::One));
            i += 1;
        }
        Ok(Pattern(items))
    }

    /// True when the pattern matches somewhere in `text`.
    pub fn search(&self, text: &str) -> bool {
        let chars: Vec<char> = text.chars().collect();
        (0..=chars.len()).any(|start| matches(&self.0, &chars, start))
    }
}

fn one(item: &Item, c: char) -> bool {
    match item {
        Item::Any => c != '\n',
        Item::Literal(l) => *l == c,
        Item::Class { negated, ranges } => {
            ranges.iter().any(|(lo, hi)| *lo <= c && c <= *hi) != *negated
        }
        Item::Start | Item::End => false,
    }
}

fn matches(items: &[(Item, Repeat)], text: &[char], at: usize) -> bool {
    let Some(((item, repeat), rest)) = items.split_first() else {
        return true;
    };
    match item {
        Item::Start => at == 0 && matches(rest, text, at),
        Item::End => at == text.len() && matches(rest, text, at),
        _ => {
            let (min, max) = match repeat {
                Repeat::One => (1, 1),
                Repeat::ZeroOrOne => (0, 1),
                Repeat::ZeroOrMore => (0, usize::MAX),
                Repeat::OneOrMore => (1, usize::MAX),
            };
            let mut count = 0;
            while count < max && at + count < text.len() && one(item, text[at + count]) {
                count += 1;
            }
            // greedy, then give back one at a time
            (min..=count).rev().any(|n| matches(rest, text, at + n))
        }
    }
}

/// How often a combo takes any action of this kind: `x`, `c`, `f`, `b` (any bet), `r`
/// (any raise).
fn kind_share(record: &NodeRecord, row: &[f64], kind: &str) -> f64 {
    record
        .actions
        .iter()
        .zip(row)
        .filter(|(a, _)| a.starts_with(kind))
        .map(|(_, p)| *p)
        .sum()
}

fn check(expected: &Expected, nodes: &[NodeRecord], failures: &mut Vec<String>) {
    let pattern = match Pattern::new(&expected.nodes) {
        Ok(p) => p,
        Err(e) => {
            failures.push(format!("can't read the pattern {:?}: {e}", expected.nodes));
            return;
        }
    };
    let matched: Vec<&NodeRecord> = nodes
        .iter()
        .filter(|r| {
            pattern.search(&r.node) && (expected.actor == "any" || expected.actor == r.actor)
        })
        .collect();
    if matched.is_empty() {
        failures.push(format!(
            "no {} node matches {:?}",
            expected.actor, expected.nodes
        ));
    }
    for record in matched {
        for (combo, row) in &record.strategy {
            let share = kind_share(record, row, &expected.action);
            if let Some(min) = expected.min.filter(|min| share < *min) {
                failures.push(format!(
                    "{:?} {combo}: {} {share:.3} < {min}",
                    record.node, expected.action
                ));
            }
            if let Some(max) = expected.max.filter(|max| share > *max) {
                failures.push(format!(
                    "{:?} {combo}: {} {share:.3} > {max}",
                    record.node, expected.action
                ));
            }
        }
    }
}

/// Every way an answer breaks the spot's expected checks. An empty list passes.
pub fn check_expected(spot: &Spot, nodes: &[NodeRecord]) -> Vec<String> {
    let mut failures = Vec::new();
    for expected in &spot.expected {
        check(expected, nodes, &mut failures);
    }
    failures
}

#[cfg(test)]
mod tests {
    use super::*;

    fn found(pattern: &str, text: &str) -> bool {
        Pattern::new(pattern).unwrap().search(text)
    }

    #[test]
    fn the_patterns_of_the_trivial_spots() {
        assert!(found("^x$", "x"));
        assert!(!found("^x$", "x b50") && !found("^x$", "") && !found("^x$", "x x"));
        assert!(found("^$", "") && !found("^$", "x"));
        assert!(found("^b[0-9.]+$", "b50") && found("^b[0-9.]+$", "b33.5"));
        assert!(
            !found("^b[0-9.]+$", "b")
                && !found("^b[0-9.]+$", "b50 r150")
                && !found("^b[0-9.]+$", "x b50")
        );
        assert!(found("^x b[0-9.]+$", "x b100") && !found("^x b[0-9.]+$", "b100"));
    }

    #[test]
    fn search_finds_a_match_anywhere() {
        assert!(found("b50", "x b50 c"));
        assert!(found(r"r\d+ c$", "b50 r150 c") && !found(r"r\d+ c$", "b50 r150 f"));
        assert!(found("x .h", "x x 7h b100") && !found("x .h", "x x 7d"));
        assert!(found("ab*c", "ac") && found("ab*c", "abbbc") && !found("ab+c", "ac"));
        assert!(found("colou?r", "color") && found("colou?r", "colour"));
        assert!(found("[^x ]", "x b") && !found("[^x ]", "x x"));
        assert!(found(r"a\.b", "a.b") && !found(r"a\.b", "axb"));
        assert!(found("[a-c]+$", "xxabc") && found("[]x]", "]") && found("[a-]", "-"));
        assert!(found("a.*b.*c", "a--b--c") && !found("a.*b.*c", "a--c--b"));
    }

    #[test]
    fn unsupported_patterns_are_errors() {
        for bad in ["(a|b)", "a{2}", "*a", "a**", "[abc", "a\\"] {
            assert!(Pattern::new(bad).is_err(), "{bad}");
        }
    }

    fn record(node: &str, actor: &str, actions: &[&str], rows: &[(&str, &[f64])]) -> NodeRecord {
        NodeRecord {
            node: node.to_string(),
            actor: actor.to_string(),
            actions: actions.iter().map(|a| a.to_string()).collect(),
            strategy: rows
                .iter()
                .map(|(c, r)| (c.to_string(), r.to_vec()))
                .collect(),
        }
    }

    #[test]
    fn checks_count_action_kinds_per_combo() {
        let nodes = vec![
            record(
                "x",
                "ip",
                &["x", "b50", "b100"],
                &[("AhKd", &[0.99, 0.01, 0.0]), ("QsQh", &[0.5, 0.25, 0.25])],
            ),
            record(
                "b50",
                "ip",
                &["f", "c", "r150", "r300"],
                &[("AhKd", &[0.0, 0.2, 0.3, 0.5])],
            ),
        ];
        let expect =
            |nodes_re: &str, actor: &str, action: &str, min: Option<f64>, max: Option<f64>| {
                Expected {
                    nodes: nodes_re.to_string(),
                    actor: actor.to_string(),
                    action: action.to_string(),
                    min,
                    max,
                    why: String::new(),
                }
            };
        let run = |e: Expected| {
            let mut failures = Vec::new();
            check(&e, &nodes, &mut failures);
            failures
        };
        assert_eq!(
            run(expect("^x$", "ip", "x", Some(0.98), None)),
            ["\"x\" QsQh: x 0.500 < 0.98"]
        );
        assert_eq!(
            run(expect("^x$", "ip", "b", None, Some(0.02))),
            ["\"x\" QsQh: b 0.500 > 0.02"]
        );
        assert!(run(expect("^b[0-9.]+$", "any", "r", Some(0.8), None)).is_empty()); // both raises count
        assert_eq!(
            run(expect("^x$", "oop", "x", Some(0.5), None)),
            ["no oop node matches \"^x$\""]
        );
        assert_eq!(run(expect("(x)", "ip", "x", Some(0.5), None)).len(), 1);
    }
}
