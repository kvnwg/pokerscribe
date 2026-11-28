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
- **Phase 7 is next** (Kevin said go, 28 Nov 2026; "Phase 7 - 2" is writing the plan): Modicum-style search on the 200bb blueprint
  (`engine/crates/search`). Its 200bb leaf tables are about 9.7 GB and 134 core-hours: a cloud
  build, roughly $3 to $5. Kevin's Mac (M3, 8 GB) can't hold the tables, so the match runs in
  the cloud too; a local Claude session on his Mac runs the commands (Remote Control can't share
  folders with cloud sessions in his app version). The exact cap goes to Kevin with the plan before any launch.
- **Open, not started:** a safe re-solving comparison; huge pages for six-max
  (`runs/phase6/calibration/huge-pages.md`); two small cloud-tool notes from the PR 46 review
  (the max run duration on a poll where the status can't be read; a `_NOT_FOUND` match on the
  listing). Reader bugs wait for Kevin's saved reads (his reads repository doesn't exist yet).
