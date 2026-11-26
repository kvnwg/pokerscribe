//! The hand evaluator (the eval crate).

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::cards;

fn rank(hand: &Bound<'_, PyAny>, count: usize) -> PyResult<u16> {
    let hand = cards::cards(hand)?;
    if hand.len() != count {
        return Err(PyValueError::new_err(format!(
            "eval{count} takes {count} cards, got {}",
            hand.len()
        )));
    }
    cards::all_different(&hand)?;
    Ok(eval::eval(&hand).value())
}

/// The strength of the best five-card hand in seven cards (two hole cards and the board).
///
/// cards: seven cards as strings ("Ah") or ints, in a list or tuple, or one string such as
/// "AhKh QhJhTh 2c3d". Returns an int from 1 (7-5-4-3-2 offsuit) to 7462 (a royal flush):
/// higher is better and equal numbers tie. It is 7463 minus the treys rank.
#[pyfunction]
pub fn eval7(cards: &Bound<'_, PyAny>) -> PyResult<u16> {
    rank(cards, 7)
}

/// eval7 for six cards (the turn).
#[pyfunction]
pub fn eval6(cards: &Bound<'_, PyAny>) -> PyResult<u16> {
    rank(cards, 6)
}

/// eval7 for five cards (the flop, or a five-card hand).
#[pyfunction]
pub fn eval5(cards: &Bound<'_, PyAny>) -> PyResult<u16> {
    rank(cards, 5)
}

/// The category of a rank from eval5, eval6 or eval7: "high card", "pair", "two pair",
/// "three of a kind", "straight", "flush", "full house", "four of a kind" or
/// "straight flush".
#[pyfunction]
pub fn hand_category(rank: u16) -> PyResult<&'static str> {
    eval::HandRank::from_value(rank)
        .map(|r| r.category().name())
        .ok_or_else(|| PyValueError::new_err(format!("a rank is from 1 to 7462, not {rank}")))
}
