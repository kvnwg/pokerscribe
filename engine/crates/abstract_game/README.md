# abstract_game: action abstraction and a shrunk heads-up game (Phase 5)

Heads-up No-Limit Hold'em cut down to a menu of bet sizes and a grouping of hands, as a game
the `cfr` crate can train on. The rules are `nlhe`'s, showdowns are ranked by `eval`, and the
`cfr` crate's `Game` trait is used as it is.

What is here:

1. Bet-size menus as settings (`Menus`), with five ready-made ones from push-or-fold to a
   Pluribus-scale menu of up to 14 sizes.
2. The pseudo-harmonic mapping (Ganzfried and Sandholm 2013) for bets that are not on the menu.
3. A `Bucketer` trait (hole cards and board to a bucket per street) so the hand-grouping work
   can plug in, with two simple bucketers: `Lossless` and `EquityBands`.
4. `AbstractGame`: the game, for any stack depth, blinds, menus and bucketer.
5. A size count for any setting: decision points, information sets and memory for regrets.

Status, 26 Nov 2026: all of it is built and tested. Push-or-fold with 10 big blinds, trained
with the `cfr` crate, matches `app/solver`'s `solve_push_fold` (see "Push-or-fold against the
Python solver"). Nothing in the app uses the crate yet. What is not here: the real hand
grouping (its own crate, in progress), the LBR exploiter, and a blueprint (Phase 6).

```rust
use abstract_game::{AbstractGame, EquityBands, GameConfig, Menus};
use cfr::{Mccfr, MccfrConfig, Sampling, Solver};

// 100 big blinds each, the default menus, 169 starting hands then 10 strength bands a street.
let config = GameConfig::new(100, Menus::standard());
let game = AbstractGame::new(config, EquityBands::new([169, 10, 10, 10])).unwrap();
println!("{} decision points, {} information sets", game.tree().len(), game.info_sets());

let mut solver = Mccfr::new(game, MccfrConfig::new(Sampling::External, 1));
solver.run(10_000);
let strategy = solver.average_policy();
```

## Settings

`GameConfig` has four fields: `stack` (each player's chips before the blinds), `small_blind`,
`big_blind` and `menus`. `GameConfig::new(stack_bb, menus)` uses blinds of 50 and 100 chips, so
bet sizes round to a hundredth of a big blind. `GameConfig::push_fold(stack_bb)` is the
all-in-or-fold game.

### Menus

`Menus::streets[s][k]` is the list of sizes offered on street `s` (preflop, flop, turn, river)
once `k` raises have been made on that street. The blinds are not raises, so preflop `k = 0`
is an open (or a raise over a limp), `k = 1` a 3-bet and `k = 2` a 4-bet. After the flop
`k = 0` is the first bet and `k = 1` the first raise. Counts past the end use the last list.
An empty list means no raise there. `Menus::limp` says whether the small blind may just call
before the flop.

A size is one of:

| Size | Meaning |
| --- | --- |
| `Size::Pot(x)` | The raise adds `x` times the pot as it would stand after calling. `Pot(1.0)` is a pot-sized bet or raise. |
| `Size::Times(x)` | Raise to `x` times the bet faced. Before any raise preflop that bet is the big blind, so `Times(2.5)` opens to 2.5 big blinds. Skipped when there is no bet to multiply (a first bet after the flop). |
| `Size::AllIn` | The whole stack. |

`Menus::actions(&state, &mut out)` turns the menu into real `nlhe` actions at any real state:
fold (when there is a bet to call), check or call, then the raises from small to large. Each
size is rounded to whole chips. A size under the minimum raise becomes the minimum raise, a
size over the stack becomes all in, and sizes that land on the same amount are offered once.

The ready-made menus:

| Menu | Preflop: open, 3-bet, 4-bet, later | Flop, turn, river: first bet, raise, later |
| --- | --- | --- |
| `push_fold()` | all in; no limp | none (never reached) |
| `minimal()` | 2.5x; 3x; all in | 0.75 pot; all in |
| `small()` | 2.5x or all in; 3x or all in; all in | 0.5 pot, pot or all in; pot or all in |
| `standard()` (the default) | 2x, 2.5x, 3x or all in; 3x, 4x or all in; 2.2x, 2.75x or all in; all in | 0.33, 0.75, 1.5 pot or all in; 0.75 pot or all in; all in |
| `wide()` | 8 opens from 2x to 5x, 5 3-bets, 4 4-bets, 2 5-bets, each with all in; then all in | flop: 13 sizes from 0.1 to 6 pots plus all in (14), then 4, 2, 0 sizes plus all in. Turn and river: 6 sizes plus all in, then 2, 1, 0 plus all in |

Change any list to make your own. `Menus::validate` rejects sizes that are not positive
numbers.

## The mapping rule

A bet that is not on the menu is read as one of the two menu sizes around it. With sizes as
shares of the pot and `a < x < b`, the bet `x` is read as the smaller size `a` with probability

```
f(x) = (b - x)(1 + a) / ((b - a)(1 + x))
```

and as `b` otherwise. This is the pseudo-harmonic mapping of Ganzfried and Sandholm, "Action
Translation in Extensive-Form Games with Large Action Spaces: Axioms, Paradoxes, and the
Pseudo-Harmonic Mapping" (IJCAI 2013). It comes from the calling frequency that makes a bluff
of size `x` break even, `1 / (1 + x)`: `f` is the weight that puts that frequency between the
ones for `a` and `b`.

- `pseudo_harmonic(a, b, x)` is the formula. `map_size(&sizes, x)` finds the neighbours on a
  whole menu and returns a `Mapping`: the two sizes, the probability of the smaller one,
  `pick(u)` for a random draw and `nearest()` for the more likely size.
- `AbstractGame::translate(&state, chips)` does it for a raise to `chips` at a state of the
  game, measuring the menu raises and the real one as shares of the pot.
- A bet under the smallest menu size is read as the smallest, and one over the largest as the
  largest. To let small bets be read as a check or call, as the paper allows, put 0 first in
  the list given to `map_size`.

Tested properties (`src/mapping.rs`, `tests/game.rs`): a size on the menu maps to itself; the
probability of the smaller size falls from 1 to 0 as the bet grows, and across a whole menu a
bigger bet is never read as a smaller size on average; there is no jump at a menu size; the
break-even calling frequency is kept exactly; doubling every chip amount changes nothing; and
these hand-worked values:

| Menu sizes around the bet | Bet | Probability of the smaller size |
| --- | --- | --- |
| 0.5 pot and pot | 0.75 pot | 3/7 |
| pot and 2 pots | 1.5 pots | 2/5 |
| check and pot | 0.5 pot | 1/3 |
| check and pot | 0.1 pot | 9/11 |
| 1/3 pot and 0.75 pot | 0.5 pot | 8/15 |
| pot and 10 pots | 3 pots | 7/18 |
| check and pot | 1/3 pot (the even point) | 1/2 |

What the crate does not do: keep track of a real hand after a bet has been mapped (the real
pot and the abstract pot then differ). That belongs with the search in Phase 7.

## Buckets

```rust
pub trait Bucketer {
    fn num_buckets(&self, street: Street) -> u64;            // for size counts
    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64; // board of 0, 3, 4 or 5 cards
}
```

The game only needs two hands to get the same id exactly when they are in the same bucket.
Ids do not have to be dense. `&B`, `Box<B>`, `Rc<B>` and `Arc<B>` are bucketers too, so one
table can serve several games.

- `Lossless`: no card abstraction. Two hands share a bucket only when one becomes the other
  by renaming suits. Preflop the ids are the 169 starting hands in chart order (AA is 0, AKs 1,
  AKo 13, 22 is 168, the order `app/solver/pushfold.py` uses; `preflop_class`, `class_name`
  and `class_from_name` convert). From the flop on the id is a code of the hand's canonical
  form: exact, but with gaps. It reports 169; 1,286,792; 55,190,538 and 2,428,287,420
  buckets for the four streets. A test recounts all four with Burnside's lemma, and another
  goes through every flop deal one by one.
- `EquityBands::new([p, f, t, r])`: bands of hand strength, for tests. Preflop the 169 hands
  are ranked by their chance against a random hand (a table from the exact equities in
  `app/solver/data/preflop_equity.npz`) and cut into `p` bands of the same number of hands;
  with 169 every hand is its own bucket. From the flop on the score is the share of the other
  player's possible hands that this hand beats on the board as it stands, cut into equal bands.
  It ignores cards to come, so a flush draw counts as the high card it is now. It is quick to
  write, not quick to run: about 1,000 hand evaluations for each player and street.

## The game

`AbstractGame::new(config, bucketer)` builds the betting tree and returns a `cfr::Game`.

- Player 0 is the small blind (the button, first to act before the flop). Player 1 is the big
  blind (first to act after it).
- Chance deals nine cards one at a time at the start: the small blind's two, the big blind's
  two, then the board. Board cards stay face down until their street. Dealing the board up
  front changes nothing for a sampling solver and keeps chance in one place. `sample_chance`
  draws a card directly. `game.deal(hole, board)` gives the state after a chosen deal.
- Actions are numbered `FOLD` (0), `CALL` (1, check or call) and `raise_to(chips)` (2 + the
  total bet for the street, as in `nlhe::Action::RaiseTo`). At every decision the legal
  actions are in that order.
- The rules are `nlhe`'s. The betting tree (`BettingTree`) is built once by playing the menus
  through `nlhe`, so every action in it is legal in the real game: minimum raises, all-ins and
  the big blind's option included. Cards do not change what may be bet, so one tree serves
  every deal. Every way a hand can end holds the payoffs `nlhe` gives for it, for each
  showdown result (small blind better, tie, big blind better), so the uncalled bet and split
  pots follow the real rules too.
- At training time a state is a place in that tree plus the cards: 88 bytes, copied, never
  boxed. At a showdown `EvalRanker` (the `eval` crate behind `nlhe`'s `HandRanker` trait)
  ranks both hands and the result picks the payoff. Payoffs are in big blinds.
- `game.replay(&state)` gives the same position as a real `nlhe::State`, for looking at the
  pot, the bets or the history. The tests use it to check every position against a hand
  played in `nlhe` on the side.
- An information set is a decision point of the betting tree and the acting player's bucket
  on that street. Its key is `bucket * decision points + decision point`: exact, no hashing,
  so two information sets never share a key. `game.info_key_of(node, bucket)` builds a key
  for reading a strategy back, and `game.tree().find(&line)` finds the decision point after a
  line of play.
- `prune_exempt` is true on the river, as the `cfr` crate asks of poker games.
- Buckets are worked out once per deal, for both players and every street the game has
  decisions on, when the last card is dealt.
- Training does not allocate once the solver has met every information set (`tests/no_alloc.rs`).

`AbstractGame::new` refuses trees of more than 10 million decision points
(`BuildError::TooLarge`, with the count); `AbstractGame::with_limit` sets another limit. A
decision point takes about 65 bytes (2.3 MB for the 36,092 of the default menu at 100 big
blinds).

## Size

`GameConfig::tree_size()` counts the betting tree without building it, so it also works for
menus far too big to train. What can happen from the start of a street depends only on the
street and the chips already in, so each such starting point is walked once and reused. The
counts are checked against trees built in full, against a walk through the `Game` interface,
and against a small game counted by hand.

- Decision points: betting sequences after which a player has to act.
- Information sets: every decision point once per bucket of its street.
- Regrets: one per action at every information set. The memory column is at 8 bytes each (an
  `f64`, the `cfr` crate's default; its integer regrets take half).

Blinds 0.5 and 1, both stacks as given. From `cargo run --release -p abstract_game --example sizes`:

### The betting tree

| Menu | Stack (bb) | Decision points | Preflop | Flop | Turn | River | Actions | Ways to end | Most actions | Longest hand |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| push-or-fold | 10 | 2 | 2 | 0 | 0 | 0 | 4 | 3 | 2 | 2 |
| minimal | 20 | 310 | 8 | 30 | 82 | 190 | 699 | 390 | 3 | 12 |
| minimal | 50 | 382 | 8 | 30 | 90 | 254 | 883 | 502 | 3 | 13 |
| minimal | 100 | 382 | 8 | 30 | 90 | 254 | 883 | 502 | 3 | 13 |
| minimal | 200 | 398 | 8 | 30 | 90 | 270 | 931 | 534 | 3 | 14 |
| small | 20 | 1,292 | 12 | 72 | 304 | 904 | 3,245 | 1,954 | 4 | 12 |
| small | 50 | 3,048 | 12 | 108 | 612 | 2,316 | 7,897 | 4,850 | 4 | 13 |
| small | 100 | 5,096 | 12 | 132 | 884 | 4,068 | 13,497 | 8,402 | 4 | 14 |
| small | 200 | 7,804 | 12 | 152 | 1,200 | 6,440 | 20,989 | 13,186 | 4 | 15 |
| standard | 20 | 5,504 | 60 | 324 | 1,260 | 3,860 | 13,873 | 8,370 | 6 | 13 |
| standard | 50 | 18,004 | 88 | 676 | 3,460 | 13,780 | 46,917 | 28,914 | 6 | 14 |
| standard | 100 | 36,092 | 88 | 948 | 6,012 | 29,044 | 96,077 | 59,986 | 6 | 15 |
| standard | 200 | 63,956 | 88 | 1,140 | 9,204 | 53,524 | 173,285 | 109,330 | 6 | 16 |
| wide | 20 | 80,808 | 364 | 4,412 | 18,792 | 57,240 | 204,113 | 123,306 | 13 | 14 |
| wide | 50 | 589,816 | 1,292 | 21,796 | 115,264 | 451,464 | 1,536,337 | 946,522 | 15 | 15 |
| wide | 100 | 2,168,076 | 1,984 | 58,332 | 373,696 | 1,734,064 | 5,752,869 | 3,584,794 | 15 | 16 |
| wide | 200 | 7,001,204 | 2,116 | 130,496 | 1,048,752 | 5,819,840 | 18,901,877 | 11,900,674 | 15 | 17 |

### Information sets and regret memory

| Menu | Stack (bb) | 10 buckets a street | Regrets | 200 buckets a street | Regrets | No card abstraction | Regrets |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| push-or-fold | 10 | 338 | 5.3 KB | 338 | 5.3 KB | 338 | 5.3 KB |
| minimal | 20 | 4,372 | 80.7 KB | 61,752 | 1.1 MB | 465,938,839,028 | 7.5 TB |
| minimal | 50 | 5,092 | 95.1 KB | 76,152 | 1.3 MB | 621,790,758,212 | 10.4 TB |
| minimal | 100 | 5,092 | 95.1 KB | 76,152 | 1.3 MB | 621,790,758,212 | 10.4 TB |
| minimal | 200 | 5,252 | 98.8 KB | 79,352 | 1.4 MB | 660,643,356,932 | 11.2 TB |
| small | 20 | 14,828 | 294.5 KB | 258,028 | 4.9 MB | 2.21e12 | 39.7 TB |
| small | 50 | 32,388 | 657.9 KB | 609,228 | 12.0 MB | 5.66e12 | 105.3 TB |
| small | 100 | 52,868 | 1.1 MB | 1,018,828 | 20.6 MB | 9.93e12 | 189.7 TB |
| small | 200 | 79,948 | 1.6 MB | 1,560,428 | 32.0 MB | 1.57e13 | 305.3 TB |
| standard | 20 | 64,580 | 1.3 MB | 1,098,940 | 21.1 MB | 9.44e12 | 170.8 TB |
| standard | 50 | 194,032 | 3.9 MB | 3,598,072 | 71.5 MB | 3.37e13 | 632.7 TB |
| standard | 100 | 374,912 | 7.6 MB | 7,215,672 | 146.5 MB | 7.09e13 | 1.3 PB |
| standard | 200 | 653,552 | 13.5 MB | 12,788,472 | 264.4 MB | 1.30e14 | 2.5 PB |
| wide | 20 | 865,956 | 16.9 MB | 16,150,316 | 311.2 MB | 1.40e14 | 2.5 PB |
| wide | 50 | 6,103,588 | 121.9 MB | 117,923,148 | 2.3 GB | 1.10e15 | 20.2 PB |
| wide | 100 | 21,996,216 | 446.1 MB | 433,553,696 | 8.6 GB | 4.23e15 | 79.2 PB |
| wide | 200 | 70,348,484 | 1.4 GB | 1,400,175,204 | 28.2 GB | 1.42e16 | 270.6 PB |

In the first two pairs of columns the 169 starting hands are kept apart before the flop and
each later street has 10 or 200 buckets. "No card abstraction" uses the `Lossless` counts.
"Most actions" is the most choices at one decision point, fold and call included. "Longest
hand" is the most decisions in one hand.

Reading the tables:

- With few sizes the tree is small: the default menu at 100 big blinds has 36,092 decision
  points. The cards are what make the game big. With 200 buckets a street that setting has
  7.2 million information sets; with no card abstraction it has 7 x 10^13.
- Stack depth matters less than the menu: from 20 to 200 big blinds the default menu grows 12
  times, while going from the default to the wide menu at 100 big blinds grows it 60 times.
- The `cfr` crate needs more than the regret column says. It keeps a strategy sum next to
  every regret (the same again) and an index of the information sets. Measured with
  `--example train`: 68 to 81 bytes per information set in all with float regrets, of which
  21 to 22 are regrets, and 58 to 64 with integer regrets (`MccfrConfig::compact`, 4 bytes a
  regret). So the default menu at 100 big blinds with 200 buckets a street needs about
  0.5 GB, and the wide menu at 100 big blinds 25 to 30 GB.

## Training speed

`cargo run --release -p abstract_game --example train -- <menu> <stack bb> <bands> <iterations> [threads] [float|int]`
trains with external-sampling MCCFR and reports speed and memory. On the 4-core cloud
container this was built in (a shared machine: the figures move by a tenth or so between runs):

| Game | Buckets after the flop | Threads, regrets | Information sets | Iterations a second | Game states visited a second | Memory per information set |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| push-or-fold, 10 bb | none (the hand ends before the flop) | 1, float | 338 | 1,116,000 | 28.1 million | 0.1 MB in all |
| small, 100 bb | starting hands only | 1, float | 7,112 | 74,700 | 15.7 million | 81 bytes |
| standard, 100 bb | starting hands only | 1, float | 50,876 | 40,900 | 13.8 million | 75 bytes |
| standard, 100 bb | starting hands only | 1, integer | 50,876 | 38,200 | 13.2 million | 64 bytes |
| standard, 100 bb | starting hands only | 4, float | 50,876 | 100,100 | 38.8 million | 75 bytes |
| standard, 100 bb | starting hands only | 4, integer | 50,876 | 130,900 | 38.4 million | 63 bytes |
| small, 100 bb | 10 `EquityBands` a street | 1, float | 52,868 | 13,700 | 2.0 million | 76 bytes |
| standard, 100 bb | 10 `EquityBands` a street | 1, float | 374,912 | 9,100 | 2.8 million | 68 bytes |
| standard, 100 bb | 10 `EquityBands` a street | 4, integer | 374,912 | 35,800 | 11.3 million | 58 bytes |

Runs of 20 million iterations (push-or-fold), 2 million (starting hands only) and 200,000
(`EquityBands`). Memory is the solver's own account (`Mccfr::memory`): regrets, strategy sums
and the index. Integer regrets are stored one unit a chip (`compact(100.0)`).

- One iteration is one sampled traversal per player.
- "Starting hands only" puts every hand in one bucket after the flop, which costs nothing to
  compute, so it shows the speed of the game alone. With `EquityBands` most of the time goes
  into the bands themselves (30 microseconds or more a deal). A real bucketer that looks its
  answer up in a table should sit much nearer the "starting hands only" rows.
- Four threads give 2.8 times the speed of one on the default menu with free buckets, and 4
  times with `EquityBands`, where the threads spend their time in the bucketer and rarely
  meet in the tables. A run on several threads depends on timing; one thread repeats exactly
  for a seed.
- To train, the `cfr` crate needs the game to be `Sync`, since its threads share it. The game
  is `Sync` whenever its bucketer is. A boxed one has to say so
  (`Box<dyn Bucketer + Send + Sync>`), and a shared one needs `Arc`, not `Rc`.

## Push-or-fold against the Python solver

`tests/push_fold.rs` builds the game with `GameConfig::push_fold(10)` and `Lossless` (2 decision
points, 338 information sets), trains it with the `cfr` crate's external-sampling MCCFR, and
compares who jams and who calls with `app/solver`'s `solve_push_fold(10)`.

The Python solver works on exact all-in equities, so its answer has no sampling noise. Ours
deals cards, so hands whose two actions are worth almost the same can land on either side.
The fixture (`tests/fixtures/push_fold_10bb.txt`, written by `tests/fixtures/make_push_fold.py`)
therefore carries, for every hand, the margin: how many big blinds the better action gains over
the other against the equilibrium opponent. The test requires:

1. Every hand with a margin of 0.05 big blinds or more is on the same side as in Python
   (played more than half the time, or less). That is 151 of the 169 hands for the jam and
   166 for the call. Python plays each of them always or never.
2. The share of hands jammed, and the share called, are within 0.015 of Python's.
3. The loss is under 0.002 big blinds a hand for each seat. The loss is what a seat gives up
   against Python's equilibrium opponent by not playing each hand the better way.

The 18 jam hands and 3 call hands with a smaller margin may land on either side: there the
two actions are worth nearly the same, and the difference is counted in the loss.

The test runs 40 million iterations with seed 1 (34 seconds):

| | Python | Trained here | Clear hands on the other side | Closer hands on the other side | Loss (bb a hand) |
| --- | ---: | ---: | --- | --- | ---: |
| Small blind jams | 58.28% of hands | 58.05% | 0 of 151 | Q6o (jammed 57% of the time; folding is better by 0.010 bb) | 0.00076 |
| Big blind calls | 37.38% of hands | 37.47% | 0 of 166 | none | 0.00026 |

The trained strategy (suited hands above the diagonal; `#` always, `.` never, `+` some of the
time but on Python's side, `J` on the other side from Python):

```
small blind jams                 big blind calls
    A K Q J T 9 8 7 6 5 4 3 2        A K Q J T 9 8 7 6 5 4 3 2
  A # # # # # # # # # # # # #      A # # # # # # # # # # # # #
  K # # # # # # # # # # # # #      K # # # # # # # # # # # + +
  Q # # # # # # # # # + # # #      Q # # # # # # # + + + . + .
  J # # # # # # # # # + + + .      J # # # # # # # + . . . . .
  T # # # # # # # # # + + + .      T # # # # # # + . . . . . .
  9 # # # # # # # # # + + . .      9 # # # . . # . . . . . . .
  8 # # # # # # # # # + + . +      8 # # + . . . # . . . . . .
  7 # # + + + + + # # + + . .      7 # # . . . . . # . . . . .
  6 # # J . . . + + # + # . .      6 # # . . . . . . # . . . .
  5 # # + . . . . . . # # + +      5 # + . . . . . . . # . . .
  4 # # . + . . . . . . # + .      4 # + . . . . . . . . # . .
  3 # # . . . . . . . . . # .      3 # . . . . . . . . . . # .
  2 # # . . . . . . . . . . #      2 # . . . . . . . . . . . #
```

How the 40 million was chosen: six seeds at three lengths (the ignored test `report`).

| Iterations | Seeds with a clear hand on the other side | Jam share (Python 0.5828) | Call share (Python 0.3738) | Worst loss, jam and call | Time |
| ---: | --- | --- | --- | --- | ---: |
| 10 million | 3 of 6 (95s twice, T2s, and K5o for the call) | 0.5728 to 0.5839 | 0.3745 to 0.3776 | 0.00227 and 0.00142 | 8 s |
| 20 million | 1 of 6 (95s) | 0.5776 to 0.5836 | 0.3740 to 0.3766 | 0.00129 and 0.00079 | 17 s |
| 40 million | 0 of 6 | 0.5751 to 0.5853 | 0.3735 to 0.3773 | 0.00076 and 0.00044 | 34 s |

The hands that were on the other side at 10 and 20 million have margins of 0.070 and 0.071,
just over the line. Sampling noise falls with the square root of the iterations, so the
closest hands are the last to settle. To rerun the sweep:

```bash
PF_ITERATIONS=40000000 PF_SEEDS=1,2,3,4,5,6 cargo test --release -p abstract_game --test push_fold report -- --ignored --nocapture
```

## Tests

```bash
cd engine
```

```bash
cargo test --release -p abstract_game
```

```bash
cargo test -p abstract_game
```

Once built, the release run takes about 50 seconds (34 of them the push-or-fold training) and
the debug run about 30. The debug run skips the two slow tests (the trained push-or-fold
comparison and the walk through every flop deal).

| Test | Checks |
| --- | --- |
| `tests/legal.rs`, `every_offered_action_is_legal_in_nlhe` | 18 settings (all five menus, stacks from 1.5 to 200 big blinds, odd blinds such as 3 and 7, a menu of awkward sizes): the whole betting tree is walked through the `Game` interface, 118,682 decision points in all, with a hand played in `nlhe` on the side: each offered action is asked of it, and at every decision `game.replay` must equal it |
| `tests/legal.rs`, `random_hands_are_legal_and_pay_what_nlhe_pays` | 30,000 random hands on 5 bigger games, from the chance node on: every offer legal, and the payoffs equal `nlhe`'s with its brute-force ranker and with `EvalRanker`, in big blinds, summing to zero |
| `tests/legal.rs`, `menus_are_legal_at_any_real_state` | Real hands played with raises of any legal size (states the abstract game never reaches): about 2 million menu actions, all legal, none twice |
| `tests/push_fold.rs` | The comparison above, the payoffs of the push-or-fold game by hand, and the fixture against the numbers the Python tests check |
| `tests/game.rs` | Chance deals each unseen card with equal probability; one key per (betting, bucket) and one (betting, bucket) per key; a player's keys do not change with the other player's cards or with board cards not yet dealt, and renaming suits changes nothing; sizes, limits and errors; the mapping at the game level; a 6 big blind game with every street trains, repeats exactly for a seed and beats random play from both seats; the same game trains on 4 threads with integer regrets; the game can be shared between threads |
| `tests/no_alloc.rs` | No allocation in training once warm, and none in the game or the lossless bucketer |
| `src/mapping.rs` | The mapping's properties and hand-worked values |
| `src/menu.rs` | Sizes in chips for the default menu preflop and after the flop, the minimum-bet and all-in corners, push-or-fold |
| `src/bucket.rs` | The 169 starting hands; lossless ids ignore suit names and card order and differ exactly when the hands differ; the four lossless counts by Burnside's lemma; all 25,989,600 flop deals give 1,286,792 ids; the preflop strength table against sampled showdowns; hand strength by hand |
| `src/size.rs`, `src/tree.rs` | Counts for push-or-fold and a 2 big blind game worked out by hand; counting against trees built in full on 9 settings; the tree does not depend on the cards; the payoffs stored for every ending are what `nlhe` pays for real hands |
| `src/ranker.rs` | `EvalRanker` and `nlhe`'s brute-force ranker agree on the winner of 20,000 showdowns |

To rebuild the push-or-fold fixture (needs numpy and treys, as the app does), from the
repository root:

```bash
python engine/crates/abstract_game/tests/fixtures/make_push_fold.py
```

## Things to know

1. The exact evaluation in the `cfr` crate (`exploitability`, `best_response_value`) walks the
   whole game, chance included, and nine cards of chance are far too many. So there is no
   exploitability number for these games yet. The LBR exploiter of this phase is the planned
   measure.
2. Lossless ids are not dense after the flop (they run up to 7.9 x 10^10 on the river), so the
   information set key overflows 64 bits for trees of more than about 230 million decision
   points. The game panics with a clear message if that ever happens.
3. Heads-up only, equal stacks, no ante. `nlhe` handles more; the tree and the keys here do not.
4. The count of information sets is an upper bound when a bucketer leaves a bucket empty.
5. A key holds the bucket of the current street only. With `Lossless` that still tells the
   whole story (a hand on the river says what it was on the flop). With a bucketer that
   groups hands, a player forgets which bucket they were in on earlier streets. That is the
   usual choice (Pluribus did the same) and keeps the game small, but it means the game is
   not one of perfect recall, so the guarantees of CFR are those of practice, not of theory.
6. A menu whose last list keeps offering small raises (a minimum raise and one other size,
   say) makes long raising wars and a tree that grows fast with the stack. End such menus
   with an all-in-only or empty list, as the ready-made ones do.
7. `EvalRanker` here is this crate's own adapter. While this was being built,
   `nlhe` gained an `EvalRanker` of its own (feature `eval`, on by default) that does the
   same thing. The two can be merged once the parallel work has landed: use `nlhe::EvalRanker`
   and delete `src/ranker.rs`.

## Layout

| File | What |
| --- | --- |
| `src/menu.rs` | `Size`, `Menus`, the ready-made menus, sizes to chips |
| `src/mapping.rs` | The pseudo-harmonic mapping |
| `src/bucket.rs` | `Bucketer`, `Lossless`, `EquityBands`, the 169 starting hands |
| `src/tree.rs` | `BettingTree`: every betting sequence, built with `nlhe` |
| `src/size.rs` | `TreeSize` and the count that does not build the tree |
| `src/game.rs` | `GameConfig`, `AbstractGame`, the `cfr::Game` implementation, `translate` |
| `src/ranker.rs` | `EvalRanker`: `eval` behind `nlhe`'s `HandRanker` (see "Things to know", 7) |
| `examples/sizes.rs` | The size tables above |
| `examples/train.rs` | A training run with speed and memory |
| `tests/` | See the table above; `tests/fixtures/` holds the Python solution and its script |
