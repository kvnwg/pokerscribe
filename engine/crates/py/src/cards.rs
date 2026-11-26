//! Cards coming in from Python: a string like `"Ah"` or the engine's int.

use eval::Card;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyString};

fn not_a_card(obj: &Bound<'_, PyAny>) -> PyErr {
    let kind = obj
        .get_type()
        .name()
        .map_or_else(|_| "object".to_string(), |n| n.to_string());
    PyTypeError::new_err(format!(
        "a card is a string like \"Ah\" or an int from 0 to 51, not {kind}"
    ))
}

/// One card: `"Ah"`, or `rank * 4 + suit` as an int.
pub fn card(obj: &Bound<'_, PyAny>) -> PyResult<Card> {
    if let Ok(text) = obj.cast::<PyString>() {
        let text = text.to_cow()?;
        return text
            .parse()
            .map_err(|e: eval::ParseCardError| PyValueError::new_err(e.to_string()));
    }
    if obj.is_instance_of::<PyBool>() {
        return Err(not_a_card(obj)); // True is an int in Python, but it is not a card
    }
    let index: i64 = obj.extract().map_err(|_| not_a_card(obj))?;
    u8::try_from(index)
        .ok()
        .and_then(Card::from_index)
        .ok_or_else(|| PyValueError::new_err(format!("card {index} is not in 0..52")))
}

/// Several cards: a list or tuple of cards, or one string such as `"AhKd"` or `"Ah Kd"`.
pub fn cards(obj: &Bound<'_, PyAny>) -> PyResult<Vec<Card>> {
    if let Ok(text) = obj.cast::<PyString>() {
        let text = text.to_cow()?;
        return eval::parse_cards(&text).map_err(|e| PyValueError::new_err(e.to_string()));
    }
    let items = obj.try_iter().map_err(|_| {
        PyTypeError::new_err("cards are a list of cards, or one string like \"AhKd\"")
    })?;
    items.map(|item| card(&item?)).collect()
}

/// An error naming the first card that appears twice.
pub fn all_different<'a>(cards: impl IntoIterator<Item = &'a Card>) -> PyResult<()> {
    let mut seen = 0u64;
    for c in cards {
        let bit = 1u64 << c.index();
        if seen & bit != 0 {
            return Err(PyValueError::new_err(format!("{c} is there twice")));
        }
        seen |= bit;
    }
    Ok(())
}

/// The engine's number for a card: rank * 4 + suit, with rank 0 = two ... 12 = ace and
/// suit 0..3 = c, d, h, s. card_index("Ah") is 50.
///
/// This is not the numbering of app/solver/ranking.py (which orders the suits s, h, d, c),
/// so pass strings between the two, never ints.
#[pyfunction]
pub fn card_index(card: &Bound<'_, PyAny>) -> PyResult<u8> {
    self::card(card).map(Card::index)
}

/// The card with this number, as a string: card_string(50) is "Ah".
#[pyfunction]
pub fn card_string(index: &Bound<'_, PyAny>) -> PyResult<String> {
    self::card(index).map(|c| c.to_string())
}
