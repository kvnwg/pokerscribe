//! Real states rebuilt from what is public: the table, the betting and the board cards seen.
//! Hole cards and cards still to come are made up (the lowest cards not in sight); nothing
//! here ever depends on them, except that the board cards seen are the real ones (the
//! blueprint hashes them when it maps an off-menu raise).

use lbr::PublicState;
use nlhe::{Card, Config, Deal, Move, State, Street};

/// The table of a public state.
pub fn config(public: &PublicState<'_>) -> Config {
    Config::new(
        public.starting_stacks(),
        public.small_blind(),
        public.big_blind(),
        public.ante(),
        public.button(),
    )
    .expect("the public state's table is valid")
}

/// The state after `history` at `config`, with the real board cards `board` (those seen so
/// far; more are made up as the streets need them) and made-up hole cards.
pub fn rebuild(config: &Config, history: &[Move], board: &[Card]) -> State {
    let mut used = 0u64;
    for &c in board {
        used |= 1 << c;
    }
    let mut spare = (0..52 as Card).filter(move |&c| used & (1 << c) == 0);
    let n = config.num_players();
    let mut hole = [[0 as Card; 2]; nlhe::MAX_PLAYERS];
    for pair in hole.iter_mut().take(n) {
        *pair = [spare.next().unwrap(), spare.next().unwrap()];
    }
    let mut full = [0 as Card; 5];
    for (k, slot) in full.iter_mut().enumerate() {
        *slot = match board.get(k) {
            Some(&c) => c,
            None => spare.next().unwrap(),
        };
    }
    let deal = Deal::new(&hole[..n], full).expect("distinct cards");
    let mut state = State::new(config, deal).expect("a valid deal");
    for m in history {
        state.apply(m.action).expect("the history is legal");
    }
    state
}

/// The real board cards seen at `street`.
pub fn board_at(board: &[Card], street: Street) -> &[Card] {
    &board[..street.board_len().min(board.len())]
}

/// Where each street starts in `history`: the index of its first action (or the history's
/// length when the street has no action yet).
pub fn street_start(history: &[Move], street: Street) -> usize {
    history
        .iter()
        .position(|m| m.street.index() >= street.index())
        .unwrap_or(history.len())
}

/// A key for a public situation: the table, the betting and the board cards of the street
/// reached after `history[..len]`.
pub fn key(public: &PublicState<'_>, len: usize, street: Street) -> String {
    use std::fmt::Write;
    let mut k = String::with_capacity(16 + 6 * len);
    let _ = write!(
        k,
        "{}/{}/{}/{}|",
        public.starting_stacks()[0],
        public.starting_stacks()[1],
        public.big_blind(),
        public.button()
    );
    for &c in board_at(public.board(), street) {
        let _ = write!(k, "{c}.");
    }
    k.push('|');
    for m in &public.history()[..len] {
        let _ = write!(k, "{}{}", m.seat, m.action);
        k.push(',');
    }
    k
}
