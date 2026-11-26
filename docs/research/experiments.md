# Strategy experiments

Every strategy option is a key in `app.poker.advice.TUNING`. The defaults are the frozen
baseline in `baseline_tuning.json` (a test checks that they match). An option becomes a
default only with credible paired evidence:

- an improvement of at least 2.5 standard errors on the default mixed table, and
- no significant loss on the fish247 table (bots like the ones on 247 Free Poker), and
- for stack-depth options, also no significant loss with tournament-like stacks, and
- from Phase 1 on, no significant loss on any held-out table (`heldout`, `regulars`,
  `switchers`, `wildcards`), which no option may be tuned on.

Whoever changes a default writes the new baseline to `baseline_tuning.json` and adds the
evidence here.

## How the numbers were made

`python tools/compare.py '<overrides>' <hands> --tables <tables> [--stacks even|uneven|tourney] [--profiles]`

Every row under Results was made before Phase 1, with what is now `--method classic`, whose
raw difference gives exactly those numbers again (a test pins two runs). From Phase 1 on the
default is duplicate deals with the luck adjustment and replays; see "Phase 1" below.

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

## Phase 1: comparing with less luck (26 Nov 2026)

The roadmap's Phase 1 gate: the standard error (SE) per comparison at least halved. What was
built, what was measured, and the decision.

### What was built

- **Duplicate deals** (`--method duplicate`): each deck is played six times with the players
  moved one seat on each time, so the app and every bot hold each seat's cards from that
  seat's position once.
- **A seed per bot decision** (also `--method keyed`, without the rotation): a bot's n-th
  decision on a street draws the same random numbers in both variants, whatever happened
  before it.
- **Luck adjustment** (`tools/luck.py`, after AIVAT): each board card's luck is taken out of
  the hand's result. The value of a moment is exact (the simulator knows every hole card)
  and mixes two values: what the app wins if the hand is checked down, and the same as if
  everyone still in had also put in their chips behind. The mix weights (by street and SPR
  band) were fitted once on seed 505 training hands and frozen. Each correction averages
  exactly zero, so the adjustment is unbiased (tests check this card by card).
- **Replays from where the variants part** (`--resample 6`): each hand where they differ is
  played five more times from that decision with fresh bot random numbers and board cards
  (the same for both), and the six results are averaged. Unbiased, since which hands get
  replayed depends only on what happened before they part.
- Standard errors count a deck's six hands as one unit; `--jobs N` splits a run over
  processes with identical results; `--save` keeps every hand's numbers.

### The gate

Rule, written in `runs/phase1_gate.sh` before each run: for 8 comparisons, r = SE of the new
way over SE of the classic raw difference, 3000 hands each, fresh seeds. Pass if the
geometric mean of r is at most 0.5, no r is above 0.75, and the new way takes at most 1.25
times as long. The estimator was improved twice, each time fixed before the seed it was
judged on.

| Comparison | Run 1: seed 303, checked down | Run 2: seed 404, frozen weights | Run 3: seed 404, with replays |
|---|---|---|---|
| `ev_sizing`, mixed | 0.90 | 0.68 | 0.49 |
| `ev_sizing`, fish247 | 0.58 | 0.94 | 0.78 |
| `bet_size: 0.5` | 0.80 | 0.90 | 0.57 |
| `semibluff_turn: "never"` | 1.09 | 0.43 | 0.48 |
| `texture_sizing` | 0.47 | 1.51 | 1.01 |
| `push_chart`, tourney | 0.33 | 0.43 | 0.42 |
| `stab: 0.0` | 0.38 | 1.05 | 1.29 |
| `commit: 1.0` | no hand differs | no hand differs | no hand differs |
| **Geometric mean** | **0.60** | **0.77** | **0.66** |
| Largest | 1.09 | 1.51 | 1.29 |
| Time, new / classic | 0.90 | 1.05 | 1.05 |

**All three runs fail.** Runs 2 and 3 are the same seed-404 runs (made with the replays),
so they share one time ratio. Full tables: `runs/phase1_gate/summary.md` and
`runs/phase1_gate_404/summary.md`.

### What the numbers say

1. **Ratios across methods are too noisy to settle this at 3000 hands.** The difference is
   zero in 94 to 99.5% of hands, and the five biggest hands carry 80 to 90% of the variance,
   so an SE from one run can easily be off by half. `texture_sizing` went from 0.47 on one
   seed to 1.51 on the other. Duplicate and classic deals play different hands, so their
   ratio carries that noise twice.
2. **On the same hands the gain is steady**: SE as a share of the raw SE, duplicate runs.

   | Seed | Checked down | Frozen weights | With replays |
   |---|---|---|---|
   | 303 | 0.75 | 0.71 | (not run) |
   | 404 | 0.72 | 0.70 | 0.60 |

   0.60 means 2.8 times fewer hands for the same precision. It is largest where the money
   goes in before the river (`push_chart`: 0.32) and smallest where it does not
   (`stab: 0.0`, 18 hands differ: little or no gain).
3. **Seat rotation and keyed bots show no measurable effect on paired comparisons**:
   duplicate raw over classic raw has a geometric mean of 0.80 on seed 303 and 1.11 on seed
   404. In hindsight that fits: both variants already get the same cards, which is what
   rotation is for. The six hands of a deck are not correlated either (clustered and
   independent SEs agree within 8%).
4. **The plain checked-down adjustment can add variance.** In seed 303's classic runs it
   made four of eight SEs bigger. Example (hand 2742, `bet_size: 0.5`): the base variant
   went all in on the turn as a 72% favourite (adjusted to its equity, +42 bb); the other
   bet small, the flush card came, and it called off its stack after it. Both lost 100 bb,
   but only the first loss was corrected. The all-in value mix fixes part of this.
5. **Where the variance left is** (`runs/phase1_variance_split.py`, seed 303, 1200 hands,
   each differing hand replayed 6 times from where the variants part):

   | Comparison | After the split, raw | After the split, luck-adjusted | Fixed before the split, luck-adjusted |
   |---|---|---|---|
   | `ev_sizing`, fish247 | 50% | 13% | 87% |
   | `bet_size: 0.5`, mixed | 53% | 51% | 49% |
   | `ev_sizing`, mixed | 85% | 88% | 12% |

   "After the split" is board cards and bot random choices still to come; the replays
   shrink it. "Fixed before the split" is above all the bots' hole cards, which decide how
   they answer each bet (on fish247, where the bots are nearly deterministic, that is almost
   everything). Neither the luck adjustment nor the replays can touch it.

### Decision

- **The Phase 1 gate is not passed. Phase 2 does not start** until a run on a fresh seed
  passes the same rule.
- The next step for the gate is AIVAT's imaginary observations for the bots: their
  strategies are known and, with a seed per decision, deterministic given their cards, so
  a hand's result can be averaged over every holding consistent with each bot's actions.
  That targets the "fixed before the split" share.
- Comparisons now default to duplicate deals, the frozen luck adjustment and 6 replays: on
  the same hands about 0.6 of the raw SE, unbiased. The replays cost time where many hands
  differ (run 3 took 1.1 to 1.5 times as long as classic for the sizing options, 1.05 on
  average; these timings shared the machine with other runs). Use the "replayed 6 times"
  figure, and `--jobs 4`. `--method classic` rebuilds every earlier row.
- Bug fixed on the way: treys gives a royal flush class 0, so a royal flush on the board
  looked like the player's own improvement over it (`hands.category` now returns 1 for
  every straight flush; regression test in `test_poker_math.py`).

### Held-out opponents

In `tools/simulate.py` (`HELD_OUT`); no strategy option may be tuned on them.

| Style | What it does that the tuning bots never do |
|---|---|
| overbettor | bets 1.1 to 1.8 times the pot (the tuning bots bet half to 0.9) |
| minbettor | bets a quarter to a third of the pot, often |
| trapper | checks strong hands 70% of the time and raises when someone bets |
| mimic | plays like a nit before the flop (and gets labelled one) and like a lag after it |
| switcher | a calling station for 30 hands, then a maniac for 30, each bot out of step |
| regular | set to the HandHQ population's action shares (below) |
| wildcard | each bot has its own random style, drawn once from a fixed seed |

Tables: `heldout` (one each of the first five), `regulars`, `switchers`, `wildcards`.

The regular against the HandHQ shares in `DATASET.md` (all table sizes), 500 hands:

| Share | HandHQ | regular |
|---|---|---|
| Preflop decisions that raise / call / fold | 14 / 14 / 69% | 13 / 12 / 73% |
| Checked to after the flop: bets | 36% | 37% |
| Facing a bet after the flop: fold / call / raise | 53 / 37 / 10% | 64 / 35 / 1% |

The bot model can't get closer on the last row: it folds whenever its strength is below the
price plus 10 points, and raises only strong hands. It is a population average, not a clone
of any player. Clones of real HandHQ players need the built dataset, which is not in this
workspace.

### Weakness report

`tools/weakness.py` replays each of the app's decisions with every other move: fold, check
or call, a small and a big bet or raise, and all in where that is a real option. Each replay
uses the same cards and bot numbers, with the app's own advice after it. Spots (street, what
the app faced, its move) are ranked by the luck-adjusted bb/100 a different move would have
gained, minus 1.5 SE. Preflop folds first in or facing one raise are replayed one in ten and
counted ten times. About half a second a hand on one core; `--jobs` splits it with identical
results.

Planted flaws (`--check-flaws`), mixed table, seed 11, 1200 hands. The cost is the flawed
copy minus the app on the same deals, luck-adjusted (negative means the flaw loses):

| Flaw | Cost (bb/100) | Rank of its spot |
|---|---|---|
| `limps`: limps instead of raising when first in | +11.7 ± 10.3 | 4 |
| `folds_river_bets`: folds every river bet without two pair or better | -14.1 ± 14.1 | 8 |
| `never_bets_river`: never bets the river when checked to | -20.1 ± 12.7 | 11 |
| `folds_to_3bets`: folds to every re-raise without the top 2% | -6.2 ± 12.0 | 17 |
| `overbets`: bets 1.5 times the pot after the flop | +20.5 ± 11.8 | not listed |
| `calls_river_bets`: calls every river bet | +12.7 ± 17.0 | not listed |

- **The success test (90% of planted flaws in the top ten) is not met: 2 of 6.**
- At this size it is not a fair test yet. No flaw's cost is significant, and two
  (overbetting, calling every river bet) may win against these bots, which bluff a lot and
  call by hand strength. A flaw that costs nothing can't be found by results. The costs
  carry about ±12 bb/100 at 1200 hands, so a fair test needs roughly ten times the hands
  (`--jobs`, on a machine with more cores).
- Two seeds of the plain baseline (11 and 12) share 5 of their top 10 spots, 4 of them with
  the same better move.
- What both seeds list for B0, as candidates for experiments (not changes):
  - raise instead of folding or checking when players limped in front;
  - raise instead of folding to a river bet (the bots fold to raises);
  - the turn facing a bet when it folds.

Baseline B0 on the held-out table (`heldout`, seed 11, 1200 hands): +42.0 ± 26.9 bb/100
raw, +38.0 ± 18.0 luck-adjusted (mixed table, seeds 11 and 12: +31.3 ± 24.9 and
+29.3 ± 22.1 luck-adjusted). Its top items there are different: raising instead of folding
to turn and flop bets, and betting small instead of checking the turn and river with a pair.
That fits the held-out bots, which bet small, overbet or fold to raises more than the
tuning bots.

### Not done in Phase 1

- Clones of individual HandHQ players (the built dataset is on another machine).
- An exploiter bot that plays against the app (local best response proper). The weakness
  report only tries other moves for the app.
- A correction for the luck of the hole-card deal, which matters for one variant's win rate,
  not for paired comparisons.
- The keyed-only runs for seed 404 were dropped to save time: cross-method ratios are too
  noisy at this size to say anything (point 1 above).

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
