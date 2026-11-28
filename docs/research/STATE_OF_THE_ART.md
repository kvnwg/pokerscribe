# State of the art: what the strongest poker AIs did, and what we do

28 Nov 2026. What Libratus, Modicum, Pluribus, DeepStack and the agents after them did to get
strong, including details that are only in the supplements and the thesis, compared with this
repo at commit 94a80d8, with the gaps ranked. Methods only: no outside code was read or copied.
Sources are at the end; [PS] means the Pluribus supplement, and so on. 1 mbb/g is 0.1 bb/100.

Nothing here changes code, a gate or a rule. Items marked **Kevin** touch a gate, a rule or the
roadmap, so they are proposals for him to decide.

## Where the bar is

Head to head against Slumbot (2018 ACPC winner, a large blueprint with no search), as each paper
reports it. Slumbot versions and error conventions differ, so treat this as a rough ladder.

| Agent | Method | Against Slumbot | Source |
| --- | --- | --- | --- |
| GTO Wizard AI | Real-time solving with deep learning, self-play | +194 ± 41 mbb/g (19.4 bb/100, 150,000 hands) | [G] |
| Supremus | DeepStack-style value networks at the end of every round, DCFR+ | +176 ± 44 (one SE) | [SU] |
| ReBeL | Self-play over public belief states, value and policy networks | +45 ± 5 | [R] |
| Modicum | Blueprint plus depth-limited search (our Phase 7 design) | +11 ± 9 (95%) | [M] |
| Student of Games | Growing-tree CFR with learned values | +7 ± 3 | [SG] |
| DeepStack, reimplemented | Continual re-solving, flop and turn networks | -63 ± 40 | [SU] |
| Baby Tartanian8 | Large blueprint, purified, no search | +36 ± 12 | [M] |

Pluribus was never measured against Slumbot (six-max). Against elite pros it won 48 ± 25 mbb/g
(5 humans, 1 AI) and 32 ± 15 (1 human, 5 AIs) after AIVAT [P].

Two things stand out. In heads-up, the two biggest published margins come from value-network
re-solving with no blueprint abstraction (Supremus, GTO Wizard AI), not from blueprint plus
search. And details decide it: the same DeepStack method lost to Slumbot until Supremus changed
the solver and the training data [SU].

## 1. Techniques compared

Impact is for the heads-up agent unless the phase is 8. Cost: low is days of work and under $10
of compute; medium is a week or two, or tens of dollars; high is a month or more, or GPUs.

| Technique | Who | Source | We do it? | Impact | Cost | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| External-sampling Linear MCCFR: discount every 10 min for the first 400 min, pruning in 95% of iterations below -300M after 200 min, never on the last round or terminal actions, regret floor -310M, 4-byte regrets | Pluribus | [PS] | Yes: `cfr`, `blueprint`, `runs/phase6/trainer.json` | (done) | | 6 |
| Regrets allocated only for action sequences met (413M of 665M) | Pluribus | [PS] | Yes: the index grows (93M of 97M sets met) | (done) | | 6 |
| Average strategy kept only preflop; after it, the average of current-strategy snapshots taken every 200 min after the first 800, saved to disk. "Reduced memory usage by nearly half" and made iterations cheaper | Pluribus | [PS] | No: the average on every street (`blueprint/src/file.rs`) | Low heads-up (the average is the one with guarantees in two-player zero-sum); medium for six-max (memory, speed) | Low | 8 |
| Lossless preflop, 169 classes | All | [PS], [M] | Yes | (done) | | 5 |
| Postflop buckets: Pluribus 200 a round (six-max); Modicum 30,000; Libratus none on the flop, 2.5M turn, 1.25M river | Pluribus, Modicum, Libratus | [PS], [M], [L] | 200 a street | Medium to high: k200 beat k50 by 3.6 bb/100 head to head at 100bb (`experiments.md`), and every top heads-up bot used far more | Medium (memory grows with buckets; 1,000 is about 35 GB) | 7 (**Kevin**: a new blueprint) |
| Potential-aware buckets with earth mover's distance, OCHS on the river | Pluribus search, Libratus | [PS], [GS14], [J13] | Yes: `abstraction` | (done) | | 5 |
| Search buckets for later rounds built per flop (500 a round) | Pluribus | [PS] | No: leaf tables use the blueprint's global 200 | Medium | High | Later |
| Bet menu of 1 to 14 sizes, picked by hand from what earlier versions used with real probability; preflop finest, flop coarser, turn and river at most 3 | Pluribus | [PS] | Partly: `rich` (8 opens preflop, 3 sizes plus all in after) | Medium (Phase 5: sizes, not buckets, moved LBR) | Low | 7 |
| Bet sizes early in the tree found by parameter optimization | Libratus | [L] | No | Low to medium | High | Later |
| Randomized pseudo-harmonic translation of off-tree bets | Pluribus, Libratus early rounds | [PS], [PH] | Yes: `abstract_game`, a hash draw | (done) | | 5 |
| Self-improvement: each night, solve responses to the opponents' most-used off-tree sizes (gaps scored by frequency and distance, the pseudo-harmonic midpoint of the top two gaps) and add them to the blueprint. By the end "roughly half of all the hands" used it | Libratus | [L], [T] | No | Medium to high preflop (search covers the postflop) | Medium | 7 (**Kevin**: whose sizes) |
| Postprocessing: drop low-probability actions (purification, thresholding). Libratus blueprint went from -8 ± 15 to +18 ± 21 against Baby Tartanian8 | Libratus, Baby Tartanian8 | [L], [T] | No | Medium against fixed bots; raises exploitability | Low | 7 |
| Search on every postflop decision, for every hand in the range | Pluribus, Modicum, Libratus (from the turn) | [PS], [M], [L] | Yes: `search` | (done) | | 7 |
| Preflop search: Pluribus searches when a raise is more than one big blind off every blueprint size (four or fewer players); Modicum re-solves the whole preflop with the new size, caches it, and values its leaves with 10 self-generated opponent strategies | Pluribus, Modicum | [PS], [M] | No: preflop is the blueprint plus translation | High against Slumbot and the GTO Wizard Benchmark, which bet any size | Medium | 7 |
| Depth limit: end of the round on rounds 1 and 2, then to the end of the game (Modicum); a two-player flop solved to the end of the game with 500 buckets later (Pluribus) | Modicum, Pluribus | [M], [PS] | Yes, as Modicum: flop to its end, turn and river to the end | (done) | | 7 |
| At a leaf, both players choose among 4 continuation strategies. Pluribus: the Modicum way, where only the opponent chooses, "makes the searcher relatively defensive/conservative" | Pluribus | [PS] | No: only the opponent chooses (`search/README.md`) | High: our search was -2.5 ± 4.6 bb/100 against its own blueprint, which fits | Medium (leaf tables need searcher lanes: 16 pairs, not 7) | 7 |
| Bias factor: 5 (Pluribus), 10 (Modicum); Modicum's round-1 set was 10 self-generated best responses | Pluribus, Modicum | [PS], [M] | 5. `search/README.md` says 5 is Modicum's; it is Pluribus's | Low | Low | 7 |
| "Weaken" continuation strategies that beat the blueprint against the blueprint, so the searcher isn't over-cautious | Modicum | [M] | No | Medium | Low | 7 |
| Re-solve from the start of the round; freeze own earlier actions for the actual hand only, opponent's not at all | Pluribus | [PS] | Partly: frozen for every combo | Low to medium | Low | 7 |
| Safe nested solving (Reach, Maxmargin, estimated alternative payoffs). Libratus used it for every subgame; Modicum on turn and river re-solves after the first. Unsafe "did substantially worse" in one test game with 30,000 buckets | Libratus, Modicum | [SN], [L], [M], [T] | No: unsafe, as Pluribus | Medium | Medium | 7 |
| Which strategy to play from a solve: Pluribus the final iteration (beliefs updated with the average); DeepStack averages only the second half of its iterations (the last 20 of 1,000 preflop); Modicum drops the first 50%; ReBeL a random iteration (provably safe) | Pluribus, DeepStack, Modicum, ReBeL | [PS], [DS], [M], [R] | No: the full DCFR average (`subgame/src/cfr.rs`, `search/src/flop.rs`) | Medium | Low | 7 |
| Change own bet sizes by a random 0 to 8% per hand, so opponents can't key on them | Libratus | [T] | No | Low against bots | Low | Later |
| Off-tree opponent action added at its node, re-solve from the root | Pluribus, Modicum, Libratus | [PS], [M], [L] | Yes | (done) | | 7 |
| Counterfactual value networks at round ends (DeepStack: flop and turn, plus a preflop one; Supremus: every round, DCFR+, more data) | DeepStack, Supremus, GTO Wizard AI | [DS], [SU], [G] | No (shelved) | High in heads-up (the top two results) | High: GPUs; DeepStack's data took over 1M core hours [T] | Later (**Kevin**) |
| Self-play over public belief states with value and policy networks | ReBeL, Student of Games | [R], [SG] | No (shelved) | Medium (45 and 7 mbb/g against Slumbot) | High | Later (**Kevin**) |
| Model-free deep CFR: Deep CFR, DREAM, ESCHER | Research | [DC], [DR], [ES] | No | Low: no top heads-up result | High | Later |
| Faster solvers: Predictive CFR+, learned or scheduled discounting | Research | [PC], [DD], [HS] | DCFR (1.5, 0, 2) | Low to medium (more iterations in the same time) | Low | 7 |
| AIVAT luck adjustment over chance and known strategies (over 10 times fewer hands) | Pluribus, Libratus, Modicum, GTO Wizard Benchmark | [A], [P], [G] | Partly: Python tools (`tools/luck.py`, `tools/hidden.py`); the Rust arena uses duplicate deals and all-in equity | High for every gate from here on | Medium | 7 (**Kevin**: gate SEs) |
| Exploiters: LBR; approximate best response learned with search and RL | Research | [LB], [ABR] | LBR yes; learned best response no | Medium | Medium | 7, 8 |
| Six-max search: preflop only when off-tree; leaves at round end, or after the second raise on a multiway flop; unsafe search 4 times faster since most hands fold | Pluribus | [PS] | Planned | High (it is Phase 8) | | 8 |

## 2. The top 10 changes, by impact for the effort

Each is an agent change judged by rule 1 (2.5 SE, LBR, fresh seeds) unless marked **Kevin**.

1. **Let the searcher choose continuation strategies too.** Pluribus's own fix for Modicum's
   defensive play [PS]; our search neither gains nor loses against its blueprint. Next step: add
   the 9 lanes where both players deviate to `search leaf` (16 in all), let the searcher pick at
   leaves, and rerun the groundwork's head to head and LBR at 20bb. At 200bb the tables grow
   from 9.7 to about 22 GB, so check the size first.
2. **AIVAT in the Rust arena** (**Kevin**, if gate SEs are to come from it). The search agent's
   and the blueprint's strategies are known, so AIVAT can remove their action luck as well as
   the cards' [A]; the Phase 7 gate and every search A/B need it. Next step: port `tools/hidden.py`'s
   correction to `arena` for strategy agents, check it is unbiased on identical agents, and report
   the SE ratio on the groundwork's 3,000 deals.
3. **Play the final iteration, or a late average, of each solve.** Every top agent avoids the
   full average [PS], [DS], [M]. Next step: a `--play final|tail|average` setting, then search
   against search head to head and LBR `b56_14`. A day of work.
4. **Preflop search for off-tree raises.** Our preflop is translation only, the gap Pluribus and
   Modicum closed [PS], [M], and the Slumbot and GTO Wizard benchmarks use their own sizes. Next
   step: count how many preflop raises in LBR `b56_14` and a short Slumbot sample (allowed, rule
   4) are more than 1bb off the menu; then a preflop solve with the raise added, leaves at the
   flop valued from the blueprint, cached per betting line as Modicum did.
5. **Self-improvement, Libratus style** (**Kevin**: whether Slumbot's sizes may pick what we add;
   GTO Wizard hands may not, by his rule). Rule 3 allows actions as observations, not labels; only
   the sizes would be used. Next step: score the gaps in our preflop menu from LBR's and B0's
   off-tree sizes, add the pseudo-harmonic midpoint of the top two, retrain (about $5), and play
   against the current blueprint.
6. **Weaken over-strong continuation values, and try factor 10.** Modicum's correction [M]
   and its bias factor are a small change to `leaf.rs`. Next step: run with #1, as a 2 by 2.
7. **A floor on the opponent's range.** A hand the blueprint never plays that way gets weight 0
   and the search then plays the blueprint (`search/README.md`, "Not done"); against Slumbot,
   B0 or a 247 bot that is common. Next step: mix 0.5%, 2% and 5% of the street-start range back
   in, and measure against B0 and LBR.
8. **Purify or threshold the blueprint and the search output.** Libratus's blueprint gained
   about 26 mbb/g against Baby Tartanian8 this way [L]. Next step: drop actions under 5%, 10%
   and 15% and renormalize; play against the unpurified agent and check LBR, since it raises
   exploitability.
9. **A finer card abstraction for the next blueprint** (**Kevin**: a new blueprint). k200 beat
   k50 at 100bb; Modicum used 30,000 buckets and Libratus no flop abstraction [M], [L]. Next step:
   `blueprint size` for 500 and 1,000 buckets at 200bb `rich`, then train the one that fits 128 GB
   (about $10 to $40) and play it under search against today's.
10. **Safe re-solving on the turn and river**, as an option. Modicum used unsafe only for the first
    turn subgame, then Reach [M]. Next step: Reach-Maxmargin with the earlier solve's values as
    the gadget, compared with unsafe under LBR `b56_14`.

Roadmap proposals for Kevin (not in the list because they are large):

- **After Phase 7, decide whether heads-up goes the value-network route** (unshelve
  DeepStack/Supremus-style re-solving). Evidence: the two best published results [G], [SU].
- **Phase 8 should copy Pluribus's memory trick** (snapshots of the current strategy after
  preflop), not our heads-up file format.

## 3. Beyond Pluribus

Pluribus is a six-max bot; in heads-up "beyond Pluribus" means beyond Modicum and Libratus. Odds
are our guesses, stated so they can be checked.

- **Pluribus plus Libratus's self-improvement.** Brown: it "was not used in Pluribus, though using
  it likely would have led to even better performance" [T]. In Libratus half of all hands ended up
  played with it. Odds of a measurable gain on preflop sizes: about 60%.
- **Pluribus's search with the fixes it never combined**: both players choosing at leaves, a
  safe gadget where unsafe is risky, a late-iteration play rule, preflop re-solving as Modicum
  did. Each is published; no agent had all four. Odds that together they beat our Phase 7 agent by
  2.5 SE: about 50%; each alone is smaller.
- **Value networks in heads-up.** Supremus (+176) and GTO Wizard AI (+194) beat Slumbot by about
  16 times what Modicum did (+11), with different Slumbot versions [SU], [G], [M]. Cost: GPUs and
  a lot of solved training spots (DeepStack: over 1M core hours of data [T]); the DeepStack
  reimplementation lost until the details were fixed [SU]. Odds that we reach Supremus's level:
  20 to 30%. Odds that a smaller version (a learned turn-start value in place of our leaf
  tables) beats the tables: about 40%.
- **More compute than Pluribus used.** Pluribus's blueprint took 12,400 core hours [P]; our whole
  Phase 6 run was about 150 core hours and $4.67. A 1,000-bucket heads-up blueprint at Pluribus's
  scale would cost tens of dollars. Odds of a gain under search: about 50%, smaller than in the
  blueprint alone, since search covers each current street at full detail.
- **Exploiting real opponents** (**Kevin**: opponent modelling is shelved). Pluribus "plays a fixed
  strategy that does not adapt" [P]. Against weak play-money bots, a safe exploiter (Libratus's
  offensive self-improvement used a size's response only after the opponent used it 8 times in a
  row [T]) would likely win more than equilibrium play. Rule 4 limits testing to our own bots,
  and there it is close to certain to help; whether it holds on 247 is untested.
- **Better measurement.** Pluribus's 48 ± 25 mbb/g needed AIVAT on 10,000 hands [P]. With AIVAT,
  LBR and a learned best response [ABR] we can see gains Pluribus's team could not afford to
  measure. Not strength by itself, but it decides how fast everything above can be judged.

## 4. Tacit knowledge

Things the papers hint at but don't pin down, and how we'd find them.

- **What to play from a solve.** Pluribus plays the final iteration, DeepStack the last half (the last 2% preflop),
  Modicum the last 50%, ReBeL a random one; nobody published the comparison. A/B the four on our
  search (#3).
- **The bias factor and the number of continuations.** 5 in Pluribus, 10 in Modicum, "fewer than
  ten" strategies suffice [M]. Sweep 3, 5 and 10, and 4 against 7 lanes.
- **The off-tree threshold for preflop search.** Pluribus's one big blind is not explained.
  Measure LBR and head to head at 0.5, 1 and 2bb.
- **Picking the menu.** Pluribus's sizes were "decided by hand based on what raise sizes earlier
  versions of Pluribus decided to use with significant positive probabilities" [PS]: a loop of
  train, look, prune, add. Run it: train, list sizes used under some share, swap them, retrain.
- **Postprocessing thresholds.** Libratus used "a new, more robust form of postprocessing" on the
  first two rounds [L], unspecified. Sweep thresholds (#8).
- **Schedules in minutes.** Pluribus's 200, 400 and 800 minute marks are wall time on its
  machine, with no ablation. Ours are iteration counts from the Phase 5 projection; the stop
  rule's change measure is the check.
- **Opponent hands the model says can't exist.** Pluribus lets opponents "have changed strategies
  anywhere in the current betting round" [PS] but doesn't say how beliefs avoid zeros. Measure how
  often the real hand of B0 or a Slumbot sample gets weight 0, then test floors (#7).
- **Leaf value accuracy.** Modicum used 3 rollouts per leaf and found a small network 11 ± 10
  mbb/g worse [M]. Measure our leaf tables' error against exact walks on sampled leaves.
- **Two small errors to watch.** `search/README.md` credits factor 5 to Modicum (it is Pluribus's;
  Modicum used 10). And Pluribus's blueprint buckets came from k-means on domain features, while
  its search buckets were potential-aware and per flop [PS]; "Pluribus used potential-aware
  buckets" is only true of its search.

## Sources

- [P] Brown, Sandholm. Superhuman AI for multiplayer poker. Science 365, 2019.
  https://noambrown.com/papers/19-Science-Superhuman.pdf
- [PS] Its supplementary materials. https://noambrown.com/papers/19-Science-Superhuman_Supp.pdf
- [L] Brown, Sandholm. Superhuman AI for heads-up no-limit poker: Libratus beats top professionals.
  Science 359, 2018. https://noambrown.com/papers/17-Science-Superhuman.pdf
- [T] Brown. Equilibrium Finding for Large Adversarial Imperfect-Information Games. PhD thesis,
  CMU-CS-20-132, 2020. https://www.csd.cmu.edu/sites/default/files/phd-thesis/CMU-CS-20-132.pdf
- [M] Brown, Sandholm, Amos. Depth-Limited Solving for Imperfect-Information Games (Modicum).
  NeurIPS 2018. https://arxiv.org/abs/1805.08195
- [SN] Brown, Sandholm. Safe and Nested Subgame Solving for Imperfect-Information Games. NeurIPS
  2017. https://arxiv.org/abs/1705.02955
- [DS] Moravčík et al. DeepStack. Science 356, 2017. https://arxiv.org/abs/1701.01724
- [SU] Zarick et al. Unlocking the Potential of Deep Counterfactual Value Networks (Supremus).
  2020. https://arxiv.org/abs/2007.10442
- [R] Brown, Bakhtin, Lerer, Gong. Combining Deep Reinforcement Learning and Search for
  Imperfect-Information Games (ReBeL). NeurIPS 2020. https://arxiv.org/abs/2007.13544
- [SG] Schmid et al. Student of Games. Science Advances 2023. https://arxiv.org/abs/2112.03178
- [A] Burch, Schmid, Moravčík, Morrill, Bowling. AIVAT. AAAI 2018. https://arxiv.org/abs/1612.06915
- [G] GTO Wizard. GTO Wizard Benchmark. 2026. https://arxiv.org/abs/2603.23660
- [LB] Lisý, Bowling. Equilibrium Approximation Quality of Current No-Limit Poker Bots. 2017.
  https://arxiv.org/abs/1612.07547
- [ABR] Timbers et al. Approximate Exploitability: Learning a Best Response. IJCAI 2022.
  https://arxiv.org/abs/2004.09677
- [DC] Brown, Lerer, Gross, Sandholm. Deep Counterfactual Regret Minimization. ICML 2019.
  https://arxiv.org/abs/1811.00164
- [DR] Steinberger, Lerer, Brown. DREAM. 2020. https://arxiv.org/abs/2006.10410
- [ES] McAleer, Farina, Lanctot, Sandholm. ESCHER. ICLR 2023. https://arxiv.org/abs/2206.04122
- [PC] Farina, Kroer, Sandholm. Faster Game Solving via Predictive Blackwell Approachability. AAAI
  2021. https://arxiv.org/abs/2007.14358
- [DD] Xu et al. Dynamic Discounted Counterfactual Regret Minimization. ICLR 2024.
  https://proceedings.iclr.cc/paper_files/paper/2024/hash/a89331e2ecbbd9d9618bc94717a91155-Abstract-Conference.html
- [HS] Zhang, McAleer, Sandholm. Faster Game Solving via Hyperparameter Schedules. 2024.
  https://arxiv.org/abs/2404.09097
- [GS14] Ganzfried, Sandholm. Potential-Aware Imperfect-Recall Abstraction with Earth Mover's
  Distance in Imperfect-Information Games. AAAI 2014.
- [J13] Johanson, Burch, Valenzano, Bowling. Evaluating State-Space Abstractions in Extensive-Form
  Games. AAMAS 2013.
- [PH] Ganzfried, Sandholm. Action Translation in Extensive-Form Games with Large Action Spaces.
  IJCAI 2013.

Not used as evidence: Brown's talk claim that 30 s of search was worth scaling the model about
100,000 times, which we found only in secondary notes.
