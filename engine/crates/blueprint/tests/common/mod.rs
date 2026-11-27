//! Helpers for the tests: a fast bucketer that needs no tables, small trained games, and
//! real hands played along abstract lines.

#![allow(dead_code)]

use abstract_game::{preflop_class, AbstractGame, Bucketer, Card, GameConfig, Menus, Street};
use blueprint::{Blueprint, StrategyFile};
use cfr::{Mccfr, MccfrConfig, Rng, Sampling, Solver};
use nlhe::{Config, Deal, State};

/// The 169 starting hands, then the category of the best hand on the board (high card to
/// straight flush): 9 buckets a street, quick to compute, good enough to learn from.
#[derive(Clone, Copy, Debug, Default)]
pub struct Category;

impl Bucketer for Category {
    fn num_buckets(&self, street: Street) -> u64 {
        if street == Street::Preflop {
            169
        } else {
            9
        }
    }

    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
        if board.is_empty() {
            return preflop_class(hole) as u64;
        }
        let cards: Vec<eval::Card> = hole
            .iter()
            .chain(board)
            .map(|&c| eval::Card::from_index(c).unwrap())
            .collect();
        eval::eval(&cards).category() as u64
    }
}

pub fn game(stack_bb: u32, menus: Menus) -> AbstractGame<Category> {
    AbstractGame::new(GameConfig::new(stack_bb, menus), Category).unwrap()
}

/// A game trained for `iterations` on one thread.
pub fn trained(stack_bb: u32, menus: Menus, iterations: u64) -> Mccfr<AbstractGame<Category>> {
    let mut solver = Mccfr::new(
        game(stack_bb, menus),
        MccfrConfig::new(Sampling::External, 7),
    );
    solver.run(iterations);
    solver
}

/// The trained solver's average strategy as a blueprint.
pub fn play(solver: &Mccfr<AbstractGame<Category>>) -> Blueprint<Category> {
    let file = StrategyFile::from_solver(solver, None, None, 0.0).file;
    let config = solver.game().config().clone();
    Blueprint::new(AbstractGame::new(config, Category).unwrap(), file).unwrap()
}

/// `count` different cards in random order.
pub fn deal(rng: &mut Rng, count: usize) -> Vec<Card> {
    let mut deck: Vec<Card> = (0..52).collect();
    for i in 0..count {
        let j = i + rng.below(52 - i);
        deck.swap(i, j);
    }
    deck.truncate(count);
    deck
}

/// A real heads-up hand with `button` as the small blind: `sb` and `bb` are the small and
/// big blind's cards.
pub fn real_hand(
    stack: u32,
    button: usize,
    sb: [Card; 2],
    bb: [Card; 2],
    board: [Card; 5],
) -> State {
    let config = Config::new(&[stack, stack], 50, 100, 0, button).unwrap();
    let hole = if button == 0 { [sb, bb] } else { [bb, sb] };
    State::new(&config, Deal::new(&hole, board).unwrap()).unwrap()
}
