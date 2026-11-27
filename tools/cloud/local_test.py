"""A whole run on this computer, with no cloud and no cost: `python -m tools.cloud local-test`.

The real supervisor runs the fake trainer, with a local folder standing in for the bucket:

1. Machine 1 starts from nothing and trains. Halfway through, every process on it gets
   SIGTERM at once, as systemd does when Google stops a Spot machine. The trainer saves; the
   supervisor uploads that checkpoint and exits, leaving the run open (not a final state).
2. Machine 2 starts with an empty disk, as a new machine would. Its supervisor downloads the
   newest checkpoint from the bucket and starts the trainer with --resume. The run finishes.
3. Checks: the second trainer resumed where the first one saved, the final hash equals that
   of a run that never stopped, the bucket keeps exactly the last 3 checkpoints, both
   sessions were recorded for the cost, the run's state is "done", and the power-off command
   ran.

With ``--trainer`` and ``--config`` it is a dress rehearsal of a real run instead
(``run_trainer``): the real supervisor runs that trainer on that config, at this computer's
thread count (``--trainer-args "--threads 4"``), with the same three steps and stage results
as the trainer writes them (stages.jsonl and a file per stage, the artifacts):

1. Machine 1 starts fresh and gets SIGTERM once ``--sigterm-after`` stages are in the bucket.
2. Machine 2 starts with an empty disk: the supervisor puts back the newest checkpoint and every
   artifact, the trainer resumes, and once ``--stop-after`` stages are in the bucket the stop
   marker is written, as ``python -m tools.cloud stop`` does.
3. Checks: the SIGTERM save was uploaded and machine 2 resumed at exactly that iteration, the
   artifacts came back (the first stage after the resume was compared with the one before
   it), every stage is in stages.jsonl once and in order, and the run's state is "stopped"
   with the last save uploaded. It prints the times that matter for a paid run (starting,
   saving, uploading, putting back) and the trainer's memory.

Paths under /opt/pscloud/bundle/files/<name> in the config (where TRAINER_FILES go on the
machine) point at the local copies given with ``--files``; nothing else in the config changes.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from . import fake_trainer
from .settings import VM_FILES
from .supervisor import (ARTIFACTS, CHECKPOINTS, SESSIONS, STATE, STATUS, STOP_MARKER,
                         LocalStore, read_json, remote_checkpoints, write_json)

HERE = os.path.dirname(os.path.abspath(__file__))
SUPERVISOR = os.path.join(HERE, "supervisor.py")
FAKE = os.path.join(HERE, "fake_trainer.py")


def run_config(root: str, machine: str, store_dir: str, fake_cfg: str, **over) -> str:
    """Write a run.json for one simulated machine and return its path."""
    mdir = os.path.join(root, machine)
    os.makedirs(mdir, exist_ok=True)
    cfg = {
        "run": "local-test",
        "store": store_dir,
        "trainer": [sys.executable, FAKE],
        "config": fake_cfg,
        "checkpoint_dir": os.path.join(mdir, "checkpoints"),
        "work_dir": mdir,
        "checkpoint_pattern": "*.ckpt",
        "keep_checkpoints": 3,
        "settle_seconds": 0.2,
        "scan_seconds": 0.1,
        "status_seconds": 0.3,
        "control_seconds": 0.3,
        "budget_usd": 100.0,
        "machine_per_hour": 2.0461,
        "ip_per_hour": 0.005,
        "disk_per_hour": 0.02,
        "crash_backoff_seconds": 0.2,
        "stop_grace_seconds": 30.0,
        "final_upload_seconds": 30.0,
        "power_off": [sys.executable, "-c",
                      "import sys; open(sys.argv[1], 'a').write('off\\n')",
                      os.path.join(mdir, "powered-off")],
        "instance": machine,
        "zone": "local",
        "machine_type": "fake",
        "provisioning": "SPOT",
    }
    cfg.update(over)
    path = os.path.join(mdir, "run.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    return path


def start_supervisor(run_json: str, log_path: str) -> subprocess.Popen:
    log = open(log_path, "ab")
    # A session of its own, so one killpg reaches the supervisor and the trainer together,
    # like systemd's control-group kill.
    return subprocess.Popen([sys.executable, SUPERVISOR, "--run-config", run_json],
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def wait_for(cond, timeout: float, what: str, poll: float = 0.05):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(poll)
    raise TimeoutError(f"timed out waiting for {what}")


def trainer_events(machine_dir: str) -> list[dict]:
    events = []
    logs = os.path.join(machine_dir, "logs")
    for fn in sorted(os.listdir(logs)) if os.path.isdir(logs) else []:
        if fn.startswith("trainer-"):
            with open(os.path.join(logs, fn), encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            events.append(json.loads(line))
                        except ValueError:
                            pass
    return events


def checkpoint_iteration(store: LocalStore, obj: str) -> int:
    with open(store.url(obj), "rb") as f:
        return int(fake_trainer.decode(f.read())["iteration"])


def run(root: str, iterations: int = 400, say=print) -> dict:
    """Run the scenario in ``root`` and return what was checked. Raises AssertionError if a
    check fails."""
    store_dir = os.path.join(root, "bucket", "runs", "local-test")
    store = LocalStore(store_dir)
    fake_cfg = os.path.join(root, "fake.json")
    with open(fake_cfg, "w", encoding="utf-8") as f:
        json.dump({"iterations": iterations, "iteration_seconds": 0.01,
                   "checkpoint_seconds": 0.3, "checkpoint_bytes": 64 * 1024,
                   "save_seconds": 0.05}, f)
    half = iterations // 2
    out = {}

    say("machine 1: fresh start")
    m1 = os.path.join(root, "machine-1")
    p1 = start_supervisor(run_config(root, "machine-1", store_dir, fake_cfg),
                          os.path.join(root, "machine-1.supervisor.out"))

    def halfway():
        st = read_json(store, STATUS)
        it = st and st["progress"].get("iterations")
        return it is not None and it >= half and remote_checkpoints(store)

    wait_for(halfway, 60, "machine 1 to get halfway with a checkpoint in the bucket")
    say(f"machine 1: at iteration {read_json(store, STATUS)['progress']['iterations']}, "
        f"sending SIGTERM to every process (Google stops the machine)")
    os.killpg(p1.pid, signal.SIGTERM)
    rc1 = p1.wait(timeout=60)
    assert rc1 == 0, f"supervisor 1 exited with {rc1}"
    assert read_json(store, STATE) is None, "a stopped machine must not end the run"
    st1 = read_json(store, STATUS)
    assert st1["stop_reason"] == "shutdown", st1["stop_reason"]
    saved = [e for e in trainer_events(m1) if e.get("event") == "saved on SIGTERM"]
    assert saved, "trainer 1 did not save on SIGTERM"
    saved_at = int(saved[-1]["iterations"])
    remote = remote_checkpoints(store)
    newest = max(remote, key=lambda c: c.seq)
    in_bucket = checkpoint_iteration(store, newest.object)
    assert in_bucket == saved_at, (
        f"the bucket's newest checkpoint is at iteration {in_bucket}, the SIGTERM save at "
        f"{saved_at}: the last save was not uploaded")
    assert 1 <= len(remote) <= 3, f"{len(remote)} checkpoints in the bucket"
    assert not os.path.exists(os.path.join(m1, "powered-off")), \
        "machine 1 powered itself off on a plain shutdown"
    say(f"machine 1: trainer saved at iteration {saved_at}, uploaded as {newest.object}; "
        f"{len(remote)} checkpoint(s) in the bucket")
    out["stopped_at"] = saved_at

    say("machine 2: new machine, empty disk")
    m2 = os.path.join(root, "machine-2")
    p2 = start_supervisor(run_config(root, "machine-2", store_dir, fake_cfg),
                          os.path.join(root, "machine-2.supervisor.out"))
    rc2 = p2.wait(timeout=120)
    assert rc2 == 0, f"supervisor 2 exited with {rc2}"
    events = trainer_events(m2)
    resumed = [e for e in events if e.get("event") == "resumed"]
    assert resumed, "trainer 2 did not resume (it started fresh)"
    assert int(resumed[0]["iterations"]) == saved_at, (
        f"trainer 2 resumed at {resumed[0]['iterations']}, not at {saved_at}")
    done = [e for e in events if e.get("event") == "done"]
    assert done, "trainer 2 did not finish"
    want = fake_trainer.expected_digest(iterations)
    assert done[-1]["digest"] == want, "the resumed run did different work from an " \
                                       "uninterrupted one"
    state = read_json(store, STATE)
    assert state and state["state"] == "done", state
    remote = remote_checkpoints(store)
    assert len(remote) == 3, f"{len(remote)} checkpoints kept, not 3"
    assert checkpoint_iteration(store, max(remote, key=lambda c: c.seq).object) == iterations
    sessions = store.list(SESSIONS)
    assert len(sessions) == 2, f"{len(sessions)} sessions recorded"
    assert os.path.exists(os.path.join(m2, "powered-off")), "machine 2 did not power off"
    st2 = read_json(store, STATUS)
    say(f"machine 2: resumed at iteration {saved_at}, finished at {iterations}; the hash "
        f"matches an uninterrupted run")
    say(f"bucket: {len(remote)} checkpoints kept "
        f"({', '.join(c.object[len(CHECKPOINTS):] for c in remote)})")
    say(f"cost recorded over {st2['cost']['sessions']} sessions: "
        f"${st2['cost']['total_usd']:.6f} (seconds at Spot prices)")
    say("state: done; machine 2 powered off")
    out.update(resumed_at=int(resumed[0]["iterations"]), digest=done[-1]["digest"],
               kept=[c.object for c in remote], sessions=len(sessions), state=state["state"],
               cost=st2["cost"])
    return out


# --- a dress rehearsal with a real trainer ---------------------------------------------------------

def local_config(config: str, files: list[str], dest: str) -> tuple[str, list[str]]:
    """Copy ``config`` to ``dest`` with every string under VM_FILES/<name> pointed at the local
    path of ``files`` called <name>. Returns the new path and what was changed."""
    local = {os.path.basename(f.rstrip(os.sep)): os.path.abspath(os.path.expanduser(f))
             for f in files}
    with open(config, encoding="utf-8") as f:
        data = json.load(f)
    changed = []

    def fix(x):
        if isinstance(x, dict):
            return {k: fix(v) for k, v in x.items()}
        if isinstance(x, list):
            return [fix(v) for v in x]
        if isinstance(x, str) and x.startswith(VM_FILES + "/"):
            name, _, rest = x[len(VM_FILES) + 1:].partition("/")
            if name not in local:
                raise SystemExit(f"{config} names {x}: give its local copy with --files")
            new = local[name] + ("/" + rest if rest else "")
            changed.append(f"{x} -> {new}")
            return new
        return x
    data = fix(data)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return dest, changed


def stage_lines(store: LocalStore) -> list[dict]:
    data = store.get_bytes(ARTIFACTS + "stages.jsonl") or b""
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def artifact_names(store: LocalStore) -> list[str]:
    return sorted(n[len(ARTIFACTS):] for n, _ in store.list(ARTIFACTS))


def run_trainer(root: str, trainer: list[str], config: str, files: list[str] | None = None,
                trainer_args: list[str] | None = None, sigterm_after: int = 2,
                stop_after: int = 4, timeout_minutes: float = 60.0,
                patterns: tuple = ("*.bps", "*.jsonl"), say=print) -> dict:
    """The dress rehearsal (see the module docstring). Raises AssertionError if a check
    fails; returns what was measured."""
    assert 1 <= sigterm_after < stop_after, "need 1 <= --sigterm-after < --stop-after"
    t0 = time.time()
    limit = timeout_minutes * 60.0
    store_dir = os.path.join(root, "bucket", "runs", "local-test")
    store = LocalStore(store_dir)
    cfg, changed = local_config(config, files or [], os.path.join(root, "config",
                                                                  os.path.basename(config)))
    for c in changed:
        say(f"config: {c}")
    over = dict(trainer=list(trainer), trainer_args=list(trainer_args or []),
                artifact_patterns=list(patterns), machine_type="local", status_seconds=5.0,
                control_seconds=2.0, settle_seconds=2.0, scan_seconds=1.0,
                stop_grace_seconds=900.0, final_upload_seconds=900.0)
    out = {"config": config, "rewritten": changed, "trainer_args": list(trainer_args or [])}

    def left():
        return max(1.0, limit - (time.time() - t0))

    def stages_in_bucket(n):
        def cond():
            lines = stage_lines(store)
            if len(lines) < n:
                return None
            names = artifact_names(store)
            want = [ln.get("strategy") for ln in lines[:n] if ln.get("strategy")]
            return lines if all(w in names for w in want) else None
        return cond

    say(f"machine 1: fresh start ({' '.join(trainer + list(trainer_args or []))})")
    m1 = os.path.join(root, "machine-1")
    t1 = time.time()
    p1 = start_supervisor(run_config(root, "machine-1", store_dir, cfg, **over),
                          os.path.join(root, "machine-1.supervisor.out"))
    try:
        lines = wait_for(stages_in_bucket(sigterm_after), left(),
                         f"machine 1 to get {sigterm_after} stage(s) into the bucket", poll=1.0)
    except BaseException:
        os.killpg(p1.pid, signal.SIGKILL)
        raise
    st = read_json(store, STATUS) or {}
    at = (st.get("progress") or {}).get("iterations")
    say(f"machine 1: {len(lines)} stage(s) in the bucket ({lines[-1]['iterations']:,} "
        f"iterations), trainer at {at:,}; SIGTERM to every process (Google stops the machine)")
    sig_at = time.time()
    os.killpg(p1.pid, signal.SIGTERM)
    rc1 = p1.wait(timeout=left())
    out["machine1_stop_seconds"] = round(time.time() - sig_at, 1)
    assert rc1 == 0, f"supervisor 1 exited with {rc1}"
    assert read_json(store, STATE) is None, "a stopped machine must not end the run"
    ev1 = trainer_events(m1)
    saved = [e for e in ev1 if e.get("event") == "saved on SIGTERM"]
    assert saved, "trainer 1 did not save on SIGTERM"
    saved_at = int(saved[-1]["iterations"])
    st1 = read_json(store, STATUS)
    assert st1["stop_reason"] == "shutdown", st1["stop_reason"]
    assert (st1["trainer"] or {}).get("exit_code") == 75, st1["trainer"]
    remote = remote_checkpoints(store)
    assert remote, "no checkpoint in the bucket"
    out.update(machine1_seconds=round(sig_at - t1, 1), stopped_at=saved_at,
               machine1_rates=[e["iterations_per_second"] for e in ev1
                               if e.get("iterations_per_second")],
               machine1_save_seconds=max([e.get("save_seconds") or 0 for e in ev1] or [0]),
               machine1_memory=st1.get("memory"),
               checkpoint_bytes=max(c.size for c in remote))
    say(f"machine 1: trainer saved at iteration {saved_at:,} and exited 75; stopped "
        f"{out['machine1_stop_seconds']} s after SIGTERM; {len(remote)} checkpoint(s) and "
        f"{len(artifact_names(store))} artifact(s) in the bucket")

    say("machine 2: new machine, empty disk")
    m2 = os.path.join(root, "machine-2")
    t2 = time.time()
    p2 = start_supervisor(run_config(root, "machine-2", store_dir, cfg, **over),
                          os.path.join(root, "machine-2.supervisor.out"))
    try:
        resumed = wait_for(lambda: [e for e in trainer_events(m2) if e.get("event") == "resumed"]
                           or None, left(), "trainer 2 to resume", poll=1.0)
        out["machine2_resume_seconds"] = round(time.time() - t2, 1)
        assert int(resumed[0]["iterations"]) == saved_at, (
            f"trainer 2 resumed at {resumed[0]['iterations']}, not at {saved_at}")
        say(f"machine 2: checkpoint and artifacts put back, trainer resumed at "
            f"{saved_at:,} after {out['machine2_resume_seconds']} s")
        lines = wait_for(stages_in_bucket(stop_after), left(),
                         f"{stop_after} stages in the bucket", poll=1.0)
    except BaseException:
        os.killpg(p2.pid, signal.SIGKILL)
        raise
    say(f"machine 2: {len(lines)} stages in the bucket; writing the stop marker "
        f"(python -m tools.cloud stop)")
    stop_at = time.time()
    write_json(store, STOP_MARKER, {"requested_at": stop_at})
    rc2 = p2.wait(timeout=left())
    out["machine2_stop_seconds"] = round(time.time() - stop_at, 1)
    assert rc2 == 0, f"supervisor 2 exited with {rc2}"
    state = read_json(store, STATE)
    assert state and state["state"] == "stopped", state
    ev2 = trainer_events(m2)
    saved2 = [e for e in ev2 if e.get("event") == "saved on SIGTERM"]
    assert saved2, "trainer 2 did not save at the stop"
    st2 = read_json(store, STATUS)
    ck = st2.get("checkpoints") or {}
    assert ck.get("last_uploaded_at") and ck["last_uploaded_at"] >= stop_at, \
        "the save at the stop was not uploaded"
    art = st2.get("artifacts") or {}
    assert art.get("restored", 0) >= sigterm_after, f"artifacts put back: {art}"
    # Every stage once, in order; the first after the resume compared with the one before.
    its = [ln["iterations"] for ln in lines]
    assert its == sorted(set(its)), f"stages out of order or twice: {its}"
    after = [ln for ln in lines if ln["iterations"] > saved_at]
    assert after, "no stage after the resume"
    k = lines.index(after[0])
    if "change_from" in after[0]:
        assert after[0]["change_from"] == lines[k - 1].get("strategy"), after[0]
        assert 0.0 < float(after[0]["change"]) < 1.0, after[0]
    if "previous_on_disk" in after[0]:
        assert after[0]["previous_on_disk"] is True, after[0]
    for ln in lines:
        if ln.get("strategy"):
            assert ln["strategy"] in artifact_names(store), ln["strategy"]
    sessions = store.list(SESSIONS)
    assert len(sessions) == 2, f"{len(sessions)} sessions recorded"
    out.update(resumed_at=int(resumed[0]["iterations"]), stopped_again_at=int(
        saved2[-1]["iterations"]), stages=lines, state=state["state"],
        machine2_rates=[e["iterations_per_second"] for e in ev2
                        if e.get("iterations_per_second")],
        machine2_save_seconds=max([e.get("save_seconds") or 0 for e in ev2] or [0]),
        machine2_memory=st2.get("memory"), artifacts=st2.get("artifacts"),
        checkpoints=[c.object for c in remote_checkpoints(store)],
        bucket_bytes=sum(size for _, size in store.list("")),
        seconds=round(time.time() - t0, 1), cost=st2.get("cost"))
    say(f"machine 2: stopped {out['machine2_stop_seconds']} s after the marker, saved at "
        f"{out['stopped_again_at']:,}; state stopped")
    say(f"stages: {', '.join(f'{x:,}' for x in its)}; the first after the resume was "
        f"compared with {lines[k - 1].get('strategy', 'the one before')}")
    peaks = [(m or {}).get("session_trainer_peak_bytes") for m in (st1.get("memory"),
                                                                   st2.get("memory"))]
    out["trainer_peak_bytes"] = max([p for p in peaks if p] or [0]) or None
    if out["trainer_peak_bytes"]:
        say(f"trainer memory: peak {out['trainer_peak_bytes'] / 1e9:.2f} GB")
    say(f"bucket: {out['bucket_bytes'] / 1e9:.2f} GB; whole rehearsal {out['seconds'] / 60:.1f} "
        f"min")
    return out


def main(keep: str | None = None, trainer: str | None = None, config: str | None = None,
         files: list[str] | None = None, trainer_args: str = "", sigterm_after: int = 2,
         stop_after: int = 4, timeout_minutes: float = 60.0, report: str | None = None) -> int:
    if trainer or config:
        if not (trainer and config):
            print("--trainer and --config go together", file=sys.stderr)
            return 2
        root = keep or tempfile.mkdtemp(prefix="pscloud-rehearsal-")
        os.makedirs(root, exist_ok=True)
        cmd = shlex.split(trainer)
        if os.path.exists(cmd[0]):
            cmd[0] = os.path.abspath(cmd[0])
        try:
            out = run_trainer(root, cmd, os.path.abspath(config), files=files,
                              trainer_args=shlex.split(trainer_args),
                              sigterm_after=sigterm_after, stop_after=stop_after,
                              timeout_minutes=timeout_minutes)
        finally:
            if not keep:
                shutil.rmtree(root, ignore_errors=True)
        if report:
            with open(report, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1)
        print("rehearsal passed" + (f"; files kept in {root}" if keep else ""))
        return 0
    if keep:
        os.makedirs(keep, exist_ok=True)
        root = keep
        run(root)
        print(f"files kept in {root}")
        return 0
    with tempfile.TemporaryDirectory(prefix="pscloud-local-test-") as root:
        run(root)
    print("local test passed")
    return 0
