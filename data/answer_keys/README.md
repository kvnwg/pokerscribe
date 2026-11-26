# Answer keys

Reference answers the PokerScribe solvers are checked against: today the Python river solver
(`app/solver`), and later the Rust river and turn solver (Phase 4). There are 40 spots
(30 river, 10 turn) and TexasSolver's answer to each one.

- `spots/`: the spots, one JSON file each. Format: `data/SPOT_FORMAT.md`.
- `texassolver/`: TexasSolver's answers in the RESULT format (same document), plus
  `index.json` (status, time and exploitability per spot).
- Code: `tools/answer_keys/`. Tests: `app/tests/test_answer_keys.py`.

## Status, 26 Nov 2026

All 40 spots are solved, with status `ok`: TexasSolver's tree matched the spot's on
every one, every answer is under 0.3% of the pot exploitability, and the three trivial
spots pass their checks. On all 30 river spots our own exploitability check gives the
same number as TexasSolver's, to the third decimal. The turn spots have only
TexasSolver's own number until a turn checker exists (the Rust solver's).

River results also carry each answer's value and bounds on the true value (`checks.values`,
`checks.oop_value_bounds`, `SPOT_FORMAT.md`), for the Phase 4 gate "TexasSolver within 0.5%
pot EV". As a check, `app/solver` solved every river spot to 0.01% of the pot: its bounds
meet TexasSolver's on all 30, and its value is within 0.30% of the pot of TexasSolver's on
every one (0.09% on average). `test_app_solver_agrees_with_texassolver` repeats this on four
spots.

Solved in the cloud session, 4 threads: 5 to 7 s a spot, most of it start-up (Quirk 11).
The results take 5.7 MB: 10 to 40 KB a river spot, 0.3 to 0.7 MB a turn spot (gzipped).

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
`tools/answer_keys/spot_defs.py`; `recheck` works our checks (exploitability, values,
bounds) out again on the saved river results without solving again. All of them:
`python -m tools.answer_keys --help`.

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
depend on TexasSolver at all. "OOP value" is what OOP wins a hand under the answer, in chips
(the pot is 100, so also percent of the pot); IP wins the rest of the pot.

<!-- solve-table:start -->
TexasSolver console@02c8021, binary sha256 `a752c18a7021f6fe9809e544f212a25de24d4f49a4a1c29a62ae97463c46ceb5`.

| Spot | Street | Status | Solve time (s) | Iterations | TexasSolver exploitability | Our check | OOP value | Nodes | File |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| r01 | river | ok | 5.58 | 31 | 0.166% | 0.166% | 100.307 | 8 | r01.jsonl |
| r02 | river | ok | 5.5 | 21 | 0.124% | 0.124% | -0.222 | 8 | r02.jsonl |
| r03 | river | ok | 5.52 | 11 | 0.000% | 0.000% | 50.000 | 8 | r03.jsonl |
| r04 | river | ok | 5.51 | 61 | 0.205% | 0.205% | 40.904 | 8 | r04.jsonl |
| r05 | river | ok | 5.34 | 71 | 0.257% | 0.257% | 38.499 | 18 | r05.jsonl |
| r06 | river | ok | 5.47 | 41 | 0.289% | 0.289% | 47.162 | 8 | r06.jsonl |
| r07 | river | ok | 5.5 | 101 | 0.236% | 0.236% | 45.598 | 26 | r07.jsonl |
| r08 | river | ok | 5.13 | 61 | 0.296% | 0.296% | 37.296 | 8 | r08.jsonl |
| r09 | river | ok | 5.92 | 61 | 0.266% | 0.266% | 30.773 | 8 | r09.jsonl |
| r10 | river | ok | 5.39 | 51 | 0.209% | 0.209% | 10.956 | 10 | r10.jsonl |
| r11 | river | ok | 5.34 | 111 | 0.298% | 0.298% | 26.801 | 12 | r11.jsonl |
| r12 | river | ok | 5.09 | 51 | 0.297% | 0.297% | 43.794 | 8 | r12.jsonl |
| r13 | river | ok | 5.73 | 51 | 0.266% | 0.266% | 6.166 | 10 | r13.jsonl |
| r14 | river | ok | 6.1 | 51 | 0.147% | 0.147% | 9.669 | 8 | r14.jsonl |
| r15 | river | ok | 5.64 | 61 | 0.227% | 0.227% | 15.343 | 12 | r15.jsonl |
| r16 | river | ok | 5.65 | 51 | 0.232% | 0.232% | 53.974 | 10 | r16.jsonl |
| r17 | river | ok | 5.71 | 61 | 0.154% | 0.154% | -0.107 | 24 | r17.jsonl |
| r18 | river | ok | 5.41 | 41 | 0.273% | 0.273% | 42.966 | 8 | r18.jsonl |
| r19 | river | ok | 6.47 | 61 | 0.165% | 0.165% | 81.864 | 8 | r19.jsonl |
| r20 | river | ok | 5.63 | 51 | 0.188% | 0.188% | -0.195 | 10 | r20.jsonl |
| r21 | river | ok | 6.23 | 41 | 0.185% | 0.185% | 39.741 | 8 | r21.jsonl |
| r22 | river | ok | 5.81 | 81 | 0.300% | 0.300% | 68.585 | 10 | r22.jsonl |
| r23 | river | ok | 5.83 | 31 | 0.283% | 0.283% | 26.661 | 8 | r23.jsonl |
| r24 | river | ok | 5.22 | 91 | 0.238% | 0.238% | 55.596 | 16 | r24.jsonl |
| r25 | river | ok | 5.61 | 41 | 0.258% | 0.258% | 42.866 | 10 | r25.jsonl |
| r26 | river | ok | 5.7 | 41 | 0.245% | 0.245% | -0.240 | 12 | r26.jsonl |
| r27 | river | ok | 5.02 | 41 | 0.131% | 0.131% | 22.168 | 8 | r27.jsonl |
| r28 | river | ok | 5.36 | 91 | 0.192% | 0.192% | 17.245 | 10 | r28.jsonl |
| r29 | river | ok | 5.47 | 71 | 0.203% | 0.203% | 94.540 | 14 | r29.jsonl |
| r30 | river | ok | 5.51 | 61 | 0.180% | 0.180% | 47.828 | 8 | r30.jsonl |
| t01 | turn | ok | 5.87 | 81 | 0.264% |  |  | 1160 | t01.jsonl.gz |
| t02 | turn | ok | 5.9 | 91 | 0.235% |  |  | 1160 | t02.jsonl.gz |
| t03 | turn | ok | 6.59 | 171 | 0.283% |  |  | 1736 | t03.jsonl.gz |
| t04 | turn | ok | 5.63 | 81 | 0.202% |  |  | 1160 | t04.jsonl.gz |
| t05 | turn | ok | 5.78 | 31 | 0.221% |  |  | 1160 | t05.jsonl.gz |
| t06 | turn | ok | 5.98 | 61 | 0.245% |  |  | 1736 | t06.jsonl.gz |
| t07 | turn | ok | 6.42 | 91 | 0.210% |  |  | 1932 | t07.jsonl.gz |
| t08 | turn | ok | 5.58 | 71 | 0.221% |  |  | 1160 | t08.jsonl.gz |
| t09 | turn | ok | 6.02 | 81 | 0.233% |  |  | 1736 | t09.jsonl.gz |
| t10 | turn | ok | 5.8 | 71 | 0.165% |  |  | 2320 | t10.jsonl.gz |
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
    table, so every spot here takes 5 to 7 s whatever its size, turn spots included.

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

