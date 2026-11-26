# nlhe: No-Limit Hold'em rules engine

An exact rules engine for No-Limit Texas Hold'em with 2 to 6 players, written for the
solver-based agent. Integer chips, no dependencies, and a state that is cheap to clone
inside CFR loops. Every rule is checked against PokerKit 0.7.8 on 10,000 recorded hands.

```
cd engine
cargo test -p nlhe            # under 10 seconds in debug
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
use nlhe::{Action, BruteForceRanker, Config, State};

// stacks per seat, small blind, big blind, ante, button
let config = Config::new(&[200, 150, 80, 200, 40, 300], 1, 2, 0, 0)?;
let mut state = State::from_seed(&config, 42);   // or State::new(&config, deal)?

while let Some(seat) = state.current_player() {
    let legal = state.legal_actions();           // fold, check, call: Option<chips>,
                                                 // raise: Option<RaiseRange { min_to, max_to }>
    let action = if legal.check { Action::Check } else { Action::Call };
    state.apply(action)?;                        // an illegal action is an error and changes nothing
}
let net = state.payouts(&BruteForceRanker).unwrap();        // final stack minus starting stack
let fin = state.final_stacks(&BruteForceRanker).unwrap();
```

- `Action::RaiseTo(x)` is the total bet for the street, not the increment.
- `history()` gives every action as a `Move { street, seat, action, added }`, where
  `added` is the chips that action put in.
- Other readers: `street`, `board` (cards face up so far), `hole_cards`, `stacks` (chips
  behind), `bets` (this street), `committed` (whole hand), `pot`, `pots` (main and side
  pots with a seat mask of contenders), `max_bet`, `full_raise`, `is_folded`, `is_all_in`,
  `button`, `small_blind_seat`, `big_blind_seat`, `is_terminal`.

### Showdown ranking

The engine does not depend on the eval crate. Showdowns go through a trait:

```rust
pub trait HandRanker {
    fn rank7(&self, cards: &[Card; 7]) -> u32;   // higher is better, equal ties
}
```

`BruteForceRanker` in `src/ranker.rs` tries all 21 five-card hands and is meant to be
read, not to be fast. Plug the eval crate's evaluator in with a one-line `impl`. Only
the order of the values matters.

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

## Layout

| File | What |
| --- | --- |
| `src/state.rs` | `Config`, `State`, actions, betting, pots, payouts |
| `src/cards.rs` | card encoding, `Deal`, the seeded `Rng` |
| `src/ranker.rs` | `HandRanker` and `BruteForceRanker` |
| `src/history.rs` | `Move` and the inline history |
| `tests/` | the PokerKit replay, the rule tests, the fixture file |
