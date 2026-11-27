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

## Round 7: final check (fresh seed 7, 25 hands, 15% skipped), every fix in

| Layout | Same instruction | Move shown on their turn | Acting seat not read | Mistakes |
| --- | --- | --- | --- | --- |
| wireframe | 32/32 | 0/82 | 0/203 | bets 3 |
| green | 31/32 | 0/81 | 0/207 | bets 3 |
| compact | 32/32 | 0/82 | 0/203 | bets 4 |
| ninemax | 32/32 | 0/82 | 0/203 | bets 3 |
| tags | 33/33 | 0/81 | 0/216 | bets 4 |
| wide (held out) | 32/32 | 0/82 | 0/203 | bets 3 |

192 of 193 instructions the same as from the true table; no wrong card, no lost seat, no
unknown stack. The one difference (green): both saw the raise, but with 9-4 suited in the big
blind the read said FOLD and the true table CALL 6, a close spot moved by a misread amount.

Still open:

- At showdown, with opponents' cards face up, the tracker can take the picture for a new hand
  start and show the river bets as whole-hand amounts (the "bets 3" above). Nothing is decided
  then, but it should be fixed.
- Lone single-digit bets without "$" are read only when two reads agree; otherwise UNKNOWN.
- Not yet checked against a real 247 table: run "Save last reads" there and replay them.

## Picture tables (26 Nov, evening): rounds 8 to 13

From Kevin's screenshots of tables with round pictures and numbers that are not chips, four new
layouts: avatars, stock, portrait and levels (`docs/research/SCREEN_READING.md`, "Round
pictures and numbers that are not chips"). Then lvtext, held out from the fixes: a bare gold
level number beside every name. Each round a fresh seed, 15% of pictures skipped (10% in the
first two).

| Round (seed) | Same instruction | Move shown on their turn |
| --- | --- | --- |
| 8 (21), before any fix | 46/56 | 53/144 |
| 9 (21), after the fixes | 51/52 | 3/144 |
| 10 (22) | 55/61 | 5/135 |
| 11 (23) | 100/100 | 5/236 |
| 12 (24) | 156/157 | 1/346 |
| 13 (25) | 160/160 | 0/344 |
| lvtext, held out (27) | 53/53 | 0/123 |
| the six older layouts (26) | 150/150 | 0/368 |

What the rounds found and fixed, each with a test in `app/tests/test_avatar_tables.py`: levels
and countdowns on pictures taken for bets; a number on the name's line taken for a bet;
pictures and the table's rim taken for card backs, and plain grey backs missed; a short timer
ring not read as the turn; showdown cards taken for yours; your hand's strength taken for your
name; the dealer button touching a level badge or a stack; a comma read as a point ("2.035");
a chip icon read as a "0" before the bet.

After round 13:

- At showdown a player beside the middle shows his cards on the board's line, smaller. Seven
  cards in a row were no board at all, and the board cards were given to the nearest player: a
  folded player at the top read as still in, and the river bets as whole-hand amounts (avatars,
  "in hand wrong 13" and most of "bets 22"). Rows are now cut where the card size changes or a
  wide gap opens.
- The chip icon read as a letter stuck to the bet ("C210"): the bet came back as nothing
  (stock). A round letter straight before an amount of two digits or more is dropped.
- In stock, "acting seat not read 40/238" is your own turns: your picture is under your cards,
  and the buttons decide then.

Still open: at showdown, the river bets already swept into the pot still show as bets worked
out from the stacks (levels and portrait, "bets 3"; the same as round 7's open item). Nothing
is decided then.

## Eight players (26 and 27 Nov)

Kevin: "it also needs to be trained on an 8 people table". `--players 8` spreads eight players
over a layout's seats, and a new eight-seat layout ("eight") was added. Seed 30, 20 hands per
layout, 15% of pictures skipped. The first run was on the code before the fixes below, the
second on the same seed after all of them.

| Layout | Same instruction | Move shown on their turn | Acting seat not read | Mistakes |
| --- | --- | --- | --- | --- |
| eight, before | 26/26 | 0/72 | 0/216 | bets 4 |
| ninemax, before | 26/26 | 0/72 | 0/216 | bets 4 |
| avatars, before | 26/26 | 0/72 | 19/216 | seat lost 19, pot 13, positions 12, bets 4, in hand 3, stacks unknown 3 |
| stock, before | 26/26 | 0/72 | 26/216 | bets 4, in hand 2, pot 1 |
| portrait, before | 20/24 | 0/69 | 0/214 | in hand 199, bets 78, positions 9, seat lost 3, pot 2 |
| eight, after | 26/26 | 0/72 | 0/216 | bets 2 |
| ninemax, after | 26/26 | 0/72 | 0/216 | bets 2 |
| avatars, after | 26/26 | 0/72 | 19/216 | bets 2, stacks unknown 2 |
| stock, after | 26/26 | 0/72 | 26/216 | bets 2 |
| portrait, after | 26/26 | 0/72 | 0/216 | bets 2 |

What the first run found, each fixed with a test (`app/tests/test_avatar_tables.py` unless
named):

- Every layout, bets 4: the turn's pictures were all skipped, and on the river the stacks just
  after the blinds went in came within the tracker's rounding allowance of the pot (288 against
  291). Being newer than the true start they were taken for it, so the big blind's 2 counted as
  a river bet. An older snapshot of the same hand that adds up to the chip now wins over a newer
  one that adds up only roughly (`test_tracker.py`,
  `test_a_skipped_street_does_not_turn_the_blinds_into_bets`).
- Portrait, four CHECKs where the truth was FOLD, with a Call 200 button on screen: the blinds
  were lost (below), you read as the big blind, and "you see the flop for free" was shown
  without a Check button. CHECK is never shown now without a Check button
  (`test_posted_blinds.py`, `test_never_check_with_a_call_button`,
  `test_a_free_look_is_only_free_with_a_check_button`).
- Portrait: the coin before a stack read as "+" ("+$ 19700"), so that seat was lost and every
  position after it moved.
- Portrait: the blinds' chips lie beside the next seat's name and stack and were dropped as
  level numbers (bets 78). An amount with a currency sign is never a level.
- Portrait: card backs lying across the table's black rim, dark inside a thin white edge, were
  missed (in hand 199).
- Avatars: the top seat's stack sits on the table's rim, and with no pot on the felt it was
  taken for the pot (seat lost 19, pot 13, positions 12). A number under a name or a picture is
  never the unlabelled pot.
- Avatars: a seat on the right has its backs on the left of its picture, further out than the
  name is wide. The search cut the outer card off, and the inner one, between the picture and
  the timer ring, was no clean card: that player read as folded on their turn.
- Stock, at showdown: a player's second card lay nearer the next seat's name, and one card at a
  time it made a folded player one still in. A pair of cards now goes to one seat together.
- Stock, on the flop: the middle of the three cards dealt was taken for the table's middle, one
  card left of it. A bet then went to the folded neighbour, the tracker found it again from its
  own player's stack, and the pot came out a bet too big. The middle is now the middle of the
  board's five places.

Left after the fixes:

- Bets 2 on every layout: at an all-in showdown, bets worked out from the stacks after the
  chips went in (the open item from round 7). Nothing is decided then.
- Acting seat not read on avatars (19) and stock (26): your own turns. Your picture's ring is
  half under your cards, and the buttons decide then. On avatars the four pictures saved were
  all your own turns (stock: all 26 are).

Six players after the fixes, same seeds as the earlier rounds, to check nothing got worse:

| Layouts (seed) | Same instruction | Move shown on their turn | Mistakes before, after |
| --- | --- | --- | --- |
| avatars, stock, portrait, levels (25, round 13) | 160/160 | 0/344 | bets 35, 12; in hand 13, 0; stacks unknown 21, 21 |
| lvtext, held out (27) | 53/53 | 0/123 | bets 2, 2 |
| the six older layouts (26) | 150/150 | 0/368 | bets 13, 10; seat lost 1, 1 (tags) |

The stacks unknown on stock (17) and avatars (4) were there in round 13 too; the instructions
were all right.
