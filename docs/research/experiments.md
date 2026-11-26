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
