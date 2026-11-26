//! Stopping a run cleanly when the machine is about to go away.
//!
//! A Spot machine gets SIGTERM about 30 seconds before it is shut down.
//! [`watch_sigterm`] makes that signal set a flag instead of killing the
//! process; [`Mccfr::train`](crate::Mccfr::train) looks at the flag after
//! every iteration, stops, saves a checkpoint and returns.
//!
//! The flag is one per process. [`request_stop`] sets it by hand (another
//! thread, a test), [`clear`] resets it.

use std::io;
use std::sync::atomic::{AtomicBool, Ordering};

static STOP: AtomicBool = AtomicBool::new(false);

/// True once a watched signal has arrived, or [`request_stop`] was called.
#[inline]
pub fn stop_requested() -> bool {
    STOP.load(Ordering::Relaxed)
}

/// Asks every training run in the process to stop at its next iteration.
pub fn request_stop() {
    STOP.store(true, Ordering::SeqCst);
}

/// Forgets a stop request, so a new run can start.
pub fn clear() {
    STOP.store(false, Ordering::SeqCst);
}

#[cfg(unix)]
mod unix {
    use super::*;

    pub const SIGINT: i32 = 2;
    pub const SIGTERM: i32 = 15;
    /// What `signal` returns when it fails.
    const SIG_ERR: usize = usize::MAX;

    extern "C" {
        /// The C library's `signal`: handlers go in and come out as
        /// addresses.
        fn signal(signum: i32, handler: usize) -> usize;
    }

    /// All a signal handler may safely do: set a flag.
    extern "C" fn on_signal(_signum: i32) {
        STOP.store(true, Ordering::SeqCst);
    }

    pub fn watch(signum: i32) -> io::Result<()> {
        let handler = on_signal as extern "C" fn(i32) as usize;
        // SAFETY: `signal` is the C library's; the handler only stores to an
        // atomic, which is safe inside a signal handler.
        if unsafe { signal(signum, handler) } == SIG_ERR {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}

/// From now on SIGTERM sets the stop flag instead of ending the process.
/// On systems without Unix signals this does nothing and says so.
pub fn watch_sigterm() -> io::Result<()> {
    #[cfg(unix)]
    return unix::watch(unix::SIGTERM);
    #[cfg(not(unix))]
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "no SIGTERM on this system",
    ))
}

/// The same for SIGINT (Ctrl-C).
pub fn watch_sigint() -> io::Result<()> {
    #[cfg(unix)]
    return unix::watch(unix::SIGINT);
    #[cfg(not(unix))]
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "no SIGINT on this system",
    ))
}
