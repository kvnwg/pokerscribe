# Answer keys

Reference answers the PokerScribe solvers are checked against: today the Python river solver
(`app/solver`), and later the Rust river and turn solver (Phase 4). There are 40 spots
(30 river, 10 turn) and TexasSolver's answer to each one.

- `spots/`: the spots, one JSON file each. Format: `data/SPOT_FORMAT.md`.
- `texassolver/`: TexasSolver's answers in the RESULT format (same document), plus
  `index.json` (status, time and exploitability per spot).
- Code: `tools/answer_keys/`. Tests: `app/tests/test_answer_keys.py`.

## Status, 26 Nov 2026: spots written, not solved yet

The spots, the converter and the checks are done and tested. **No spot has been solved
yet.** The cloud session that wrote this couldn't download TexasSolver: its releases are
on `github.com`, and the session's GitHub access only covered this repo. So the
solving runs on Kevin's Mac (below). Until then `texassolver/` is empty, and the version,
settings and times below are what the tool will use and record, not measured values.

## Licence: keep TexasSolver out of this repo

TexasSolver is AGPL-3.0. So:

- It is installed outside the repo, in `~/answer-keys/`.
- Its source, its binaries and anything built from its code are never committed.
- It is only ever run as a separate program: `tools/answer_keys` writes a config file,
  runs `console_solver -i <config>` in a subprocess, and reads the JSON it writes.
  Nothing in `tools/answer_keys` comes from TexasSolver's source.
- The raw output and logs stay in `~/answer-keys/work/`. Only our parsed RESULT files
  are committed.
- b-inary's `postflop-solver` is also AGPL and isn't used either.

## Solving on the Mac

1. Get TexasSolver's console version, **v0.2.0**, the latest release, from
   <https://github.com/bilibili/TexasSolver/releases>, and unzip it into
   `~/answer-keys/TexasSolver/`. That folder should end up with the `console_solver`
   program and its `resources/` folder next to it.
   - If the macOS download only has the desktop app and no `console_solver`, build the
     console version from source, following the steps in TexasSolver's own README, still
     inside `~/answer-keys/`.
   - If macOS refuses to open it, clear the download flag:
     `xattr -dr com.apple.quarantine ~/answer-keys/TexasSolver`.
   - Check that it runs before going further: from `~/answer-keys/TexasSolver`, run
     `./console_solver -i resources/text/commandline_sample_input.txt`.
2. Solve the four spots that test the converter's guesses first (a trivial spot, a raise
   size, a reraise and a turn spot with a raise size):

   ```
   .venv/bin/python -m tools.answer_keys solve r01 r05 r24 t10 --solver ~/answer-keys/TexasSolver/console_solver
   ```

   Each spot prints `ok`, `warn` or `fail`, with the reason. If any fails because
   "TexasSolver's tree differs from the spot's", see "Quirks" below before going on.
3. Solve the rest. Spots already solved for the same spot file are skipped:

   ```
   .venv/bin/python -m tools.answer_keys solve --solver ~/answer-keys/TexasSolver/console_solver
   ```

4. Check them, then commit `data/answer_keys/texassolver/` and this README (the solve
   table below is rewritten by `solve`, or by `report`):

   ```
   .venv/bin/python -m tools.answer_keys validate
   ```

Other commands: `config <id>` prints a spot's TexasSolver config; `parse <id> --dump
<file> [--log <file>]` reads output from a run you did by hand; `make-spots` rebuilds
`spots/` from `tools/answer_keys/spot_defs.py`. All of them: `python -m tools.answer_keys
--help`.

## Settings

| Setting | Value | Why |
| --- | --- | --- |
| Target | `set_accuracy 0.3` | Stop at 0.3% of the pot exploitability, by TexasSolver's own measure. |
| Exploitability check | `set_print_interval 10` | TexasSolver works out its exploitability, and so can stop, every 10 iterations. |
| Iteration cap | `set_max_iteration 5000` | A safety stop. A spot that hits it is marked `warn` (not converged). |
| Threads | `set_thread_num` = every core | |
| Isomorphism | `set_use_isomorphism 0` | Keeps every river card in a turn spot's output. Slower than 1. |
| All-in threshold | `set_allin_threshold 1.0` | Only sizes at or over the stack become all in, as in `app/solver`. |
| Raise limit | `set_raise_limit` = the spot's `max_raises` | See "Quirks". |
| Output | `set_dump_rounds` = 1 (river) or 2 (turn) | The whole tree of the spot. |
| Time limit | 3600 s a spot | `--timeout`. |

Each result's header records the settings, TexasSolver's version and the sha256 of the
binary that solved it.

## Solve times and exploitability

Filled in by `solve`. "TexasSolver exploitability" is its own last number. "Our check" is
the exploitability of its answer worked out by `app/solver/exploitability.py` (river spots
only), which doesn't depend on TexasSolver at all.

<!-- solve-table:start -->
Not solved yet.
<!-- solve-table:end -->

For scale: `app/solver` solves each river spot to 0.3% in under 0.1 s, so TexasSolver's
river spots should take seconds. The turn spots have 1,160 to 1,932 decision nodes (48
river cards each, with isomorphism off) and should take minutes. Results are about 0.1 MB a
river spot; a turn spot is up to about 1.5 MB gzipped (measured on random strategies,
which compress worse than real ones).

## Quirks

What TexasSolver needs, and the guesses the converter makes about it. The guesses are
built so that a wrong one fails loudly on the first run instead of saving a wrong key.

1. **Ranges by class only.** TexasSolver reads ranges like `AA,KK:0.5,AKs`, with no single
   combos. So every range here is made of whole classes with one weight each, and the
   converter refuses any other range (`spots.class_weights`). TexasSolver removes the
   board cards itself.
2. **What a BET or RAISE amount means isn't documented.** It could be the chips put in on
   the street after the action, the chips added, the chips added on top of the call, or
   the chips put in since the spot started. The converter tries every reading and keeps
   the one that rebuilds the spot's own tree exactly; the header records it as
   `solver.reading`. If no reading does, the spot fails with the differences listed. It
   doesn't save a key for a game that isn't the spot's.
3. **Raise sizes.** In the spots, a raise is a share of the pot after calling, on top of
   the call (`app/solver`). TexasSolver is given the same number as a percent. If its rule
   is different, the tree check in point 2 shows it: the raise amounts won't match. The fix
   then goes in `texassolver.config_text`, converting our size into TexasSolver's. The
   spots are chosen so that no size is cut to the all-in and the min-raise never binds
   (`SPOT_FORMAT.md`, "Sizes"), so that rounding and all-in rules can't differ.
4. **Raise limit.** `max_raises` counts raises after the first bet. If TexasSolver's
   `set_raise_limit` also counts the bet, trees with raises will be missing their last
   raise. Then run with `--raise-limit-extra 1`, which the header records.
5. **Donk sizes.** TexasSolver has separate sizes for an out of position lead ("donk").
   They are set to the same sizes as OOP's bets, so a lead is just a bet. The flop's sizes
   are also set (copies of the first street's) in case a build wants every street.
6. **Who is player 0.** The converter doesn't use TexasSolver's player numbers. OOP acts
   first on every street and the players take turns, so it works out the actor itself. If
   TexasSolver's numbers disagree with that, it adds a note to `solver.notes`.
7. **Output layout.** An action node has `actions`, `childrens` (or `children`) keyed by
   action, and `strategy: {actions, strategy: {combo: [p, ...]}}`. A chance node has
   `dealcards` keyed by card. The two cards of a combo come in either order; they are
   rewritten in our canonical spelling. There are no EVs.
8. **Exploitability units.** TexasSolver prints "Total exploitability" in percent of the
   pot; the header stores it as a share (`0.003`). For river spots our own check is next to
   it. If the two differ by about a factor of 2 on every spot, TexasSolver defines it
   without the halving we use (`SOLVER.md`, "Payoffs"). Then 0.3% by its measure is 0.15%
   by ours, which is stricter, so the keys are still good. A spot whose own check is over
   twice the target is marked `warn`.
9. **Not converged.** A spot that reaches `set_max_iteration` before the target is saved,
   but marked `warn`. Solve it again with more iterations.

## The spots

All pots are 100. "Sizes" are bet sizes as shares of the pot; "r" marks raise sizes, as
shares of the pot after calling. Going all in is always allowed. Ranges are in each spot
file (`range_text`).

The three trivial spots have `expected` checks with obvious answers:

- r01: IP holds only air against top set, so it checks and folds to every bet.
- r02: the same with the seats swapped.
- r03: a royal flush is on the board, so IP never folds to a bet.

`app/solver` passes all three (a test checks this). A TexasSolver answer that fails one is
not saved.

| Spot | Board | SPR | Sizes (pot shares; raises after r; all in always) | Max raises | Combos oop / ip | Decision nodes | What |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| r01 | Ks 7d 2c 4h 9s | 1 | oop 0.5, ip 0.5 | 1 | 3 / 16 | 8 | Trivial: OOP holds only top set, IP holds only high-card air |
| r02 | Jc 8d 3s Ks 2h | 1 | oop 0.5, ip 0.5 | 1 | 16 / 6 | 8 | Trivial: IP holds only sets, OOP holds only high-card air |
| r03 | Ah Kh Qh Jh Th | 2 | oop 0.5, ip 0.5 | 1 | 105 / 42 | 8 | Trivial: royal flush on the board, every hand splits |
| r04 | Ks 7d 2c 4h 9s | 1.5 | oop 0.5, ip 0.75 | 1 | 65 / 54 | 8 | Dry K72-94, condensed OOP vs polar IP, one size |
| r05 | Ks 7d 2c 4h 9s | 3 | oop 0.5 r0.5, ip 0.33/1 r0.5 | 1 | 65 / 54 | 13 | Dry K72-94, polar IP with two sizes and a raise size |
| r06 | Jc 8d 3s Ks 2h | 0.5 | oop 0.25, ip 0.25 | 1 | 61 / 47 | 8 | Dry KJ832, SPR 0.5, small bet or all in |
| r07 | Jc 8d 3s Ks 2h | 5 | oop 0.33 r0.5, ip 0.33/0.75/1.5 r0.5 | 1 | 61 / 47 | 16 | Dry KJ832, SPR 5, three IP sizes |
| r08 | Qd 6c 2h 9s 4d | 2 | oop 0.66, ip 0.66 | 1 | 234 / 112 | 8 | Dry Q9642, two wide ranges |
| r09 | Kc Kd 5h 9s 2c | 1 | oop 0.5, ip 0.75 | 1 | 78 / 61 | 8 | Paired KK952, condensed OOP vs polar IP |
| r10 | As Ac 7h 7d 2s | 2 | oop 0.5, ip 0.5/1.25 | 1 | 100 / 53 | 10 | Double-paired AA772, polar IP with two sizes |
| r11 | Ah 8c 3d 3s Jc | 4 | oop 0.5, ip 0.25/0.75/2 | 1 | 66 / 63 | 12 | Paired AJ833, SPR 4, three IP sizes up to 2x pot |
| r12 | Td 4c 4s 8h 2d | 1.5 | oop 0.75, ip 0.5 | 1 | 51 / 81 | 8 | Paired T8442, OOP polar lead into condensed IP |
| r13 | Jh Th 8c 9h 2s | 2 | oop 0.33, ip 0.5/1 | 1 | 61 / 58 | 10 | Wet JT982 three hearts, polar IP with two sizes |
| r14 | Jh Th 8c 9h 2s | 0.5 | oop 0.33, ip 0.33 | 1 | 61 / 58 | 8 | Wet JT982 three hearts, SPR 0.5 |
| r15 | 9s 8s 6d 7c Ks | 3 | oop 0.5 r0.5, ip 0.75 r0.5 | 1 | 62 / 66 | 10 | Wet K9876 three spades, raise size |
| r16 | Qh Jh 5h 2c 4h | 1 | oop 0.5, ip 0.33/0.75 | 1 | 84 / 79 | 10 | Four hearts QJ542, condensed OOP vs polar IP |
| r17 | Tc 9c 7d 6c 3h | 5 | oop 0.5 r0.5, ip 0.5/1/2 r0.5 | 1 | 66 / 44 | 16 | Wet T9763 three clubs, SPR 5, three IP sizes |
| r18 | 8d 7d 5s 4c Ad | 1.5 | oop 0.5, ip 0.5 | 1 | 222 / 185 | 8 | Wet A8754 three diamonds, two wide ranges |
| r19 | Kh Qd Jc 4s 2h | 2 | oop 1, ip 0.5 | 1 | 54 / 63 | 8 | Broadway KQJ42, OOP polar pot-size lead |
| r20 | 6h 5h 4d 7s Qh | 3 | oop 0.33, ip 0.33/0.75 | 1 | 83 / 43 | 10 | Wet Q7654 three hearts, two IP sizes |
| r21 | Ks 7d 2c 4h 9s | 1 | oop 0.5, ip 0.5 | 1 | 299 / 230 | 8 | Dry K72-94, two wide ranges, SPR 1 |
| r22 | Jc 8d 3s Ks 2h | 3 | oop 0.75/1.5, ip 0.5 | 1 | 52 / 51 | 10 | Dry KJ832, OOP polar lead with two sizes |
| r23 | 9s 8s 6d 7c Ks | 0.5 | oop 0.25, ip 0.25 | 1 | 62 / 66 | 8 | Wet K9876 three spades, SPR 0.5 |
| r24 | Qh Jh 5h 2c 4h | 5 | oop 0.33 r0.5, ip 0.33 r0.5 | 2 | 84 / 79 | 14 | Four hearts QJ542, SPR 5, a raise and a reraise |
| r25 | Tc 9c 7d 6c 3h | 1 | oop 0.5, ip 0.33/0.66 | 1 | 231 / 198 | 10 | Wet T9763, two wide ranges, two IP sizes |
| r26 | 8d 7d 5s 4c Ad | 2 | oop 0.33, ip 0.33/0.75/1.5 | 1 | 66 / 53 | 12 | Wet A8754, polar IP with three sizes |
| r27 | As Ac 7h 7d 2s | 0.5 | oop 0.33, ip 0.33 | 1 | 100 / 53 | 8 | Double-paired AA772, SPR 0.5 |
| r28 | Kc Kd 5h 9s 2c | 5 | oop 0.5, ip 1/2.5 | 1 | 78 / 61 | 10 | Paired KK952, SPR 5, IP overbets |
| r29 | Jh Th 8c 9h 2s | 4 | oop 0.75 r0.5, ip 0.5 r0.5 | 1 | 58 / 61 | 10 | Wet JT982, OOP polar lead into condensed IP, raise size |
| r30 | Qd 6c 2h 9s 4d | 1.5 | oop 1, ip 1 | 1 | 66 / 54 | 8 | Dry Q9642, polar IP pot-size bet |
| t01 | Ks 7d 2c 4h | 3 | oop 0.5, ip 0.5 ; river oop 0.5, ip 0.5 | 1 | 71 / 49 | 1160 | Turn: dry K724, condensed OOP vs polar IP |
| t02 | Jh Th 8c 2s | 2 | oop 0.5, ip 0.5 ; river oop 0.5, ip 0.5 | 1 | 64 / 53 | 1160 | Turn: wet JT82 two hearts |
| t03 | Qh Jh 5h 2c | 5 | oop 0.33, ip 0.33 ; river oop 0.5/1, ip 0.5/1 | 1 | 72 / 73 | 1736 | Turn: three hearts QJ52, SPR 5, two river sizes |
| t04 | As Ac 7h 2d | 1 | oop 0.25, ip 0.25 ; river oop 0.4, ip 0.4 | 1 | 102 / 51 | 1160 | Turn: paired AA72, SPR 1 |
| t05 | Jc 8d 3s Ks | 0.5 | oop 0.2, ip 0.2 ; river oop 0.2, ip 0.2 | 1 | 58 / 43 | 1160 | Turn: dry KJ83, SPR 0.5 |
| t06 | 9s 8s 6d Kc | 1.5 | oop 0.5, ip 0.5 ; river oop 0.25/0.4, ip 0.25/0.4 | 1 | 57 / 62 | 1736 | Turn: wet K986 two spades, two river sizes |
| t07 | Td 4c 4s 8h | 4 | oop 0.5/1, ip 0.5/1 ; river oop 0.5, ip 0.5 | 1 | 75 / 48 | 1932 | Turn: paired T844, SPR 4, two turn sizes |
| t08 | 8d 7d 5s 4c | 2 | oop 0.33, ip 0.33 ; river oop 0.5, ip 0.5 | 1 | 63 / 39 | 1160 | Turn: wet 8754 two diamonds |
| t09 | Ah 8c 3d Jc | 3 | oop 0.75, ip 0.75 ; river oop 0.5/0.8, ip 0.5/0.8 | 1 | 66 / 65 | 1736 | Turn: AJ83 two clubs, big turn bet, two river sizes |
| t10 | Kh Qd Jc 4s | 5 | oop 0.5 r0.5, ip 0.5 r0.5 ; river oop 0.5, ip 0.5 | 1 | 63 / 50 | 1930 | Turn: broadway KQJ4, SPR 5, turn raise size |
