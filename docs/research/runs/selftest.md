# Self-test runs (Phase 0)

`tools/selftest.py`: PokerScribe plays on our own demo table (`app/tests/demo_table.py`). Every
picture goes through the reader, the tracker, the hand memory and the advice, as in watch mode,
and is checked against the truth. On your turn, the instruction is compared with the one the
advice gives when handed the true table (same maths, so any difference comes from reading).
Unclear cards are confirmed the way you would, so each deck is learned once. Bots and rules are
those of `tools/simulate.py`. Nothing touches a real poker client.

Layouts (all 6 players, blinds 1/2, stacks carried over and topped up below 40 big blinds):

| Layout | What it varies |
| --- | --- |
| wireframe | Kevin's annotated table: grey felt, "Total pot" with the bets, collected pot, timer bars, glow, hand number, "$" |
| green | green felt, "Pot" without the bets, glow only (no timer bar), four-colour deck, no "$", "Raise to 240" buttons, no hand number |
| compact | 1024x720, blue felt, bets never printed (the pot holds them), empty outline bars under every seat |
| ninemax | nine seats with three empty, sizing buttons and an amount box, Check/Fold and Call any boxes off your turn |
| tags | the last action replaces the name ("Call", "All in"), drawn at 80% and saved as JPEG |

## Round 1: before any fix (seed 2, 12 hands per layout)

| Layout | Same instruction | Move shown on their turn | Main mistakes |
| --- | --- | --- | --- |
| wireframe | 17/19 | 24/45 | bets missed 100, seats lost 11, folded seats read as in 12 |
| green | crashed (a duplicate card reached the maths: fixed in the self-test) | | |
| compact | 17/17 | 25/42 | showdown cards taken for yours, seats lost 4 |
| ninemax | 14/16 | 0/45 (pre-action boxes) | last hand's board and cards kept 13, bets missed 134 |
| tags | 15/19 | 34/45 | action tags read as your buttons 23, seats lost 108, positions wrong 101 |

Causes found and fixed (each has a test in `app/tests/test_selftest_table.py` or `test_hand.py`):

- Grey felt: the few coloured things (card backs, your plate) were taken for the felt, so card
  backs were never seen. A felt colour now has to cover 12% of the picture.
- Card backs close to the felt's colour: only the big areas of that colour (the felt) are left
  out now, not every pixel of that colour.
- Any amount on the same line as the pot label, within three label widths, was dropped: often a
  bet. Only the pot's own number, touching its label, is dropped now.
- One action word low on the screen counted as your buttons (the fallback forgot to drop it), and
  two tags far apart on one line counted as a row of buttons. Buttons must sit side by side; a
  lone one counts only in the bottom right corner.
- "All in" in place of the name lost the seat.
- After you folded, an opponent's face-up showdown cards were taken for yours. Yours are at the
  bottom middle.
- Other players' turn: not read at all. Now read from the timer bar or the glow ring (step 7).
- New hand missed after a single empty picture: last hand's board and hole cards were kept. Now:
  a new hand number, a board cleared while you have cards, or cards back that nothing ties to the
  old hand.
- Bet chips and a matching action tag ("Bet 60") now strengthen each other.

## Round 2: same seed after the fixes

| Layout | Same instruction | Move shown on their turn | Acting seat not read | Main mistakes left |
| --- | --- | --- | --- | --- |
| wireframe | 17/17 | 0/42 | 1/126 | bets 13 (from the tracker), one stack misread ("$25i") lost a seat |
| green | 17/19 | 0/47 | 0/127 | bets 113: lone digits ("6") never found |
| compact | 17/17 | 0/42 | 0/126 | bets 10 |
| ninemax | 16/17 | 0/42 | 0/126 | bets 133, a seat lost |
| tags | 20/21 | 0/49 | 4/131 | bets 82, a serif K on the dark felt not found as a card |

Fixed after round 2:

- Owing more than a big blind means someone raised, even when the bets weren't read (it said
  "RAISE TO 6" facing a raise to 6). A raise is at least a big blind more than the bet you face.
- A seat whose stack can't be read keeps its place (stack UNKNOWN): leaving it out shifted every
  position after it. "i" read for "1" in a number is repaired.
- A glyph touching the card edge by a pixel on a dark felt is ink, not felt showing through.
- The tracker, first adding up after the flop, took everything before as this round's bets. And a
  "no bet" that the stacks contradict is replaced by the stacks' number.
- Buttons and the timer on your seat strengthen each other (one faint "Bet" button missed your turn).

Before and after the advice changes, `python tools/simulate.py 400 --seed 11 --stacks tourney`
prints exactly the same: on complete reads the frozen baseline plays as before.

## Round 3: fresh seed (seed 3, 20 hands per layout, 10% of pictures skipped)

| Layout | Same instruction | Move shown on their turn | Mistakes |
| --- | --- | --- | --- |
| wireframe | 20/20 | 0/55 | none |
| green | 20/20 | 0/55 | a wrong hole card 5, bets 61, a seat 1 |
| compact | 20/20 | 0/55 | none |
| ninemax | 20/20 | 0/55 | bets 86 |
| tags | 19/20 | 0/53 | bets 17, pot 5, a seat 1 |

Fixed after round 3:

- A wrong hole card shown as known (the worst kind). Hand 12 was 3d 4c, hand 13 Ah 3d, and the
  empty picture between them was skipped; the table shows no hand number and no pot before the
  flop. The 3d matched, so it looked like the same hand, and the unsure Ah was filled in from
  memory as 4c. Memory no longer fills a card that this read clearly sees as another card.
- Short amounts the text finder skips ("$2", a lone "6" by a chip) are now looked for and read
  directly; a lone digit comes back UNKNOWN rather than as no bet.
- "Total pot: $1o" is $10; full-width digits are read.

## Round 4: fresh seed (seed 4, 25 hands per layout, 15% of pictures skipped)

| Layout | Same instruction | Move shown on their turn | Mistakes |
| --- | --- | --- | --- |
| wireframe | 28/28 | 0/68 | bets 13 (worked out from the stacks) |
| green | 28/28 | 0/68 | bets 88 (from the stacks), pot 1 |
| compact | 28/28 | 0/68 | bets 18 (from the stacks) |
| ninemax | 28/28 | 0/68 | bets 86 (from the stacks), pot 1 |
| tags | 35/38 | 0/73 | bets 6; 2 of the 3 differences were the self-test's (the true table left out the tags) |

Fixed after round 4:

- The pictures of the last raise and call before the flop were skipped, so the tracker's level
  for the round stayed at 7 and on the flop 14 of each player's chips looked like flop bets. On
  the first read of a round the level is now at least what every player still in has put in
  (only players known to have cards: you without cards have folded).
- "Totalpot:$51" and "Raiseto$46" (OCR dropping spaces) lost the pot and the raise button.
- The self-test's true table now has the last actions on a layout that shows them.

## Round 5: fresh seed (seed 5, 25 hands, 15% skipped), with a held-out sixth layout

`wide` was added after all the fixes above, to check they generalise: 1600x1000, other seat
spots, an orange timer bar and no glow, bigger text, another card font.

| Layout | Same instruction | Move shown on their turn | Mistakes |
| --- | --- | --- | --- |
| wireframe | 42/42 | 0/87 | bets 2 |
| green | 35/38 | 0/79 | pot 2 (tracker), a seat 1, bets 1 |
| compact | 42/42 | 0/87 | bets 6 |
| ninemax | 37/38 | 0/79 | pot 3 (tracker) |
| tags | 40/40 | 0/86 | bets 2 |
| wide (held out) | 39/41 | 0/91 | your bet read as 4 (it was the collected pot), "RAISE TO ABOUT 250" facing a raise to 99 |

Fixed after round 5:

- "RAISE TO ABOUT 250" when you faced a raise (CALL 66 from the true table): the stakes were read
  as "$1/s2" (no blinds), the blinds' own "$1" and "$2" just under the confidence bar, so with
  no big blind known "someone raised" fell back to action tags this table doesn't show. Now the
  big blind's own chips (even a faint read) or the smallest bet stand in for the stakes, "s2"
  after a "/" is "$2", and two reads of an amount that agree raise its confidence.
- The collected pot just below the board (your guide's element 11) was read as your bet. Bets lie
  at most about two thirds of the way from a seat to the middle.
- On a client whose pot leaves out this round's bets, a bet the size of the pot made a later set
  of stacks add up to the pot by chance: the tracker took it for a new hand and the pot lost the
  bets. The hand start already found is kept while it still adds up.

## Round 6: fresh seed (seed 6, 25 hands, 15% skipped), all six layouts

The first four layouts (wireframe 30/31, green 35/36, compact 30/31, ninemax 43/43 the same
instruction, no move on their turn) showed one new mistake, caused by a fix from round 5:

- Keeping the hand start already found misfired at the start of a hand. The stacks where the
  last hand began added up to the new pot by chance, so your blind from the last hand counted as
  a bet in this one: "Someone raised", FOLD with J9 on the button (the true table: open to 5).
  The start is kept now only in the case it was meant for: the newest set of stacks adds up to
  the middle pot alone, and the old start adds up to the pot plus the printed bets. Replaying the
  logged reads of that hand gives your bet 0 and the call 2.

Also fixed after round 6:

- A folded player's dimmed stack ("209", grey on dark) wasn't found as text, so the seat was
  lost. A name with nothing under it now has the spot under it read directly.
- A lone "9" beside its chip read as "19": the chip's edge was in the crop. Only the text is
  read now, and a lone digit without "$" never counts on one read.
