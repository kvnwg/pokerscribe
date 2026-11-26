//! Per-depth buffers so tree walks never allocate once warmed up.
//!
//! A recursive walk takes the buffer for its depth, fills it, recurses, and
//! puts it back. A buffer is created the first time a depth is reached and
//! reused on every later visit, so steady-state iterations allocate nothing.

use crate::game::Action;

#[derive(Default)]
pub(crate) struct Frame {
    pub actions: Vec<Action>,
    pub chance: Vec<(Action, f64)>,
    pub probs: Vec<f64>,
    pub values: Vec<f64>,
    pub explored: Vec<bool>,
}

#[derive(Default)]
pub(crate) struct Scratch {
    frames: Vec<Frame>,
}

impl Scratch {
    #[inline]
    pub fn take(&mut self, depth: usize) -> Frame {
        if depth >= self.frames.len() {
            self.frames.resize_with(depth + 1, Frame::default);
        }
        std::mem::take(&mut self.frames[depth])
    }

    #[inline]
    pub fn put(&mut self, depth: usize, mut frame: Frame) {
        frame.actions.clear();
        frame.chance.clear();
        self.frames[depth] = frame;
    }
}
