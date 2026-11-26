//! The rules: blinds and antes, betting, the order of play, side pots and payouts.

use std::fmt;

use crate::cards::{Card, Deal, DealError};
use crate::history::{History, Move};
use crate::ranker::HandRanker;
use crate::{Chips, MAX_PLAYERS};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(u8)]
pub enum Street {
    Preflop = 0,
    Flop = 1,
    Turn = 2,
    River = 3,
}

impl Street {
    pub const ALL: [Street; 4] = [Street::Preflop, Street::Flop, Street::Turn, Street::River];

    pub fn index(self) -> usize {
        self as usize
    }

    /// How many board cards are face up on this street.
    pub fn board_len(self) -> usize {
        [0, 3, 4, 5][self as usize]
    }

    fn next(self) -> Street {
        match self {
            Street::Preflop => Street::Flop,
            Street::Flop => Street::Turn,
            Street::Turn | Street::River => Street::River,
        }
    }
}

/// A player action.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Action {
    Fold,
    Check,
    /// Match the largest bet, or put in the whole stack if it is smaller.
    Call,
    /// Bet or raise so that this street's bet becomes the amount (a total, not an increment).
    RaiseTo(Chips),
}

impl fmt::Display for Action {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Action::Fold => write!(f, "fold"),
            Action::Check => write!(f, "check"),
            Action::Call => write!(f, "call"),
            Action::RaiseTo(a) => write!(f, "raise to {a}"),
        }
    }
}

/// The amounts a raise may go to: any whole number in `min_to..=max_to`.
/// `max_to` is always the player's whole stack (all in). When the stack is too small for
/// a full raise, `min_to == max_to`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RaiseRange {
    pub min_to: Chips,
    pub max_to: Chips,
}

/// What the current player may do.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct LegalActions {
    /// Folding is allowed only when there is something to call.
    pub fold: bool,
    pub check: bool,
    /// The chips a call would put in, when there is a bet to call.
    pub call: Option<Chips>,
    pub raise: Option<RaiseRange>,
}

impl LegalActions {
    pub fn allows(&self, action: Action) -> bool {
        match action {
            Action::Fold => self.fold,
            Action::Check => self.check,
            Action::Call => self.call.is_some(),
            Action::RaiseTo(a) => self.raise.is_some_and(|r| r.min_to <= a && a <= r.max_to),
        }
    }
}

/// The table before the cards are dealt.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Config {
    num_players: u8,
    button: u8,
    small_blind: Chips,
    big_blind: Chips,
    ante: Chips,
    stacks: [Chips; MAX_PLAYERS],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConfigError {
    /// Fewer than 2 or more than 6 players.
    PlayerCount(usize),
    /// A seat has no chips.
    EmptyStack(usize),
    /// The big blind must be at least 1 chip.
    NoBigBlind,
    /// The small blind is larger than the big blind.
    SmallBlindTooBig,
    /// The button is not one of the seats.
    Button(usize),
    /// The chips on the table do not fit in a `Chips`.
    TooManyChips,
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConfigError::PlayerCount(n) => write!(f, "{n} players; the engine takes 2 to 6"),
            ConfigError::EmptyStack(s) => write!(f, "seat {s} has no chips"),
            ConfigError::NoBigBlind => write!(f, "the big blind must be at least 1 chip"),
            ConfigError::SmallBlindTooBig => {
                write!(f, "the small blind is larger than the big blind")
            }
            ConfigError::Button(b) => write!(f, "the button {b} is not a seat"),
            ConfigError::TooManyChips => write!(f, "the chips on the table overflow"),
        }
    }
}

impl std::error::Error for ConfigError {}

impl Config {
    /// `stacks[s]` is seat `s`'s stack. Seats go clockwise: the small blind is the seat
    /// after the button, the big blind the one after that. Heads-up, the button is the small
    /// blind. `ante` is posted by every player (0 for none).
    pub fn new(
        stacks: &[Chips],
        small_blind: Chips,
        big_blind: Chips,
        ante: Chips,
        button: usize,
    ) -> Result<Config, ConfigError> {
        let n = stacks.len();
        if !(2..=MAX_PLAYERS).contains(&n) {
            return Err(ConfigError::PlayerCount(n));
        }
        if let Some(s) = stacks.iter().position(|&x| x == 0) {
            return Err(ConfigError::EmptyStack(s));
        }
        if big_blind == 0 {
            return Err(ConfigError::NoBigBlind);
        }
        if small_blind > big_blind {
            return Err(ConfigError::SmallBlindTooBig);
        }
        if button >= n {
            return Err(ConfigError::Button(button));
        }
        if stacks
            .iter()
            .try_fold(0 as Chips, |acc, &s| acc.checked_add(s))
            .is_none()
        {
            return Err(ConfigError::TooManyChips);
        }
        let mut st = [0; MAX_PLAYERS];
        st[..n].copy_from_slice(stacks);
        Ok(Config {
            num_players: n as u8,
            button: button as u8,
            small_blind,
            big_blind,
            ante,
            stacks: st,
        })
    }

    pub fn num_players(&self) -> usize {
        self.num_players as usize
    }
    pub fn button(&self) -> usize {
        self.button as usize
    }
    pub fn small_blind(&self) -> Chips {
        self.small_blind
    }
    pub fn big_blind(&self) -> Chips {
        self.big_blind
    }
    pub fn ante(&self) -> Chips {
        self.ante
    }
    pub fn stacks(&self) -> &[Chips] {
        &self.stacks[..self.num_players as usize]
    }

    /// The small blind seat: the button heads-up, otherwise the seat after it.
    pub fn small_blind_seat(&self) -> usize {
        let n = self.num_players();
        if n == 2 {
            self.button()
        } else {
            (self.button() + 1) % n
        }
    }

    pub fn big_blind_seat(&self) -> usize {
        (self.small_blind_seat() + 1) % self.num_players()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ActionError {
    /// The hand is over.
    HandOver,
    /// The action is not among the legal actions.
    Illegal(Action),
}

impl fmt::Display for ActionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ActionError::HandOver => write!(f, "the hand is over"),
            ActionError::Illegal(a) => write!(f, "{a} is not legal here"),
        }
    }
}

impl std::error::Error for ActionError {}

/// A main or side pot: its chips and the seats that can win it (a bit mask by seat).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Pot {
    pub amount: Chips,
    pub eligible: u8,
}

/// Up to one pot per distinct contribution level, so at most `MAX_PLAYERS + 1`.
#[derive(Clone, Copy, Debug)]
pub struct Pots {
    len: usize,
    pots: [Pot; MAX_PLAYERS + 1],
}

impl Pots {
    pub fn as_slice(&self) -> &[Pot] {
        &self.pots[..self.len]
    }
}

/// One hand of No-Limit Hold'em, from the blinds to the payouts.
///
/// No heap memory unless a hand runs past [`crate::history::INLINE_MOVES`] actions, so
/// `clone` is a copy of a few hundred bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct State {
    n: u8,
    button: u8,
    sb_seat: u8,
    bb_seat: u8,
    small_blind: Chips,
    big_blind: Chips,
    ante: Chips,
    starting: [Chips; MAX_PLAYERS],
    stacks: [Chips; MAX_PLAYERS],
    /// Chips bet on the current street, not yet in the pot.
    bets: [Chips; MAX_PLAYERS],
    /// Everything each seat has put in this hand, including `bets`.
    committed: [Chips; MAX_PLAYERS],
    max_bet: Chips,
    /// The size of a full raise on this street: the big blind, or the last full raise.
    full_raise: Chips,
    folded: u8,
    /// Seats that acted on this street since the last full raise.
    acted: u8,
    /// Seats still to act in this betting round.
    pending: u8,
    actor: u8,
    street: Street,
    terminal: bool,
    deal: Deal,
    history: History,
}

const fn bit(seat: usize) -> u8 {
    1 << seat
}

impl State {
    /// Posts the antes and blinds and starts the preflop betting.
    pub fn new(config: &Config, deal: Deal) -> Result<State, DealError> {
        let n = config.num_players();
        let mut seen = 0u64;
        for &c in deal.hole[..n].iter().flatten().chain(deal.board.iter()) {
            if c >= 52 {
                return Err(DealError::BadCard(c));
            }
            if seen & (1 << c) != 0 {
                return Err(DealError::Duplicate(c));
            }
            seen |= 1 << c;
        }
        let mut s = State {
            n: n as u8,
            button: config.button,
            sb_seat: config.small_blind_seat() as u8,
            bb_seat: config.big_blind_seat() as u8,
            small_blind: config.small_blind,
            big_blind: config.big_blind,
            ante: config.ante,
            starting: config.stacks,
            stacks: config.stacks,
            bets: [0; MAX_PLAYERS],
            committed: [0; MAX_PLAYERS],
            max_bet: 0,
            full_raise: config.big_blind,
            folded: 0,
            acted: 0,
            pending: 0,
            actor: 0,
            street: Street::Preflop,
            terminal: false,
            deal,
            history: History::new(),
        };

        // Antes go in first. A player short of the ante posts what they have, and the part
        // of the largest ante nobody else matched goes back.
        let mut posted_ante = [0; MAX_PLAYERS];
        if s.ante > 0 {
            for i in 0..n {
                posted_ante[i] = s.ante.min(s.stacks[i]);
                s.put(i, posted_ante[i]);
            }
            s.collect();
        }

        // Blinds. A player who cannot cover a blind posts what is left after the ante.
        for (seat, blind) in [
            (s.sb_seat as usize, s.small_blind),
            (s.bb_seat as usize, s.big_blind),
        ] {
            let amount = blind.min(s.starting[seat] - posted_ante[seat]);
            s.put(seat, amount);
        }
        s.max_bet = s.bets[..n].iter().copied().max().unwrap_or(0);

        if !s.begin_round(Street::Preflop) {
            s.finish_round();
        }
        Ok(s)
    }

    /// A state dealt from a seed with [`Deal::from_seed`].
    pub fn from_seed(config: &Config, seed: u64) -> State {
        let deal = Deal::from_seed(seed, config.num_players(), config.button());
        State::new(config, deal).expect("a seeded deal is always valid")
    }

    // ----- reading the state -----

    pub fn num_players(&self) -> usize {
        self.n as usize
    }
    pub fn button(&self) -> usize {
        self.button as usize
    }
    pub fn small_blind_seat(&self) -> usize {
        self.sb_seat as usize
    }
    pub fn big_blind_seat(&self) -> usize {
        self.bb_seat as usize
    }
    pub fn big_blind(&self) -> Chips {
        self.big_blind
    }
    pub fn small_blind(&self) -> Chips {
        self.small_blind
    }
    pub fn ante(&self) -> Chips {
        self.ante
    }
    pub fn street(&self) -> Street {
        self.street
    }
    pub fn is_terminal(&self) -> bool {
        self.terminal
    }

    /// The seat to act, or `None` when the hand is over.
    pub fn current_player(&self) -> Option<usize> {
        (!self.terminal).then_some(self.actor as usize)
    }

    pub fn starting_stacks(&self) -> &[Chips] {
        &self.starting[..self.n as usize]
    }
    /// Chips behind (not bet) for each seat.
    pub fn stacks(&self) -> &[Chips] {
        &self.stacks[..self.n as usize]
    }
    /// This street's bets.
    pub fn bets(&self) -> &[Chips] {
        &self.bets[..self.n as usize]
    }
    /// Everything each seat has put in this hand, this street's bets included.
    pub fn committed(&self) -> &[Chips] {
        &self.committed[..self.n as usize]
    }
    /// All chips in the middle, this street's bets included.
    pub fn pot(&self) -> Chips {
        self.committed().iter().sum()
    }
    pub fn max_bet(&self) -> Chips {
        self.max_bet
    }
    /// The smallest raise increment on this street (the big blind or the last full raise).
    pub fn full_raise(&self) -> Chips {
        self.full_raise
    }
    pub fn is_folded(&self, seat: usize) -> bool {
        self.folded & bit(seat) != 0
    }
    pub fn is_all_in(&self, seat: usize) -> bool {
        !self.is_folded(seat) && self.stacks[seat] == 0
    }
    /// Seats that have not folded, as a bit mask.
    pub fn active_mask(&self) -> u8 {
        self.all_mask() & !self.folded
    }
    pub fn hole_cards(&self, seat: usize) -> [Card; 2] {
        self.deal.hole[seat]
    }
    /// The board cards face up so far. After an all-in the board runs out to five cards.
    pub fn board(&self) -> &[Card] {
        &self.deal.board[..self.street.board_len()]
    }
    pub fn deal(&self) -> &Deal {
        &self.deal
    }
    /// Every player action so far, in order.
    pub fn history(&self) -> &[Move] {
        self.history.as_slice()
    }

    /// What the current player may do (nothing once the hand is over).
    pub fn legal_actions(&self) -> LegalActions {
        if self.terminal {
            return LegalActions::default();
        }
        let i = self.actor as usize;
        let to_call = self.max_bet - self.bets[i];
        LegalActions {
            fold: to_call > 0,
            check: to_call == 0,
            call: (to_call > 0).then(|| to_call.min(self.stacks[i])),
            raise: self.raise_range(i),
        }
    }

    fn raise_range(&self, i: usize) -> Option<RaiseRange> {
        let to_call = self.max_bet - self.bets[i];
        if self.stacks[i] <= to_call {
            return None; // calling already puts them all in
        }
        let someone_can_answer = (0..self.n as usize)
            .any(|j| j != i && !self.is_folded(j) && self.stacks[j] + self.bets[j] > self.max_bet);
        if !someone_can_answer {
            return None;
        }
        // An all-in below a full raise does not reopen the betting for a player who already
        // acted: they may raise again only once the bet has gone up by a full raise in
        // total since their last action.
        if self.acted & bit(i) != 0 && to_call < self.full_raise {
            return None;
        }
        let all_in = self.stacks[i] + self.bets[i];
        Some(RaiseRange {
            min_to: all_in.min(self.max_bet + self.full_raise),
            max_to: all_in,
        })
    }

    // ----- playing -----

    /// Applies the current player's action. Returns an error, and changes nothing, if the
    /// action is not legal.
    pub fn apply(&mut self, action: Action) -> Result<(), ActionError> {
        if self.terminal {
            return Err(ActionError::HandOver);
        }
        if !self.legal_actions().allows(action) {
            return Err(ActionError::Illegal(action));
        }
        let i = self.actor as usize;
        let b = bit(i);
        let added = match action {
            Action::Fold => {
                self.folded |= b;
                0
            }
            Action::Check => {
                self.acted |= b;
                0
            }
            Action::Call => {
                let amount = (self.max_bet - self.bets[i]).min(self.stacks[i]);
                self.put(i, amount);
                self.acted |= b;
                amount
            }
            Action::RaiseTo(to) => {
                let added = to - self.bets[i];
                let increment = to - self.max_bet;
                self.put(i, added);
                self.max_bet = to;
                if increment >= self.full_raise {
                    self.full_raise = increment;
                    self.acted = b;
                } else {
                    self.acted |= b;
                }
                // everyone else still in with chips behind gets to answer
                self.pending = self.active_mask() & self.with_chips_mask();
                added
            }
        };
        self.pending &= !b;
        self.history.push(Move {
            street: self.street,
            seat: i as u8,
            action,
            added,
        });

        if self.pending == 0 || self.active_mask().count_ones() <= 1 {
            self.finish_round();
        } else {
            self.actor = self.first_in(self.pending, i + 1) as u8;
        }
        Ok(())
    }

    /// Final stacks once the hand is over (`None` before). Showdowns use the ranker.
    pub fn final_stacks<R: HandRanker>(&self, ranker: &R) -> Option<[Chips; MAX_PLAYERS]> {
        if !self.terminal {
            return None;
        }
        let won = self.winnings(ranker);
        let mut out = [0; MAX_PLAYERS];
        for i in 0..self.n as usize {
            out[i] = self.stacks[i] + won[i];
        }
        Some(out)
    }

    /// Net result per seat once the hand is over: final stack minus starting stack.
    pub fn payouts<R: HandRanker>(&self, ranker: &R) -> Option<[i64; MAX_PLAYERS]> {
        let fin = self.final_stacks(ranker)?;
        let mut out = [0; MAX_PLAYERS];
        for i in 0..self.n as usize {
            out[i] = fin[i] as i64 - self.starting[i] as i64;
        }
        Some(out)
    }

    /// The main and side pots from what everyone has put in, with the seats that have not
    /// folded as the contenders.
    pub fn pots(&self) -> Pots {
        self.pots_for(self.active_mask())
    }

    // ----- internals -----

    fn all_mask(&self) -> u8 {
        ((1u16 << self.n) - 1) as u8
    }

    fn with_chips_mask(&self) -> u8 {
        let mut m = 0;
        for i in 0..self.n as usize {
            if self.stacks[i] > 0 {
                m |= bit(i);
            }
        }
        m
    }

    /// The first seat in `mask` going clockwise from `from` (inclusive).
    fn first_in(&self, mask: u8, from: usize) -> usize {
        let n = self.n as usize;
        (0..n)
            .map(|k| (from + k) % n)
            .find(|&s| mask & bit(s) != 0)
            .expect("mask is not empty")
    }

    fn put(&mut self, i: usize, amount: Chips) {
        self.stacks[i] -= amount;
        self.bets[i] += amount;
        self.committed[i] += amount;
    }

    /// Ends the street's betting: the part of the largest bet that nobody matched goes back
    /// to its owner, and the rest goes into the pot.
    fn collect(&mut self) {
        let n = self.n as usize;
        let (mut first, mut second) = (0, 0);
        for &b in &self.bets[..n] {
            if b > first {
                second = first;
                first = b;
            } else if b > second {
                second = b;
            }
        }
        for i in 0..n {
            if self.bets[i] > second {
                let back = self.bets[i] - second;
                self.stacks[i] += back;
                self.committed[i] -= back;
            }
            self.bets[i] = 0;
        }
        self.max_bet = 0;
    }

    /// Starts a betting round. Returns false if nobody has a decision to make.
    fn begin_round(&mut self, street: Street) -> bool {
        self.street = street;
        self.full_raise = self.big_blind;
        self.acted = 0;
        let n = self.n as usize;
        let active = self.active_mask();
        // A player whose bet already covers everyone else's whole stack has nothing to decide.
        let (mut first, mut second) = (0, 0);
        for i in 0..n {
            if active & bit(i) != 0 {
                let total = self.stacks[i] + self.bets[i];
                if total > first {
                    second = first;
                    first = total;
                } else if total > second {
                    second = total;
                }
            }
        }
        let mut pending = 0;
        for i in 0..n {
            if active & bit(i) != 0 && self.stacks[i] > 0 && second > self.bets[i] {
                pending |= bit(i);
            }
        }
        self.pending = pending;
        if pending == 0 || active.count_ones() <= 1 {
            return false;
        }
        if pending.count_ones() == 1 {
            let only = pending.trailing_zeros() as usize;
            if self.bets[only] >= self.max_bet {
                self.pending = 0;
                return false;
            }
        }
        let start = match street {
            Street::Preflop => self.bb_seat as usize + 1,
            _ => self.button as usize + 1,
        };
        self.actor = self.first_in(pending, start) as u8;
        true
    }

    /// Collects the bets and moves on until someone has a decision or the hand is over.
    fn finish_round(&mut self) {
        loop {
            self.pending = 0;
            self.collect();
            if self.active_mask().count_ones() <= 1 || self.street == Street::River {
                self.terminal = true;
                return;
            }
            if self.begin_round(self.street.next()) {
                return;
            }
        }
    }

    /// Pots by contribution level. Each level's contenders are the seats in `contenders`
    /// that put in at least that much; neighbouring levels with the same contenders merge.
    fn pots_for(&self, contenders: u8) -> Pots {
        let n = self.n as usize;
        let mut levels = [0 as Chips; MAX_PLAYERS];
        levels[..n].copy_from_slice(&self.committed[..n]);
        levels[..n].sort_unstable();
        let mut out = Pots {
            len: 0,
            pots: [Pot {
                amount: 0,
                eligible: 0,
            }; MAX_PLAYERS + 1],
        };
        let mut previous = 0;
        for (k, &level) in levels[..n].iter().enumerate() {
            if k > 0 && level == levels[k - 1] {
                continue;
            }
            let mut amount = 0;
            let mut eligible = 0;
            for i in 0..n {
                if self.committed[i] >= level {
                    amount += level - previous;
                    if contenders & bit(i) != 0 {
                        eligible |= bit(i);
                    }
                }
            }
            while out.len > 0 && out.pots[out.len - 1].eligible == eligible {
                out.len -= 1;
                amount += out.pots[out.len].amount;
            }
            if amount > 0 {
                out.pots[out.len] = Pot { amount, eligible };
                out.len += 1;
            }
            previous = level;
        }
        out
    }

    /// Chips each seat takes from the pots at the end of the hand.
    fn winnings<R: HandRanker>(&self, ranker: &R) -> [Chips; MAX_PLAYERS] {
        let n = self.n as usize;
        let mut won = [0; MAX_PLAYERS];
        let active = self.active_mask();
        if active.count_ones() == 1 {
            won[active.trailing_zeros() as usize] = self.pot();
            return won;
        }

        let mut ranks = [0u32; MAX_PLAYERS];
        for i in 0..n {
            if active & bit(i) != 0 {
                let [a, b] = self.deal.hole[i];
                let d = &self.deal.board;
                ranks[i] = ranker.rank7(&[a, b, d[0], d[1], d[2], d[3], d[4]]);
            }
        }
        let best_of = |mask: u8| {
            (0..n)
                .filter(|&i| mask & bit(i) != 0)
                .map(|i| ranks[i])
                .max()
        };

        // Hands that cannot win any part of any pot are killed, and the pots are formed again
        // without them (so neighbouring pots with the same winners merge).
        let mut alive = 0;
        for pot in self.pots_for(active).as_slice() {
            let best = best_of(pot.eligible);
            for i in 0..n {
                if pot.eligible & bit(i) != 0 && Some(ranks[i]) == best {
                    alive |= bit(i);
                }
            }
        }

        // Each pot is split evenly between its best hands; the chips that do not divide go to
        // the first of them clockwise from the button.
        for pot in self.pots_for(alive).as_slice() {
            let best = best_of(pot.eligible);
            debug_assert!(best.is_some(), "a pot nobody can win");
            let mut winners = [0usize; MAX_PLAYERS];
            let mut k = 0;
            for j in 1..=n {
                let i = (self.button as usize + j) % n;
                if pot.eligible & bit(i) != 0 && Some(ranks[i]) == best {
                    winners[k] = i;
                    k += 1;
                }
            }
            if k == 0 {
                continue;
            }
            let share = pot.amount / k as Chips;
            let odd = pot.amount % k as Chips;
            for &w in &winners[..k] {
                won[w] += share;
            }
            won[winners[0]] += odd;
        }
        won
    }
}
