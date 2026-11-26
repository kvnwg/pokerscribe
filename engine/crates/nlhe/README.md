# nlhe: No-Limit Hold'em rules engine

An exact rules engine for No-Limit Texas Hold'em with 2 to 6 players, written for the
solver-based agent. Integer chips, a state that is cheap to clone inside CFR loops, and no
dependency outside this workspace (only the eval crate, and that one is optional). Every
rule is checked against PokerKit 0.7.8 on 10,000 recorded hands.

```
cd engine
cargo test -p nlhe                         # about 12 seconds in debug
cargo test -p nlhe --no-default-features   # the rules engine alone, without the eval crate
cargo clippy -p nlhe --all-targets
```

## Cards

A card is a `u8`, `rank * 4 + suit`: rank 0 is a two and 12 an ace, suits 0 to 3 are clubs,
diamonds, hearts and spades. The eval crate uses the same encoding. `parse_card("As")`,
`card_string(51)` and `card(rank, suit)` convert.

## Rules

- Seats 0 to n-1 go clockwise. The small blind is the seat after the button and the big
  blind the next one. Heads-up, the button posts the small blind and acts first preflop;
  the big blind acts first on later streets.
- Stacks are per seat. The ante (optional) is posted by everyone, then the blinds. A
  player short of the ante or a blind posts what they have and is all in. If one player
  posted a larger ante than everyone else, the unmatched part goes back to them.
- Preflop, play starts with the seat after the big blind; later streets with the first
  seat after the button that is still in. Players who are all in, or whose bet already
  covers every other player's whole stack, are skipped.
- Legal actions: fold (only when there is something to call; never when checking is
  free), check, call (the full amount or the rest of the stack), and raise to any amount
  from the minimum to all in.
- Minimum raise: the bet plus the last full raise on this street, which is at least the
  big blind (the minimum opening bet). A raise is full when it raises by at least that
  much. A player who cannot make a full raise may still go all in for less.
- An all-in below a full raise does not reopen the betting for players who already acted:
  a player who acted on this street since the last full raise may raise again only once
  the bet has gone up by at least a full raise in total since their last action (several
  short all-ins can add up to that). Players who have not acted yet, such as the big
  blind after limps, may always raise.
- Nobody may raise when no other player still in has chips left to answer.
- At the end of each betting round, the part of the largest bet that nobody matched goes
  back to its owner (the uncalled bet).
- When at most one player still in has chips, the board runs out to the river.
- Side pots form by contribution level; neighbouring levels with the same contenders are
  one pot. At showdown, hands that cannot win any part of any pot are killed and the pots
  re-formed without them. Each pot is split evenly between its best hands, and the odd
  chips all go to the first of those winners clockwise from the button.
- Deterministic deals: `Deal::from_seed(seed, players, button)` shuffles with SplitMix64
  (Fisher-Yates, no modulo bias) and deals the hole cards round the table from the seat
  after the button, then five board cards. The same seed gives the same cards everywhere.
  `Deal::new(hole, board)` takes fixed cards instead.

Not covered: straddles, rake, running it twice, more than 6 players. A small blind equal
to the big blind is allowed (the button still acts first heads-up), but the reference
fixtures only use a small blind below the big blind.

## API

```rust
use nlhe::{Action, Config, EvalRanker, State};

// stacks per seat, small blind, big blind, ante, button
let config = Config::new(&[200, 150, 80, 200, 40, 300], 1, 2, 0, 0)?;
let mut state = State::from_seed(&config, 42);   // or State::new(&config, deal)?

while let Some(seat) = state.current_player() {
    let legal = state.legal_actions();           // fold, check, call: Option<chips>,
                                                 // raise: Option<RaiseRange { min_to, max_to }>
    let action = if legal.check { Action::Check } else { Action::Call };
    state.apply(action)?;                        // an illegal action is an error and changes nothing
}
let net = state.payouts(&EvalRanker).unwrap();        // final stack minus starting stack
let fin = state.final_stacks(&EvalRanker).unwrap();
```

- `Action::RaiseTo(x)` is the total bet for the street, not the increment.
- `history()` gives every action as a `Move { street, seat, action, added }`, where
  `added` is the chips that action put in.
- Other readers: `street`, `board` (cards face up so far), `hole_cards`, `stacks` (chips
  behind), `bets` (this street), `committed` (whole hand), `pot`, `pots` (main and side
  pots with a seat mask of contenders), `max_bet`, `full_raise`, `is_folded`, `is_all_in`,
  `button`, `small_blind_seat`, `big_blind_seat`, `is_terminal`.

### Showdown ranking

The engine never ranks hands itself. Showdowns go through a trait:

```rust
pub trait HandRanker {
    fn rank7(&self, cards: &[Card; 7]) -> u32;   // higher is better, equal ties
}
```

Two rankers come with the crate, both in `src/ranker.rs`:

- `EvalRanker` uses the eval crate's table evaluator. It is the one to play and solve
  with: about 6 nanoseconds a hand. Its value is the eval crate's rank, 1 (7-5-4-3-2
  offsuit) to 7,462 (royal flush).
- `BruteForceRanker` tries all 21 five-card hands. It is meant to be read, not to be
  fast (about 3.7 microseconds a hand, over 600 times slower), and it is the reference
  the tests check `EvalRanker` against.

The two times are from `cargo run --release -p nlhe --example rankers` (10,000 random
hands, a cloud container with an Intel Xeon at 2.10 GHz, 26 Nov 2026).

Only the order of the values matters, and the two rankers use different numbers for the
same hand, so never compare a value from one with a value from the other.

`EvalRanker` is behind the Cargo feature `eval`, which is on by default. A crate that
wants the rules engine with no dependency at all asks for it without default features:

```toml
nlhe = { path = "../nlhe", default-features = false }
```

### Cost

`State` is 496 bytes with no heap memory: stacks and masks are fixed arrays, and the
history keeps its first 20 moves inline (a longer hand moves it to the heap). In a release
build a clone takes about 13 ns, and a decision (legal actions, a clone and an apply,
counting the seeded deal and a brute-force showdown per hand) about 0.3 microseconds.

## Tests

`tests/pokerkit_fixtures.rs` replays `tests/fixtures/pokerkit_nlhe.txt`: 10,000 hands
(4,469 heads-up, 4,535 six-max, the rest 3 to 5 players) played by
`tools/reference/nlhe_fixtures.py` with PokerKit 0.7.8, fixed cards and random legal
actions over mixed stacks with many short all-ins. At each of the 64,284 decisions the
engine must agree on whose turn it is, the street, every stack, whether folding is
allowed, the call amount and the exact raise range. At the end it must agree on the main
and side pots and the final stacks. A second test replays every hand with the button on
each other seat. The file includes 3,011 hands with side pots, 2,320 split pots (581 with
odd chips) and 3,632 all-in raises below a full raise.

Rebuild the fixtures (the output is identical for the same seed):

```
pip install pokerkit==0.7.8
python tools/reference/nlhe_fixtures.py --hands 10000 --seed 20261126 \
    --out engine/crates/nlhe/tests/fixtures/pokerkit_nlhe.txt
```

Where PokerKit 0.7.8 breaks the reopening rule above, the fixtures follow the rule and
flag the step:

- D (173 steps): PokerKit counts the first raise of a street as full whatever its size,
  so a limper facing an all-in of less than a big blind over the limp could re-raise.
- A (206 steps): PokerKit keeps one list of short all-ins for the whole table, so after
  two short all-ins add up to a full raise and a third short all-in follows, the first
  bettor could not raise although the bet went up by more than a full raise since they
  acted.

Only the yes or no on raising is overridden. The raise sizes, call amounts, order of play,
pots, returned bets and odd chips are all PokerKit's, and the script checks that
PokerKit's minimum raise always equals the rule's.

`tests/rules.rs` has a hand-made test for each rule (seat order, the big blind's option,
minimum raises, each reopening case, side pots, uncalled bets, antes, odd chips, seeded
deals, long histories), checks the brute-force ranker against the known count of every
category over all 2,598,960 five-card hands, and plays 20,000 random hands checking that
no chip is lost.

`EvalRanker` is checked in two ways (both need the feature `eval`):

- `tests/eval_ranker.rs` deals 100,000 random showdowns with 2 to 6 players (399,794
  hands, 4,769 of the 4,824 seven-card ranks). In each one the two rankers must give
  every hand the same category and put every pair of hands in the same order; sorted
  together, all the hands seen must come out in one order under both. Then everyone goes
  all in from random stacks (79,720 of the showdowns have side pots, 5,559 a tie for the
  best hand) and the engine must pay out the same chips with either ranker.
- `tests/pokerkit_fixtures.rs` replays the 10,000 PokerKit hands a second time with
  `EvalRanker`, the button on every seat as before. PokerKit's pots and final stacks must
  come out again.

## Layout

| File | What |
| --- | --- |
| `src/state.rs` | `Config`, `State`, actions, betting, pots, payouts |
| `src/cards.rs` | card encoding, `Deal`, the seeded `Rng` |
| `src/ranker.rs` | `HandRanker`, `BruteForceRanker` and `EvalRanker` |
| `src/history.rs` | `Move` and the inline history |
| `tests/` | the PokerKit replay, the rule tests, the two rankers compared, the fixture file |
