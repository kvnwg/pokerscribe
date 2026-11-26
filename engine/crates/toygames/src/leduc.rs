//! Leduc hold'em with OpenSpiel's rules (`leduc_poker`,
//! open_spiel/games/leduc_poker/leduc_poker.cc), default parameters (no
//! action mapping, no suit isomorphism, player 0 starts).
//!
//! 2 or 3 players, a deck of 2 * (players + 1) cards: cards 2r and 2r + 1
//! have rank r (for two players J J Q Q K K). Everyone antes 1. Chance deals
//! one private card to each player in order, then round 1 of betting, then
//! one public card, then round 2. Actions: Fold 0 (only legal when facing a
//! bet), Call 1 (check when nothing to call), Raise 2 (at most two raises a
//! round, by 2 chips in round 1 and 4 in round 2). Player 0 opens each round.
//! A round ends when everyone still in has checked, or everyone but the last
//! raiser has called. At showdown a player whose private card pairs the
//! public card wins; otherwise higher rank wins and equal ranks split the
//! pot. Payoffs are chips won or lost.

use cfr::{Action, Game, InfoKey, Node};

pub const FOLD: Action = 0;
pub const CALL: Action = 1;
pub const RAISE: Action = 2;

const MAX_PLAYERS: usize = 3;
const MAX_CARDS: usize = 2 * (MAX_PLAYERS + 1);
const MAX_RAISES: u8 = 2;
const NO_CARD: u8 = 15;

#[derive(Clone, Copy, Debug)]
pub struct Leduc {
    players: usize,
}

impl Leduc {
    pub fn new(players: usize) -> Self {
        assert!(
            (2..=MAX_PLAYERS).contains(&players),
            "Leduc supports 2 or 3 players"
        );
        Leduc { players }
    }

    fn deck_size(&self) -> usize {
        2 * (self.players + 1)
    }
}

impl Default for Leduc {
    fn default() -> Self {
        Leduc::new(2)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LeducState {
    /// Bit c set while card c is still in the deck.
    deck: u16,
    private: [u8; MAX_PLAYERS],
    public: u8,
    dealt: u8,
    /// Player to act, or -1 at a chance node.
    cur: i8,
    round: u8,
    stakes: i32,
    ante: [i32; MAX_PLAYERS],
    pot: i32,
    folded: [bool; MAX_PLAYERS],
    remaining: u8,
    num_calls: u8,
    num_raises: u8,
    /// Betting so far, as base-4 digits behind a leading 1: actions are
    /// 0, 1, 2 and the digit 3 marks the end of round 1.
    history: u64,
    terminal: bool,
}

impl LeducState {
    fn ready_for_next_round(&self) -> bool {
        (self.num_raises == 0 && self.num_calls == self.remaining)
            || (self.num_raises > 0 && self.num_calls == self.remaining - 1)
    }

    /// OpenSpiel's RankHand.
    fn rank_hand(&self, player: usize, deck_size: i32) -> i32 {
        let (mut lo, mut hi) = (self.public as i32, self.private[player] as i32);
        if lo > hi {
            std::mem::swap(&mut lo, &mut hi);
        }
        if lo % 2 == 0 && hi == lo + 1 {
            deck_size * deck_size + lo
        } else {
            (hi / 2) * deck_size + lo / 2
        }
    }

    pub fn private_card(&self, player: usize) -> u8 {
        self.private[player]
    }

    pub fn public_card(&self) -> Option<u8> {
        (self.public != NO_CARD).then_some(self.public)
    }

    pub fn round(&self) -> u8 {
        self.round
    }
}

impl Leduc {
    fn next_player(&self, s: &LeducState) -> i8 {
        let n = self.players;
        let from = if s.cur < 0 { n - 1 } else { s.cur as usize };
        for i in 1..=n {
            let p = (from + i) % n;
            if !s.folded[p] {
                return p as i8;
            }
        }
        unreachable!("every player folded")
    }

    fn after_action(&self, s: &mut LeducState) {
        if s.remaining == 1 || (s.round == 2 && s.ready_for_next_round()) {
            s.terminal = true;
        } else if s.ready_for_next_round() {
            s.round = 2;
            s.num_raises = 0;
            s.num_calls = 0;
            s.cur = -1;
            s.history = s.history * 4 + 3;
        } else {
            s.cur = self.next_player(s);
        }
    }
}

impl Game for Leduc {
    type State = LeducState;

    fn num_players(&self) -> usize {
        self.players
    }

    fn root(&self) -> LeducState {
        let n = self.players;
        let mut ante = [0; MAX_PLAYERS];
        ante[..n].fill(1);
        LeducState {
            deck: ((1u32 << self.deck_size()) - 1) as u16,
            private: [NO_CARD; MAX_PLAYERS],
            public: NO_CARD,
            dealt: 0,
            cur: -1,
            round: 1,
            stakes: 1,
            ante,
            pot: n as i32,
            folded: [false; MAX_PLAYERS],
            remaining: n as u8,
            num_calls: 0,
            num_raises: 0,
            history: 1,
            terminal: false,
        }
    }

    fn node(&self, s: &LeducState) -> Node {
        if s.terminal {
            Node::Terminal
        } else if s.cur < 0 {
            Node::Chance
        } else {
            Node::Player(s.cur as usize)
        }
    }

    fn chance_outcomes(&self, s: &LeducState, out: &mut Vec<(Action, f64)>) {
        let p = 1.0 / s.deck.count_ones() as f64;
        for c in 0..self.deck_size() {
            if s.deck & (1 << c) != 0 {
                out.push((c as Action, p));
            }
        }
    }

    fn legal_actions(&self, s: &LeducState, out: &mut Vec<Action>) {
        if s.stakes > s.ante[s.cur as usize] {
            out.push(FOLD);
        }
        out.push(CALL);
        if s.num_raises < MAX_RAISES {
            out.push(RAISE);
        }
    }

    fn apply(&self, s: &mut LeducState, a: Action) {
        if s.cur < 0 {
            let card = a as u8;
            debug_assert!(s.deck & (1 << card) != 0, "card {card} already dealt");
            s.deck &= !(1 << card);
            if (s.dealt as usize) < self.players {
                s.private[s.dealt as usize] = card;
                s.dealt += 1;
                if s.dealt as usize == self.players {
                    s.cur = self.next_player(s);
                }
            } else {
                s.public = card;
                s.cur = self.next_player(s);
            }
            return;
        }
        let p = s.cur as usize;
        s.history = s.history * 4 + a as u64;
        match a {
            FOLD => {
                s.folded[p] = true;
                s.remaining -= 1;
            }
            CALL => {
                let amount = s.stakes - s.ante[p];
                s.ante[p] += amount;
                s.pot += amount;
                s.num_calls += 1;
            }
            RAISE => {
                let raise = if s.round == 1 { 2 } else { 4 };
                let amount = s.stakes - s.ante[p] + raise;
                s.stakes += raise;
                s.ante[p] += amount;
                s.pot += amount;
                s.num_raises += 1;
                s.num_calls = 0;
            }
            _ => panic!("illegal Leduc action {a}"),
        }
        debug_assert!(s.history < 1 << 62, "history overflow");
        self.after_action(s);
    }

    fn info_key(&self, s: &LeducState) -> InfoKey {
        let p = s.cur as usize;
        p as u64 | (s.private[p] as u64) << 2 | (s.public as u64) << 6 | s.history << 10
    }

    fn utility(&self, s: &LeducState, player: usize) -> f64 {
        let n = self.players;
        let won = if s.remaining == 1 {
            if s.folded[player] {
                0.0
            } else {
                s.pot as f64
            }
        } else if s.folded[player] {
            0.0
        } else {
            let ds = self.deck_size() as i32;
            let best = (0..n)
                .filter(|&q| !s.folded[q])
                .map(|q| s.rank_hand(q, ds))
                .max()
                .unwrap();
            let winners = (0..n)
                .filter(|&q| !s.folded[q] && s.rank_hand(q, ds) == best)
                .count();
            if s.rank_hand(player, ds) == best {
                s.pot as f64 / winners as f64
            } else {
                0.0
            }
        };
        won - s.ante[player] as f64
    }

    /// Pluribus did not prune on the last betting round.
    fn prune_exempt(&self, s: &LeducState) -> bool {
        s.round == 2
    }
}

const _: () = assert!(MAX_CARDS <= 16);

#[cfg(test)]
mod tests {
    use super::*;
    use cfr::{expected_values, Cfr, Solver, UniformPolicy, Variant};

    #[test]
    fn two_player_tree_matches_openspiel_size() {
        // OpenSpiel's leduc_poker has 936 information states (468 each).
        let solver = Cfr::new(Leduc::new(2), Variant::Vanilla);
        assert_eq!(solver.info_sets(), 936);
        let ev = expected_values(&Leduc::new(2), &UniformPolicy);
        assert!((ev[0] + ev[1]).abs() < 1e-12);
    }

    #[test]
    fn showdown_and_fold() {
        let g = Leduc::new(2);
        let mut s = g.root();
        g.apply(&mut s, 0); // player 0: J
        g.apply(&mut s, 4); // player 1: K
        g.apply(&mut s, RAISE); // 0 raises to 3
        g.apply(&mut s, CALL); // 1 calls
        assert_eq!(g.node(&s), Node::Chance);
        g.apply(&mut s, 1); // public J: player 0 pairs
        assert_eq!(g.node(&s), Node::Player(0));
        let mut fold = s;
        g.apply(&mut fold, CALL);
        g.apply(&mut fold, RAISE); // 1 bets 4
        let mut actions = Vec::new();
        g.legal_actions(&fold, &mut actions);
        assert_eq!(actions, vec![FOLD, CALL, RAISE]);
        g.apply(&mut fold, FOLD);
        assert_eq!(g.node(&fold), Node::Terminal);
        assert_eq!(g.utility(&fold, 0), -3.0);
        assert_eq!(g.utility(&fold, 1), 3.0);
        g.apply(&mut s, RAISE); // 0 bets 4
        g.apply(&mut s, CALL);
        assert_eq!(g.node(&s), Node::Terminal);
        assert_eq!(g.utility(&s, 0), 7.0);
        assert_eq!(g.utility(&s, 1), -7.0);
    }

    #[test]
    fn split_pot() {
        let g = Leduc::new(2);
        let mut s = g.root();
        g.apply(&mut s, 0); // J
        g.apply(&mut s, 1); // J
        g.apply(&mut s, CALL);
        g.apply(&mut s, CALL);
        g.apply(&mut s, 4); // public K
        g.apply(&mut s, CALL);
        g.apply(&mut s, CALL);
        assert_eq!(g.node(&s), Node::Terminal);
        assert_eq!(g.utility(&s, 0), 0.0);
    }
}
