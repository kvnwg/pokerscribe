//! Warmed-up iterations must not allocate. A counting global allocator
//! (per thread, since tests run in parallel) checks it.

use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

use cfr::{Cfr, Mccfr, MccfrConfig, Sampling, Solver, Variant};
use toygames::{Kuhn, Leduc};

struct Counting;

thread_local! {
    static ALLOCS: Cell<u64> = const { Cell::new(0) };
}

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let _ = ALLOCS.try_with(|c| c.set(c.get() + 1));
        System.alloc(layout)
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        System.dealloc(ptr, layout)
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        let _ = ALLOCS.try_with(|c| c.set(c.get() + 1));
        System.realloc(ptr, layout, new_size)
    }
}

#[global_allocator]
static GLOBAL: Counting = Counting;

fn allocations_during(f: impl FnOnce()) -> u64 {
    let before = ALLOCS.with(|c| c.get());
    f();
    ALLOCS.with(|c| c.get()) - before
}

#[test]
fn full_width_iterations_do_not_allocate() {
    for variant in [
        Variant::Vanilla,
        Variant::CfrPlus,
        Variant::Linear,
        Variant::DCFR,
    ] {
        let mut solver = Cfr::new(Leduc::new(2), variant);
        solver.run(2);
        assert_eq!(allocations_during(|| solver.run(5)), 0, "{variant:?}");
    }
}

#[test]
fn mccfr_iterations_do_not_allocate_once_the_table_is_full() {
    let es = MccfrConfig::new(Sampling::External, 3);
    let configs = [
        es,
        es.linear(10, 1_000_000),
        es.linear(10, 1_000_000)
            .pruning(100, -5.0, 0.95)
            .regret_floor(-1e6),
        MccfrConfig::new(Sampling::OUTCOME, 3).linear(10, 1_000_000),
    ];
    for cfg in configs {
        let mut solver = Mccfr::new(Kuhn::new(3), cfg);
        // Kuhn has 48 information sets; a few thousand iterations reach them all.
        solver.run(20_000);
        assert_eq!(solver.info_sets(), 48);
        assert_eq!(allocations_during(|| solver.run(2_000)), 0, "{cfg:?}");
    }
}
