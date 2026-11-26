# What the books and papers say, and where PokerScribe uses it

Principles in our own words, with the status of each in the engine. "Rule" means it is in the
advice code; "setting" means it is a switch in the tuning table that stays off until paired tests
justify it (see `experiments.md`); "planned" means a phase of the research roadmap.

## The Mathematics of Poker (Chen and Ankenman)

| Principle | Status |
| --- | --- |
| Call when your chance to win is above the price: call / (pot + call) | Rule (pot odds on every call) |
| A bet's value adds the times they fold: EV = fold share x pot + call share x (equity x (pot + 2 x bet) - bet) | Setting `ev_sizing` |
| Half-street game: a balanced bettor using s times the pot bluffs s/(1+2s) of its bets (one third at pot size); the caller defends 1/(1+s) of its range | Setting `balanced_river`; planned as a solver check (Phase 2) |
| Checked to on the river in position (no raise possible): bet when you beat more than half of the hands that would call | Setting `river_ip_call_share` |
| Polarized ranges over several streets: grow the pot by the same fraction each street so the stacks go in by the river (geometric sizing); very deep stacks cap it because worse hands stop calling | Setting `geometric` |
| Jam-or-fold is close to optimal up to about 10 to 11 big blinds heads-up (12 to 13 out of position later); ranges are far looser than intuition; equity against the calling range matters more than against random hands | Setting `push_chart` (measured +0.6 +/- 0.9, stays off) |
| Hand reading and opponent statistics are Bayesian: start from a prior, update with evidence, small samples shrink toward the prior | Rule (profiles start from a prior); planned in full (Phase 3) |

## Modern Poker Theory (Acevedo)

| Principle | Status |
| --- | --- |
| Never fold when checking is free | Rule |
| Equity buckets by hand-versus-range equity: strong 75%+, good 50 to 75%, weak 33 to 50%, trash under 33% | Setting `bucket_sizing` |
| Ranges full of good-but-not-great hands bet small and often; polarized ranges bet big | Setting `bucket_sizing`, `small_bet_from` |
| Single-street sizes by stack-to-pot ratio: at 1 or less all in; 1 to 2 pot or all in; around 3 three quarters; 5 to 10 three quarters, overbets only with the nuts | Planned (solver, Phase 2) |
| A third of the pot is a sound default continuation bet when unsure, in short and medium stacks | Rule (dry boards) |
| Size up against players who call a lot; bet small and often against players who fold or raise a lot | Setting `ev_sizing` (profile shift) |
| Don't bluff players who call everything; don't try to fold out top pair from recreational players | Rule (no semi-bluffs or stabs into stations) |
| Multiway pots: play passively, bet draws only when they are to the nuts | Planned |
| Before betting a medium hand, ask what a raise would do to it; if it hates a raise and one is likely, check | Planned |
| Out of position as the preflop caller, check nearly everything on boards that favour the raiser | Setting `oop_lead` |
| River calls: defend near 1/(1+s); always call with hands that beat their value range; don't call bluff-catchers against players with too few bluffs | Rule (betting-range narrowing); blockers come from card removal in the equity engine |

## Papers

| Paper | Idea | Status |
| --- | --- | --- |
| Zinkevich et al. 2007, CFR | Minimise counterfactual regret at every decision; the average strategy approaches equilibrium in two-player zero-sum games | Planned: river solver (Phase 2) |
| Lanctot et al. 2009, Monte Carlo CFR | Sample chance or opponent actions so each iteration is cheap; external and outcome sampling | Planned: blueprint (Phase 4) |
| Brown and Sandholm 2019, Discounted/Linear CFR; Tammelin 2014, CFR+ | Weight later iterations more; converges much faster in practice | Planned (Phase 2) |
| Brown et al. 2019, Deep CFR | Neural networks replace regret tables, no hand-made abstraction | Planned only if Phase 4 shows abstraction limits strength |
| Moravcik et al. 2017, DeepStack; Brown and Sandholm 2017, Libratus | Search at decision time; nested safe subgame solving; patch the blueprint where opponents find holes | Planned (Phases 2 and 4) |
| Brown and Sandholm 2019, Pluribus | Six-player: Linear MCCFR blueprint (12,400 core hours) plus depth-limited search with four continuation strategies; 1 to 33 s per search on two CPUs | The Phase 4 target |
| Brown et al. 2020, ReBeL | Search and self-play over public belief states; provable in two-player zero-sum only | Phase 5 candidate |
| Burch et al. 2018, AIVAT | Unbiased luck adjustment using value estimates and known strategies; cut the standard deviation by 85% (44 times fewer hands) | Tool (Phase 1): `tools/luck.py` corrects the flop, turn and river with exact checked-down and all-in values and frozen weights; the app is deterministic, so its choices need no correction; the bots' choices and the hole-card deal are not corrected |
| Lisy and Bowling 2017, local best response | Cheap lower bound on exploitability; abstraction-based bots lost over 3 big blinds per hand to it | Partly (Phase 1): `tools/weakness.py` tries every other move at each of the app's decisions against our bots and ranks the spots where one wins more; an exploiter bot that plays against the app is still to do |
| Johanson et al. 2007 and 2009, restricted Nash and data-biased responses; Ganzfried and Sandholm, safe exploitation | Exploit an opponent model while bounding what a wrong model can cost | Planned (Phase 3) |
