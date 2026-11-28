# Manager state

The manager session's working notes: who does what, the standing rules, and what is open. A
new manager session starts here instead of from the old session's history. Keep it short:
history belongs in `experiments.md`, not here. Updated 28 Nov 2026.

## Standing rules (Kevin)

- The manager starts, verifies and merges the work of the other sessions. Sessions open PRs and
  don't merge them. Small decisions are the manager's; crucial ones are Kevin's: money beyond what
  he approved, changing B0 beyond bug fixes, gates or rules in `README.md`, rule 4, anything that
  can't be undone.
- Sessions are titled "Phase X - N". Model Opus 5.5, never Fable. Effort (28 Nov 2026): xhigh
  for solver and engine code and experiment design, high for normal coding, medium for write-ups,
  docs and routine checks.
- Cloud commands (launch, stop, cleanup) run on Kevin's Mac. Settings stay in
  `~/.config/pokerscribe/cloud.env`, never in the repo (this repo is public).

## Using tokens well

- Sessions message the manager when they finish; the check-in (every 4 hours) is a safety net.
  Don't read other sessions' event logs unless one looks stuck.
- Results go into files in the repo (`docs/research/runs/...`), not pasted between sessions.
- Briefs are narrow: one task, the files to read, what done looks like. Long jobs run in the
  background with no polling. CI runs the full suite; run it locally only for risky changes.
- When a phase ends, the manager updates this file and Kevin can start a fresh manager session
  from it.

## Now

- **Phase 6 is done** (27 Nov 2026): the gate passed (it512M beat it1M by +147.68 ± 3.89 and B0
  by +16.3 ± 4.1, z +4.00). Cloud cost $4.67; only the checkpoint bucket is left (about $0.41 a
  month). Raw results in `runs/phase6/calibration/`; the entry is "Phase 6: the calibration
  run and the gate" in `experiments.md` (PR 47).
- **Phase 7, planned, waiting on Kevin's cap** (28 Nov 2026). Merged: AIVAT in the arena (PR 52,
  unbiased on its pre-registered checks) and the plan (PR 51, `runs/phase7/README.md`,
  `phase7.json`, `gate.py`). Search with 16 lanes (both players pick at leaves) on it512M. The
  whole run (leaf tables, bench, pilot, gate match, variants `modicum` and `final`, LBR, repeat) is
  one tools/cloud job. The gate is read on AIVAT (z at least 2.5), the plain figure beside it, and
  falls back to the plain figure if AIVAT is missing or a decision is unexplained. At 200bb AIVAT's
  SE ratio was about 0.81 on 192 deals (0.61 at 20bb); the pilot measures it. LBR at about ±50
  (`lbr.chunks` 10; 28 is ±30, 2 is ±110). Estimate 14 h, about $21; cap $30 in
  `cloud.env.example` (±30: $36, cap $50; ±110: $14, cap $20). Nothing launched. Next: Kevin
  picks the cap, "Phase 7 - 2" writes the paste brief, a local Claude session on his Mac (M3, 8 GB)
  launches, watches and cleans up; then gate.py on the results.
- **Phase 7 later work:** preflop search for off-tree raises, the Slumbot match, the GTO Wizard
  Benchmark (README "Decisions" for self-improvement, finer blueprint, value networks, safe
  exploitation). The stale branch `claude/phase7-plan-200bb-aivat-wip` can be deleted (the
  sessions' proxy refuses deletes).
- **Open, not started:** a safe re-solving comparison; huge pages for six-max
  (`runs/phase6/calibration/huge-pages.md`); two small cloud-tool notes from the PR 46 review
  (the max run duration on a poll where the status can't be read; a `_NOT_FOUND` match on the
  listing). Reader bugs wait for Kevin's saved reads (his reads repository doesn't exist yet).
