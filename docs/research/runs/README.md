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
