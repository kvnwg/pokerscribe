# Strategy experiments

Every strategy option is a key in `app.poker.advice.TUNING`. The defaults are the frozen
baseline in `baseline_tuning.json` (a test checks that they match). An option becomes a
default only with credible paired evidence:

- an improvement of at least 2.5 standard errors on the default mixed table, and
- no significant loss on the fish247 table (bots like the ones on 247 Free Poker), and
- for stack-depth options, also no significant loss with tournament-like stacks.

Whoever changes a default writes the new baseline to `baseline_tuning.json` and adds the
evidence here.

## How the numbers were made

`python tools/compare.py '<overrides>' <hands> --tables <tables> [--stacks even|uneven|tourney] [--profiles]`

- Paired simulation, seed 101: both variants get the same cards, the same stacks and the
  same bot decisions. The hand is played with the base variant. When the other variant
  would act differently somewhere, the hand is replayed with it. The difference and its
  standard error (SE) come from the per-hand differences.
- 6-max, blinds 1/2. Stacks:
  - `even`: everyone 100 big blinds.
  - `uneven`: bots 15 to 250, the app 100.
  - `tourney`: bots 8 to 70, the app 8 to 150.
  - Short bots (15bb or less) go all in instead of raising small.
- `--profiles`: the app learns each bot's style from the hands, as in watch mode. It uses
  `profiles.update` on every action it can see and `profiles.annotate` before `advise`, so
  the profile-based exploits are measured, not assumed.
- Win rates are in big blinds per 100 hands (bb/100). "Differ" counts the hands where the
  two variants acted differently. Only those hands carry the difference.
- No run had any always-wrong instruction. The simulator's checks found none:
  - folding when checking is free;
  - a bet or raise with no amount;
  - a deep weak all-in;
  - a weak all-in at 25bb or more while a big stack is in;
  - folding the nuts on the river.

## Results

| Option | Stacks | Table | Hands | Differ | Difference (bb/100) | Decision |
|---|---|---|---|---|---|---|
| `push_chart` | tourney | mixed | 2000 | 22 | +3.0 ± 2.0 | off |
| | tourney | stations | 2000 | 19 | -0.4 ± 2.1 | |
| | tourney | maniacs | 1000 | 5 | -0.4 ± 1.5 | |
| | tourney | fish247 | 1000 | 8 | +0.1 ± 2.0 | |
| `reshove` | tourney | mixed | 1000 | 3 | -2.8 ± 3.6 | off |
| | tourney | fish247 | 1000 | 1 | -0.8 ± 0.8 | |
| `bully` | uneven | mixed | 1000 | 3 | +0.6 ± 0.7 | off |
| `commit: 1.0` | even | mixed | 1500 | 2 | -1.4 ± 1.4 | off |
| | even | stations | 1500 | 0 | 0.0 | |
| `semibluff_turn: "combo"` | even | mixed | 1500 | 6 | -1.0 ± 1.0 | see below |
| | even | fish247 | 1500 | 13 | +1.2 ± 1.5 | |
| `semibluff_turn: "never"` | even | mixed | 1500 | 7 | -1.3 ± 1.0 | off |
| | even | fish247 | 1500 | 20 | -0.9 ± 1.9 | |
| `ev_sizing` (time-limited maths, see note) | even | mixed | 1000 | 41 | +5.3 ± 11.2 | see below |
| | even | fish247 | 1000 | 65 | +2.4 ± 2.3 | |
| `ev_sizing`, with profiles | even | mixed | 3000 | 149 | +5.0 ± 6.0 | off |
| | even | fish247 | 3000 | 204 | -1.1 ± 7.7 | |
| `semibluff_turn: "combo"`, with profiles | even | mixed | 2000 | 4 | -0.8 ± 0.9 | off |
| | even | fish247 | 2000 | 0 | 0.0 | |

Note on the first `ev_sizing` run: its sizing maths used a time limit, not a fixed number
of samples, so that run was not exactly repeatable. The simulator now fixes the sample
count for it too (`variant` in tools/simulate.py). The profile runs above it use that.

Not run, so they stay off: `eff_push`, `commit` with tournament stacks, `commit_draws`,
`geometric`, `river_ip_call_share`, `balanced_river`, `bucket_sizing` / `small_bet_from`,
`oop_lead`, and `bully` with tournament stacks. They were stopped by the instruction to
finish only the runs in flight.

## Decisions

Nothing met the evidence rule, so every default stays at the baseline. Each option is
still there as an experiment flag in TUNING, with its own tests.

- **`ev_sizing`**: off.
  - It picks bet and raise sizes by expected value, with fold equity. This was the user's
    request that big raises scare opponents off.
  - Results: +5.0 ± 6.0 on mixed and -1.1 ± 7.7 on fish247 (3000 hands each, with
    profiles). That is under 1 SE either way.
  - Sizing changes about 5 to 7% of hands, and those hands swing a lot, so a credible
    answer needs far more hands, roughly 30000 per table.
- **`semibluff_turn: "combo"`**: off.
  - On the turn it semi-bluffs only with 12 or more outs, or against a player who folds a
    lot. It is short of the bar on mixed: -1.0 ± 1.0 and -0.8 ± 0.9.
  - On fish247 it was +1.2 ± 1.5 without profiles. With profiles nothing differs, because
    the 247-style bots are all labelled stations.
  - The user's spot is covered by the bug fix that does stay on: no semi-bluffs into a
    player labelled a station, on any street. After about a dozen hands each, the 247
    bots carry that label.
- **Bug fixes kept** (not strategy changes):
  - no semi-bluffs into a player labelled a station;
  - the reason names the draw and its chance to hit, for example "flush draw (about 1 in
    5 to hit on the river)".
- **Stack-depth options** stay off: `push_chart`, `reshove`, `bully`, `commit`. They
  change very few hands at these stacks (1 to 22 per 1000 to 2000), and none reached 2.5
  SE. `reshove` and `commit` were slightly negative.

## Profiles check

150 hands on the mixed table with `--profiles`. Each bot ended up with a label that
matches how it actually plays:

| Bot | Learned label | VPIP | PFR |
|---|---|---|---|
| station | station | 45% | 7% |
| nit | nit | 13% | 9% |
| tag | nit | 14% | 10% |
| lag | tag | 18% | 13% |
| maniac | maniac | 53% | 33% |

The simulator's "tag" and "lag" bots play tighter than their names. Their VPIP setting
applies only when nobody has raised; against raises they mostly fold. So the labels follow
their real frequencies, which is what the advice should react to.

Over 2000 to 3000 hands the labels were:

- station, nit and tag right;
- the lag bot labelled tag (VPIP 28%, PFR 20 to 21%), just under the lag line once the
  small-sample prior is counted;
- the maniac labelled lag (VPIP 49%), just under the 50% maniac line;
- all five fish247 bots labelled station (VPIP 32 to 34%, PFR 4 to 5%).

## Phase 2 groundwork: river solver (26 Nov 2026)

Nothing the advice does has changed, so no strategy comparison was needed. The solving
algorithm itself comes in a later session. See `SOLVER.md`.

One paired run checked that nothing changes:
`tools/compare.py '{"river_solver": true}' 150 --tables mixed` (seed 101). Result: 0 of
150 hands differ, +0.0 ± 0.0 bb/100. With the stub, the switch falls back to the rules
every time.

- **New switch `river_solver`: off.** When it's on, heads-up river decisions use the
  solver's strategy if it answers within its time budget (300 ms of the 400 ms target).
  Otherwise the rules decide: the solver isn't written yet, it fails, it is too slow, the
  hero faces a raise, or the stacks weren't read reliably. Like every option, it needs the
  B0 bar (2.5 SE, no significant loss to any table, repeated on fresh seeds) before it can
  become a default.
- **`baseline_tuning.json`**: `"river_solver": false` was added (only added to, nothing
  edited). B0 plays exactly as before, and the test that the defaults match the file still
  holds.
- **Built and tested** (`app/solver/`):
  - `RiverSpot`;
  - the betting tree;
  - fast river ranking;
  - `RiverStrategy`;
  - an exact exploitability checker;
  - the timing harness;
  - the label format;
  - the bridge from the advice;
  - two scripts, `tools/solver_timing.py` and `tools/label_river.py`.
- **Checks that pass now**:
  - ranking orders every combo exactly as treys does on 30 boards (flush, straight-flush,
    quads, full-house and wheel boards included). It takes about 0.5 ms for all 1,081
    combos of a board.
  - the exploitability checker gives exactly 0 for the closed-form half-street
    equilibrium at bet sizes 0.5, 0.75, 1 and 2 times the pot. It gives the hand-worked
    losses for two mistakes:
    - a caller who always folds: 725/19 chips in a pot of 100;
    - a bettor who never bluffs: 75/19.
  - on a small game with card clashes, it matches brute force over every pure
    counter-strategy. It takes about 5 ms on a spot with medium ranges.
- **Waiting for the solver**: the answer-key tests (bluff share s/(1+2s), call share
  1/(1+s) and the game value, at four bet sizes) are skipped until `solve_river` stops
  raising `NotImplementedError`. There are no timing numbers yet.

## Phase 2: river solver and push-or-fold (26 Nov 2026)

`solve_river` now works. The `river_solver` switch is still off, and nothing was compared
against B0 in simulation: that waits for Phase 1. Raw numbers:
`runs/phase2_solver.log`, made by `runs/phase2_solver.py`.

### Method: Discounted CFR, not CFR+

Both are in `app/solver/cfr.py` and share one loop. Median (worst) exploitability in % of
the pot over 12 benchmark spots per range size, at equal iterations:

| Ranges | Method | 50 | 100 | 200 | 400 |
|---|---|---|---|---|---|
| narrow | Discounted CFR | 0.42 (1.99) | 0.15 (0.64) | 0.05 (0.18) | 0.01 (0.06) |
| narrow | CFR+ | 0.98 (4.35) | 0.34 (1.58) | 0.13 (0.62) | 0.04 (0.27) |
| medium | Discounted CFR | 0.45 (1.71) | 0.15 (0.44) | 0.05 (0.17) | 0.02 (0.07) |
| medium | CFR+ | 0.82 (2.95) | 0.34 (1.14) | 0.13 (0.47) | 0.05 (0.19) |
| wide | Discounted CFR | 0.42 (1.39) | 0.16 (0.38) | 0.05 (0.15) | 0.01 (0.06) |
| wide | CFR+ | 0.82 (3.31) | 0.34 (1.22) | 0.13 (0.45) | 0.05 (0.20) |

Discounted CFR is about 3 times closer at every count, so it is the default. An iteration
costs the same for both. CFR+ is kept as `method="cfr+"`. On the tiny half-street game
CFR+ is the quicker one early on (0.02% against 0.07% at 100 iterations), but that game
is solved in milliseconds either way.

### Answer keys: The Mathematics of Poker's half-street game

Pot 100. "Test" is how the tests run it: it stops once exploitability is under 0.1% of the
pot, after 64 to 128 iterations and about 10 ms. "Long" is 20,000 iterations.

| Bet | Quantity | Book | Solver (test) | Solver (long) |
|---|---|---|---|---|
| 0.5 pot | bluff share s/(1+2s) | 0.2500 | 0.2513 | 0.2500 |
| | call share 1/(1+s) | 0.6667 | 0.6704 | 0.6667 |
| | bettor's value | 21.0526 | 21.0524 | 21.0526 |
| 0.75 pot | bluff share | 0.3000 | 0.3024 | 0.3000 |
| | call share | 0.5714 | 0.5719 | 0.5714 |
| | bettor's value | 22.5564 | 22.5563 | 22.5564 |
| 1 pot | bluff share | 0.3333 | 0.3341 | 0.3333 |
| | call share | 0.5000 | 0.5030 | 0.5000 |
| | bettor's value | 23.6842 | 23.6840 | 23.6842 |
| 2 pots | bluff share | 0.4000 | 0.3999 | 0.4000 |
| | call share | 0.3333 | 0.3349 | 0.3334 |
| | bettor's value | 26.3158 | 26.3158 | 26.3158 |

Value hands bet 100% in every row. Tolerances in the tests, unchanged from the groundwork
session: frequencies within 0.02, exploitability at most 0.2% of the pot, value within 0.4
chips. The largest frequency error at the test setting is 0.004. All five answer-key tests
passed on the solver's first run; neither a book number nor a tolerance was changed.

### Exploitability falls toward zero

Exploitability in % of the pot (the solver's own number equals the independent checker's
to 9 decimals):

| Spot | Method | 10 | 30 | 100 | 300 | 1000 | 3000 |
|---|---|---|---|---|---|---|---|
| half-street, pot bet | Discounted CFR | 3.287 | 0.224 | 0.074 | 0.017 | 0.0061 | 0.0019 |
| | CFR+ | 1.109 | 0.117 | 0.018 | 0.011 | 0.0026 | 0.0018 |
| two ranges, default sizes | Discounted CFR | 6.762 | 1.531 | 0.097 | 0.0074 | 0.0006 | 0.0001 |
| | CFR+ | 9.568 | 2.622 | 0.340 | 0.041 | 0.0040 | 0.0005 |
| benchmark spot | Discounted CFR | 10.749 | 1.757 | 0.252 | 0.046 | 0.0073 | 0.0011 |
| | CFR+ | 10.494 | 3.026 | 0.503 | 0.107 | 0.023 | 0.0045 |

The test (`test_solver_cfr.py`) asserts, for all six rows, that exploitability at 10, 100
and 1000 iterations strictly falls, by at least a factor of 3 each time, and is under 0.1%
of the pot at 1000.

### Push-or-fold, heads-up, 5 to 15 big blinds

`app/solver/pushfold.py` solves the game on exact all-in equities for all 169 x 169
starting hands, with card removal. `tools/build_preflop_equity.py` builds that table in
101 s by going through 134,459 boards that stand for all 2,598,960. Checks on the table:

- AA against KK is 0.819460505, the same to 9 decimals as enumerating all 1,712,304
  boards combo by combo;
- the per-board counting matches the slow pair-by-pair way, ranked by treys;
- five matchups agree with the app's sampling equity engine.

Published results to compare against:

- **Chart**: HoldemResources, "HeadsUp Push/Fold Nash Equilibrium", no ante: for each
  hand, the highest stack at which it is pushed or called
  (https://www.holdemresources.net/hune). Same game and same stack definition as ours.
- **Book**: the two jam shares this repo already quotes from The Mathematics of Poker
  (about 62% at 8 big blinds, 58% at 10). The book's own table isn't online.
- **Second table**: PokerStrategy's shares per stack
  (https://www.pokerstrategy.com/strategy/sit-and-go/1779/).

| Stack | Jam: chart | Jam: solver | Jam: book | Call: chart | Call: solver | SB result (bb/hand) | Hands that differ from the chart |
|---|---|---|---|---|---|---|---|
| 5 | 72.2% | 71.5% | | 62.3% | 62.1% | +0.056 | 96o (the solver mixes it, 17% jam) |
| 8 | 62.3% | 61.9% | 62% | 45.4% | 45.0% | -0.004 | 84s, 43s (the solver folds both) |
| 10 | 58.4% | 58.3% | 58% | 37.3% | 37.4% | -0.045 | none |
| 12 | 53.2% | 53.2% | | 33.0% | 33.0% | -0.083 | none |
| 15 | 45.7% | 45.7% | | 28.8% | 28.5% | -0.127 | none |

Solver exploitability is under 0.000001 bb a hand at every stack, in 200 to 300 iterations
and about 20 ms. Tolerances in the tests:

- shares within 1.5 points of the chart (the largest gap is 0.7);
- book shares within 1 point;
- a hand may differ from the chart only where its two actions are worth within 0.01 bb of
  each other.

**The three hands that differ: the solver is right, and nothing was changed.** The
reasoning:

1. The chart and the solver describe the same game. Played in our game, the chart's
   strategy can be exploited for at most 0.00009 bb a hand, and its value for the small
   blind matches ours to 4 decimals at every stack. So the equities and the rules agree.
2. The chart gives one cutoff per hand. Some suited hands switch between jam and fold
   several times as the stack changes. The page notes this for 63s, 53s and 43s only.
   Solving every half big blind from 7.5 to 10.5 shows 84s going jam, fold, jam, fold,
   fold, jam, fold. From 8 to 10 it is worth within 0.006 bb of folding, and its sign
   depends on which hand the big blind has just added to its calls. The chart's 10.1 is
   the highest stack where 84s is a jam, not a promise for every stack below.
3. At 8 big blinds, jamming 84s against the chart's own calling range loses 0.013 bb
   compared with folding, and 43s loses 0.015. Against the equilibrium calling range they
   lose 0.0015 and 0.0028. So folding is correct there, by a hair.
4. 96o at 5 big blinds is a mixed hand at the edge of its cutoff (jamming and folding are
   worth the same to 0.0003 bb).

The second table differs from the chart itself at short stacks (at 5 big blinds it lists
74.1% and 68.6% against the chart's 72.2% and 62.3%), so it isn't the same calculation. At
15 big blinds it agrees with both (45.7% and 28.4%). It also says the small blind's result
is positive under 7.5 big blinds and about -0.1 at 15 to 20, which matches the last column.

### Decision time

Budget 300 ms for the solver, target 400 ms for the decision. 200 benchmark spots per
range size (`tools/solver_timing.py --ranges all`). The solver stops when its answer is
under 0.1% of the pot or when the budget is nearly spent, so the time passes almost by
construction. What tells spots apart is how exploitable the answer still is at that point.

| Ranges (combos) | Time p50 | Time p95 | Time max | Exploitability p50 | p95 | max | Over 1% |
|---|---|---|---|---|---|---|---|
| narrow (about 120 v 180) | 100 ms | 290 ms | 291 ms | 0.06% | 0.10% | 0.15% | 0 of 200 |
| medium (about 290 v 350) | 141 ms | 290 ms | 291 ms | 0.07% | 0.14% | 0.23% | 0 of 200 |
| wide (about 500 v 550) | 288 ms | 290 ms | 299 ms | 0.08% | 0.31% | 0.53% | 0 of 200 |

The whole decision through `advise()` (the switch turned on inside the measuring script
only), on 150 random heads-up river spots: p50 155 ms, p95 313 ms, max 317 ms, none over
400 ms. The solver's answer was used in all 150.

No spot misses the bar of 1% of the pot. The weakest are wide ranges with stacks of 8
pots: more combos make each iteration slower (about 2 ms against 0.6 ms), and the deeper
tree needs more iterations, so only about 125 fit in the budget. In about 1 run in 600 on
this machine a single slow moment pushed a solve a few ms past 300; the advice then uses
the rules for that decision.

### Not done, on purpose

- The switch stays off; no B0 comparison (after Phase 1).
- Ranges in the advice are still the placeholder (Phase 3). Facing a raise still uses the
  rules. (Both done since: the next section.)
- The push-or-fold solver isn't wired into the advice. The `push_chart` option still
  uses its hand-typed table.

## Phase 2: river ranges from the betting, and facing a raise (26 Nov 2026)

Two things the river solver lacked: it was given the same top 25% of hands for both players
whatever had happened, and it left a raise of your bet to the rules. Both are done. The
`river_solver` switch is still off, B0 is untouched, and nothing was compared against B0:
that waits for Phase 1. Raw numbers: `runs/phase2_ranges.log`, made by
`runs/phase2_ranges.py`. How it works: `SOLVER.md`.

### What was built

- `app/poker/history.py`: `BettingRecord` keeps who bet how much on each round of the hand
  being watched. `app/poker/profiles.py` feeds it every read and puts the result on the
  river state.
- `app/solver/ranges.py`: `river_ranges` turns that record, the seats and what the app has
  learned about the opponent into weighted ranges for both players.
- `app/solver/bridge.py`: a raise of the hero's bet is solved (fold, call or all in). The
  bets already made are the only sizes on offer where they were made. Three safeguards
  (below).
- `BetSizes`: `reraises`, `allin_within` and `exact`.
- 69 more tests than before. Full suite: 623 passed, 1 skipped, and the 6 known failures
  of this container (4 need fonts, 2 need a screen).

### How the ranges were measured

The simulator is only used here to deal hands and to see which cards the bots really hold.
The app's seat plays the frozen baseline with the switch off, so this is not a strategy
comparison. For every hand that reaches the river heads-up with the app to act, the real
two cards are looked up in each guess of the range:

- **in range**: how often the real hand is in the range at all;
- **bits**: log2 of (the probability the range gives the real hand / the probability with
  no information), with 5% of the weight spread evenly so a miss costs a lot, not
  everything. 0 = knowing nothing; each bit halves the field.

Seed 31 is where the settings were looked at. Seed 77 was held out and run once, after
the settings were frozen. 6000 hands per table, with `--profiles`. Seed 31 is in brackets.

**The opponent's range.**

| Table | Guess | Real hand in range | Combos | Bits |
|---|---|---|---|---|
| mixed (366 hands) | placeholder, top 25% | 59.0% (70.1%) | 274 | -0.63 (0.05) |
| | pot size only | 73.8% (75.0%) | 402 | -0.44 (-0.41) |
| | recorded betting | 72.1% (73.9%) | 377 | -0.39 (-0.38) |
| | recorded betting + profile | 89.1% (91.5%) | 465 | 0.54 (0.62) |
| fish247 (440 hands) | placeholder, top 25% | 81.1% (79.9%) | 270 | 0.76 (0.68) |
| | pot size only | 91.6% (90.9%) | 435 | 0.55 (0.45) |
| | recorded betting | 87.5% (88.5%) | 406 | 0.40 (0.41) |
| | recorded betting + profile | 98.0% (95.8%) | 463 | 1.28 (1.01) |

**The app's own range**, as the opponent should see it (the profile isn't used for it).

| Table | Guess | Real hand in range | Combos | Bits |
|---|---|---|---|---|
| mixed | placeholder, top 25% | 59.3% (57.7%) | 274 | -0.62 (-0.73) |
| | pot size only | 83.3% (80.5%) | 404 | 0.50 (0.45) |
| | recorded betting | 86.6% (80.8%) | 376 | 1.16 (0.75) |
| fish247 | placeholder, top 25% | 57.5% (51.9%) | 270 | -0.72 (-1.09) |
| | pot size only | 91.4% (88.1%) | 460 | 0.91 (0.81) |
| | recorded betting | 96.6% (93.6%) | 445 | 1.58 (1.33) |

What the tables say:

- **The full guess is clearly better than the placeholder, on hands it had never seen.**
  "Recorded betting + profile" is what the advice gets while watching. The opponent's real
  hand is in it 89% and 98% of the time, against 59% and 81%, and it scores 1.17 and 0.52
  bits more. The standard errors of the in-range shares are about 1 to 3 points (366 and
  440 hands). The bits have no standard errors.
- **Without the profile the betting record does little for the opponent's range.** It is
  about level with the pot-size guess. On the fish247 table both score fewer bits than
  the placeholder (0.40 and 0.55 against 0.76), though they hold the real hand more often:
  they are wider than they need to be. The difference between the last two rows is the
  profile: these bots are far from the typical player the defaults assume (the station
  plays 45% of hands, the maniac about 50%, the 247-style fish 33% while raising 5%). So
  for the first hands of a session, before the profiles know the players, expect the
  weaker row.
- **The app's own range gains the most from the record**, because the app does play by the
  charts: its hand is in the range 87% and 97% of the time, against 59% and 58%.

How the model got here, all on seed 31:

1. The first version was worse than the placeholder: the opponent's real hand in range
   54% to 62% of the time, against 68% to 77% (1500 hands). Three causes, each found by
   looking at which step lost the real hand, each fixed:
   - ranges were cut to the 400 heaviest combos, which chopped wide ranges in half. The
     solver was timed on bigger ranges (about 0.15% to 0.27% of the pot from an
     equilibrium with ranges of 800 combos, 0.34% to 0.9% with 1000; side measurements,
     not in the log), and the cap is now 700;
   - a caller's hands before the flop came straight from the charts, far too few for
     loose players, and limping then calling a raise wasn't a case at all. Opponents'
     ranges are now as wide as their style is loose;
   - a flop bet by the player who raised before the flop was read like any bet. It comes
     from many more hands.
2. Of the 44 misses then left on the mixed table, 24 were lost at the preflop step,
   mostly against the maniac bot, which the profiles label "lag" (see "Profiles check"
   above). The ranges now use the counted shares of hands played and raised, not only the
   label. Mixed table: 87.9% to 91.5% in range, 0.40 to 0.62 bits. fish247: 95.4% to
   95.8%, 0.73 to 1.01 bits.
3. The settings are standard poker reasoning and none was fitted to a bot. But seed 31
   was looked at many times, so only seed 77 counts as a test.

### Facing a raise, and three safeguards

The bridge now builds the spot from the start of the river with the bets already made in
it, at their real sizes, and finds the hero's node: "b100 r300" for a bet of 100 raised to
300. Testing it on real states turned up a fault that also affected facing a plain bet.

**The fault.** Three of a kind, facing a half-pot bet, got "fold 25%, call 25%, raise 25%,
raise 25%". The tree offered the opponent several bet sizes. In the solution the opponent
used other sizes and never the one that was really made, so the answer to that bet was
never worked out against anything, and a strategy that was never worked out is an even
split.

**The fixes.**

- The bets and raises already made are the only sizes offered where they were made. The
  question is what to do now that this bet happened.
- If under 0.2% of the opponent's range makes this bet in the solution anyway, the solver
  has no answer, and the rules decide.
- If the hero's own hand gets to this spot under 5% of the time in the solution (it was
  played differently earlier than the solver would have), its mix there means little. The
  instruction is then the best action for that hand against the opponent's solved
  strategy.
- An answer more than 1% of the pot from an equilibrium is not used. The rules decide.

**How it was checked.** The simulator's bots next to never raise a river bet: 2 real cases
in 24,000 hands (both on seed 31, both answered). So each river bet the app made was
answered by a made-up raise the size of the pot, and the solver was asked what to do.
Seed 77:

| | mixed | fish247 |
|---|---|---|
| River bets by the app | 78 | 106 |
| Answered | 76 (fold 30, call 41, all in 5) | 103 (fold 58, call 36, all in 9) |
| No answer (the solution has no hands for that raise) | 2 | 3 |
| Solver time p50 / p95 / max | 265 / 290 / 300 ms | 246 / 290 / 295 ms |
| Distance from an equilibrium, % of the pot, p50 / p95 / max | 0.08 / 0.35 / 0.54 | 0.07 / 0.27 / 0.82 |

This shows the machinery answers in time and near an equilibrium. It says nothing about
whether folding or calling was right: a made-up raise isn't one the opponent chose, and
nothing was played out.

### All in only up to six pots

The first cost run found about one solver answer in six over the 1% bar: 12 of 80
decisions on the mixed table and 16 of 80 on fish247 (seed 31). All were limped pots: 2
big blinds in the middle and 100 behind. All in was always one of the choices, and there
it is a bet of 40 pots. The same spots solved for 300 ms with all in on offer and with it
left out (seed 31, the first 150 river decisions of each table, at most 25 per row):

| Stack, in pots | Spots | With all in: median % of the pot | Over 1% | Without: median | Over 1% |
|---|---|---|---|---|---|
| up to 1 | 12 | 0.04 | 0 of 12 | 0.04 | 0 of 12 |
| 1 to 2 | 21 | 0.07 | 0 of 21 | 0.05 | 0 of 21 |
| 2 to 3 | 17 | 0.05 | 0 of 17 | 0.06 | 0 of 17 |
| 3 to 4 | 11 | 0.06 | 0 of 11 | 0.06 | 0 of 11 |
| 4 to 6 | 22 | 0.13 | 0 of 22 | 0.08 | 0 of 22 |
| 6 to 10 | 30 | 0.20 | 0 of 25 | 0.08 | 0 of 25 |
| 10 to 20 | 102 | 0.56 | 2 of 25 | 0.06 | 0 of 25 |
| over 20 | 85 | 2.67 | 22 of 25 | 0.10 | 1 of 25 |

So `BetSizes.allin_within`: all in is a choice of its own only where it is a bet of at
most that many pots (for a raise, pots after calling). The bridge uses 6. A bet that was
really made is in the tree at any size. After the change, on seed 31: 0 of 400 answers
over the bar.

### Cost of a decision

The whole decision through `advise()`, with the switch turned on inside the measuring
script only. The first 200 heads-up river decisions of each table, seed 77:

| | mixed | fish247 |
|---|---|---|
| Time p50 / p95 / max (target 400 ms) | 292 / 298 / 322 ms | 294 / 299 / 332 ms |
| Answered by the solver | 197 of 200 | 199 of 200 |
| Left to the rules: the solver over its 300 ms | 1 | 0 |
| Left to the rules: over 1% of the pot | 0 | 0 |
| Left to the rules: no answer for that bet | 2 | 0 |
| Left to the rules: not counted by the script | 0 | 1 |
| Answered with the best action for a hand the solution never brings there | 4 | 1 |
| Distance from an equilibrium, % of the pot, p50 / p95 / max | 0.08 / 0.26 / 0.61 | 0.09 / 0.24 / 0.53 |
| Combos in the two ranges together, p50 / max | 871 / 1401 | 1047 / 1394 |

The one decision the script has no reason for is most likely a solve that the advice's
own clock, which starts a little earlier, put just past 300 ms (that table's slowest
decision took 332 ms).

The ranges are bigger than the placeholder's (about 870 to 1050 combos together against
550), so the solver now uses its whole 300 ms on most decisions: p50 went from 155 ms to
about 293 ms. p95 stays under 400 ms.

### What this doesn't show

- Whether the solver's play wins more than the rules. That is the B0 comparison after
  Phase 1. Run it with `--profiles`: without them the simulator keeps no betting record
  and the ranges are only guessed from the pot.
- Real opponents. The cards looked up here are bots' cards.
- Real river raises: 2 in 24,000 hands.
- Hands with three or more players on the river: the rules still decide those.

## Phase 2: the same answer every run, and time by pot size (26 Nov 2026)

**Read this with the new roadmap in mind.** The roadmap was replaced the same day
(`README.md`), while this section and the one above were being built for the old one.
Where they say the comparison against B0 "waits for Phase 1": the new roadmap doesn't ask
for that comparison. Phase 2 is now the reference the Rust solver must match, and the
switch stays off. The measurements themselves stand.

The two smaller jobs left after the ranges. The `river_solver` switch is still off, B0
plays as before, and nothing was compared against B0. Raw numbers:
`runs/phase2_budget.log`, made by `runs/phase2_budget.py` (seed 77, 6000 hands a table,
the first 200 heads-up river decisions of each; the simulator only deals the hands).
Both settings below were chosen on seed 31.

### The same answer every run

By the clock, the same spot gets a different number of iterations on every run, so a
simulator run with the solver on could not be repeated, and two variants could not be
compared hand for hand.

- **New setting `river_solver_fixed_work`: off.** `tools/simulate.py` turns it on for
  every variant, the way it already fixes the number of equity samples. The solver then
  has no clock. It runs the iterations its 300 ms buys on the reference machine
  (`reference_iterations`): 300 / (0.064 + 0.00007 x combos of both players x ends of the
  hand in the tree), a fit on 272 spots from seed 31 (within 11% for half of them, 24% for
  nine in ten). The early stop is the same as by the clock. Nothing is ever "late".
- **`baseline_tuning.json`**: `"river_solver_fixed_work": false` was added (only added to,
  nothing edited). With `river_solver` off the setting is never read.

| Check | mixed | fish247 |
|---|---|---|
| The same spot solved twice gives the same strategy, bit for bit | 200 of 200 | 200 of 200 |
| A fresh process gives the same strategy | 60 of 60 | 60 of 60 |
| `advise()` twice in the simulator's mode gives the same instruction | 60 of 60 | 60 of 60 |
| Within 1% of the pot of an equilibrium | 200 of 200 | 200 of 200 |
| Iterations, fixed work / by the clock on this machine, p10 / p50 / p90 | 0.85 / 1.04 / 1.21 | 0.79 / 0.96 / 1.28 |
| The same action as by the clock | 197 of 197 | 200 of 200 |

So the simulator's solver is the app's solver to within about a fifth of the work either
way, and it picked the same action every time. On a faster or slower machine than this
one the app itself gets more or fewer iterations than the simulator assumes. Bit for bit
holds on one machine; another machine's maths library may round differently.

### Time by pot size

The solver stopped early once its answer was within 0.1% of the pot, whatever the pot.
Measured on seed 31: pots over 50 big blinds were done in about 40 ms and then stopped,
while pots of 2 to 3 big blinds, a quarter of all river spots, used the whole 300 ms. And
giving the big pots a longer limit changed nothing (the same answer at 100 ms and at
1200 ms), because the early stop ended them, not the clock.

So the early stop now follows the pot (`solve.target_for`): a hundredth of a big blind,
the same accuracy in chips for every pot. That is 0.1% of a pot of 10 big blinds, 0.4% of
2.5 and 0.02% of 50, and never looser than 0.5% of the pot or tighter than 0.01%. The 300
ms limit is unchanged. Each spot solved under both rules:

| Pot, big blinds | Spots | Old: time p50 | Old: % of pot | Old: big blinds | New: time p50 | New: % of pot | New: big blinds |
|---|---|---|---|---|---|---|---|
| mixed, up to 3 | 35 | 288 ms | 0.077 | 0.0019 | 144 ms | 0.242 | 0.0056 |
| 3 to 8 | 60 | 288 ms | 0.088 | 0.0083 | 263 ms | 0.114 | 0.0096 |
| 8 to 20 | 40 | 288 ms | 0.112 | 0.0158 | 288 ms | 0.103 | 0.0156 |
| 20 to 50 | 46 | 139 ms | 0.060 | 0.0211 | 289 ms | 0.023 | 0.0097 |
| over 50 | 19 | 71 ms | 0.067 | 0.0437 | 209 ms | 0.009 | 0.0065 |
| fish247, up to 3 | 68 | 288 ms | 0.081 | 0.0022 | 139 ms | 0.219 | 0.0055 |
| 3 to 8 | 49 | 268 ms | 0.089 | 0.0072 | 271 ms | 0.101 | 0.0082 |
| 8 to 20 | 48 | 288 ms | 0.098 | 0.0153 | 288 ms | 0.102 | 0.0158 |
| 20 to 50 | 24 | 188 ms | 0.058 | 0.0223 | 288 ms | 0.023 | 0.0115 |
| over 50 | 11 | 76 ms | 0.061 | 0.0427 | 213 ms | 0.010 | 0.0071 |

"% of pot" is the median distance from an equilibrium, "big blinds" the mean.

| All 200 spots | mixed, old | mixed, new | fish247, old | fish247, new |
|---|---|---|---|---|
| Time, mean | 219 ms | 227 ms | 239 ms | 222 ms |
| Time, p95 | 289 ms | 290 ms | 290 ms | 290 ms |
| From an equilibrium, big blinds, mean | 0.0150 | 0.0098 | 0.0112 | 0.0095 |
| The same, worst spot | 0.0777 | 0.0466 | 0.0805 | 0.0859 |
| Over 1% of the pot | 0 | 0 | 0 | 0 |

- The smallest pots answer in half the time (288 ms to about 140) and end up about 3
  times further from an equilibrium, which is still half a hundredth of a big blind.
- Pots over 20 big blinds are solved 2 to 6 times closer, with the time they used to
  leave unused.
- Over all spots the mean distance in chips falls by a third on the mixed table and by
  15% on fish247, for about the same total time. The worst single spot on fish247 did not
  improve.
- The whole decision through `advise()`: p50 285 and 257 ms, p95 296 and 296 ms, max 303
  and 304 ms. 197 and 200 of 200 answered by the solver.

Keep the size of this in view: these are hundredths of a big blind. What the solver loses
by guessing the ranges wrong is far bigger. This change spends the same time better; it
is not a reason to expect better play on its own.

Not done: a longer limit than 300 ms for the biggest pots. It would break the 400 ms rule
(pots over 50 big blinds are about 1 river decision in 12), and the early stop, not the
clock, was what ended those solves.

## Slumbot harness check (26 Nov 2026)

A test of `tools/slumbot`, not a strategy experiment. The check/call bot played 200 hands
against Slumbot through its public API, 100 in each seat. It never folds and never bets.

`python -m tools.slumbot play --hands 200 --log docs/research/runs/slumbot/checkcall_200.jsonl --bot checkcall`

- **Rules.** Heads-up, blinds 50/100, 200bb stacks reset every hand. Requests were sent at most
  once a second: 1,138 in 19 minutes.
- **Result checks.** None of the hands was aborted. We recomputed every result from the parsed
  action string and the cards, and all 200 match Slumbot's `winnings`. That includes 191
  showdowns, checked with treys, and 9 hands where Slumbot folded its small blind.

| Measure | bb/100 | Hands |
|---|---|---|
| Raw | -257.8 ± 83.5 | 200 |
| Baseline (Slumbot's luck-adjusted figure) | -206.5 ± 88.8 | 200 |
| As big blind | -219.5 ± 129.4 | 100 |
| As small blind | -296.0 ± 106.1 | 100 |

For a B0 benchmark, the per-hand standard deviation here is about 12 bb. Reaching ± 10 bb/100
would take roughly 14,000 hands, about 22 hours at this pace. The baseline figure didn't cut the
variance for check/call, because that bot plays nothing like Slumbot. It should help more for B0.

## Rust engine link: the `rust_solver` switch and the cost of the call (26 Nov 2026)

Not a strategy experiment: nothing the advice does has changed. The Python app and the Rust
engine are now connected in two places. See `SOLVER.md`, "The Rust backend", and
`engine/crates/py/README.md`.

- **New switch `rust_solver`: off.** It only chooses who solves a river spot that
  `river_solver` (also off) already sends to the solver: the Rust program `subgame-solve`
  through `app/solver/rust_backend.py`, or the Python solver as before. When the program
  is missing or fails, the Python solver answers.
- **`baseline_tuning.json`**: `"rust_solver": false` was added (only added to, nothing
  edited). The test that the defaults match the file still holds.
- **Paired runs checked that nothing changes** (`tools/compare.py`, table mixed, seed
  101, no program built, so the Python solver answers). Log:
  `runs/rust_solver_switch_check.log`.
  - `{"rust_solver": true}` against the baseline, 150 hands: 0 hands differ.
  - `{"river_solver": true, "rust_solver": true}` against `{"river_solver": true}`
    (`--base`), 1,000 hands: 0 hands differ. So with the program missing, the Rust switch
    leaves the river solver's play exactly as it was. (The simulator runs the solver
    with fixed work, so this repeats.)
  - Also in the log, because they were run: each of those two solver variants against
    the baseline over 150 hands. Both give the same line, +11.7 ± 8.3 bb/100 from 3
    hands that differ. That is 1.4 standard errors on 150 hands. It was run to see the
    two lines agree and says nothing about `river_solver` against B0.
- **Not compared against B0**, and not to be turned on: `river_solver` itself has not
  passed the B0 bar. The backend was written and tested against a stand-in that follows
  the program's command line and file formats. `subgame-solve` reached the repo the same
  day, and the backend works with it as written (below).

### Bet sizes the SPOT format can't say

The SPOT format's bet sizes are `bets`, `raises` and `allin`. The river solver's sizes
got three more options today (`reraises`, `allin_within`, `exact`), which the format
doesn't describe and the advice uses on every spot. The backend says them with the
format's three keys wherever that gives exactly the same tree, and sends everything else
to the Python solver without a call.

Counted on the advice's own spots: every heads-up river decision of the app's seat in
6,000 simulated hands (table mixed, seed 77), collected as `runs/phase2_budget.py`
collects them.

| | Spots |
| --- | --- |
| Heads-up river decisions | 394 |
| Written as a SPOT, same tree | 302 (77%) |
| Can't be written, the Python solver's | 92 (23%) |

All 92 have stacks of 12.6 to 17.7 pots. There, all in is within six pots as a raise of
the pot-sized bet but not as a raise of the half-pot bet (the line is at 12.5 and 19
pots), and one list of raise sizes can't say both. No decision in the sample faced a
raise. The fix belongs on the Rust side: `subgame-solve` reading the three options, then
`EXTENDED_SIZES = True` in `rust_backend.py`.

### Against the real program

`runs/rust_solver_real.py` (log `runs/rust_solver_real.log`): the same 394 river spots,
each solved by the Python solver and by `subgame-solve` through the backend, by the
clock and with the advice's settings. Then every decision through `advise()` with
`rust_solver` off and on, both switches on in the measuring script only.

| | Python solver | `subgame-solve` |
| --- | --- | --- |
| Answered | 394 | 302, none failed (92 can't be written) |
| The solve call, p50 / p95 / max | 287 / 290 / 303 ms | 56 / 154 / 228 ms |
| Of that, solving / everything else, p50 | 287 ms / none | 44 ms / 15 ms |
| From an equilibrium, % of the pot, p50 / p95 / max | 0.10 / 0.35 / 0.74 | 0.06 / 0.40 / 0.50 |
| Answers over 1% of the pot | 0 | 0 |
| The whole decision through `advise()`, p50 / p95 / max | 294 / 299 / 441 ms | 79 / 297 / 311 ms |
| Decisions the solver answered | 388 of 394 | 389 of 394 |

- What the backend had taken on trust held: the target is in percent of the pot,
  `--time-ms` limits the solving, and a size over the stack becomes all in (every one of
  the 302 answers came back for exactly the spot's tree).
- The program's own exploitability is the Python checker's: the largest difference is
  0.00003% of the pot.
- The median decision drops from 294 ms to 79 ms. The p95 stays at 297 ms because the 92
  spots that can't be written are still the Python solver's.
- The advice would act the same on both answers in 289 of 297 spots where both have one
  for the hero's hand. The other 8 are close mixes (call 58%, fold 42% against 50%, 50%;
  all 8 are in the log). Through `advise()`: the same instruction on 384 of 394.
- One paired run in the simulator, with the program built:
  `tools/compare.py '{"river_solver": true, "rust_solver": true}' 1000 --tables mixed
  --base '{"river_solver": true}'` (seed 101): 1 of 1,000 hands differs, -0.1 ± 0.1
  bb/100, and a second run gives the same line. This compares the two solvers on the
  same spots, not either of them with B0. Log: `runs/rust_solver_switch_check.log`.

### What the call costs

Each decision that goes to the Rust program pays for starting it, writing the spot and
reading the answer back. `tools/rust_solver_overhead.py --advice-hands 6000
--advice-spots 400`, 5 calls a spot, in a Linux cloud container (Intel Xeon at 2.10 GHz,
4 cores). Run twice: with the real program (`--binary`; overhead is the whole call less
the solving time the program reports) and with a stand-in that does no solving
(`tools/replay_solve.rs`). Log: `runs/rust_solver_overhead.log`.

| Spots | Combos, both ranges | Real program: p50 | p95 | max | Stand-in: p50 | p95 | max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| narrow ranges, 40 | 219 to 340 | 8.6 ms | 12.2 ms | 29.5 ms | 5.7 ms | 7.2 ms | 17.3 ms |
| medium ranges, 40 | 462 to 685 | 13.3 ms | 17.8 ms | 33.1 ms | 10.2 ms | 16.4 ms | 37.7 ms |
| wide ranges, 40 | 909 to 1,145 | 19.3 ms | 26.6 ms | 35.1 ms | 13.4 ms | 20.7 ms | 35.9 ms |
| the advice's spots, 302 | 110 to 1,401 (median 833) | 16.8 ms | 26.4 ms | 36.0 ms | 11.7 ms | 19.7 ms | 28.4 ms |

- On the advice's spots: about 17 ms a call that is not solving, 26 ms at p95, which is
  6.6% of the 400 ms decision budget.
- Starting the program is 1.5 ms of it. Reading the answer in Python is the largest part
  (7 to 9 ms at the median on the advice's spots).
- The backend keeps 40 ms of the solver's 300 ms back for this, so the program gets
  260 ms. The largest overhead measured in any run is 37.7 ms.
- Not in these numbers: a Mac.

## Research notes (paraphrased, with sources)

- **Big stack pressure.** A big stack should stay active and attack short stacks: open
  and re-raise wider against them, since they must fold or risk everything. Avoid big
  pots with other big stacks. The source gives no numbers.
  ([PokerNews: Playing the Big Stack in Tournament Poker](https://www.pokernews.com/strategy/playing-the-big-stack-in-tournament-poker-20436.htm))
  - Most of this is about tournament payouts (ICM). In chip terms (cash games,
    play-money tables) it is an exploit of short stacks that fold too much, not a rule.
  - The `bully` option tests it with normal sizes. It never goes all in because a stack is
    short.
- **Stack-to-pot ratio.** SPR is the effective stack divided by the pot on the flop.
  - Low is about 0 to 6. With top pair or an overpair at SPR about 3, getting all in is
    easy.
  - Medium is about 7 to 16; high is 17 or more and wants near-nut hands.
  - [The Poker Bank: SPR](https://www.thepokerbank.com/strategy/concepts/spr/)
  - This is the `commit` option.
- **Push or fold.** No-ante equilibrium shares by seat at 10 big blinds: early seats about
  18 to 25%, cutoff 34%, button 44%. Above about 15 to 20 big blinds, open-raising is
  better. The 15 and 20 big blind rows on that page are estimates.
  ([PokerSkill: Push/fold charts](https://www.pokerskill.com/charts/push-fold/))
  - The heads-up small blind shoves about 58% at 10 big blinds and 62% at 8 (The
    Mathematics of Poker, from the integrator's summary). That is the heads-up row of
    `PUSH_SHARE`.
  - Only the smaller stack needs to be short. That is what `eff_push` tests: raise the
    size of the short stacks, never more.
- **Minimum defence frequency.** MDF = pot / (pot + bet): 75% against a third of the pot,
  67% against half, 60% against two thirds, 50% against the pot.
  ([PokerListings: MDF](https://www.pokerlistings.com/poker-terms/mdf))
  - The app calls on pot odds against the hands that bet, which already defends wide
    against small bets.
  - Against opponents who rarely bluff, folding more than MDF is the exploit. The
    `balanced_river` option (bluff share s/(1+2s), a balanced river bettor) tests the
    other view.
- **Stealing and re-stealing.** Steal from the hijack, cutoff and button. At 1/2, a raise
  to 5 to win 3 breaks even if it works 60% of the time. Re-steal against players who
  steal.
  ([PokerNews: Stealing and Restealing](https://www.pokernews.com/strategy/10-more-hold-em-tips-stealing-and-restealing-25606.htm))
  - The opening charts already steal wide from late seats. `reshove` tests the short-stack
    re-steal.
- **Low-stakes mistakes.**
  - Slowplaying on dry boards: check-raise strong hands instead.
  - Betting too small when the opponent is capped.
  - Not betting weak made hands to take pots early.
  - [PokerNews: GTO Wizard, 3 Mistakes Low-Stakes Players Make](https://www.pokernews.com/strategy/gto-wizard-low-stakes-mistakes-47867.htm)
- **The Mathematics of Poker** (Chen and Ankenman, from the integrator's summary):
  - balanced river bluff share s/(1+2s);
  - thin river value bets in position;
  - geometric sizing, (1+2f)^n = 1 + 2 SPR;
  - jam or fold to about 10 or 11 big blinds;
  - draws near 50% want the money in early.

  These became `balanced_river`, `river_ip_call_share`, `geometric`, `push_chart` and
  `commit_draws`.
- **Modern Poker Theory** (Acevedo, from the integrator's summary):
  - equity buckets, so good hands bet small: `bucket_sizing`, `small_bet_from`;
  - check out of position on boards that favour the raiser: `oop_lead`;
  - no bluffs into calling stations: semi-bluffs no longer go into a player labelled a
    station.
