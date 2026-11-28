# Phase 7 launch brief

For a local Claude Code session on Kevin's Mac, in `~/pokerscribe`. Kevin pastes everything
below the line as one message. The runbook is `README.md` in this folder; where the two differ,
this brief wins (it never raises the cap).

---

You are launching and watching the Phase 7 run (cloud, about 12 to 14 hours, capped at $30), then
reporting its result. The runbook is `docs/research/runs/phase7/README.md`, "The run, step by
step"; read only what a step below needs.

**Rules, for the whole session**
- Never write a project, bucket, service account or billing account name in a reply, a file you
  write or the repo. Tool output will show them; write `<project>`, `<bucket>`, `<account>`.
- Never raise `BUDGET_USD` (30). Never `resume` after the cap stops the run.
- On anything unexpected, stop and ask Kevin. Don't stop, resume or delete anything he hasn't
  asked for here.
- Don't commit or push. Rule 4 holds: nothing on live sites, nothing for real money.

**1. Pull.** Nothing is built on the Mac: `tools/cloud` and `gate.py` are standard-library
Python, and the rented machine builds the Rust job from this checkout's `engine/`, so the tree
must be main as it is.
```
cd ~/pokerscribe && git checkout main && git pull --ff-only
git merge-base --is-ancestor 473c700 HEAD && echo ok    # the plan with AIVAT
git status --short                                     # must print nothing
```

**2. Checks before launch.** Every command after this uses
`P="--settings $HOME/.config/pokerscribe/cloud-phase7.env"` (a separate file, so Phase 6's
`cloud.env` stays as it is). Shell variables don't carry over between your commands, so set `P`
in each one.
- If `~/.config/pokerscribe/cloud-phase7.env` is missing: copy
  `docs/research/runs/phase7/cloud.env.example` there, then fill only its empty `PROJECT`,
  `BUCKET` and `SERVICE_ACCOUNT` from `~/.config/pokerscribe/cloud.env` with a small script that
  never prints the values and never edits `cloud.env`. If it exists, don't overwrite it.
- Then, without printing values:
  ```
  F=~/.config/pokerscribe/cloud-phase7.env
  grep -cE '^(PROJECT|BUCKET|SERVICE_ACCOUNT)=.+' $F     # 3
  grep -x 'BUDGET_USD=30' $F                              # one line
  K='^(PROJECT|BUCKET|SERVICE_ACCOUNT|SPOT_PRICE_PER_HOUR)='
  diff <(grep -vE "$K" $F) <(grep -vE "$K" docs/research/runs/phase7/cloud.env.example) && echo same
  ```
  Anything else: stop and ask Kevin.
- Ask Kevin for today's Spot price of c4a-highcpu-64 in us-central1 and put it in
  `SPOT_PRICE_PER_HOUR` (the file has $1.445888 from 27 Nov 2026; keep it if he has none).
- The files the job takes from the Mac: `ls -l ~/phase6/run1/strategy-512000000.bps` and
  `ls ~/abstraction/k200`. If either is missing, stop and ask Kevin.
- `python -m tools.cloud $P leftovers`: only the bucket may be listed. A machine, disk, IP,
  snapshot or image: stop and ask Kevin.
- `python -m tools.cloud $P check` must end with "all checks passed".
- `python -m tools.cloud $P launch --dry-run` must show c4a-highcpu-64, SPOT, a 120 GB disk and
  `--max-run-duration` of about 73,000 s (20 h 19 min, the $30 cap at about $1.48 an hour).

**3. Launch.**
```
mkdir -p ~/phase7
python -m tools.cloud $P launch
```
Then ask Kevin to open a second Terminal window, keep the Mac on power and awake, and run there
(the recovery loop restarts the machine after a Spot preemption; it must outlive this session):
```
cd ~/pokerscribe && caffeinate -i python -m tools.cloud --settings $HOME/.config/pokerscribe/cloud-phase7.env recover 2>&1 | tee -a ~/phase7/recover.log
```

**4. Watch** every 30 to 60 minutes, not more often: one `python -m tools.cloud $P watch` (no
`--every`) and `tail -5 ~/phase7/recover.log`. Healthy:
- machine RUNNING; trainer running, crashes 0; progress reported in the last few minutes;
- progress moves through the plan: the leaf build to 544,000,000 deals, then the bench, the
  pilot, the gate's chunks of 2,000 deals, the variants, LBR runs and the repeat;
- memory: the trainer under 70 GB of 128;
- artifacts growing, no failed uploads;
- cost rising about $1.48 an hour, near $21 at the end, under the $30 cap;
- a restart after a preemption is normal (at most 10).

Stop and ask Kevin if `recover` exits before the run is done (budget, restarts used up, a stop
not by a preemption, setup stuck), if progress isn't reported for 30 minutes, on any crash,
repeated failed upload, error or WARNING, if memory passes 70 GB, or if the cost will pass $30
before the end. If the run ends with "a street is over its bound: no match was played", that is
by the plan: go to step 5.

**5. On finish** (`recover.log` ends with "finished: the run is done" and `recover` has
exited; a run that ends failed, budget or stopped is unexpected):
```
python -m tools.cloud $P artifacts --download ~/phase7/run --only '*.json'
python -m tools.cloud $P artifacts --download ~/phase7/run --only '*.deals'
python3 docs/research/runs/phase7/gate.py ~/phase7/run; echo "gate.py exit $?"
python -m tools.cloud $P watch                 # the final cost line
python -m tools.cloud $P cleanup --yes         # deletes the machine and its disk, keeps the bucket
python -m tools.cloud $P leftovers             # only the bucket (the parts, about $0.44 a month)
```

**6. Report.** Write `~/phase7/report.md` with:
- gate.py's output and `~/phase7/run/summary.md`, verbatim, and gate.py's exit code;
- the final cost line;
- the leftovers after cleanup, as kind and dollars a month, names replaced as above;
- every incident with its UTC time (preemptions, restarts, warnings, what Kevin decided);
- the launch and end times, and `git rev-parse --short HEAD`.

Check the file for any project, bucket or account name, then tell Kevin it is ready to send to
the manager session (or to paste its text back there).
