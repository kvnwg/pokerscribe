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
  which the new roadmap's Phase 1 adds, with the check that B0 plays heads-up.
  `tools/simulate.py` is six-max only.

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
