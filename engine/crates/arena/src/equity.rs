//! Showdown pots and all-in equity.
//!
//! When the betting ends before the river with players all in, the rest of the board is
//! pure luck. [`all_in_equity`] replaces that luck by its average: each seat's payout
//! averaged over every board that could still come.
//!
//! The average is taken over the cards really left in the deck: the hole cards of every
//! seat are out of it, the folded ones too. Given all the cards dealt and all the
//! actions, each remaining board is equally likely, so the average is exactly the
//! expected payout and scoring it in place of the real payout changes no agent's
//! expected result. (Leaving the folded cards in the deck, as hand trackers must, would
//! be slightly off: players fold weak cards more often than strong ones.)

use eval::Hand;
use nlhe::{Chips, Rng, State, MAX_PLAYERS};

use crate::ranker::to_eval;

const fn bit(seat: usize) -> u8 {
    1 << seat
}

/// The pots of a hand whose betting is over, ready to pay any showdown.
///
/// The same rules as the nlhe engine, which keeps its own version private: pots by
/// contribution level, hands that cannot win any pot are killed and the pots formed
/// again without them, each pot is split between its best hands and the odd chips go to
/// the first winner clockwise from the button. The tests check it against the engine.
#[derive(Clone, Debug)]
pub struct Pots {
    n: usize,
    button: usize,
    /// Seats that have not folded.
    active: u8,
    /// One entry per contribution level above zero, lowest first: the chips at that level
    /// and the seats that paid them.
    levels: [(Chips, u8); MAX_PLAYERS],
    num_levels: usize,
    /// When every level has the same contenders: all the chips, and those contenders.
    single: Option<(Chips, u8)>,
}

impl Pots {
    /// `committed[seat]` is what each seat put in over the whole hand (uncalled bets
    /// already returned), `active` the seats that have not folded.
    pub fn new(committed: &[Chips], active: u8, button: usize) -> Pots {
        let n = committed.len();
        assert!((2..=MAX_PLAYERS).contains(&n) && button < n);
        let mut sorted = [0; MAX_PLAYERS];
        sorted[..n].copy_from_slice(committed);
        sorted[..n].sort_unstable();
        let mut levels = [(0, 0); MAX_PLAYERS];
        let mut num_levels = 0;
        let mut previous = 0;
        for &level in &sorted[..n] {
            if level == previous {
                continue;
            }
            let mut payers = 0;
            for seat in 0..n {
                if committed[seat] >= level {
                    payers |= bit(seat);
                }
            }
            levels[num_levels] = ((level - previous) * payers.count_ones(), payers);
            num_levels += 1;
            previous = level;
        }
        let mut pots = Pots {
            n,
            button,
            active,
            levels,
            num_levels,
            single: None,
        };
        let (formed, len) = pots.form(active);
        if len == 1 {
            pots.single = Some(formed[0]);
        }
        pots
    }

    /// The pots of a finished hand.
    pub fn of(state: &State) -> Pots {
        Pots::new(state.committed(), state.active_mask(), state.button())
    }

    /// All the chips in the middle.
    pub fn total(&self) -> Chips {
        self.levels[..self.num_levels].iter().map(|l| l.0).sum()
    }

    /// The pots when only `contenders` can win: neighbouring levels with the same
    /// contenders are one pot.
    fn form(&self, contenders: u8) -> ([(Chips, u8); MAX_PLAYERS], usize) {
        let mut out = [(0, 0); MAX_PLAYERS];
        let mut len = 0;
        for &(chips, payers) in &self.levels[..self.num_levels] {
            let eligible = payers & contenders;
            let mut amount = chips;
            while len > 0 && out[len - 1].1 == eligible {
                len -= 1;
                amount += out[len].0;
            }
            out[len] = (amount, eligible);
            len += 1;
        }
        (out, len)
    }

    /// Splits `amount` evenly between `winners`; the odd chips go to the first of them
    /// clockwise from the button.
    fn split(&self, amount: Chips, winners: u8, won: &mut [Chips; MAX_PLAYERS]) {
        let k = winners.count_ones();
        if k == 0 {
            return;
        }
        let mut extra = amount % k;
        for j in 1..=self.n {
            let seat = (self.button + j) % self.n;
            if winners & bit(seat) != 0 {
                won[seat] += amount / k + extra;
                extra = 0;
            }
        }
    }

    /// Chips each seat takes from the pots, given each active seat's hand rank (higher
    /// is better, equal ties). Ranks of folded seats are ignored.
    pub fn winnings(&self, ranks: &[u32; MAX_PLAYERS]) -> [Chips; MAX_PLAYERS] {
        let mut won = [0; MAX_PLAYERS];
        if self.active.count_ones() == 1 {
            won[self.active.trailing_zeros() as usize] = self.total();
            return won;
        }
        let (pots, len) = self.form(self.active);
        let mut alive = 0;
        for &(_, eligible) in &pots[..len] {
            alive |= best(ranks, eligible);
        }
        let (pots, len) = self.form(alive);
        for &(amount, eligible) in &pots[..len] {
            self.split(amount, best(ranks, eligible), &mut won);
        }
        won
    }
}

/// The seats of `mask` holding its best rank.
fn best(ranks: &[u32; MAX_PLAYERS], mask: u8) -> u8 {
    let mut top = 0;
    let mut winners = 0;
    for seat in 0..MAX_PLAYERS {
        if mask & bit(seat) == 0 {
            continue;
        }
        if winners == 0 || ranks[seat] > top {
            top = ranks[seat];
            winners = bit(seat);
        } else if ranks[seat] == top {
            winners |= bit(seat);
        }
    }
    winners
}

/// If the hand went to a showdown with board cards dealt after the last decision (the
/// players were all in, or only one had chips left): the number of board cards that
/// were face up when the betting ended, 0, 3 or 4. Otherwise `None`.
pub fn all_in_runout(state: &State) -> Option<usize> {
    if !state.is_terminal() || state.active_mask().count_ones() < 2 {
        return None;
    }
    // No action at all means the blinds or antes put everyone all in.
    let known = state.history().last().map_or(0, |m| m.street.board_len());
    (known < 5).then_some(known)
}

/// Counts the showdown results over many boards.
struct Tally<'a> {
    pots: &'a Pots,
    /// The seats that can win, with their hole cards.
    seats: [(usize, eval::Card, eval::Card); MAX_PLAYERS],
    num_seats: usize,
    /// One pot: how many boards each set of winners took it.
    by_winners: [u64; 1 << MAX_PLAYERS],
    /// Several pots: chips won per seat, summed over the boards.
    won: [u64; MAX_PLAYERS],
    boards: u64,
}

impl Tally<'_> {
    /// Adds the boards made of `base` (4 board cards) and each card of `last` in turn.
    /// Working a row at a time keeps the counts of the inner loop out of memory.
    #[inline(always)]
    fn add_row(&mut self, base: Hand, last: &[eval::Card]) {
        self.boards += last.len() as u64;
        let seats = &self.seats[..self.num_seats];
        if self.pots.single.is_none() {
            for &c in last {
                let board = base.add(c);
                let mut ranks = [0u32; MAX_PLAYERS];
                for &(seat, a, b) in seats {
                    ranks[seat] = board.add(a).add(b).eval7().value() as u32;
                }
                let won = self.pots.winnings(&ranks);
                for seat in 0..self.pots.n {
                    self.won[seat] += won[seat] as u64;
                }
            }
        } else if let [(first, a, b), (second, c, d)] = *seats {
            // Two hands and one pot, the usual case: count without branching.
            let (mut wins, mut ties) = (0u64, 0u64);
            for &card in last {
                let board = base.add(card);
                let mine = board.add(a).add(b).eval7();
                let theirs = board.add(c).add(d).eval7();
                wins += (mine > theirs) as u64;
                ties += (mine == theirs) as u64;
            }
            self.by_winners[bit(first) as usize] += wins;
            self.by_winners[(bit(first) | bit(second)) as usize] += ties;
            self.by_winners[bit(second) as usize] += last.len() as u64 - wins - ties;
        } else {
            for &card in last {
                let board = base.add(card);
                let mut ranks = [0u16; MAX_PLAYERS];
                let mut top = 0;
                for (i, &(_, a, b)) in seats.iter().enumerate() {
                    ranks[i] = board.add(a).add(b).eval7().value();
                    top = top.max(ranks[i]);
                }
                let mut winners = 0;
                for (i, &(seat, _, _)) in seats.iter().enumerate() {
                    winners |= ((ranks[i] == top) as usize) << seat;
                }
                self.by_winners[winners] += 1;
            }
        }
    }
}

/// Calls `f` for every way to add `missing - 1` cards of `stub` to `base`, with the
/// cards that can still follow as the last one: together, every set of `missing` cards.
fn each_row<F: FnMut(Hand, &[eval::Card])>(
    base: Hand,
    stub: &[eval::Card],
    missing: usize,
    f: &mut F,
) {
    if missing == 1 {
        f(base, stub);
        return;
    }
    for i in 0..=stub.len() - missing {
        each_row(base.add(stub[i]), &stub[i + 1..], missing - 1, f);
    }
}

/// A uniform integer in `0..n` with one multiplication in place of a division (Lemire's
/// method, with its rejection step, so there is no bias).
#[inline]
fn below(rng: &mut Rng, n: u64) -> u64 {
    let mut m = rng.next_u64() as u128 * n as u128;
    if (m as u64) < n {
        let threshold = n.wrapping_neg() % n;
        while (m as u64) < threshold {
            m = rng.next_u64() as u128 * n as u128;
        }
    }
    (m >> 64) as u64
}

fn choose(n: u64, k: u64) -> u64 {
    (0..k).fold(1, |acc, i| acc * (n - i) / (i + 1))
}

/// The expected result of each seat, in chips, over every board that could still come
/// after the betting ended. `None` when no board card was dealt after the last decision
/// (see [`all_in_runout`]): then the real payout stands.
///
/// With `sample: Some((boards, seed))`, and when more than `boards` boards are possible,
/// that many are drawn at random from the seed in place of all of them. The result is
/// then an estimate with no bias, and far cheaper before the flop (1,712,304 boards
/// heads-up, 658,008 six-handed).
pub fn all_in_equity(state: &State, sample: Option<(u32, u64)>) -> Option<[f64; MAX_PLAYERS]> {
    let known = all_in_runout(state)?;
    let n = state.num_players();
    let deal = state.deal();
    let pots = Pots::of(state);

    // The deck: every card not in a hand (folded hands included) and not on the board.
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
    let mut stub = [to_eval(0); 52];
    let mut stub_len = 0;
    for c in 0..52u8 {
        if dealt & (1 << c) == 0 {
            stub[stub_len] = to_eval(c);
            stub_len += 1;
        }
    }
    let stub = &mut stub[..stub_len];
    let missing = 5 - known;

    let can_win = match pots.single {
        Some((_, contenders)) => contenders,
        None => state.active_mask(),
    };
    let mut tally = Tally {
        pots: &pots,
        seats: [(0, stub[0], stub[0]); MAX_PLAYERS],
        num_seats: 0,
        by_winners: [0; 1 << MAX_PLAYERS],
        won: [0; MAX_PLAYERS],
        boards: 0,
    };
    for seat in 0..n {
        if can_win & bit(seat) != 0 {
            let [a, b] = deal.hole[seat];
            tally.seats[tally.num_seats] = (seat, to_eval(a), to_eval(b));
            tally.num_seats += 1;
        }
    }

    match sample {
        Some((boards, seed)) if choose(stub_len as u64, missing as u64) > boards as u64 => {
            let mut rng = Rng::new(seed);
            for _ in 0..boards {
                // The first `missing` steps of a Fisher-Yates shuffle: a uniform draw.
                let mut board = base;
                for j in 0..missing {
                    let pick = j + below(&mut rng, (stub_len - j) as u64) as usize;
                    stub.swap(j, pick);
                    if j + 1 < missing {
                        board = board.add(stub[j]);
                    }
                }
                tally.add_row(board, &stub[missing - 1..missing]);
            }
        }
        _ => each_row(base, stub, missing, &mut |board, last| {
            tally.add_row(board, last)
        }),
    }

    if let Some((amount, _)) = pots.single {
        for winners in 1..tally.by_winners.len() {
            let count = tally.by_winners[winners];
            if count > 0 {
                let mut won = [0; MAX_PLAYERS];
                pots.split(amount, winners as u8, &mut won);
                for seat in 0..n {
                    tally.won[seat] += won[seat] as u64 * count;
                }
            }
        }
    }
    let committed = state.committed();
    let mut expected = [0.0; MAX_PLAYERS];
    for seat in 0..n {
        expected[seat] = tally.won[seat] as f64 / tally.boards as f64 - committed[seat] as f64;
    }
    Some(expected)
}
