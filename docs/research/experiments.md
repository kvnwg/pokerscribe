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
  that redeal the opponents, and luck only where nobody can bet again. It is unbiased, has
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
  (`texture_sizing`) in run 5. It is unbiased (see above), so it stays the default in
  `tools/compare.py`.
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

## Phase 2: the river solver against B0 (26 Nov 2026)

Phase 1 was closed by Kevin's decision (Phase 1, gate run 5), so the rest of Phase 2's gate
can run: `river_solver` must beat B0 by 2.5 SE.

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
