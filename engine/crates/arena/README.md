# arena: the match arena

Plays poker agents against each other at No-Limit Hold'em, from heads-up to six-max, and
reports who won in bb/100 with a standard error (SE). It is the tool behind the rule "a new
version replaces the last one only if it beats it by 2.5 SE", so behind the gates of Phases
6, 7 and 8. The rules come from the `nlhe` crate and the showdowns from `eval`.

Status, 28 Nov 2026: built and tested on simple bots; B0 plays in it from Python
(`tools/b0_arena.py`, through `engine/crates/py`), and so do the blueprint and the search
agent. Every match is also scored with AIVAT ("AIVAT" below), which needs fewer hands for the
same standard error; it is reported next to the main figure, not used to judge anything yet.
Nothing in the app uses the arena.

| Asked for | Result |
| --- | --- |
| Identical agents give 0 within the SE | Pass. tag against tag heads-up over 4 million hands: +0.00 and +0.02 bb/100 on two seeds, SE 0.03. tag against 5 tags over 1.8 million hands: -0.04 and +0.06, SE 0.04. random against random gives the same picture. The largest gap in the eight runs is 1.5 SE. |
| A clearly better bot beats a clearly worse one | Pass. tag beats call by 222 bb/100 heads-up (SE 1.4) and by 659 against five of them (SE 6.2). tag beats random by 73 (SE 1.5). |
| Duplicate plus all-in equity gives a clearly smaller SE than plain play over the same number of hands | Pass for close agents, the case the 2.5 SE rule is about: 2.0 times smaller heads-up and at six-max (tag-loose against tag), as good as 4 times the hands. For agents that differ a lot it is 1.1 to 1.5 times smaller, and in one six-max case duplicate makes it larger. See "Standard errors". |
| The same seed gives the same result | Pass: the same to the last bit, on any number of threads. |

## Use

```bash
cd engine
```

```bash
cargo build --release -p arena
```

```bash
./target/release/arena --agents tag,tag-loose --deals 200000 --out match.json
```

```
2 players [tag-loose tag], blinds 50/100, stacks 10000, seed 1
200000 deals x 2 = 400000 hands, duplicate, scored as all-in equity (at most 10000 boards) (695 hands adjusted)
agent          seats     bb/100       SE       z   plain SE   illegal
tag                1     -10.79     0.45   -24.1       0.84         0
  BTN/SB                  -9.94     0.99
  BB                     -11.64     1.06
tag-loose          1     +10.79     0.45   +24.1       0.84         0
  BTN/SB                 +11.64     1.06
  BB                      +9.94     0.99
0.19 s, 2148591 hands/s on 4 threads
```

`z` is the win rate in standard errors, the number the 2.5 rule looks at. `plain SE` is what
plain play would have given over the same number of hands.

| Option | Meaning | Default |
| --- | --- | --- |
| `--agents A,B` | Agents by name: `fold call raise minraise jam random tag tag-loose mixed mixed-loose`. | |
| `--players N` | Table size, 2 to 6. The second agent sits in each seat in turn, the first in all the others. | 2 |
| `--lineup I,J,...` | The agent (0 for the first) at each place of the table, for any other mix. | |
| `--deals N` | Deals. With duplicate play each is played once per rotation of the lineup. | 10000 |
| `--seed N` | The match seed. | 1 |
| `--plain` | No duplicate play: each deal once, the lineup moving one seat a deal. | duplicate |
| `--no-equity` | Score the real chips when players are all in before the river. | equity |
| `--max-runouts N` | Average the all-in equity over at most N boards. | 10000 |
| `--exact-equity` | Average over every board, also before the flop (10 to 15 ms a hand). | |
| `--shared-randomness` | A seat gets the same random numbers in every replay of a deal. | off |
| `--stack-bb N`, `--blinds SB/BB`, `--ante N` | Stacks in big blinds, blinds and ante in chips. | 100, 50/100, 0 |
| `--threads N` | Worker threads. | every core |
| `--out FILE` | Save the report as JSON. | |
| `--no-aivat` | Don't score with AIVAT as well. | AIVAT on |
| `--aivat-facing NAME` | How AIVAT values a bet still to be answered: `minimum-defense`, `called` or `taken-back` (see "AIVAT"). | `minimum-defense` |
| `--aivat-boards N` | Boards AIVAT draws for its values before the flop. | 2000 |

Exit code 0: played. 1: the match settings are wrong or the file can't be written. 2: the
command line is wrong.

From Rust:

```rust
use arena::{bots, run_match, Agent, MatchConfig};

let agents = [bots::builtin("tag").unwrap(), Agent::of("mine", MyPlayer::new())];

// Heads-up: every deal twice, seats swapped.
let report = run_match(&MatchConfig::heads_up(200_000, 1), &agents)?;

// Six-max, agent 1 against five of agent 0: every deal six times, agent 1 in each seat in turn.
let report = run_match(&MatchConfig::one_against_the_rest(6, 100_000, 1), &agents)?;

// Any mix: the agent at each place of the table.
let report = run_match(&MatchConfig::new(&[0, 1, 0, 1, 0, 1], 100_000, 1), &agents)?;

let mine = report.result("mine").unwrap();
println!("{:+.2} bb/100, SE {:.2}, z {:?}", mine.bb_per_100, mine.se.unwrap(), mine.z());
report.save("match.json".as_ref())?;
```

## Players

An agent implements one method:

```rust
pub trait Player: Send {
    /// The action for the seat `view.seat()`, which is to act.
    fn act(&mut self, view: &View<'_>) -> Action;

    fn begin_hand(&mut self, _view: &View<'_>) {}   // optional
    fn end_hand(&mut self, _view: &View<'_>) {}     // optional

    // Optional, for AIVAT: the chances the last action was drawn with, and the chances
    // this player would play with at any view.
    fn probabilities(&self) -> Option<&[(Action, f64)]> { None }
    fn chances_at(&self, _view: &View<'_>, _out: &mut Vec<(Action, f64)>) -> bool { false }
}
```

`Action` is nlhe's: `Fold`, `Check`, `Call`, `RaiseTo(total bet of the street)`. A closure
`|view: &View<'_>| ...` is a player too.

A `View` is what that seat may see, and nothing else:

| | |
| --- | --- |
| Its cards | `hole()` |
| The board | `board()`, `street()` |
| The action history | `history()`: every action with its street, seat and chips |
| The stacks | `stacks()` (chips behind), `starting_stacks()`, `bets()` (this street), `committed()` (whole hand), `pot()`, `max_bet()`, `to_call()` |
| The table | `seat()`, `num_players()`, `button()`, `small_blind_seat()`, `big_blind_seat()`, `small_blind()`, `big_blind()`, `ante()`, `is_folded(seat)`, `is_all_in(seat)` |
| What it may do | `legal()`: fold, check, the call amount, the raise range |
| Helpers | `check_or_call()`, `check_or_fold()`, `raise_to(amount)` and `raise_pot(fraction)` (moved into the legal range) |
| Randomness | `seed()`, `rng()`, `pick(&weights)` |
| At the end | `is_over()`, `net()` (its result in chips), `shown(seat)` (cards turned up at a showdown) |

The other players' cards cannot be reached before a showdown: the view holds the full state
privately and has no method that returns them.

An action that is not legal is replaced by a check, or by a fold when checking is not
allowed, and counted (`illegal_actions` in the report, `illegal` in the table). A match with
a count above 0 is a match with a bug in an agent.

An `Agent` is a name and a way to make players. The arena makes one player per seat and per
thread, so an agent that holds several seats never shares state between them:

```rust
Agent::of("tag", TightAggressive::default())          // copies of a player
Agent::new("blueprint", move || Box::new(BlueprintPlayer::new(tables.clone())))
```

Random choices should come from the view (`rng()` or `pick`), not from a generator kept in
the player. The arena gives every seat a private random number for each hand, derived from
the match seed, and `rng()` derives one generator per decision from it. That is what makes
a match repeat exactly.

How the coming agents fit:

- The blueprint: a player holding the tables behind an `Arc`. `act` maps the view to its
  bucket and its action menu, then returns `menu[view.pick(&probabilities)]`.
- LBR's `Strategy` trait: a wrapper that holds a strategy and samples from it with
  `view.pick` makes any strategy a player. LBR itself is a player. To follow the opponent's
  range it needs "what would you do here with these cards": `view.imagine(seat, cards)` is
  the same public situation through another seat's eyes with cards of the caller's choosing,
  and `view.config()` with `view.history()` rebuilds the public state in an nlhe `State`.
- B0 through Python: built, in `engine/crates/py` ("Matches in the arena"). A player there
  hands a Python object the view's fields at each decision and turns its answer into an
  `Action`; `tools/b0_arena.py` is B0 as such an object. `begin_hand` and `end_hand` (with
  `net()` and `shown()`) give it the hand boundaries and the showdowns profiles would learn
  from (B0 plays without profiles for now). An agent that learns from one hand to the next
  repeats exactly only with `threads: 1`. The same crate has the adapter for a `Strategy`
  and the list of agents Python can name (`src/agents.rs`), where the blueprint goes.

## A match

**Seats.** The button is always seat 0, so a seat number is a position: seat 1 is the small
blind, seat 2 the big blind, then UTG, HJ and CO at six-max. Heads-up, seat 0 is the button
and small blind and seat 1 the big blind. The agents move, not the button. Every seat starts
every hand with the same stack.

**Lineup and rotations.** `lineup` names the agent at each place of the table. Rotation `r`
moves every place `r` seats clockwise.

- Plain play: deal `d` is played once, with rotation `d % players`, so every agent visits
  every seat equally often.
- Duplicate play (the default): every deal is played with every rotation. Heads-up that is
  twice, seats swapped. With `[b, a, a, a, a, a]` it is six times, b in each seat in turn
  and a in the five others (`--lineup 0,1,1,1,1,1` is the other way round: one a among
  five b). Any other lineup works the same way: `[a, b, c, a, b, c]` is played three
  times, since after three seats the seating repeats.

**Samples.** One sample per deal and agent: the agent's score averaged over all its seats
in all the replays of the deal. The win rate is the mean of the samples and the SE is their
standard deviation over the square root of the number of deals. Deals are independent of
each other. Hands of the same deal are not, which is the point of duplicate play, and why
the SE is taken per deal and not per hand. An agent that holds five seats has a win rate
per seat: against a lone opponent winning 10 bb/100 it shows -2.

**Seeds.** Every random number comes from the match seed: the cards of deal `d` (shuffled
by nlhe's `Deal::from_seed`), each seat's private number for each hand, and the boards drawn
for the all-in equity. Deals are added up in fixed blocks of 32 and the blocks merged in
order, so the result does not depend on the number of threads, to the last bit.

## Luck reduction

Three things, each optional, for the main figure; AIVAT, a fourth, is reported next to it
(its own section below).

**1. Duplicate play**, above. It removes the luck of who was dealt what.

**2. All-in equity.** When the betting ends before the river with players all in, the rest
of the board is pure luck. The hand is then scored as each seat's payout averaged over the
boards that could still come, in place of the board that came.

- The average is taken over the cards really left in the deck: the hole cards of every seat
  are out of it, the folded ones too. Given all the cards dealt and all the actions, every
  remaining board is equally likely, so the score has exactly the expected value of the real
  payout: no agent's expected result changes. (Leaving folded cards in the deck, as a hand
  tracker must, would be slightly off: players fold weak cards more often than strong ones.)
- Side pots, split pots and odd chips are paid as the nlhe engine pays them, board by board.
- On the flop (at most 990 boards) and the turn (at most 44) every board is counted.
- Before the flop there are 1,712,304 boards heads-up, which takes 10 to 15 ms. By default
  the arena draws 10,000 of them at random (seeded by the deal) and averages those. That is
  still an estimate with no bias, the SE of a match is the same to three digits (table
  below), and matches with all-ins run 16 to 27 times faster. `max_runouts: None` or
  `--exact-equity` counts every board.
- The replays of a deal often end all in with the same cards and chips. The answer is
  worked out once per deal.

| 200,000 hands (120,000 at six-max) | Every board | 10,000 boards | 1,000 boards | 100 boards | Real chips |
| --- | --- | --- | --- | --- | --- |
| tag against raise, heads-up: bb/100 | +139.16 | +139.18 | +139.19 | +138.98 | +137.64 |
| SE | 3.38 | 3.38 | 3.39 | 3.40 | 4.37 |
| Hands a second | 28,000 | 657,000 | 1,768,000 | 2,346,000 | 2,400,000 |
| tag against jam, heads-up: bb/100 | -10.28 | -10.26 | -10.25 | -10.52 | -7.52 |
| SE | 1.73 | 1.73 | 1.74 | 1.74 | 2.59 |
| Hands a second | 29,000 | 791,000 | 4,513,000 | 7,817,000 | 8,827,000 |
| tag against 5 random, six-max: bb/100 | +161.51 | +161.48 | +161.59 | +161.19 | +166.99 |
| SE | 4.96 | 4.96 | 4.97 | 4.98 | 6.79 |
| Hands a second | 5,300 | 86,000 | 572,000 | 1,222,000 | 1,797,000 |

**3. Shared randomness** (off by default). With `shared_randomness`, a seat gets the same
private random numbers in every replay of a deal. Two agents that would make the same choice
with the same random number then do make the same choice, and the replays differ only where
the agents differ. Identical agents score exactly 0. On the test bots, which hardly use
random numbers, it changes little (0.42 to 0.41 below). It is there for agents with mixed
strategies, drawn with `view.pick`, and its worth for those is not measured yet.

**Scorers.** A `Scorer` turns a finished hand into each seat's score:

```rust
pub trait Scorer: Send + Sync {
    fn name(&self) -> String;
    /// `scores` arrives holding the real payouts: change only what is adjusted.
    fn score(&self, hand: &HandRecord<'_>, scores: &mut [f64]);
}
```

`HandRecord` has the final nlhe `State` (every hole card, the board, the whole history, the
starting stacks), the agent in each seat, the real payouts, the chances each player reported
for its actions, and a seed. All-in equity is one scorer (`AllInEquity`), real chips another
(`ActualChips`), AIVAT a third (`Aivat`). Pass one to `run_match_scored(&config, &agents,
&scorer)` for the main figure. Duplicate play, the SE and the report work on whatever the
scorer returns. A match runs AIVAT next to its main scorer when `config.aivat` is set (with
the players at hand, so it can ask them for answers; as the main scorer it can't).

## AIVAT

After Burch, Schmid, Moravcik, Morrill and Bowling, "AIVAT: A New Variance Reduction
Technique for Agent Evaluation in Imperfect Information Games" (AAAI 2018). In
`src/aivat.rs`.

On by default in the binary (`--no-aivat` turns it off) and in Python's `run_match`
(`aivat=False`); in Rust, `MatchConfig::heads_up(...).with_aivat()`. Each agent's line in the
summary gets a second line:

```
AGENT_LINES
```

`SE x` is AIVAT's SE over the main figure's, `minus the above` the paired difference AIVAT
minus the main figure, deal by deal, with its SE: both figures have no bias, so it should be
0 up to its SE. The last line counts the decisions whose random choice was corrected.

**What it takes out.** A hand is a sequence of events: the deal of the hole cards, each
board card, each action. At every event whose chances are known exactly, AIVAT subtracts
the luck of its outcome `x`:

```
v(after x) - sum over every outcome y of P(y) v(after y)
```

where `v` is a value estimate for each seat. Known chances:

- The deal and the board cards, always. The arena deals them: every unseen card is equally
  likely, whatever the players did, since nobody sees the cards before they fall. The deal's
  correction compares its value with the exact average over every deal, worked out without
  dealing (every seat that can win a pot is as likely as any other to hold the best hand).
- The actions of an agent that reports the chances it drew its action with
  (`Player::probabilities`): the blueprint (`blueprint:<file>` from Python, `search
  match`), the search agent (`search:<file>`: the strategy its solve played), any LBR
  `Strategy` played through the py crate, and the test bot `mixed`.
- Not the actions of an agent whose chances are unknown: the rule bots (`tag` and the
  others), B0 and any Python agent. Their actions stay as they are; they still get the
  correction for the cards and the deal, which is all a hand tracker could do for them.

**Why it has no bias, by construction.** Given everything before an event, its correction
averages exactly 0, whatever `v` is: the outcome is drawn with the chances `P`, so the first
term averages to the second. So every hand's corrected score has the same expected value as
its real result, and no agent's expected win rate moves. The argument needs only three
things, each checked or enforced in the code:

1. The chances are the real ones. For the cards this is how the arena deals (the deck is
   every card not in a hand, folded ones too, and not on the board). For an agent, the
   action must have been drawn with the chances it reports, from a random number nothing else
   depends on: `View::pick` does exactly that, and the blueprint and search adapters use it.
   An action that is not among the reported chances, or chances that include an illegal
   action, are not used, and the report counts them (`unexplained_decisions`: above 0 means a
   bug in the agent).
2. `v` after each outcome is a fixed function of the situation (every card, which the arena
   knows, the chips, the betting so far), not of the random number that picked the outcome.
   It can be as rough as it likes: a poor `v` takes out less luck, it never moves the average.
   That is why AIVAT may use every player's cards: it is the arena that computes it, not an
   agent.
3. The answers used to value an action (below) depend only on the situation asked about,
   not on what happened in the hand (`Player::chances_at`'s contract).

The preflop values are averages over 2,000 random boards, drawn from a seed of the deal's own
(the same in every replay), so they are estimates with no bias of the exact average, and the
flop's correction, which compares the exact flop value with that estimate, still averages 0
(a test checks it).

**The value estimate `v`.** The check-down value: each seat's share of the chips in the
middle if nobody bet again and the hand were shown down, averaged over every board still to
come, minus what it put in. Exact on the flop, turn and river, 2,000 boards before the flop
(`--aivat-boards`). Side pots are paid as at the table and ties split exactly. A bet still to
be answered is valued as `--aivat-facing` says:

- `minimum-defense` (the default): each player facing it calls with the chance `P / (P + r)`
  and folds otherwise, each on its own (`r`: what it must add to call, `P`: the chips in the
  middle at its own level). With it a bet that never wins at a showdown is worth exactly as
  much as giving up, as against an opponent that defends just enough.
- `taken-back`: only the chips everyone matched are checked down.
- `called`: everyone facing it calls. Clearly worse: it values every bluff as a loss.

And an action is valued one step further when the next player to act can say what it would
play there (`Player::chances_at`): the value after each of its answers, averaged with its
chances. The blueprint can, and so can `mixed`; the search agent says no (an answer would cost
a search), and so do B0 and the rule bots. Against a known strategy a bet is then worth what
that strategy's folds and calls make it worth, not what the minimum defense frequency guesses.

**What it gains.** SE of AIVAT over the SE of the main figure (duplicate play and all-in
equity already applied), heads-up:

| Match | Chances known | Deals | AIVAT SE over the main SE | Over plain play's SE |
| --- | --- | ---: | ---: | ---: |
| 20bb blueprint (64M iterations) against a copy of itself, two seeds | Both | 1,000,000 each | 0.610, 0.611 | 0.318 |
| 64M against the same run's 16M file | Both | 1,000,000 | 0.618 | 0.331 |
| 64M against the 4M file | Both | 1,000,000 | 0.635 | 0.349 |
| SEARCH_ROW |
| 64M against `tag` | The blueprint's | 200,000 | 0.790 | 0.641 |
| `tag` against `tag`, 20bb | Neither: cards only | 1,000,000 | 0.807 | 0.142 |
| `mixed` against `mixed`, 100bb | Both | 100,000 | 0.695 | 0.516 |
| `tag` against `mixed-loose`, 100bb | `mixed-loose`'s | 100,000 | 0.890 | 0.749 |
| `tag-loose` against `tag`, 100bb | Neither: cards only | 100,000 | 0.884 | 0.443 |

The blueprint rows are the pre-registered checks of `docs/research/experiments.md` ("Phase 7:
AIVAT in the arena"); the bot rows at 100bb are pilots (seed 3).

The hands needed for a given SE shrink by the square of the ratio. Cards-only AIVAT (agents
with unknown chances) gains least; it is the agents' own random choices, and the bets valued
by real answers, that carry most of it.

**What it costs.** COST_TEXT

**Choices made on pilots, then frozen.** Valuing bets as called, taken back or by the minimum
defense frequency, and the answers: `docs/research/experiments.md`, "Phase 7: AIVAT in the
arena", with the checks that show it unbiased (pre-registered there before they ran).

## The report

`report.save(path)` writes JSON (`MatchReport::load` reads it back):

| Field | What |
| --- | --- |
| `format` | `"pokerscribe-arena/1"` |
| `config` | The settings: `lineup`, `stack`, `small_blind`, `big_blind`, `ante`, `deals`, `seed`, `duplicate`, `all_in_equity`, `max_runouts`, `shared_randomness`, `threads`, `aivat` (`null`, or its `boards` and `facing`) |
| `scoring` | The scorer's name, such as `"all-in equity (at most 10000 boards)"` |
| `aivat_scoring` | AIVAT's settings in words, or `null` without AIVAT |
| `agents` | The agents' names; the lineup holds indexes into this list |
| `players`, `deals`, `replays_per_deal`, `hands` | Table size, deals, replays of each deal, hands played |
| `adjusted_hands` | Hands whose score differs from the real chips |
| `results` | One entry per agent, below |
| `timing` | `seconds`, `hands_per_second`, `threads`. The only part that changes between two runs of the same match |

Each entry of `results`:

| Field | What |
| --- | --- |
| `index`, `agent`, `seats`, `hands` | Which agent, how many seats it holds, hands it played counting each seat |
| `bb_per_100`, `se` | The win rate per seat held and its SE, after the luck reduction of the match. `se` is `null` with fewer than 2 deals |
| `actual_bb_per_100`, `actual_se` | The same match in real chips, before the scorer's adjustment |
| `plain_se` | The SE plain play would give over the same number of hands: real chips, every hand its own sample |
| `illegal_actions` | Illegal actions it returned |
| `aivat` | `null` without AIVAT, otherwise: `bb_per_100` and `se` (AIVAT's figure), `minus_main` and `minus_main_se` (AIVAT minus `bb_per_100` deal by deal), `se_ratio` (`se` over the main `se`), `corrected_decisions`, `unknown_decisions`, `unexplained_decisions` (its decisions corrected, without known chances, and with chances that can't be right) |
| `by_seat` | For each seat: `seat`, `position` (`BTN`, `SB`, `BB`, `UTG`, `HJ`, `CO`; heads-up `BTN/SB` and `BB`), `hands`, `bb_per_100`, `se` |

## Test bots

In `src/bots.rs`. None is meant to play well.

| Name | Plays |
| --- | --- |
| `fold` | Checks when it is free, folds to any bet |
| `call` | Checks or calls, never raises |
| `raise`, `minraise`, `jam` | Bets or raises whenever it may: by the pot, by the minimum, or all in |
| `random` | Fold, check or call, and raise with equal chances; a raise goes to an amount drawn evenly between the minimum and a pot-sized raise |
| `tag` | Tight-aggressive rules. Before the flop: the Chen score of its two cards against a bar that rises with the players still to act; opens for 2.5 big blinds, re-raises its best hands. After the flop: the share of the other possible hands it beats right now; bets or raises strong hands, calls when the price fits its strength, folds the rest, and bets the flop half the time after raising before it |
| `tag-loose` | `tag` with a bar one point lower before the flop. It stands in for "the next version" |
| `mixed` | A mixed strategy whose chances are known, for testing AIVAT. With `s` the strength of its hand (the Chen score scaled to 0 to 1 before the flop, `tag`'s hand strength after it), it weighs fold `3 (1 - s)^2` (when there is a bet), check or call 1, raises of half the pot, the pot and all in `s^2`, `s^3` and `s^6`, draws one with `view.pick`, and reports the weights |
| `mixed-loose` | `mixed` with half the weight on folding |

Heads-up, tag beats call by 222 bb/100, random by 73 and raise by 136, and tag-loose beats
tag by 11 (400,000 hands each). tag is not strong: jam beats it by 10 bb/100 (SE 1.7 over
200,000 hands), because tag folds too much to an all-in.

## Tests

```bash
cargo test -p arena              # 40 tests, about 2.5 minutes (most of it the AIVAT tests)
cargo test --release -p arena    # the same in about 15 seconds
cargo clippy -p arena --all-targets
```

`tests/matches.rs`:

| Test | Checks |
| --- | --- |
| `identical_agents_give_zero_within_the_standard_error` | Two copies of the same bot (random, tag), heads-up and six-max, plain and duplicate, three seeds: the win rate is within 3 SE of 0 in all 24 matches |
| `identical_agents_without_randomness_give_exactly_zero_in_duplicate` | call, raise and fold against themselves: exactly 0 with SE 0. With shared randomness the same holds for random and tag |
| `a_better_bot_beats_a_worse_one` | call beats fold; tag beats call and random heads-up, and fold and call at six-max: by more than 4 SE each. No rake: the two sides add up to 0 |
| `duplicate_and_all_in_equity_cut_the_standard_error` | tag-loose against tag over the same number of hands: the SE is at least 1.6 times smaller heads-up (measured 2.08) and 1.3 times at six-max (1.90), the report's own `plain_se` agrees with the plain run, and both runs measure the same win rate |
| `all_in_equity_alone_cuts_the_standard_error_and_keeps_the_mean` | raise against random in plain play: 15% of hands adjusted, SE 32.4 to 23.6, same win rate |
| `the_same_seed_gives_the_same_result` | Twice the same; 1, 2 and 3 threads the same to the last bit; another seed differs; a longer match starts with the same deals |
| `heads_up_duplicate_plays_each_deal_twice_with_the_seats_swapped`, `six_max_duplicate_seats_b_in_every_seat_in_turn`, `any_mix_of_agents_visits_every_seat`, `plain_play_moves_the_lineup_one_seat_a_deal` | Who sat where with which cards, hand by hand |
| `the_report_adds_up`, `the_report_saves_to_json_and_loads_back`, `bad_settings_are_refused` | Counts, seat names, seats averaging to the overall result, the JSON fields, refused settings |
| `an_illegal_action_becomes_a_check_or_a_fold_and_is_counted`, `the_test_bots_only_make_legal_actions` | An always-illegal player scores exactly as `fold` does; the eight bots never return an illegal action, at 3 and 100 big blinds |
| `a_player_sees_its_own_cards_and_only_public_things`, `players_can_be_structs_or_closures`, `pick_follows_the_weights` | The view from inside a match |
| `a_custom_scorer_is_the_hook_for_aivat` | The report is built from what a custom scorer returns |

`tests/aivat.rs`:

| Test | Checks |
| --- | --- |
| `a_card_correction_averages_zero_over_every_card_that_can_come` | 300 random hands (2 to 6 players, uneven stacks, antes) stopped when the flop's or the turn's betting ends: the check-down value averaged over every next card is the value before it, exactly, and the values add up to 0 |
| `the_flop_correction_averages_zero_and_the_sample_before_it_has_no_bias` | The flop's check-down value over all 17,296 flops averages to the exact value before the flop; 40 estimates from 2,000 boards each average to it within their spread |
| `the_check_down_value_on_the_river_pays_like_the_engine` | Over 1,000 random showdowns (side pots, folded players, ties) the river's check-down value is what nlhe pays, to within the odd chips the engine hands out whole |
| `a_bet_still_to_be_answered_is_valued_as_the_rule_says` | The big blind before the small blind acts, a bluff and a value bet, worked out by hand under each rule; a bluff that never wins is worth as much as giving up under the minimum defense frequency |
| `the_deal_correction_averages_zero` | The value at the start of 6,000 random deals averages, within its SE, to the even shares the deal correction subtracts, at 2, 3 and 6 players |
| `identical_agents_give_zero_with_aivat` | `mixed` against itself, heads-up and three-handed, duplicate and plain, three seeds: AIVAT and AIVAT minus the main figure within 3 SE of 0; exactly 0 with shared randomness |
| `aivat_agrees_with_the_main_figure_and_narrows_it` | Five pairs of bots, heads-up and six-max, with and without known chances: AIVAT minus the main figure within 3.5 SE, the results add up to 0, only agents with known chances get their decisions corrected, and the SE is smaller for `mixed` |
| `answers_narrow_aivat_and_wrong_answers_do_no_harm` | With `mixed`'s answers the SE is smaller than without; a player that gives wrong answers still gets an AIVAT figure that agrees with the main one, and two of them give about 0 |
| `chances_that_cannot_be_right_are_not_used_and_are_counted` | A player that reports chances it did not play with is never corrected and is counted as unexplained |
| `aivat_repeats_on_any_number_of_threads_and_saves_to_json` | 1, 2 and 3 threads the same to the last bit; the JSON fields; a report from before AIVAT still loads |
| `aivat_is_a_scorer_too_and_its_scores_add_up_to_zero` | As the main scorer it gives the figure it gives next to it; one hand's scores add up to 0 |

`tests/equity.rs`:

| Test | Checks |
| --- | --- |
| `pots_pay_every_showdown_like_the_engine` | 20,000 random hands, 2 to 6 players, uneven stacks, antes: the arena's pots pay every seat what nlhe pays (over 1,000 hands with side pots and over 100 with odd chips are required) |
| `all_in_equity_equals_replaying_every_board` | 72 random all-ins on the flop and turn with side pots and folded players: the equity equals the same betting replayed in the nlhe engine on every possible board, paid by nlhe's slow ranker |
| `folded_cards_are_out_of_the_deck` | Kings all in against aces with the other two kings folded: no equity at all |
| `preflop_equity_over_every_board` | Mirror-image hands are worth exactly 0; aces against kings equals a count written as five plain loops over all 1,712,304 boards |
| `sampled_equity_is_close_repeatable_and_seeded` | Same seed, same boards; the mean of 400 samples closes in on the exact value; the flop is exact whatever the cap |
| `no_adjustment_without_cards_to_come`, `blinds_that_put_everyone_all_in_count_as_a_runout`, `the_scorer_leaves_other_hands_alone_and_reuses_a_deal`, `the_eval_ranker_orders_hands_like_the_brute_force_one` | The edges: all in on the river, a fold, blinds larger than the stacks, the answer kept for a deal, the adapter from `eval` to nlhe's `HandRanker` |

## Standard errors

```bash
cargo run --release -p arena --example variance
```

26 Nov 2026, seed 2026, 100 big blinds deep. Every column of a row is over the same number
of hands, and all are standard errors in bb/100 except the first and the last. "Plain" is
real chips with one seating a deal. The equity uses the default 10,000 boards.

Heads-up, 400,000 hands a cell (200,000 deals when duplicate):

| Match | bb/100 | Plain | Plain + equity | Duplicate | Duplicate + equity | + shared randomness | Plain over duplicate + equity | All-in hands |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tag-loose against tag | +11.4 | 0.84 | 0.71 | 0.49 | 0.42 | 0.41 | 1.99 | 0.2% |
| tag against tag | -0.1 | 0.73 | 0.61 | 0.09 | 0.09 | 0.00 | 8.55 | 0.2% |
| random against random | +0.2 | 3.09 | 2.96 | 3.04 | 2.92 | 0.00 | 1.06 | 0.6% |
| tag against random | +72.9 | 1.73 | 1.57 | 1.70 | 1.54 | 1.54 | 1.12 | 0.5% |
| tag against call | +221.9 | 1.61 | 1.61 | 1.44 | 1.44 | 1.43 | 1.12 | 0.0% |
| tag against raise | +135.5 | 3.14 | 2.42 | 3.07 | 2.38 | 2.38 | 1.32 | 3.5% |
| raise against random | +1092.8 | 7.24 | 5.32 | 6.74 | 5.11 | 5.12 | 1.42 | 15.0% |

Six-max, one agent against five of the other, 600,000 hands a cell (100,000 deals when
duplicate). The win rate and the SE are the lone agent's:

| Match | bb/100 | Plain | Plain + equity | Duplicate | Duplicate + equity | + shared randomness | Plain over duplicate + equity | All-in hands |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tag-loose against 5 tag | +2.2 | 1.00 | 0.84 | 0.59 | 0.51 | 0.50 | 1.96 | 1.0% |
| tag against 5 tag | +0.0 | 0.88 | 0.73 | 0.07 | 0.07 | 0.00 | 12.81 | 1.0% |
| random against 5 random | -4.7 | 10.03 | 6.83 | 9.68 | 6.74 | 0.00 | 1.49 | 32.7% |
| tag against 5 random | +157.7 | 3.05 | 2.25 | 2.99 | 2.18 | 2.20 | 1.40 | 22.1% |
| tag against 5 call | +659.2 | 6.92 | 6.64 | 6.47 | 6.22 | 6.22 | 1.11 | 0.5% |
| raise against 5 tag | -724.1 | 4.96 | 3.72 | 7.73 | 6.86 | 6.86 | 0.72 | 13.4% |

What the tables say:

- For two versions of the same agent (the first row of each table), duplicate plus all-in
  equity halves the SE. Half the SE is worth four times the hands: a gap that plain play
  shows at 2.5 SE after 4 million hands shows after 1 million.
- The closer the agents, the more duplicate play does: 12.8 times for identical agents at
  six-max, 2 times for tag-loose against tag, 1.1 times for agents as different as tag and
  call. Duplicate removes the luck of the cards only as far as both agents do similar
  things with the same cards.
- All-in equity does more the more hands end all in before the river: nothing when 0% do
  (tag against call), a quarter off the SE at 3.5% (tag against raise), a third off at
  six-max with random bots.
- Duplicate play does nothing for random against random heads-up (3.09 to 3.04): what
  random does has nothing to do with its cards.
- One case where duplicate play hurts: raise against 5 tag, 0.72. The raiser's result
  hangs on whether one of the tags holds a big hand, not on its own cards. The six replays
  of a deal keep the same cards in the same seats, so a deal that is bad for the raiser is
  bad five or six times over, and six replays tell less than six fresh deals. The SE the
  report gives is still right, only larger. Every report carries `plain_se` next to `se`:
  when `se` is not well below it, run that match with `--plain`.

## Speed

```bash
cargo run --release -p arena --example speed
```

26 Nov 2026, in a cloud container (Intel Xeon @ 2.10 GHz, 4 cores), Rust 1.97, release
build. Duplicate play and all-in equity over at most 10,000 boards unless the row says
otherwise.

| Match | Hands | Hands/s, 1 thread | Hands/s, 4 threads | All-in hands |
| --- | --- | --- | --- | --- |
| Heads-up, call against call, plain | 2,000,000 | 1,161,000 | 4,271,000 | 0.0% |
| Heads-up, tag against call | 1,000,000 | 88,000 | 333,000 | 0.0% |
| Heads-up, tag-loose against tag | 1,000,000 | 549,000 | 2,106,000 | 0.2% |
| Heads-up, tag against random | 500,000 | 239,000 | 864,000 | 0.5% |
| Heads-up, tag against raise | 500,000 | 177,000 | 685,000 | 3.5% |
| Heads-up, tag against raise, every board | 40,000 | 8,200 | 31,000 | 3.5% |
| Six-max, tag-loose against 5 tag | 600,000 | 266,000 | 1,033,000 | 0.9% |
| Six-max, tag against 5 random | 600,000 | 22,600 | 89,000 | 22.3% |
| Six-max, tag against 5 random, every board | 30,000 | 1,370 | 5,500 | 22.2% |

The arena itself costs under a microsecond a hand (the first row: the deal, the betting, the
showdown and the sums). The rest is the bots: tag works out its hand strength at every
decision after the flop, and against call every hand reaches the river. Four threads give
3.6 to 4 times one thread.

| All-in equity, one hand | Time |
| --- | --- |
| Heads-up before the flop, all 1,712,304 boards | 13.9 ms |
| Heads-up before the flop, 10,000 boards | 0.29 ms |
| Heads-up before the flop, 1,000 boards | 0.03 ms |
| Heads-up on the flop, all 990 boards | 4.5 µs |
| Heads-up on the turn, all 44 boards | 0.3 µs |
| Six players before the flop, all 658,008 boards | 12.6 ms |
| Six players before the flop, 10,000 boards | 0.45 ms |
| Six players on the flop, all 666 boards | 13.0 µs |

## Things to know

1. Before the flop the all-in equity is an average over 10,000 random boards by default,
   not over all of them. The SE of a match is the same to three digits either way (see
   "Luck reduction"). `--exact-equity` counts every board at 10 to 15 ms a hand.
2. Duplicate play is not always a gain at six-max, one against five: see the last row of
   "Standard errors". Compare `se` with `plain_se`.
3. Stacks are the same in every seat and are reset every hand. There is no rake. The button
   never moves; the agents do.
4. Results repeat exactly only if the players decide from the view alone. A player that
   learns between hands (B0 with profiles) needs `threads: 1` to repeat, and its duplicate
   replays are no longer the same match played twice.
5. An agent with several seats gets a win rate per seat. In a two-agent match the z value
   has the same size on both sides, with the sign turned.
6. The SE treats the win rate as normal, as every bb/100 figure does. With few deals and
   rare huge pots the true spread is wider than the SE says. The 24 identical-agent matches
   of the tests, a few thousand hands each, stay within 1.9 SE.
7. AIVAT is reported, not used to judge: the gates read the main figure until the checks in
   `docs/research/experiments.md` ("Phase 7: AIVAT in the arena") show it unbiased. Its
   corrections for an agent's own choices are only as honest as the chances the agent
   reports; `unexplained_decisions` above 0 means they can't be right.
8. Not built yet: uneven stacks, and a hand history file. A `Scorer` sees every finished hand
   and could write one. The bridge to Python for B0 is built (`engine/crates/py`).

## Layout

| File | What |
| --- | --- |
| `src/player.rs` | `Player`, `View`, `Agent` |
| `src/hand.rs` | `play_hand`: one hand between players, illegal actions replaced and counted; `play_hand_recorded` keeps the chances each player reported (`Decisions`) |
| `src/runner.rs` | `MatchConfig`, `run_match`: rotations, seeds, threads, the sums and the SE |
| `src/equity.rs` | `Pots` (showdown pots as nlhe pays them) and `all_in_equity` |
| `src/luck.rs` | `Scorer`, `HandRecord`, `ActualChips`, `AllInEquity` |
| `src/aivat.rs` | `Aivat`: the AIVAT scorer, its check-down values and `Facing` |
| `src/report.rs` | `MatchReport`, its JSON and its text table |
| `src/bots.rs` | The test bots, the Chen score, hand strength |
| `src/ranker.rs` | `EvalRanker` (nlhe's own, the `eval` crate behind its `HandRanker`, re-exported) and `to_eval`, an nlhe card as an `eval` card |
| `src/bin/arena.rs` | The command line |
| `examples/variance.rs`, `examples/speed.rs` | The tables above |
| `tests/` | `matches.rs`, `equity.rs` and `aivat.rs` |
