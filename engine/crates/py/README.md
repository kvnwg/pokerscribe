# py: the Rust engine from Python (`pokerscribe_engine`)

Python bindings for two crates of the engine, built with PyO3 and maturin:

- the hand evaluator (`eval`): `eval7` and friends;
- the No-Limit Hold'em rules engine (`nlhe`): one hand, from the blinds to the payouts.

This is the link between the Python app and the Rust core. The Python side (B0, the
simulator, experiment scripts) and a Rust agent can now play the same hand under the same
rules. Nothing in the app uses the module yet, and the app runs without it.

```python
import pokerscribe_engine as pe

pe.eval7(["Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d"])    # 7462, the best hand there is

hand = pe.new_hand([200, 200], 1, 2, seed=7)            # heads-up, 1/2 blinds, button on seat 0
while not hand.is_terminal:
    legal = hand.legal_actions()                         # fold, check, call, min_raise_to, max_raise_to
    hand.apply("check" if legal.check else "call")       # or hand.apply("raise", 6)
hand.payouts()                                           # chips won or lost by each seat
```

## Build

The module is optional. `./setup_mac.sh` builds it when Rust is installed and skips it
otherwise (set `POKERSCRIBE_SKIP_RUST=1` to skip it anyway). To build it by hand, from the
repo root:

```bash
.venv/bin/python -m pip install ./engine/crates/py
```

That takes well under a minute. It needs Rust ([rustup.rs](https://rustup.rs)) and fetches
maturin by itself. To check the build:

```bash
.venv/bin/python -m pytest app/tests/test_engine_bindings.py
```

50 tests pass. If the module isn't built, the file is skipped (1 skipped) and nothing fails.

After changing the Rust code, build again. The same `pip install` works; this is quicker
when you do it often:

```bash
.venv/bin/python -m pip install maturin
```

```bash
.venv/bin/maturin develop --release -m engine/crates/py/Cargo.toml
```

How the build is set up:

- The bindings are behind the Cargo feature `python`, which is off by default. So
  `cargo build` and `cargo test` in `engine/` compile this crate as an empty library and
  need neither PyO3 nor Python. maturin turns the feature on (`pyproject.toml`).
- One build works on Python 3.10 and every later version (PyO3's `abi3-py310`), so the
  module does not have to be rebuilt when the virtual environment changes Python.
- The build is a release build, and it lands in `engine/target` with the other crates.
- The bindings are tested from Python, so `cargo test` runs nothing here. To check the
  Rust code without building the module:

```bash
cd engine && cargo clippy -p py --features python
```

## Cards

A card is a string, `"Ah"` (rank `23456789TJQKA`, suit `cdhs`, either case), or an int.
Wherever several cards go in, a list or tuple of cards works, and so does one string:
`"AhKd"`, `"Ah Kd"`, `"Ah,Kd"`. Cards that come out are always strings.

The int is the engine's number for the card: `rank * 4 + suit`, with rank 0 for a two up to
12 for an ace and suits 0 to 3 for clubs, diamonds, hearts, spades. So `2c` is 0, `Ah` is 50
and `As` is 51.

**Do not pass ints between this module and `app/solver/ranking.py`.** That file also
computes `rank * 4 + suit`, but it orders the suits s, h, d, c. `As` is 51 here and 48
there. Strings mean the same thing on both sides, so use strings (a test pins this down).

## API

| Name | What |
| --- | --- |
| `eval7(cards)` | Strength of the best five cards out of seven: an int from 1 (7-5-4-3-2 offsuit) to 7462 (royal flush). Higher is better and equal numbers tie. It is 7463 minus the treys rank that `app/poker/hands.py` uses. |
| `eval6(cards)`, `eval5(cards)` | The same for six cards (the turn) and five (the flop). |
| `hand_category(rank)` | `"high card"`, `"pair"`, `"two pair"`, `"three of a kind"`, `"straight"`, `"flush"`, `"full house"`, `"four of a kind"` or `"straight flush"`. |
| `card_index(card)`, `card_string(index)` | Between `"Ah"` and 50. |
| `new_hand(stacks, small_blind, big_blind, ante=0, button=0, *, seed=None, hole=None, board=None)` | A new hand, as a `State`. See below. |
| `State`, `LegalActions` | The classes. `State(...)` takes the same arguments as `new_hand`. |
| `MAX_PLAYERS`, `MAX_RANK`, `__version__` | 6, 7462, and the crate's version. |

Wrong input raises `ValueError` (a card that doesn't exist, the same card twice, the wrong
number of cards, a table that makes no sense, an action that is not legal), `TypeError`
(something that is not a card or not a whole number), or `IndexError` (a seat that is not
at the table).

### A hand

```python
hand = pe.new_hand([200, 150, 80], 1, 2, ante=0, button=0, seed=42)
```

- `stacks`: each seat's chips, seat 0 first, for 2 to 6 seats. Chips are whole numbers.
- Seats go clockwise. The small blind is the seat after the button and the big blind the
  next one. Heads-up, the button posts the small blind and acts first before the flop.
- The cards come from one of two keyword arguments:
  - `seed`, an int from 0 to 2**64 - 1. The same seed always gives the same cards, here
    and in Rust (`nlhe::Deal::from_seed`).
  - `hole` and `board`, fixed cards: one pair per seat, such as
    `[["Ah", "Kd"], ["7c", "2d"]]` or `["AhKd", "7c2d"]`, and all five board cards. The
    state shows only the board cards of the streets reached.

The rules are the nlhe crate's (minimum raises, short all-ins that don't reopen the
betting, side pots, odd chips): see `engine/crates/nlhe/README.md`.

What a `State` tells you:

| | |
| --- | --- |
| `current_player` | The seat to act, or `None` once the hand is over. |
| `is_terminal` | True once the hand is over. |
| `street`, `board` | `"preflop"`, `"flop"`, `"turn"` or `"river"`, and the board cards face up so far. After an all-in the board runs out to five cards. |
| `hole_cards(seat)` | That seat's two cards. Every seat can be read: the caller decides what each player gets to see. |
| `stacks`, `bets`, `committed` | Per seat: chips behind, this street's bet, everything put in this hand. |
| `pot`, `max_bet`, `full_raise` | All chips in the middle (this street's bets included), the largest bet this street, the smallest raise increment. |
| `starting_stacks`, `num_players`, `button`, `small_blind_seat`, `big_blind_seat`, `small_blind`, `big_blind`, `ante` | The table. |
| `is_folded(seat)`, `is_all_in(seat)` | |
| `pots()` | Main and side pots: `[(chips, [seats that can win it]), ...]`. |
| `history()` | Every action so far, each a dict: `street`, `seat`, `action`, `amount` (what a raise went to, else `None`) and `added` (the chips it put in). |

Playing:

| | |
| --- | --- |
| `legal_actions()` | A `LegalActions`: `fold` and `check` (True or False), `call` (the chips a call puts in, or `None`), `min_raise_to` and `max_raise_to` (or `None` when the player may not raise; `max_raise_to` is all in). Also `can_raise`, `names()` (such as `["fold", "call", "raise"]`) and `allows(action, amount=None)`. Read-only. |
| `apply("fold")`, `apply("check")`, `apply("call")` | The current player acts. |
| `apply("raise", amount)` | Bet or raise. `amount` is the player's total bet on this street afterwards: raise **to**, not raise by. An opening bet is a raise too, and `"bet"` is accepted as another name. |
| `payouts()` | Chips won or lost by each seat: final stack minus starting stack. Showdowns are ranked by the eval crate (`nlhe::EvalRanker`). `ValueError` before the hand is over. |
| `final_stacks()` | Each seat's stack after the hand. |
| `copy()` | An independent copy (`copy.copy` and `copy.deepcopy` work too). States compare with `==`. |

An action that is not legal raises `ValueError` and changes nothing.

Type stubs are in `pokerscribe_engine.pyi` and are installed with the module. They are
written by hand; a test checks that they name everything the module has.

## What B0 against a Rust agent still needs

This module gives both sides one table to play at. Still to write, in later phases:

- an adapter from a `State` to what B0's advice reads (`app/state/model.py`), and from its
  instruction back to `apply`. `B0Bot` in `tools/slumbot/bots.py` plans the same adapter
  for Slumbot and is not wired yet either;
- the Rust agent itself, exposed here as a function that takes a `State` and returns an
  action. The solver crates (`cfr`, `subgame`) are not exposed yet;
- the match loop: duplicate deals from seeds, and the luck adjustment of Phase 1.

The river solver is connected in a different way: `app/solver/rust_backend.py` runs the
program `subgame-solve` as a separate process and does not use this module.

## Speed

On the cloud container the other crates were timed on (Intel Xeon at 2.10 GHz, one
thread, Python 3.13, release build), 26 Nov 2026:

| Call | Time |
| --- | --- |
| `eval7` with seven ints | 0.27 µs |
| `eval7` with seven strings | 0.49 µs |
| treys, through `app/poker/hands.evaluate`, for comparison | 9.6 µs |
| `legal_actions()` | 0.11 µs |
| `copy()` | 0.23 µs |
| A six-max hand of random legal actions, from `new_hand` to `payouts` (about 10 decisions) | 8.1 µs |

Almost all of that is the cost of crossing from Python into Rust and back: the evaluator
itself takes about 4 nanoseconds. Loops that need millions of evaluations belong in Rust.

## Tests

`app/tests/test_engine_bindings.py` (50 tests, about a second):

- `eval7` is exactly 7463 minus the treys rank on 20,000 random seven-card hands, and
  `eval6` and `eval5` on 3,000 each. It orders 3,000 pairs of hands as
  `app/solver/ranking.py` does.
- The 10,000 PokerKit hands that the nlhe crate replays in Rust are replayed through
  Python: at each of the 64,284 decisions, whose turn it is, the street, every stack and
  the legal actions with the raise range, then the pots and the final stacks.
- 2,000 random hands lose no chip.
- Hand-made hands for the blinds, the order of play, a showdown, an uncalled bet, side
  pots, a split pot with an odd chip, seeds, copies and every refused input.

## Layout

| File | What |
| --- | --- |
| `Cargo.toml` | The crate. Package `py`, library `pokerscribe_engine`, feature `python`. |
| `pyproject.toml` | The maturin build: module name, the `python` feature. |
| `src/lib.rs` | The module and what it exports. |
| `src/cards.rs` | Cards coming in from Python. |
| `src/hand_eval.rs` | `eval5`, `eval6`, `eval7`, `hand_category`. |
| `src/game.rs` | `State`, `LegalActions`, `new_hand`. |
| `pokerscribe_engine.pyi` | Type stubs. |
