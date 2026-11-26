# External benchmarks and compute costs

Research notes, 26 Nov 2026. No code. Every number has a source in brackets, listed at the end.
Prices and leaderboards change; the date each was read is given.

Units: bb/100 is big blinds won per 100 hands. mbb/g (also written mbb/h or mbb/hand) is
thousandths of a big blind per hand, so 10 mbb/g = 1 bb/100. Error bars are written as the source
wrote them; what the "±" means differs between papers and is noted each time.

## Summary

- Both public benchmarks play the same game: heads-up No-Limit Hold'em, blinds 50/100, 200 big
  blind stacks (20,000 chips), stacks reset every hand [G1, G2, S1]. That is the old ACPC format.
  Neither is six-max, so they can test heads-up parts of PokerScribe (the river solver, push-or-fold),
  not the six-max agent as a whole.
- Both are built for bots and invite them, with play chips, so they fit Rule 4 ("environments we own
  or may use"). GTO Wizard's terms forbid using the hands to train or calibrate our agent [G3], so
  it can only be a test, never a tuning set.
- GTO Wizard luck-adjusts with AIVAT on their side and returns a standard error [G1, G4]. Slumbot
  returns raw chips per hand through the API [S1]; luck adjustment would be our job.
- The 19.4 bb/100 GTO Wizard AI vs Slumbot result is stated by the GTO Wizard authors only, with
  150,000 hands, and the paper does not say what the ± is or whether it was luck-adjusted [G1].
  It is plausible next to Supremus's independent 176 ± 44 mbb/g against Slumbot [P4].
- The Modicum, Pluribus and DeepStack claims check out against the papers, with small corrections
  (section 3).
- A 64-core machine does a 700-core-hour run in about 11 hours and a 12,400-core-hour run in about
  8 days. On-demand totals: roughly $27 to $56 for the heads-up run and $470 to $990 for the
  six-max run on AWS or GCP; spot roughly $11 to $33 and $190 to $590 (section 4).

## 1. GTO Wizard Benchmark

### What it is

A public REST API where your bot plays heads-up hands against GTO Wizard AI, plus a public
leaderboard [G1, G2]. GTO Wizard AI is described as a proprietary agent that combines
equilibrium finding with deep learning, trained by self-play "over hundreds of millions of hands",
that computes its strategy in real time [G1, section 3]. The API spec is titled "Ruse AI Researcher
API" [G4]; Ruse AI was bought by GTO Wizard in 2023 [G7].

### How to get access

1. Fill in the request form behind "Evaluate Your Model" on benchmark.gtowizard.com [G2, G6].
   The form posts to `/users/request` with: email, organization, bot name, an API key that you
   choose yourself (32 to 256 characters), and a reason for joining (up to 2,000 characters) [G4].
2. GTO Wizard reviews the request and confirms by email [G2, G6].
3. Play with the key in the `X-API-Key` header [G4]. Endpoints: `POST /hands` (new hand, the only
   game name is `HUNL 200BB`), `POST /hands/{hand_id}/act` (actions `f`, `k`, `c`, `b` with an
   amount), `GET /hands/in-progress`, `GET /results`, and the public `GET /leaderboard` and
   `GET /winnings` [G4].
4. Starter client (Python 3.13 and uv) with fold, check-call, all-in and random sample agents:
   github.com/gtowizard-ai/researcher-api-client [G6].

The API only plays hands and reports chips won or lost; requests for solver features are refused,
and access can be revoked on suspected misuse [G2, G6].

### Limits

| Rule | Value | Source |
| --- | --- | --- |
| Hands to appear on the site's leaderboard | 1 | [G2] |
| Default `min_hands` filter of the leaderboard endpoint | 1,000 | [G4] |
| Hands per user per game | 10,000 a day, 25,000 a week, 50,000 a month | [G2] |
| Resets | midnight UTC; weekly on Monday; monthly on the 1st | [G2] |

The site says the limits "may change at any time" [G2]. An April 2026 PokerNews article gave
different numbers (2,500 hands minimum, 100,000 a month) [G8]; the live site's numbers above are
newer and should be used.

### Terms (last updated 21 Feb 2026) [G3]

- Use is licensed only "for the sole purpose of performance benchmarking". Revocable, not
  transferable.
- Not allowed: sharing the API key; scraping or systematic querying to extract GTO Wizard AI's
  strategy; using benchmark data "to train, fine-tune, or calibrate" any AI or solver; human help
  during hands ("Centaur" play); manipulating results; overloading or evading rate limits.
- Results are public. You grant GTO Wizard a perpetual, royalty-free license to publish your bot's
  name, rank, data and full hand histories, and to use your bot's play to improve their own AI.
- They can end access at any time without notice. Liability is capped at the greater of $100 or
  what you paid in 12 months. Czech law governs.

What this means for us: the no-calibration rule means GTO Wizard hands can never feed B0 tuning,
opponent models or the TUNING dict. It is a final exam only. Our hand histories become theirs to
publish.

### Game format

Heads-up No-Limit Hold'em, blinds 50 and 100 chips, 200 big blind stacks (20,000 chips), stacks
reset before every hand, each hand independent, following the ACPC [G1, sections 3 and 4.1; G2].
Heads-up Pot-Limit Omaha is listed as "coming soon" [G2].

### How results are luck-adjusted

- GTO Wizard runs AIVAT [A1] on its side. AIVAT is an unbiased estimator that subtracts the luck of
  the cards (chance correction) and the luck of the known agent's own random action choices (action
  correction), using that agent's strategy, which is why only GTO Wizard can compute it [A1, G4].
- The paper and the site claim about a threefold cut in standard deviation, so about 10 times fewer
  hands for the same significance [G1, section 3; G2].
- Each result returns raw bb/100, "All Hands Chips" (the result against GTO Wizard AI's whole
  range), the chance and action corrections, the AIVAT win rate in bb/100, and its standard error
  [G4].
- The leaderboard ranks by the lower end of the 95% confidence interval of the AIVAT win rate [G2].
- Naming trap: the API field is called `aivat_std_bb_per_100`, but its description says it is the
  standard error, with the old name kept for compatibility [G4]. The paper's Table 2 calls the same
  ± "the standard deviation of the match" [G1]. The live numbers behave like a standard error (they
  shrink with the square root of the hands), so treat it as a standard error.

### What this means in hands

From the live leaderboard (53 bots with at least 20,000 hands, read 26 Nov 2026 18:06 UTC [G5]):
standard error × √hands ÷ 100 gives a per-hand AIVAT standard deviation of 1.97 to 3.30 bb, median
2.53 bb. At the median, a standard error of 2 bb/100 takes about 16,000 hands, 1 bb/100 about
64,000 hands, 0.5 bb/100 about 255,000 hands. One month's cap of 50,000 hands gives about 1.1
bb/100 [derived from G5 and G2].

### Leaderboard on 26 Nov 2026 [G5]

Only one bot of the 100 listed has a positive luck-adjusted win rate: "Pokermon", +2.08 bb/100
with standard error 0.95 over 50,000 hands (95% interval lower end +0.22). Best LLM entries:
"GPT-6 (Low Reasoning)" −5.40 ± 2.41 over 10,000 hands; "GPT-6 (XHigh Reasoning)" −8.79 ± 1.99.
In the paper (5,000 hands each, as of March 2026), the best LLM was GPT-5.3 at Extra High
reasoning, −16 ± 3 bb/100, and an always all-in bot lost 380.6 ± 4.3 [G1, Table 2]. The snapshot
is saved in `runs/benchmarks_2026-11-26/gtowizard_leaderboard.json`, with the API spec next to it.

### The 19.4 bb/100 claim against Slumbot

What the paper says: "In 2022, GTO Wizard AI demonstrated its superiority by defeating Slumbot,
the 2018 ACPC champion, by a margin of 19.4 ± 4.1 bb/100 over 150 000 hands" [G1, section 3 and
abstract]. 19.4 bb/100 is 194 mbb/g.

What it does not say: whether the ± is a standard error, a standard deviation or a 95% interval;
whether the match was luck-adjusted; which GTO Wizard AI version played; or where the hand
histories are [G1]. The claim comes only from GTO Wizard's own authors. I found no independent
replication.

How it sits next to other results: even if the ± were a 95% interval it would be clearly
significant. The size fits Supremus's 176 ± 44 mbb/g (one standard error) against Slumbot over
150,000 hands [P4] and AlphaHoldem's 111.56 ± 16.06 mbb/h (95% interval) [P5]. Verdict: the number
is quoted correctly from arXiv 2603.23660 and is plausible, but it is a self-reported result
without a stated error definition.

## 2. Slumbot API

### What it is

Slumbot is Eric Jackson's abstraction-based bot, winner of the 2018 ACPC [P1, section 6.2; G1].
Its strategy is a precomputed lookup table with no real-time search; computing it took about
250,000 core hours and 2 TB of RAM [P1, section 6.2]. The site's current bot version is from
February 2017, patched on 19 Mar 2017 for a river weakness; the API was added with the backend
rewrite of 23 May 2021; leaderboards were cleared on 7 Dec 2022 after exploits were found [S2].
The open-source Slumbot2019 code is on GitHub under the MIT license [S3]; it is the CFR code, not
the trained strategy files.

### Game format

Blinds 50 and 100, stacks 200 big blinds (20,000 chips), stacks reset after each hand. You start in
the big blind, and the site advises an even number of hands so you get the button exactly half the
time [S1]. Actions are strings such as `b200c/kk/kk/kb200`, where a bet amount is the chips put in
on that street only [S1].

### Access, terms and rate limits

- HTTPS POST with JSON bodies to slumbot.com: `/slumbot/api/new_hand`, `/slumbot/api/act`,
  `/slumbot/api/login`. No key: the first `new_hand` call can omit the token, and every response
  carries a token to send next time [S1]. Logging in (with a username registered on the website) is
  needed for your hands to count toward the leaderboards [S1].
- Terms of use: none published. The site's API page, help and news text have no terms and no
  rate limits [S1, S2]. The only stated limit is a five-minute timeout per action on the website,
  from Feb 2017 [S2]. Read the absence of terms as "be polite": one hand at a time, no parallel
  hammering, and ask Eric Jackson (issues on github.com/ericgjackson/slumbot2019, which the site
  names for feedback [S2]) before a large run.
- Luck: the API returns raw chips won per hand [S1]. The website's Stats page shows "baseline"
  numbers (your result minus what Slumbot got playing itself with your cards in your seat, a
  duplicate-style comparison) and confidence intervals [S2]. Slumbot's strategy is not public, so
  AIVAT against it is not possible; an all-in expected value adjustment is (Supremus used it [P4]).
- Leaderboards exist for 500, 1,000, 5,000, 10,000, 20,000 and 100,000 hands, raw and baseline
  [S1, from the site's own page code].

### Published results against Slumbot

| Bot | Result vs Slumbot | ± means | Hands | Luck adjustment | Source |
| --- | --- | --- | --- | --- | --- |
| Baby Tartanian8 (ACPC 2016 winner) | +36 ± 12 mbb/g | not stated | not stated | not stated | [P1, section 6.2] |
| Modicum | +11 ± 9 mbb/g | 95% interval | not stated | AIVAT | [P1, Table 1] |
| ReBeL | +45 ± 5 mbb/g | one standard deviation | not stated | AIVAT | [P2, Table 1] |
| Supremus | +176 ± 44 mbb/g | one standard error | 150,000 | all-in expected value | [P4, section 4.4] |
| DeepStack reimplementation (Supremus authors) | −63 ± 40 mbb/g | one standard error | 150,000 | all-in expected value | [P4, section 3] |
| AlphaHoldem | +111.56 ± 16.06 mbb/h | 95% interval | 100,000 | not stated | [P5, Table 3] |
| OpenStack (AlphaHoldem's DeepStack reimplementation) | +103.08 mbb/h | none given | 100,000 | not stated | [P5] |
| Student of Games (vs Slumbot2019) | +7 ± 3 mbb/hand | text says 95% interval, table says one standard error | 3.1M matches | AIVAT | [P6, Table 2] |
| GTO Wizard AI | +19.4 ± 4.1 bb/100 (194 mbb/g) | not stated | 150,000 | not stated | [G1] |

Notes: ReBeL's table lists Modicum as 11 ± 5 (one standard deviation), which matches Modicum's
own ±9 at 95% [P1, P2]. "Slumbot" is not one fixed opponent across these papers: Modicum names the
2018 ACPC winner [P1], Supremus the slumbot.com bot [P4], Student of Games the open-source
Slumbot2019 [P6].

## 3. Claim checks

### Modicum (arXiv 1805.08195, NeurIPS 2018) [P1]

| Claim | Paper | Verdict |
| --- | --- | --- |
| 4 cores and 16 GB | "two prior top agents using only a 4-core CPU and 16 GB of memory" (abstract). The strategy was computed with 16 GB of RAM; play used "just a 4-core CPU" (section 6.2) | Correct |
| About 700 core hours | Blueprint solved by Monte Carlo CFR "for 700 core hours" (section 6.2). Section 7 says Modicum needed "less than 1,000 core hours" for its value mapping and "less than 1,000 core hours of computation" overall | Correct for the blueprint; say "700 core hours for the blueprint, under 1,000 in total" |
| About 20 seconds per hand | "an average of 20 seconds for an entire hand of poker" (section 6.2) | Correct (average for a whole hand, not per decision) |
| Beat Baby Tartanian8 and Slumbot | +6 ± 5 and +11 ± 9 mbb/g, 95% intervals, AIVAT (Table 1). Without real-time solving the blueprint lost: −57 ± 13 and −11 ± 8 | Correct. Both margins are small, about 1 bb/100 or less |

Context from the same section: Baby Tartanian8 took about 2 million core hours and 18 TB of RAM;
Slumbot about 250,000 core hours and 2 TB [P1, section 6.2].

### Pluribus (Science, 2019) [P3]

| Claim | Paper | Verdict |
| --- | --- | --- |
| 64 cores for 8 days | "computed in 8 days on a 64-core server" | Correct |
| About 12,400 core hours | "a total of 12,400 CPU core hours" (8 × 24 × 64 = 12,288, so about 8 days of the full machine) | Correct, exact figure |
| Under 512 GB | "It required less than 512 GB of memory" | Correct |

Also in the paper: about $144 "at current cloud computing spot instance rates" (2019); play ran on
two Intel Haswell E5-2695 v3 CPUs with under 128 GB, at about 20 seconds per hand against copies of
itself; the blueprint size was chosen to fit 128 GB in play [P3].

### DeepStack (Science, 2017)

Claim: never shown to beat earlier top bots.

- Modicum's authors write that DeepStack "was never shown to defeat prior top AIs even though it
  used over 1,000,000 core hours" [P1, section 7]. DeepStack's own paper reports "over 175 core
  years" (about 1.5 million core hours, on 6,144 cores) to generate and solve the training data
  for its turn network, plus half a GPU year for the flop
  network [P7, supplement].
- DeepStack's paper evaluated against 33 professionals (44,852 games, 486 mbb/g after AIVAT) and
  against local best response, not against other bots. Its supplement explains why: Act1 and
  Slumbot tied head to head (within 20 mbb/g) yet differed by 1,300 mbb/g in local best response,
  so they used local best response instead [P7].
- Reimplementations disagree: the Supremus authors' DeepStack reimplementation lost to Slumbot by
  63 ± 40 mbb/g over 150,000 hands [P4]; AlphaHoldem's reimplementation (OpenStack) won 103.08
  mbb/h over 100,000 hands, with no error bar [P5].

Verdict: correct for DeepStack itself. Add "a reimplementation later lost to Slumbot in one paper
and beat it in another".

A side finding: AlphaHoldem's abstract says it beat DeepStack with statistical significance
[P5, abstract], but its own Table 3 shows +16.91 ± 22.34 mbb/h at 95% against OpenStack, an
interval that includes zero [P5, Table 3]. That opponent was a reimplementation, not DeepStack.

## 4. Renting the compute

### Cores versus vCPUs

Core hours in the papers are cores. Cloud vCPUs are often hardware threads, half a core:

- One vCPU is one physical core on AWS C7a, R7a, C8a and R8a (AMD, no SMT) [C2] and on AWS
  Graviton (one thread per core in AWS's table) [C3], and on GCP C4A (Arm Axion: "Each vCPU is
  equivalent to an entire core") [C5].
- One vCPU is one thread on GCP C4D and similar x86 series ("two threads per core") [C5]. A
  64-vCPU C4D is 32 cores, so it is left out below.
- Hetzner's largest AX server, the AX162, has an AMD EPYC 9454P: 48 cores, 96 threads [C9, C10].
  No Hetzner AX server has 64 cores, so it is listed at 48 cores and runs proportionally longer.

The 2015 Haswell cores in the Pluribus paper are slower than these, so the totals below are on the
safe side if the code scales the same way. Arm machines (Graviton, Axion) need the engine built for
Arm.

### Hourly prices (USD, Linux, no tax)

AWS: us-east-1, from instances.vantage.sh, which republishes AWS price data, read 26 Nov 2026
[C1]. GCP: us-central1, from gcloud-compute.com, data last updated 22 Nov 2026 [C4]. Hetzner:
Falkenstein, Nuremberg or Helsinki, from Hetzner's own price API, with the required primary IPv4
included, excluding VAT, read 26 Nov 2026 [C7]. Spot prices move hour to hour; these are one
reading.

64 cores, about 128 GB:

| Machine | CPU | Cores | RAM | On-demand $/h | Spot $/h |
| --- | --- | --- | --- | --- | --- |
| AWS c7a.16xlarge | AMD EPYC Genoa | 64 | 128 GiB | 3.284 | 1.219 |
| AWS c8a.16xlarge | AMD EPYC Turin | 64 | 128 GiB | 3.449 | 1.050 |
| AWS c8g.16xlarge | Graviton4 (Arm) | 64 | 128 GiB | 2.552 | 0.992 |
| GCP c4a-highcpu-64 | Axion (Arm) | 64 | 128 GB | 2.4243 | 1.3146 |
| Hetzner AX162-1 | AMD EPYC 9454P | 48 | 128 GB | 1.1602 (€0.984) + $359 setup | none |

64 cores, about 512 GB:

| Machine | CPU | Cores | RAM | On-demand $/h | Spot $/h |
| --- | --- | --- | --- | --- | --- |
| AWS r7a.16xlarge | AMD EPYC Genoa | 64 | 512 GiB | 4.869 | 1.009 |
| AWS r8a.16xlarge | AMD EPYC Turin | 64 | 512 GiB | 5.112 | 3.036 |
| AWS r8g.16xlarge | Graviton4 (Arm) | 64 | 512 GiB | 3.770 | 1.244 |
| GCP c4a-highmem-64 | Axion (Arm) | 64 | 512 GB | 3.7722 | 2.0461 |
| Hetzner AX162-3 | AMD EPYC 9454P | 48 | 512 GB | 3.0432 (€2.5625) + $949 setup | none |

Hetzner details: the AX162-1 is $724 (€614) a month with a $359 (€304) setup fee; the AX162-3 is
$1,899 (€1,599) a month with $949 (€799) setup [C7]. Hetzner's billing docs say hourly charges
never exceed the monthly price [C8]. Older blog prices are out of date: a Nov 2024 comparison listed the AX162 from €199 a
month [C11], against €614 now [C7].

### Totals

A 700-core-hour run (Modicum-sized heads-up blueprint) is 700 / 64 = 10.9 hours on 64 cores, or
15 hours on Hetzner's 48 cores (rounded up to whole hours). A 12,400-core-hour run (Pluribus-sized
six-max blueprint) is 193.75 hours (8.1 days) on 64 cores, or 259 hours (10.8 days) on 48 cores.
AWS and GCP bill these machines by the second, so no rounding [C1, C4]. Totals = hours × hourly
price, plus Hetzner's setup fee. Storage and network are left out.

| Machine | RAM | 700 core h, on-demand | 700 core h, spot | 12,400 core h, on-demand | 12,400 core h, spot |
| --- | --- | --- | --- | --- | --- |
| AWS c7a.16xlarge | 128 GiB | $36 | $13 | $636 | $236 |
| AWS c8a.16xlarge | 128 GiB | $38 | $11 | $668 | $203 |
| AWS c8g.16xlarge | 128 GiB | $28 | $11 | $494 | $192 |
| GCP c4a-highcpu-64 | 128 GB | $27 | $14 | $470 | $255 |
| Hetzner AX162-1 | 128 GB | $376 | none | $659 | none |
| AWS r7a.16xlarge | 512 GiB | $53 | $11 | $943 | $195 |
| AWS r8a.16xlarge | 512 GiB | $56 | $33 | $990 | $588 |
| AWS r8g.16xlarge | 512 GiB | $41 | $14 | $730 | $241 |
| GCP c4a-highmem-64 | 512 GB | $41 | $22 | $731 | $396 |
| Hetzner AX162-3 | 512 GB | $995 | none | $1,737 | none |

Reading the table:

- Modicum needed 16 GB [P1], so the heads-up run fits the 128 GB machines: about $27 to $38
  on-demand, $11 to $14 spot.
- Pluribus needed under 512 GB [P3], so the six-max run needs the 512 GB row: about $730 to $990
  on-demand, $195 to $590 spot. Hetzner costs more here only because of the $949 setup fee; its
  hourly part is $788.
- Spot machines can be taken back with two minutes' warning on AWS [C6] and with 0 to 120 seconds'
  notice (your choice) on GCP [C12]. An 8-day run on spot needs regular checkpoints of the regret
  tables and a restart script. GCP says spot discounts reach up to 91% [C12].
- Pluribus's own estimate was about $144 at 2019 spot prices [P3]; today's spot readings above are
  higher.
- Hetzner is a monthly dedicated server with hourly billing: worth it only if the machine will stay
  busy for weeks, since the setup fee is paid each time.

## Sources

GTO Wizard
- [G1] Provost, Ilenic, Solinas, Beardsell. "GTO Wizard Benchmark". arXiv 2603.23660, 24 Mar 2026.
  https://arxiv.org/abs/2603.23660 (abstract; sections 2, 3, 4.1, 6.3, 6.4; Table 2)
- [G2] GTO Wizard Benchmark site, About and FAQ. https://benchmark.gtowizard.com/ (read 26 Nov 2026)
- [G3] GTO Wizard API and Leaderboard Terms of Service, last updated 21 Feb 2026.
  https://benchmark.gtowizard.com/terms/ (read 26 Nov 2026)
- [G4] Researcher API spec. https://researcher.gtowizard.com/openapi.json and
  https://researcher.gtowizard.com/docs (read 26 Nov 2026; copy in
  `runs/benchmarks_2026-11-26/gtowizard_openapi.json`)
- [G5] Live leaderboard, `GET https://researcher.gtowizard.com/leaderboard?game_name=HUNL%20200BB&limit=100&min_hands=1`,
  read 26 Nov 2026 18:06 UTC (copy in `runs/benchmarks_2026-11-26/gtowizard_leaderboard.json`)
- [G6] Client code. https://github.com/gtowizard-ai/researcher-api-client
- [G7] PokerListings, "GTO Wizard AI Beat All Major LLMs in Poker" ("In 2023, GTO Wizard acquired ground-breaking Ruse AI").
  https://www.pokerlistings.com/news/gto-wizard-ai-beat-all-major-llms-in-poker-is-the-game-over
- [G8] PokerNews, "GTO Wizard AI Outperforms GPT-5 and Grok 4 in New Benchmark", 13 Apr 2026.
  https://www.pokernews.com/news/2026/04/gto-wizard-ai-outperforms-gpt-5-and-grok-4-in-new-benchmark-51020.htm
- [A1] Burch, Schmid, Moravčík, Bowling. "AIVAT". arXiv 1612.06915. https://arxiv.org/abs/1612.06915

Slumbot
- [S1] slumbot.com, API tab, and https://slumbot.com/sample_api.py (read 26 Nov 2026)
- [S2] slumbot.com, News and Help tabs (entries dated 3 Feb 2017 to 19 Jul 2025, read 26 Nov 2026)
- [S3] https://github.com/ericgjackson/slumbot2019 (MIT license)

Papers
- [P1] Brown, Sandholm, Amos. "Depth-Limited Solving for Imperfect-Information Games" (Modicum).
  NeurIPS 2018. https://arxiv.org/abs/1805.08195 (abstract, sections 1, 6.2, 7, Table 1, appendix A)
- [P2] Brown, Bakhtin, Lerer, Gong. "Combining Deep Reinforcement Learning and Search for
  Imperfect-Information Games" (ReBeL). https://arxiv.org/abs/2007.13544 (Table 1)
- [P3] Brown, Sandholm. "Superhuman AI for multiplayer poker" (Pluribus). Science 365, 2019.
  https://noambrown.github.io/papers/19-Science-Superhuman.pdf
- [P4] Zarick, Pellegrino, Brown, Banister. "Unlocking the Potential of Deep Counterfactual Value
  Networks" (Supremus). https://arxiv.org/abs/2007.10442 (sections 3, 4.4, 5)
- [P5] Zhao et al. "AlphaHoldem". AAAI 2022.
  https://ojs.aaai.org/index.php/AAAI/article/view/20394 (abstract, Table 3 and text)
- [P6] Schmid et al. "Student of Games". https://arxiv.org/abs/2112.03178 (Table 2 and text)
- [P7] Moravčík et al. "DeepStack". Science 356, 2017, with supplement.
  https://arxiv.org/abs/1701.01724

Prices and hardware
- [C1] instances.vantage.sh pages for c7a, c8a, c8g, r7a, r8a, r8g .16xlarge, e.g.
  https://instances.vantage.sh/aws/ec2/c7a.16xlarge (us-east-1, read 26 Nov 2026)
- [C2] AWS instance pages: "Every vCPU on a C7a instance is a physical CPU core"; same wording on
  the R7a, C8a and R8a pages. https://aws.amazon.com/ec2/instance-types/c7a/ (and /r7a/, /c8a/, /r8a/)
- [C3] AWS EC2 instance type specifications (Graviton rows show 1 thread per core; m8g.16xlarge is
  64 vCPUs, 64 cores). https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html
- [C4] gcloud-compute.com, us-central1 pages, e.g. https://gcloud-compute.com/us-central1/c4a-highmem-64.html
  (last update 22 Nov 2026)
- [C5] Google Cloud, general-purpose machine family docs.
  https://docs.cloud.google.com/compute/docs/general-purpose-machines
- [C6] AWS, Spot Instance interruption notices.
  https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-instance-termination-notices.html
- [C7] Hetzner AX162 page and configurator, https://www.hetzner.com/dedicated-rootserver/ax162/,
  and its price API: https://website-price-api.hetzner.com/api/v1/products/ROBOT_1724+ROBOT_1266
  (AX162-1 with IPv4) and https://website-price-api.hetzner.com/api/v1/products/ROBOT_1726+ROBOT_1266
  (AX162-3 with IPv4), read 26 Nov 2026
- [C8] Hetzner, billing system. https://docs.hetzner.com/general/others/new-billing-model/ (changed 1 Oct 2026)
- [C9] Hetzner AX162 product details: "AMD EPYC 9454P incl. Simultaneous Multithreading" [C7]
- [C10] EPYC 9454P with 48 cores: Puget Systems parts page https://pugetsystems.com/parts/CPU/AMD-EPYC-9454P-2-75GHz-48-Core-290W-15144 ;
  96 threads: WikiChip on the EPYC 9454 family https://en.wikichip.org/wiki/amd/epyc/9454
- [C11] Achromatic, "Hetzner Server Comparison", 4 Nov 2024. https://www.achromatic.dev/blog/hetzner-server-comparison
- [C12] Google Cloud, Spot VMs. https://docs.cloud.google.com/compute/docs/instances/spot
