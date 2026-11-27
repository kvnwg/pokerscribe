# lbr: local best response (Phase 5)

Local best response (LBR) measures how exploitable a heads-up No-Limit Hold'em strategy is. It
plays against the strategy, reads it, and takes what a simple greedy rule can take. What LBR
wins is a lower bound on what a perfect opponent would win, so a lower LBR win rate means a
stronger strategy. The method is from Lisy and Bowling 2017, "Equilibrium Approximation Quality
of Current No-Limit Poker Bots" (arXiv 1612.07547), called "the paper" below.

Status, 26 Nov 2026: built, and checked against the paper and against exact results. Nothing
uses it yet. The blueprint (Phase 6) will implement `Strategy`, and the roadmap's gates read
"LBR falls at every checkpoint".

| Check | Result |
| --- | --- |
| Always fold (the paper's text: 750 mBB per hand) | 75.0 bb/100, exact, whenever LBR may bet. |
| Always call (the paper's Table 2) | Fold and call only: 0, exact, as in the paper. With pot and all in: 4,861 ± 22 on rounds 3-4 and 3,363 ± 22 on rounds 1-4, against the paper's 4,900 ± 20 and 3,400 ± 26. |
| Random legal action (Table 2) | All four cells within 1.3 standard errors of the paper. With pot and all in on rounds 3-4: 8,088 ± 41 against 8,070 ± 36. |
| Half call, half raise (Table 2) | One cell of four agrees. Not explained: "Things to know", 1. |
| Always raise (not in the paper) | Minimum raise 4,768 ± 22, pot-sized raise 3,890 ± 23 (pot and all in, rounds 3-4). Always all in: 1,513 ± 31 when LBR thinks before the flop. |
| Win probability against plain enumeration | Equal to 1e-12 on the flop, turn and river, with a second evaluator. The exact preflop table equals direct enumeration to 1e-12. |
| Perfect play, closed form (the AKQ river game) | LBR's exact expected winnings are the value of the game in each seat: +50 and -50 chips, 0 over the two seats, to 1e-9. Each of four mistakes by the opponent gives LBR exactly a quarter of the pot. |
| Perfect play, solved (a river spot, 14 hands a side that block each other) | In position LBR equals the exact best response to 1e-9. Over the two seats it wins 0.0001 chips in a pot of 200, inside the solution's own distance from equilibrium (0.00015). |
| Speed, 4 cores | Rounds 3-4: 13,000 to 28,000 hands per second against the trivial strategies. Rounds 1-4: 1,800 and up (1,800 when every hand sees a flop), after 171 s once for the exact preflop table. |

All win rates are LBR's, in big blinds per 100 hands, ± one standard error, over 100,000 hands.

## Use

```bash
cd engine
```

```bash
cargo test -p lbr
```

```bash
cargo test --release -p lbr -- --ignored
```

```bash
cargo run --release -p lbr --example paper_table -- --preflop
```

- The first test command takes about 30 seconds in a debug build. The second runs the three
  slow tests (the exact preflop table and the 100,000-hand comparisons with the paper):
  about 5 minutes in a release build.
- The example prints the table under "Results". Options: `--hands N` (100,000), `--seed S`,
  `--preflop` (add the settings where LBR thinks on every street, with the exact preflop
  table), `--sampled BOARDS` (add them with sampled preflop win probabilities instead).

To measure a strategy, implement `Strategy` for it and play a match:

```rust
use lbr::{play_match, ActionProbs, LbrConfig, MatchConfig, PublicState, Strategy};
use nlhe::{Action, Card};

struct Blueprint { /* ... */ }

impl Strategy for Blueprint {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        // public.history(), public.board(), public.legal_actions(), public.pot(), ...
        out.push(Action::Call, 0.7);
        out.push(Action::RaiseTo(300), 0.3);
    }
}

// 100,000 hands at the paper's table: blinds 50 and 100, stacks of 200 big blinds.
let result = play_match(&blueprint, &LbrConfig::default(), &MatchConfig::acpc(100_000, 1));
println!("{result}"); // "+123.4 ± 5.6 bb/100 over 100000 hands (button ..., big blind ...)"
```

Units: `bb_per_100` is big blinds won by LBR per 100 hands. The paper uses mBB per hand (divide
by 10 to get bb/100) and BB per hand (multiply by 100).

## What LBR does

This is the paper's Figure 1.

1. Range. At the start the opponent is equally likely to hold any two cards LBR does not hold.
   After each opponent action, every hand's weight is multiplied by the probability the
   opponent's strategy gives that action with that hand (Bayes' rule). Hands that share a card
   with the board are dropped as the board comes. No abstraction: all 1,326 hands are tracked.
2. Win probability (`wp`). The chance LBR's hand wins a showdown against that range if the
   rest of the board is dealt and nobody bets again. Every possible rest of the board is
   dealt, and a tie counts as half a win.
3. Value of each action, with folding worth 0. `pot` is everything in the middle and `asked`
   is what LBR must add to call:
   - call (or check): `wp * pot - (1 - wp) * asked`
   - a bet or raise of `a` on top of the call: `fp * pot + (1 - fp) * (wp' * (pot + a) -
     (1 - wp') * (asked + a))`, where `fp` is the probability that the opponent folds to it
     (their strategy's fold probability, averaged over the range) and `wp'` is the win
     probability against the hands that do not fold.
4. LBR takes the action with the highest value if that value is above 0, and folds otherwise.
   Among equal values it takes the first of: call, then the bets from small to large.

So LBR looks one action ahead: the opponent folds as their strategy says, and otherwise the
hand is checked down. It is not a best response, and a good strategy can beat it (the paper's
own "full cards" bot beat it by 536 mBB per hand). It is a legal way to play, so what it wins is
always a lower bound.

Two details the paper leaves open, as done here:

- With unequal stacks, only the chips the shorter stack can match count as won or lost.
- When check is free, LBR never folds (the rules engine does not allow it): if no action is
  worth more than 0 it checks.

## Settings

The paper names a setting by its bets and by the rounds where LBR thinks. In the other rounds
it always checks or calls (and still tracks the range).

| Paper | Here | Bets LBR weighs |
| --- | --- | --- |
| fc | `LbrConfig::fc(first)` | fold, call |
| fcpa | `LbrConfig::fcpa(first)` | fold, call, pot, all in |
| 56 bets | `LbrConfig::bets56(first)` | fold, call, all in and the 55 pot fractions `0.05 * 1.15^k`, k = 0 to 54 (5% of the pot to 95 pots) |
| on-tree | `LbrConfig::new(&bets, first)` | fold, call and any list of `BetSize::Pot(fraction)` and `BetSize::AllIn` |
| rounds 1-4 | `first = Street::Preflop` | LBR thinks on every street |
| rounds 3-4 | `first = Street::Turn` | check or call before the flop and on the flop |

- `LbrConfig::default()` is "fcpa, rounds 3-4". In the paper most of what LBR won from every
  bot came with this setting, and waiting until the turn won far more than starting before
  the flop. `LbrConfig::paper_settings()` lists the five settings the paper ran against every
  bot; report the largest win rate over them.
- `streets` is public: one `StreetPolicy` per street, so any mix can be set (DeepStack's
  tables use fold and call before the turn, for example).
- A pot fraction is of the pot after LBR's call, so `Pot(1.0)` is the usual pot-sized raise.
  A size below the minimum bet becomes the minimum bet, and one above the stack becomes all
  in, as in the paper. Equal sizes are weighed once.
- `preflop_equity` only matters when LBR thinks before the flop. `PreflopEquity::Exhaustive`
  (the default, the paper's way) deals all 2,118,760 boards against all 1,225 hands: about
  2 billion evaluations for each of the 169 starting-hand classes, kept for the life of the
  process (171 seconds for all of them on 4 cores). `PreflopEquity::Sampled { boards }`
  deals that many random boards per hand: no start-up cost and the only practical choice in
  a debug build, at the price of a little noise (see "Things to know", 3).

## The interface

| Item | What |
| --- | --- |
| `Strategy` | `action_probs(public, hole, out)`: the probability of each legal action for the player to act holding `hole`. A raise is `Action::RaiseTo(amount)`. Optional `action_prob_for_range(public, action, hands, out)`: one action's probability for many hands at once. LBR only calls this one (once per opponent action and once per bet it weighs, about 1,100 hands each time), and the default asks `action_probs` hand by hand. Override it when work can be shared across hands. |
| `PublicState` | What both players see: betting history, stacks, bets, pot, board cards face up, legal actions. It wraps an nlhe `State` and hides the hole cards and the cards to come, so a strategy cannot peek. |
| `Lbr` | One seat of one hand. `observe(state, action)` before each opponent action is applied, `act(state)` for LBR's own, `evaluate(state)` for the action with the win probability and the value of every option. `Lbr::with_range` starts from a given range (for play from the middle of a hand). |
| `play_match(strategy, lbr_config, match_config)` | N hands on all cores. Returns `MatchResult { hands, bb_per_100, std_err, button_bb_per_100, big_blind_bb_per_100 }`. |
| `play_hand` | One hand from a seed. |
| `win_probability(hole, board, range)`, `showdown_equities`, `preflop_equities`, `preflop_equities_sampled` | The win probability on its own, and the table of equities against each of the 1,326 hands. |
| `Range` | A weight per hand: `uniform`, `from_hands`, `set`, `weight`, `remove_cards`, `normalize`. |
| `EvalRanker` | The eval crate's evaluator as an nlhe `HandRanker`: nlhe's own (`nlhe::EvalRanker`), re-exported. |
| `AlwaysFold`, `AlwaysCall`, `AlwaysRaise`, `CallOrRaise`, `UniformRandom` | The trivial strategies of the tests. |

How a match is played:

- Each deal is played twice, once with LBR on the button and once in the big blind. The cards
  stay with the positions, so the two players swap hands (a duplicate match, as in the paper).
  Stacks are reset every hand.
- The standard error treats the two hands of a deal as one observation. The luck of the deal
  partly cancels inside it.
- Everything comes from `MatchConfig::seed`: the cards (nlhe's seeded deal), the opponent's
  sampled actions and LBR's sampled preflop boards. The result is the same on any number of
  cores (a test checks 1 core against all).
- The opponent's action is drawn from `action_probs` for the hand it really holds. LBR never
  sees that hand.

## Results

### Trivial strategies, against the paper

Every row: 100,000 hands (50,000 deals, each played from both seats), seed 20261126, blinds 50
and 100, stacks of 200 big blinds, as in the paper. ± is one standard error. The paper gives
95% intervals in BB per hand; they are shown here as standard errors in bb/100 (the interval
over 1.96, times 100). "Apart by" is the difference over the standard error of the difference.

| Strategy | LBR setting | LBR wins (bb/100) | Paper (bb/100) | Apart by |
| --- | --- | ---: | ---: | ---: |
| always fold | fcpa, rounds 1-4 | +75.0 ± 0.0 | 75 | exact |
| always fold | fcpa, rounds 3-4 | +75.0 ± 0.0 | 75 | exact |
| always call | fc, rounds 1-4 | +0.0 ± 0.0 | 0 | exact |
| always call | fc, rounds 3-4 | +0.0 ± 0.0 | 0 | exact |
| always call | fcpa, rounds 1-4 | +3,362.9 ± 22.0 | 3,400 ± 26 | 1.1 SE |
| always call | fcpa, rounds 3-4 | +4,860.6 ± 22.5 | 4,900 ± 20 | 1.3 SE |
| random action | fc, rounds 1-4 | +1,534.4 ± 29.1 | 1,570 ± 20 | 1.0 SE |
| random action | fc, rounds 3-4 | +171.2 ± 10.5 | 220 ± 36 | 1.3 SE |
| random action | fcpa, rounds 1-4 | +3,920.5 ± 36.7 | 3,910 ± 31 | 0.2 SE |
| random action | fcpa, rounds 3-4 | +8,088.5 ± 41.2 | 8,070 ± 36 | 0.3 SE |
| 1/2 call, 1/2 raise | fc, rounds 1-4 | +1,721.1 ± 24.2 | 710 ± 26 | 28.5 SE |
| 1/2 call, 1/2 raise | fc, rounds 3-4 | +715.0 ± 23.0 | 1,620 ± 15 | 33.0 SE |
| 1/2 call, 1/2 raise | fcpa, rounds 1-4 | +2,288.2 ± 28.7 | 2,310 ± 26 | 0.6 SE |
| 1/2 call, 1/2 raise | fcpa, rounds 3-4 | +2,193.6 ± 21.0 | 2,440 ± 31 | 6.6 SE |

The strategies:

- Always fold: folds to any bet and checks when checking is free. On the button LBR calls, the
  big blind checks, and LBR's first bet wins the pot (1 BB). In the big blind LBR wins the
  small blind at once (0.5 BB). The average is the paper's 750 mBB per hand, with no luck in
  it.
- Always call: with fold and call only, every hand is checked down and the two seats of each
  deal cancel exactly. With bets, a true best response waits for the river and wins 5,000
  (the paper's 50 BB per hand). LBR moves all in as soon as it is ahead: 4,861 from the turn
  on, 3,363 from before the flop.
- Random action (`UniformRandom::Actions`): every legal action is equally likely, each raise
  amount counting as one action. See "Things to know", 2.
- 1/2 call, 1/2 raise (`CallOrRaise`): checks or calls half the time, otherwise raises to an
  amount drawn evenly from the legal range. See "Things to know", 1.

### All strategies and settings

The same 100,000 hands. Always raise and the second kind of random are not in the paper.

| Strategy | fc, 1-4 | fc, 3-4 | fcpa, 1-4 | fcpa, 3-4 | 56 bets, 1-4 | 56 bets, 3-4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| always fold | +25.2 ± 0.2 | +25.2 ± 0.2 | +75 ± 0 | +75 ± 0 | +75 ± 0 | +75 ± 0 |
| always call | 0 ± 0 | 0 ± 0 | +3,363 ± 22 | +4,861 ± 22 | +3,363 ± 22 | +4,861 ± 22 |
| 1/2 call, 1/2 raise | +1,721 ± 24 | +715 ± 23 | +2,288 ± 29 | +2,194 ± 21 | +2,288 ± 29 | +2,194 ± 21 |
| random action | +1,534 ± 29 | +171 ± 10 | +3,920 ± 37 | +8,088 ± 41 | +4,800 ± 38 | +8,147 ± 41 |
| random kind of action | +1,429 ± 24 | +593 ± 26 | +2,201 ± 33 | +4,978 ± 37 | +3,386 ± 35 | +5,548 ± 37 |
| always raise, minimum | +7.0 ± 0.3 | +6.4 ± 0.2 | +3,299 ± 22 | +4,768 ± 22 | +3,299 ± 22 | +4,768 ± 22 |
| always raise, pot | +1,238 ± 10 | +1,194 ± 10 | +2,716 ± 26 | +3,890 ± 23 | +2,716 ± 26 | +3,890 ± 23 |
| always raise, all in | +1,513 ± 31 | 0 ± 0 | +1,513 ± 31 | 0 ± 0 | +1,513 ± 31 | 0 ± 0 |

- Against a strategy that never folds, LBR only ever uses its largest bet, so fcpa and 56
  bets give the same hands and the same number. The 56 bets earn more where a fold can be
  bought cheaply (the two random strategies).
- Always raise, minimum: with fold and call only LBR gets such good odds that it almost never
  folds, and wins almost nothing. With bets it plays as against always call.
- Always raise, all in: on rounds 3-4 LBR must call before the flop with any hand, so every
  deal is a showdown and the two seats cancel. Thinking before the flop, it calls with the
  hands that are ahead of a random hand and wins 1,513. A setting is only a lower bound:
  try several.
- Random kind of action (`UniformRandom::Kinds`): fold, check or call, and raise with a third
  each.

### Perfect play

Against a strategy that plays perfectly LBR should win nothing. Three games small enough to
know the perfect strategy (`tests/perfect_play.rs`):

1. The AKQ game, closed form. River, board 2c 2d 2h 7s 8s, 200 in the pot and 200 behind.
   The button holds aces or queens, the big blind kings. The solution: kings check and call a
   bet with probability pot / (pot + bet); aces bet; queens bluff with probability
   bet / (pot + bet). LBR's expected winnings are computed exactly (no sampling) over all 72
   deals. With all in only, with fcpa and with the 56 bets it wins +50.000000 chips on the
   button and -50.000000 in the big blind: the value of the game in each seat, and 0 over the
   two. If the opponent calls every bet, folds to every bet, always bluffs or never bluffs,
   LBR wins exactly 50 chips (a quarter of the pot) over the two seats.
2. A solved river spot. Board Kh Th 7s 4c 2d, 14 hands a side, kings, tens and aces in both
   ranges, so each hand changes what the other can hold. Check or bet all in (the pot), fold
   or call. Solved by the cfr crate's CFR+ (3,000 iterations) to 0.00015 chips from
   equilibrium, measured by its exact best response. On the button LBR wins +26.966366, the
   exact best response's value to 1e-9: last to act, with one bet size, one action ahead is
   the whole game. In the big blind it wins -26.966255 against the best response's
   -26.966219. Over the two seats: +0.0001 chips.
3. Stacks of one big blind, through `play_match`. The big blind is all in on posting and the
   small blind should always call (every hand has more than the 25% it needs). LBR finds
   that, and over 600 hands the result is exactly 0.

### Win probability

`tests/win_probability.rs` compares the win probability with plain enumeration using the
rules engine's `BruteForceRanker`, a different evaluator from the one LBR uses. They agree to
1e-12 on hand-made and random weighted ranges on the flop, turn and river, and on each of the
1,326 entries of a turn table and a river table. The exact preflop table agrees to 1e-12 with
direct enumeration of all 1,712,304 boards for 16 pairs of hands.

## Speed

Release build, Rust 1.97, a 4-core cloud container (Intel Xeon at 2.30 GHz), 26 Nov 2026.
Hands per second on 4 cores, 100,000 hands, from `examples/paper_table.rs`:

| Strategy | fc, 1-4 | fc, 3-4 | fcpa, 1-4 | fcpa, 3-4 | 56 bets, 1-4 | 56 bets, 3-4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| always call | 1,824 | 26,615 | 3,575 | 26,653 | 3,220 | 20,948 |
| 1/2 call, 1/2 raise | 2,235 | 14,072 | 6,067 | 13,297 | 5,737 | 14,473 |
| random action | 3,098 | 15,229 | 32,210 | 17,083 | 12,743 | 16,154 |
| always raise, pot | 1,836 | 26,152 | 3,779 | 28,440 | 3,563 | 23,335 |

So 100,000 hands take 4 to 8 seconds on rounds 3-4 and up to 55 seconds on rounds 1-4, plus
171 seconds once for the exact preflop table. On rounds 1-4 the cost is the flop: a hand that
gets there with LBR still to decide needs the flop table below. Hands that end before the flop
are far faster (always raise, all in: 76,000 to 210,000 a second).

Where the time goes, on one core:

| Step | Time | Work |
| --- | ---: | --- |
| Win probabilities on the river | 4 microseconds | 990 evaluations |
| On the turn | 83 microseconds | 46 rivers, 45,540 evaluations |
| On the flop | 1.9 ms | 1,081 turn and river pairs, 1,070,190 evaluations |
| Before the flop, exact, per class | 3.75 s | 2,118,760 boards, 2.1 billion evaluations; 169 classes, once |
| Before the flop, 1,000 sampled boards | 2.5 ms | 990,000 evaluations, every hand |

- The table of win probabilities against all 1,326 hands is worked out once per street and
  reused for every bet size, so 56 bets cost little more than 2 against a trivial strategy.
- Against a real strategy its own speed will decide. LBR asks for one action's probability
  for every hand still possible (up to 1,225 before the flop, 1,081 on the turn): once per
  opponent action, and once per bet size at each LBR decision. With 56 bets that is up to
  about 60,000 lookups per decision. The paper reports up to 8 hours per 1,000 hands with
  56 bets against real bots. Override `action_prob_for_range` so the work shared by all
  hands is done once.
- Debug builds are 20 to 30 times slower. The default tests are sized for them.

## Tests

| File | Checks |
| --- | --- |
| `tests/win_probability.rs` | The win probability equals plain enumeration with the rules engine's brute-force ranker (a different evaluator from LBR's): hand-made and random weighted ranges on the flop, turn and river, with hands that cannot be held; every one of the 1,326 equities on a turn and a river; one river case worked out on paper. Sampled preflop equities are within 4 standard errors of all 1,712,304 boards. Ignored (slow in debug): the exact preflop table equals direct enumeration to 1e-12 for two classes and 16 opposing hands chosen to exercise the suit renaming, and gives the known 82.40% for kings and 34.58% for 7-2 offsuit against a random hand. |
| `tests/decisions.rs` | Bayes' rule by hand (a strategy that raises aces always and kings half the time: 1/9 and 1/18 per combination after a raise, with LBR's own cards counted); board cards remove hands; an action the strategy never takes changes nothing; every option's value equals the paper's formula for five hands against three strategies; calling by pot odds; unequal stacks; never folding a free check. |
| `tests/chumps.rs` | The trivial strategies: exact results where there are any (always fold 75, always call with fc 0, always all in with rounds 3-4 0), "wins big" by more than 5 standard errors elsewhere (3 for the smallest edge), the paper's numbers within 4 standard errors at 3,000 hands, the same result on 1 core and on all. Ignored: `paper_table_2` and `paper_table_2_rounds_1_to_4`, the 100,000-hand comparison above. |
| `tests/perfect_play.rs` | The AKQ game, the solved river spot and the one-big-blind match above. LBR's expected winnings are computed exactly there: its own actions are followed and the opponent's are averaged with their probabilities, each branch with its own copy of the range. |
| `src/*.rs` | Unit tests: the evaluator adapter agrees with nlhe's brute-force ranker on who wins 3,000 random showdowns; the 169 classes and their suit renaming; hand indices; the 56 bet sizes; every trivial strategy's list is legal, sums to 1 and agrees with its per-range shortcut. |

## Things to know

1. Half call, half raise does not match the paper. The paper's row reads 710, 1,620, 2,310
   and 2,440 (fc 1-4, fc 3-4, fcpa 1-4, fcpa 3-4). Ours: 1,721, 715, 2,288 and 2,194. Only
   fcpa on rounds 1-4 agrees. What we know:
   - With fold and call only, ours are near the paper's two numbers with the rounds
     exchanged: 715 ± 23 against 710 ± 26, and 1,721 ± 24 against 1,620 ± 15 (still 3.6
     standard errors apart). Ours also have the order of the paper's own random column
     (rounds 1-4 above rounds 3-4). Two cells may be exchanged in the paper's table. That is
     a guess, and the paper's text says that waiting helps against this strategy.
   - The paper does not say how the raise is drawn or what the strategy does when it cannot
     raise. Here the amount is drawn evenly from the legal range (the reading that
     reproduces the random column) and the strategy calls when it cannot raise. We tried
     folding a quarter or a half of the time when it cannot raise: fcpa on rounds 3-4 goes
     to 3,704 and 5,925, further from the paper's 2,440.
   - The other three strategies agree in all 10 cells, so we left this open rather than tune
     a trivial strategy to a number.
2. "A random legal action" has two readings. `UniformRandom::Actions` makes every legal
   action equally likely with each raise amount its own action, so it raises nearly always
   and folds or calls half and half once it cannot raise. This reproduces the paper's four
   numbers. `UniformRandom::Kinds` gives fold, call and raise a third each; against it
   LBR wins 4,978 where the paper has 8,070.
3. Sampled preflop win probabilities cost little. On the same 20,000 hands, always call with
   fcpa on rounds 1-4: 3,224 with 100 boards, 3,238 with 500, 3,249 with 2,000, 3,246 exact.
   Random action with fc on rounds 1-4: 1,329, 1,336, 1,363, 1,373 exact. The standard error
   of these runs is 49 and 65, so use the exact table for numbers that will be compared.
4. LBR is a lower bound and can be negative. It lost 536 mBB per hand to the paper's bot with
   no card abstraction, which a true best response beat by 90. A falling LBR number is
   evidence of a stronger strategy, not proof, and one setting can miss what another finds
   (always all in, above).
5. LBR asks about bets the strategy never trained on. With 56 bets most sizes are off any
   blueprint's tree, so `action_probs` must answer for every legal state (that is the
   strategy's action translation). The paper found bots most exploitable exactly there.
6. If the opponent takes an action their strategy gives no probability with any hand, LBR
   keeps the range it had. In `play_match` this cannot happen: actions are drawn from the
   strategy.
7. Folding is not allowed when checking is free (nlhe's rule). So always fold checks its
   option in the big blind, and LBR needs a bet to win that pot: with fold and call only it
   wins 25, not 75.
8. Not built: the paper's second variance reduction (counting the expected result over all
   the hands the opponent could hold, about 20% narrower intervals together with duplicate
   deals), its averaging over samples for strategies that sample their translation, and
   more than two players.
9. Chips are whole numbers. At the default table a big blind is 100 chips, so the smallest
   pot fractions of the 56 bets round to the minimum bet early in a hand.

## Layout

| File | What |
| --- | --- |
| `src/strategy.rs` | `Strategy`, `ActionProbs` |
| `src/public.rs` | `PublicState` |
| `src/player.rs` | `Lbr`: the range update and the decision |
| `src/config.rs` | `LbrConfig`, `BetSize`, `StreetPolicy`, `PreflopEquity`, the paper's bet sets |
| `src/equity.rs` | Win probabilities: exhaustive on every street, the preflop table, sampling |
| `src/range.rs` | `Range`, hand indices |
| `src/runner.rs` | `play_match`, `play_hand`, `MatchConfig`, `MatchResult` |
| `src/chumps.rs` | The trivial strategies |
| `src/ranker.rs` | `EvalRanker` (re-exported from nlhe) and the card conversion to eval |
| `examples/paper_table.rs` | The results table |
| `tests/` | See "Tests" |
