# py: the Rust engine from Python (`pokerscribe_engine`)

Python bindings for three crates of the engine, built with PyO3 and maturin:

- the hand evaluator (`eval`): `eval7` and friends;
- the No-Limit Hold'em rules engine (`nlhe`): one hand, from the blinds to the payouts;
- the match arena (`arena`): matches between Rust agents and Python agents, with duplicate
  deals, the all-in luck adjustment and bb/100 with a standard error. B0 plays Rust agents
  this way (`tools/b0_arena.py`, below).

This is the link between the Python app and the Rust core. Nothing in the app uses the
module yet, and the app runs without it.

```python
import pokerscribe_engine as pe

pe.eval7(["Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d"])    # 7462, the best hand there is

hand = pe.new_hand([200, 200], 1, 2, seed=7)            # heads-up, 1/2 blinds, button on seat 0
while not hand.is_terminal:
    legal = hand.legal_actions()                         # fold, check, call, min_raise_to, max_raise_to
    hand.apply("check" if legal.check else "call")       # or hand.apply("raise", 6)
hand.payouts()                                           # chips won or lost by each seat

report = pe.run_match(["tag", "call"], 10_000, seed=1)  # heads-up, each deal twice, seats swapped
print(report.summary())                                  # bb/100 and standard errors
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

58 tests pass. If the module isn't built, the file is skipped (1 skipped) and nothing fails.

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

## Matches in the arena

`run_match(agents, deals, seed=1, ...)` plays a match in the arena (`engine/crates/arena`)
and returns its report. Each agent is a Rust agent's name or a Python object:

```python
report = pe.run_match(["tag", "call"], 10_000, seed=1)       # two Rust agents
report = pe.run_match([MyAgent(), "tag"], 1_000, seed=1)      # a Python agent against one
tag = report.result("tag")                                    # a dict: bb_per_100, se, by_seat, ...
tag["bb_per_100"] / tag["se"]                                 # z, the number the 2.5 rule looks at
```

The arena does the rest exactly as in a match between Rust agents: the deals from the seed,
duplicate play, the all-in equity, one sample per deal for the standard error, and the
report. A Python agent changes none of it. The same seed gives the same report, to the last
bit, on any number of threads (`app/tests/test_engine_bindings.py`).

| Argument | Meaning | Default |
| --- | --- | --- |
| `agents` | Rust agents' names (`agents()`) and Python objects, in any mix. | |
| `deals` | Deals. With duplicate play each is played once per rotation of the lineup: heads-up twice, seats swapped. | |
| `seed` | The match seed. | 1 |
| `players` | Table size, 2 to 6. The second agent sits in each seat in turn, the first in all the others. | 2 |
| `lineup` | The agent (an index into `agents`) at each place of the table, for any other mix. | |
| `stack`, `small_blind`, `big_blind`, `ante` | In chips. Every seat starts every hand with `stack`. | 10000, 50, 100, 0 |
| `duplicate` | Replay each deal with the lineup rotated through every seat. | True |
| `all_in_equity`, `max_runouts` | Score the equity of hands all in before the river, over at most `max_runouts` boards (`None`: every board). | True, 10000 |
| `shared_randomness` | A seat gets the same random numbers in every replay of a deal. | False |
| `threads` | Worker threads. `None`: one when a Python agent plays (Python agents take turns holding the GIL anyway), every core otherwise. | None |

The meaning of each is in the arena's README, which also explains the report's fields. A
`MatchReport` has `to_dict()`, `to_json()`, `summary()` (the arena command's table, also
`str(report)`), `save(path)` and `result(name or index)`.

### Python agents

```python
class MyAgent:
    name = "mine"                      # optional: the name in the report (else the class name)

    def act(self, view):               # required: this seat is to act
        legal = view.legal_actions()
        return "check" if legal.check else "call"   # or "fold", or ("raise", amount)

    def begin_hand(self, view): ...    # optional: the blinds are in and the cards dealt
    def end_hand(self, view): ...      # optional: view.net, view.shown(seat)
```

`act` returns `"fold"`, `"check"`, `"call"` or `("raise", amount)`, where `amount` is the
total bet of the street after it (raise to, not raise by; `"bet"` is the same). The arena
calls it with the GIL taken for that call only.

A `View` is what the seat may see. It has the same names as a `State` where they mean the
same thing:

| | |
| --- | --- |
| This seat | `seat`, `hole`, `legal_actions()`, `to_call`, `seed`, `pick(weights)` |
| The table | `num_players`, `button`, `small_blind_seat`, `big_blind_seat`, `small_blind`, `big_blind`, `ante`, `starting_stacks` |
| The hand so far | `street`, `board`, `history()`, `stacks`, `bets`, `committed`, `pot`, `max_bet`, `full_raise`, `is_folded(seat)`, `is_all_in(seat)` |
| The end | `is_over`, `net` (this seat's result in chips, in `end_hand`), `shown(seat)` (its own cards, and after a showdown those of every player who did not fold) |

- The other seats' cards can't be reached. The view holds only what the seat may see; the
  other cards are made up inside it and nothing returns them.
- `seed` is the seat's private random number for the hand, and `pick(weights)` draws an
  index with it, as the Rust agents draw theirs. An agent that takes its random choices
  from these repeats exactly.
- An action that is not legal is the arena's business: it becomes a check, or a fold when
  checking is not allowed, and is counted in `illegal_actions`.
- An exception in the agent, or an answer that is not an action at all (`42`, `"shove"`),
  stops the match: `run_match` raises it. The deals left are played without asking the
  Python agents again (they check or fold), which takes well under a second.
- A Python object listed once and seated at several places plays all of them with the same
  object. Pass one object per place to keep them apart.

### Rust agents

`agents()` lists the names `run_match` knows:

| Name | Agent |
| --- | --- |
| `fold`, `call`, `raise`, `minraise`, `jam`, `random`, `tag`, `tag-loose` | The arena's test bots (`engine/crates/arena/README.md`, "Test bots"), arena `Player`s |
| `lbr-fold`, `lbr-call`, `lbr-jam`, `lbr-call-or-raise`, `lbr-random` | LBR's chumps (`engine/crates/lbr/src/chumps.rs`): always fold, always check or call, always all in, call or raise half and half, and fold, call or raise with equal chances. They are `Strategy`s, played through the adapter below |
| `blueprint:<file>` | The blueprint in that strategy file (`engine/crates/blueprint`), with the bucket tables it was trained with (the directory the file records). `blueprint:<file>?tables=<dir>` reads the tables from `dir` instead, for a file trained on another machine (they must be the same tables: the file's checksums are checked). A `Strategy`, played through the adapter below. Seat it at the stacks and blinds it was trained for: `blueprint info <file>` shows them. A file that can't be loaded is a `ValueError` naming it. `agents()` doesn't list it, since the name holds a path |
| `search:<file>` | Depth-limited search on that blueprint (`engine/crates/search`): the blueprint before the flop, a solve of every street after it, with the leaf tables `<file>.leaf` next to it if they are there (`search leaf` builds them; without them the flop's leaves are checked down). Slow: seconds a decision after the flop. A `Strategy`, like the blueprint; a file that can't be loaded is a `ValueError` naming it |

**The hook for new agents** is `rust_agent` in `src/agents.rs`. A Rust agent becomes
playable from Python, B0 included, with one line there:

```rust
"mine" => Agent::of(name, MyPlayer::new()),               // anything that implements arena's Player
"mine-too" => strategy_agent(name, MyStrategy::new()),    // anything that implements lbr's Strategy
```

The blueprint went in this way, as `blueprint_agent`, with a name that carries the file.

- A `Player` (the arena's trait) is copied into every seat and thread, as in the arena.
- A `Strategy` (LBR's trait, which the blueprint implements) gives a probability for
  each action. `strategy_agent` asks it at every decision, with the public state rebuilt
  from the view (`visible_state`: the same table, betting and board, the seat's own cards,
  every other card made up), and draws the action with `View::pick`, so a match repeats
  exactly. It holds the strategy behind an `Arc`, so big tables are not copied.
- The adapter is checked by playing the three chumps that do what an arena bot does:
  `lbr-call`, `lbr-fold` and `lbr-jam` give exactly the reports of `call`, `fold` and
  `jam`, to the last bit.

## B0 against a Rust agent

`tools/b0_arena.py` seats B0, the frozen rule-based agent (`app/poker`), at the table:

```bash
python tools/b0_arena.py tag --deals 1000 --seed 1     # B0 against the tag bot, 2000 hands
python tools/b0_arena.py b0 --deals 200                # B0 against itself
python tools/b0_arena.py call --log illegal.jsonl --out report.json
```

| Option | Meaning | Default |
| --- | --- | --- |
| `OPPONENT` | A Rust agent's name, or `b0` for a second B0. | |
| `--deals N` | Deals, each played twice with the seats swapped. | 1000 |
| `--seed N` | The match seed. | 1 |
| `--variant JSON` | With `b0`: the opponent is a variant of B0 (overrides of `advice.TUNING`, as in `tools/compare.py`). | |
| `--stack-bb N` | Stacks in big blinds. | 100 |
| `--plain`, `--no-equity` | No duplicate play; real chips for all-in hands. | |
| `--log FILE` | Every instruction that is not legal as said, one JSON line each, with the spot. | |
| `--out FILE` | The report as JSON, with B0's counts. | |

It prints the arena's report, then B0's counts and where the time went:

```
2 players [b0 tag], blinds 50/100, stacks 10000, seed 1
100 deals x 2 = 200 hands, duplicate, scored as all-in equity (at most 10000 boards) (0 hands adjusted)
agent          seats     bb/100       SE       z   plain SE   illegal
b0                 1     +41.31    20.43    +2.0      20.22         0
  BTN/SB                 +39.13    38.37
  BB                     +43.50    13.12
tag                1     -41.31    20.43    -2.0      20.22         0
  BTN/SB                 -43.50    13.12
  BB                     -39.13    38.37
5.19 s, 39 hands/s on 1 threads
b0: 164 instructions in 200 hands; not legal as said: none; the simulator's always-wrong checks: none
time: 5.2 s, 38.5 hands/s, 31.7 ms per B0 instruction. In B0: advice 5.2 s, ...
```

From Python, `b0_arena.run(against, deals, seed)` returns the report and B0's player, whose
`stats()` holds the counts. `B0Player` itself is an ordinary Python agent and can be passed
to `run_match` with anything else.

**What B0 sees.** Exactly what it sees in `tools/simulate.py`. `table(view)` turns the
arena's view into the simulator's own `Hand`, and B0 is asked through the simulator's own
functions (`simulate.app_state`, then `simulate.decision`):

- amounts in the simulator's chips: the simulator's big blind is 2, so one of its chips is
  `big_blind / 2` arena chips (50 at the default 50/100). B0 sees blinds 1/2 and, 100 big
  blinds deep, stacks of 200;
- the seats named "BTN/SB" and "BB", as the reader names them;
- the pot without this street's bets, each player's bet this street, the amount to call,
  the buttons the simulator would show, and each player's last action this street, labelled
  as the simulator labels it (a raise that puts a player all in is "all-in");
- no profiles (as in `tools/compare.py` by default) and no antes (B0 never had them; a
  table with antes or blinds not in the ratio 1:2 is refused).

`test_b0_sees_each_spot_exactly_as_in_the_simulator` plays 400 random hands in the engine,
then the same cards and moves in the simulator, and checks that B0 gets the same
`GameState` at every one of its decisions, to the last bit, and the same result.

**What B0's instruction becomes.** The nlhe action the simulator would play for it
(`simulate.app_move`, then `simulate.act`), so B0 plays as it does in the simulator. When the
instruction is not legal as said, the simulator fixes it without a word; here it is played
the same way, counted by kind in `stats()["illegal"]`, and written to `--log`:

| Not legal as said | Played |
| --- | --- |
| fold when checking is free | check |
| check facing a bet | fold |
| call with nothing to call | check |
| bet or raise with no amount | the simulator's size: 3 times the bet, or 2/3 of the pot |
| below the minimum bet or raise | the minimum |
| more than the stack | all in |
| raise when only a call is allowed (the other player is all in or covered) | call |
| WAIT, or another instruction that is no move, on your turn | check, or fold facing a bet |

The arena never sees an illegal action from B0, so its `illegal` column stays at 0: B0's
own count is the one to read. `stats()["always_wrong"]` also has the simulator's
always-wrong checks (`simulate.check_advice`: folding the nuts, folding aces before the
flop, all in too deep with a weak hand, ...), and `stats()["always_wrong_examples"]` the
first 25 spots that failed one, with the betting so far. B0's logic and `TUNING` are not
touched.

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

**B0 in the arena** (`docs/research/runs/phase6_b0_arena/summary.md`, 27 Nov 2026, the same
machine, one process each, heads-up at 100 big blinds):

| Opponent | Hands/s | B0 instructions per hand | ms per B0 instruction |
| --- | --- | --- | --- |
| fold | 91 | 0.50 | 22 |
| jam | 33 | 1.22 | 25 |
| tag | 32 | 0.84 | 37 |
| tag-loose | 22 | 1.11 | 41 |
| B0 (two B0s at the table) | 12 to 13 | 2.6 to 2.8 | 29 |
| always-call | 4.6 | 3.11 | 70 |

All of the time is B0's. The arena, the Rust agent and the crossings between Rust and Python
together take 0.0% to 0.2% of a match. Inside B0, 94% is its Monte Carlo equity (400 samples
per estimate, a fixed count so runs repeat): 88% in the equity the simulator gives the advice
(`simulate.sim_compute`) and the rest in the advice's own equity runs. Building B0's spot from
the view, the always-wrong checks and turning the instruction into an action take under 0.5%.
Instructions before the flop are the cheapest (22 ms against fold, where B0 acts only before
the flop); against always-call, where every hand goes to the river, they average 70 ms.

A match with a Python agent plays on one thread (`threads=None` picks 1), because the agent
holds Python's lock while it thinks. More cores need more processes: separate matches on
different seeds, pooled (each deal is an independent unit, so their SEs combine).

## Tests

`app/tests/test_engine_bindings.py` (58 tests, a few seconds):

- `eval7` is exactly 7463 minus the treys rank on 20,000 random seven-card hands, and
  `eval6` and `eval5` on 3,000 each. It orders 3,000 pairs of hands as
  `app/solver/ranking.py` does.
- The 10,000 PokerKit hands that the nlhe crate replays in Rust are replayed through
  Python: at each of the 64,284 decisions, whose turn it is, the street, every stack and
  the legal actions with the raise range, then the pots and the final stacks.
- 2,000 random hands lose no chip.
- Hand-made hands for the blinds, the order of play, a showdown, an uncalled bet, side
  pots, a split pot with an odd chip, seeds, copies and every refused input.
- Matches: every Rust agent by name; a match adds up to zero, repeats with the same seed
  and gives the same result on 1 or 3 threads; the report saves, prints and reads back;
  `lbr-call`, `lbr-fold` and `lbr-jam` play exactly as `call`, `fold` and `jam` through
  the strategy hook; a Python agent sees its own cards and only what is public; every form
  of answer, an illegal answer counted as the arena counts one, and an error in a Python
  agent that stops the match.

`app/tests/test_b0_arena.py` (9 tests, about a minute and a half, most of it B0 against always-call):

- B0 sees each spot exactly as in the simulator: 400 random hands played in the engine and
  again in the simulator, with the same `GameState` at each of B0's decisions and the same
  result; and the spot reads as the app reads a table at 50/100.
- Each instruction becomes the simulator's move, and what is wrong with an instruction is
  named as the simulator would fix it (hand-made spots for each kind, among them BET 1.5
  into two big blinds on the turn). Illegal instructions are counted and written to the log,
  and the simulator's always-wrong checks are counted with the spots that fail them.
- B0 against B0 is exactly 0 in duplicate play (SE 0) and within 3 SE without it.
- B0 beats always-call and always-fold by more than 2.5 SE heads-up.
- The same seed gives the same match, and B0 is unchanged (`TUNING` as frozen).

## Layout

| File | What |
| --- | --- |
| `Cargo.toml` | The crate. Package `py`, library `pokerscribe_engine`, feature `python`. |
| `pyproject.toml` | The maturin build: module name, the `python` feature. |
| `src/lib.rs` | The module and what it exports. |
| `src/cards.rs` | Cards coming in from Python. |
| `src/hand_eval.rs` | `eval5`, `eval6`, `eval7`, `hand_category`. |
| `src/game.rs` | `State`, `LegalActions`, `new_hand`. |
| `src/arena.rs` | `run_match`, `MatchReport`, the `View` a Python agent gets, and the adapter that seats a Python object. |
| `src/agents.rs` | The Rust agents by name, the hook for a `Strategy`, and `visible_state` (what a player may see). |
| `pokerscribe_engine.pyi` | Type stubs. |
