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
| `push_chart` (26 Nov, seed 101) | tourney | mixed | 20000 | 243 | +0.6 ± 0.6 | off |
| | tourney | fish247 | 20000 | 229 | -0.2 ± 0.6 | |
| | tourney | stations | 20000 | 191 | +0.3 ± 0.7 | |
| | tourney | maniacs | 20000 | 153 | +0.7 ± 0.6 | |
| `committed_raise: 0.25` (26 Nov, seed 101, `--short-raise`) | tourney | mixed | 20000 | 343 | +0.7 ± 1.0 | off |
| | tourney | fish247 | 20000 | 90 | -0.2 ± 0.5 | |
| | tourney | stations | 20000 | 85 | -0.8 ± 0.5 | |
| | tourney | maniacs | 20000 | 399 | +0.6 ± 1.2 | |

Note on the first `ev_sizing` run: its sizing maths used a time limit, not a fixed number
of samples, so that run was not exactly repeatable. The simulator now fixes the sample
count for it too (`variant` in tools/simulate.py). The profile runs above it use that.

`committed_raise` (added 26 Nov after Kevin's K9 hand: a 247 bot raised to 30 of its 100 at
5/10): facing one raise from a committed short stack, decide on the whole effective stack against
the push-or-fold range for the raiser's seat. Measured with `--short-raise` (short bots raise small
instead of moving all in, as that 247 bot did); without it the simulator never makes the spot (0 of
2000 hands differ). Neither it nor `push_chart` (Kevin's Q8 offsuit with 5 big blinds) is
significant over 20000 hands; `committed_raise` leans negative against stations (1.6 SE), whose
short raises are tighter than the charts assume. Both stay off. One "folded the best possible
hand" appeared on the stations table in both runs; it is B0's (the base variant's count).

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
  rules.
- The push-or-fold solver isn't wired into the advice. The `push_chart` option still
  uses its hand-typed table.

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
