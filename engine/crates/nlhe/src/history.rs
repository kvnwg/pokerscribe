//! The action history, stored inside the state so that cloning a state does not allocate
//! for ordinary hands.

use crate::state::{Action, Street};
use crate::Chips;

/// One player action, as it happened.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Move {
    pub street: Street,
    pub seat: u8,
    pub action: Action,
    /// Chips the action moved from the player's stack into their bet (0 for a fold or a
    /// check, the call amount for a call, the difference for a raise).
    pub added: Chips,
}

impl Move {
    const EMPTY: Move = Move {
        street: Street::Preflop,
        seat: 0,
        action: Action::Fold,
        added: 0,
    };
}

/// Moves held inline up to this many; a longer hand moves them to the heap.
pub const INLINE_MOVES: usize = 20;

#[derive(Clone, Debug)]
pub struct History {
    len: u16,
    inline: [Move; INLINE_MOVES],
    spill: Option<Vec<Move>>,
}

impl History {
    pub fn new() -> History {
        History {
            len: 0,
            inline: [Move::EMPTY; INLINE_MOVES],
            spill: None,
        }
    }

    pub fn push(&mut self, m: Move) {
        if let Some(v) = &mut self.spill {
            v.push(m);
        } else if (self.len as usize) < INLINE_MOVES {
            self.inline[self.len as usize] = m;
            self.len += 1;
        } else {
            let mut v = Vec::with_capacity(4 * INLINE_MOVES);
            v.extend_from_slice(&self.inline);
            v.push(m);
            self.spill = Some(v);
        }
    }

    pub fn as_slice(&self) -> &[Move] {
        match &self.spill {
            Some(v) => v,
            None => &self.inline[..self.len as usize],
        }
    }
}

impl Default for History {
    fn default() -> History {
        History::new()
    }
}

impl PartialEq for History {
    fn eq(&self, other: &History) -> bool {
        self.as_slice() == other.as_slice()
    }
}

impl Eq for History {}
