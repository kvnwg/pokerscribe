#![allow(dead_code)]

use cfr::{expected_values, exploitability, Game, Solver};

/// Exploitability and player 0's value of a solver's average policy.
pub fn measure<G: Game, S: Solver>(game: &G, solver: &S) -> (f64, f64) {
    let pol = solver.average_policy();
    (exploitability(game, &pol), expected_values(game, &pol)[0])
}

/// A minimal JSON reader, enough for the committed reference file.
#[derive(Debug, Clone)]
pub enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl Json {
    pub fn parse(text: &str) -> Json {
        let mut p = Parser {
            s: text.as_bytes(),
            i: 0,
        };
        let v = p.value();
        p.ws();
        assert_eq!(p.i, p.s.len(), "trailing data in JSON");
        v
    }

    pub fn get(&self, key: &str) -> &Json {
        match self {
            Json::Obj(kv) => {
                &kv.iter()
                    .find(|(k, _)| k == key)
                    .unwrap_or_else(|| panic!("no key {key}"))
                    .1
            }
            _ => panic!("not an object"),
        }
    }

    pub fn num(&self) -> f64 {
        match self {
            Json::Num(x) => *x,
            _ => panic!("not a number: {self:?}"),
        }
    }

    pub fn arr(&self) -> &[Json] {
        match self {
            Json::Arr(a) => a,
            _ => panic!("not an array"),
        }
    }
}

struct Parser<'a> {
    s: &'a [u8],
    i: usize,
}

impl Parser<'_> {
    fn ws(&mut self) {
        while self.i < self.s.len() && self.s[self.i].is_ascii_whitespace() {
            self.i += 1;
        }
    }

    fn eat(&mut self, c: u8) {
        self.ws();
        assert_eq!(
            self.s[self.i], c,
            "expected '{}' at byte {}",
            c as char, self.i
        );
        self.i += 1;
    }

    fn string(&mut self) -> String {
        self.eat(b'"');
        let start = self.i;
        while self.s[self.i] != b'"' {
            assert_ne!(self.s[self.i], b'\\', "escapes not supported");
            self.i += 1;
        }
        let out = String::from_utf8(self.s[start..self.i].to_vec()).unwrap();
        self.i += 1;
        out
    }

    fn value(&mut self) -> Json {
        self.ws();
        match self.s[self.i] {
            b'{' => {
                self.i += 1;
                let mut kv = Vec::new();
                self.ws();
                if self.s[self.i] == b'}' {
                    self.i += 1;
                    return Json::Obj(kv);
                }
                loop {
                    let k = self.string();
                    self.eat(b':');
                    kv.push((k, self.value()));
                    self.ws();
                    self.i += 1;
                    if self.s[self.i - 1] == b'}' {
                        return Json::Obj(kv);
                    }
                }
            }
            b'[' => {
                self.i += 1;
                let mut a = Vec::new();
                self.ws();
                if self.s[self.i] == b']' {
                    self.i += 1;
                    return Json::Arr(a);
                }
                loop {
                    a.push(self.value());
                    self.ws();
                    self.i += 1;
                    if self.s[self.i - 1] == b']' {
                        return Json::Arr(a);
                    }
                }
            }
            b'"' => Json::Str(self.string()),
            b't' => {
                self.i += 4;
                Json::Bool(true)
            }
            b'f' => {
                self.i += 5;
                Json::Bool(false)
            }
            b'n' => {
                self.i += 4;
                Json::Null
            }
            _ => {
                let start = self.i;
                while self.i < self.s.len() && b"+-0123456789.eE".contains(&self.s[self.i]) {
                    self.i += 1;
                }
                Json::Num(
                    std::str::from_utf8(&self.s[start..self.i])
                        .unwrap()
                        .parse()
                        .unwrap(),
                )
            }
        }
    }
}
