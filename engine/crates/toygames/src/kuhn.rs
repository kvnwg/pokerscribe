//! Kuhn poker for 2 or more players, with OpenSpiel's rules
//! (`kuhn_poker`, open_spiel/games/kuhn_poker/kuhn_poker.cc).
//!
//! n players, n + 1 cards (0 is lowest). Everyone antes 1. Chance deals one
//! card to player 0, then 1, and so on. Players act in turn: Pass (action 0)
//! or Bet (action 1, one chip). With no bet, the game ends once every player
//! has passed and the highest card wins. After the first bet each other
//! player acts once more, in turn: Bet means call, Pass means fold. The
//! highest card among the players who bet wins the pot. Payoffs are chips
//! won or lost.

use cfr::{Action, Game, InfoKey, Node};

pub const PASS: Action = 0;
pub const BET: Action = 1;

const MAX_PLAYERS: usize = 8;

#[derive(Clone, Copy, Debug)]
pub struct Kuhn {
    players: usize,
}

impl Kuhn {
    pub fn new(players: usize) -> Self {
        assert!(
            (2..=MAX_PLAYERS).contains(&players),
            "Kuhn supports 2 to {MAX_PLAYERS} players"
        );
        Kuhn { players }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct KuhnState {
    /// Card of each player (valid for the first `dealt`).
    cards: [u8; MAX_PLAYERS],
    dealt: u8,
    /// Betting actions so far; bit i set means action i was a bet.
    bets: u16,
    len: u8,
    /// Player who bet first, or -1.
    first_bettor: i8,
    terminal: bool,
}

impl KuhnState {
    /// Whether `player` put a bet in at any point.
    fn did_bet(&self, player: usize, n: usize) -> bool {
        (0..self.len as usize).any(|i| i % n == player && self.bets & (1 << i) != 0)
    }
}

impl Game for Kuhn {
    type State = KuhnState;

    fn num_players(&self) -> usize {
        self.players
    }

    fn root(&self) -> KuhnState {
        KuhnState {
            cards: [0; MAX_PLAYERS],
            dealt: 0,
            bets: 0,
            len: 0,
            first_bettor: -1,
            terminal: false,
        }
    }

    fn node(&self, s: &KuhnState) -> Node {
        if s.terminal {
            Node::Terminal
        } else if (s.dealt as usize) < self.players {
            Node::Chance
        } else {
            Node::Player(s.len as usize % self.players)
        }
    }

    fn chance_outcomes(&self, s: &KuhnState, out: &mut Vec<(Action, f64)>) {
        let dealt = &s.cards[..s.dealt as usize];
        let left = self.players + 1 - dealt.len();
        let p = 1.0 / left as f64;
        for card in 0..=self.players as u8 {
            if !dealt.contains(&card) {
                out.push((card as Action, p));
            }
        }
    }

    fn legal_actions(&self, _s: &KuhnState, out: &mut Vec<Action>) {
        out.push(PASS);
        out.push(BET);
    }

    fn apply(&self, s: &mut KuhnState, a: Action) {
        let n = self.players;
        if (s.dealt as usize) < n {
            s.cards[s.dealt as usize] = a as u8;
            s.dealt += 1;
            return;
        }
        let player = s.len as usize % n;
        if a == BET {
            s.bets |= 1 << s.len;
            if s.first_bettor < 0 {
                s.first_bettor = player as i8;
            }
        }
        s.len += 1;
        let len = s.len as usize;
        s.terminal = if s.first_bettor < 0 {
            len == n
        } else {
            len == n + s.first_bettor as usize
        };
    }

    fn info_key(&self, s: &KuhnState) -> InfoKey {
        let player = s.len as usize % self.players;
        player as u64 | (s.cards[player] as u64) << 4 | (s.len as u64) << 8 | (s.bets as u64) << 16
    }

    fn utility(&self, s: &KuhnState, player: usize) -> f64 {
        let n = self.players;
        let pot = n + s.bets.count_ones() as usize;
        let winner = (0..n)
            .filter(|&p| s.first_bettor < 0 || s.did_bet(p, n))
            .max_by_key(|&p| s.cards[p])
            .expect("no player left");
        let put_in = if s.did_bet(player, n) { 2.0 } else { 1.0 };
        if player == winner {
            pot as f64 - put_in
        } else {
            -put_in
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cfr::{expected_values, Cfr, Solver, UniformPolicy, Variant};

    #[test]
    fn two_player_tree() {
        let solver = Cfr::new(Kuhn::new(2), Variant::Vanilla);
        assert_eq!(solver.info_sets(), 12);
        let ev = expected_values(&Kuhn::new(2), &UniformPolicy);
        assert!((ev[0] + ev[1]).abs() < 1e-12);
    }

    #[test]
    fn three_player_tree() {
        // OpenSpiel: 48 information states for 3-player Kuhn.
        let solver = Cfr::new(Kuhn::new(3), Variant::Vanilla);
        assert_eq!(solver.info_sets(), 48);
        let ev = expected_values(&Kuhn::new(3), &UniformPolicy);
        assert!(ev.iter().sum::<f64>().abs() < 1e-12);
    }

    #[test]
    fn payoffs() {
        let g = Kuhn::new(2);
        let mut s = g.root();
        g.apply(&mut s, 2); // player 0 gets the king
        g.apply(&mut s, 0); // player 1 the jack
        g.apply(&mut s, PASS);
        g.apply(&mut s, BET);
        assert_eq!(g.node(&s), Node::Player(0));
        let mut fold = s;
        g.apply(&mut fold, PASS);
        assert_eq!(g.node(&fold), Node::Terminal);
        assert_eq!(g.utility(&fold, 0), -1.0);
        assert_eq!(g.utility(&fold, 1), 1.0);
        g.apply(&mut s, BET);
        assert_eq!(g.utility(&s, 0), 2.0);
        assert_eq!(g.utility(&s, 1), -2.0);
    }
}
