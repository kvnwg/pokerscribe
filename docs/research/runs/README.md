# Raw experiment runs

The scripts and logs behind the results in `../experiments.md`, kept as they were run. Paths inside
point at the old cloud workspace (`/home/claude/PokerScribe`); run from the repo root instead.

Phase 1 (26 Nov 2026), run from the repo root:

- `phase1_gate.sh`: the gate runs, with each run's pass rule written in its header before it
  ran; `phase1_gate_summary.py <folder>` rebuilds `phase1_gate/summary.md` and
  `phase1_gate_404/summary.md` from the per-hand JSON (not committed; the script rebuilds it).
- `phase1_variance_split.py`: where the variance left in a comparison comes from
  (`phase1_variance/`).
- `weakness/`: the weakness report on the baseline (seeds 11 and 12, the held-out table) and
  the planted-flaw checks, from `tools/weakness.py`.
- After run 3: `phase1_hidden_explore.py` and `phase1_hidden_fit.py` (the hidden-cards estimate
  and its value weights), `phase1_redeal_explore.py` with `phase1_redeal_summary.py` (redealt
  replays, `phase1_redeal/`), and gate run 4: `phase1_gate4.sh` with `phase1_gate4_summary.py`
  (`phase1_gate4/summary.md`).
- Gate run 5: `phase1_gate5.sh` (the same summary script, `phase1_gate5/summary.md`), and
  `phase1_gate5_noise.py`, written after its result, on how much one run's ratios move by
  chance (`phase1_gate5/noise.md`).
- The replays against the raw difference (after the merge with the Phase 2 work):
  `phase1_replay_explore/run.sh` rebuilds every look at `bet_size: 0.5` (every play of each
  hand that differs, on the gate runs' seeds and on seeds 41 to 48, and the tests on them, one
  `.txt` per test), and `phase1_replay_check.sh`, with its rule in the header before it ran,
  the confirming check on seeds 51 to 66 (`phase1_replay_check/summary.md`).

Phase 2 (26 Nov 2026):

- `phase2_solver_b0.sh`: `river_solver` against B0, with the four stages' rule in its header
  before any of its seeds were played; `phase2_solver_b0_summary.py <stage>` rebuilds
  `phase2_solver_b0/stage*.md`. It ran before the merge with main's river ranges, so running it
  again now gives different numbers (see its header).
- `phase2_solver.py`: the numbers behind "river solver and push-or-fold"; `phase2_ranges.py`:
  how well the river ranges from the betting predict real cards, and their cost;
  `phase2_budget.py`: the solver's time by pot size, and whether a simulator run repeats
  exactly. Each with its `.log` (`experiments.md`, Phase 2).
