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

- **The Phase 1 gate is not passed. Phase 2 does not start.** Runs 1 to 3 failed; run 4
  (below) fails on one of its three conditions.
- After run 3, AIVAT's imaginary observations for the bots were built and the replays were
  made to redeal the opponents' cards (next sections). Run 4 used the redeal.
- Comparisons now default to the run 4 method: duplicate deals, 6 replays from the split
  that redeal the opponents, and luck only where nobody can bet again. It is unbiased
  (checked on large runs later: Phase 1 check, the replays against the raw difference), has
  about 0.4 of the classic SE, and costs about 1.2 times the CPU. Use the "replayed 6
  times" figure, and `--jobs 4`. `--method classic` rebuilds every earlier row.
- Bug fixed on the way: treys gives a royal flush class 0, so a royal flush on the board
  looked like the player's own improvement over it (`hands.category` now returns 1 for
  every straight flush; regression test in `test_poker_math.py`).

### The opponents' cards (after run 3)

What was left after run 3 was mostly the bots' hole cards (point 5 above). Two tools go
after it. Both condition on everything up to the split, so they only touch the 1 to 6% of
hands where the variants differ.

**Imaginary observations** (`tools/hidden.py`, AIVAT's method for players whose strategy is
known). Used when the variants part heads-up after the flop:

- The opponent's class: the pairs it could hold, given everything before the split. They
  are the hands with which `bot_decide`, run again with the recorded seeds, makes exactly
  its moves. Given the split they are equally likely (a uniform deal, and a bot's move is a
  function of its cards once its random numbers are fixed).
- After the split the bot's random numbers are fresh. So each of its moves has a known
  probability for each hand in its class: `move_probs`, worked out from `bot_decide`. It
  matches 4,000 seeded runs of the bot (mean z squared 0.94).
- Each variant's result is replaced by:
  - the average result over the class hands still consistent at the end,
  - minus a correction at each of the opponent's moves and at each board card: the value
    of what happened minus the expected value.
  
  Each correction averages zero, so the estimate is unbiased whatever value is used.
- Checked exactly (`app/tests/test_hidden.py` and exhaustive scripts): deal every class hand
  to the opponent, and every runout still to come. The average estimate then equals the
  average result to 10^-15, for splits on the river, the turn and the flop (7,992 deals),
  and also with arbitrary value weights.
- Where it helps and where it doesn't:
  - Strong where the bots play by their cards: fish247, 0.44 of the raw SE against 0.84
    for replays alone (seed 303).
  - Weak where the money goes in later (the mixed table). Its values are checked-down
    values, which can't foresee the stacks going in after a card or a bet, so a late swing
    lands in one correction. Fitting value weights helped little, even in sample.

**Redealt replays** (`compare.py --redeal`):

- What changes: the replays from the split also deal each bot still in a fresh hand drawn
  from its class (all live bots together, no card twice).
- Why it's unbiased: given the split, every assignment is equally likely, and the hand up
  to the split comes out exactly the same (a test checks it). So each replay is a fresh draw
  of the rest of the hand, opponents' cards included, and the average keeps the expected
  value.
- It needs no value function, works for multiway and preflop splits, and costs no more than
  the replays.
- Why this isn't the same as playing more hands: it averages over the opponents' cards only
  in the hands that differ, which are the only ones that carry the difference.

Exploration on seeds 303 and 404 (1500 hands each), same hands, SE as a share of the raw
SE (`runs/phase1_redeal/summary.md`):

| Estimate | Geometric mean (14 cells) | Largest cell |
|---|---|---|
| Replays (run 3), raw | 0.65 | 1.04 |
| Replays, luck-adjusted | 0.61 | 1.02 |
| Redealt replays, raw | 0.46 | 0.97 |
| Redealt replays, luck-adjusted | 0.39 | 1.00 |
| Redealt replays, luck only where nobody can bet again | 0.39 | 1.22 |

- The last one was chosen for run 4. Pooled over the two seeds per comparison it was the
  best: about 0.39 overall, worst comparison about 0.77 (`semibluff_turn: "never"`).
- The full luck adjustment blew up on one comparison (`stab: 0.0`, seed 303: 0.98 of raw).
  Correcting one variant's board luck but not the other's breaks the cancellation that
  common cards give. Even exact corrections can do that, as `texture_sizing` on seed 303
  shows.
- On top of the redeal, the hidden-cards estimate did not help consistently.

### Gate run 4

Rule (`runs/phase1_gate4.sh`, committed before any hand on its seeds was played):

- The new way: redealt replays with luck only where nobody can bet again, on seeds 606 and
  707.
- The old way: classic raw, on seeds 303, 404, 606 and 707.
- r is the ratio of their sd per hand, pooled over seeds. A single 3000-hand run's SE can
  be off by half, which is why the sd is pooled.
- The same three conditions as before: geometric mean at most 0.5, no r above 0.75, CPU per
  hand at most 1.25 times classic.

| Comparison | Hands, new / old | New way (bb/100) | Old way (bb/100) | r |
|---|---|---|---|---|
| `stab: 0.0` | 6000 / 12000 | -0.5 ± 0.4 | -5.2 ± 2.3 | 0.12 |
| `push_chart`, tourney | 6000 / 12000 | -0.0 ± 0.2 | -0.3 ± 0.9 | 0.17 |
| `ev_sizing`, fish247 | 6000 / 12000 | +2.5 ± 1.4 | +2.8 ± 2.9 | 0.35 |
| `ev_sizing`, mixed | 6000 / 12000 | +2.0 ± 1.3 | +1.1 ± 2.4 | 0.39 |
| `bet_size: 0.5` | 6000 / 12000 | -2.3 ± 1.3 | -3.5 ± 2.3 | 0.40 |
| `texture_sizing` | 6000 / 12000 | -1.9 ± 1.1 | -0.8 ± 1.6 | 0.51 |
| `semibluff_turn: "never"` | 6000 / 12000 | -2.5 ± 1.1 | -3.1 ± 0.9 | 0.80 |
| `commit: 1.0` | 6000 / 12000 | +1.3 ± 1.1 | -0.1 ± 0.4 | 2.02 |

Geometric mean of r: **0.42** (passes, at most 0.5). CPU per hand: **1.17** times classic
(passes, at most 1.25). Largest r: **2.02** (fails, at most 0.75). **Run 4 fails**, on the
third condition only.

- `commit: 1.0` changes almost nothing:
  - Of 12000 old-way hands, 7 differ and 2 differ in the result (-39 and +26 bb).
  - Of 6000 new-way hands, 4 differ and 2 differ by more than 3 bb (+16 and +65).
  - Both SEs come from those few hands, so their ratio carries almost no information.
  - The rule left out only comparisons in which no hand differs, so it counts.
- `semibluff_turn: "never"`: about 1 hand in 130 differs (47 of 6000 new, 86 of 12000 old).
  What's left is how much the true effect varies from hand to hand given the split. No
  method that conditions on the split can take that out.
- On the six comparisons where many hands differ, the SE is 0.12 to 0.51 of classic: more
  than halved everywhere except `texture_sizing` (0.51).
- Even with `commit` left out, `semibluff_turn: "never"` (0.80) fails the third condition;
  its exploration cells gave 0.76 and 0.77, so that is not chance.
- So the gate as written is not passed, and Phase 2 does not start.
- Read as "halved on average", it is passed (0.42, 5.7 times fewer hands for the same
  precision).
- Which reading counts, or whether to change the rule (for example, judge only comparisons
  in which at least 1% of hands differ, or drop the per-comparison condition), is Kevin's
  decision, to be written down before any further gate run.
- Share of hands that differ in run 4 (new / old): `ev_sizing` fish247 5.6% / 5.1%,
  `bet_size: 0.5` 4.1% / 4.2%, `texture_sizing` 4.1% / 4.2%, `ev_sizing` mixed 3.9% / 4.0%,
  `push_chart` 1.4% / 1.1%, `semibluff_turn: "never"` 0.8% / 0.7%, `stab: 0.0` 0.5% / 0.7%,
  `commit: 1.0` 0.07% / 0.06%.
- A 1% cutoff would set aside three comparisons. Two are the failing ones; the third,
  `stab: 0.0`, passes anyway (0.12). Any such rule is chosen after seeing run 4, so it should
  be confirmed by a run on fresh seeds before Phase 2.

**Decision (Kevin, 26 Nov 2026, after run 4):** judge only comparisons in which at least 1%
of hands play differently, and confirm on fresh seeds.

### Gate run 5

Rule (`runs/phase1_gate5.sh`, committed before any hand on its seeds was played):

- The new way: as in run 4, on seeds 808 and 909 (never used before).
- The old way: classic raw, pooled over seeds 303, 404, 606, 707, 808 and 909.
- Judged: the comparisons in which at least 1% of the new way's hands differ (seeds 808 and
  909 together).
- Pass:
  - geometric mean of r over those at most 0.5;
  - none of them above 0.75;
  - CPU per hand at most 1.25 times classic, over all eight comparisons.
- If run 5 passes, the Phase 1 gate is passed. Run 4 would also pass this rule (0.34; largest
  0.51; CPU 1.17), but it was used to choose the rule, so it doesn't count.

Result (`runs/phase1_gate5/`, `summary.md`). Hands: 6000 new way (seeds 808 and 909), 18000
old way (seeds 303 to 909).

| Comparison | Hands that differ, new | New way (bb/100) | Old way (bb/100) | r |
|---|---|---|---|---|
| `push_chart`, tourney | 1.07% | -0.1 ± 0.2 | -0.6 ± 0.7 | 0.153 |
| `ev_sizing`, fish247 | 5.55% | +3.6 ± 1.6 | +1.6 ± 2.2 | 0.434 |
| `ev_sizing`, mixed | 4.27% | +0.5 ± 1.9 | +1.1 ± 1.9 | 0.583 |
| `bet_size: 0.5` | 4.45% | -2.5 ± 2.2 | -3.3 ± 1.7 | 0.734 |
| `texture_sizing` | 4.45% | -3.0 ± 1.6 | -0.9 ± 1.3 | 0.751 |
| Not judged (under 1%): `stab: 0.0` | 0.87% | -2.9 ± 1.2 | -5.3 ± 1.8 | 0.381 |
| Not judged: `semibluff_turn: "never"` | 0.78% | -1.6 ± 0.8 | -2.3 ± 0.8 | 0.572 |
| Not judged: `commit: 1.0` | 0.12% | +0.8 ± 1.1 | -0.4 ± 0.4 | 1.453 |

Geometric mean of r over the five judged: **0.46** (passes, at most 0.5). CPU per hand:
**1.24** times classic (passes, at most 1.25). Largest judged r: **0.7507**, `texture_sizing`
(fails, at most 0.75). **Run 5 fails**, on the third condition, by 0.0007. `summary.md` shows
it rounded to 0.75.

- `bet_size: 0.5` (0.734) is just under the bar too.
- Nothing in the method changed between runs 4 and 5, yet the same comparisons moved a lot:
  `bet_size: 0.5` from 0.40 to 0.73, `texture_sizing` from 0.51 to 0.75, `ev_sizing` on mixed
  from 0.39 to 0.58. An sd estimated from 6000 hands with a few large results is itself noisy.

How much one run moves by chance (`runs/phase1_gate5_noise.py`, output in
`phase1_gate5/noise.md`). It was worked out after run 5's result was seen, so it describes the
runs and tests nothing.

| Comparison | Run 4 | Run 5 | Both pooled | 95% of runs like run 5 |
|---|---|---|---|---|
| `push_chart`, tourney | 0.17 | 0.15 | 0.16 | 0.12 to 0.20 |
| `ev_sizing`, fish247 | 0.35 | 0.43 | 0.41 | 0.30 to 0.56 |
| `ev_sizing`, mixed | 0.39 | 0.58 | 0.50 | 0.33 to 0.72 |
| `bet_size: 0.5` | 0.40 | 0.73 | 0.61 | 0.42 to 0.83 |
| `texture_sizing` | 0.51 | 0.75 | 0.65 | 0.43 to 0.95 |

- Pooled: the new way's 12000 hands of runs 4 and 5 (seeds 606, 707, 808 and 909) over the
  old way's 18000.
- Last column: 2000 runs of run 5's size drawn with replacement from the pooled hands, with
  the same decks for every comparison, as fresh seeds would give.
- In those draws run 5's rule passes its two r conditions 67% of the time: the geometric
  mean in 93%, the largest r in 69% (`texture_sizing` is above 0.75 in 24% of draws,
  `bet_size: 0.5` in 11%). The CPU condition comes on top: 1.17 in run 4 and 1.24 in run 5,
  against 1.25.
- So if the pooled numbers are about right, a run like this fails about one time in three
  by chance alone.
- Pooled, the geometric mean over the five is 0.42, and 0.53 without `push_chart`.
  `push_chart` changes all-in decisions before the flop, after which nobody can bet, so the
  luck of every board card comes out exactly. On `bet_size: 0.5` and `texture_sizing` the SE
  is about 0.6 to 0.65 of classic, not halved.
- Even so, the new way needs less CPU for the same precision in every judged comparison: r
  squared times that comparison's CPU ratio is 0.02 (`push_chart`) to 0.73
  (`texture_sizing`) in run 5. It is unbiased (see above, and the Phase 1 check near the end),
  so it stays the default in `tools/compare.py`.
- **So the gate as written is not passed, and Phase 2 does not start.**
- What next (another run decided in advance, a different rule, or starting Phase 2 without a
  pass) is Kevin's decision, to be written down here before anything more is run for the
  gate.

**Decision (Kevin, 26 Nov 2026, after run 5): good enough.**

- The gate is not passed as written. Phase 1 is closed on Kevin's call, not on a pass.
- The comparison of `river_solver` against B0 (the rest of Phase 2's gate) may go ahead.
- The new way stays the default for comparisons.
- Known limit: on changes like `bet_size: 0.5` and `texture_sizing` the SE is about 0.6 to
  0.65 of classic, so such comparisons need about 2.5 times fewer hands than classic, not 4.

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
- A heads-up simulator mode (`--players 2`, each deal played twice with the seats swapped),
  which the new roadmap's Phase 1 adds, with the check that B0 plays heads-up. Added later:
  see "Phase 1: the heads-up mode" below.

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

## Phase 2: the river solver against B0 (26 Nov 2026)

Phase 1 was closed by Kevin's decision (Phase 1, gate run 5), so the rest of Phase 2's gate
can run: `river_solver` must beat B0 by 2.5 SE.

**Read this with the merge in mind.** This was run on a branch, with the solver as it was
before the two sections below it: both players' ranges were the "medium" preset, and
simulations used this section's fixed 300 iterations. At the merge with main the next
sections' work came in: ranges from the betting, and `river_solver_fixed_work`, which
replaced `SOLVER_ITERATIONS`. So the result below is for that older solver, and running
`runs/phase2_solver_b0.sh` again now gives different numbers. The new roadmap (replaced the
same day) doesn't ask for this comparison.

### Simulations repeat exactly

In the app the solver stops on its 300 ms budget, so how far it gets depends on the machine.
In a 300-hand probe on the mixed table (seed 7, one process on a cloud core), the budget
stopped 12 of its 17 calls, at 246 to 326 iterations (median 278). The other 5 reached 0.1%
of the pot first. So comparisons with the switch on would change from run to run, between
one process and `--jobs`, and with how many runs share the machine.

- Simulations (`tools/simulate.py`, `SOLVER_ITERATIONS`) now give the solver a fixed 300
  iterations in place of the budget. It still stops early at 0.1% of the pot, and it never
  falls back to the rules for being slow. 300 is about what the budget allows on a cloud
  core; a faster machine gets further in the app.
- The app is unchanged: the budget still decides there (`app/poker/advice.py`,
  `SOLVER_ITERATIONS` is None). With the switch off nothing changes anywhere.
- Test (`app/tests/test_solver_simulation.py`): 36 hands in which the solver changes a
  decision give the same results twice, with a 1 ms budget, and split over two processes.
  Before the change, the 1 ms budget changed them.

### The comparison: rule

`runs/phase2_solver_b0.sh`, committed before any hand on its seeds was played:

- Each run: `tools/compare.py '{"river_solver": true}' 3000 --tables <table> --seed <seed>`
  with the defaults (Phase 1's way: duplicate decks, 6 replays from the split with the bots
  redealt, luck only where nobody can bet again; even stacks; no profiles).
- The estimate: the "replayed 6 times" figure, pooled over a stage's seeds, SE with decks
  as units.
- Stage 1: mixed, seeds 1111, 2222, 3333 and 4444 (12000 hands). Passes if `river_solver`
  minus B0 is at least 2.5 SE.
- Stage 2, only if stage 1 passes: fish247 and the four held-out tables, seeds 1111 and
  2222 (6000 hands each). Passes if none loses significantly, taken here as -2 SE or less.
- Stages 3 and 4, only if 1 and 2 pass: the same on fresh seeds (5555 to 8888 for mixed,
  5555 and 6666 for the others).
- The B0 bar is met only if all four pass. Even then the switch stays off until Kevin
  decides, since it changes what the app tells him at the table. If a stage fails, the
  later ones aren't run and the switch stays off.
- Chosen from a pilot on seed 7 (600 hands, mixed, already used for the probe): +15.0 ±
  12.4 bb/100 with 9 hands that differ. Projected SE at 12000 hands: about 2.8 bb/100.

All figures below are `river_solver` minus B0, "replayed 6 times", in bb/100
(`runs/phase2_solver_b0/`, one `stage<n>.md` per stage). No run had any always-wrong
instruction.

### Stage 1: mixed (passes)

| Seed | Hands that differ | river_solver minus B0 |
|---|---|---|
| 1111 | 77 | +12.8 ± 4.8 |
| 2222 | 57 | -0.9 ± 2.9 |
| 3333 | 59 | +8.1 ± 4.5 |
| 4444 | 60 | +3.2 ± 3.3 |
| **Pooled, 12000 hands** | **253 (2.1%)** | **+5.8 ± 2.0, that is 2.94 SE** |

The four seeds spread a bit more than their SEs suggest (Cochran's Q 7.0 on 3 degrees of
freedom, p about 0.07), so the SE may be a little small. Stage 3, on fresh seeds, checks
that.

### Stage 2: fish247 and the held-out tables (passes)

6000 hands each, seeds 1111 and 2222:

| Table | Hands that differ | river_solver minus B0 | In SE |
|---|---|---|---|
| fish247 | 205 (3.4%) | +1.6 ± 2.9 | +0.55 |
| heldout | 169 (2.8%) | +1.0 ± 2.9 | +0.33 |
| regulars | 109 (1.8%) | +5.0 ± 2.1 | +2.44 |
| switchers | 121 (2.0%) | +3.9 ± 3.5 | +1.12 |
| wildcards | 148 (2.5%) | +2.4 ± 3.6 | +0.66 |

None loses significantly (the bar was -2 SE). All five are ahead, none by 2.5 SE.

### Stage 3: mixed on fresh seeds (fails)

| Seed | Hands that differ | river_solver minus B0 |
|---|---|---|
| 5555 | 72 | +8.5 ± 5.2 |
| 6666 | 86 | -2.5 ± 4.5 |
| 7777 | 68 | +2.9 ± 2.8 |
| 8888 | 65 | -1.1 ± 4.8 |
| **Pooled, 12000 hands** | **291 (2.4%)** | **+2.0 ± 2.2, that is 0.88 SE** |

**Stage 1 did not repeat, so `river_solver` does not meet the B0 bar and stays off.** As
the rule says, stage 4 was not run. B0 is unchanged.

- The two stages don't contradict each other: they are 1.3 SE apart. Stage 1 was probably
  on the lucky side, which is what the repeat on fresh seeds is for.
- Described, not a test (pooling wasn't in the rule): all eight mixed seeds together, 24000
  hands, give +3.9 ± 1.5 (2.6 SE, 95% range about +1 to +7), and no table lost in stage 2.
  So the solver probably gains a little on the river against these bots, but the rule's
  repeat didn't confirm it.
- A likely limit: the solver assumes both players hold the "medium" preset range
  (`app/solver/bridge.py`), whatever they did before the river. The opponent model
  (Phase 3) is what would give it real ranges.
- Another try needs a new rule, written down before its seeds are played (for example more
  hands, or once the solver has real ranges). That is Kevin's call.

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

## Phase 2: the Python solver as a reference (26 Nov 2026)

Not a strategy experiment: nothing was compared for strength, and the app and B0 are
untouched. Under the new roadmap the Python river solver is the reference the Rust solver
must match, so this measures how far it can be trusted. Script and raw output:
`runs/phase2_reference.py`, `runs/phase2_reference.log`. Write-up: `RIVER_SOLVER.md`.

**What was made.** 20 river spots with the Python solver's answer to each, in
`data/reference_spots/python_solver/` (formats of `data/SPOT_FORMAT.md`): 12 with an answer
worked out by hand, 4 realistic ones written as ranges, 4 with the ranges the app builds
from a betting line. Each solved with no clock to 0.001% of the pot.

**Results.**

| Check | Result |
| --- | --- |
| Known answers (half-street game at 8 sizes and shapes: bluff share s/(1+2s), call share 1/(1+s), value) | Shares within 0.0002, values within 0.0001 chips of a pot of 100 |
| Known values of the 4 trivial spots (0, 0, 100, 50) | Within 0.001 chips |
| Exploitability of the 20 saved answers | 0.0001% to 0.0010% of the pot, so each true value is known to within 0.002 chips |
| The same 20 spots in the app's 300 ms | 0.02% to 0.08% of the pot, in 2 to 290 ms |
| Time to 0.5% / 0.1% / 0.01% of the pot | Median 5 / 12 / 61 ms, slowest 131 / 382 / 1,366 ms |
| Against TexasSolver's 30 river keys | Bounds meet on all 30. Values differ by 0.09 chips on average, 0.31 at most (r01, where the true value is 100 and TexasSolver says 100.307) |
| The Rust solver (`engine/crates/subgame`) on the 20 spots, default target 0.3% | No problems. Value within 0.38 chips of the reference on every spot, bounds meet on all 20 |
| The Rust solver at a 0.01% target | No problems. Value within 0.016 chips, known bluff and call shares within half a point |
| Push-or-fold at 5, 8, 10, 12, 15 big blinds | 11 to 21 ms, exploitability under 0.000001 big blinds a hand, shares within 0.7 points of the published chart |

**Two things learned.**

- Frequencies move far more than values. At 0.3% of the pot from an equilibrium the Rust
  solver's call share on py05 (a quarter-pot bet) is 7 points from the known one, while its
  value is 0.1 chips off. So a solver is checked by value and bounds, and the known shares
  are only asked of a tight solve.
- The last decimals are expensive: the 2-pot bet (py04) needs 2,048 iterations for 0.01%
  and 32,768 for 0.001%.

**Decision.** The reference set stays as the check for the Rust solver and what follows it
(`python -m tools.reference_spots rust`). Nothing to switch on.

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

## Phase 1 check: the replays against the raw difference (26 Nov 2026)

Kevin's Phase 1 brief asks for a large run showing that the luck-reduced mean matches the raw
mean within its SE. The luck adjustment had such tests, card by card. The default "replayed 6
times" figure (replays from the split that redeal the opponents) only had an argument. This
section checks it. Scripts and one output file per test: `runs/phase1_replay_explore/`
(`run.sh` rebuilds them) and `runs/phase1_replay_check.sh`.

**On the gate runs' hands** (runs 4 and 5, seeds 606 to 909, 12000 hands per comparison,
bb/100):

| Comparison | Raw | Replayed 6 times | Replayed minus raw |
|---|---|---|---|
| `push_chart`, tourney | -0.8 ± 0.8 | -0.1 ± 0.1 | +0.7 ± 0.8 (+0.9 SE) |
| `ev_sizing`, fish247 | +4.6 ± 2.4 | +3.0 ± 1.1 | -1.6 ± 2.1 (-0.8 SE) |
| `ev_sizing`, mixed | -0.4 ± 2.0 | +1.3 ± 1.2 | +1.7 ± 2.0 (+0.8 SE) |
| `bet_size: 0.5` | +6.7 ± 2.6 | -2.4 ± 1.3 | -9.2 ± 2.4 (-3.8 SE) |
| `texture_sizing` | +0.9 ± 1.8 | -2.5 ± 1.0 | -3.4 ± 1.7 (-1.9 SE) |
| `stab: 0.0` | -2.3 ± 1.4 | -1.7 ± 0.6 | +0.6 ± 1.1 (+0.6 SE) |
| `semibluff_turn: "never"` | -0.2 ± 1.0 | -2.1 ± 0.7 | -1.9 ± 1.2 (-1.5 SE) |
| `commit: 1.0` | +1.2 ± 1.4 | +1.1 ± 0.8 | -0.2 ± 1.3 (-0.1 SE) |

The luck adjustment alone (no replays) is within 1.7 SE of raw on all eight. `bet_size: 0.5`
fails the check by a wide margin, so it was looked at play by play.

**`bet_size: 0.5`, every play kept** (`record.py`: for each of the 513 hands that differ, the
original pair, 5 replays with the bots' real cards and 5 redealt):

- On every hand that differs (here and on the 8 new seeds below): the replays repeat the
  betting before the split exactly, with real or redealt cards; the bots' real hands are in
  their classes; and replaying the real hands through the redeal code gives the same results
  (salts 1 and 2).
- The gap comes from a few big pots. In 9 hands the original deal had the half-pot bet 62 to
  137 bb ahead, and none went the other way; the replays' big swings go both ways. Hand 2980
  of seed 909 is one: a station holding A-K folds to a 2/3-pot bet on A-J-2 but calls half
  pot, then calls down against a set (+89.5 bb). The half-pot bet really does win there; the
  question is only how often such hands come up.
- If the replays keep the expected value, the original deal is just one of a hand's six
  exchangeable plays. Picking at random which one counts as the original (per hand) puts the
  observed gap in the bottom 0.03% (real-card replays) and below every one of 4000 draws
  (redealt).

**Where the real hands sit within their classes** (1885 live bots in hands that differ, on
the gate seeds and the 8 new seeds below): their rank by preflop strength is 0.50 and by
strength at the split 0.51 (0.5 expected). In the band that folds to the 2/3-pot bet but
calls half pot (first answer after the split, same random numbers) there are 46 real hands
against 42.8 expected. They beat the app at showdown on the original board 361 times against
356 expected. Subgroups move by up to 2.7 SE in both directions (heads-up high, multiway low
on the new seeds), about what this many looks give by chance.

**On 8 new seeds** (41 to 48, 24000 hands, 1020 that differ):

| Estimate of `bet_size: 0.5` | bb/100 |
|---|---|
| Raw | -2.1 ± 1.6 |
| Replays with the bots' real cards | -2.4 ± 1.2 |
| Redealt replays (the default, before the luck adjustment) | -4.1 ± 0.9 |
| Classic, gate run 5's 18000 separate hands | -3.3 ± 1.7 |

- Real-card replays against the original deals: -0.09 ± 0.27 bb per hand that differs
  (relabelling p 0.38). Redealt replays: -0.56 ± 0.34 (p 0.04).
- The exact test of the redeal: one extra redealt hand per hand, replayed with the same 5
  salts as the real cards. If the redeal draws from the right hands, the two are
  interchangeable, so the sign of their difference is a coin flip whatever the tails look
  like. Real minus redealt: +0.005 ± 0.24 bb per hand, p 0.98 (two-sided). On the gate seeds
  it was +0.95 ± 0.44, p 0.03.

**The confirming check** (`runs/phase1_replay_check.sh`, its rule committed before any hand
on its seeds was played). Seeds 51 to 66, 48000 hands, 2210 that differ. For each of those
hands, three arms replayed with salts 1 to 5: the bots' real cards and two redealt draws. The
test is the exact relabelling one, one-sided. The rule: p under 0.01 means biased, p over 0.10
means no sign of a bias.

| Estimate of `bet_size: 0.5` | bb/100 |
|---|---|
| Raw (the original deals) | -3.6 ± 1.2 |
| Replays with the bots' real cards | -3.9 ± 0.8 |
| Redealt replays | -3.4 ± 0.6 |

Real arm minus redealt arms: -0.5 bb/100, z -0.6, p 0.73. **No sign of a bias on new hands.**
Raw minus redealt: -0.2 ± 1.2 bb/100.

**So:**

- The gap on the gate runs' hands was the raw figure's luck, not the replays': a few big pots
  the half-pot bet happened to win, which the replays average out. The new seeds and the
  classic method agree with the replayed figure. On its own that draw was unusual (about 1 in
  3000, or 1 in 400 allowing for the eight comparisons).
- With a few big pots deciding it, the raw figure can move further than its ± suggests. That
  is one more reason to read the "replayed 6 times" figure.
- The redeal stays the default. Gate runs 4 and 5 measured SE ratios, which a gap in the
  mean doesn't touch. The `river_solver` comparison used the replayed figure. Both stand.
- For Kevin's brief (item 2): on 48000 new hands the redealt replays' mean matches the raw
  mean (-0.2 ± 1.2 bb/100 apart) with about half the SE (0.61 against 1.16, before the luck
  adjustment).
- Also seen on the way: half-pot value bets lose to B0's two thirds of the pot by about 3.5
  bb/100 on mixed. B0 isn't tuned any more, so nothing changes.

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
    two lines agree and says nothing about `river_solver` against B0 (for that, see
    "Phase 2: the river solver against B0").
  - Those runs used the comparison tool as it was before the Phase 1 tools arrived
    (`--method classic` today). Run again with the tool as it is now (duplicate decks,
    hands that differ replayed 6 times): 0 of 150 and 0 of 1,002 hands differ.
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
  bb/100, and a second run gives the same line. With the comparison tool as it is now
  (duplicate decks, replays): 1 of 1,002 hands differs, -0.9 ± 0.9 bb/100 replayed 6
  times. This compares the two solvers on the same spots, not either of them with B0.
  Log: `runs/rust_solver_switch_check.log`.

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

## Phase 1: the heads-up mode (26 Nov 2026)

The last part of Kevin's Phase 1 brief: a heads-up mode (`--players 2`) in the simulator and
the comparisons, B0 playing heads-up without always-wrong instructions, six-max play not
changed at all, and the gate (SE at least halved) for heads-up too.

### What was built

- **`tools/simulate.py --players 2`**: the app against one of the table's five bots at a
  time: the first of each deal's seat shuffle, so a different one from deal to deal.
  - Heads-up rules: the button posts the small blind and acts first before the flop; the big
    blind acts first on the flop, turn and river.
  - The seats are named as the reader names them, "BTN/SB" and "BB"
    (`app.state.positions`), so the advice sees what it would see at a real two-player table.
- **`tools/compare.py --players 2`**: duplicate deals play each deal twice with the seats
  swapped. The app holds the button's cards once and the big blind's once, against the same
  bot on the same board. Everything else works as in six-max:
  - a seed per bot decision;
  - 6 replays from where the variants part, with the bot dealt fresh hands it could hold;
  - the luck of board cards after which nobody can bet again taken out;
  - a deck's two hands as one unit for the SE;
  - `--jobs`, with the same results.
- **More always-wrong checks** in `simulate.check_advice`, for moves the table can't take as
  said:
  - a bet or raise under the minimum, or more than the stack;
  - CALL with nothing to call, CHECK facing a bet;
  - folding aces before the flop.
- **Nothing in `app/poker` changed**, B0 included. The advice already handled the heads-up
  seats: the button's chart (`charts.OPEN["BTN/SB"]`), the raiser's seat group, who is in
  position, and the players behind for push-or-fold.
- **Six-max plays exactly as before.** These were all identical to the commit before the
  heads-up mode, problem counts included:
  - 720 hands on four tables and stack settings;
  - 120 hands with profiles;
  - paired runs of 72 hands with each of the three methods.

  `test_six_max_unchanged_by_the_heads_up_mode` pins some of them, and the baseline test
  passes.

### B0 heads-up

`runs/phase1_heads_up_b0.sh` and `phase1_heads_up_b0/summary.md`: every table and stack
setting heads-up, 2000 hands each (1000 with profiles), and three six-max runs with the same
checks for comparison.

| Heads-up, 2000 hands each | B0, bb/100 | Button raises |
|---|---|---|
| mixed / stations / nits / tags | +20.2 / +24.4 / +30.9 / +25.1 | 44% / 43% / 42% / 44% |
| lags / maniacs / fish247 | +22.2 / +5.9 / +22.0 | 43% / 45% / 46% |
| heldout / regulars / switchers / wildcards | +19.3 / +26.1 / +25.3 / +2.0 | 44% / 44% / 46% / 47% |
| mixed: uneven / tourney / 500 bb deep / profiles (1000) | +27.2 / +20.8 / +18.0 / +24.8 | 41% / 42% / 43% / 44% |
| fish247: tourney / 500 bb deep | +10.6 / +7.7 | 43% / 45% |

- **No always-wrong instruction** in 37629 heads-up instructions (33000 hands, 17 settings).
  That covers every tuning and held-out table, uneven and tournament stacks, 500 big blinds
  deep, and profiles. Both kinds of check found nothing: `check_advice`'s and the new ones.
- From the button B0 raises 41% to 47% of hands and folds the rest. That's its six-max
  button chart (`OPEN["BTN/SB"] = OPEN["BTN"]`). Heads-up solver strategies open far wider
  (about 80% at 100 big blinds), but that's a question for the new agent, not a bug, and B0
  is frozen.
- **The bots keep their six-max styles**, so heads-up they fold a lot before the flop
  (`runs/phase1_heads_up_bots.py`, mixed, 2500 hands, in `phase1_heads_up_b0/bots.txt`):
  - in the big blind facing an open: the nit 92%, the tag 85%, the lag 84%, the maniac 67%
    and the station 66%;
  - on the button, first in: the nit 83%, the tag 81%, the lag 68%, the station 51% and the
    maniac 43%.

  So B0 wins against every table, and the bots are weak heads-up opponents. Heads-up styles
  for them would need data: the HandHQ heads-up hands are in the shelved dataset.
- **One older six-max bug**, which the new checks found in the six-max runs (1 of 2038
  instructions on fish247, 500 big blinds deep):
  - B0 said BET 1.5 into a pot of 4 chips (two big blinds) on the turn, under the minimum
    bet of 2.
  - The simulator plays the minimum instead, so no result changes.
  - It isn't fixed here, because six-max play must not change. It's a plain bug fix for
    later, with a regression test. (Fixed on 27 Nov 2026: "B0 fix: no bet under the
    minimum", below.)

### The gate, heads-up

Rule (`runs/phase1_heads_up_gate.sh`, committed in 68791d6 before any heads-up hand on its
seeds was played):

- Gate run 5's rule, heads-up: the same 8 comparisons, 3000 hands each.
- The new way: the defaults (each deal twice with the seats swapped; 6 replays from where the
  variants part, with the bot redealt; luck taken out only where nobody can bet again), on
  seeds 1111 and 1212.
- The old way: classic, raw difference, pooled over seeds 1111 to 1414.
- r: the new way's sd per hand over the old way's (decks as units), as in runs 4 and 5.
- Judged: the comparisons in which at least 1% of the new way's hands differ.
- Pass: geometric mean of r at most 0.5, none above 0.75, CPU per hand at most 1.25 times
  classic.

Result (`runs/phase1_heads_up_gate/summary.md`). Hands: 6000 new way, 12000 old way.

| Comparison | Hands that differ, new | New way (bb/100) | Old way (bb/100) | r | CPU, new / old |
|---|---|---|---|---|---|
| `push_chart`, tourney | 2.52% | +1.2 ± 0.2 | +1.5 ± 0.6 | 0.258 | 1.16 |
| `bet_size: 0.5` | 4.42% | -1.3 ± 0.6 | -0.0 ± 1.3 | 0.323 | 1.39 |
| `texture_sizing` | 4.43% | -0.6 ± 0.5 | -0.7 ± 1.1 | 0.327 | 1.40 |
| `ev_sizing`, fish247 | 8.27% | +2.3 ± 1.0 | +3.5 ± 1.6 | 0.439 | 1.71 |
| `ev_sizing`, mixed | 5.57% | +3.7 ± 1.3 | +3.8 ± 1.8 | 0.497 | 1.80 |
| `semibluff_turn: "never"` | 1.57% | -3.2 ± 0.9 | -3.3 ± 1.3 | 0.529 | 1.12 |
| Not judged (under 1%): `stab: 0.0` | 0.42% | -1.2 ± 0.4 | -1.7 ± 1.0 | 0.295 | 1.11 |
| Not judged: `commit: 1.0` | 0.03% | no result differs | | | 1.03 |

Geometric mean of r over the six judged: **0.38** (passes, at most 0.5). Largest judged r:
**0.53**, `semibluff_turn: "never"` (passes, at most 0.75). CPU per hand: **1.41** times
classic (fails, at most 1.25). **The heads-up run fails**, on the CPU condition only.

- The SE is more than halved on average heads-up too: 0.38, against 0.46 in six-max run 5,
  and every judged comparison is at 0.53 or below (run 5: up to 0.75). Read strictly (every
  comparison at most 0.5), one is over: `semibluff_turn: "never"` at 0.53.
- The extra CPU is the replays. Heads-up more hands differ (4% to 8% for the sizing
  comparisons, about 4% in six-max), and each is played 10 more times. It is highest for
  `ev_sizing` (1.7 and 1.8), whose decisions are the slowest.
- Per CPU second instead of per hand, r becomes r x the square root of the CPU ratio:
  geometric mean 0.45, largest 0.67 (`ev_sizing`, mixed). That was worked out after the
  result, so it tests nothing.
- The seat swap alone does nothing for these comparisons: the raw duplicate difference's sd
  is 0.68 to 1.27 of classic's. The gain is the replays'. Pairing the variants already
  cancels the cards they share.
- The brief's gate is "at equal hands", which this passes on average; the CPU bar came with
  run 5's rule. As with run 5, whether that is good enough is Kevin's call. Nothing in the
  method was changed for heads-up.

**Decision (27 Nov 2026, the manager session under Kevin's delegation): good enough. Phase 1
is done.**

- Kevin left the call to the manager session ("if u think its passed then sure").
- The gate is not passed as written: the CPU condition fails (1.41 against 1.25).
- Both SE conditions pass: geometric mean of r 0.38 (bar 0.5), largest judged r 0.53 (bar
  0.75). B0 plays heads-up with no always-wrong instruction.
- The CPU cost is paid back: per CPU second the SE is 0.45 of the old way's (geometric mean),
  so a comparison still needs far less computer time than classic. That figure was worked
  out after the result, so it is a reason for the call, not a pass.
- The new way stays the default for comparisons, heads-up too.
- Phase 6's "beats B0 heads-up by 2.5 SE" will be measured in the Rust arena, not with
  `tools/compare.py`, so this gate's CPU cost doesn't slow Phase 6.

### Not done

- Head-to-head play: two variants against each other heads-up, each deal played twice with
  the seats swapped. Phase 6's "beats B0 heads-up" needs it once there is a second agent.
  (Built since, in the Rust arena, B0 included: "Phase 6 groundwork" below.)
- Heads-up styles for the bots (above).
- The weakness report (`tools/weakness.py`) and the luck weights' fit (`tools/luck.py fit`)
  are six-max only. The comparisons don't use the weights: they only correct board cards
  after which nobody can bet again, where the weights have no effect.

## B0 fix: no bet under the minimum (27 Nov 2026)

The bug the heads-up work found (above): in six-max B0 said BET 1.5 into a pot of 4 chips
(two big blinds), under the minimum bet of one big blind (2). A plain bug fix, so regression
tests and no simulation (CLAUDE.md). `TUNING` and `baseline_tuning.json` are unchanged.

### The cause

- The `stab` rule bets a third of the pot: heads-up after the flop, checked to B0 last on a
  dry board, from a 40% chance of winning. In a pot of 4 or 5 chips a third rounds to 1.5,
  under the big blind of 2.
- `_aggressive` turns a size into BET x, RAISE TO x or ALL IN. It capped a size at the stack,
  but it never raised one to the minimum.

### Every bet and raise in `app/poker`

Every sized bet and raise goes through `_aggressive` in `app/poker/advice.py`. The rest are
all-ins.

- Before the flop: the open (2.5 big blinds, 3 from the small blind), the raise over limpers
  (3 big blinds plus one per limper, 3.5 plus one from the big blind), re-raises (3 or 4 times
  the raise plus one per caller, 2.3 times cold), raising a re-raise (2.2 or 2.5 times), and
  `eff_push` and `bully` (off). All are at least twice the bet they answer, so at or over the
  minimum.
- After the flop: raising a bet for value (3 times their bet, or from 2.5 times with
  `ev_sizing`), value bets (2/3 of the pot, or `texture_sizing`, `geometric`, `ev_sizing`,
  `bucket_sizing`), `small_bet_from` (a third), `river_ip_call_share` (half), semi-bluffs
  (half) and `stab` (a third). The bets are shares of the pot, and the smallest pot after the
  flop is two big blinds: half of it or more is at least the big blind, a third isn't. Of the
  options on by default, only `stab` bets a third.
- The river solver's bets and raises (`river_solver`, off). Its tree (`app/solver/tree.py`)
  has no floor of one big blind for a bet, so in a tiny pot it could also say a bet under the
  minimum.
- A size from a big blind guessed from the pot, when the blinds weren't read ("RAISE TO
  ABOUT 5").
- All-ins: `_shove` and CALL ALL IN, the whole stack, which is always allowed.

### The fix

One last check on every instruction, after `_never_fold_a_free_check` (`_legal_size`):

- A bet or raise under the minimum goes up to it, and the small print says "That's the
  smallest bet allowed."
- The minimum (`_min_to`): the biggest bet plus the last raise (its gap down to the next bet
  on the table), and at least one big blind more. A first bet is at least one big blind. With
  nothing to call, a bigger bet on screen is taken for a misread.
- Never more than your chips. When the minimum is most of your chips the instruction is ALL
  IN, as for any size (`ALL_IN_SHARE`). When it is more than you have, it's all in for less,
  which is allowed.
- A guessed size ("ABOUT") is capped at the stack but never turned into ALL IN. The random
  spots in `test_advice_fuzz.py` found one, RAISE TO ABOUT 333 with 200 chips (a big blind of
  133 guessed from the pot), that the cap would otherwise have made a weak all-in. Before the
  fix it said the 333.
- Known limit: the minimum is worked out from the bets on the table, so after an all-in that
  wasn't a full raise it can come out a little low. The rules' raises are at least twice the
  bet there, far above it.

Tests: `app/tests/test_legal_sizes.py`. They cover the exact spot (hand 665 of the six-max
fish247 run, 500 big blinds deep, seed 43, rebuilt as the simulator holds it), small pots,
short stacks, raises and the minimum itself.

### Check runs

`simulate.check_advice` on the main tables, on the commit before the fix and on the fix,
compared hand by hand (`runs/b0_min_bet.py`, `runs/b0_min_bet/summary.md`).

| Setting | Hands | Instructions | Under the minimum, before | After | Other always-wrong, after |
|---|---|---|---|---|---|
| Six-max: the 11 tables at 100 and 500 big blinds, tournament and uneven stacks, seed 43 | 52000 | 73338 | 14 | 0 | none |
| Heads-up: the 17 settings of `phase1_heads_up_b0.sh` | 33000 | 37629 | 0 | 0 | none |

- Before: the 14 were all one spot. B0 was in the big blind, the small blind completed, it was
  checked to B0 on the flop or turn, and B0 said BET 1.5 into 4 chips. That's about 1 in 5200
  six-max instructions, on 7 of the 11 tables. There were none heads-up: there the big blind
  acts first after the flop, and B0 never just calls from the button.
- After: none, and no other always-wrong instruction.
- Exactly those 14 instructions changed (BET 1.5 to BET 2), and no hand's result changed: the
  simulator already played the minimum. So the six-max values pinned in
  `test_six_max_unchanged_by_the_heads_up_mode` are unchanged too.

## Phase 6 groundwork: B0 against Rust agents (27 Nov 2026)

Phase 6's gate needs the heads-up blueprint to beat B0 by 2.5 SE heads-up. Until now nothing let
B0 play a Rust agent: B0 is Python (`app/poker`) and the arena (`engine/crates/arena`) seats Rust
agents only. This builds that and measures what such a test costs. Usage:
`engine/crates/py/README.md`, "Matches in the arena" and "B0 against a Rust agent".

### What was built

- **`pokerscribe_engine.run_match`** (`engine/crates/py`): a match in the Rust arena, from Python.
  The arena still runs everything: each deal twice with the seats swapped, all-in hands scored by
  their equity, bb/100 with the SE per deal. Its public API is unchanged. Each seat is one of:
  - a Rust agent by name: the arena's 8 bots and 5 of the LBR crate's simple strategies
    (`pokerscribe_engine.agents()`);
  - any Python object with `act(view)`. The arena calls it on its turn and holds Python's lock
    only for that call. The view has the agent's own cards, what is public and the betting so
    far, and nothing else (the other cards in the view's state are made up).

  A Rust `Player` or `Strategy` becomes a name with one line in `src/agents.rs`. That is the hook
  the blueprint will use. Checked through it: `lbr-call`, `lbr-fold` and `lbr-jam` (the LBR
  crate's strategies) play exactly the matches `call`, `fold` and `jam` play.
- **`tools/b0_arena.py`**: B0 as a Python agent.
  - What B0 sees: the arena's view becomes the simulator's own `Hand`. B0 is then asked through
    `simulate.app_state` and `simulate.decision`, so it gets the spot the simulator gives it: the
    stacks, the blinds (1/2 in the simulator's chips), the seats named "BTN/SB" and "BB", and the
    betting so far. Checked on 400 random hands, each played in the engine and then in the
    simulator: the same `GameState` at every one of B0's decisions, to the last bit, and the
    same result.
  - What it plays: the simulator's move for the instruction (`simulate.app_move`, then
    `simulate.act`). An instruction that is not legal as said is played as the simulator plays
    it, counted by kind, and written to a log with the spot (one JSON line each).
- **Why this design.** The arena drives and B0 is one more agent. Two other designs were
  possible:
  - Python could drive the match through the nlhe bindings, but then the duplicate deals, the
    all-in equity and the SE would exist twice.
  - B0 could be rewritten in Rust, but it is frozen, and a rewrite would have to be proved equal
    to it.

  This way the scoring exists once, in Rust, and a Rust agent plays at Rust speed. Only B0 is
  Python.

### Results

`runs/phase6_b0_arena.py` (`phase6_b0_arena/summary.md`): heads-up, 100 big blinds, blinds
50/100, duplicate and all-in equity unless the row says plain. Seeds 601 to 610.

| B0 against | Hands | B0, bb/100 | SE without the pairing | sd per deal | Hands/s |
|---|---|---|---|---|---|
| B0 | 800 | exactly 0 | 39.7 | 0 | 12.4 |
| B0, plain (each deal once) | 1000 | -42.1 ± 32.5 | | 1027 | 7.1 |
| B0 with `bet_size: 0.5` | 3000 | +2.9 ± 3.9 | 14.1 | 150 | 13.1 |
| fold | 2000 | +34.7 ± 1.2 | 1.2 | 37 | 91 |
| call | 2000 | +239.5 ± 19.2 | 22.0 | 606 | 4.6 |
| tag | 6000 | +8.2 ± 5.6 | 7.7 | 308 | 32 |
| tag-loose | 6000 | +2.5 ± 7.4 | 8.6 | 403 | 22 |
| jam | 2000 | +8.1 ± 20.1 | 32.5 | 635 | 33 |
| lbr-random | 2000 | +157.7 ± 34.3 | 38.1 | 1083 | 16 |
| lbr-call-or-raise | 2000 | +362.6 ± 53.1 | 65.1 | 1678 | 10 |

- **B0 against B0 is exactly 0** in duplicate play, with an SE of 0. B0 is deterministic (its
  equity runs are seeded from what it sees), so each deal's two hands cancel. Without the
  pairing, -42 ± 32 over 1000 hands, 1.3 SE from 0.
- **B0 beats always-fold by 29 SE and always-call by 12.5 SE.** It also beats both LBR test
  strategies by more than 4.5 SE.
- **The arena's tag bots are near B0's strength heads-up**: +8.2 ± 5.6 and +2.5 ± 7.4, neither
  2 SE from 0.
- **The same seed gives the same match.** The two LBR matches, played a second time, gave the
  same report, B0's counts included.
- **B0 is unchanged**: nothing in `app/poker` was touched, `TUNING` is the same after a match,
  and the baseline test passes.
- **The pairing helps less here than in the simulator's comparisons.** The SE over the SE without
  the pairing is 0.73 against tag, 0.85 against tag-loose and 0.62 against jam, but 0.28
  against B0's own variant. Two different agents play a deal's two hands differently, so the
  cards cancel less. Most of the gain in `tools/compare.py` comes from replaying the hands two
  variants play differently, from the point where they part, against the same bots. A match
  between two agents has no such point, so only the seat swap is left.

### Instructions that can't be played as said

- **None** in 41145 instructions over 26800 hands. Every instruction B0 gave was legal as said.
- **The simulator's always-wrong checks** (`simulate.check_advice`) fired 9 times, all on the
  same spot.
  - The spot: B0 raised (to 2.5 big blinds on the button, or to 4.5 in the big blind after a
    limp), the LBR random strategy re-raised to 26 to 87 big blinds, and B0 went all in with AKo.
  - Why the check fires: it counts any all-in 40 big blinds deep or more before the flop, with a
    hand outside the top 5%, and AKo is just outside.
  - Why it is a false alarm: the check doesn't look at what B0 is facing. Against a re-raise of
    a quarter of the stack or more, all in with AKo is a normal play.

  No other opponent here led to it, and Phase 1's 37629 heads-up instructions against the
  simulator's bots had none. The check is not changed here.
- **One thing about B0**, from the jam match: B0 calls a 100 big blind jam only with JJ or better
  (12 calls in 430 jams, seed 610, 300 deals; `runs/phase6_b0_jam_calls.py`). Against a bot that jams every hand, the best
  answer calls with any hand that has about half the equity against a random hand, roughly half
  of all hands. That is why B0 is only +8 against jam, and a blueprint will find it. B0 is
  frozen, so it stays.

### Speed

All of the time is B0's. The arena, the Rust agent and the crossings between Rust and Python take
0.0% to 0.2% of each match.

- B0 costs 22 ms to 70 ms per instruction: 22 ms before the flop (against fold, where it acts
  only there), 37 ms against tag, 70 ms against call, where every hand goes to the river.
- So hands per second depend on how many instructions a hand needs, from 91 against fold to 4.6
  against call. Against a near-equal opponent (tag, tag-loose) it is 22 to 32 hands per second
  on one process.
- A profile of 300 hands against tag:
  - 94% of B0's time is its Monte Carlo equity: 88% in the equity the simulator gives the advice
    (`simulate.sim_compute`, 400 samples per estimate) and the rest in the advice's own equity
    runs;
  - building the spot, the checks and turning the instruction into an action take under 0.5%.
- A match with a Python agent plays on one thread, since the agent holds Python's lock. The
  measurement ran four matches at once, one process each.

### Hands for a 2.5 SE test

With one sample per deal, an edge of D bb/100 is 2.5 SE after (2.5 sd / D)^2 deals, twice that in
hands:

| Opponent (sd per deal) | Edge 5 bb/100 | Edge 10 bb/100 | Edge 20 bb/100 |
|---|---|---|---|
| B0 with `bet_size: 0.5` (150) | 11,324 | 2,832 | 708 |
| tag (308) | 47,414 | 11,854 | 2,964 |
| tag-loose (403) | 81,230 | 20,308 | 5,078 |
| jam (635) | 201,600 | 50,400 | 12,600 |
| lbr-random (1083) | 586,766 | 146,692 | 36,674 |

- **A near-equal opponent of a different kind (tag, tag-loose)**: an sd of 300 to 400 per deal.
  An edge of 5 bb/100 then takes 47,000 to 81,000 hands, about 25 to 60 minutes on one process.
  An edge of 10 bb/100 takes 12,000 to 20,000 hands, about 6 to 15 minutes. The blueprint
  against B0 is the same kind of test: two different agents, not two variants of one.
- **A variant of B0** has an sd of only 150, because a deal's two hands mostly cancel. It is not
  a guide for the blueprint.
- **The sd depends on the opponent**: it grows with the size of the pots, so an agent that
  re-raises and jams a lot (lbr-random) needs ten times the hands. The first run against the
  blueprint should measure it, and the test should be sized from that.
- **CLAUDE.md's promotion rule** also asks for a repeat on fresh seeds, which doubles the hands.

### Not done

- A match with a Python agent uses one process. Splitting one test over processes (separate
  seeds, pooled per deal) is not built; `runs/phase6_b0_arena.py` runs separate matches in
  parallel instead.
- The always-wrong check for jams doesn't look at the bet faced (above). It is shared with the
  simulator runs, so it is left as it is.
- Heads-up styles for the arena's bots, and the redeal replays for matches between different
  agents.

## Phase 5: the gate (27 Nov 2026)

The Phase 5 gate (`README.md`, roadmap): "LBR win rate falls as buckets and sizes are added, then
flattens". It is also the first real poker training, so its speed and memory feed Phase 6's cost
estimate. Everything here ran on this machine: 4 cores (Intel Xeon at 2.1 GHz), 16 GB.

In short:

- **The gate fails: 3 of its 7 conditions hold**, the same on a fresh set of deals. More bet
  sizes lower LBR's win rate by 14 to 18 bb/100 at every bucket count. More buckets don't: from
  10 to 50 a street LBR rises on both menus, and from 50 to 200 it is flat. Training the runs
  longer doesn't change that.
- At 20 big blinds most of what LBR wins comes from bets the menu doesn't have (about 18% of the
  blueprint's decisions fall off the tree), which more sizes fix and more buckets can't. Why
  buckets don't help even where LBR stays on the menu isn't tested; the cheapest next step is the
  bucket half at 100 big blinds.
- **OCHS against equity on the river**: neither wins on both menus, so Phase 6 keeps OCHS, as
  pre-registered. Equity was better on the standard menu on both deal sets, so it is worth
  checking again with deeper stacks.
- **Small bets**: Phase 6 keeps reading them as the smallest menu size.
- **Speed**: 15,000 iterations a second on 1 thread at 20bb (standard-k200), 3.73 times that on
  4. In the Phase 6 game, 2.6 to 2.8 million game states a second per thread, as fast on 4
  threads as on 1.
- **Memory**: 60 to 65 bytes an information set at 20bb. The Phase 6 game (97.2M information
  sets) needs a 5.2 to 7.3 GB table and 6.4 to 7.4 GB in all, so a 128 GB machine is plenty.
- **Phase 6 projection** (heads-up, 200bb, a rich preflop, 200 buckets, 64 threads on a
  c4a-highmem-64): 2.5 to 14 hours at the central speed ($5 to $28 spot), 0.5 to 47 hours across
  all the ranges. The uncertainty is a factor of about 100, mostly in how much training a 200bb
  game needs.
- **B0 against the blueprint** at 20bb: the path works (no illegal instruction in 4,111). The
  blueprint won +24.9 ± 6.8 bb/100, which is not evidence of anything.

### What was built

- **`engine/crates/blueprint`** (its README has the use and the file format):
  - the adapter from `abstraction`'s bucket tables to `abstract_game`'s `Bucketer`, as that
    crate's README describes it, with the tables identified by their checksums;
  - training with `cfr`'s external-sampling MCCFR: lock-free threads, 32-bit integer regrets,
    Pluribus's regret floor, linear weighting, optional negative-regret pruning, checkpoints every
    few minutes and on SIGTERM, resumable on the same machine or another, one log line per session;
  - a strategy file of 2 bytes a probability with a JSON header and a checksum, refused when it
    doesn't fit the game or the tables;
  - `Blueprint`, which plays the file as `lbr`'s `Strategy`: real bets that are not on the menu
    are read with `abstract_game`'s pseudo-harmonic mapping (a draw from a hash of the betting,
    so the same spot is always read the same way);
  - LBR matches that keep each deal's result, so two strategies measured on the same deals have
    a paired standard error;
  - the gate procedure (`src/gate.rs`) and the `blueprint` command, including the `tools/cloud`
    trainer contract (`--config`, `--checkpoint-dir`, `--resume`, 75 on SIGTERM).
- **The arena hook**: the agent `blueprint:<strategy file>` in `engine/crates/py`, so
  `tools/b0_arena.py` plays a blueprint against B0.
- No change to `cfr`, `abstract_game`, `abstraction` or `lbr`.

### Bucket tables

`abstraction-build build --out ~/abstraction/k<B> --buckets <B>` on 4 cores, 138 MB each:

| Tables | Buckets (flop, turn, river) | River feature | Build time | Sanity checks |
| --- | --- | --- | ---: | --- |
| k10 | 10, 10, 10 | OCHS (8 clusters) | 58 s | 13 of 19 pass (the checks are written for 50 or more buckets) |
| k50 | 50, 50, 50 | OCHS | 169 s | 19 of 19 |
| k200 | 200, 200, 200 | OCHS | 499 s | 19 of 19 |
| k50eq | 50, 50, 50 | equity (`--river-feature equity`) | 80 s | 19 of 19 |

### The design, and the pilots it came from

Pre-registered in `runs/phase5_gate/README.md` before the gate started, and run unchanged from
`runs/phase5_gate/plan.json`.

- **Heads-up at 20 big blinds** (blinds 50/100, 2,000 chips each). The standard menu with 200
  buckets has 1.1M information sets there, which trains to a flat LBR in about an hour on 4
  cores. After an open and a call the stack is still 3.5 pots, so bet sizes after the flop
  matter. At 100 big blinds the same game is many times larger (`blueprint size`).
- **Two menus** (`abstract_game::Menus`): small (preflop opens of 2.5 times and all in, 3-bets of
  3 times and all in; after the flop a half or a whole pot or all in, then a pot raise or all in)
  and standard (three opens, two 3-bets, two 4-bets; after the flop a third, three quarters or
  one and a half pots or all in, then three quarters or all in). **Three bucket counts** (10, 50
  and 200 a street, OCHS on the river) and 50 with equity on the river: 8 runs.
- **Training**: external-sampling MCCFR on 4 threads, seed 1, integer regrets (100 a big
  blind), Pluribus's floor, linear weighting every 200,000 iterations up to 20M, no pruning.
- **Stages** at 4M iterations, then doubling, up to 1,024M. After each: LBR `b56_14` (56 bets,
  rounds 1 to 4) and `fcpa34`, 50,000 hands, seed 777, the same deals at every stage.
- **Stop rule, two-sided**, after the first doubling that meets both:
  1. LBR flat: `b56_14` moved, either way, by less than max(3% of its level, 2 paired SE);
  2. play settled: the average strategy changed by at most 8% over the doubling (the share of
     play that changed, each information set weighted by how often it is reached,
     `StrategyFile::change_from`).
- **Final measurement** at the last stage: `b56_14`, `b56_34`, `fcpa14`, `fcpa34` and `fc34`,
  100,000 hands, seed 778, the same deals for every run, so every difference between runs is
  paired deal by deal. Then the same five with bets below the menu's smallest size read as a
  check or call. `fc14` was left out: 30 times slower than the others and weak in the pilot.
- **M**, a run's figure for the gate, is the largest of the five (the paper's rule).

The pilots, both on small-k50 at 20 big blinds:

- **Pilot 1** (2M iterations, linear weighting, 20,000 hands each, seed 777): `b56_14` 111.5 ±
  4.2, `b56_34` 75.6 ± 5.3, `fcpa14` 7.7 ± 4.6, `fc14` -4.6 ± 3.3, `fc34` -46.1 ± 4.8 bb/100.
  The 56-bet settings are far the strongest at this depth, so `b56_14` is the stage measure.
  `fc14` ran at 80 hands a second, against 1,644 to 8,682 for the others.
- **Pilot 2** (with and without linear weighting, stages from 2M, no stop rule;
  `runs/phase5_gate/pilot2/`):

  | Iterations | 2M | 4M | 8M | 16M | 32M | 64M |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: |
  | Linear, `b56_14` | 122.4 | 130.0 | 131.1 | 131.6 | 131.1 | 132.3 |
  | Linear, `fcpa34` | 3.6 | 3.8 | 5.8 | 10.1 | 8.4 | 13.2 |
  | Linear, change over the doubling | | 0.099 | 0.085 | 0.077 | 0.065 | 0.050 |
  | Plain, `b56_14` | 115.3 | 121.0 | 126.6 | 128.6 | | |
  | Plain, `fcpa34` | -4.4 | -4.5 | 1.2 | 10.7 | | |
  | Plain, change over the doubling | | 0.072 | 0.061 | 0.054 | | |

  Each LBR figure has an SE of 2.6 to 2.7 (`b56_14`) or 3.4 (`fcpa34`), 50,000 hands, seed
  777. The 64M linear strategy gave `b56_34` 93.0 ± 3.2.

  What it showed:
  - **LBR rises as the strategy converges.** The equilibrium of this coarse game is more
    exploitable in the real game than the strategies on the way to it, as Johanson et al.
    (2011) found for abstract CFR strategies in limit hold'em. So a lower LBR at equal
    iterations can mean "less converged", and the stop rule checks movement both ways.
  - **Linear weighting gets there sooner**: its `b56_14` was flat from 4M, the plain run's still
    rising at 16M. The plain run's smaller change per doubling is not faster convergence: its
    average moves more slowly because early iterations weigh as much as late ones.
  - **0.08 is met at 16M** on small-k50 with linear weighting, where LBR is flat too, so the two
    criteria agree there.

### Training

All eight runs stopped by the rule, none at the cap (`runs/phase5_gate/gate/`, `results.md`):

| Run | Information sets | Stopped at | Change over the last doubling | Train time | Iterations/s, 4 threads | `b56_14` by stage (seed 777) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| small-k10 | 14,828 | 8M | 0.063 | 0.8 min | 160,289 | 120.8, 122.6 |
| small-k50 | 66,028 | 16M | 0.074 | 1.8 min | 145,148 | 126.0, 127.3, 129.1 |
| small-k50eq | 66,028 | 32M | 0.074 | 3.7 min | 143,303 | 117.0, 121.8, 128.4, 129.7 |
| small-k200 | 258,028 | 64M | 0.063 | 8.7 min | 122,991 | 119.8, 126.7, 128.7, 131.0, 131.6 |
| standard-k10 | 64,580 | 32M | 0.068 | 7.0 min | 76,890 | 97.4, 106.0, 112.7, 116.0 |
| standard-k50 | 282,340 | 64M | 0.063 | 16.6 min | 64,522 | 104.8, 111.4, 114.9, 113.1, 114.5 |
| standard-k50eq | 282,340 | 64M | 0.068 | 16.0 min | 66,951 | 103.0, 107.6, 110.1, 111.3, 112.1 |
| standard-k200 | 1,098,940 | 64M | 0.077 | 20.1 min | 53,464 | 103.0, 107.0, 112.9, 117.0, 117.0 |

The stages are 4M, 8M, 16M and so on; each LBR figure has an SE of 2.5 to 2.7. Every run's LBR
rose while it trained and then flattened, as in the pilot. Where the two criteria disagreed it
was the change measure that held runs back (standard-k50 and standard-k50eq had a flat LBR at
32M but still changed 8.2% and 9.0%), so the runs stopped at about the same distance from their
own limits, not at equal time: the larger games got 4 to 8 times the iterations of the smallest.

### Final LBR

100,000 hands, seed 778, the same deals for every run; bb/100 won by LBR; the off-tree share is
the share of the blueprint's decisions, under `b56_14`, where the abstract game could not follow
the hand and the blueprint checked or called:

| Run | 56 bets, 1-4 | 56 bets, 3-4 | fcpa, 1-4 | fcpa, 3-4 | fc, 3-4 | M | Off the tree |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| small-k10 | 120.4 ± 1.8 | 77.8 ± 2.3 | 8.9 ± 2.0 | -0.7 ± 2.4 | -46.7 ± 2.1 | 120.4 ± 1.8 | 17.8% |
| small-k50 | 125.3 ± 1.8 | 84.5 ± 2.3 | 8.7 ± 2.0 | 2.7 ± 2.4 | -39.8 ± 2.1 | 125.3 ± 1.8 | 17.6% |
| small-k50eq | 127.9 ± 1.8 | 84.4 ± 2.3 | 11.6 ± 2.0 | 4.9 ± 2.4 | -36.3 ± 2.0 | 127.9 ± 1.8 | 18.7% |
| small-k200 | 128.9 ± 1.9 | 85.6 ± 2.3 | 11.5 ± 2.0 | 4.2 ± 2.4 | -40.6 ± 2.0 | 128.9 ± 1.9 | 17.9% |
| standard-k10 | 105.1 ± 1.8 | 64.7 ± 2.3 | 5.2 ± 2.0 | 7.3 ± 2.4 | -40.1 ± 2.1 | 105.1 ± 1.8 | 18.1% |
| standard-k50 | 111.7 ± 1.9 | 67.3 ± 2.3 | 4.6 ± 2.0 | 13.4 ± 2.4 | -36.6 ± 2.1 | 111.7 ± 1.9 | 18.9% |
| standard-k50eq | 107.3 ± 1.8 | 66.2 ± 2.3 | 3.2 ± 1.9 | 16.4 ± 2.4 | -29.8 ± 2.1 | 107.3 ± 1.8 | 19.1% |
| standard-k200 | 112.3 ± 1.9 | 66.4 ± 2.3 | 3.5 ± 2.0 | 13.8 ± 2.4 | -35.8 ± 2.0 | 112.3 ± 1.9 | 18.8% |

References on the same deals (`blueprint reference`, `runs/phase5_gate/after/references.jsonl`):

| Strategy | 56 bets, 1-4 | 56 bets, 3-4 | fcpa, 1-4 | fcpa, 3-4 | fc, 3-4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Always call | 320.8 ± 2.1 | 465.0 ± 2.2 | 320.8 ± 2.1 | 465.0 ± 2.2 | 0.0 ± 0.0 |
| Random action | 465.4 ± 3.8 | 767.3 ± 4.1 | 402.7 ± 3.7 | 763.3 ± 4.1 | 10.2 ± 0.8 |
| Random kind of action | 353.3 ± 3.5 | 555.4 ± 3.8 | 266.4 ± 3.4 | 502.4 ± 3.8 | 60.8 ± 2.6 |

Under `b56_14` LBR wins 33% to 40% as much from a blueprint as from always calling (105 to 129
against 321), and under `b56_34` 14% to 18% as much. Against always call `fc34` wins nothing by
construction: neither ever bets, so every hand goes to a showdown.

### The gate: fails (3 of 7 conditions)

Paired differences of M on the same deals (the second run minus the first; negative is better):

| Condition | Difference | In SE | Holds |
| --- | ---: | ---: | --- |
| Sizes help, 10 buckets: standard - small | -15.3 ± 1.6 | -9.5 | yes |
| Sizes help, 50 buckets | -13.6 ± 1.6 | -8.5 | yes |
| Sizes help, 200 buckets | -16.6 ± 1.6 | -10.5 | yes |
| Buckets help, small menu: k50 - k10 | +4.9 ± 1.5 | +3.2 | no |
| Then flattens, small menu: k200 - k50 | +3.6 ± 1.4 | +2.5 | no |
| Buckets help, standard menu: k50 - k10 | +6.6 ± 1.4 | +4.6 | no |
| Then flattens, standard menu: k200 - k50 | +0.6 ± 1.4 | +0.4 | no (flat, but nothing fell before it) |

- **Bet sizes help, by a lot.** The standard menu is 13.6 to 16.6 bb/100 less exploitable at
  every bucket count, 8.5 to 10.5 SE.
- **Buckets do not.** From 10 to 50 buckets LBR rises on both menus. From 50 to 200 it rises
  again on the small menu and is flat on the standard one. The same holds setting by setting
  (`results.md`, paired differences): no LBR setting falls by 2 SE when buckets are added, and
  most rise. On fresh deals the verdict is the same (the checks below).

### Checks after the gate (not pre-registered)

Three checks added once the gate's results were in (`runs/phase5_gate/after/`; `checks.py`,
output in `checks.md`):

1. **Fresh deals.** Every run's final strategy again with `b56_14` (M on seed 778 for every
   run), on a third deal set: seed 779, 100,000 hands. The gate's comparisons, paired on each
   seed's deals:

   | Comparison | Seed 778 (the gate) | Seed 779 | Both, 200,000 hands |
   | --- | ---: | ---: | ---: |
   | Sizes, 10 buckets: standard - small | -15.3 ± 1.6 | -13.3 ± 1.6 | -14.3 ± 1.1 |
   | Sizes, 50 buckets | -13.6 ± 1.6 | -15.6 ± 1.6 | -14.6 ± 1.1 |
   | Sizes, 200 buckets | -16.6 ± 1.6 | -18.6 ± 1.6 | -17.6 ± 1.1 |
   | Buckets, small menu: k50 - k10 | +4.9 ± 1.5 | +5.0 ± 1.5 | +4.9 ± 1.1 |
   | Buckets, small menu: k200 - k50 | +3.6 ± 1.4 | +1.1 ± 1.4 | +2.3 ± 1.0 |
   | Buckets, standard menu: k50 - k10 | +6.6 ± 1.4 | +2.6 ± 1.5 | +4.6 ± 1.0 |
   | Buckets, standard menu: k200 - k50 | +0.6 ± 1.4 | -1.9 ± 1.4 | -0.6 ± 1.0 |
   | Equity - OCHS, small menu | +2.6 ± 1.5 | -2.2 ± 1.5 | +0.2 ± 1.1 |
   | Equity - OCHS, standard menu | -4.4 ± 1.5 | -5.9 ± 1.5 | -5.2 ± 1.0 |

   - The gate's verdict is the same on seed 779 alone and on both deal sets together: the
     three sizes conditions hold, the four buckets conditions don't.
   - Every run scored 1 to 8 bb/100 more on seed 779: luck of the deals that all runs share,
     which the paired differences cancel.
   - The gaps between the two seeds are within 1.3 SE for 7 of these 9 comparisons, and 2.0 and
     2.3 SE for the other two.
   - One measurement stands out: standard-k10 on seed 778, 105.1, against 116.0 ± 2.6 on seed
     777 (its last stage, 50,000 hands) and 112.9 ± 1.8 on seed 779. Measured again it is the
     same deal by deal (check 2), so it is the luck of those deals for that strategy, about 3
     SE. It makes the standard menu's rise from 10 to 50 buckets larger on seed 778 (+6.6) than
     on seed 777 (-1.6 ± 2.1) or seed 779 (+2.6). On none of the three does it fall.
2. **The same measurement twice.** standard-k10 and small-k10 on seed 779 by two separate
   processes, and standard-k10 on seed 778 again after the checks: identical deal by deal each
   time. An LBR measurement depends only on the strategy file, the setting and the seed.
3. **Longer training.** small-k10 trained on from its stop at 8M iterations to 64M (8 times), and
   small-k200 from 64M to 256M (4 times), then measured on the final deals:

   | Run | `b56_14` at the stop | Trained on | Change | `fcpa34` at the stop | Trained on | Change |
   | --- | ---: | ---: | ---: | ---: | ---: | ---: |
   | small-k10, 8M to 64M | 120.4 ± 1.8 | 125.0 ± 1.8 | +4.6 ± 1.3 | -0.7 ± 2.4 | 1.5 ± 2.4 | +2.2 ± 2.0 |
   | small-k200, 64M to 256M | 128.9 ± 1.9 | 131.4 ± 1.9 | +2.5 ± 1.0 | 4.2 ± 2.4 | 6.7 ± 2.4 | +2.5 ± 1.8 |

   Both rose with more training, as every run did before its stop, and small-k200 stays above
   small-k10: +6.4 ± 1.4 under `b56_14` after training on (k10 at 64M, k200 at 256M), against
   +8.5 ± 1.6 at their stops; under `fcpa34`, +5.3 ± 2.4 against +4.9 ± 2.5. Training on took
   6 and 26 minutes.

### Why the buckets half fails, and what it does and doesn't show

- **What LBR wins at 20bb comes mostly from bets the menu doesn't have.**
  - `b56_14` wins 105 to 129 bb/100; `fcpa14`, the same exploiter with only a pot bet and all
    in, wins 3 to 12.
  - With the 56 sizes, 18% of the blueprint's decisions are off the tree (17.6% to 19.1% in every
    run, whatever the menu or buckets). Off the tree it checks or calls whatever it holds: after
    a raise where the menu has none, or after a raise read as the menu's all in when the real
    hand goes on.
  - So M measures the betting abstraction and its translation far more than the card
    abstraction. More sizes help there; more buckets can't.
- **But buckets don't help where LBR stays on the menu either.** On the small menu `fcpa`'s bets
  (a pot and all in) are exactly menu bets (0.0% off the tree), and `fcpa14` and `fcpa34` don't
  fall from 10 to 200 buckets (+2.6 ± 2.2 and +4.9 ± 2.5). No setting falls by 2 SE when buckets
  are added, on either menu.
- **It isn't that the finer runs were stopped early.** They got 4 to 8 times the iterations of the
  coarse ones, and LBR rises as a run converges, so stopping them later would raise their LBR
  further, not lower it. Trained on (check 3 above), small-k10 rose by 4.6 and small-k200 by 2.5,
  and the gap between them stayed (+6.4 ± 1.4).
- **It isn't one lucky set of deals.** On a third deal set (check 1) the verdict is the same, and
  pooled over the two 100,000-hand deal sets, M rises by 4.9 and 4.6 bb/100 from 10 to 50 buckets (4.6 and
  4.5 SE) and moves by +2.3 and -0.6 from 50 to 200.
- **Why, then.** Not tested here; possible reasons:
  1. At 20 big blinds most of the game's value is decided before the flop, where every run uses
     the same exact 169 classes, and after it the stacks are at most 3.5 pots, where coarse
     equity buckets already separate most of what matters.
  2. Finer abstractions are not guaranteed to be less exploitable (Waugh et al. 2009,
     "abstraction pathologies"), and the buckets here are imperfect recall: each street is
     clustered without the earlier ones.
  3. A finer strategy fits the abstract betting more closely, so it may lose more when LBR leaves
     it (the overfitting Johanson et al. 2011 saw as abstract strategies converge).

  Which of these it is would show at deeper stacks: the bucket half at 100 big blinds (standard
  menu, 10, 50 and 200 buckets: 7.2M information sets at 200) takes about 3 to 4 hours here.
- **The references** (always call 320.8, random kind of action 353.3, random action 465.4 under
  `b56_14`): LBR wins 33% to 40% as much from a blueprint as from always calling.
- **The standard menu is not better everywhere**: where LBR only checks and calls until the turn
  (`fcpa34`, `fc34`) it is 3 to 12 bb/100 more exploitable than the small menu (1.9 to 5.0 SE). Its
  M is lower because `b56_14` and `b56_34` gain far more.

### OCHS against equity on the river

At 50 buckets, the second run minus the first, paired on the final deals:

| Menu | `b56_14` (M) | `b56_34` | `fcpa14` | `fcpa34` | `fc34` |
| --- | ---: | ---: | ---: | ---: | ---: |
| small, equity - OCHS | +2.6 ± 1.5 | -0.1 ± 2.1 | +2.9 ± 2.1 | +2.2 ± 2.4 | +3.5 ± 1.9 |
| standard, equity - OCHS | -4.4 ± 1.5 | -1.2 ± 2.2 | -1.4 ± 2.0 | +3.0 ± 2.3 | +6.8 ± 1.8 |

- On M, equity is lower on the standard menu on both deal sets (-4.4 ± 1.5 on seed 778, -5.9 ±
  1.5 on seed 779; -5.2 ± 1.0 together, 5.0 SE) and no different on the small one (+2.6 and
  -2.2; +0.2 ± 1.1 together). The pre-registered rule asks for a win on both menus, so **Phase 6
  keeps OCHS**, the choice in the literature (Johanson et al. 2013). They cost the same to train.
- The evidence is split, not empty. Where LBR's play is about the river (`fc34`: check and call
  to the turn, then fold or call), OCHS is better on both menus, by 1.9 and 3.8 SE (seed 778
  only). M under `b56_14` mostly measures the bet translation (above), which is not what the
  river feature is for.
- Phase 6 uses the standard menu after the flop, so its result there matters more. The cheap
  way to settle it is the same pair with deeper stacks, where more of the pot is played on the
  river.

### Small bets: read as the smallest size (the default) or as a check or call

The check-or-call reading minus the default, paired:

| Run | `b56_14` | `b56_34` |
| --- | ---: | ---: |
| small-k10 | +3.7 ± 0.5 | +28.7 ± 1.0 |
| small-k50 | +4.0 ± 0.5 | +31.5 ± 1.1 |
| small-k50eq | +3.4 ± 0.5 | +32.3 ± 1.0 |
| small-k200 | +4.7 ± 0.5 | +29.4 ± 1.0 |
| standard-k10 | +0.2 ± 0.3 | +14.2 ± 0.8 |
| standard-k50 | -0.3 ± 0.4 | +14.7 ± 0.8 |
| standard-k50eq | -1.7 ± 0.4 | +16.6 ± 0.8 |
| standard-k200 | +0.2 ± 0.3 | +14.3 ± 0.8 |

The other three settings make no bet below the menu's smallest size and are the same deal for
deal under both readings (a check that the option changes nothing else). **Phase 6 keeps the
default**: the check-or-call reading is worse by 14 to 32 bb/100 on the turn and river on every
run, and better by 2 SE only once (standard-k50eq, `b56_14`, -1.7).

### Speed and memory at 20 big blinds

Iterations per second on 4 threads, from the gate's own sessions (averaged over each run):

| Menu | 10 buckets | 50 buckets | 200 buckets |
| --- | ---: | ---: | ---: |
| small | 160,289 | 145,148 | 122,991 |
| standard | 76,890 | 64,522 | 53,464 |

One iteration is one external-sampling traversal for each player. It visits about 190 game
states on the small menu and 360 to 380 on the standard one, so the speed in states is about the
same, 18 to 30 million a second on 4 threads, and falls as the table grows.

Threads, `blueprint bench`, standard-k200 at 20bb with linear weighting, 60 seconds each after
60 seconds of warm-up (`runs/phase5_gate/after/bench.jsonl`):

| Threads | Iterations/s | Per thread | States/s | Speed-up |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 15,027 | 15,027 | 4.29M | 1.00 |
| 2 | 28,042 | 14,021 | 8.61M | 1.87 |
| 3 | 45,055 | 15,018 | 14.86M | 3.00 |
| 4 | 56,058 | 14,014 | 19.04M | 3.73 |

Four threads run at 93% of four times one thread. The earlier benches, before the gate, gave
3.45 on the same game and 3.70 on standard-k50, but 2.92 on small-k10, whose 15,000 information
sets the threads share more often. The whole table here is 67 MB, inside this machine's 260 MB
L3 cache; the Phase 6 table is not (below).

Memory, from each run's last session (cfr's `Mccfr::memory`, every array and the index):

| Run | Information sets | Slots | Bytes per information set | Table | Process, peak | Strategy file | Checkpoint |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| small-k10 | 14,828 | 37,697 | 65.0 | 1.0 MB | 149 MB | 0.08 MB | 0.7 MB |
| small-k50 | 66,028 | 166,177 | 62.6 | 4.1 MB | 162 MB | 0.33 MB | 3.2 MB |
| small-k50eq | 66,028 | 166,177 | 62.6 | 4.1 MB | 165 MB | 0.33 MB | 3.2 MB |
| small-k200 | 258,028 | 647,977 | 62.9 | 16.2 MB | 225 MB | 1.30 MB | 12.7 MB |
| standard-k10 | 64,578 | 166,869 | 64.1 | 4.1 MB | 225 MB | 0.33 MB | 3.2 MB |
| standard-k50 | 282,339 | 714,710 | 60.3 | 17.0 MB | 238 MB | 1.43 MB | 13.9 MB |
| standard-k50eq | 282,340 | 714,713 | 60.3 | 17.0 MB | 242 MB | 1.43 MB | 13.9 MB |
| standard-k200 | 1,098,940 | 2,769,113 | 60.8 | 66.8 MB | 424 MB | 5.54 MB | 54.1 MB |

- **About 60 to 65 bytes an information set**: 12 bytes for each of its 2.5 actions (a 32-bit
  regret and a 64-bit strategy sum) and about 30 bytes of index.
- **The process** holds the bucket tables (about 140 MB whatever the bucket count) and, in the
  gate, LBR's preflop tables, so it peaks at 150 to 420 MB.
- **The strategy file** is 2 bytes a slot. **The checkpoint** is 19 bytes an information set
  plus 12 a slot.

### Pruning

Pluribus's negative-regret pruning (an action whose regret is below the threshold is skipped
with probability 0.95, never on the river) on standard-k200, switched on at 10M iterations.
`blueprint bench`, 300 seconds of warm-up (about 17M iterations), then 120 seconds on 4 threads
(`runs/phase5_gate/after/bench-prune.jsonl`):

| Threshold | Iterations/s | States per iteration | States/s |
| --- | ---: | ---: | ---: |
| none | 50,729 | 377 | 19.1M |
| -10,000 big blinds | 51,907 (+2.3%) | 342 | 17.8M |
| -100,000 big blinds | 51,831 (+2.2%) | 382 | 19.8M |

Pruning hardly pays at this length. Regrets don't fall far enough: in small-k200's checkpoint at 64M
iterations, 14% of the regrets are below -10,000 big blinds, 1.2% below -100,000 and 0.2% below
-300,000, and 11 of 648,000 are at the floor of -3.1 million. Pluribus's threshold is -3 million big
blinds in these units, so at this length it would prune almost nothing. No positive regret is near
the 32-bit limit (the largest is 2,000 to 4,100 big blinds, where the limit is 21 million). Pruning
stays off for the projection below. Whether it pays in Phase 6 depends on how far regrets fall in a
run of that length, so it should be benched there after a few hours of training rather than assumed.

### The Phase 6 game on this machine

The game the brief asks to project: heads-up, 200 big blinds, 200 buckets per postflop street,
a rich preflop (the `rich` menu: the wide menu's preflop with 8 opens, 5 3-bets, 4 4-bets and 2
5-bets, each with all in, then the standard menu after the flop). `blueprint size --stack 200
--menu rich --buckets 200`: 97,158,404 information sets and 251,686,705 regret slots.

It was trained here for 25 minutes on 4 threads, through the `tools/cloud` trainer contract
(SIGTERM, exit 75), then resumed on 1 thread for 5 minutes, to measure its speed and memory
(`runs/phase5_gate/after/rich/log.jsonl`, `projection.md`). It is not a usable strategy.

| Session | Threads | Iterations | Iterations/s | States/s | States per iteration | Information sets met | Table | Resident |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 0.0M to 1.0M | 13,448 | 9.4M | 697 | 55.0M (57%) | 3.93 GB | 5.24 GB |
| 2 | 4 | 1.0M to 2.6M | 14,217 | 11.2M | 789 | 71.7M (74%) | 4.43 GB | 5.74 GB |
| 4 | 4 | 4.3M to 5.8M | 11,699 | 11.4M | 973 | 84.6M (87%) | 4.81 GB | 6.12 GB |
| 6 | 4 | 7.2M to 8.5M | 10,504 | 11.0M | 1,051 | 89.0M (92%) | 4.94 GB | 6.24 GB |
| 8 | 4 | 9.8M to 11.0M | 9,259 | 10.1M | 1,094 | 91.2M (94%) | 5.00 GB | 6.31 GB |
| 10 | 4 | 12.1M to 13.3M | 9,867 | 11.0M | 1,110 | 92.5M (95%) | 5.04 GB | 6.34 GB |
| 12 | 4 | 14.4M to 15.1M | 9,444 | 10.7M | 1,134 | 93.3M (96%) | 5.06 GB | 6.37 GB |
| 13 | 1 | 15.1M to 15.8M | 2,322 | 2.6M | 1,132 | 93.6M (96%) | 7.22 GB | 7.39 GB |

Sessions of about 2 minutes, each ending with a save; all 13 are in `projection.md`.

- **Speed** holds at 10 to 11 million states a second on 4 threads while the table grows from 4
  to 5 GB, far past this machine's 260 MB L3 cache, and 4 threads ran at full speed each: 2.68M
  states a second per thread in the last 4-thread session, 2.63M on 1 thread just after. At 20bb,
  where the table fits in the cache, 4 threads gave 93% of that.
- **States per iteration** rise as the strategy leaves uniform play: 697 at 1M iterations,
  1,008 at 7M, 1,134 at 15M. At 20 big blinds they rose about 12% more from 4M iterations to
  the stop.
- **Memory**: 3.02 GB of slots (12 bytes each) and the index. During the run the index was 2.15 GB
  with 96% of the information sets met, with room for the rest (a shard doubles past three
  quarters full), so a fresh run's table ends at about 5.2 GB. A checkpoint load sizes the index
  at twice the information sets (`cfr`'s `SharedTable::with_capacity`), so after the resume it
  was 4.30 GB and the table 7.22 GB. The whole process was 6.4 GB resident on 4 threads and 7.4
  GB after the resume.
- **Saves** took 5 to 11 seconds every 2 minutes. The checkpoint at 93.3M information sets was
  4.69 GB, exactly 19 bytes an information set and 12 a slot, so 4.87 GB for the whole game.
- **The contract held**: SIGTERM at 15,107,138 iterations, a save, exit 75; the 1-thread
  session resumed at exactly 15,107,138 and stopped the same way.

### Phase 6 projection

`runs/phase5_gate/projection.py`, output in `runs/phase5_gate/projection.md`. The hours come from
two numbers: the work the run needs (game states to visit) and the speed on the rented machine.
Neither is measured for Phase 6 itself, so each is given as a range.

**Work.** How much training the gate's runs needed to reach the gate's level of convergence (the
strategy changes by 8% over a doubling), read off two ways:

1. Iterations against information sets, a power law fitted to the eight runs: iterations ≈
   4.39e4 × (information sets)^0.53. At 97.2M information sets: 7.4e8 iterations (1-sd band
   3.8e8 to 1.4e9). At the Phase 6 game's 1,134 states per iteration (measured, and rising as it
   trains: 1.0 to 1.5 times that), 1.0e12 states (4.3e11 to 2.4e12).
2. States per information set as at 20 big blinds: the runs visited 20,000 to 99,000 states per
   information set (median 57,600) before they reached the bar. For 97.2M information sets that
   is 5.6e12 (2.0e12 to 9.7e12) states.

The two disagree by a factor of 4 to 6. The power law says bigger games need fewer visits per
information set, which held from 15,000 to 1.1M information sets here (iterations grew as the
0.53 power of the information sets), but it is extrapolated 88 times beyond the largest run.
The second model assumes no such saving. Neither knows that a 200 big blind game has longer
hands and deeper betting than a 20 big blind one, so a 20bb run is a shaky guide to the 200bb
one either way.

**Speed on a c4a-highmem-64** (64 Arm cores, Google's Axion, 512 GB), from the 1-thread speed
measured in the Phase 6 game here (2.63M states a second, 96% of the table met), times 64
threads, times three guesses, each (slow, central, fast):

- an Axion core against one of this machine's 2.1 GHz Xeon cores: 0.8, 1.0, 1.5 (not measured;
  no Arm machine here);
- 64 threads against 64 times one thread: 0.5, 0.7, 0.9 (4 threads gave 0.93 at 20bb and 1.02
  in the Phase 6 game here, but 64 threads share one memory system, and the Phase 6 table is
  far outside any cache);
- the whole table met against 96% met here: 0.85, 0.95, 1.0.

That gives 57M (slow), 112M (central) and 227M (fast) states a second.

**Hours**, the work over the speed (low is the low work at the fast speed, high the high work
at the slow speed):

| Work model | States, low / central / high | Hours, low | Hours, central | Hours, high | Spot cost, central |
| --- | --- | ---: | ---: | ---: | ---: |
| Power law in iterations | 4.3e11 / 1.0e12 / 2.4e12 | 0.5 | 2.5 | 11.8 | $5 |
| States per information set as at 20bb | 2.0e12 / 5.6e12 / 9.7e12 | 2.4 | 13.9 | 46.9 | $28 |

Spot cost at $2.05 an hour (c4a-highmem-64, us-central1, `BENCHMARKS.md`, read 26 Nov 2026). The
high end, 47 hours, is $96 spot.

- **Memory is not the constraint.** The table needs 5.2 GB in a fresh run and 7.3 GB after a resume,
  the whole process 6.4 to 7.4 GB (measured), the checkpoint 4.9 GB and the strategy file 0.5 GB.
  The 512 GB of a c4a-highmem-64 is about 60 times what it needs: a c4a-highcpu-64 (the same 64
  cores with 128 GB) runs it with room to spare, at $1.31 an hour spot against $2.05
  (`BENCHMARKS.md`, prices read 26 Nov 2026). Finer buckets fit too: the table grows with the
  buckets (`blueprint size`), and at 1,000 a street (484M information sets, 1.25 billion slots) it
  would be about 27 to 39 GB at the same bytes per slot and per information set.
- **The hours are uncertain by a factor of about 100** (0.5 to 47 hours), most of it from the work,
  not the speed. The way to narrow it is cheap: a few hours on the rented machine, with LBR and the
  change measure at each doubling, gives the real speed on 64 threads and the start of the real
  convergence curve, at a few dollars an hour.
- **What converged means here** is the gate's bar (8% change over a doubling, LBR flat), not
  Phase 6's gate ("LBR falls at every checkpoint; beats B0 heads-up by 2.5 SE"). At 20 big
  blinds LBR rose as the runs converged, so Phase 6's first gate condition may not hold as
  written for a blueprint judged by LBR with off-menu bets.

### B0 against the blueprint (run check)

`tools/b0_arena.py blueprint:<standard-k200's final strategy> --stack-bb 20 --deals 1000 --seed
2027` (`runs/phase5_gate/after/b0.json`, `b0.out`): 1,000 deals, each played twice with the seats
swapped, all-in hands scored by equity (38 adjusted).

- The blueprint won +24.9 ± 6.8 bb/100 (3.7 SE; +27.2 on the button, +22.6 in the big blind).
- B0 gave 4,111 instructions, none illegal, none flagged by the simulator's always-wrong checks.
- 282.7 seconds, 7.1 hands a second, 68.8 ms per B0 instruction (99% of it in B0's advice).

As pre-registered, this only shows the path works end to end: a 20 big blind match of 2,000
hands is not evidence for Phase 6's gate (heads-up, 200bb, 2.5 SE).

### The cloud trainer contract

`runs/phase5_gate/cloud_local_test.py` runs `tools/cloud`'s real supervisor with the blueprint
trainer on this machine, as two machines: the first trains, every process gets SIGTERM, the
trainer saves at 2,558,692 iterations and exits with 75, and the supervisor uploads it; the
second starts with an empty disk, downloads it, resumes at exactly 2,558,692 and finishes, and
the run's state is "done". The rich run above used the same contract.

### Decision

**Decision (Kevin, 27 Nov 2026): the failure is accepted and Phase 6 starts.**

- The sizes half passes clearly (8.5 to 10.5 paired SE at every bucket count), and that is
  what the Phase 6 game relies on (the `rich` menu). The buckets half fails at 20 big blinds.
  It is checked again at 100 big blinds (standard menu, 10, 50 and 200 buckets), as
  information, before the full Phase 6 run. Phase 6 keeps 200 buckets and OCHS on the river.
- **Phase 6's gate changed** (the roadmap in `README.md`). It was "LBR falls at every checkpoint;
  beats B0 heads-up by 2.5 SE". It is now: the last checkpoint beats the first head-to-head by
  2.5 SE (duplicate deals in the Rust arena), and the blueprint beats B0 heads-up by 2.5 SE. LBR,
  with menu bets only and with the 56 sizes, is measured at every checkpoint and reported, not
  pass or fail. Why: in all eight runs here LBR with off-menu bets rose as training went on (for
  example small-k200 from 119.8 bb/100 at 4M iterations to 131.6 at 64M), so the old wording
  would judge the betting abstraction rather than the training. Rule 1 (`README.md`, Rules) is
  unchanged.
- **The Phase 6 machine** is a c4a-highcpu-64 (64 Arm cores, 128 GB, about $1.31 an hour spot,
  against $2.05 for the c4a-highmem-64 the projection priced): the game needs 6.4 to 7.4 GB.
- **Spending**: first a calibration run of about 2 hours, capped at $10, that measures the speed
  on 64 threads, LBR and the change at each doubling. The cap for the full run is set from what
  it measures. At $1.31 an hour, the projection above is about $3 to $18 at the central speed
  and about $61 at the high end of every range.

### Not done

- **Why the buckets half fails** is not tested. The cheapest next step is the bucket half at 100
  big blinds (standard menu, 10, 50 and 200 buckets; 7.2M information sets at 200), about 3 to 4
  hours here. (Done after the gate: "Phase 5 check: buckets at 100 big blinds", below.)
- **Bucket counts above 200**, and potential-aware river buckets.
- **Pruning on a long run**, and Linear CFR's interval and length (Pluribus's, unchanged).
- **The speed on Arm and on 64 threads**: guessed above, not measured.
- **LBR's `fc14`** (30 times slower) and settings with more sizes on the flop only.
- **Phase 6 itself.** Nothing was rented.

## Phase 5 check: buckets at 100 big blinds (27 Nov 2026)

A check added after the gate, not a gate run. At 20 big blinds more buckets didn't lower LBR's
win rate; Kevin asked whether that is the stack depth or will carry into Phase 6. The plan
(`docs/research/runs/phase5_100bb/README.md`, `plan.json`) was committed before training
(350f9c4): heads-up, 100 big blinds, the standard menu, OCHS on the river, 10, 50 and 200 buckets
a street, the gate's training settings and stop rule (change at most 0.08, LBR flat, cap 256M),
then LBR on the same 100,000 deals (seed 778) for all three with six settings (the gate's five
and `fc14`). Results, tables and files are in that folder (`results.md`, `checks.md`).

- **Training.** All three converged: standard-k10 at 16M iterations (7 minutes), standard-k50
  at 64M (40 minutes), standard-k200 at 128M (1.6 hours, 22,786 iterations a second, 1.6 GB).
  M is `b56_14` for all three: 592.6 ± 7.9, 575.6 ± 7.7 and 592.9 ± 7.7 bb/100.
- **The plan's verdict**: buckets help from 10 to 50 (M -16.9 ± 7.8, 2.2 paired SE), then M
  rises again from 50 to 200 (+17.3 ± 7.0, 2.5 SE), so it doesn't flatten. None of the plan's
  four outcomes fits; standard-k200's M equals standard-k10's (+0.4 ± 7.7).
- **On a second deal set** (seed 779, not pre-registered): 10 to 50 is -24.0 ± 7.7 (3.1 SE),
  50 to 200 +7.0 ± 7.0. Pooled over both: -20.5 ± 5.5 (3.7 SE), +12.2 ± 5.0 (2.5 SE), and 10 to
  200 -8.3 ± 5.4 (1.5 SE). All of the fall from 10 to 50 is with the blueprint on the button.
- **Near the menu, more buckets are more exploitable.** From 10 to 200 buckets (seed 778):
  `fcpa14` +36.5 (4.9 SE), `fcpa34` +42.8 (6.6 SE), `b56_34` +42.3 (6.1 SE), `fc34` +13.5 (3.6
  SE); at 20 big blinds the same settings moved by at most 2.7 SE. With `fcpa14` only 1.5% to
  1.7% of the blueprint's decisions are off the tree, so this is not mainly the bet translation.
- **Answer.** Partly the stack depth: at 100 big blinds 10 buckets are measurably too coarse.
  But LBR shows no gain from 50 to 200 buckets, and the near-menu settings get worse at every
  step, more than at 20 big blinds, so this is likely to carry into Phase 6.
- **For Phase 6.** Its gate is head to head and against B0, with LBR only reported (Phase 5: the
  gate, Decision), so the gate is unchanged. But LBR at 100 big blinds goes against 200 buckets
  over 50 (M +12.2 ± 5.0 pooled, `fcpa34` +18.5 ± 6.5), and Phase 6's LBR readings shouldn't be
  expected to show what 200 buckets buy. LBR measures the worst case, not play against a real
  opponent: if 200 buckets are to be checked before the full run, the cheap way is standard-k50
  against standard-k200 head to head at 100 big blinds in the arena (done after the check:
  standard-k200 wins, below). Why finer buckets are more exploitable is not tested (the gate's
  three candidates stand).
- **Scale.** LBR wins 1,671.7 ± 10.9 bb/100 from always calling at 100 big blinds; the three
  blueprints give it 34% to 35% of that (33% to 40% at 20 big blinds).

### Head to head: standard-k50 against standard-k200 (added after the check)

Informational, not a gate run. The plan (`docs/research/runs/phase5_100bb_h2h/plan.md`) was
committed before the main run (171028d), with the manager's rule: standard-k200 ahead by 2.5 SE
means the extra buckets pay off in play; standard-k50 ahead by 2.5 SE is flagged before Phase
6's full run; anything else is inconclusive. The check's final strategy files, the Rust arena
(duplicate deals with the seats swapped, the all-in equity adjustment), 2,000,000 deals a match,
sized from a pilot on other seeds.

- **standard-k200 beats standard-k50 by 3.74 ± 0.48 bb/100 (7.7 SE)**, and by 3.74 ± 0.49 on
  fresh deals: the extra buckets pay off in play. Nothing to flag; Phase 6's gate is unchanged.
- **The sanity check passes**: standard-k50 beats standard-k10 by 13.28 ± 0.52 (25.7 SE), as LBR
  found from 10 to 50. standard-k200 beats standard-k10 by 15.03 ± 0.52. Each step up in
  buckets wins, by less each time.
- **By seat** (each figure includes the button's advantage of about 15 bb/100): standard-k200
  wins 19.29 ± 0.91 on the button and loses 11.81 ± 0.91 in the big blind against standard-k50.
- **So from 50 to 200 buckets, play and LBR disagree**: LBR found standard-k200 more exploitable
  (M +12.2 ± 5.0 pooled), yet it beats standard-k50. This supports Phase 6's 200 buckets, and
  says again that Phase 6's LBR readings are not the value of its card abstraction. Both
  blueprints share the menu, so the match doesn't test play against bets off it.
- **Added after review** (not pre-registered; doesn't change the decision): the main match and
  the replication agreed to 0.0023 bb/100, by chance. Their deals differ, and ten more fresh
  seeds (9203 to 9212) give +2.41 to +4.33 with the spread their SEs predict (p = 0.38). Pooled
  over 12 seeds: +3.57 ± 0.14 bb/100 (`runs/phase5_100bb_h2h/extra.md`).

## Phase 6: ready to launch (27 Nov 2026)

Phase 6 of the roadmap: the heads-up blueprint, Linear Monte Carlo CFR with negative-regret
pruning, trained on a rented Google Cloud machine. This gets it ready: when Kevin approves the
spending, one `python -m tools.cloud launch` on his computer starts the run, and one command
measures every strategy file it writes. Nothing was rented or launched. The plan, the settings
and how they were chosen, the costs and the gate's readings: `runs/phase6/README.md`.

In short:

- **The run** (`runs/phase6/trainer.json`): 200 big blinds, the `rich` menu, 200 buckets a
  postflop street with OCHS on the river, seed 1, 64 threads on a c4a-highcpu-64 (64 Arm cores,
  128 GB; $1.4714 an hour all in at Google's Spot price of 27 Nov 2026; the trainer needs 9 GB at
  most). Linear weighting every 1.75M
  iterations up to 70M, pruning from 35M at -3 million big blinds with probability 0.95:
  Pluribus's schedule as fractions of a nominal run of 2e9 iterations, the middle of the Phase 5
  projection, and Pluribus's threshold, checked against the regrets this game reaches.
- **A strategy file at each doubling**, 1M to 8,192M (14 files of 0.5 GB), each with the change
  from the stage before, the regrets by street and what pruning skipped, kept in the bucket and
  downloaded with `python -m tools.cloud artifacts --download DIR`. Any other checkpoint can be
  exported off the machine (`blueprint export`).
- **The bucket tables** go in the launch bundle (138 MB), not built on the machine: cheaper, and
  the machine trains with exactly the bytes Kevin's evaluation reads.
- **One evaluation command**, `tools/blueprint_eval.py`: LBR (`fcpa14` and `b56_14`) on the same
  deals for every file, head to head in the arena between consecutive files and last against
  first, B0 at 200bb split over processes, the stop rule at each stage, a projection of where it
  stops, and the gate's reading.
- **The dress rehearsal** passed here (`python -m tools.cloud local-test` with the real trainer
  and `trainer.json`, 4 threads, 19.2 minutes): a SIGTERM saved at 2,038,070 iterations, a new
  machine with an empty disk got the checkpoint and the strategy files back and resumed at
  exactly that iteration, and the stop marker ended it "stopped" at 8,033,450.
- **The small-scale check** (`runs/phase6/check.md`): the settings scaled to 8M iterations, two
  runs here with pruning on and off. Pruning trains: on the same deals LBR wins -26 ± 34
  (`fcpa14`) and -23 ± 32 (`b56_14`) bb/100 less against the pruned strategy, head to head it
  is +2.1 ± 10.9, and it skipped 98.4M actions, for 6.8% more iterations a second by the end.
- **The plan**: the cheap real test (a few cents), then a calibration run of about 2 hours (about
  $3, capped at $10) that measures the speed on 64 Arm threads and the start of the convergence
  curve, then the same run going on to the stop rule, with a cap worked out from what the
  calibration measured. At the Phase 5 projection's speeds it stops at the stage at 1,024M (2.9
  hours, $4.30) or 8,192M (23 hours, $33.80), centrally; 45 hours ($66.70) at the high end.
- **The gate**, Kevin's wording of 27 Nov 2026, pre-registered (`runs/phase6/README.md`, "The
  gate"): the last stage file beats the first (1M) head to head by 2.5 SE (200,000 deals, seed
  6101), and beats B0 heads-up by 2.5 SE, in a match sized from a 4,000-deal sizing match's sd
  for an edge of 10 bb/100 (seeds 7201 on). LBR (`fcpa14`, `b56_14`, 20,000 hands, seed 6001) is
  reported at every stage.

### What was built

- **Strategies at stages** (`engine/crates/blueprint`, the cloud trainer): with
  `"strategies": {"first": F, "factor": K}` in the config, it writes `strategy-<iterations>.bps`
  at F, F x K, ... and the end, and a line in `stages.jsonl`: the change from the latest earlier
  stage on the disk (so after a resume on a new machine it is measured from the file that came
  back), the regrets by street (the share below -1,000 to -1,000,000 big blinds and below the
  pruning threshold, the lowest), pruning's counters, the export and measure times and the
  memory. A session never runs past the next stage.
- **A streaming export** (`cfr`, `Mccfr::for_each_set`, 17 lines with a test): the strategy file
  is written from one information set at a time. Before, an export copied every regret and
  strategy sum first, about 10 GB more for the Phase 6 game. This is the one change to the cfr
  crate; nothing in training changed.
- **`blueprint export`**: the strategy file of any checkpoint, off the machine.
- **`blueprint lbr --strategy A,B,...`**: several files in one process, so LBR's exact preflop
  win probabilities (about 3.8 minutes on 4 cores at the start of each process) are worked out
  once. Before, every file paid it.
- **`blueprint:<file>?tables=<dir>`** in `pokerscribe_engine` (`engine/crates/py`): a file
  trained on another machine played with the local copy of its tables (the checksums are still
  checked). The arena and B0 need it for files trained in the cloud.
- **`tools/cloud`**: artifacts (files matching `ARTIFACT_PATTERNS`, by default the strategy files
  and the trainer's JSON logs, uploaded as they are written, put back on a new machine, listed and
  downloaded by `artifacts`); `TRAINER_FILES` (files sent in the bundle, such as the tables);
  c4a-highcpu-64 as a documented option, with `check` testing the trainer's memory
  (`TRAINER_MEMORY_GB`) against the machine type in each zone and the disk against
  `CHECKPOINT_GB` and `ARTIFACTS_GB`; `watch` warns when the trainer's memory passes 90% of the
  machine; `local-test --trainer T --config C` is the dress rehearsal. With Google's figures
  of 27 Nov 2026 (from Kevin's console, through the manager session): c4a-highcpu-64 is the
  default machine, the prices are Google's, a Spot machine's IP is priced on its own ($0.0025 an
  hour), the disk is $0.08 a GB a month and provisioned IOPS and throughput above Hyperdisk
  Balanced's free baseline are counted in the cost, and `check` reads the C4A quota as Google
  names it ("CPUs per VM family", vm_family C4A) through the Cloud Quotas API, keeping the
  `C4A_CPUS` path and a "?" line when neither works. The Cloud Quotas path is tested only on a
  sample written from Google's documented format. 14 new tests.
- **`tools/blueprint_eval.py`** with `app/tests/test_blueprint_eval.py` (7 tests, on fake
  measurements).

### The evaluation on two early files

The rehearsal's 1M and 2M files (0.05% and 0.1% of the nominal run), to check every measurement
and what it costs (`runs/phase6/eval-early.md`):

| Measurement | 1M | 2M | 2M against 1M |
| --- | ---: | ---: | ---: |
| LBR `fcpa14`, bb/100 | +311 ± 34 | +264 ± 30 | -48 ± 36 (z -1.3) |
| LBR `b56_14`, bb/100 | +476 ± 36 | +394 ± 32 | -81 ± 39 (z -2.1) |
| Head to head, 200,000 deals | | | 2M wins +120.9 ± 4.5 (z +26.8) |
| B0, 4,000 deals | | the blueprint loses -96 ± 20 (z -4.7) | |

- B0 at 200bb: 15 to 18 hands a second per process, 11,752 instructions, none that couldn't be
  played as said and none flagged by the simulator's always-wrong checks.
- B0's sd was 1,291 bb/100 a deal. At that sd a 2.5 SE result needs 833,000 hands at an edge of
  5 bb/100, 208,000 at 10 and 52,000 at 20 (on 10 cores, 1.4 hours, 22 minutes and 5 minutes).
  Against a trained file the sd may be quite different; the summary measures it each time.
- LBR: 6 seconds (`fcpa14`) and 17 to 19 seconds (`b56_14`) per file at 20,000 hands after the
  start-up. Head to head: 400,000 hands in about 2 seconds of play, plus about 15 seconds to
  load the two files (a first try at 20,000 deals gave +150.4 ± 14.2; the default is now
  200,000).

### The small-scale check of the settings

`docs/research/runs/phase6/pruning_check.py` (results in `runs/phase6/check.md`): two runs of
the Phase 6 game on 4 threads to 8M iterations through the real trainer, with every iteration
count in `trainer.json` and the threshold multiplied by 0.004 (8M / 2e9): linear weighting every
7,000 up to 280,000, pruning from 140,000 at -12,000 big blinds, probability 0.95. Pruning on in
one, off in the other. Pre-registered in the script before it ran: training seed 1, LBR seed
6001 and 20,000 hands, head to head seed 6101 and 20,000 deals; pruning "trains" if the pruned
run is not worse by 2.5 SE on either measure and pruning skipped something.

| At 8M iterations | Pruning | No pruning |
| --- | ---: | ---: |
| Training time | 724 s | 754 s |
| Iterations a second, 4M to 8M | 11,448 | 10,718 |
| States per iteration, 4M to 8M | 822 | 883 |
| Actions skipped by pruning | 98.4M (25.6M by 4M) | 0 |
| Change from the 4M file | 0.1345 | 0.1341 |
| LBR `fcpa14`, bb/100 | +111.2 ± 28.0 | +137.1 ± 27.7 |
| LBR `b56_14`, bb/100 | +389.4 ± 30.3 | +412.2 ± 29.3 |

- LBR, pruning minus no pruning on the same deals: -25.9 ± 33.7 (`fcpa14`, z -0.77) and
  -22.9 ± 32.0 (`b56_14`, z -0.71). Head to head, pruning against no pruning: +2.1 ± 10.9
  bb/100 over 40,000 hands.
- The same states a second; 6.9% fewer states an iteration, so 6.8% more iterations a second at
  the end. The saving grows with the run (25.6M actions skipped by 4M, 98.4M by 8M); the
  calibration's stages measure it on the real run.
- At 8M, 4.0% of the preflop slots were below the threshold, 0.77% of the flop, 0.35% of the
  turn and 0.16% of the river (never pruned, only measured).
- **Pruning trains**, by the pre-registered reading.
- Not covered: the regret floor was not scaled (it stayed at -3.1M, which nothing reached), and
  the speed on 64 threads and the regrets of a real 2e9 run are only measured on the rented
  machine.

### Not done

- **Anything on Google's side.** Nothing was rented: not the cheap real test, not a C4A machine,
  not a real preemption notice.
- **The speed on 64 Arm threads**, and the Arm build: the calibration run measures them.
- **Whether `abstraction-build` gives the same tables on Arm as on x86.** Copying the tables makes
  it not matter for this run.
- **Stage pauses.** The export and the measures run on one thread while the other 63 wait, about
  1.5 minutes a stage (14 to 17 minutes of the calibration's 2 hours, 21 minutes over a whole
  run). A parallel export, or one from a checkpoint in a separate process, would save most of it.
- **The Cloud Quotas API on a real project**: `check`'s reading of the C4A quota is tested on
  Google's documented format only.

### The calibration launch (27 Nov 2026): no training, the setup failed

Kevin approved one launch capped at $3.50 (`BUDGET_USD=3.5`, within the $10 approval), run by
hand from his Mac. `check`, `local-test` and `launch --dry-run` passed.

- **Attempt 1** made nothing: Google refused the create (Hyperdisk Balanced given a throughput
  needs the IOPS too). Fixed in #44.
- **Attempt 2** made `ps-hu-blueprint-1` (c4a-highcpu-64, Spot, $1.4714/h, hard stop after
  2h22m43s; bundle a73c83ca13d54641, which included the Phase 7 groundwork pulled with #44). The
  startup script stopped at the build one second after it began: `cargo build --release --bin
  blueprint -p blueprint --locked` exited with 101. The machine then sat idle and billing: no
  checkpoint, no report, about $1.25 at 51 minutes (`watch` warned "no report from the machine
  for 51 min"), then Kevin was told to `stop` it.

**Cause, reproduced here.** `engine/Cargo.lock` was not in the repo, so the bundle carried the
one in Kevin's `engine/`, written by his builds before the pull. It had no entry for the new
`search` crate, and with `--locked` cargo refuses to add one: "cannot update the lock file ...
because --locked was passed", exit 101, before compiling anything. The same command on today's
`main` with an up-to-date lockfile builds the trainer (14 s on x86), and the workspace
type-checks for aarch64 Linux. The Phase 7 code was not at fault, only the lockfile.

**Why it billed.** The startup script's failure handler (upload the log, mark the run failed,
power off) is an ERR trap, and bash doesn't run one inside a function without `set -E`. The
build runs inside one, so the script just exited. Cargo's output went only to the machine's own
`/var/lib/pscloud/startup.log`, not to the serial console or the bucket. The supervisor never
started, so the tools' cost estimate counted nothing for the boot after the stop. Only Google's
`--max-run-duration` still capped the spending.

**Fixed (tools/cloud, with tests):** `engine/Cargo.lock` is committed, and CI builds with
`--locked` (it fails if the lockfile misses a crate); `check`, `launch` and the dry run check the
local lockfile before anything is created; the startup script runs with `set -E` and prints the
end of cargo's output on the serial console; `recover` stops a machine with no report
`SILENT_STOP_MINUTES` (30) after it started; a boot that never reported counts in the cost
estimate, and `stop`, `cleanup` and `recover` record it in the bucket's sessions so `launch` and
later supervisors count it too.

**Not done:** the trainer has still not been built or run on an Arm machine. The next launch is
Kevin's decision: the stopped machine must go first (`cleanup`; `launch` refuses while it
exists, and `resume` would boot it with the old bundle), and `BUDGET_USD` sets what the next
attempt may spend on top of what this one cost (the billing console has the real figure).

## Phase 6: the calibration run and the gate (27 Nov 2026)

The calibration run of the Phase 6 plan (`runs/phase6/README.md`, "The plan": "The calibration
run: about 2 hours, capped at $10"), on a second machine after the failed launch above, with the
fixes of #44 and #45. It trained the heads-up blueprint past the stop rule's first "stop" inside
the calibration's budget, so there is no full run, and **the Phase 6 gate passes**: the gate's
last file (512M iterations) beats the first (1M) head to head by +147.7 ± 3.9 bb/100 (z +38.0)
and beats B0 heads-up by +16.3 ± 4.1 (z +4.00). Run by hand from Kevin's Mac. The raw material,
gathered by the manager session from the calibration session's reports, is in
`runs/phase6/calibration/`: `notes.md` (the timeline, the cost, the evaluations, the incident),
`summary-1.02G.md` (the first evaluation's summary, verbatim) and `huge-pages.md`. Training was
on a rented machine and every match was against our own agents (rule 4).

In short:

- **The run**: c4a-highcpu-64 Spot in us-central1-a, about 2 hours 19 minutes from the launch
  to the budget stop, 1,330,975,013 iterations, no preemption, restart or crash. **$4.67 in
  all**, including the $1.29 the failed launch's idle boot cost.
- **The speed**: about 183,000 iterations a second at the end on 64 Arm threads, 1.85 times the
  Phase 5 projection's central speed and near its fast end (200,000). The 47,036 a second
  `watch` showed at 7 minutes was the stage pauses diluting the rate, not the training speed.
- **The stop rule** first said stop at the 512M stage (change 0.0745, LBR `b56_14` moved +10.9 ±
  12.2). By the pre-registration that file is the gate's last, the 1,024M file is reported
  only, and no full run is needed.
- **The gate passes**: head to head +147.68 ± 3.89 bb/100 (z +37.99); B0 +16.3 ± 4.1 over
  82,000 hands (z +4.00), in a match sized from the sizing match's sd (801 a deal), as
  registered.
- **LBR**, reported: `fcpa14` fell from +391 to +112 bb/100 by 8M and has been about flat since
  (+94 to +156); `b56_14` stayed near +480 at every stage. What LBR wins with 56 sizes comes
  from bets off the menu: Phase 7's problem.
- **An incident**: one false "no report from the machine" during the run, from a failed read of
  `status.json`. Fixed in #46, before it could stop a healthy machine.
- **Huge pages**, a side test: the trainer 1.145 times as fast. Not used for heads-up, kept for
  six-max (the manager session's decision).

### The run

`runs/phase6/trainer.json` and `cloud.env.example`, with `BUDGET_USD=5` (Kevin, inside his $10
calibration approval): c4a-highcpu-64 Spot in us-central1-a, an 80 GB Hyperdisk Balanced at
3,000 IOPS and 400 MiB/s, $1.4714 an hour (machine $1.4459, IP $0.0025, disk $0.0230). The cap
counted the failed launch's boot ($1.29, recorded in the bucket since #45), and Google's hard
stop on the machine was at 2h31m20s, about what the $3.71 left buys; the supervisor's budget
stop came first. Launched about 19:32 UTC. Times from `watch`, about ±2 minutes:

| After the launch | Iterations | `watch`'s speed, a second |
| --- | ---: | ---: |
| 7 minutes | 16M | 47,036 |
| about 21 minutes | 128M | 141,821 |
| about 34 minutes | 256M | 153,705 |
| about 1h47m | 1,024M | 176,662 |
| about 2h19m (21:51, the budget stop) | 1,330,975,013 | 183,096 (the trainer's own count: 182,020) |

- **The stop**: requested at 21:51 by the budget; the trainer saved on SIGTERM and exited 75
  (stopped). `recover`, running on Kevin's Mac, logged one "wait" line a minute and exited at
  21:52 with "finished: the run is budget".
- **The cost**: $4.67 (machine $4.56, IP $0.01, disk $0.10), the $1.29 boot included, so this
  machine cost about $3.38. The plan's central estimate for the whole run (the power law,
  stopping at the 1,024M stage) was $4.30.
- **Memory**: the trainer used 7.5 GB, at most 9.8 GB, of the machine's 134.8 GB: more than the
  rehearsal's peak (8.86 GB) and `TRAINER_MEMORY_GB=9`, which `check` tests, but harmless here.
- **Files**: 13 artifacts, 5.5 GB (11 strategy files of 503.4 MB, `stages.jsonl` and
  `log.jsonl`), and the last 3 checkpoints, 4.9 GB each. After `cleanup` only the bucket is
  left: 20.28 GB, about $0.41 a month.
- **On Kevin's Mac**: `abstraction-build check ~/abstraction/k200` passed its 19 checks with the
  runbook's checksums (flop 7e143f5b92504f9b, turn e8f2df9a3d04e8b8, river e7ff8e349b9587b6),
  and `blueprint` (`cargo --locked`) and `pokerscribe_engine` were rebuilt from main.

### The speed

`watch`'s rate is taken between the trainer's session lines, so it counts the stage pauses. The
five stages from 1M to 16M come in the first 7 minutes, and at each one training waits while one
thread exports the strategy file and measures it (about 1.5 minutes a stage in the rehearsal),
so the 47,036 at 16M counts those waits as time without iterations. Each doubling takes twice
as long as the one before, so the pauses weigh less and less, and the rate approaches the
training speed: 141,821 at 128M, 153,705 at 256M, 176,662 at 1,024M and 183,096 at the end.

The Phase 5 projection (57M, 112M and 227M states a second at 1,134 states an iteration) gave
50,300, 98,800 and 200,000 iterations a second. The run's final speed is 1.85 times the central
one and 0.92 times the fast one. Its states a second and states per iteration (`log.jsonl`)
aren't in the notes.

### The evaluations

1. **All 11 files** (`summary-1.02G.md`; its header has the command, with `--b0 none`). The change
   from each stage to the next rose to 0.2055 at 8M, inside the linear phase, then fell: 0.1883,
   0.1691, 0.1488, 0.1187, 0.0887 (256M), 0.0745 (512M) and 0.0655 (1,024M), by a factor of 0.82
   a doubling over the last four. **The stop rule** (a change of at most 0.08, and `b56_14` moved
   by less than 3% or 2 SE) first says stop at 512M: change 0.0745, `b56_14` +10.9 ± 12.2 (z
   +0.89). The run's own projection puts a change of 0.08 at about 4.4e8 iterations; the Phase
   5 projection's power law had put it at 7.4e8.
2. **Why the gate's last file is 512M, and why there is no full run** (the manager session's
   reading of the pre-registration). README, "The gate": the checkpoints are the stage files
   from 1M "up to the stage where the stop rule says stop", the last file is that stage's, and
   which files are first and last is "fixed once the run starts". The stop rule said stop at
   512M, so the 512M file is the gate's last. The run went on past it because the calibration
   was meant to run about 2 hours, and its budget ended it at 1,331M. The 1,024M file is reported,
   not judged. The full run was to train until the stop rule says stop (README, "From the
   calibration to the full run": `until` stays 8,192M and the stop rule ends the run), and the
   calibration already had, so there is none.
3. **eval512**: the files from 1M to 512M (`--out ~/phase6/eval512 --b0 last --b0-deals 4000
   --b0-seed 6201`). Every LBR figure (both settings, 10 files), every LBR difference and every
   head to head between consecutive files repeated `summary-1.02G.md` exactly; only the hands a
   second differ. New in it: 512M against 1M head to head, and LBR from the first file to the
   last. Its summary after the gate's match (`summary-512M.md`, as `summary-1.02G.md` calls it)
   is on Kevin's Mac; `notes.md` quotes its B0 and gate sections verbatim.
4. **B0, the sizing match** (not judged): 4,000 deals (8,000 hands), seeds 6201 on, the blueprint
   +12.9 ± 12.7 bb/100 (z +1.02), sd 801 a deal, 64.7 hands a second over all processes.
5. **B0, the gate's match**: N = (2.5 × 801 / 10)² = 40,100 deals, rounded up to 41,000 (82,000
   hands), seeds 7201 on: **the blueprint +16.3 ± 4.1 bb/100 (z +4.00)**, sd 825 a deal, at 67.3
   hands a second (about 20 minutes). At the match's own sd N would have been 43,000; N is set
   from the sizing match's sd, as registered, and the two matches are not pooled.

### The gate

| Condition (passes at z ≥ 2.5) | Result | |
| --- | ---: | --- |
| The 512M file against the 1M file head to head, 200,000 deals, seed 6101 | +147.68 ± 3.89 bb/100, z +37.99 | passes |
| The 512M file against B0 heads-up, 41,000 deals, seeds 7201 on | +16.3 ± 4.1 bb/100, z +4.00 | passes |

**The gate passes**, by the summary's own reading (`notes.md`). Head to head, every doubling
still gained, by less each time: from +117.7 (2M against 1M) to +6.9 ± 2.3 (256M against 128M),
+3.4 ± 2.2 (512M against 256M, z +1.5) and +2.3 ± 2.1 (1,024M against 512M, z +1.1). The
1,024M file beat the 1M file by +145.8 ± 3.9, about what the 512M file did. As the README says,
beating the nearly random 1M file shows that the training went somewhere, and little more.

### LBR (reported, not pass or fail)

| Setting | 1M | 8M | 32M | 512M | 1,024M | 512M minus 1M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `fcpa14` | +391.0 | +111.5 | +94.0 | +155.7 | +151.1 | -235.3 ± 39.6 (z -5.95) |
| `b56_14` | +436.1 | +481.5 | +480.2 | +490.3 | +481.8 | +54.2 ± 41.4 (z +1.31) |

- **`fcpa14`** (bets of the pot and all in only, the menu's own sizes): the fall was over by 8M.
  The only step of 2.5 SE from one file to the next was 1M to 2M (-156.8 ± 35.0). From 8M on it
  stayed between +94 and +156, with no step of 2 SE.
- **`b56_14`** (56 sizes): between +410 and +523 at every stage, about +480, with no trend. With
  56 sizes LBR makes bets the menu doesn't have, and at 512M the abstract game couldn't follow
  the hand in 8.5% of the blueprint's decisions, so the blueprint just checked or called ("Off
  the menu" in the summary; 0.7% under `fcpa14`). That is the weakness the Phase 5 gate found.
  More training doesn't touch it. Phase 7's search adds off-tree bets and re-solves; in the
  Phase 7 groundwork, at 20 big blinds, LBR `b56_14` won 35.8 ± 5.7 bb/100 less against search
  than against its blueprint.

### The incident: a false "no report"

During the run one `watch` printed no status lines and "WARNING no report from the machine for
78 min". A minute later `gcloud storage ls -l` showed `status.json` freshly written, and the
next `watch` was normal. The cause: `GcsStore.get_bytes` returned None when a read failed (a
failed `gcloud storage cat` that matched "not found", or JSON that didn't parse), and the tools
took a missing status for "never reported this boot". `recover`'s stop of a silent machine
(#45) read it the same way, so one bad read could have stopped a healthy machine; it didn't, in
about 140 polls. Fixed in #46: a failed read is "unknown", the silent-machine stop needs 3 looks
a poll apart that agree, `stop` waits for the save when the report is unknown, and `leftovers`
prices each disk's provisioned IOPS and throughput (it had shown the stopped disk at $6.40 a
month; Google bills $16.80 at 400 MiB/s).

### Side test: huge pages

`huge-pages.md` (the manager session): the Phase 6 game to 4M iterations on 4 threads in a
4-core x86 cloud container, plain against huge pages through glibc
(`GLIBC_TUNABLES=glibc.malloc.hugetlb=1`, about 3.75 of the 8 GB in huge pages), in the order
plain, huge, huge, plain. With huge pages it trained 1.145 times as fast (279 s against 319 s
on average). Huge pages won both pairs, by 1.09 and 1.19, and the container's runs vary by
about 14%. **Decision (the manager session): not used for heads-up**, where the blueprint is
done (it would have saved about $2 to $4 on a full run). **Kept for six-max** (Phase 8), where
the runs are longer, and where asking for huge pages on every big table in the trainer
(`madvise`) may give more than the glibc setting. Not measured on Arm.

### Not done

- **The run's own counters**: states a second, states per iteration, the regrets by street and
  what pruning skipped (`stages.jsonl` and `log.jsonl`, in the bucket and on Kevin's Mac) aren't
  in the notes, so they aren't reported here.
- **Whether `fcpa14`'s rise from +94 at 32M to +156 at 512M is real**: no step between files was
  2 SE, and at 20,000 hands each figure's SE is about 25 bb/100.
- **The Phase 7 gate** on this blueprint: beating it by 2.5 SE, a luck-adjusted Slumbot match and
  the GTO Wizard Benchmark.

## Phase 7 groundwork: depth-limited search (27 Nov 2026)

Phase 7 of the roadmap (`README.md`): "Depth-limited search on every postflop decision
(Modicum): opponent picks among blueprint and fold/call/raise-biased versions at the leaf;
ranges updated every action; off-tree bets added and re-solved". This builds the search
(`engine/crates/search`) and measures it on a 20 big blind Phase 5 blueprint on this machine (4
cores, Intel Xeon at 2.1 GHz). It is groundwork, not the Phase 7 gate: the gate is for the
Phase 6 blueprint at 200 big blinds. The plan was written and committed before the runs
(`runs/phase7_groundwork/README.md`, commit 2d9a22a); the results are in `results.md` there.
Everything was offline, against our own agents (rule 4).

In short:

- **The search works end to end**: every postflop decision of 6,000 hands against the blueprint,
  15,000 hands against LBR and 200 against B0 (from Python, `tools/b0_arena.py
  search:<file>`) was searched, with no illegal action.
- **Head-to-head it does not beat the blueprint**: -2.51 ± 4.56 bb/100 over 3,000 deals
  (z -0.55). An edge of more than about +6.6 bb/100 is unlikely. Against its own blueprint the
  search's ranges are exact and it never re-solves, so its only possible edge is exact hands over
  200 buckets; at 20bb that is likely small next to its own solving error.
- **LBR wins less against search than against the blueprint**: by 35.8 ± 5.7 bb/100 with 56 bet
  sizes (`b56_14`: +112.8 against the blueprint, +77.1 against search; z -6.3, pooled over two
  seeds, 7,500 hands each) and by 10.7 ± 5.3 with fold, call, pot and all in (`fcpa14`, z -2.0;
  LBR finds nothing against either). Both kept their sign on fresh seeds (`fcpa14` only at
  z -1.1). The `b56_14` gain most likely comes from the off-menu bets being added to the tree and
  re-solved (18% of the flop solves were re-solves): the weakness the Phase 5 gate found.
- **Decision time on 4 threads**: flop p50 0.48 s and p95 0.75 s, turn 2.2 s and 6.0 s, river
  39 ms and 158 ms. Estimated for the Phase 6 game (200bb) on 64 cores: about 0.3 to 0.6 s on the
  flop, 1.5 to 5 s on the turn, under 0.3 s on the river, plus 9.7 GB of leaf tables that take
  about 2 hours to build there.
- **Ranges**: in 300 hands against the blueprint both players' real hands were in the range and
  in the solve at every one of 415 decisions after the flop, and were typical members of it.

### What was built

- **Ranges.** Both players start with all 1,326 combos; each action multiplies the actor's
  weights by that combo's probability of it, and board cards remove combos. The opponent's
  probabilities are the blueprint's, of the real action or, for a size the blueprint doesn't
  have, of the menu action it reads it as (its own pseudo-harmonic mapping). The searcher's own
  are those it played with (its solved strategy after the flop), so its hand never drops out of
  its own range.
- **River and turn.** A subgame from the real state (pot, stacks, bets), the blueprint's menu at
  every decision plus the real off-menu actions, solved with the `subgame` crate: the river to
  0.5% of the pot, the turn to 2% with every river card and a smaller river menu (three quarters
  of the pot or all in, then all in).
- **Flop, depth-limited.** Discounted CFR over every combo to the end of the flop, to 1% of the
  pot. At a leaf the opponent picks, per hand, one of four continuation strategies (the
  blueprint, and the blueprint with the probability of folding, of checking or calling, or of
  betting or raising multiplied by 5 and renormalized, as in Pluribus; Modicum used 10); the searcher
  plays the blueprint. The leaf values are precomputed tables: for each abstract turn start and
  each of 7 strategy pairs, the big blind's expected share of the pot by the two hands' flop
  buckets, averaged over 16M random deals walked exactly through the blueprint's turn and river
  (22 minutes on 4 cores at 20bb, 149 MB). Card removal is exact at every leaf. Modicum valued
  its leaves by rollouts at run time; tables are faster per decision but grow with the game
  (below).
- **Re-solving.** A bet not in the street's tree is added and the street solved again from its
  start, with the searcher's earlier decisions on the street fixed to what it played. Unsafe, as
  Pluribus re-solves: the opponent's range at the street's start is taken as it is, with no
  gadget holding its values to the earlier solve's. A safe gadget needs those values for every
  hand, and at a flop cut off by estimated leaf values they are estimates too; LBR is the check
  on what unsafe costs.
- **Agents.** `search:<strategy file>` in the arena and from Python
  (`engine/crates/py/src/agents.rs`), and `lbr::Strategy` for LBR.
- **Small changes elsewhere**, each with a test: `subgame` builds a tree from its parts and can
  freeze a node's strategy (the solver and its best response follow it); `blueprint` gives the
  strategy at a node for one bucket and the probability of an off-menu action as it reads it.

### Results

All in `runs/phase7_groundwork/results.md`, with the raw outputs. At 20 big blinds, 2,000 chips,
blinds 50 and 100, the Phase 5 standard-k200 blueprint retrained with the gate's spec, its leaf
tables from 16M deals.

| Measure (LBR: what LBR wins; lower is better) | Blueprint | Search | Search minus blueprint |
| --- | ---: | ---: | ---: |
| Search's bb/100 against the blueprint, 3,000 deals (seed 7101) | | -2.51 ± 4.56 | |
| LBR `b56_14`, 1,500 hands (seed 7103) | +118.0 ± 14.0 | +75.5 ± 14.3 | -42.5 ± 12.2 |
| LBR `b56_14`, 6,000 hands (seed 7202) | +111.6 ± 7.5 | +77.4 ± 7.6 | -34.1 ± 6.4 |
| LBR `fcpa14`, 1,500 hands (seed 7102) | -25.1 ± 16.6 | -53.0 ± 16.2 | -27.9 ± 11.8 |
| LBR `fcpa14`, 6,000 hands (seed 7201) | +0.4 ± 7.9 | -6.0 ± 8.0 | -6.4 ± 6.0 |
| B0's bb/100 against it, 100 deals (seed 7107) | +11.78 ± 18.25 | -4.70 ± 22.08 | |

The fresh-seed LBR runs (7201, 7202) were added after the first results and written into the
plan before they ran. The LBR differences are paired deal by deal (`search compare`).

Decision time, 150 hands against the blueprint on 4 threads (seed 7104):

| Street | p50 | p95 | Max | Iterations (mean) | Exploitability (mean) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flop | 480 ms | 752 ms | 1,044 ms | 46 | 0.88% of the pot |
| Turn | 2,228 ms | 6,021 ms | 6,677 ms | 55 | 1.76% |
| River | 39 ms | 158 ms | 206 ms | 71 | 0.45% |

On 1, 2 and 4 threads (6 flops, 6 turns): a turn solve 3.0 to 3.3 times faster on 4 (8% of it
serial), a flop solve 2.3 to 3.0 times (17% serial). For 200 big blinds on 64 cores the estimate
takes time as solver nodes times combos times iterations (constant on the turn here, 0.010
microseconds on one thread), Amdahl's law with those serial shares, and an Axion core as fast
as one here (not measured): the turn's subgame has 13,857 nodes at 200bb (8,980 here on
average). The Phase 6 game (`rich` menu) has 8,669 abstract turn starts against 133 here, so its
leaf tables would be 9.7 GB at 200 buckets and take about 134 core-hours at 16M deals.

Not judged here, since it is groundwork: the head-to-head would fail the Phase 7 gate's 2.5 SE
bar. On the Phase 6 blueprint the search's gain may be larger, since a 200bb game's
abstraction leaves more to fix; that is for the gate to show.

### Not done

- **The Phase 7 gate**: it needs the Phase 6 blueprint.
- **Ranges against opponents that are not the blueprint** (LBR, B0, people): a hand the
  blueprint would never play that way gets weight 0 and the search plays it as the blueprint.
  How often that happens wasn't measured.
- **A safe re-solving gadget** (Brown and Sandholm 2017), to compare with the unsafe form under
  LBR.
- **Leaf values by rollout at run time**, as Modicum did, which a 200bb game may need: its tables
  would be 9.7 GB at 200 buckets.
- **Parallelizing the flop's leaves**: 17% of a flop solve runs on one thread, so the flop gains
  little past 4 threads.

## Phase 7: AIVAT in the arena (28 Nov 2026)

AIVAT (Burch, Schmid, Moravcik, Morrill and Bowling, AAAI 2018) in the Rust arena
(`engine/crates/arena/src/aivat.rs`), so that head-to-head comparisons need fewer hands. It is
reported next to the main figure, not used to judge anything, until the checks below show it
unbiased. How it works and why it is unbiased by construction: `engine/crates/arena/README.md`,
"AIVAT". Everything here is offline, against our own agents (rule 4).

### Plan (written and committed before the runs)

**The estimator, frozen for these runs**: the arena's defaults as committed with this plan.
The value of a situation is its check-down value (each seat's share of the chips if nobody bet
again, averaged over every board still to come, exact after the flop, 2,000 random boards
before it); a bet still to be answered is called with the minimum defense frequency and folded
to otherwise; and an action is valued one step further, by the answers of the next player to
act, when that player can give them (blueprint agents can, the search agent and B0 can't). The
cards and the deal are corrected for every agent; the actions of an agent that reports the
chances it played with (blueprints, the search agent) are corrected too; those of agents that
don't (rule bots, B0) are not.

**Pilots, which chose those settings** (their seeds are not used below):

- Arena bots, seed 3, 100,000 deals at 100bb: the SE of AIVAT over the main figure's SE was
  0.766 for `mixed` against itself (a test bot with known chances), 0.890 for `tag` against
  `mixed-loose` and 0.886 for `tag-loose` against `tag` (cards only). Valuing every unanswered
  bet as called was clearly worse (1.395 on `tag` against `mixed-loose`, more SE than without
  AIVAT); the minimum defense frequency and taking the bet back did about as well as each other.
- Blueprints, seed 9001, 20,000 deals: the standard-k200 file at 16M iterations against the one
  at 4M (this training run, below). SE ratio 0.761 with the minimum defense frequency, 0.732
  with the bet taken back, 0.929 with it called. With the answers of the next player added: 0.635
  and 0.638. The paired difference AIVAT minus main was within 1.4 of its SE in every variant.
- On `mixed` against itself (seed 3) the answers took the ratio from 0.766 to 0.695.
- The tests in `engine/crates/arena/tests/aivat.rs` use their own seeds; they are tests, not
  runs.

**The agents.** The 20bb standard-k200 blueprint, retrained here with the Phase 5 gate's spec
as for the Phase 7 groundwork (standard menu, 200 buckets a street, 20 big blinds, training seed
1, 4 threads, linear weighting to 20M): the files at 4M, 16M and 64M iterations
(`/root/bp/standard-k200/strategy-<N>.bps`). The search agent: `search:<64M file>` with leaf
tables from `search leaf --deals 16000000 --seed 7` and `search::Settings::default()`, as in the
groundwork. The rule bot `tag`.

**The runs.** All through `pokerscribe_engine.run_match` at 2,000 chips, blinds 50 and 100,
heads-up, each deal twice with the seats swapped, the main figure with all-in equity (at most
10,000 boards), AIVAT at its defaults, 4 threads. Scripts and outputs go to
`docs/research/runs/phase7_aivat/`. No run is stopped early or extended on its result.

| # | Match | Deals | Seed | What it checks |
| --- | --- | ---: | ---: | --- |
| 1a | 64M against a second copy of itself | 1,000,000 | 7501 | Identical agents, every action corrected |
| 1b | The same | 1,000,000 | 7502 | The same on a fresh seed |
| 1c | `tag` against `tag` | 1,000,000 | 7503 | Identical agents, cards only |
| 2a | 16M against 64M | 1,000,000 | 7511 | Agreement on a large run, SE ratio |
| 2b | 4M against 64M | 1,000,000 | 7512 | The same with a larger gap |
| 3 | `tag` against 64M | 200,000 | 7531 | Agreement when one agent's chances are unknown |
| 4 | Search on 64M against 64M | 500 | 7521 | SE ratio on the search groundwork's setup |

**How each is read.**

- **Identical agents (1a to 1c)**: pass if AIVAT's bb/100 is within 3 SE of 0, and the paired
  difference AIVAT minus the main figure (per deal) within 3 of its SE.
- **Agreement (2a, 2b, 3)**: pass if AIVAT minus the main figure is within 2.5 of its paired SE.
  This is sharper than comparing the two intervals: the two figures come from the same hands,
  so most of their noise is shared. Both figures and their SEs are reported too.
- **SE ratio**: AIVAT's SE over the main figure's SE (duplicate play and all-in equity), and over
  `plain_se` (what plain play would give over the same hands: real chips, every hand on its
  own). Reported for 2a, 2b, 3 and 4. The pilots point to about 0.64 on blueprint against
  blueprint.
- **The search run (4)**: 500 deals give a rough SE ratio (it is estimated from the same deals
  for both figures, so it is far more precise than either SE). The agreement check is reported
  but, at this size, can only catch a large bias.
- **The verdict**: AIVAT counts as shown unbiased for this use if 1a, 1b, 1c, 2a, 2b and 3 all
  pass. If one fails, AIVAT stays reported only, the cause is looked for, and no setting is
  changed and run again on these seeds.

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
