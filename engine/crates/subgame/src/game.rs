//! A spot made ready to solve: its tree, each range as a vector of combo weights, and the
//! tables that value the ends of the hand.
//!
//! Card removal is exact. A combo meets only the opposing combos it shares no card with.
//! Their total is: all of them, less those holding my first card, less those holding my
//! second card, plus the one holding both. So every end of the hand is valued in one pass
//! over the opposing range with 52 per-card sums. A showdown first sorts both ranges by
//! hand strength (once per board) and then walks them together, keeping the same sums for
//! the combos already passed: O(n log n) to set up, O(n) per showdown per iteration.
//!
//! Payoffs are those of `app/solver/exploitability.py`: chips at the end of the hand,
//! counting the pot at the start of the spot as nobody's yet. The winner takes the pot
//! plus what the loser put in, the loser loses what they put in, a split gives each half
//! the pot. The two players' payoffs add up to the pot.
//!
//! On a turn spot every river card that is in neither hand is equally likely: 44 cards
//! for any two hands that can be dealt together, so each deal (oop combo, ip combo, river)
//! weighs `w_oop * w_ip / 44`. The factor is applied to the opponent's reach where the
//! card is dealt, together with the removal of the combos that hold that card.

use eval::{Card, Hand};

use crate::cards::Combo;
use crate::spot::{Spot, SpotError, Street};
use crate::tree::{Node, NodeKind, Tree};

/// River cards a turn deal can still get: 52 less the board's 4 and the two hands' 4.
pub const RIVERS_PER_DEAL: f64 = 44.0;

/// One combo in a list sorted by strength.
#[derive(Clone, Copy, Debug)]
struct Ranked {
    index: u32,
    cards: [u8; 2],
    strength: u16,
}

/// One full board: the spot's own (river spots) or the turn board plus one river card.
#[derive(Clone, Debug)]
pub struct Runout {
    pub river: Option<Card>,
    /// For each player, 1.0 for the combos that can be held on this board and 0.0 for
    /// those that use the river card.
    pub alive: [Vec<f64>; 2],
    /// For each player, the combos that can be held, weakest first.
    sorted: [Vec<Ranked>; 2],
}

#[derive(Clone, Debug)]
pub struct Game {
    pub spot: Spot,
    pub tree: Tree,
    /// Each player's combos in the order of the spot's range, and their weights.
    pub combos: [Vec<Combo>; 2],
    pub weights: [Vec<f64>; 2],
    /// The two card indices of each combo.
    cards: [Vec<[u8; 2]>; 2],
    /// Where a player's combo sits in the other player's range, or `u32::MAX`.
    same: [Vec<u32>; 2],
    pub runouts: Vec<Runout>,
    /// The weight of every deal that can happen: the sum of `w_oop * w_ip` over the pairs
    /// of combos that share no card.
    pub total: f64,
    /// What a river card multiplies the opponent's reach by on a turn spot: `1 / 44`.
    pub chance_weight: f64,
    /// Taken off every payoff: 0. With half the pot, payoffs add up to 0 instead of the
    /// pot. Only that and `chance_weight` change when the tests redo TexasSolver's own
    /// turn arithmetic (river weight 1/46 on zero-sum payoffs; see the README).
    pub payoff_shift: f64,
}

impl Game {
    pub fn new(spot: Spot) -> Result<Game, SpotError> {
        let tree = Tree::new(&spot);
        let combos = [0, 1].map(|p| spot.ranges[p].iter().map(|(c, _)| *c).collect::<Vec<_>>());
        let weights = [0, 1].map(|p| spot.ranges[p].iter().map(|(_, w)| *w).collect::<Vec<_>>());
        let cards = [0, 1].map(|p| combos[p].iter().map(Combo::indices).collect::<Vec<_>>());
        let same = [0, 1].map(|p: usize| {
            combos[p]
                .iter()
                .map(|c| {
                    combos[1 - p]
                        .iter()
                        .position(|o| o == c)
                        .map_or(u32::MAX, |i| i as u32)
                })
                .collect::<Vec<_>>()
        });
        let board = Hand::from_cards(&spot.board);
        let runouts = tree
            .runouts
            .iter()
            .map(|&river| {
                let full = river.map_or(board, |c| board.add(c));
                let mut alive = [Vec::new(), Vec::new()];
                let mut sorted = [Vec::new(), Vec::new()];
                for p in 0..2 {
                    for (i, combo) in combos[p].iter().enumerate() {
                        let live = river.is_none_or(|c| !combo.contains(c));
                        alive[p].push(if live { 1.0 } else { 0.0 });
                        if live {
                            let strength = full.add(combo.hi).add(combo.lo).eval7().value();
                            sorted[p].push(Ranked {
                                index: i as u32,
                                cards: cards[p][i],
                                strength,
                            });
                        }
                    }
                    sorted[p].sort_by_key(|r| r.strength); // stable: ties keep the range's order
                }
                Runout {
                    river,
                    alive,
                    sorted,
                }
            })
            .collect();
        let mut game = Game {
            spot,
            tree,
            combos,
            weights,
            cards,
            same,
            runouts,
            total: 0.0,
            chance_weight: 1.0 / RIVERS_PER_DEAL,
            payoff_shift: 0.0,
        };
        let mut meets = vec![0.0; game.n(0)];
        game.meets(0, &game.weights[1], &mut meets);
        game.total = meets.iter().zip(&game.weights[0]).map(|(m, w)| m * w).sum();
        if game.total <= 0.0 {
            return Err(SpotError(
                "every deal clashes: the two ranges share a card in every pairing".to_string(),
            ));
        }
        Ok(game)
    }

    /// Number of combos in a player's range.
    pub fn n(&self, player: usize) -> usize {
        self.weights[player].len()
    }

    pub fn is_turn(&self) -> bool {
        self.spot.street == Street::Turn
    }

    /// For every combo of `player`: the opposing reach it can meet, which is the sum of
    /// `opp_reach` over the opposing combos that share no card with it.
    pub fn meets(&self, player: usize, opp_reach: &[f64], out: &mut [f64]) {
        let opp = 1 - player;
        let mut all = 0.0;
        let mut with = [0.0f64; 52];
        for (r, c) in opp_reach.iter().zip(&self.cards[opp]) {
            all += r;
            with[c[0] as usize] += r;
            with[c[1] as usize] += r;
        }
        let same = &self.same[player];
        for (i, c) in self.cards[player].iter().enumerate() {
            let both = if same[i] == u32::MAX {
                0.0
            } else {
                opp_reach[same[i] as usize]
            };
            out[i] = all - with[c[0] as usize] - with[c[1] as usize] + both;
        }
    }

    /// The value of a fold or showdown node for every combo of `player`: its payoff summed
    /// over the opposing combos, weighted by `opp_reach` (how often each gets here, times
    /// its range weight and the chance of the river card).
    pub fn terminal_values(&self, node: &Node, player: usize, opp_reach: &[f64], out: &mut [f64]) {
        let pot = self.spot.pot;
        match node.kind {
            NodeKind::Fold { folder } => {
                let u = if folder == player {
                    -node.put[player]
                } else {
                    pot + node.put[folder]
                };
                let u = u - self.payoff_shift;
                self.meets(player, opp_reach, out);
                match node.runout.filter(|_| self.is_turn()) {
                    // on a dealt river, a combo that holds the river card isn't there
                    Some(r) => {
                        for (v, alive) in out.iter_mut().zip(&self.runouts[r].alive[player]) {
                            *v *= u * alive;
                        }
                    }
                    None => out.iter_mut().for_each(|v| *v *= u),
                }
            }
            NodeKind::Showdown => {
                let runout = &self.runouts[node.runout.expect("a showdown has a full board")];
                let tie = 0.5 * pot - self.payoff_shift;
                self.showdown(runout, player, opp_reach, tie, 0.5 * pot + node.put[0], out);
            }
            _ => panic!("not a terminal node: {:?}", node.key),
        }
    }

    /// `out[i] = tie * (reach met) + edge * (reach beaten - reach lost to)`.
    fn showdown(
        &self,
        runout: &Runout,
        player: usize,
        opp_reach: &[f64],
        tie: f64,
        edge: f64,
        out: &mut [f64],
    ) {
        let opp = 1 - player;
        let (mine, theirs) = (&runout.sorted[player], &runout.sorted[opp]);
        if mine.len() < out.len() {
            out.fill(0.0); // combos that hold the river card
        }
        // Weakest first: the reach of every opposing combo this one beats.
        let mut sum = 0.0;
        let mut with = [0.0f64; 52];
        let mut j = 0;
        for m in mine {
            while j < theirs.len() && theirs[j].strength < m.strength {
                let t = &theirs[j];
                let r = opp_reach[t.index as usize];
                sum += r;
                with[t.cards[0] as usize] += r;
                with[t.cards[1] as usize] += r;
                j += 1;
            }
            out[m.index as usize] = sum - with[m.cards[0] as usize] - with[m.cards[1] as usize];
        }
        // The rest of the opposing range in one go, for the reach each combo meets.
        let mut all = sum;
        let mut all_with = with;
        for t in &theirs[j..] {
            let r = opp_reach[t.index as usize];
            all += r;
            all_with[t.cards[0] as usize] += r;
            all_with[t.cards[1] as usize] += r;
        }
        // Strongest first: the reach of every opposing combo that beats this one.
        let same = &self.same[player];
        sum = 0.0;
        with = [0.0f64; 52];
        j = theirs.len();
        for m in mine.iter().rev() {
            while j > 0 && theirs[j - 1].strength > m.strength {
                j -= 1;
                let t = &theirs[j];
                let r = opp_reach[t.index as usize];
                sum += r;
                with[t.cards[0] as usize] += r;
                with[t.cards[1] as usize] += r;
            }
            let i = m.index as usize;
            let (a, b) = (m.cards[0] as usize, m.cards[1] as usize);
            let lost = sum - with[a] - with[b];
            let both = if same[i] == u32::MAX {
                0.0
            } else {
                opp_reach[same[i] as usize]
            };
            let met = all - all_with[a] - all_with[b] + both;
            out[i] = tie * met + edge * (out[i] - lost);
        }
    }

    /// The same values the slow way, one pair of combos at a time. For tests.
    pub fn terminal_values_naive(&self, node: &Node, player: usize, opp_reach: &[f64]) -> Vec<f64> {
        let opp = 1 - player;
        let pot = self.spot.pot;
        let river = node.runout.and_then(|r| self.runouts[r].river);
        let board: Vec<Card> = self.spot.board.iter().copied().chain(river).collect();
        let strength = |c: &Combo| {
            let cards: Vec<Card> = board.iter().copied().chain([c.hi, c.lo]).collect();
            eval::eval(&cards)
        };
        let mut out = vec![0.0; self.n(player)];
        for (i, mine) in self.combos[player].iter().enumerate() {
            if river.is_some_and(|c| mine.contains(c)) {
                continue;
            }
            for (j, theirs) in self.combos[opp].iter().enumerate() {
                if theirs.contains(mine.hi)
                    || theirs.contains(mine.lo)
                    || river.is_some_and(|c| theirs.contains(c))
                {
                    continue;
                }
                let payoff = match node.kind {
                    NodeKind::Fold { folder } if folder == player => -node.put[player],
                    NodeKind::Fold { folder } => pot + node.put[folder],
                    NodeKind::Showdown => match strength(mine).cmp(&strength(theirs)) {
                        std::cmp::Ordering::Greater => pot + node.put[opp],
                        std::cmp::Ordering::Less => -node.put[player],
                        std::cmp::Ordering::Equal => 0.5 * pot,
                    },
                    _ => panic!("not a terminal node"),
                };
                out[i] += opp_reach[j] * payoff;
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spot::tests::RIVER;
    use serde_json::Value;

    /// A spot with wide, overlapping ranges: every combo of the ranks given.
    pub(crate) fn wide_spot(street: &str) -> Spot {
        let mut v: Value = serde_json::from_str(RIVER).unwrap();
        let board: Vec<&str> = if street == "turn" {
            vec!["Ks", "7d", "2c", "4h"]
        } else {
            vec!["Ks", "7d", "2c", "4h", "9s"]
        };
        v["street"] = street.into();
        v["board"] = serde_json::json!(board);
        v["stacks"] = serde_json::json!([150, 150]);
        let sizes = serde_json::json!({
            "oop": {"bets": [0.5], "raises": [0.5], "allin": true},
            "ip": {"bets": [0.5], "raises": [0.5], "allin": true}});
        v["sizes"] = sizes.clone();
        if street == "turn" {
            v["river_sizes"] = sizes;
        }
        let range = |ranks: &str, weight: f64| {
            let mut out = serde_json::Map::new();
            let cards: Vec<Card> = Card::all()
                .filter(|c| ranks.contains(eval::RANK_CHARS[c.rank() as usize]))
                .filter(|c| !board.contains(&c.to_string().as_str()))
                .collect();
            for (i, a) in cards.iter().enumerate() {
                for b in &cards[..i] {
                    let w = if (a.index() + b.index()) % 3 == 0 {
                        weight
                    } else {
                        1.0
                    };
                    out.insert(Combo::new(*a, *b).unwrap().text(), w.into());
                }
            }
            Value::Object(out)
        };
        v["ranges"] = serde_json::json!({"oop": range("AK9742", 0.5), "ip": range("AKQ972", 0.25)});
        Spot::from_json(&v.to_string()).unwrap()
    }

    /// Repeatable reaches between 0 and 1, some of them 0.
    pub(crate) fn fake_reach(n: usize, seed: u64) -> Vec<f64> {
        let mut x = seed.wrapping_mul(0x9E3779B97F4A7C15) | 1;
        (0..n)
            .map(|_| {
                x ^= x << 13;
                x ^= x >> 7;
                x ^= x << 17;
                let u = (x >> 11) as f64 / (1u64 << 53) as f64;
                if u < 0.15 {
                    0.0
                } else {
                    u
                }
            })
            .collect()
    }

    fn assert_close(a: &[f64], b: &[f64], what: &str) {
        assert_eq!(a.len(), b.len());
        for (i, (x, y)) in a.iter().zip(b).enumerate() {
            assert!(
                (x - y).abs() <= 1e-9 * (1.0 + y.abs()),
                "{what}, combo {i}: {x} != {y}"
            );
        }
    }

    #[test]
    fn every_terminal_matches_the_pair_by_pair_sum() {
        for street in ["river", "turn"] {
            let game = Game::new(wide_spot(street)).unwrap();
            assert!(game.n(0) > 100 && game.n(1) > 100);
            let mut checked = 0;
            for (id, node) in game.tree.nodes.iter().enumerate() {
                // every terminal of a river spot; on the turn, those of three river cards
                if !node.is_terminal()
                    || (street == "turn" && node.runout.is_some_and(|r| r % 20 != 3))
                {
                    continue;
                }
                for player in 0..2 {
                    let mut reach = fake_reach(game.n(1 - player), (id * 2 + player) as u64 + 1);
                    if let Some(r) = node.runout {
                        for (x, alive) in reach.iter_mut().zip(&game.runouts[r].alive[1 - player]) {
                            *x *= alive;
                        }
                    }
                    let mut fast = vec![f64::NAN; game.n(player)];
                    game.terminal_values(node, player, &reach, &mut fast);
                    let slow = game.terminal_values_naive(node, player, &reach);
                    assert_close(
                        &fast,
                        &slow,
                        &format!("{street} {:?} player {player}", node.key),
                    );
                    checked += 1;
                }
            }
            assert!(checked > 20, "{street}: {checked} terminals checked");
        }
    }

    #[test]
    fn deals_that_share_a_card_get_no_weight() {
        let game = Game::new(wide_spot("river")).unwrap();
        let mut total = 0.0;
        for (a, wa) in game.combos[0].iter().zip(&game.weights[0]) {
            for (b, wb) in game.combos[1].iter().zip(&game.weights[1]) {
                if !b.contains(a.hi) && !b.contains(a.lo) {
                    total += wa * wb;
                }
            }
        }
        assert!((game.total - total).abs() < 1e-9 * total);
        // both ranges hold AsAh: against it alone, AsAh itself meets nothing
        let i = game.combos[0]
            .iter()
            .position(|c| c.text() == "AhAd")
            .unwrap();
        let j = game.combos[1]
            .iter()
            .position(|c| c.text() == "AhAd")
            .unwrap();
        let mut reach = vec![0.0; game.n(1)];
        reach[j] = 1.0;
        let mut out = vec![0.0; game.n(0)];
        game.meets(0, &reach, &mut out);
        assert_eq!(out[i], 0.0);
        for (k, c) in game.combos[0].iter().enumerate() {
            let clash = c.text().contains("Ah") || c.text().contains("Ad");
            assert_eq!(out[k], if clash { 0.0 } else { 1.0 }, "{}", c.text());
        }
    }

    #[test]
    fn a_turn_runout_drops_the_combos_that_hold_the_river_card() {
        let game = Game::new(wide_spot("turn")).unwrap();
        assert_eq!(game.runouts.len(), 48);
        for runout in &game.runouts {
            let river = runout.river.unwrap();
            for p in 0..2 {
                for (combo, alive) in game.combos[p].iter().zip(&runout.alive[p]) {
                    assert_eq!(*alive == 0.0, combo.contains(river));
                }
                let n_alive = runout.alive[p].iter().filter(|a| **a == 1.0).count();
                assert_eq!(runout.sorted[p].len(), n_alive);
                assert!(runout.sorted[p]
                    .windows(2)
                    .all(|w| w[0].strength <= w[1].strength));
            }
        }
    }

    #[test]
    fn ranges_that_always_clash_are_refused() {
        let mut v: Value = serde_json::from_str(RIVER).unwrap();
        v["ranges"] = serde_json::json!({"oop": {"AhAd": 1.0}, "ip": {"AhKd": 1.0, "AdQc": 0.5}});
        let e = Game::new(Spot::from_json(&v.to_string()).unwrap()).unwrap_err();
        assert!(e.0.contains("every deal clashes"));
    }
}
