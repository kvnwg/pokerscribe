//! AIVAT: a luck correction that leaves every agent's expected result as it is.
//!
//! After Burch, Schmid, Moravcik, Morrill and Bowling, "AIVAT: A New Variance Reduction
//! Technique for Agent Evaluation in Imperfect Information Games" (AAAI 2018). The arena
//! deals the cards, so it knows every card of every hand, which makes the estimator
//! simpler than the paper's general one.
//!
//! # The estimator
//!
//! A hand is a sequence of events: the deal of the hole cards, the players' actions and
//! the board cards. For some of them the arena knows the exact chances given everything
//! before: the cards (every unseen card is equally likely, whatever the players did,
//! since nobody sees them before they fall) and the actions of a player that reports the
//! chances it drew its action with ([`crate::Player::probabilities`]). At each such event
//! with outcome `x`, AIVAT subtracts a correction
//!
//! ```text
//! v(after x) - sum over every possible outcome y of P(y) v(after y)
//! ```
//!
//! where `v` is a value estimate for each seat. Given everything before the event, the
//! correction averages exactly 0, whatever `v` is: `x` is drawn with the chances `P`, so
//! the first term's average is the second. So the corrected score of every hand has the
//! same expected value as its real result, for any `v` and whichever events are
//! corrected. That is the whole argument, and the reason it needs nothing from the agents
//! but honest chances: the value estimate only decides how much luck is taken out, never
//! the expected result. Actions of a player that reports nothing (B0, a Python agent, a
//! rule bot) are not corrected: their chances are unknown.
//!
//! When `v` is good, the corrections cancel most of the luck: a lucky river card raises
//! the real result and the correction by about the same amount.
//!
//! # The value estimate
//!
//! [`Aivat`]'s `v` is the check-down value: each seat's share of the chips in the middle
//! if nobody bet again and the hand were shown down, averaged over every board that can
//! still come, minus what the seat put in. Side pots are paid as at the table and ties
//! split exactly. A bet that has not been answered yet is valued by [`Facing`]: by
//! default each player facing it calls with the chance that makes a bluff break even
//! (the pot before the bet over the pot after it, the minimum defense frequency) and
//! folds otherwise.
//!
//! An action is valued one step further when the next player to act can say what it
//! would play there ([`crate::Player::chances_at`]; blueprint agents and the rule bot
//! `mixed` can): the value after each of its answers, averaged with its chances. A
//! bet that a known strategy folds to most of the time is then worth about the pot,
//! whatever the minimum defense frequency says. The answers are asked for after the hand,
//! about situations it may not have reached, and only shape `v`, so they can't bias the
//! result either, as long as they depend on nothing that happened in the hand.
//!
//! The averages are exact on the flop, the turn and the river (every board). Before the
//! flop they are averaged over [`Aivat::boards`] boards drawn at random, an estimate with
//! no bias drawn from a random number of its own, which is all the corrections need. The
//! deal's correction uses the exact average over all deals, worked out without dealing:
//! every seat that can win a pot is as likely as any other to hold the best hand.

use std::cell::RefCell;
use std::rc::Rc;

use eval::Hand;
use nlhe::{Action, Chips, Config, Deal, Rng, State, MAX_PLAYERS};
use serde::{Deserialize, Serialize};

use crate::equity::{below, choose};
use crate::luck::{HandRecord, Scorer};
use crate::mix;
use crate::player::{Player, View};
use crate::ranker::to_eval;

/// The default of [`Aivat::boards`].
pub const DEFAULT_AIVAT_BOARDS: u32 = 2_000;

const fn bit(seat: usize) -> u8 {
    1 << seat
}

/// How the value estimate treats a bet (or raise) that players still have to answer.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Facing {
    /// Each player facing the bet calls with the chance `P / (P + r)` and folds
    /// otherwise, each on its own: `r` is what it has to add to call and `P` the chips
    /// in the middle at its own level before that (what every seat put in, up to what
    /// it put in). This is the minimum defense frequency: with it a bet that never wins
    /// at a showdown is worth exactly as much as giving up.
    #[default]
    MinimumDefense,
    /// Every player facing the bet calls.
    Called,
    /// The bet is taken back: only the chips everyone matched are checked down.
    TakenBack,
}

impl Facing {
    pub const NAMES: [&'static str; 3] = ["minimum-defense", "called", "taken-back"];

    pub fn parse(name: &str) -> Option<Facing> {
        match name {
            "minimum-defense" => Some(Facing::MinimumDefense),
            "called" => Some(Facing::Called),
            "taken-back" => Some(Facing::TakenBack),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Facing::MinimumDefense => "minimum-defense",
            Facing::Called => "called",
            Facing::TakenBack => "taken-back",
        }
    }
}

/// The AIVAT scorer (see the module notes). A match runs it next to its main scorer
/// when `MatchConfig::aivat` holds one; it is also a [`Scorer`] of its own.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct Aivat {
    /// Boards drawn for the value estimate before the flop.
    pub boards: u32,
    /// How bets still to be answered are valued.
    pub facing: Facing,
}

impl Default for Aivat {
    fn default() -> Aivat {
        Aivat {
            boards: DEFAULT_AIVAT_BOARDS,
            facing: Facing::MinimumDefense,
        }
    }
}

/// One hand scored by AIVAT.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct AivatHand {
    /// Each seat's corrected score in chips. They add up to 0, as the payouts do.
    pub scores: [f64; MAX_PLAYERS],
    /// Per seat: decisions whose random choice was corrected.
    pub corrected: [u32; MAX_PLAYERS],
    /// Per seat: decisions without known chances (not corrected).
    pub unknown: [u32; MAX_PLAYERS],
    /// Per seat: decisions whose reported chances can't be right: the action taken is not
    /// among them, or one of them is not legal (not corrected).
    pub unexplained: [u32; MAX_PLAYERS],
}

/// The chips of a hand at one moment: what is in, what is behind, who is still in.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Stakes {
    pub n: usize,
    /// Everything each seat has put in this hand.
    pub committed: [Chips; MAX_PLAYERS],
    /// Chips behind.
    pub behind: [Chips; MAX_PLAYERS],
    /// Seats that have not folded.
    pub active: u8,
}

impl Stakes {
    pub fn of(state: &State) -> Stakes {
        let n = state.num_players();
        let mut s = Stakes {
            n,
            committed: [0; MAX_PLAYERS],
            behind: [0; MAX_PLAYERS],
            active: state.active_mask(),
        };
        s.committed[..n].copy_from_slice(state.committed());
        s.behind[..n].copy_from_slice(state.stacks());
        s
    }

    /// The chips after `action` (legal) by the player to act in `state`. No card is dealt
    /// and no bet is returned: what the betting would do next is the value's business.
    pub fn after(state: &State, action: Action) -> Stakes {
        let mut s = Stakes::of(state);
        let seat = state.current_player().expect("someone is to act");
        let bet = state.bets()[seat];
        let added = match action {
            Action::Fold => {
                s.active &= !bit(seat);
                0
            }
            Action::Check => 0,
            Action::Call => (state.max_bet() - bet).min(s.behind[seat]),
            Action::RaiseTo(to) => to - bet,
        };
        s.committed[seat] += added;
        s.behind[seat] -= added;
        s
    }

    /// The chips by contribution level, lowest first: each level's chips and the seats
    /// that paid them (folded seats too: their chips are in the pot).
    fn levels(&self) -> ([(f64, u8); MAX_PLAYERS], usize) {
        let n = self.n;
        let mut sorted = [0; MAX_PLAYERS];
        sorted[..n].copy_from_slice(&self.committed[..n]);
        sorted[..n].sort_unstable();
        let mut out = [(0.0, 0); MAX_PLAYERS];
        let mut len = 0;
        let mut previous = 0;
        for &level in &sorted[..n] {
            if level == previous {
                continue;
            }
            let mut payers = 0;
            for seat in 0..n {
                if self.committed[seat] >= level {
                    payers |= bit(seat);
                }
            }
            out[len] = (((level - previous) * payers.count_ones()) as f64, payers);
            len += 1;
            previous = level;
        }
        (out, len)
    }

    /// Each seat's net result when only one seat is left in: it takes everything.
    fn decided(&self) -> [f64; MAX_PLAYERS] {
        let mut out = [0.0; MAX_PLAYERS];
        let total: Chips = self.committed[..self.n].iter().sum();
        let winner = self.active.trailing_zeros() as usize;
        for seat in 0..self.n {
            out[seat] = -(self.committed[seat] as f64);
        }
        out[winner] += total as f64;
        out
    }

    /// Each seat's average net result over every deal of the cards, with these chips
    /// checked down: each pot is shared evenly between the seats that can win it, since
    /// the deal treats every seat alike.
    pub fn even_shares(&self) -> [f64; MAX_PLAYERS] {
        if self.active.count_ones() <= 1 {
            return self.decided();
        }
        let (levels, len) = self.levels();
        let mut won = [0.0; MAX_PLAYERS];
        share_levels(
            &levels[..len],
            self.active,
            &mut won,
            |eligible, amount, won| {
                let k = eligible.count_ones() as f64;
                for seat in 0..self.n {
                    if eligible & bit(seat) != 0 {
                        won[seat] += amount / k;
                    }
                }
            },
        );
        net(self, &won)
    }
}

/// Pays out `levels`: `pay(eligible, amount, won)` for each pot of chips that `eligible`
/// (the payers still in) can win. Chips of a level nobody still in paid for go to the
/// next level up (they can't be won otherwise; the top level is always paid by someone
/// still in, since a seat folds only to a larger bet).
fn share_levels(
    levels: &[(f64, u8)],
    active: u8,
    won: &mut [f64; MAX_PLAYERS],
    mut pay: impl FnMut(u8, f64, &mut [f64; MAX_PLAYERS]),
) {
    let mut carried = 0.0;
    for &(amount, payers) in levels {
        let eligible = payers & active;
        if eligible == 0 {
            carried += amount;
            continue;
        }
        pay(eligible, amount + carried, won);
        carried = 0.0;
    }
    debug_assert!(carried == 0.0, "the top level is paid by a seat still in");
}

fn net(stakes: &Stakes, won: &[f64; MAX_PLAYERS]) -> [f64; MAX_PLAYERS] {
    let mut out = [0.0; MAX_PLAYERS];
    for seat in 0..stakes.n {
        out[seat] = won[seat] - stakes.committed[seat] as f64;
    }
    out
}

/// The showdowns of every board that can still come (or of a sample of them), for the
/// seats that can still win.
#[derive(Clone, Debug)]
enum Outcomes {
    /// Two seats: how often each wins, and how often they tie.
    Two {
        seats: [usize; 2],
        win: [f64; 2],
        tie: f64,
    },
    /// More seats: each board's hand rank of each seat of `seats` (higher is better).
    Many {
        seats: Vec<usize>,
        ranks: Vec<u16>,
        boards: usize,
    },
}

impl Outcomes {
    /// The showdowns for the seats of `alive`, with `known` board cards of `deal` face up.
    /// The deck is every card not in a hand (folded ones too) and not on the board.
    /// `sample`: draw that many boards from that seed in place of all of them when there
    /// are more.
    fn new(deal: &Deal, n: usize, known: usize, alive: u8, sample: Option<(u32, u64)>) -> Outcomes {
        let seats: Vec<usize> = (0..n).filter(|&s| alive & bit(s) != 0).collect();
        debug_assert!(seats.len() >= 2);
        let holes: Vec<[eval::Card; 2]> =
            seats.iter().map(|&s| deal.hole[s].map(to_eval)).collect();
        let mut dealt = 0u64;
        for seat in 0..n {
            for c in deal.hole[seat] {
                dealt |= 1 << c;
            }
        }
        let mut base = Hand::new();
        for &c in &deal.board[..known] {
            dealt |= 1 << c;
            base = base.add(to_eval(c));
        }
        let mut stub: Vec<eval::Card> = (0..52u8)
            .filter(|&c| dealt & (1 << c) == 0)
            .map(to_eval)
            .collect();
        let missing = 5 - known;
        let mut boards: Vec<Hand> = Vec::new();
        match sample {
            Some((count, seed)) if choose(stub.len() as u64, missing as u64) > count as u64 => {
                let mut rng = Rng::new(seed);
                boards.reserve(count as usize);
                for _ in 0..count {
                    // The first `missing` steps of a Fisher-Yates shuffle: a uniform draw.
                    let mut board = base;
                    for j in 0..missing {
                        let pick = j + below(&mut rng, (stub.len() - j) as u64) as usize;
                        stub.swap(j, pick);
                        board = board.add(stub[j]);
                    }
                    boards.push(board);
                }
            }
            _ => each_board(base, &stub, missing, &mut |b| boards.push(b)),
        }
        if let [a, b] = holes[..] {
            let (mut wins, mut ties) = (0u64, 0u64);
            for board in &boards {
                let mine = board.add(a[0]).add(a[1]).eval7();
                let theirs = board.add(b[0]).add(b[1]).eval7();
                wins += (mine > theirs) as u64;
                ties += (mine == theirs) as u64;
            }
            let total = boards.len() as f64;
            let losses = boards.len() as u64 - wins - ties;
            Outcomes::Two {
                seats: [seats[0], seats[1]],
                win: [wins as f64 / total, losses as f64 / total],
                tie: ties as f64 / total,
            }
        } else {
            let mut ranks = Vec::with_capacity(boards.len() * seats.len());
            for board in &boards {
                for h in &holes {
                    ranks.push(board.add(h[0]).add(h[1]).eval7().value());
                }
            }
            Outcomes::Many {
                seats,
                ranks,
                boards: boards.len(),
            }
        }
    }

    /// Each seat's average net result with these chips checked down. Every seat of
    /// `stakes.active` must be one of the seats the showdowns were made for.
    fn checkdown(&self, stakes: &Stakes) -> [f64; MAX_PLAYERS] {
        if stakes.active.count_ones() <= 1 {
            return stakes.decided();
        }
        let (levels, len) = stakes.levels();
        let levels = &levels[..len];
        let mut won = [0.0; MAX_PLAYERS];
        match self {
            Outcomes::Two { seats, win, tie } => {
                debug_assert_eq!(stakes.active, bit(seats[0]) | bit(seats[1]));
                share_levels(levels, stakes.active, &mut won, |eligible, amount, won| {
                    if eligible.count_ones() == 2 {
                        won[seats[0]] += amount * (win[0] + 0.5 * tie);
                        won[seats[1]] += amount * (win[1] + 0.5 * tie);
                    } else {
                        won[eligible.trailing_zeros() as usize] += amount;
                    }
                });
            }
            Outcomes::Many {
                seats,
                ranks,
                boards,
            } => {
                let k = seats.len();
                for b in 0..*boards {
                    let row = &ranks[b * k..(b + 1) * k];
                    share_levels(levels, stakes.active, &mut won, |eligible, amount, won| {
                        let mut top = 0u16;
                        let mut winners = 0u8;
                        for (j, &seat) in seats.iter().enumerate() {
                            if eligible & bit(seat) == 0 {
                                continue;
                            }
                            if winners == 0 || row[j] > top {
                                top = row[j];
                                winners = bit(seat);
                            } else if row[j] == top {
                                winners |= bit(seat);
                            }
                        }
                        debug_assert_eq!(winners & !eligible, 0);
                        let share = amount / winners.count_ones() as f64;
                        for &seat in seats {
                            if winners & bit(seat) != 0 {
                                won[seat] += share;
                            }
                        }
                    });
                }
                for w in won.iter_mut() {
                    *w /= *boards as f64;
                }
            }
        }
        net(stakes, &won)
    }
}

/// The check-down value of `stakes` on a table of `n` seats dealt `deal`, with its first
/// `known` board cards (0, 3, 4 or 5) face up: each seat's share of the chips, averaged
/// over every board that can still come, minus what it put in. The deck leaves out every
/// hole card, folded ones too. With `sample: Some((boards, seed))`, and when more boards
/// are possible, that many are drawn from the seed in place of all of them.
pub fn checkdown(
    deal: &Deal,
    n: usize,
    known: usize,
    stakes: &Stakes,
    sample: Option<(u32, u64)>,
) -> [f64; MAX_PLAYERS] {
    assert!(matches!(known, 0 | 3 | 4 | 5), "0, 3, 4 or 5 board cards");
    if stakes.active.count_ones() <= 1 {
        return stakes.decided();
    }
    Outcomes::new(deal, n, known, stakes.active, sample).checkdown(stakes)
}

/// Calls `f` with every board made of `base` and `missing` cards of `stub`.
fn each_board(base: Hand, stub: &[eval::Card], missing: usize, f: &mut impl FnMut(Hand)) {
    if missing == 0 {
        f(base);
        return;
    }
    for i in 0..=stub.len() - missing {
        each_board(base.add(stub[i]), &stub[i + 1..], missing - 1, f);
    }
}

/// Which showdowns: the deal, the seats, the board cards face up, the sample.
#[derive(Clone, Copy, PartialEq)]
struct Key {
    deal: Deal,
    n: usize,
    known: usize,
    alive: u8,
    sample: Option<(u32, u64)>,
}

thread_local! {
    /// The showdowns of the deal this thread scored last. The replays of a deal share
    /// their cards, so they share most of these.
    static SHOWDOWNS: RefCell<Vec<(Key, Rc<Outcomes>)>> = const { RefCell::new(Vec::new()) };
}

/// The showdowns one hand needs, by the number of board cards face up.
struct Showdowns {
    deal: Deal,
    n: usize,
    sample: (u32, u64),
    tables: [Option<Rc<Outcomes>>; 6],
}

impl Showdowns {
    fn new(deal: Deal, n: usize, sample: (u32, u64)) -> Showdowns {
        Showdowns {
            deal,
            n,
            sample,
            tables: Default::default(),
        }
    }

    /// The check-down value of `stakes` with `known` board cards face up. `alive` is who
    /// is really still in at this point of the hand (`stakes.active` is within it).
    fn checkdown(&mut self, known: usize, alive: u8, stakes: &Stakes) -> [f64; MAX_PLAYERS] {
        if stakes.active.count_ones() <= 1 {
            return stakes.decided();
        }
        let table = match &self.tables[known] {
            Some(t) => Rc::clone(t),
            None => {
                let key = Key {
                    deal: self.deal,
                    n: self.n,
                    known,
                    alive,
                    sample: (known == 0).then_some(self.sample),
                };
                let t = SHOWDOWNS.with_borrow_mut(|seen| {
                    if seen.first().is_some_and(|(k, _)| k.deal != key.deal) {
                        seen.clear();
                    }
                    if let Some((_, t)) = seen.iter().find(|(k, _)| *k == key) {
                        return Rc::clone(t);
                    }
                    let t = Rc::new(Outcomes::new(&key.deal, key.n, known, alive, key.sample));
                    seen.push((key, Rc::clone(&t)));
                    t
                });
                self.tables[known] = Some(Rc::clone(&t));
                t
            }
        };
        table.checkdown(stakes)
    }
}

impl Aivat {
    /// The value estimate of `stakes`, given how to check chips down (`checkdown`): a bet
    /// still to be answered is called or folded to as [`Aivat::facing`] says, then the
    /// chips are checked down. Exact when only one seat is left in.
    pub fn value(
        &self,
        stakes: &Stakes,
        mut checkdown: impl FnMut(&Stakes) -> [f64; MAX_PLAYERS],
    ) -> [f64; MAX_PLAYERS] {
        if stakes.active.count_ones() <= 1 {
            return stakes.decided();
        }
        let n = stakes.n;
        let top = (0..n)
            .filter(|&s| stakes.active & bit(s) != 0)
            .map(|s| stakes.committed[s])
            .max()
            .unwrap_or(0);
        // The players facing a bet: still in, below the top, with chips behind.
        let mut facing = [(0usize, 0 as Chips, 0.0f64); MAX_PLAYERS];
        let mut count = 0;
        for seat in 0..n {
            let c = stakes.committed[seat];
            if stakes.active & bit(seat) != 0 && c < top && stakes.behind[seat] > 0 {
                let to_call = (top - c).min(stakes.behind[seat]);
                let pot: Chips = stakes.committed[..n].iter().map(|&x| x.min(c)).sum();
                let calls = match self.facing {
                    Facing::MinimumDefense => pot as f64 / (pot + to_call) as f64,
                    Facing::Called | Facing::TakenBack => 1.0,
                };
                facing[count] = (seat, to_call, calls);
                count += 1;
            }
        }
        if count == 0 || self.facing == Facing::TakenBack {
            return checkdown(stakes);
        }
        let mut out = [0.0; MAX_PLAYERS];
        for callers in 0..1u32 << count {
            let mut p = 1.0;
            let mut s = *stakes;
            for (k, &(seat, to_call, calls)) in facing[..count].iter().enumerate() {
                if callers & (1 << k) != 0 {
                    p *= calls;
                    s.committed[seat] += to_call;
                    s.behind[seat] -= to_call;
                } else {
                    p *= 1.0 - calls;
                    s.active &= !bit(seat);
                }
            }
            if p == 0.0 {
                continue;
            }
            let v = if s.active.count_ones() <= 1 {
                s.decided()
            } else {
                checkdown(&s)
            };
            for seat in 0..n {
                out[seat] += p * v[seat];
            }
        }
        out
    }

    /// A short name for the report.
    pub fn describe(&self) -> String {
        format!(
            "AIVAT (check-down values, bets valued as {} or by the known answers, {} boards \
             before the flop)",
            self.facing.name(),
            self.boards
        )
    }

    /// Scores one finished hand: its real result minus the corrections for the deal, every
    /// board card, and every action whose chances were reported (see the module notes).
    pub fn score_hand(&self, hand: &HandRecord<'_>) -> AivatHand {
        self.score_hand_with(hand, None)
    }

    /// [`Aivat::score_hand`], valuing each action a player could have taken by the answers
    /// the next player to act would give to it, when that player can say
    /// ([`Player::chances_at`]). `players[seat]` is the player of each seat. A match scores
    /// this way.
    pub fn score_hand_with(
        &self,
        hand: &HandRecord<'_>,
        players: Option<&[Box<dyn Player>]>,
    ) -> AivatHand {
        let fin = hand.state;
        let n = fin.num_players();
        let config = Config::new(
            fin.starting_stacks(),
            fin.small_blind(),
            fin.big_blind(),
            fin.ante(),
            fin.button(),
        )
        .expect("the hand was played on this table");
        let deal = *fin.deal();
        let mut state = State::new(&config, deal).expect("the hand was dealt from this deal");
        let mut showdowns = Showdowns::new(deal, n, (self.boards, mix(hand.seed, 0xA17A7)));
        let mut out = AivatHand::default();
        let mut luck = [0.0; MAX_PLAYERS];
        let add =
            |luck: &mut [f64; MAX_PLAYERS], a: &[f64; MAX_PLAYERS], b: &[f64; MAX_PLAYERS]| {
                for seat in 0..n {
                    luck[seat] += a[seat] - b[seat];
                }
            };

        // The deal: its value against the average over every deal.
        let root = Stakes::of(&state);
        let alive = state.active_mask();
        let dealt = self.value(&root, |s| showdowns.checkdown(0, alive, s));
        let average = self.value(&root, Stakes::even_shares);
        add(&mut luck, &dealt, &average);

        let mut known = 0;
        let mut answers = Vec::new();
        self.cards(&state, &mut known, &mut showdowns, &mut luck);
        for (t, m) in fin.history().iter().enumerate() {
            let seat = m.seat as usize;
            match hand.decisions.get(t) {
                None => out.unknown[seat] += 1,
                Some(chances) => match self.choice(
                    &state,
                    m.action,
                    chances,
                    known,
                    &mut showdowns,
                    players,
                    &mut answers,
                ) {
                    Some(correction) => {
                        for s in 0..n {
                            luck[s] += correction[s];
                        }
                        out.corrected[seat] += 1;
                    }
                    None => out.unexplained[seat] += 1,
                },
            }
            state.apply(m.action).expect("the history is legal");
            self.cards(&state, &mut known, &mut showdowns, &mut luck);
        }
        for seat in 0..n {
            out.scores[seat] = hand.payouts[seat] as f64 - luck[seat];
        }
        out
    }

    /// The corrections for the board cards that came since `known` were face up: for each
    /// street, the check-down value with its cards against the average over all of them.
    fn cards(
        &self,
        state: &State,
        known: &mut usize,
        showdowns: &mut Showdowns,
        luck: &mut [f64; MAX_PLAYERS],
    ) {
        let face_up = state.street().board_len();
        if face_up == *known {
            return;
        }
        let stakes = Stakes::of(state);
        let alive = state.active_mask();
        while *known < face_up {
            let next = if *known == 0 { 3 } else { *known + 1 };
            let after = showdowns.checkdown(next, alive, &stakes);
            let before = showdowns.checkdown(*known, alive, &stakes);
            for seat in 0..stakes.n {
                luck[seat] += after[seat] - before[seat];
            }
            *known = next;
        }
    }

    /// The correction for `action`, taken in `state` by a player that reported `chances`,
    /// or `None` when the chances can't be the ones it was drawn with.
    fn choice(
        &self,
        state: &State,
        action: Action,
        chances: &[(Action, f64)],
        known: usize,
        showdowns: &mut Showdowns,
        players: Option<&[Box<dyn Player>]>,
        answers: &mut Vec<(Action, f64)>,
    ) -> Option<[f64; MAX_PLAYERS]> {
        let merged = merge(state, chances)?;
        if !merged.iter().any(|(a, _)| *a == action) {
            return None;
        }
        let alive = state.active_mask();
        let n = state.num_players();
        let mut value = |a: Action| {
            if let Some(v) =
                players.and_then(|p| self.answered(state, a, known, alive, showdowns, p, answers))
            {
                return v;
            }
            self.value(&Stakes::after(state, a), |s| {
                showdowns.checkdown(known, alive, s)
            })
        };
        let taken = value(action);
        let mut correction = taken;
        for &(a, w) in &merged {
            let v = if a == action { taken } else { value(a) };
            for seat in 0..n {
                correction[seat] -= w * v[seat];
            }
        }
        Some(correction)
    }

    /// The value of `action` in `state` averaged over the answers of the next player to
    /// act, when the betting goes on in this street and that player says what it would
    /// play ([`Player::chances_at`]); `None` otherwise.
    #[allow(clippy::too_many_arguments)]
    fn answered(
        &self,
        state: &State,
        action: Action,
        known: usize,
        alive: u8,
        showdowns: &mut Showdowns,
        players: &[Box<dyn Player>],
        answers: &mut Vec<(Action, f64)>,
    ) -> Option<[f64; MAX_PLAYERS]> {
        let mut next = state.clone();
        next.apply(action).ok()?;
        if next.street() != state.street() {
            return None;
        }
        let seat = next.current_player()?;
        answers.clear();
        if !players[seat].chances_at(&View::new(&next, seat, 0), answers) {
            return None;
        }
        let merged = merge(&next, answers)?;
        let mut out = [0.0; MAX_PLAYERS];
        for &(a, w) in &merged {
            let v = self.value(&Stakes::after(&next, a), |s| {
                showdowns.checkdown(known, alive, s)
            });
            for s in 0..state.num_players() {
                out[s] += w * v[s];
            }
        }
        Some(out)
    }
}

/// `chances` with weights not above 0 left out, duplicates merged and the rest scaled to
/// add up to 1; `None` when one of them is not legal in `state` or none is left.
fn merge(state: &State, chances: &[(Action, f64)]) -> Option<Vec<(Action, f64)>> {
    let legal = state.legal_actions();
    let mut merged: Vec<(Action, f64)> = Vec::with_capacity(chances.len());
    for &(a, w) in chances {
        if !(w > 0.0) {
            continue;
        }
        if !legal.allows(a) {
            return None;
        }
        match merged.iter_mut().find(|(b, _)| *b == a) {
            Some(slot) => slot.1 += w,
            None => merged.push((a, w)),
        }
    }
    let total: f64 = merged.iter().map(|x| x.1).sum();
    if !(total > 0.0 && total.is_finite()) {
        return None;
    }
    for x in &mut merged {
        x.1 /= total;
    }
    Some(merged)
}

impl Scorer for Aivat {
    fn name(&self) -> String {
        self.describe()
    }

    fn score(&self, hand: &HandRecord<'_>, scores: &mut [f64]) {
        let scored = self.score_hand(hand);
        scores.copy_from_slice(&scored.scores[..scores.len()]);
    }
}
