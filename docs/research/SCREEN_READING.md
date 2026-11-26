# How the reader reads a poker table

The order PokerScribe works through on every capture. Each step uses what the steps before it
found. Built and tested on 247 Free Poker (play money). Written 26 Nov 2026 from Kevin's notes and
wireframe.

## The steps

**1. Seats** (once per table, again if the window moves)
- Each seat has a name, a stack, a bet spot in front of it (toward the middle) and a card spot.
- Your seat is the one with face-up cards, usually bottom middle.
- Skip empty seats (dashed outline, "Empty seat", "Sit here") and sitting-out seats (no cards dealt).
- Status: done. Seats come from name and stack text; "sitting out" and "empty seat" text is recognised.

**2. Stakes**
- Blinds come only from a labelled line: "Blinds 1/2", "NL 2/4", a Stakes box.
- Numbers in names, level badges (Lv), dates, hand numbers and table numbers are never blinds.
- Confirm with the small and big blind chips posted at the start of the hand.
- Status: done. Labelled text only; posted chips on the first read of a hand.

**3. New hand or same hand** (every read)
- Signs of a new hand: a new hand number, new hole cards, an empty board, the button moved.
- Then clear last hand's bets, actions and folds.
- When in doubt it's a new hand: forgetting a card only means reading (or asking) again, but
  last hand's cards carried into this one means advice on the wrong cards.
- Status: done. The hand number ("# 357,618,379", "Hand #...") is read and never taken for an
  amount; a new number is a new hand. The board going from 3+ cards to none while you have
  cards is a new hand. One empty read followed by cards that nothing ties to the old hand (no
  board card or hole card the same, not even as a guess) is a new hand.

**4. Button and positions** (every hand)
- The D disc sits beside one seat.
- Clockwise from it: button, small blind, big blind, then the rest, skipping empty seats.
- Heads-up, the button is the small blind and acts first before the flop.
- Status: done (disc detection).

**5. Cards**
- Your two cards, then the board. The board count sets the street: 0 preflop, 3 flop, 4 turn,
  5 river. Within a hand it only grows.
- Who's still in: seats showing card backs. No cards means folded.
- Status: done. 247's deck by template, unclear cards by the Claude card reader, card backs by colour.

**6. Money**
- The bet in front of a seat is that player's total for this betting round, not the size of the
  last raise. Blinds count as bets before the flop.
- The stack under a name is chips behind, not counting the bet in front. 0 or "All-in" means all in.
- The amount by the chip pile in the middle is the pot from earlier rounds. "Total pot" is that
  plus every bet still in front of the players. When the next card comes, the bets slide into the pot.
- Status: done. The tracker works out whether the pot on screen includes the bets by checking that
  the chips add up.

**7. Whose turn**
- The running timer bar or highlight marks the player acting. One seat at a time.
- Yours: the Fold, Call, Raise (or Check, Bet) buttons appear. Boxes like "Check/Fold" or
  "Call any" mean it isn't your turn yet.
- Signals, most reliable first: your buttons; the timer bar under a plate; the glow ring around
  it; the rule (the next seat clockwise that still has cards and isn't all in).
- Buttons sit side by side in one row. Action tags on two seat plates can share a line ("Call"
  lower left, "Fold" lower right) but far apart: they are not buttons. A single button counts
  only in the bottom right corner.
- Status: done for the first three. Each seat's plate is found from its text outwards; a thin
  bright bar under it or a bright ring on both sides marks the seat acting. Only a seat that
  clearly stands out counts; two lit seats means unknown. Another seat acting and no buttons:
  not your turn (WAIT). Buttons and the timer on your seat strengthen each other. Not done: the
  rule-based prediction as a check.

**8. What you face**
- To call = the biggest bet in front of anyone minus your own bet. The Call button shows the same number.
- Check offered means nothing to call: never fold.
- "Raise to" is your total after the raise, not the amount added. The slider and Amount box are
  your pending choice, never a bet on the table.
- Status: done.

**9. What changed since the last read**
- Who put chips in and how much (new bet minus old bet, or the drop in their stack), who folded,
  whether a card came. That is the story of the hand ("UTG raised to 6, the button called"), and the
  decision needs it.
- Status: done. The tracker infers it from changes between reads.

**10. Does it add up** (before any advice)
- Total pot = Pot + all bets in front.
- Call amount = biggest bet minus your bet.
- Two different hole cards, none of them on the board, no card shown twice.
- The board didn't lose cards within the hand.
- Chips are conserved within a hand: stacks + bets + pot stay the same total.
- If anything fails, read again instead of advising. Never all-in on a stack it couldn't read.
- Status: partly. Chips conserved and no all-in on an unread stack are done. The Total pot and
  Call amount checks don't yet stop advice.

**11. Decide.**

## Example layout (Kevin's wireframe)

| Element | Where | What it means | Trap |
| --- | --- | --- | --- |
| Filled green bar | Under the acting player's name | That seat is acting; the fill shrinks with the clock | Only one at a time |
| Outline bar | Under every other seat | Not acting | |
| Chip and amount | In front of each seat | That player's bet this round | Not the size of the last raise |
| Pot | Chip pile, middle | Chips from earlier rounds | |
| Total pot | Wide pill, top middle | Pot plus the bets in front | Must equal Pot + bets |
| Stakes | Centre | Blinds, and ante if any | The only place blinds come from |
| D | Beside one seat | Dealer button | Moves every hand |
| Two card slots on the photo | Each seat | Hole cards; card backs for opponents | No cards = folded |
| Name and Stack | Under the photo | Chips behind | Doesn't include the bet in front |
| Lv | Beside the photo | Level badge | Never chips |
| Dashed outlines | Empty seat, its bar and bet slot | No player | Skip |
| Fold, Call X, Raise to Y | Action panel | Your turn; X = what you owe; Y = your total after raising | Check offered = never fold |
| Min, 2.5x, 3x, 4x, Max | Above the slider | Size presets; Max = all-in | |
| Slider and Amount | Action panel | Your pending choice | Never a bet on the table |
| Menu, icons | Bottom left | Nothing | Ignore |

Not in the wireframe but on every real table: the board, the hand number, a last-action tag per
seat (Check, Call, Raise, Fold, All-in), side pots and the showdown reveal.

## Signals by element (from the annotated table guide, 26 Nov)

| Element | Tells you | Watch out for | Status |
| --- | --- | --- | --- |
| Header | Table, game, stakes | Stakes without "Blinds" are not used: blinds come from the chips | done |
| Seat plate | Who's seated, stack behind | Stack excludes the bet in front; an unreadable stack still keeps the seat | done |
| Card backs | Still in the hand | Grey felt; backs close to the felt's colour | done |
| Dimmed plate, no cards | Folded or sitting out | | done |
| Glow ring, timer bar | Whose turn | A second bar can be the time bank | done |
| Status plate | All in, Sitting out, last action tags | "All in" or a tag can replace the name | done |
| Dealer button | Anchors every position | A missing seat shifts every position after it | done |
| Bet in front | This round only | A bet on the same line as the pot label is still a bet | done |
| Total pot / pot | Middle plus bets, or middle only | Calibrated by the tracker | done |
| Board | Street | Empty dashed slots | done |
| Hero seat | Your cards, bottom middle | Face-up cards elsewhere are a showdown | done |
| Action buttons | Your turn, call and raise amounts | Tags on plates, sizing buttons | done |
| Hand number | New hand | Never an amount | done |

Frame-to-frame events (fold, check, call, bet, raise, all in, street over, showdown, pot
awarded) come from the tracker's stack changes (step 9). Still to do from the guide: the
predicted next actor as a check, and the Total pot and Call amount checks blocking advice
(step 10).

## Self-test (Phase 0)

`tools/selftest.py` plays hands on our own table (`app/tests/demo_table.py`, no real client)
and runs every picture through exactly what watch mode does: reader, tracker, hand memory,
advice. It compares each read with the truth and each instruction with the one given from the
true table. Five layouts: the annotated wireframe (grey felt, Total pot with bets, timer bars),
green (Pot without bets, glow only, four-colour deck, no "$"), compact (bets never printed,
smaller window), nine seats with three empty, sizing buttons and pre-action boxes, and tags
(last action replaces the name, scaled down and saved as JPEG). See the run log in
`docs/research/runs/selftest.md`.

    python tools/selftest.py --hands 20 --seed 3 --drop 0.1 --out "<folder for examples>"

## Next

The two missing checks (step 10) and the predicted next actor, then confirm everything on 247
from saved reads ("Save last reads").
