# tools/cloud: training runs on a rented Google Cloud machine

These tools run one long training job (the Phase 6 heads-up blueprint) on a big Arm machine in
Google Cloud: a c4a-highmem-64 (64 vCPUs, 512 GB), a c4a-highcpu-64 (the same 64 vCPUs with 128 GB,
for a trainer that needs little memory, as the Phase 6 blueprint does), or similar, for hours or
days, usually as a Spot machine, which Google can take back at any time with 30 seconds' warning. You run them on
your own computer; they drive the gcloud CLI. They:

1. **launch**: create the machine (machine type, region, Spot or on-demand, and disk size are
   settings), put the trainer on it (built there for aarch64, or copied as it is), run it under
   systemd so it comes back after a reboot, and print how to watch it;
2. **sync checkpoints**: copy each new checkpoint to a Cloud Storage bucket as soon as it is
   written, keep the last 3 there, and resume from the bucket's newest one when a machine starts
   with nothing newer on its disk;
3. **recover**: start the machine again after a Spot preemption (or make a new one) and resume,
   up to `MAX_RESTARTS` times;
4. **watch**: progress, iterations per second, memory, cost so far, and time since the last
   checkpoint;
5. **keep the results**: the strategy files and other results the trainer writes beside its
   checkpoints go to the bucket too, and all of them are kept (`artifacts`);
6. **stop and clean up**: stop the machine, keep the bucket, and list everything in the project
   still costing money;
7. **cap the cost**: stop everything at `BUDGET_USD`.

Nothing in the repo names a project, bucket, account or key: they come from a settings file kept
outside the repo (Setup, step 5) or from environment variables.

All of it can be tried without spending money: `python -m tools.cloud local-test` runs the whole
cycle on your computer, with a fake trainer and a local folder standing in for the bucket. See
"Testing without money".

## Contents

| File | What it is |
|---|---|
| `__main__.py` | the commands: `python -m tools.cloud <command>` |
| `settings.example.env` | every setting, explained. Copy it out of the repo and fill it in |
| `settings.py` | reads the settings and checks them |
| `control.py` | what the commands do (launch, watch, recover, stop, resume, cleanup, check) |
| `gce.py` | the gcloud commands for machines, quotas and leftovers |
| `supervisor.py` | runs on the machine: runs the trainer, syncs checkpoints, reports, keeps the cap |
| `vm/startup.sh` | the machine's startup script: installs the bundle and the systemd service |
| `fake_trainer.py` | a small program that pretends to train and keeps the trainer contract |
| `local_test.py` | the local end-to-end test (`local-test`), and the dress rehearsal with a real trainer |
| `tests/` | the tests; they run with the rest (`python -m pytest`) |

## Setup (once)

1. **gcloud.** Install the Google Cloud CLI (`brew install --cask google-cloud-sdk`, or Google's
   installer), then:

   ```
   gcloud auth login
   gcloud components install beta      # for the 2-minute Spot notice (step "Spot preemption")
   ```

   The tools need Python 3.9 or later and nothing else (standard library only).

2. **A project with billing.** Create a project (or pick one) and link a billing account to it. A
   free trial account can't run more than 8 vCPUs at a time, so upgrade it to a paid account
   first. Also set a budget alert on the billing account (Billing, Budgets & alerts). It only
   sends email, but it doesn't depend on these tools at all.

3. **The APIs.**

   ```
   gcloud services enable compute.googleapis.com storage.googleapis.com --project <PROJECT>
   ```

4. **Quota: 64 C4A vCPUs in us-central1.** New projects have little or no C4A quota. In the
   console, open IAM & Admin, Quotas & System Limits, filter for the C4A CPUs quota of the
   Compute Engine API in region us-central1, select it, choose Edit, and ask for 64 (the
   machine's vCPU count). Check the "CPUs (all regions)" quota the same way (`CPUS_ALL_REGIONS`):
   it must have room for 64 too, so ask for 64 or more if it doesn't.
   - Don't ask for preemptible quota. A Spot machine counts against the normal C4A quota when
     the project has no preemptible quota.
   - A stopped machine doesn't use CPU quota, and `recover` deletes the old machine before it
     makes a new one, so 64 is enough.
   - A request can be granted in minutes or take a couple of days. A new billing account may be
     asked for some payment history first.
   - If `launch` fails with a quota error that names a disk (Hyperdisk Balanced capacity), ask
     for that quota the same way.
   - `python -m tools.cloud check` shows the C4A quota and how much of it is used. It looks for a
     quota called `C4A_CPUS`, which follows Google's naming for the other families but hasn't
     been checked on a real project. If `check` says it found none, read the Quotas page.

5. **The settings file.**

   ```
   mkdir -p ~/.config/pokerscribe
   cp tools/cloud/settings.example.env ~/.config/pokerscribe/cloud.env
   ```

   Fill in at least `PROJECT`, `BUCKET` (bucket names are global, so pick a new one; launch makes
   it), `RUN_NAME`, `BUDGET_USD`, the price for the provisioning you chose
   (`SPOT_PRICE_PER_HOUR` or `STANDARD_PRICE_PER_HOUR`: there is no built-in price, on purpose),
   and the trainer (see "The trainer"). Every setting is explained in the file.
   - Keep the file outside the repo. `check` and `launch` refuse a settings file that git tracks.
   - Any setting can also be set as an environment variable with a `PSCLOUD_` prefix, which wins
     over the file: `PSCLOUD_BUDGET_USD=25 python -m tools.cloud launch`.
   - Another file: `python -m tools.cloud --settings <file> <command>`, or `PSCLOUD_SETTINGS=<file>`.

6. **A service account for the machine (recommended).** Without `SERVICE_ACCOUNT` the machine
   runs as the project's default compute service account, which often has the Editor role on
   the whole project. The machine only needs to read and write the bucket, so make an account
   that can do only that. Make the bucket first, so the role can be given on it alone (launch
   then uses it as it is):

   ```
   gcloud iam service-accounts create pscloud-trainer --project <PROJECT>
   gcloud storage buckets create gs://<BUCKET> --project <PROJECT> --location us-central1 \
       --uniform-bucket-level-access --public-access-prevention --soft-delete-duration=0
   gcloud storage buckets add-iam-policy-binding gs://<BUCKET> \
       --member serviceAccount:pscloud-trainer@<PROJECT>.iam.gserviceaccount.com \
       --role roles/storage.objectAdmin
   ```

   Then set `SERVICE_ACCOUNT=pscloud-trainer@<PROJECT>.iam.gserviceaccount.com` in the settings.

7. **Check.**

   ```
   python -m tools.cloud local-test          # the whole cycle on this computer, about 10 s
   python -m tools.cloud check               # settings, login, project, APIs, machine, quota, bucket
   python -m tools.cloud launch --dry-run    # every command launch would run; runs none
   ```

8. **The cheap real test** (a few cents, see "Testing without money") before the first big run.

## The trainer

Any program that keeps this contract:

```
<trainer> --config <file> --checkpoint-dir <dir> [--resume]
```

- `--resume` is passed when a checkpoint is in `<dir>`, and only then.
- Write a checkpoint every few minutes, atomically: to a temporary name (ending in `.tmp` or
  `.part`, or starting with a dot), then rename it. The final name must match
  `CHECKPOINT_PATTERN` (default `*.ckpt`). One checkpoint is one file.
- The supervisor never deletes files in `<dir>`. Either reuse one name (simplest: the supervisor
  pins the version it is uploading, so the next rename can't spoil the upload) or delete older
  checkpoints yourself.
- On SIGTERM: save a checkpoint, then exit (75 is a good code). Be done within about a minute
  (see "Spot preemption").
- Exit 0 only when the training is finished. Any other exit that wasn't asked for counts as a
  crash: the supervisor restarts the trainer with `--resume`, up to `MAX_TRAINER_CRASHES` times,
  then marks the run failed.
- Optional: progress lines on stdout, one JSON object per line, such as
  `{"iterations": 1200000, "target_iterations": 200000000}`. `watch` shows them with iterations
  per second (over the last 10 minutes) and the time left. All output is kept in the logs.
- Optional: results (artifacts). Any other file in `<dir>` whose name matches
  `ARTIFACT_PATTERNS` (default `*.bps,*.jsonl`: the blueprint's strategy files, `stages.jsonl`
  and its `log.jsonl`) goes to `artifacts/<name>` in the bucket once it has not changed for a
  few seconds, again each time it changes, and is never deleted there. A new machine gets all of
  them back before the trainer starts, so a trainer that compares a result with the one before
  (the blueprint's change measure) finds it on the disk. Write big ones whole and rename them,
  as checkpoints; small ones may be appended to. `none` turns it off.

How the trainer gets to the machine:

- `TRAINER_MODE=build`: the engine's source (`ENGINE_DIR`, default `engine/`, without `target/`)
  goes into the bundle, and the machine installs Rust (`RUST_TOOLCHAIN`) and runs
  `cargo build --release --bin <TRAINER_CARGO_BIN>` (plus `-p <TRAINER_CARGO_PACKAGE>`,
  `--features <TRAINER_CARGO_FEATURES>`, and `--locked` when there is a `Cargo.lock`). That is a
  native Arm build, so there is no cross-compiling on the Mac. The first machine of a run saves
  the built program to the bucket; later machines of the run download it instead of building.
- `TRAINER_MODE=copy`: `TRAINER_PATH` is copied as it is. It must be an aarch64 Linux program
  (the settings check reads its header) or a script, such as `tools/cloud/fake_trainer.py`.
- `TRAINER_CONFIG` is copied and passed as `--config`. `TRAINER_ARGS` adds arguments, such as
  `--threads 64`.
- `TRAINER_FILES` (optional): files or folders the trainer reads, such as the bucket tables. Each
  goes into the bundle and is installed at `/opt/pscloud/bundle/files/<its name>` (a folder's
  files keep their place inside it), so a config names them there:
  `"abstraction": "/opt/pscloud/bundle/files/k200"`. `check` and `launch` refuse a config that
  names a path there that `TRAINER_FILES` doesn't provide.

The trainer's sizes can be given, and are then checked before anything is rented:
`TRAINER_MEMORY_GB` (its peak memory, measured) against the machine type's memory (with 10% to
spare; `check` also compares it with the memory Google reports), and `CHECKPOINT_GB` with
`ARTIFACTS_GB` against `DISK_SIZE_GB` (4 checkpoints, all the artifacts and 30 GB for the
system). `watch` warns when the trainer's peak passes 90% of the machine's memory.

## Commands

Run them from the repo root: `python -m tools.cloud <command>`.

| Command | What it does |
|---|---|
| `check` | everything that can be checked without spending money |
| `launch [--dry-run] [--force]` | makes the bucket if needed, uploads the bundle, creates the machine, prints how to watch. `--force` launches on a run that is already done |
| `watch [--every 60]` | progress, speed, memory, checkpoints, cost, restarts |
| `recover [--once]` | keeps the run going through Spot preemptions: leave it running |
| `logs [--supervisor] [-n 60]` | the end of the trainer's (or the supervisor's) output, from the bucket |
| `stop` | the trainer saves, the last checkpoint is uploaded, the machine powers off. Keeps the disk and the bucket |
| `resume` | after a stop (or after raising `BUDGET_USD`): starts the machine again, or makes a new one |
| `artifacts [--download DIR] [--only GLOB]` | lists the run's artifacts in the bucket (strategy files, `stages.jsonl`); with `--download`, copies the ones `DIR` doesn't have yet (`stages.jsonl` every time) |
| `cleanup [--yes]` | stops the run, deletes the machine and its disk, keeps the bucket, lists what is left |
| `leftovers` | everything in the project that still costs money: machines, disks, IPs, snapshots, images, buckets |
| `local-test [--keep DIR]` | the whole cycle on this computer: fake trainer, folder as bucket, SIGTERM, resume |
| `local-test --trainer T --config C [--files F] [--trainer-args A]` | a dress rehearsal of a real run on this computer (see "Testing without money") |

A run:

```
python -m tools.cloud check
python -m tools.cloud launch
caffeinate -i python -m tools.cloud recover     # in a second terminal; leave it running
python -m tools.cloud watch --every 60
```

`watch` looks like this:

```
run         hu-blueprint-1   bucket gs://<BUCKET>/runs/hu-blueprint-1
machine     ps-hu-blueprint-1  us-central1-a  c4a-highmem-64  SPOT  RUNNING for 3 h 10 min
trainer     running (resumed), up 3 h 08 min, crashes 0
progress    41,250,000 iterations of 200,000,000 (20.6%), 3,810 per second, about 11 h 34 min left (reported 42 s ago)
memory      trainer 302.0 GB (peak 305.0 GB), machine 311.0 of 541.0 GB used
checkpoint  written 11 min ago (blueprint.ckpt, 4.8 GB); uploaded 10 min ago; 3 in the bucket
artifacts   9 in the bucket; last strategy-128000000.bps 25 min ago  (python -m tools.cloud artifacts --download DIR)
cost        about $13.36 so far (at the last report: machine $13.10, IP $0.03, disk $0.20); cap $40.00 (33%); at $2.08/h the cap is reached in 12 h 49 min
restarts    1 of 10 (last: start at 2026-11-27 06:02 UTC, preempted at 2026-11-27 05:58 UTC)
report      40 s ago
```

If the machine runs but hasn't reported for a while, `watch` adds a WARNING line with the command
that shows the machine's startup output.

When the trainer finishes, the supervisor marks the run done and powers the machine off, and
`recover` exits. Then `python -m tools.cloud cleanup` deletes the machine and its disk, and the
checkpoints stay in the bucket. Delete the bucket yourself once you have what you need from it:
`gcloud storage rm -r gs://<BUCKET>`.

## How it works

### The bucket

```
gs://<BUCKET>/runs/<RUN_NAME>/
  bundle/          what the machine installs: manifest.json, supervisor.py, run.json, the config,
                   the trainer (or the engine's source, and the saved build)
  checkpoints/     <sequence>-<UTC time>-<name>, e.g. 00000012-20261127T093000Z-blueprint.ckpt
                   (the last KEEP_CHECKPOINTS of them)
  artifacts/       the trainer's other results under their own names (ARTIFACT_PATTERNS), all kept
  status.json      the supervisor's report, every STATUS_SECONDS
  state.json       the run's final state once it has one: done, failed, budget or stopped
  sessions/        one file per boot of a machine; the cost estimate comes from these
  restarts.json    every start and new machine that recover or resume made
  launch.json      what launch made
  control/stop     written by stop; the supervisor and recover both look for it
  logs/            the trainer's and the supervisor's output, the startup logs
```

The sequence number makes the newest checkpoint the last in order, whatever the clocks say. Launch
makes the bucket in `REGION` with uniform access, public access prevention, and soft delete off
(with soft delete on, every replaced checkpoint would stay, and be billed, for 7 more days).

### On the machine

`launch` creates the machine with `vm/startup.sh` as its startup script and two metadata values:
where the run is in the bucket, and which bundle version to install. At every boot the script:

1. installs gcloud and Python if the image lacks them;
2. downloads the bundle, once per version (a reboot of the same machine skips this), with the
   `TRAINER_FILES` under `/opt/pscloud/bundle/files/`;
3. in build mode, installs Rust and builds the trainer, or downloads the build that an earlier
   machine of the run saved;
4. writes the systemd service `pscloud-trainer` and starts it.

If any step fails, the script uploads its log to `logs/`, marks the run failed, and powers the
machine off, so a broken setup doesn't bill for hours.

systemd runs the supervisor (`supervisor.py`), and the supervisor runs the trainer. The service is
enabled, so a reboot starts it again, and it resumes. `Restart=on-failure` brings the supervisor
back if it dies. If it dies 5 times within an hour, `pscloud-on-failure` uploads the journal,
marks the run failed, and powers the machine off.

The supervisor:

- records the boot as a session, for the cost estimate;
- stops at once if the budget is spent or a stop was requested;
- downloads the bucket's newest checkpoint if it is newer than anything on the disk (a new
  machine has an empty disk; a machine started again after a preemption usually has a newer
  checkpoint on its own disk);
- runs the trainer, with `--resume` when a checkpoint is on the disk;
- uploads each new checkpoint as soon as it is complete, checks its size in the bucket, and only
  then deletes the bucket's checkpoints beyond the newest `KEEP_CHECKPOINTS`;
- puts back the bucket's artifacts that the disk lacks (a new machine), and uploads each new or
  changed artifact after the checkpoints (all are kept);
- writes `status.json` every `STATUS_SECONDS`: progress, iterations per second, memory (the
  machine's, and the trainer's current and peak), checkpoints, and cost;
- when Google gives notice of a preemption, the machine shuts down, the budget is reached, or
  `stop` asks: sends the trainer SIGTERM, waits up to `STOP_GRACE_SECONDS` for it to save, then
  uploads the last checkpoint (taking up to `FINAL_UPLOAD_SECONDS`);
- restarts the trainer if it crashes;
- writes the final state and powers the machine off when the run is done, failed, out of
  budget, or stopped.

### Spot preemption

The machine is created with `--instance-termination-action=STOP`. A preempted machine is stopped,
not deleted, so its disk and the checkpoint the trainer saved last are kept.

With `PREEMPTION_NOTICE_SECONDS=120` it is also created with
`gcloud beta compute instances create ... --preemption-notice-duration=120s`. As Google documents
it, the metadata value `instance/preempted` then turns TRUE 2 minutes before the usual shutdown,
and the machine is powered off up to 30 seconds after the shutdown starts. The supervisor checks
for the notice every 2 seconds and stops the trainer at once, so the trainer and the last upload
have about 2.5 minutes. Without the notice (`0`, or if it doesn't work on C4A) they have the 30
seconds only. A checkpoint that the 30 seconds cut off before it reached the bucket is still on
the disk, and it is used when the same machine starts again. Only a new machine would resume from
the bucket's older one.

`recover` looks at the run every `RECOVER_POLL_SECONDS` and decides, in this order:

| What it sees | What it does |
|---|---|
| the run is done, failed, budget or stopped | exits |
| a stop was requested | exits |
| the machine is running (or starting) | waits |
| the cost is within `BUDGET_MARGIN_MINUTES` of the cap, or less than 10 minutes of budget is left | gives up |
| `MAX_RESTARTS` restarts already used | gives up |
| no machine | makes a new one, which resumes from the bucket |
| the machine was stopped by a preemption | starts it again, which resumes from its disk (or from the bucket if that is newer) |
| the machine was stopped some other way | gives up, unless `RESTART_ANY_STOP=true`: a stop from the console is left alone |
| `RECREATE_AFTER_FAILED_STARTS` starts in a row failed for lack of capacity | deletes the machine and makes a new one in the next zone of `ZONES` |

A preemption is recognised from the supervisor's last report (its stop reason is "preempted") or
from GCE's `compute.instances.preempted` operation. Each start and each new machine counts as one
restart; `resume` doesn't count. Creating a machine tries the zones of `ZONES` in order when one
has no capacity.

### The budget

Three separate layers stop the spending:

1. **The supervisor.** When its cost estimate reaches `BUDGET_USD` minus `BUDGET_MARGIN_MINUTES`
   of running, it stops the trainer (which saves), uploads the last checkpoint, marks the run
   "budget", and powers the machine off.
2. **Google itself.** Every start sets the machine's `--max-run-duration` to the running time the
   rest of the budget buys at the current price, so GCE stops the machine at the cap even if the
   supervisor, the startup script and your computer all fail.
3. **recover, resume and launch.** They don't start or create a machine once the budget is spent,
   or when less than 10 minutes of it is left.

To go on after a "budget" stop, raise `BUDGET_USD` and run `resume`.

### What the cost estimate counts

It counts the machine and its external IP for each boot, from the boot to the last report plus
one status interval, at the prices in the settings, and the disk for every hour since the first
boot, running or stopped. It doesn't count:

- the bucket's storage (3 checkpoints of 5 GB cost well under a dollar a month; Standard storage
  is about $0.02 per GB per month);
- requests to the bucket and traffic within the region (small);
- downloading checkpoints out of Google Cloud, which is billed per GB;
- price changes: the price is the one in the settings, not the live one.

The billing console is the real figure, but it lags by hours. The estimate is what the cap uses.

### Disk speed and big checkpoints

On the free Hyperdisk Balanced baseline (140 MiB/s), writing a 5 GB checkpoint takes about 35
seconds, and reading it back for the upload about as long again. That fits in the 2.5 minutes the
notice gives, but not in 30 seconds. For checkpoints of several GB, set `DISK_THROUGHPUT_MBPS`
(say 400) and `DISK_IOPS`, which cost extra. Also checkpoint often enough: a preemption costs the
work done since the last checkpoint that reached the bucket, plus a few minutes for the boot. The
gap between "written" and "uploaded" in `watch` shows how long an upload takes; look at it during
the cheap real test.

## Testing without money

- **The tests:** `python -m pytest tools/cloud/tests` (they also run with the rest of the tests).
  Unit tests; the supervisor with the fake trainer; the startup script run for real in a sandbox
  (systemctl, cargo and apt-get replaced by stubs, a folder for the metadata server, a fake
  gcloud for the bucket); and whole runs through an in-memory Compute Engine: preemptions, a new
  machine in another zone, the budget stops, and the restart limit.
- **`python -m tools.cloud local-test`:** the real supervisor and the fake trainer, with a local
  folder as the bucket. Machine 1 trains until halfway, then every process gets SIGTERM (as at a
  preemption), the trainer saves, and the checkpoint is uploaded. Machine 2 starts with an empty
  disk, downloads the checkpoint, resumes and finishes. It checks that the trainer resumed where
  it saved, that the final hash matches a run that never stopped, that 3 checkpoints are kept,
  and that the cost covers both sessions:

  ```
  machine 1: fresh start
  machine 1: at iteration 210, sending SIGTERM to every process (Google stops the machine)
  machine 1: trainer saved at iteration 213, uploaded as checkpoints/00000007-20261127T003432Z-fake.ckpt; 3 checkpoint(s) in the bucket
  machine 2: new machine, empty disk
  machine 2: resumed at iteration 213, finished at 400; the hash matches an uninterrupted run
  bucket: 3 checkpoints kept (00000011-..., 00000012-..., 00000013-...)
  cost recorded over 2 sessions: $0.037360 (seconds at Spot prices)
  state: done; machine 2 powered off
  local test passed
  ```

- **`python -m tools.cloud local-test --trainer T --config C`:** a dress rehearsal of a real run,
  with the real trainer and its real config, at this computer's thread count
  (`--trainer-args "--threads 4"`). Paths under `/opt/pscloud/bundle/files/<name>` in the config
  point at the local copies given with `--files` (the same as `TRAINER_FILES`); nothing else in
  it changes. Machine 1 starts fresh and gets SIGTERM once `--sigterm-after` stages (default 2)
  are in the bucket; machine 2 starts with an empty disk, gets the checkpoint and every artifact
  back, resumes, and once `--stop-after` stages (default 4) are in the bucket the stop marker is
  written, as `stop` does. It checks that the SIGTERM save was uploaded and resumed from at
  exactly its iteration, that the first stage after the resume was compared with the one before
  it (so the artifacts came back), that every stage is there once and in order, and that the run
  ends "stopped" with the last save uploaded. It prints the times that matter for a paid run and
  the trainer's memory; `--report FILE` saves them. The Phase 6 rehearsal:
  `docs/research/runs/phase6/README.md`, "The dress rehearsal".
- **`python -m tools.cloud launch --dry-run`:** prints every gcloud command and upload launch
  would make, as for a new run, and runs none of them (it doesn't even need a login).

### The cheap real test (a few cents)

Before the first big run, do the whole thing for real on a 1-vCPU machine with the fake trainer.
Make a second settings file, `~/.config/pokerscribe/cloud-test.env`, as a copy of `cloud.env` with:

```
RUN_NAME=cloud-test-1
MACHINE_TYPE=c4a-standard-1
DISK_SIZE_GB=20
SPOT_PRICE_PER_HOUR=<the current price of c4a-standard-1>
BUDGET_USD=1
TRAINER_MODE=copy
TRAINER_PATH=tools/cloud/fake_trainer.py
TRAINER_CONFIG=<a file holding {"iterations": 20000, "iteration_seconds": 0.05, "checkpoint_seconds": 60, "checkpoint_bytes": 100000000}>
RESTART_ANY_STOP=true
```

That trains for about 17 minutes and writes a 100 MB checkpoint every minute. Then, with
`T="--settings $HOME/.config/pokerscribe/cloud-test.env"`:

1. `python -m tools.cloud $T launch`, then `python -m tools.cloud $T watch --every 30`. Within a few
   minutes: a report, progress, a checkpoint written and then uploaded.
2. Stop the machine as Google would: `gcloud compute instances stop ps-cloud-test-1 --zone <ZONE>`.
   The shutdown sends SIGTERM, so `watch` shows the stop reason "shutdown" and a fresh checkpoint.
3. `python -m tools.cloud $T recover --once` starts it again (because of `RESTART_ANY_STOP=true`),
   and `watch` shows the trainer "resumed".
4. `python -m tools.cloud $T cleanup --yes` deletes the machine and its disk. Then
   `python -m tools.cloud $T resume` makes a new machine, which resumes from the bucket.
5. Let it finish, then compare the digest on the `"event": "done"` line of
   `python -m tools.cloud $T logs` with
   `python -c "from tools.cloud import fake_trainer; print(fake_trainer.expected_digest(20000))"`.
6. `python -m tools.cloud $T cleanup --yes`, then `leftovers`: only the bucket should be left.
   Delete the test's folder in it: `gcloud storage rm -r gs://<BUCKET>/runs/cloud-test-1`.

## Limits, and what hasn't been checked

- **Nothing here has run on real Google Cloud yet.** Every gcloud flag was checked offline against
  the help of gcloud 570. Not checked: the exact output of `gcloud storage ls -l` (the supervisor
  reads it to list the checkpoints), the field names `gcloud storage buckets describe` returns
  (for check's soft delete and location lines), the name of the C4A quota, the Hyperdisk price,
  and whether the beta 2-minute notice works on C4A. The cheap real test covers all but the last
  two.
- **`recover` runs on your computer.** If the computer sleeps or loses its network, nothing starts
  the machine again. The run is safe meanwhile (a stopped machine, the checkpoints in the bucket,
  only the disk billing), but it doesn't go on. Run `recover` under `caffeinate -i`, on power,
  with the lid open, or on a computer that doesn't sleep.
- **One checkpoint is one file.** A trainer that writes a folder per checkpoint needs a change
  in the supervisor.
- **The supervisor doesn't delete checkpoints from the machine's disk** (see "The trainer").
- **One machine per run.** Two runs at once need two `RUN_NAME`s, and quota for both.
- **The cost is an estimate** from the prices in the settings. Read the prices before each run.

## Checklist before a paid run

- [ ] `python -m pytest tools/cloud/tests` and `python -m tools.cloud local-test` pass.
- [ ] The real trainer keeps the contract: run it locally on a small config, send it `kill -TERM`
      halfway, check that it saved and exited, then run it with `--resume` and check that it goes
      on from the saved point and finishes with exit code 0.
- [ ] The trainer's memory fits the machine (512 GB on c4a-highmem-64, 128 GB on c4a-highcpu-64)
      with room to spare: measured at a smaller size and scaled up, and set as
      `TRAINER_MEMORY_GB` so `check` compares it with the machine.
- [ ] The cheap real test has passed in this project: report, upload, stop and restart, a new
      machine resuming from the bucket, cleanup.
- [ ] `python -m tools.cloud check` ends with "all checks passed": login, APIs, machine type,
      quota, beta, bucket.
- [ ] The prices in the settings are today's (`SPOT_PRICE_PER_HOUR` or `STANDARD_PRICE_PER_HOUR`,
      and `DISK_PRICE_PER_GB_MONTH`), and `BUDGET_USD` is what you are willing to spend on this run.
- [ ] A budget alert is set on the billing account (Setup, step 2).
- [ ] `RUN_NAME` is new, or its checkpoints in the bucket are the ones to resume from.
- [ ] The checkpoints fit: `DISK_SIZE_GB` holds 4 of them, the artifacts and 30 GB (set
      `CHECKPOINT_GB` and `ARTIFACTS_GB` and `check` says so); with checkpoints of several GB,
      `DISK_THROUGHPUT_MBPS` is raised; the trainer saves within a minute of SIGTERM.
- [ ] `TRAINER_FILES` lists everything the config names under `/opt/pscloud/bundle/files/`.
- [ ] `TRAINER_CONFIG` and `TRAINER_ARGS` are what you mean to train (iterations, 64 threads).
- [ ] `python -m tools.cloud launch --dry-run` shows the machine type, zone, Spot, disk size and
      maximum run duration you expect.
- [ ] A computer that won't sleep is ready to run `caffeinate -i python -m tools.cloud recover`.
- [ ] Afterwards: `cleanup`, then `leftovers` shows only the bucket.
