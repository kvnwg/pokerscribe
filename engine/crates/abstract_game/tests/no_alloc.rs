//! Training must not allocate once every information set has been met: the game's state
//! is copied, never boxed, and both bucketers work without the heap. A counting global
//! allocator (per thread, since tests run in parallel) checks it.

use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

use abstract_game::{AbstractGame, Bucketer, EquityBands, GameConfig, HandState, Lossless, Menus};
use cfr::{Game, Mccfr, MccfrConfig, Node, Sampling, Solver};

struct Counting;

thread_local! {
    static ALLOCS: Cell<u64> = const { Cell::new(0) };
}

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let _ = ALLOCS.try_with(|c| c.set(c.get() + 1));
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        let _ = ALLOCS.try_with(|c| c.set(c.get() + 1));
        unsafe { System.realloc(ptr, layout, new_size) }
    }
}

#[global_allocator]
static GLOBAL: Counting = Counting;

/// Warms the solver up until it stops finding new information sets, then counts the
/// allocations of more iterations.
fn allocations_once_warm<B: Bucketer>(game: AbstractGame<B>, warm_up: u64) -> u64 {
    let total = game.info_sets();
    let mut solver = Mccfr::new(game, MccfrConfig::new(Sampling::External, 6));
    solver.run(warm_up);
    assert_eq!(
        solver.info_sets() as u128,
        total,
        "the warm-up did not reach every information set"
    );
    let before = ALLOCS.with(|c| c.get());
    solver.run(500);
    ALLOCS.with(|c| c.get()) - before
}

#[test]
fn push_or_fold_trains_without_allocating() {
    let game = AbstractGame::new(GameConfig::push_fold(10), Lossless).unwrap();
    assert_eq!(allocations_once_warm(game, 20_000), 0);
}

#[test]
fn a_game_with_every_street_trains_without_allocating() {
    let game = AbstractGame::new(
        GameConfig::new(6, Menus::minimal()),
        EquityBands::new([4, 2, 2, 2]),
    )
    .unwrap();
    assert_eq!(allocations_once_warm(game, 8_000), 0);
}

/// Every line of play from `state`, reading the key and the actions at each decision and
/// the result at each ending, with buffers the caller owns.
fn walk(
    game: &AbstractGame<Lossless>,
    state: &HandState,
    buffers: &mut [Vec<cfr::Action>],
) -> (u64, f64) {
    match game.node(state) {
        Node::Terminal => (0, game.utility(state, 0)),
        Node::Chance => unreachable!("the cards are out"),
        Node::Player(_) => {
            let (mine, deeper) = buffers.split_first_mut().expect("deep enough");
            mine.clear();
            game.legal_actions(state, mine);
            let mut keys = game.info_key(state) % 7;
            let mut won = 0.0;
            for &action in mine.iter() {
                let mut next = *state;
                game.apply(&mut next, action);
                let below = walk(game, &next, deeper);
                keys += below.0;
                won += below.1;
            }
            (keys, won)
        }
    }
}

#[test]
fn the_lossless_bucketer_and_the_game_do_not_allocate() {
    // With no card abstraction there are far too many information sets to warm a solver
    // up, so this counts what the game itself does: deal, then walk every line of play.
    let game = AbstractGame::new(GameConfig::new(6, Menus::minimal()), Lossless).unwrap();
    let mut buffers: Vec<Vec<cfr::Action>> = (0..32).map(|_| Vec::with_capacity(16)).collect();
    let mut state = game.root();
    let before = ALLOCS.with(|c| c.get());
    for card in [3, 17, 22, 40, 51, 8, 30, 12, 45] {
        game.apply(&mut state, card);
    }
    let (_, won) = walk(&game, &state, &mut buffers);
    assert_eq!(ALLOCS.with(|c| c.get()) - before, 0);
    assert!(won.is_finite());
}
