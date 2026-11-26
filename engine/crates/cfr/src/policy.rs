//! Policies: a probability for each legal action at each information set.

use crate::game::InfoKey;
use crate::table::InfoTable;

/// Anything that gives action probabilities by information set.
pub trait Policy {
    /// Writes the probabilities of the `out.len()` legal actions at `key`
    /// into `out`. Information sets the policy has never seen get uniform.
    fn action_probs(&self, key: InfoKey, out: &mut [f64]);
}

/// Plays every legal action with equal probability.
#[derive(Clone, Copy, Debug, Default)]
pub struct UniformPolicy;

impl Policy for UniformPolicy {
    fn action_probs(&self, _key: InfoKey, out: &mut [f64]) {
        let p = 1.0 / out.len() as f64;
        out.fill(p);
    }
}

/// A policy stored as a table: an [`InfoTable`] plus one flat probability
/// array, the same layout the solvers use.
#[derive(Clone, Debug, Default)]
pub struct TabularPolicy {
    table: InfoTable,
    probs: Vec<f64>,
}

impl TabularPolicy {
    pub fn new() -> Self {
        Self::default()
    }

    /// Builds the policy from a table and per-slot weights (strategy sums or
    /// regrets already turned into probabilities), normalising each
    /// information set. A set whose weights sum to zero becomes uniform.
    pub fn from_weights(table: &InfoTable, weights: &[f64]) -> Self {
        let mut probs = weights[..table.slots()].to_vec();
        for set in table.sets() {
            normalize_or_uniform(&mut probs[set.range()]);
        }
        TabularPolicy {
            table: table.clone(),
            probs,
        }
    }

    /// Adds or replaces one information set.
    pub fn insert(&mut self, key: InfoKey, player: usize, probs: &[f64]) {
        let (idx, new) = self.table.get_or_insert(key, probs.len(), player);
        if new {
            self.probs.resize(self.table.slots(), 0.0);
        }
        let set = self.table.set(idx);
        self.probs[set.range()].copy_from_slice(probs);
    }

    /// The stored probabilities at `key`, if any.
    pub fn get(&self, key: InfoKey) -> Option<&[f64]> {
        self.table
            .get(key)
            .map(|i| &self.probs[self.table.set(i).range()])
    }

    pub fn table(&self) -> &InfoTable {
        &self.table
    }

    /// Number of information sets stored.
    pub fn len(&self) -> usize {
        self.table.len()
    }

    pub fn is_empty(&self) -> bool {
        self.table.is_empty()
    }
}

impl Policy for TabularPolicy {
    fn action_probs(&self, key: InfoKey, out: &mut [f64]) {
        match self.get(key) {
            Some(p) => {
                debug_assert_eq!(p.len(), out.len());
                out.copy_from_slice(p);
            }
            None => UniformPolicy.action_probs(key, out),
        }
    }
}

/// Scales `w` to sum to one, or makes it uniform if its sum is not positive.
#[inline]
pub fn normalize_or_uniform(w: &mut [f64]) {
    let sum: f64 = w.iter().sum();
    if sum > 0.0 {
        w.iter_mut().for_each(|x| *x /= sum);
    } else {
        let p = 1.0 / w.len() as f64;
        w.fill(p);
    }
}

/// Regret matching: probabilities proportional to positive regret, uniform
/// when no regret is positive.
#[inline]
pub fn regret_matching(regrets: &[f64], out: &mut [f64]) {
    let mut sum = 0.0;
    for (o, &r) in out.iter_mut().zip(regrets) {
        let x = if r > 0.0 { r } else { 0.0 };
        *o = x;
        sum += x;
    }
    if sum > 0.0 {
        // Divide rather than multiply by 1 / sum: the same rounding as
        // OpenSpiel, which keeps long runs in step with it.
        out.iter_mut().for_each(|x| *x /= sum);
    } else {
        let p = 1.0 / out.len() as f64;
        out.fill(p);
    }
}
