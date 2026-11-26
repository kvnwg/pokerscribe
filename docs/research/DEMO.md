# Conference demo notes

Proposal, 26 Nov 2026. Not approved.

**Target:** Web Summit Vancouver 2027, 25 to 28 May 2027, Vancouver Convention Centre.
Startups apply through vancouver.websummit.com/startups.

## Ground rules

1. Everyone at the table knows they are playing an AI.
2. Not on commercial poker sites' tables, private lobbies included: their rules ban bots on every
   table (PokerStars lists bots as prohibited at all times). Same as rule 4 in `README.md`.
3. Free play: no buy-ins, no real money. Confirm with Web Summit that a poker demo is fine on the floor.

## Open question: which platform

Proposed: a poker game run by us, where the AI takes the game state straight from the game, so
nothing is misread on stage. How the screen reader reads a table is in `SCREEN_READING.md`.

## Format ideas

- Heads-up challenges: one visitor at a time against the AI.
- A screen beside the table showing the AI's range, win chance and a one-line reason per decision.
- A luck-adjusted leaderboard over the whole event, because short matches are mostly luck.
  Pluribus's result rested on 10,000 hands with luck correction.

## Strength needed by May

Phases are from the roadmap in `README.md`.

- Heads-up challenge: needs Phase 7, the blueprint with depth-limited search, to hold up against
  good players.
- Six-max (Phase 8) will not be ready by May 2027, so the demo is heads-up only.
