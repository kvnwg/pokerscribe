# Answer keys

Reference answers the PokerScribe solvers are checked against: today the Python river solver
(`app/solver`), and later the Rust river and turn solver (Phase 4). There are 40 spots
(30 river, 10 turn) and TexasSolver's answer to each one.

- `spots/`: the spots, one JSON file each. Format: `data/SPOT_FORMAT.md`.
- `texassolver/`: TexasSolver's answers in the RESULT format (same document), plus
  `index.json` (status, time and exploitability per spot).
- Code: `tools/answer_keys/`. Tests: `app/tests/test_answer_keys.py`.

## Status, 26 Nov 2026

Solving in progress in the cloud session: TexasSolver is built (below) and the converter
matches its trees on every spot tried. Results are committed as they finish.

## Licence: keep TexasSolver out of this repo

TexasSolver is AGPL-3.0. So:

- It is installed outside the repo, in `~/answer-keys/`.
- Its source, its binaries and anything built from its code are never committed.
- It is only ever run as a separate program: `tools/answer_keys` writes a config file,
  runs `console_solver -i <config>` in a subprocess, and reads the JSON it writes.
  Nothing in `tools/answer_keys` comes from TexasSolver's source. Its rules were found
  from its README and by running it on test configs and reading the output.
- The raw output and logs stay in `~/answer-keys/work/`. Only our parsed RESULT files
  are committed.
- b-inary's `postflop-solver` is also AGPL and isn't used either.

## The TexasSolver build

- Source: the `console` branch of <https://github.com/bupticybee/TexasSolver> (the
  author's own repository; `bilibili/TexasSolver` isn't reachable from cloud sessions),
  commit `02c8021`, built from source. No release of the console version is newer than
  the code on that branch, so results record `console@02c8021` as the version, plus the
  sha256 of the binary.
- Built and run in a cloud session (Linux, 4 cores). The same steps work on a Mac with
  CMake and a compiler that has OpenMP:

  ```
  mkdir -p ~/answer-keys && cd ~/answer-keys
  git clone --depth 1 -b console https://github.com/bupticybee/TexasSolver TexasSolver-console
  cd TexasSolver-console && mkdir build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j
  ```

- It must run from the folder that holds its `resources/` (the source folder), hence
  `--solver-cwd`.

## Solving

```
python -m tools.answer_keys solve --solver ~/answer-keys/TexasSolver-console/build/console_solver --solver-cwd ~/answer-keys/TexasSolver-console
python -m tools.answer_keys validate
```

`solve` skips spots already solved for the same spot file (`--force` solves them again),
prints `ok`, `warn` or `fail` for each one with the reason, and rewrites the table below.
Other commands: `config <id>` prints a spot's TexasSolver config; `parse <id> --dump <file>
[--log <file>]` reads output from a run done by hand; `make-spots` rebuilds `spots/` from
`tools/answer_keys/spot_defs.py`. All of them: `python -m tools.answer_keys --help`.

## Settings

| Setting | Value | Why |
| --- | --- | --- |
| Target | `set_accuracy 0.3` | Stop at 0.3% of the pot exploitability, by TexasSolver's own measure. |
| Exploitability check | `set_print_interval 10` | TexasSolver works out its exploitability, and so can stop, every 10 iterations. |
| Iteration cap | `set_max_iteration 5000` | A safety stop. A spot that hits it is marked `warn` (not converged). |
| Threads | `set_thread_num` = every core | 4 here. |
| Isomorphism | `set_use_isomorphism 0` | Keeps every river card in a turn spot's output. |
| All-in threshold | `set_allin_threshold 1000` | Turns TexasSolver's own all-in rule off (see "Quirks"). |
| Raises a street | 3, fixed | TexasSolver has no setting for it, so every spot has `max_raises` 3. |
| Output | `set_dump_rounds` = 1 (river) or 2 (turn) | The whole tree of the spot. |
| Time limit | 3600 s a spot | `--timeout`. |

Each result's header records the settings, the version and the binary's sha256.

## Solve times and exploitability

"TexasSolver exploitability" is its own last number. "Our check" is the exploitability of
its answer worked out by `app/solver/exploitability.py` (river spots only), which doesn't
depend on TexasSolver at all.

<!-- solve-table:start -->
Not solved yet.
<!-- solve-table:end -->

## Quirks

What TexasSolver does, found from its README and by running it on test configs. Every
solve still rebuilds TexasSolver's tree from its output and compares it node by node with
the spot's own tree, so if any of this is wrong for some spot, that spot fails instead of
saving a wrong key.

1. **Ranges by class only.** TexasSolver reads ranges like `AA,KK:0.5,AKs`, with no single
   combos. So every range here is made of whole classes with one weight each, and the
   converter refuses any other range (`spots.class_weights`). TexasSolver removes the
   board cards itself.
2. **No raise limit setting.** `set_raise_limit` is not a command ("command not
   recognized"). TexasSolver always allows 3 raises after the first bet on each street,
   so every spot has `max_raises` 3, and the converter refuses any other value.
3. **Its all-in threshold depends on the pot.** With `set_allin_threshold 1`, it still
   turned a re-raise to 282 into an all-in with 300 behind. The tests fit "all in when
   (amount + half the starting pot) / stack is over the threshold". At 1000 that never
   happens, which leaves the same rule as `app/solver`: a size at or over the stack is the
   all-in, and equal amounts are offered once.
4. **Raise sizes** are the same as ours: a share of the pot after calling, on top of the
   call. Facing a bet of 50 into 100, 50% is a raise to 150.
5. **What the amounts mean.** `BET 50` is a bet of 50. `RAISE x` is the chips the raise
   adds: facing 250 with 100 in, `RAISE 200` is all in for 300. The converter still tries
   every reading and keeps the one that rebuilds the spot's tree; the header records it as
   `solver.reading` (`to` when no raise follows a player's own bet, where both read the same).
6. **The river deal lists all 52 cards**, the board's too. Those branches can't happen and
   are skipped.
7. **Donk sizes.** TexasSolver has separate sizes for an out of position lead ("donk").
   They are set to OOP's bet sizes, so a lead is just a bet. The flop's sizes are set too
   (copies of the first street's), though no flop is played.
8. **Who is player 0.** The converter doesn't rely on TexasSolver's player numbers: OOP acts
   first on every street and the players take turns. (TexasSolver calls OOP player 1.)
9. **Output layout.** An action node has `actions`, `childrens` keyed by action, and
   `strategy: {actions, strategy: {combo: [p, ...]}}`. A chance node has `dealcards` keyed
   by card. The two cards of a combo come in either order; they are rewritten in our
   canonical spelling. There are no EVs.
10. **Exploitability.** TexasSolver prints "Total exploitability" in percent of the pot; the
    header stores it as a share. On the river spots it equals our own check, so the two
    measure the same thing.
11. **Start-up time.** About 5 s of each run is TexasSolver loading its 52 MB hand-ranking
    table, so most river spots take about 5.5 s whatever their size.

## The spots

All pots are 100. "Sizes" are bet sizes as shares of the pot; "r" marks raise sizes, as
shares of the pot after calling. Going all in is always allowed, and every spot allows 3
raises a street. Ranges are in each spot file (`range_text`).

The three trivial spots have `expected` checks with obvious answers:

- r01: IP holds only air against top set, so it checks and folds to every bet.
- r02: the same with the seats swapped.
- r03: a royal flush is on the board, so IP never folds to a bet.

Both `app/solver` and TexasSolver pass all three. A TexasSolver answer that fails one
isn't saved.

